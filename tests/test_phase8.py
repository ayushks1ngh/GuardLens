"""Phase 8 hardening and end-to-end acceptance gate."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from guardlens.app import app
from guardlens.events import ActivityLog, get_engine, utcnow
from guardlens.events.store import event_store
from guardlens.reporting.maintenance import prune_activity
from guardlens.types import EventDraft


def test_packaging_and_operator_docs_exist():
    for path in ["Dockerfile", "docker-compose.yml", "run.sh", ".dockerignore", "docs/09-session-recovery.md"]:
        assert Path(path).exists(), path
    assert Path("run.sh").stat().st_mode & 0o111


def test_input_validation_and_health_detail():
    with TestClient(app) as client:
        assert client.post("/api/cameras", json={"name": "", "source": "x"}).status_code == 422
        assert client.post("/api/cameras", json={"name": "x", "source": "x", "analyze_fps": 0}).status_code == 422
        health = client.get("/health").json()
        assert "analysis_enabled" in health and "detectors" in health


def test_activity_retention_pruning():
    with TestClient(app):
        from guardlens.events import Camera
        with Session(get_engine()) as session:
            camera = Camera(name="C", source="x", enabled=False); session.add(camera); session.commit(); session.refresh(camera)
            session.add(ActivityLog(camera_id=camera.id, timestamp=utcnow()-timedelta(days=40), summary={}))
            session.add(ActivityLog(camera_id=camera.id, timestamp=utcnow(), summary={}))
            session.commit()
        assert prune_activity(30) == 1
        with Session(get_engine()) as session: assert len(session.exec(select(ActivityLog)).all()) == 1


def test_websocket_overlay_fallback():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/overlay") as socket:
            assert isinstance(socket.receive_json(), dict)


def test_full_api_happy_path():
    with TestClient(app) as client:
        camera = client.post("/api/cameras", json={"name": "Lobby", "source": "http://127.0.0.1:9/video"}).json()
        cid = camera["id"]
        client.patch(f"/api/cameras/{cid}", json={"enabled": False})
        zone = client.post(f"/api/cameras/{cid}/zones", json={"name": "Door", "polygon": [[0,0],[1,0],[1,1],[0,1]]}).json()
        rule = client.post("/api/rules", json={"type":"zone_intrusion","name":"Door entry","camera_id":cid,"zone_id":zone["id"],"severity":"critical","cooldown_seconds":10,"params":{"classes":["person"]}})
        assert rule.status_code == 201

        event = event_store.persist(cid, EventDraft(type="zone_intrusion", severity="critical", metadata={"zone_id": zone["id"]}, snapshot=np.zeros((20,20,3), dtype=np.uint8)))
        listed = client.get("/api/events", params={"camera_id":cid,"severity":"critical"}).json()
        assert listed["total"] == 1
        assert client.post(f"/api/events/{event.id}/acknowledge").json()["status"] == "acknowledged"
        assert client.post(f"/api/events/{event.id}/resolve", json={"note":"Reviewed"}).json()["status"] == "resolved"
        assert client.get("/api/analytics/summary").json()["total"] == 1
        report = client.get("/api/reports/daily", params={"date": "today"}).json()
        assert report["content"]["event_count"] == 1
        assert client.get("/api/reports/daily/download").status_code == 200
        assert client.get("/api/reports/daily/today/download").status_code == 200
