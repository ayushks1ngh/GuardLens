"""Background vision-language analyzer: asks a VLM about trigger frames off the
analysis loop, so slow cloud calls never block detection.

Used by the `vlm_watch` rule. Opt-in and inert unless GUARDLENS_NVIDIA_API_KEY is set.
Transmits trigger frames to an external vision API — a deliberate privacy tradeoff.
"""
from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("guardlens.vlm")

_INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_MODEL = os.environ.get("GUARDLENS_VLM_MODEL", "meta/llama-3.2-11b-vision-instruct")


class VlmWatcher:
    """One in-flight request per camera, debounced; persists an event on a hit."""

    def __init__(self) -> None:
        self._busy: dict[int, bool] = {}
        self._last_run: dict[int, float] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(os.environ.get("GUARDLENS_NVIDIA_API_KEY"))

    def submit(self, camera_id: int, frame: np.ndarray, prompt: str,
               keywords: list[str], severity: str, cooldown: float) -> None:
        if not self.available or frame is None:
            return
        now = time.time()
        with self._lock:
            if self._busy.get(camera_id):
                return
            if now - self._last_run.get(camera_id, 0.0) < cooldown:
                return
            self._busy[camera_id] = True
            self._last_run[camera_id] = now
        t = threading.Thread(
            target=self._run, args=(camera_id, frame.copy(), prompt, keywords, severity),
            name=f"vlm-{camera_id}", daemon=True,
        )
        t.start()

    def _run(self, camera_id: int, frame: np.ndarray, prompt: str,
             keywords: list[str], severity: str) -> None:
        try:
            answer = self._ask(frame, prompt)
            if not answer:
                return
            lowered = answer.lower()
            hit = any(k.strip().lower() in lowered for k in keywords if k.strip())
            # Guard against the model simply echoing a negative ("no knife").
            negated = any(p in lowered for p in ("no ", "not ", "none", "no sharp", "nothing"))
            if hit and not negated:
                from guardlens.events.store import event_store
                from guardlens.types import EventDraft
                event_store.persist(camera_id, EventDraft(
                    type="vlm_alert", severity=severity,
                    metadata={"vlm_answer": answer[:500], "matched": [k for k in keywords if k.strip().lower() in lowered]},
                    snapshot=frame,
                ))
                logger.info("[cam %s] vlm_alert: %s", camera_id, answer[:160])
        except Exception:
            logger.exception("[cam %s] VLM watcher failed", camera_id)
        finally:
            with self._lock:
                self._busy[camera_id] = False

    def _ask(self, frame: np.ndarray, prompt: str) -> Optional[str]:
        key = os.environ.get("GUARDLENS_NVIDIA_API_KEY")
        if not key:
            return None
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        if not ok:
            return None
        b64 = base64.b64encode(buf).decode("ascii")
        payload = {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]}],
            "model": _MODEL, "max_tokens": 512, "temperature": 0.2, "top_p": 0.9, "stream": False,
        }
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
        import requests
        for attempt in range(3):
            try:
                r = requests.post(_INVOKE_URL, headers=headers, json=payload, timeout=60)
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"]
                if r.status_code == 503:
                    time.sleep(3 * (attempt + 1)); continue
                return None
            except requests.RequestException:
                time.sleep(2)
        return None


vlm_watcher = VlmWatcher()
