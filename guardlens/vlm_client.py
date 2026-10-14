"""Shared vision-language client used by every agent, rule and chat endpoint.

One place owns provider selection, budgets, caching and failure handling, so the rest of the
app never talks to a model API directly. All built-in providers speak the OpenAI-compatible
chat-completions protocol (NVIDIA NIM, Google Gemini, OpenRouter, a local Ollama), so adding
another is configuration, not code. Free tiers are the default; every provider is inert until
its API key (or, for Ollama, its URL) is set in the environment.

Safety properties:
- Cloud calls are budgeted (global per-minute and per-day, plus per-camera per-hour).
- A provider that keeps failing is skipped for a cool-down (circuit breaker) and the next one
  in the chain is tried, so a 503 from one free tier does not take agents down.
- A camera marked "local only" may use only providers flagged ``local`` (frames never leave).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional, Sequence

import cv2
import numpy as np

logger = logging.getLogger("guardlens.vlm")


class VlmUnavailable(Exception):
    """No provider could answer (no key, over budget, all failing, or privacy-blocked)."""

    def __init__(self, reason: str, kind: str = "unavailable"):
        super().__init__(reason)
        self.reason, self.kind = reason, kind


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    key_env: str = ""
    model_env: str = ""
    default_model: str = ""
    local: bool = False
    # For local servers the "key" is optional; availability is decided by url_env instead.
    url_env: str = ""
    label: str = ""

    def resolved_base(self) -> str:
        return (os.environ.get(self.url_env) if self.url_env else None) or self.base_url

    def key(self) -> str:
        return os.environ.get(self.key_env, "") if self.key_env else ""

    def model(self) -> str:
        return (os.environ.get(self.model_env) if self.model_env else None) or self.default_model

    @property
    def available(self) -> bool:
        if self.url_env:
            return bool(os.environ.get(self.url_env))
        return bool(self.key())


# Order = default fallback chain. NVIDIA first because it is what GuardLens already used.
DEFAULT_PROVIDERS: list[ProviderSpec] = [
    ProviderSpec("nvidia", "https://integrate.api.nvidia.com/v1", "GUARDLENS_NVIDIA_API_KEY",
                 "GUARDLENS_VLM_MODEL", "meta/llama-3.2-11b-vision-instruct", label="NVIDIA NIM (free tier)"),
    ProviderSpec("gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GUARDLENS_GEMINI_API_KEY",
                 "GUARDLENS_GEMINI_MODEL", "gemini-2.5-flash", label="Google Gemini (free tier)"),
    ProviderSpec("openrouter", "https://openrouter.ai/api/v1", "GUARDLENS_OPENROUTER_API_KEY",
                 "GUARDLENS_OPENROUTER_MODEL", "meta-llama/llama-3.2-11b-vision-instruct:free",
                 label="OpenRouter (free models)"),
    ProviderSpec("ollama", "http://localhost:11434/v1", "", "GUARDLENS_OLLAMA_MODEL", "qwen3-vl:2b",
                 local=True, url_env="GUARDLENS_OLLAMA_URL", label="Local Ollama"),
]


@dataclass
class VlmResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    cached: bool = False


@dataclass
class _Breaker:
    failures: int = 0
    open_until: float = 0.0


@dataclass
class _Budget:
    per_minute: int = 20
    per_day: int = 2000
    per_camera_hour: int = 60
    minute: deque = field(default_factory=deque)
    camera_hour: dict = field(default_factory=lambda: defaultdict(deque))
    day: str = ""
    day_count: int = 0

    def _trim(self, now: float) -> None:
        while self.minute and now - self.minute[0] > 60:
            self.minute.popleft()
        for q in self.camera_hour.values():
            while q and now - q[0] > 3600:
                q.popleft()
        today = date.today().isoformat()
        if today != self.day:
            self.day, self.day_count = today, 0

    def check(self, camera_id: Optional[int], now: float) -> None:
        self._trim(now)
        if len(self.minute) >= self.per_minute:
            raise VlmUnavailable("per-minute AI call limit reached", "budget")
        if self.day_count >= self.per_day:
            raise VlmUnavailable("daily AI call limit reached", "budget")
        if camera_id is not None and len(self.camera_hour[camera_id]) >= self.per_camera_hour:
            raise VlmUnavailable("this camera reached its hourly AI call limit", "budget")

    def record(self, camera_id: Optional[int], now: float) -> None:
        self.minute.append(now)
        self.day_count += 1
        if camera_id is not None:
            self.camera_hour[camera_id].append(now)


def tile_images(frames: Sequence[np.ndarray], max_side: int = 1024) -> np.ndarray:
    """Combine several frames into one grid image (most free VLMs accept a single image)."""
    if len(frames) == 1:
        return frames[0]
    cols = 2 if len(frames) <= 4 else 3
    rows = -(-len(frames) // cols)
    cell_w = max_side // cols
    cell_h = int(cell_w * 9 / 16)
    canvas = np.zeros((rows * cell_h, cols * cell_w, 3), dtype=np.uint8)
    for i, frame in enumerate(frames):
        small = cv2.resize(frame, (cell_w, cell_h))
        cv2.putText(small, str(i + 1), (8, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)
        r, c = divmod(i, cols)
        canvas[r * cell_h:(r + 1) * cell_h, c * cell_w:(c + 1) * cell_w] = small
    return canvas


def _encode(frame: np.ndarray, max_side: int = 1024) -> bytes:
    h, w = frame.shape[:2]
    scale = max_side / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise VlmUnavailable("could not encode the image", "error")
    return buf.tobytes()


_SSE_DONE = object()


def _sse_delta(raw) -> object:
    """The text carried by one server-sent-events line of an OpenAI-style stream; _SSE_DONE at the end, else None."""
    line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    if not line.startswith("data:"):
        return None
    body = line[5:].strip()
    if body == "[DONE]":
        return _SSE_DONE
    try:
        choices = json.loads(body).get("choices") or []
        return ((choices[0].get("delta") or {}).get("content") or None) if choices else None
    except (ValueError, AttributeError):
        return None


class VlmClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._providers = list(DEFAULT_PROVIDERS)
        self._chain: list[str] = [p.name for p in self._providers]
        self._breakers: dict[str, _Breaker] = defaultdict(_Breaker)
        self._budget = _Budget()
        self._cache: dict[str, tuple[float, VlmResult]] = {}
        self._cache_seconds = 300.0
        self._breaker_failures = 3
        self._breaker_cooldown = 60.0
        self._local_only: set[int] = set()
        self._stats: dict[str, Any] = {"calls": 0, "cached": 0, "failures": 0, "by_provider": defaultdict(int)}
        # Replaceable in tests: (url, headers, json, timeout) -> response-like object.
        self._post: Callable[..., Any] = self._http_post
        self._stream: Callable[..., Any] = self._http_stream

    # -- configuration -------------------------------------------------
    def configure(self, cfg: Optional[dict] = None) -> None:
        cfg = cfg or {}
        with self._lock:
            by_name = {p.name: p for p in DEFAULT_PROVIDERS}
            for custom in cfg.get("providers", []):
                by_name[custom["name"]] = ProviderSpec(**custom)
            self._providers = list(by_name.values())
            self._chain = cfg.get("chain") or [p.name for p in self._providers]
            budget = cfg.get("budget", {})
            self._budget.per_minute = int(budget.get("per_minute", 20))
            self._budget.per_day = int(budget.get("per_day", 2000))
            self._budget.per_camera_hour = int(budget.get("per_camera_hour", 60))
            self._cache_seconds = float(cfg.get("cache_seconds", 300))
            self._breaker_failures = int(cfg.get("breaker_failures", 3))
            self._breaker_cooldown = float(cfg.get("breaker_cooldown_seconds", 60))

    def set_local_only(self, camera_ids: Sequence[int]) -> None:
        with self._lock:
            self._local_only = {int(c) for c in camera_ids}

    def local_only(self) -> list[int]:
        return sorted(self._local_only)

    # -- introspection -------------------------------------------------
    def _ordered(self) -> list[ProviderSpec]:
        by_name = {p.name: p for p in self._providers}
        return [by_name[n] for n in self._chain if n in by_name]

    @property
    def available(self) -> bool:
        return any(p.available for p in self._ordered())

    def available_for(self, camera_id: Optional[int]) -> bool:
        return any(p.available and self._allowed(p, camera_id) for p in self._ordered())

    def _allowed(self, provider: ProviderSpec, camera_id: Optional[int]) -> bool:
        return provider.local or camera_id is None or camera_id not in self._local_only

    def status(self) -> dict:
        now = time.time()
        with self._lock:
            self._budget._trim(now)
            return {
                "available": self.available,
                "providers": [
                    {
                        "name": p.name, "label": p.label or p.name, "model": p.model(), "local": p.local,
                        "key_env": p.url_env or p.key_env,
                        "configured": p.available,
                        "paused": self._breakers[p.name].open_until > now,
                    }
                    for p in self._ordered()
                ],
                "budget": {
                    "per_minute": self._budget.per_minute, "used_last_minute": len(self._budget.minute),
                    "per_day": self._budget.per_day, "used_today": self._budget.day_count,
                    "per_camera_hour": self._budget.per_camera_hour,
                },
                "local_only_cameras": sorted(self._local_only),
                "stats": {**{k: v for k, v in self._stats.items() if k != "by_provider"},
                          "by_provider": dict(self._stats["by_provider"])},
            }

    # -- calling -------------------------------------------------------
    @staticmethod
    def _http_post(url: str, headers: dict, payload: dict, timeout: float):
        import requests
        return requests.post(url, headers=headers, json=payload, timeout=timeout)

    def _candidates(self, camera_id: Optional[int], now: float) -> list[ProviderSpec]:
        """Providers allowed to see this camera; raises VlmUnavailable when none can, or the budget is spent."""
        candidates = [p for p in self._ordered() if p.available and self._allowed(p, camera_id)]
        if not candidates:
            private = any(p.available for p in self._ordered())
            raise VlmUnavailable(
                "this camera is set to keep video on this device and no local AI model is set up"
                if private else "no AI provider is configured", "privacy" if private else "unconfigured")
        with self._lock:
            self._budget.check(camera_id, now)
        return candidates

    @staticmethod
    def _messages(prompt: str, image_bytes: bytes, system: Optional[str], history: Optional[Sequence[dict]]) -> list[dict]:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.extend(history or [])
        content: list[dict] = [{"type": "text", "text": prompt}]
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        messages.append({"role": "user", "content": content})
        return messages

    def _record_success(self, provider: ProviderSpec, camera_id: Optional[int]) -> None:
        with self._lock:
            self._breakers[provider.name].failures = 0
            self._budget.record(camera_id, time.time())
            self._stats["calls"] += 1
            self._stats["by_provider"][provider.name] += 1

    def _record_failure(self, provider: ProviderSpec, trips: bool) -> None:
        breaker = self._breakers[provider.name]
        with self._lock:
            self._stats["failures"] += 1
            if trips:
                breaker.failures += 1
                if breaker.failures >= self._breaker_failures:
                    breaker.open_until = time.time() + self._breaker_cooldown
                    breaker.failures = 0
                    logger.warning("VLM provider %s paused for %ss", provider.name, self._breaker_cooldown)

    @staticmethod
    def _http_stream(url: str, headers: dict, payload: dict, timeout: float):
        import requests
        return requests.post(url, headers=headers, json=payload, timeout=timeout, stream=True)

    def ask_stream(
        self,
        images: Sequence[np.ndarray] | np.ndarray | None,
        prompt: str,
        *,
        camera_id: Optional[int] = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        system: Optional[str] = None,
        history: Optional[Sequence[dict]] = None,
        timeout: float = 40.0,
    ):
        """Like ask(), but yields {"type": "delta", "text"} as words arrive, then {"type": "done", "result": VlmResult}.

        Falls back to the next provider only before the first word arrives. If a provider breaks mid-answer the words
        received so far are kept (the final text ends with an ellipsis). Raises VlmUnavailable when nothing answers.
        """
        frames: list[np.ndarray] = []
        if images is not None:
            frames = [images] if isinstance(images, np.ndarray) else list(images)
        image_bytes = _encode(tile_images(frames)) if frames else b""
        candidates = self._candidates(camera_id, time.time())
        messages = self._messages(prompt, image_bytes, system, history)
        errors: list[str] = []
        for provider in candidates:
            if self._breakers[provider.name].open_until > time.time():
                errors.append(f"{provider.name}: paused after repeated failures")
                continue
            payload = {"model": provider.model(), "messages": messages, "max_tokens": max_tokens,
                       "temperature": temperature, "stream": True}
            headers = {"Accept": "text/event-stream"}
            if provider.key():
                headers["Authorization"] = f"Bearer {provider.key()}"
            started, parts, trips, response = time.time(), [], True, None
            try:
                response = self._stream(provider.resolved_base().rstrip("/") + "/chat/completions", headers, payload, timeout)
                if response.status_code != 200:
                    errors.append(f"{provider.name}: HTTP {response.status_code}")
                    trips = response.status_code in (408, 429) or response.status_code >= 500
                else:
                    for raw in response.iter_lines():
                        delta = _sse_delta(raw)
                        if delta is _SSE_DONE:
                            break
                        if delta:
                            parts.append(delta)
                            yield {"type": "delta", "text": delta}
                    text = "".join(parts).strip()
                    if not text:
                        raise ValueError("empty answer")
                    self._record_success(provider, camera_id)
                    yield {"type": "done", "result": VlmResult(text, provider.name, payload["model"], int((time.time() - started) * 1000))}
                    return
            except GeneratorExit:
                raise
            except Exception as exc:
                errors.append(f"{provider.name}: {type(exc).__name__}")
                if parts:  # the answer broke off: keep the words that did arrive
                    self._record_failure(provider, True)
                    yield {"type": "done", "result": VlmResult("".join(parts).strip() + " …", provider.name, payload["model"],
                                                                int((time.time() - started) * 1000))}
                    return
            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass
            self._record_failure(provider, trips)
        raise VlmUnavailable("; ".join(errors) or "no provider answered", "failed")

    def ask(
        self,
        images: Sequence[np.ndarray] | np.ndarray | None,
        prompt: str,
        *,
        camera_id: Optional[int] = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
        system: Optional[str] = None,
        history: Optional[Sequence[dict]] = None,
        cache: bool = False,
        timeout: float = 40.0,
    ) -> VlmResult:
        """Ask a question about image(s). Raises VlmUnavailable if no provider can answer."""
        frames: list[np.ndarray] = []
        if images is not None:
            frames = [images] if isinstance(images, np.ndarray) else list(images)
        image_bytes = _encode(tile_images(frames)) if frames else b""
        cache_key = ""
        now = time.time()
        if cache:
            cache_key = hashlib.sha1(image_bytes + prompt.encode()).hexdigest()
            with self._lock:
                hit = self._cache.get(cache_key)
            if hit and hit[0] > now:
                with self._lock:
                    self._stats["cached"] += 1
                return VlmResult(hit[1].text, hit[1].provider, hit[1].model, 0, cached=True)

        candidates = self._candidates(camera_id, now)
        messages = self._messages(prompt, image_bytes, system, history)

        errors: list[str] = []
        for provider in candidates:
            breaker = self._breakers[provider.name]
            if breaker.open_until > time.time():
                errors.append(f"{provider.name}: paused after repeated failures")
                continue
            payload = {"model": provider.model(), "messages": messages, "max_tokens": max_tokens,
                       "temperature": temperature, "stream": False}
            headers = {"Accept": "application/json"}
            if provider.key():
                headers["Authorization"] = f"Bearer {provider.key()}"
            started = time.time()
            try:
                response = self._post(provider.resolved_base().rstrip("/") + "/chat/completions", headers, payload, timeout)
                if response.status_code == 200:
                    text = (response.json()["choices"][0]["message"].get("content") or "").strip()
                    if not text:
                        raise ValueError("empty answer")
                    result = VlmResult(text, provider.name, payload["model"], int((time.time() - started) * 1000))
                    self._record_success(provider, camera_id)
                    if cache_key:
                        with self._lock:
                            self._cache[cache_key] = (time.time() + self._cache_seconds, result)
                            if len(self._cache) > 200:
                                self._cache.pop(next(iter(self._cache)))
                    return result
                errors.append(f"{provider.name}: HTTP {response.status_code}")
                trips = response.status_code in (408, 429) or response.status_code >= 500
            except Exception as exc:  # network errors, bad JSON, empty answers
                errors.append(f"{provider.name}: {type(exc).__name__}")
                trips = True
            self._record_failure(provider, trips)
        raise VlmUnavailable("; ".join(errors) or "no provider answered", "failed")


vlm_client = VlmClient()
