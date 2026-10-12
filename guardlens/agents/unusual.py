"""Repeat-alert merging and "unusual for this time" flags. Fully local, no AI needed."""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from guardlens.agents import Agent, AgentContext, register_agent
from guardlens.events import Event, get_engine


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_outlier(current: int, history: list[int], sigma: float, min_samples: int) -> tuple[bool, dict]:
    """True when ``current`` exceeds history mean + sigma*std (needs enough comparable weeks)."""
    info = {"current": current, "weeks": len(history)}
    if len(history) < min_samples:
        return False, {**info, "reason": "not enough history yet"}
    mean = statistics.fmean(history)
    spread = statistics.pstdev(history) or 0.5  # avoid zero-variance false certainty
    info.update(typical=round(mean, 2), spread=round(spread, 2))
    return current > mean + sigma * spread and current >= 3, info


@register_agent
class UnusualActivityAgent(Agent):
    """Marks repeat alerts and spikes that are unusual for the time of week."""
    key = "unusual_activity"
    label = "Repeats and unusual activity"
    description = "Groups repeated alerts together and flags times when a camera is busier than it normally is."
    param_schema = {
        "merge_window_seconds": {"type": "integer", "default": 120, "min": 10, "max": 3600, "label": "Treat repeats within",
                                 "help": "A same-type alert on the same camera this soon after another counts as a repeat."},
        "sensitivity": {"type": "number", "default": 2.0, "min": 1, "max": 4, "step": 0.5, "label": "Unusual-activity sensitivity",
                        "help": "Lower flags more. It compares the last hour with the same hour in previous weeks."},
        "lookback_weeks": {"type": "integer", "default": 4, "min": 2, "max": 12, "label": "Weeks of history to compare"},
    }

    def on_event(self, event: dict, ctx: AgentContext) -> Optional[dict]:
        created = parse_time(event["created_at"])
        camera_id, type_ = event["camera_id"], event["type"]
        window = timedelta(seconds=int(ctx.params.get("merge_window_seconds", 120)))
        out: dict = {}
        with Session(get_engine()) as session:
            previous = session.exec(
                select(Event).where(Event.camera_id == camera_id, Event.type == type_, Event.id < event["id"],
                                    Event.created_at >= created.replace(tzinfo=None) - window)
                .order_by(Event.id.desc())
            ).first()
            if previous is not None:
                out.update(repeat_of=previous.id, title="Repeat alert",
                           summary=f"Same kind of alert on this camera shortly after #{previous.id}.")
            weeks = int(ctx.params.get("lookback_weeks", 4))
            history = []
            naive = created.replace(tzinfo=None)
            for w in range(1, weeks + 1):
                end = naive - timedelta(weeks=w)
                start = end - timedelta(hours=1)
                history.append(session.exec(select(func.count(Event.id)).where(
                    Event.camera_id == camera_id, Event.created_at > start, Event.created_at <= end)).one())
            current = session.exec(select(func.count(Event.id)).where(
                Event.camera_id == camera_id, Event.created_at > naive - timedelta(hours=1),
                Event.created_at <= naive)).one()
        outlier, info = is_outlier(current, history, float(ctx.params.get("sensitivity", 2.0)), min_samples=min(3, weeks))
        if outlier:
            out.update(unusual=True, baseline=info, title=out.get("title", "Busier than usual"),
                       summary=f"{current} alerts in the last hour; this camera usually has about {info['typical']} at this time.")
        return out or None
