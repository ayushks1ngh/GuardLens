"""Notifier CRUD/test and event analytics endpoints (Phase 6)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from guardlens.events import Event, NotifierConfig, get_engine
from guardlens.notifiers import dispatcher, get_notifier_class, notifier_types

router = APIRouter(prefix="/api", tags=["notifiers", "analytics"])


class NotifierCreate(BaseModel):
    type: str
    config: dict[str, Any]
    enabled: bool = True
    min_severity: Literal["info", "warning", "critical"] = "warning"


class NotifierUpdate(BaseModel):
    config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    min_severity: Optional[Literal["info", "warning", "critical"]] = None


@router.get("/notifiers/types")
def types(): return notifier_types()


def _public_notifier(row: NotifierConfig) -> dict:
    """Return operational metadata without echoing webhook tokens/headers."""
    config = row.config or {}
    raw_url = config.get("url")
    endpoint = None
    if raw_url:
        from urllib.parse import urlsplit
        parsed = urlsplit(raw_url)
        endpoint = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    return {
        **row.model_dump(exclude={"config"}),
        "config": {
            "endpoint": endpoint,
            "configured_keys": sorted(config.keys()),
        },
    }


@router.get("/notifiers")
def list_notifiers():
    with Session(get_engine()) as session:
        return [_public_notifier(row) for row in session.exec(select(NotifierConfig)).all()]


def _validate_notifier(type_: str, config: dict) -> None:
    cls = get_notifier_class(type_)
    if not cls:
        raise HTTPException(422, "unknown notifier type")
    try:
        instance = cls()
        instance.setup(config)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, f"invalid notifier config: {exc}") from exc


@router.post("/notifiers", status_code=201)
def create_notifier(body: NotifierCreate):
    _validate_notifier(body.type, body.config)
    with Session(get_engine()) as session:
        row = NotifierConfig(**body.model_dump()); session.add(row); session.commit(); session.refresh(row)
    dispatcher.reload(); return _public_notifier(row)


@router.patch("/notifiers/{notifier_id}")
def update_notifier(notifier_id: int, body: NotifierUpdate):
    with Session(get_engine()) as session:
        row = session.get(NotifierConfig, notifier_id)
        if not row: raise HTTPException(404, "notifier not found")
        changes = body.model_dump(exclude_unset=True)
        if "config" in changes:
            _validate_notifier(row.type, changes["config"])
        for k, v in changes.items(): setattr(row, k, v)
        session.add(row); session.commit(); session.refresh(row)
    dispatcher.reload(); return _public_notifier(row)


@router.post("/notifiers/{notifier_id}/test")
def test_notifier(notifier_id: int):
    with Session(get_engine()) as session: row = session.get(NotifierConfig, notifier_id)
    if not row: raise HTTPException(404, "notifier not found")
    cls = get_notifier_class(row.type); notifier = cls(); notifier.setup(row.config)
    try: notifier.send({"type": "guardlens_test", "severity": "critical", "id": None})
    except Exception as exc: raise HTTPException(502, f"notifier failed: {exc}")
    return {"status": "sent"}


@router.delete("/notifiers/{notifier_id}")
def delete_notifier(notifier_id: int):
    with Session(get_engine()) as session:
        row = session.get(NotifierConfig, notifier_id)
        if not row: raise HTTPException(404, "notifier not found")
        session.delete(row); session.commit()
    dispatcher.reload(); return {"status": "deleted", "id": notifier_id}


def _event_conditions(from_: Optional[datetime], to: Optional[datetime]):
    conditions = []
    if from_: conditions.append(Event.created_at >= from_)
    if to: conditions.append(Event.created_at <= to)
    return conditions


@router.get("/analytics/summary")
def analytics_summary(
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
):
    with Session(get_engine()) as session:
        stmt = select(Event)
        for c in _event_conditions(from_, to): stmt = stmt.where(c)
        events = session.exec(stmt).all()
    def counts(field):
        result = {}
        for event in events:
            key = getattr(event, field); result[key] = result.get(key, 0) + 1
        return result
    return {"total": len(events), "by_type": counts("type"), "by_severity": counts("severity"), "by_status": counts("status")}


@router.get("/analytics/by-camera")
def analytics_by_camera():
    with Session(get_engine()) as session:
        rows = session.exec(select(Event.camera_id, func.count(Event.id)).group_by(Event.camera_id)).all()
    return [{"camera_id": camera_id, "count": count} for camera_id, count in rows]


@router.get("/analytics/timeline")
def analytics_timeline(
    bucket: Literal["hour", "day"] = "hour",
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
):
    stmt = select(Event).order_by(Event.created_at)
    for condition in _event_conditions(from_, to):
        stmt = stmt.where(condition)
    with Session(get_engine()) as session:
        events = session.exec(stmt).all()
    fmt = "%Y-%m-%d" if bucket == "day" else "%Y-%m-%dT%H:00:00Z"
    values = {}
    for event in events:
        key = event.created_at.strftime(fmt); values[key] = values.get(key, 0) + 1
    return [{"bucket": key, "count": value} for key, value in sorted(values.items())]
