"""Streaming routes: MJPEG video + SSE overlay (see docs/04-api-spec.md)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from guardlens.capture.manager import manager
from guardlens.streaming.stream import mjpeg_generator, overlay_event_stream

router = APIRouter(tags=["stream"])


@router.get("/stream/{camera_id}/mjpeg")
def mjpeg(
    camera_id: int,
    max_frames: Optional[int] = Query(default=None, ge=1, le=10),
):
    return StreamingResponse(
        mjpeg_generator(camera_id, max_frames=max_frames),
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


@router.websocket("/ws/overlay")
async def overlay_websocket(websocket: WebSocket):
    """WebSocket fallback for clients that cannot consume SSE."""
    from guardlens import auth
    from guardlens.streaming.stream import overlay_payload

    # The HTTP login middleware never sees WebSocket connections, so check here (browsers send the session cookie).
    if auth.auth_state.enabled and await __import__("asyncio").to_thread(auth.identify, websocket.headers, websocket.cookies) is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            await websocket.send_json(overlay_payload())
            await __import__("asyncio").sleep(0.5)
    except WebSocketDisconnect:
        return


@router.get("/api/stream/status")
def stream_status():
    return {"cameras": manager.status()}
