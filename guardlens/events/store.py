"""Event persistence, JPEG evidence, and live-event fan-out (Phase 3)."""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
from sqlmodel import Session

from guardlens.events import Event, get_engine, utcnow
from guardlens.types import EventDraft

logger = logging.getLogger("guardlens.events.store")


class EventBus:
    """Small in-process replay buffer consumed by SSE clients."""

    def __init__(self, maxlen: int = 500):
        self._items: deque[dict] = deque(maxlen=maxlen)
        self._sequence = 0
        self._lock = threading.Lock()

    def publish(self, payload: dict) -> None:
        with self._lock:
            self._sequence += 1
            self._items.append({"sequence": self._sequence, **payload})

    def after(self, sequence: int) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._items if item["sequence"] > sequence]


class EventStore:
    def __init__(self):
        self._snapshots_dir = Path("data/snapshots")
        self._lock = threading.Lock()

    def configure(self, snapshots_dir: Path) -> None:
        self._snapshots_dir = Path(snapshots_dir)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    def persist(
        self,
        camera_id: int,
        draft: EventDraft,
        *,
        rule_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
    ) -> Event:
        """Atomically save evidence then insert an event row."""
        snapshot_path = None
        with self._lock:
            if draft.snapshot is not None:
                filename = f"{utcnow():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:10]}.jpg"
                absolute = self._snapshots_dir / filename
                ok = cv2.imwrite(str(absolute), draft.snapshot)
                if not ok:
                    raise OSError(f"failed to write snapshot {absolute}")
                snapshot_path = filename

            event = Event(
                type=draft.type,
                severity=draft.severity,
                camera_id=camera_id,
                rule_id=rule_id,
                person_id=draft.person_id,
                snapshot_path=snapshot_path,
                event_metadata=draft.metadata,
                created_at=created_at or utcnow(),
            )
            try:
                with Session(get_engine()) as session:
                    session.add(event)
                    session.commit()
                    session.refresh(event)
                try:
                    from guardlens.recording import clip_recorder
                    clip_path = clip_recorder.link_event(
                        camera_id, event.id, draft.type, frame=draft.snapshot
                    )
                    if clip_path:
                        event.clip_path = clip_path
                        with Session(get_engine()) as clip_session:
                            stored = clip_session.get(Event, event.id)
                            if stored:
                                stored.clip_path = clip_path
                                clip_session.add(stored)
                                clip_session.commit()
                except Exception:
                    logger.exception("clip trigger failed; event remains persisted")
            except Exception:
                if snapshot_path:
                    (self._snapshots_dir / snapshot_path).unlink(missing_ok=True)
                raise

        payload = event.model_dump(mode="json")
        event_bus.publish(payload)
        try:
            from guardlens.notifiers import dispatcher
            dispatcher.dispatch(payload)
        except Exception:
            logger.exception("notifier dispatch setup failed; event remains persisted")
        return event

    def delete_evidence(self, event: Event) -> None:
        if event.snapshot_path:
            (self._snapshots_dir / Path(event.snapshot_path).name).unlink(missing_ok=True)
        if event.clip_path:
            try:
                from sqlalchemy import func
                with Session(get_engine()) as session:
                    references = session.exec(
                        select(func.count(Event.id)).where(
                            Event.clip_path == event.clip_path,
                            Event.id != event.id,
                        )
                    ).one()
                if references == 0:
                    from guardlens.recording import clip_recorder
                    (clip_recorder.clips_dir / Path(event.clip_path).name).unlink(missing_ok=True)
            except Exception:
                logger.exception("failed to delete clip evidence %s", event.clip_path)


async def event_stream(last_sequence: int = 0):
    """SSE stream with replay by in-process sequence number and heartbeats."""
    sequence = last_sequence
    while True:
        items = event_bus.after(sequence)
        if items:
            for item in items:
                sequence = item["sequence"]
                yield f"id: {sequence}\ndata: {__import__('json').dumps(item)}\n\n"
        else:
            yield ": heartbeat\n\n"
        await asyncio.sleep(0.5)


event_bus = EventBus()
event_store = EventStore()
