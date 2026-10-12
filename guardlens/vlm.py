"""Background vision-language watcher: asks a VLM about trigger frames off the analysis
loop, so slow cloud calls never block detection.

Used by the ``vlm_watch`` rule. Inert unless a provider is configured (see
``guardlens.vlm_client``). Trigger frames leave this device unless the camera is marked
"local only" — a deliberate, opt-in privacy tradeoff.
"""
from __future__ import annotations

import logging
import re
import threading
import time

import numpy as np

from guardlens.vlm_client import VlmUnavailable, vlm_client

logger = logging.getLogger("guardlens.vlm")


def keyword_hits(answer: str, keywords: list[str]) -> list[str]:
    """Keywords present in the answer and not negated right before them ("no knife")."""
    lowered = answer.lower()
    hits = []
    for keyword in (k.strip().lower() for k in keywords if k.strip()):
        for match in re.finditer(re.escape(keyword), lowered):
            before = lowered[max(0, match.start() - 24):match.start()]
            if not re.search(r"\b(no|not|without|none|nothing|isn't|aren't)\b(\W+\w+){0,2}\W*$", before):
                hits.append(keyword)
                break
    return hits


class VlmWatcher:
    """One in-flight request per camera, debounced; persists an event on a hit."""

    def __init__(self) -> None:
        self._busy: dict[int, bool] = {}
        self._last_run: dict[int, float] = {}
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return vlm_client.available

    def submit(self, camera_id: int, frame: np.ndarray, prompt: str,
               keywords: list[str], severity: str, cooldown: float) -> None:
        if frame is None or not vlm_client.available_for(camera_id):
            return
        now = time.time()
        with self._lock:
            if self._busy.get(camera_id):
                return
            if now - self._last_run.get(camera_id, 0.0) < cooldown:
                return
            self._busy[camera_id] = True
            self._last_run[camera_id] = now
        threading.Thread(
            target=self._run, args=(camera_id, frame.copy(), prompt, keywords, severity),
            name=f"vlm-{camera_id}", daemon=True,
        ).start()

    def _run(self, camera_id: int, frame: np.ndarray, prompt: str,
             keywords: list[str], severity: str) -> None:
        try:
            answer = vlm_client.ask(frame, prompt, camera_id=camera_id, max_tokens=256).text
            hits = keyword_hits(answer, keywords)
            if hits:
                from guardlens.events.store import event_store
                from guardlens.types import EventDraft
                event_store.persist(camera_id, EventDraft(
                    type="vlm_alert", severity=severity,
                    metadata={"vlm_answer": answer[:500], "matched": hits}, snapshot=frame,
                ))
                logger.info("[cam %s] vlm_alert: %s", camera_id, answer[:160])
        except VlmUnavailable as exc:
            logger.info("[cam %s] VLM watch skipped: %s", camera_id, exc.reason)
        except Exception:
            logger.exception("[cam %s] VLM watcher failed", camera_id)
        finally:
            with self._lock:
                self._busy[camera_id] = False


vlm_watcher = VlmWatcher()
