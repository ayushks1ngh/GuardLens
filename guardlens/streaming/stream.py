"""Streaming: MJPEG video + lightweight overlay metadata (see ADR-005).

Heavy pixels go over cheap MJPEG (consumed by a plain <img> tag). Small JSON
overlays (alert flag, counts, boxes) go over SSE. This replaces the original
base64-every-frame-over-WebSocket design.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Optional

import cv2

from guardlens.capture.manager import manager

# ---------------------------------------------------------------------------
# Overlay store: per-camera latest lightweight metadata. Populated by the
# analysis pipeline in Phase 2; in Phase 1 it holds connection/fps only.
# ---------------------------------------------------------------------------


class OverlayStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._data: dict[int, dict] = {}

    def update(self, camera_id: int, payload: dict) -> None:
        with self._lock:
            self._data[camera_id] = {**payload, "ts": time.time()}

    def get(self, camera_id: int) -> dict:
        with self._lock:
            return dict(self._data.get(camera_id, {}))

    def all(self) -> dict[int, dict]:
        with self._lock:
            return {k: dict(v) for k, v in self._data.items()}


overlay_store = OverlayStore()

_JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), 70]


def _encode_jpeg(frame) -> Optional[bytes]:
    ok, buf = cv2.imencode(".jpg", frame, _JPEG_PARAMS)
    if not ok:
        return None
    return buf.tobytes()


def mjpeg_generator(camera_id: int, target_fps: float = 15.0):
    """Yield multipart MJPEG chunks for a camera's latest frames."""
    boundary = b"--frame"
    interval = 1.0 / target_fps if target_fps > 0 else 0.0
    waited = 0.0
    while True:
        worker = manager.get_worker(camera_id)
        if worker is None:
            break
        frame, _ts = worker.get_latest()
        if frame is not None:
            waited = 0.0
            jpeg = _encode_jpeg(frame)
            if jpeg:
                yield (
                    boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
        else:
            # No frame yet (camera connecting). Give up after a while so the
            # response can't block forever if the source never produces frames.
            waited += max(interval, 0.1)
            if waited > 20.0:
                break
        time.sleep(interval if frame is not None else 0.1)


async def overlay_event_stream(camera_id: Optional[int] = None):
    """SSE generator for overlay metadata (all cameras or one)."""
    while True:
        if camera_id is not None:
            payload = {str(camera_id): overlay_store.get(camera_id)}
        else:
            payload = {str(k): v for k, v in overlay_store.all().items()}
        # merge in live connection/fps from the manager
        for s in manager.status():
            key = str(s["camera_id"])
            payload.setdefault(key, {})
            payload[key]["connected"] = s["connected"]
            payload[key]["fps"] = s["fps"]
        yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(0.5)
