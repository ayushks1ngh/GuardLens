"""Phase 6 acceptance tests: notifier isolation/filtering and analytics."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.events import Camera, Event, NotifierConfig, get_engine
from guardlens.events.store import event_store
from guardlens.notifiers import Notifier, NotifierDispatcher, register_notifier
from guardlens.types import EventDraft

SENT = []

@register_notifier
class TestNotifier(Notifier):
    key = "phase6_test"
    config_schema = {"fail": {"type": "bool"}}
    def send(self, event):
        if self.config.get("fail"): raise RuntimeError("expected")
        SENT.append(event)


def seed_camera():
    with Session(get_engine()) as session:
        camera = Camera(name="C", source="x", enabled=False); session.add(camera); session.commit(); session.refresh(camera); return camera.id


def test_dispatch_severity_and_failure_isolation():
    with TestClient(app):
        with Session(get_engine()) as session:
            session.add(NotifierConfig(type="phase6_test", config={}, min_severity="critical"))
            session.add(NotifierConfig(type="phase6_test", config={"fail": True}, min_severity="info"))
            session.commit()
        dispatcher = NotifierDispatcher(); dispatcher.reload()
        assert dispatcher.dispatch({"severity": "info", "type": "x"})[0].result(timeout=2) is False
        futures = dispatcher.dispatch({"severity": "critical", "type": "x"})
        assert sorted(f.result(timeout=2) for f in futures) == [False, True]
        assert SENT[-1]["severity"] == "critical"
        dispatcher.shutdown()


def test_notifier_crud_and_test_endpoint(monkeypatch):
    with TestClient(app) as client:
        created = client.post("/api/notifiers", json={"type": "phase6_test", "config": {}, "min_severity": "warning"})
        assert created.status_code == 201
        nid = created.json()["id"]
        assert any(x["key"] == "phase6_test" for x in client.get("/api/notifiers/types").json())
        assert client.post(f"/api/notifiers/{nid}/test").status_code == 200
        assert client.patch(f"/api/notifiers/{nid}", json={"enabled": False}).json()["enabled"] is False
        assert client.post("/api/notifiers", json={"type": "webhook", "config": {"url": "not-a-url"}}).status_code == 422
        assert client.delete(f"/api/notifiers/{nid}").status_code == 200


def test_analytics_counts_are_correct():
    with TestClient(app) as client:
        cid = seed_camera()
        event_store.persist(cid, EventDraft(type="person", severity="critical"))
        event_store.persist(cid, EventDraft(type="vehicle", severity="warning"))
        event_store.persist(cid, EventDraft(type="person", severity="warning"))
        summary = client.get("/api/analytics/summary").json()
        assert summary["total"] == 3
        assert summary["by_type"] == {"person": 2, "vehicle": 1}
        assert summary["by_severity"] == {"critical": 1, "warning": 2}
        assert client.get("/api/analytics/by-camera").json() == [{"camera_id": cid, "count": 3}]
        timeline = client.get("/api/analytics/timeline", params={"bucket": "day"}).json()
        assert sum(item["count"] for item in timeline) == 3


def test_event_persists_even_when_notifier_fails():
    with TestClient(app):
        from guardlens.notifiers import dispatcher
        with Session(get_engine()) as session:
            session.add(NotifierConfig(type="phase6_test", config={"fail": True}, min_severity="info")); session.commit()
        dispatcher.reload()
        event = event_store.persist(seed_camera(), EventDraft(type="person", severity="critical"))
        with Session(get_engine()) as session:
            assert session.get(Event, event.id) is not None
