"""Optional vision-language 'ask about the camera' endpoint (ADR-010 VLM seam).

Sends the latest frame of a camera to a cloud VLM. The API key is read only from
the GUARDLENS_NVIDIA_API_KEY environment variable and never persisted or logged.
This transmits camera frames to an external provider; it is opt-in and off unless
a key is configured.
"""
from __future__ import annotations

import base64
import os
import time

import cv2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from guardlens.capture.manager import manager

router = APIRouter(prefix="/api/vision", tags=["vision"])

_INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
# Lightweight, fast vision model. The heavier reasoning model frequently hit the
# free endpoint's concurrency cap (503) and was ~3x slower.
_MODEL = os.environ.get("GUARDLENS_VLM_MODEL", "meta/llama-3.2-11b-vision-instruct")


class AskBody(BaseModel):
    camera_id: int
    question: str = Field(min_length=1, max_length=1000)


@router.get("/status")
def vision_status():
    return {"available": bool(os.environ.get("GUARDLENS_NVIDIA_API_KEY")), "model": _MODEL}


@router.post("/ask")
def vision_ask(body: AskBody):
    key = os.environ.get("GUARDLENS_NVIDIA_API_KEY")
    if not key:
        raise HTTPException(503, "vision model not configured (set GUARDLENS_NVIDIA_API_KEY)")
    worker = manager.get_worker(body.camera_id)
    if worker is None:
        raise HTTPException(404, "camera is not running")
    frame, _ = worker.get_latest()
    if frame is None:
        raise HTTPException(409, "no frame available from this camera yet")

    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise HTTPException(500, "failed to encode frame")
    b64 = base64.b64encode(buf).decode("ascii")

    payload = {
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": body.question},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
        "model": _MODEL,
        "max_tokens": 1024,
        "temperature": 0.3,
        "top_p": 0.9,
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}

    import requests  # local import keeps the dependency optional at import time
    last_err = "unknown error"
    for attempt in range(2):
        try:
            resp = requests.post(_INVOKE_URL, headers=headers, json=payload, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                answer = data["choices"][0]["message"]["content"]
                return {"answer": answer, "model": _MODEL}
            if resp.status_code == 503:
                last_err = "model busy (free-tier capacity). Try again in a moment."
                time.sleep(2)
                continue
            last_err = f"provider returned {resp.status_code}"
            break
        except requests.RequestException as exc:
            last_err = f"request failed: {exc}"
            time.sleep(1)
    raise HTTPException(502, f"vision model unavailable: {last_err}")
