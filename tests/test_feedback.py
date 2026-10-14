"""Stage 3.3: judging alerts as real / false alarm, and the evaluation built from those judgements."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens import feedback
from guardlens.app import app
from guardlens.events import Camera, Event, get_engine
from guardlens.events.store import event_store
from guardlens.types import EventDraft


def _event(severity="warning", triage=None):
    with Session(get_engine()) as session:
        cam = Camera(name="Judge cam", source="none", enabled=False)
        session.add(cam); session.commit(); session.refresh(cam)
    event = event_store.persist(cam.id, EventDraft(type="person", severity=severity))
    if triage:
        with Session(get_engine()) as session:
            row = session.get(Event, event.id)
            row.event_metadata = {**(row.event_metadata or {}), "agent": {"event_triage": triage}}
            session.add(row); session.commit()
    return event.id


def test_judging_sets_changes_and_clears_without_touching_severity_or_status():
    with TestClient(app) as client:
        eid = _event("critical")
        out = client.put(f"/api/events/{eid}/feedback", json={"label": "false_alarm"}).json()
        assert out["event_metadata"]["feedback"]["label"] == "false_alarm" and out["severity"] == "critical" and out["status"] == "new"
        assert client.put(f"/api/events/{eid}/feedback", json={"label": "real"}).json()["event_metadata"]["feedback"]["label"] == "real"
        assert "feedback" not in client.put(f"/api/events/{eid}/feedback", json={"label": None}).json()["event_metadata"]
        assert client.put(f"/api/events/{eid}/feedback", json={"label": "maybe"}).status_code == 422
        assert client.put("/api/events/999999/feedback", json={"label": "real"}).status_code == 404


def test_judging_keeps_the_rest_of_the_alerts_data():
    with TestClient(app) as client:
        eid = _event(triage={"threat": 0, "false_alarm": "high"})
        client.put(f"/api/events/{eid}/feedback", json={"label": "real"})
        meta = client.get(f"/api/events/{eid}").json()["event_metadata"]
        assert meta["agent"]["event_triage"]["threat"] == 0 and meta["feedback"]["label"] == "real"


def test_summary_and_evaluation_use_only_judged_alerts_with_ai_notes():
    with TestClient(app) as client:
        quiet = {"threat": 0, "false_alarm": "high"}
        ids = [_event(triage=quiet), _event(triage=quiet), _event(triage={"threat": 2, "false_alarm": "low"}), _event()]
        for eid, label in zip(ids, ["false_alarm", "real", "real", "real"]):  # the 2nd is a REAL alert the AI would have hidden
            client.put(f"/api/events/{eid}/feedback", json={"label": label})
        out = client.get("/api/events/feedback/summary").json()
        assert out["judged"] == 4 and out["real"] == 3 and out["false_alarms"] == 1 and out["with_ai_notes"] == 3
        ev = out["evaluation"]
        assert ev["events"] == 3  # the one without an AI note is not part of the evaluation
        assert ev["false_alarm_reduction"] == 1.0 and ev["missed_real_rate"] == 0.5
        assert ev["safe_to_enable_suppression"] is False  # one hidden real alert, and far fewer than 50 judged


def test_set_label_rejects_unknown_values():
    import pytest
    with pytest.raises(ValueError):
        feedback.set_label(Event(type="x", camera_id=1), "bogus")
