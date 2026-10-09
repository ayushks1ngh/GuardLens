"""Streaming routes: MJPEG video + SSE overlay (see docs/04-api-spec.md)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from guardlens.capture.manager import manager
from guardlens.streaming.stream import mjpeg_generator, overlay_event_stream

router = APIRouter(tags=["stream"])


@router.get("/stream/{camera_id}/mjpeg")
def mjpeg(camera_id: int):
    return StreamingResponse(
        mjpeg_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.get("/api/stream/{camera_id}/overlay")
async def overlay_one(camera_id: int):
    return StreamingResponse(
        overlay_event_stream(camera_id), media_type="text/event-stream"
    )


@router.get("/api/stream/overlay")
async def overlay_all():
    return StreamingResponse(overlay_event_stream(None), media_type="text/event-stream")


@router.get("/api/stream/status")
def stream_status():
    return {"cameras": manager.status()}
