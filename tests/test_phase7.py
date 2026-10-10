"""Phase 7 acceptance tests: activity sampling and pluggable daily reports."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from guardlens.app import app
from guardlens.events import ActivityLog, Camera, get_engine
from guardlens.events.store import event_store
from guardlens.reporting import ReportGenerator, generator_types, register_generator
from guardlens.reporting.activity import activity_sampler
from guardlens.types import Detection, EventDraft, FrameContext


def camera():
    with Session(get_engine()) as session:
        row = Camera(name="Report cam", source="x", enabled=False); session.add(row); session.commit(); session.refresh(row); return row.id


def test_activity_sampler_interval_and_summary():
    with TestClient(app):
        cid = camera(); activity_sampler.configure(10, 30); activity_sampler._last.clear()
        ctx = FrameContext(camera_id=cid, timestamp=1000, frame_shape=(100,100), detections=[
            Detection("person", .9, (0,0,.2,.5)), Detection("car", .9, (.3,0,.6,.5)),
            Detection("face", 1, (.1,.1,.2,.2), attributes={"person_id": 1, "name": "Ayush"}),
        ])
        assert activity_sampler.sample(ctx) is True
        assert activity_sampler.sample(ctx) is False
        ctx.timestamp = 1011; assert activity_sampler.sample(ctx) is True
        with Session(get_engine()) as session:
            rows = session.exec(select(ActivityLog)).all()
            assert len(rows) == 2 and rows[0].summary["people"] == 1
            assert rows[0].summary["vehicles"] == {"car": 1}
            assert rows[0].summary["known"] == ["Ayush"]


def test_daily_report_cache_regenerate_and_download():
    with TestClient(app) as client:
        cid = camera(); now = datetime.now(timezone.utc)
        with Session(get_engine()) as session:
            session.add(ActivityLog(camera_id=cid, timestamp=now, summary={"people": 2, "vehicles": {"car": 1}, "known": ["Ayush"], "unknown_faces": 1})); session.commit()
        event_store.persist(cid, EventDraft(type="zone_intrusion", severity="critical"), created_at=now)
        report = client.get("/api/reports/daily").json()
        assert report["content"]["event_count"] == 1
        assert "GuardLens daily briefing" in report["text"] and "critical" in report["text"]
        cached_at = report["generated_at"]
        assert client.get("/api/reports/daily").json()["generated_at"] == cached_at
        regenerated = client.post("/api/reports/daily/regenerate").json()
        assert regenerated["generated_at"] >= cached_at
        download = client.get("/api/reports/daily/download")
        assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
        assert "GuardLens daily briefing" in download.text
        assert client.get("/api/activity").json()


def test_report_generator_is_swappable_without_api_changes():
    @register_generator
    class DummyReport(ReportGenerator):
        key = "phase7_dummy"
        def generate(self, date, activity, events): return {"content": {"dummy": True}, "text": "dummy"}
    assert "phase7_dummy" in generator_types()
    from guardlens.reporting import get_generator
    assert get_generator("phase7_dummy").generate(datetime.now().date(), [], [])["text"] == "dummy"
