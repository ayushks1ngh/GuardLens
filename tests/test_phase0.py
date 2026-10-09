"""Phase 0 acceptance-gate tests.

Gate 0:
- Server starts (app importable, lifespan runs).
- GET /health returns 200 with device info.
- DB file created with all tables.
- Dashboard shell served at /.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from guardlens.app import app
from guardlens.events import get_engine

EXPECTED_TABLES = {
    "camera", "zone", "rule", "event", "eventnote", "person",
    "faceimage", "notifierconfig", "setting", "activitylog", "report",
}


def test_health_ok():
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "python" in body
        assert "device" in body
        assert isinstance(body["cameras"], list)


def test_config_endpoint():
    with TestClient(app) as client:
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()
        assert "analyze_fps" in body
        assert "detectors" in body
        assert "reporting" in body


def test_db_tables_created():
    with TestClient(app):  # triggers lifespan -> init_engine
        insp = inspect(get_engine())
        tables = set(insp.get_table_names())
        missing = EXPECTED_TABLES - tables
        assert not missing, f"missing tables: {missing}"


def test_dashboard_served():
    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        assert "GUARDLENS" in r.text.upper()


def test_sample_video_present():
    assert Path("data/samples/mall_cctv.mp4").exists()
