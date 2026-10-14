"""Your judgement on alerts ("real" / "false alarm"): the labelled data that triage evaluation needs (Stage 3.3)."""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from guardlens.agents.evaluation import evaluate_triage
from guardlens.events import Event, utcnow

LABELS = ("real", "false_alarm")
NEEDED = 50  # real alerts judged before suppression may even be considered (docs/12 §2.4)


def set_label(event: Event, label: Optional[str]) -> None:
    """Record (or clear, with None) the person's verdict on this alert. Reassigns the JSON so the change is saved."""
    if label is not None and label not in LABELS:
        raise ValueError(f"label must be one of {LABELS} or null")
    meta = dict(event.event_metadata or {})
    if label is None:
        meta.pop("feedback", None)
    else:
        meta["feedback"] = {"label": label, "at": utcnow().isoformat()}
    event.event_metadata = meta


def label_of(event: Event) -> Optional[str]:
    return ((event.event_metadata or {}).get("feedback") or {}).get("label")


def _triage_note(event: Event) -> Optional[dict]:
    return ((event.event_metadata or {}).get("agent") or {}).get("event_triage")


def summary(session: Session) -> dict:
    judged = [e for e in session.exec(select(Event)).all() if label_of(e)]
    real = sum(label_of(e) == "real" for e in judged)
    return {"judged": len(judged), "real": real, "false_alarms": len(judged) - real,
            "with_ai_notes": sum(_triage_note(e) is not None for e in judged), "needed_real": NEEDED}


def triage_report(session: Session) -> dict:
    """The offline evaluation of alert triage, from alerts you have judged that also carry an AI note."""
    rows = []
    for event in session.exec(select(Event)).all():
        label, note = label_of(event), _triage_note(event)
        if label and note:
            rows.append({"label": label, "threat": note.get("threat"), "false_alarm": note.get("false_alarm")})
    return evaluate_triage(rows)
