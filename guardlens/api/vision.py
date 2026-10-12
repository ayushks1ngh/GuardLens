"""Optional vision-language 'ask about the camera' endpoint (ADR-010 VLM seam).

Sends the latest frame of a camera to the configured VLM provider chain
(``guardlens.vlm_client``). Frames leave this device unless the camera is marked
"local only"; the feature is off until a provider key/URL is set in the environment.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from guardlens.capture.manager import manager
from guardlens.vlm_client import VlmUnavailable, vlm_client

router = APIRouter(prefix="/api/vision", tags=["vision"])


class AskBody(BaseModel):
    camera_id: int
    question: str = Field(min_length=1, max_length=1000)


@router.get("/status")
def vision_status():
    status = vlm_client.status()
    first = next((p for p in status["providers"] if p["configured"]), None)
    return {**status, "model": first["model"] if first else None}


@router.post("/ask")
def vision_ask(body: AskBody):
    if not vlm_client.available:
        raise HTTPException(503, "vision model not configured (set a provider key, e.g. GUARDLENS_NVIDIA_API_KEY)")
    worker = manager.get_worker(body.camera_id)
    if worker is None:
        raise HTTPException(404, "camera is not running")
    frame, _ = worker.get_latest()
    if frame is None:
        raise HTTPException(409, "no frame available from this camera yet")
    try:
        result = vlm_client.ask(frame, body.question, camera_id=body.camera_id, max_tokens=1024, temperature=0.3)
    except VlmUnavailable as exc:
        code = 429 if exc.kind == "budget" else 403 if exc.kind == "privacy" else 502
        raise HTTPException(code, f"vision model unavailable: {exc.reason}") from exc
    return {"answer": result.text, "model": result.model, "provider": result.provider}
