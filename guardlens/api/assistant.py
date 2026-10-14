"""Ask GuardLens chat API."""
from __future__ import annotations

import itertools
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from guardlens import assistant
from guardlens.events.store import event_store
from guardlens.vlm_client import VlmUnavailable, vlm_client

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class ChatBody(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    session_id: Optional[str] = Field(default=None, max_length=64)
    camera_id: Optional[int] = None


@router.post("/chat")
def chat(body: ChatBody):
    if not vlm_client.available:
        raise HTTPException(503, "No AI provider is set up yet (see the Agents page).")
    try:
        return assistant.chat(body.question, body.camera_id, body.session_id, event_store._snapshots_dir)
    except VlmUnavailable as exc:
        code = 429 if exc.kind == "budget" else 403 if exc.kind == "privacy" else 502
        raise HTTPException(code, exc.reason) from exc


def _error_status(exc: VlmUnavailable) -> int:
    return 429 if exc.kind == "budget" else 403 if exc.kind == "privacy" else 502


@router.post("/chat/stream")
def chat_stream(body: ChatBody):
    """Server-sent events: `meta` (picture, camera), many `delta` (words), then `done` (final cleaned answer)."""
    if not vlm_client.available:
        raise HTTPException(503, "No AI provider is set up yet (see the Agents page).")
    stream = assistant.chat_stream(body.question, body.camera_id, body.session_id, event_store._snapshots_dir)
    held = []
    try:  # pull until the first word (or the end) so a provider failure is a proper HTTP error, not a broken stream
        for event in stream:
            held.append(event)
            if event["type"] != "meta":
                break
    except VlmUnavailable as exc:
        raise HTTPException(_error_status(exc), exc.reason) from exc

    def frames():
        try:
            for event in itertools.chain(held, stream):
                yield f"event: {event['type']}\ndata: {json.dumps({k: v for k, v in event.items() if k != 'type'})}\n\n"
        except VlmUnavailable as exc:
            yield f"event: error\ndata: {json.dumps({'status': _error_status(exc), 'message': exc.reason})}\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.delete("/sessions/{session_id}")
def clear_session(session_id: str):
    return {"cleared": assistant.sessions.clear(session_id)}
