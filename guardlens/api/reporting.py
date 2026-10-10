"""Activity browsing and cached/regeneratable daily report API."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlmodel import Session, select

from guardlens.events import ActivityLog, Event, Report, get_engine, utcnow
from guardlens.reporting import generator_types, get_generator, reporting_runtime

router = APIRouter(prefix="/api", tags=["reporting"])


def _bounds(day: date):
    start = datetime.combine(day, time.min, timezone.utc)
    return start, start + timedelta(days=1)


def _generate(day: date, force: bool = False):
    key = reporting_runtime.generator
    with Session(get_engine()) as session:
        cached = session.exec(select(Report).where(Report.date == day).order_by(Report.generated_at.desc())).first()
        if cached and not force: return cached
        start, end = _bounds(day)
        activity = session.exec(select(ActivityLog).where(ActivityLog.timestamp >= start, ActivityLog.timestamp < end).order_by(ActivityLog.timestamp)).all()
        events = session.exec(select(Event).where(Event.created_at >= start, Event.created_at < end).order_by(Event.created_at)).all()
        result = get_generator(key).generate(day, activity, events)
        if cached:
            cached.generated_at = utcnow(); cached.generator = key; cached.content = result["content"]; cached.text = result["text"]; row = cached
        else: row = Report(date=day, generator=key, content=result["content"], text=result["text"])
        session.add(row); session.commit(); session.refresh(row); return row


def _parse_day(value: Optional[str]) -> date:
    if not value or value == "today":
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(422, "date must be YYYY-MM-DD or 'today'") from exc


@router.get("/activity")
def activity(
    camera_id: Optional[int] = None,
    from_: Optional[datetime] = Query(default=None, alias="from"),
    to: Optional[datetime] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = select(ActivityLog)
    if camera_id is not None: stmt = stmt.where(ActivityLog.camera_id == camera_id)
    if from_: stmt = stmt.where(ActivityLog.timestamp >= from_)
    if to: stmt = stmt.where(ActivityLog.timestamp <= to)
    with Session(get_engine()) as session:
        return session.exec(stmt.order_by(ActivityLog.timestamp.desc()).offset(offset).limit(limit)).all()


@router.get("/reports/types")
def report_types(): return generator_types()


@router.get("/reports/daily")
def daily(date_: Optional[str] = Query(default=None, alias="date")):
    return _generate(_parse_day(date_))


@router.post("/reports/daily/regenerate")
def regenerate(date_: Optional[str] = Query(default=None, alias="date")):
    return _generate(_parse_day(date_), force=True)


@router.get("/reports/daily/download", response_class=PlainTextResponse)
def download(date_: Optional[str] = Query(default=None, alias="date")):
    day = _parse_day(date_)
    report = _generate(day)
    return PlainTextResponse(report.text, headers={"Content-Disposition": f'attachment; filename="guardlens-{day}.txt"'})


@router.get("/reports/daily/{date_value}/download", response_class=PlainTextResponse)
def download_alias(date_value: str):
    return download(date_value)
