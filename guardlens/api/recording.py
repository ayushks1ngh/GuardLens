"""Runtime recording settings backed by the flexible Setting JSON table."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlmodel import Session

from guardlens.events import Setting, get_engine
from guardlens.recording import clip_recorder

router = APIRouter(prefix="/api/recording", tags=["recording"])


class RecordingSettings(BaseModel):
    enabled: bool = False
    mode: str = Field(default="event", pattern="^(off|motion|event|continuous)$")
    pre_roll_seconds: float = Field(default=5, ge=0, le=60)
    post_roll_seconds: float = Field(default=10, ge=0, le=300)
    max_clip_seconds: float = Field(default=120, ge=1, le=3600)
    segment_seconds: float = Field(default=300, ge=10, le=3600)
    retention_days: int = Field(default=7, ge=0, le=3650)
    quota_mb: int = Field(default=2048, ge=1)
    codec_preferences: list[str] = Field(default_factory=lambda: ["mp4v", "MJPG"], min_length=1, max_length=4)


def _current() -> RecordingSettings:
    with Session(get_engine()) as session:
        stored = session.get(Setting, "recording")
    return RecordingSettings(**(stored.value if stored else {}))


@router.get("")
def get_recording():
    return {"config": _current().model_dump(), "status": clip_recorder.status()}


@router.patch("")
def update_recording(body: RecordingSettings):
    values = body.model_dump()
    if any(len(codec) != 4 or not codec.isascii() for codec in values["codec_preferences"]):
        from fastapi import HTTPException
        raise HTTPException(422, "each codec must be exactly four ASCII characters")
    with Session(get_engine()) as session:
        stored = session.get(Setting, "recording") or Setting(key="recording")
        stored.value = values
        session.add(stored); session.commit()
    clips_dir = clip_recorder.clips_dir
    clip_recorder.stop_all()
    clip_recorder.configure(clips_dir, values)
    return {"config": values, "status": clip_recorder.status()}
