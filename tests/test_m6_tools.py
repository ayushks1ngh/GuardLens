"""M6 deterministic tools: quiet-hour routing, incident report drafts, health issues."""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.events import Camera, Event, EventNote, get_engine
from guardlens.events.store import event_store
from guardlens.notifiers import dispatcher, in_quiet_hours
from guardlens.types import EventDraft
from guardlens.vlm_client import vlm_client


def _camera(name="Lobby", **kw) -> int:
    with Session(get_engine()) as session:
        camera = Camera(name=name, source=kw.pop("source", "none"), enabled=kw.pop("enabled", False), **kw)
        session.add(camera); session.commit(); session.refresh(camera)
        return camera.id


def test_quiet_window_logic():
    night = {"quiet_enabled": True, "quiet_start": "23:00", "quiet_end": "07:00"}
    assert in_quiet_hours(night, "23:30") and in_quiet_hours(night, "03:00") and not in_quiet_hours(night, "12:00")
    day = {"quiet_enabled": True, "quiet_start": "13:00", "quiet_end": "15:00"}
    assert in_quiet_hours(day, "14:00") and not in_quiet_hours(day, "15:00")
    assert not in_quiet_hours({"quiet_enabled": False, "quiet_start": "00:00", "quiet_end": "23:59"}, "12:00")


def test_quiet_hours_hold_back_minor_alerts_but_not_critical(monkeypatch):
    with TestClient(app) as client:
        sent = []

        class Spy:
            def send(self, event): sent.append(event["severity"])

        dispatcher._entries = [(1, "info", Spy())]
        now = datetime.now()
        put = client.put("/api/notifiers/routing", json={"values": {
            "quiet_enabled": True, "quiet_start": "00:00", "quiet_end": "23:59", "quiet_min_severity": "critical"}})
        assert put.status_code == 200 and put.json()["values"]["quiet_enabled"] is True
        dispatcher._entries = [(1, "info", Spy())]  # reload() inside the PUT replaced the entries from the DB
        for severity in ("info", "warning", "critical"):
            for future in dispatcher.dispatch({"type": "x", "severity": severity}):
                future.result(timeout=5)
        assert sent == ["critical"], now
        assert client.put("/api/notifiers/routing", json={"values": {"quiet_start": "25:99"}}).status_code == 422
        client.put("/api/notifiers/routing", json={"values": {"quiet_enabled": False}})
        got = client.get("/api/notifiers/routing").json()
        assert {f["name"] for f in got["fields"]} >= {"quiet_enabled", "quiet_start", "quiet_end", "quiet_min_severity"}
        assert got["values"]["quiet_enabled"] is False


def test_incident_report_collects_timeline_notes_and_evidence():
    with TestClient(app) as client:
        camera_id = _camera("Garage")
        first = event_store.persist(camera_id, EventDraft(type="vehicle", severity="info"))
        main = event_store.persist(camera_id, EventDraft(type="person", severity="critical"))
        other_camera = event_store.persist(_camera("Elsewhere"), EventDraft(type="person", severity="info"))
        event_store.annotate(main.id, "event_triage", {"title": "Person at car", "summary": "Someone tries a car door."})
        with Session(get_engine()) as session:
            session.add(EventNote(event_id=main.id, text="Guard dispatched")); session.commit()
        report = client.get(f"/api/events/{main.id}/incident-report").json()
        ids = [t["id"] for t in report["timeline"]]
        assert first.id in ids and main.id in ids and other_camera.id not in ids  # same camera only
        markdown = report["markdown"]
        assert "# Incident report" in markdown and "Person at car" in markdown and "Guard dispatched" in markdown
        assert "must review" in markdown and report["narrative"] is None
        assert client.get("/api/events/999999/incident-report").status_code == 404


def test_incident_ai_narrative_is_grounded_and_skipped_for_private_cameras(monkeypatch):
    class Reply:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": "A person approached [E%d]. A fire began [E99999]."}}]}

    monkeypatch.setenv("GUARDLENS_NVIDIA_API_KEY", "t")
    vlm_client.configure({"budget": {"per_minute": 100, "per_day": 100, "per_camera_hour": 100}})
    seen = []
    original = vlm_client._post
    with TestClient(app) as client:
        camera_id = _camera("Porch")
        main = event_store.persist(camera_id, EventDraft(type="person", severity="warning"))
        vlm_client._post = lambda u, h, p, t: (seen.append(p), type("R", (), {
            "status_code": 200, "json": lambda self: {"choices": [{"message": {"content": f"A person approached [E{main.id}]. A fire began [E99999]."}}]}})())[1]
        report = client.get(f"/api/events/{main.id}/incident-report", params={"ai": True}).json()
        assert report["narrative"] == f"A person approached [E{main.id}]." and "AI summary" in report["markdown"]
        vlm_client.set_local_only([camera_id])
        seen.clear()
        private = client.get(f"/api/events/{main.id}/incident-report", params={"ai": True}).json()
        assert private["narrative"] is None and not seen
    vlm_client._post = original
    vlm_client.set_local_only([]); vlm_client.configure({})


def test_health_issues_explain_problems_with_fixes():
    with TestClient(app) as client:
        _camera("Dead cam", source="http://10.0.0.9/video", enabled=True)
        _camera("Phone", source="webrtc:abc", enabled=True, source_type="webrtc")
        issues = client.get("/api/health/issues").json()
        messages = {i["message"]: i for i in issues}
        dead = messages["“Dead cam” is not sending video."]
        assert dead["area"] == "camera" and "address" in dead["fix"]
        assert "pairing link" in messages["“Phone” is not sending video."]["fix"]
        assert any(i["area"] == "security" for i in issues)  # login is off by default
        assert all({"level", "area", "message", "fix"} <= set(i) for i in issues)
