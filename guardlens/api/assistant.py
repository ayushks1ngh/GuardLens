"""Ask GuardLens chat API."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
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


@router.delete("/sessions/{session_id}")
def clear_session(session_id: str):
    return {"cleared": assistant.sessions.clear(session_id)}
