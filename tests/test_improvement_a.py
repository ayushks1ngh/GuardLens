"""Improvement Phase A tests: source adapters, migration, probe, and API compatibility."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from guardlens.app import app
from guardlens.capture.sources import CameraSource, create_source, register_source, source_types
from guardlens.capture.worker import CaptureWorker
from guardlens.events.models import init_engine

SAMPLE = "data/samples/mall_cctv.mp4"


def test_opencv_modes_and_source_discovery():
    types = source_types()
    opencv = next(item for item in types if item["key"] == "opencv")
    assert {mode["key"] for mode in opencv["modes"]} == {"device", "network", "file"}
    assert create_source("opencv", {"mode": "device", "device_index": 0}).legacy_source == "0"
    device = create_source("opencv", {"mode": "device", "device_index": 0})
    assert device.config["pixel_format"] == "MJPG"
    assert (device.config["width"], device.config["height"], device.config["capture_fps"]) == (640, 480, 30)
    assert create_source("opencv", {"mode": "file", "path": SAMPLE}).legacy_source == SAMPLE
    network = create_source("opencv", {"mode": "network", "url": "http://user:pass@phone.local:8080/video"})
    assert network.config["url"].startswith("http://user:pass@")



def test_device_capture_settings_are_applied(monkeypatch):
    properties = []

    class FakeCapture:
        def isOpened(self): return True
        def set(self, key, value): properties.append((key, value)); return True
        def get(self, key):
            return {
                cv2.CAP_PROP_FPS: 15.0,
                cv2.CAP_PROP_FRAME_WIDTH: 800.0,
                cv2.CAP_PROP_FRAME_HEIGHT: 600.0,
            }.get(key, 0.0)
        def release(self): pass

    opened = []
    def fake_video_capture(value, backend):
        opened.append((value, backend))
        return FakeCapture()

    monkeypatch.setattr(cv2, "VideoCapture", fake_video_capture)
    adapter = create_source("opencv", {
        "mode": "device", "device_index": 2, "pixel_format": "MJPG",
        "width": 800, "height": 600, "capture_fps": 15,
    })
    try:
        assert adapter.open()
        assert opened[0][0] == 2
        assert (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")) in properties
        assert (cv2.CAP_PROP_FRAME_WIDTH, 800) in properties
        assert (cv2.CAP_PROP_FRAME_HEIGHT, 600) in properties
        assert (cv2.CAP_PROP_FPS, 15) in properties
    finally:
        adapter.close()

def test_new_source_plugin_requires_no_capture_edits():
    @register_source
    class SyntheticSource(CameraSource):
        key = "phase_a_synthetic"
        label = "Synthetic"
        modes = [{"key": "test", "label": "Test", "fields": []}]
        def open(self): self.status.opened = True; self.status.fps = 10; return True
        def read(self): return True, np.zeros((8, 12, 3), dtype=np.uint8)

    worker = CaptureWorker(700, "synthetic", source_type="phase_a_synthetic")
    worker.start()
    deadline = time.time() + 2
    while time.time() < deadline and worker.get_latest()[0] is None: time.sleep(0.02)
    frame, _ = worker.get_latest(); worker.stop()
    assert frame is not None and frame.shape == (8, 12, 3)


def test_source_types_probe_and_typed_camera_api():
    with TestClient(app) as client:
        types = client.get("/api/cameras/source-types")
        assert types.status_code == 200 and any(x["key"] == "opencv" for x in types.json())
        assert isinstance(client.get("/api/cameras/local-devices").json(), list)
        probe = client.post("/api/cameras/probe", json={
            "source_type": "opencv", "source_config": {"mode": "file", "path": SAMPLE}
        })
        assert probe.status_code == 200, probe.text
        assert probe.json()["resolution"] == {"width": 1920, "height": 1080}

        created = client.post("/api/cameras", json={
            "name": "Typed sample", "source_type": "opencv",
            "source_config": {"mode": "file", "path": SAMPLE},
        })
        assert created.status_code == 201, created.text
        body = created.json(); assert body["source_type"] == "opencv"
        assert body["source_config"]["mode"] == "file"
        cid = body["id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            current = client.get(f"/api/cameras/{cid}").json()
            if current["status"]["connected"]: break
            time.sleep(0.1)
        assert current["status"]["connected"]
        assert current["status"]["resolution"] == {"width": 1920, "height": 1080}
        assert current["status"]["last_frame_age"] is not None


def test_legacy_camera_api_remains_compatible():
    with TestClient(app) as client:
        created = client.post("/api/cameras", json={"name": "Legacy", "source": SAMPLE})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["source"] == SAMPLE and body["source_type"] == "opencv"
        assert body["source_config"]["mode"] == "file"
        updated = client.patch(f"/api/cameras/{body['id']}", json={"source": "0", "enabled": False})
        assert updated.status_code == 200
        assert updated.json()["source_config"]["mode"] == "device"
        assert updated.json()["source_config"]["device_index"] == 0


def test_network_credentials_are_redacted_and_invalid_sources_rejected():
    with TestClient(app) as client:
        created = client.post("/api/cameras", json={
            "name": "Phone", "source_type": "opencv",
            "source_config": {"mode": "network", "url": "http://user:secret@127.0.0.1:9/video", "timeout_ms": 250},
        })
        assert created.status_code == 201
        text = created.text
        assert "secret" not in text and "user:" not in text
        token_camera = client.post("/api/cameras", json={
            "name": "Token camera", "source_type": "opencv",
            "source_config": {"mode": "network", "url": "http://127.0.0.1:9/video?token=private", "timeout_ms": 250},
        })
        assert "private" not in token_camera.text and "token=" not in token_camera.text
        client.patch(f"/api/cameras/{token_camera.json()['id']}", json={"enabled": False})
        cid = created.json()["id"]
        client.patch(f"/api/cameras/{cid}", json={"enabled": False})
        assert client.post("/api/cameras/probe", json={"source_type": "unknown", "source": "x"}).status_code == 422
        assert client.post("/api/cameras/probe", json={"source_type": "opencv", "source_config": {"mode": "network", "url": "file:///tmp/x"}}).status_code == 422


def test_existing_sqlite_camera_schema_migrates_without_data_loss(tmp_path):
    db_path = tmp_path / "legacy.db"
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE camera (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, source VARCHAR NOT NULL, enabled BOOLEAN NOT NULL, analyze_fps FLOAT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)")
    db.execute("INSERT INTO camera VALUES (1, 'Old', '0', 0, NULL, '2026-01-01', '2026-01-01')")
    db.commit(); db.close()
    engine = init_engine(f"sqlite:///{db_path}")
    columns = {c["name"] for c in inspect(engine).get_columns("camera")}
    assert {"source_type", "source_config"} <= columns
    check = sqlite3.connect(db_path)
    row = check.execute("SELECT name, source, source_type, source_config FROM camera WHERE id=1").fetchone()
    assert row == ("Old", "0", "opencv", "{}")


def test_dashboard_exposes_probe_first_source_wizard():
    with TestClient(app) as client:
        html = client.get("/").text
        for marker in ("source-modes", "probe-cam-btn", "cam-device", "cam-url", "cam-path"):
            assert f'id="{marker}"' in html
        assert "Secure WebRTC pairing" in html
        assert 'id="create-pairing-btn"' in html
        assert 'id="add-cam-btn" disabled' in html
