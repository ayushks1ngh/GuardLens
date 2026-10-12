"""Event history, filtering, workflow, notes, deletion, and live SSE."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from guardlens.events import Event, EventNote, get_engine, utcnow
from guardlens.events.store import event_bus, event_store, event_stream

router = APIRouter(prefix="/api/events", tags=["events"])


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ResolveBody(BaseModel):
    note: Optional[str] = Field(default=None, min_length=1, max_length=2000)


def _event_or_404(session: Session, event_id: int) -> Event:
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(404, "event not found")
    return event


@router.get("")
def list_events(
    camera_id: Optional[int] = None,
    type: Optional[str] = None,
    severity: Optional[str] = None,
    status: Optional[str] = None,
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    conditions = []
    if camera_id is not None:
        conditions.append(Event.camera_id == camera_id)
    if type:
        conditions.append(Event.type == type)
    if severity:
        conditions.append(Event.severity == severity)
    if status:
        conditions.append(Event.status == status)
    if from_:
        conditions.append(Event.created_at >= from_)
    if to:
        conditions.append(Event.created_at <= to)

    with Session(get_engine()) as session:
        total_stmt = select(func.count(Event.id))
        stmt = select(Event)
        for condition in conditions:
            total_stmt = total_stmt.where(condition)
            stmt = stmt.where(condition)
        total = session.exec(total_stmt).one()
        items = session.exec(
            stmt.order_by(Event.created_at.desc()).offset(offset).limit(limit)
        ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/stream")
async def stream_events(last_event_id: Optional[str] = Header(default=None)):
    # A fresh connection only sees *new* events; EventSource sends Last-Event-ID on its own
    # reconnects, which is what triggers replay of anything missed. Without this a page load
    # replayed up to 500 old events (and re-sounded every old critical alarm).
    try:
        last = int(last_event_id) if last_event_id is not None else event_bus.latest_sequence()
    except ValueError:
        last = event_bus.latest_sequence()
    return StreamingResponse(event_stream(last), media_type="text/event-stream")


@router.get("/{event_id}/clip")
def get_event_clip(event_id: int):
    with Session(get_engine()) as session:
        event = _event_or_404(session, event_id)
        if not event.clip_path:
            raise HTTPException(404, "event has no clip")
        from guardlens.recording import clip_recorder
        path = clip_recorder.clips_dir / Path(event.clip_path).name
        if not path.is_file():
            raise HTTPException(404, "event clip file is unavailable")
        media_type = "video/mp4" if path.suffix.lower() == ".mp4" else "video/x-msvideo"
        return FileResponse(path, media_type=media_type, filename=path.name)


@router.get("/{event_id}")
def get_event(event_id: int):
    with Session(get_engine()) as session:
        event = _event_or_404(session, event_id)
        notes = session.exec(
            select(EventNote).where(EventNote.event_id == event_id).order_by(EventNote.created_at)
        ).all()
        return {**event.model_dump(), "notes": notes}


@router.post("/{event_id}/acknowledge")
def acknowledge_event(event_id: int):
    with Session(get_engine()) as session:
        event = _event_or_404(session, event_id)
        if event.status == "resolved":
            raise HTTPException(409, "resolved event cannot be acknowledged")
        event.status = "acknowledged"
        event.acknowledged_at = event.acknowledged_at or utcnow()
        session.add(event)
        session.commit()
        session.refresh(event)
        return event


@router.post("/{event_id}/resolve")
def resolve_event(event_id: int, body: ResolveBody = ResolveBody()):
    with Session(get_engine()) as session:
        event = _event_or_404(session, event_id)
        event.status = "resolved"
        event.acknowledged_at = event.acknowledged_at or utcnow()
        event.resolved_at = event.resolved_at or utcnow()
        session.add(event)
        if body.note:
            session.add(EventNote(event_id=event_id, text=body.note))
        session.commit()
        session.refresh(event)
        return event


@router.post("/{event_id}/notes", status_code=201)
def add_note(event_id: int, body: NoteBody):
    with Session(get_engine()) as session:
        _event_or_404(session, event_id)
        note = EventNote(event_id=event_id, text=body.text)
        session.add(note)
        session.commit()
        session.refresh(note)
        return note


@router.delete("/{event_id}")
def delete_event(event_id: int):
    with Session(get_engine()) as session:
        event = _event_or_404(session, event_id)
        notes = session.exec(select(EventNote).where(EventNote.event_id == event_id)).all()
        for note in notes:
            session.delete(note)
        event_store.delete_evidence(event)
        session.delete(event)
        session.commit()
    return {"status": "deleted", "id": event_id}
