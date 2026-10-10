"""Periodic/explicit retention maintenance."""
from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, select

from guardlens.events import ActivityLog, get_engine, utcnow


def prune_activity(retention_days: int) -> int:
    """Delete activity samples older than the configured retention window."""
    cutoff = utcnow() - timedelta(days=max(1, retention_days))
    with Session(get_engine()) as session:
        rows = session.exec(select(ActivityLog).where(ActivityLog.timestamp < cutoff)).all()
        for row in rows: session.delete(row)
        session.commit()
        return len(rows)
