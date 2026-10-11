"""Improvement Phase C: motion detection and bounded clip recording."""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.detectors import create_detector
from guardlens.events import Camera, Event, get_engine
from guardlens.events.store import event_store
from guardlens.recording import ClipRecorder
from guardlens.rules import RuleConfig, RuleEngine, rule_types
from guardlens.types import EventDraft, FrameContext


def options(**overrides):
    base = {
        "enabled": True, "mode": "event", "pre_roll_seconds": 0.2,
        "post_roll_seconds": 0.1, "max_clip_seconds": 2,
        "segment_seconds": 10, "retention_days": 7, "quota_mb": 10,
        "codec_preferences": ["MJPG"],
    }
    base.update(overrides)
    return base


def test_motion_detector_and_rule_are_plugins():
    assert "motion" in {item["key"] for item in rule_types()}
    detector = create_detector("motion", {"warmup_frames": 2, "min_area": 0.01, "detect_shadows": False})
    background = np.zeros((100, 100, 3), dtype=np.uint8)
    detector.process(background); detector.process(background)
    changed = background.copy(); changed[20:70, 20:70] = 255
    detections = detector.process(changed)
    assert any(item.class_name == "motion" for item in detections)
    engine = RuleEngine([RuleConfig(type="motion", name="movement", cooldown_seconds=0, params={})])
    ctx = FrameContext(camera_id=1, timestamp=1, frame_shape=(100, 100), detections=detections, frame=changed)
    drafts = engine.evaluate(ctx, now=1)
    assert len(drafts) == 1 and drafts[0].type == "motion"


def test_recorder_writes_bounded_pre_and_post_roll_clip(tmp_path):
    recorder = ClipRecorder(); recorder.configure(tmp_path, options())
    start = time.time(); frame = np.full((48, 64, 3), 80, dtype=np.uint8)
    for i in range(4): recorder.on_frame(1, frame + i, start + i * 0.04, 25)
    name = recorder.trigger(1, 7, "person", frame)
    assert name and recorder.status()["active"]
    recorder.on_frame(1, frame, start + 0.20, 25)
    recorder.on_frame(1, frame, start + 0.40, 25)
    assert not recorder.status()["active"]
    path = tmp_path / name
    assert path.is_file() and path.stat().st_size > 0
    cap = cv2.VideoCapture(str(path)); ok, decoded = cap.read(); cap.release()
    assert ok and decoded.shape[:2] == (48, 64)


def test_event_persistence_links_and_serves_clip(tmp_path):
    recorder = __import__("guardlens.recording", fromlist=["clip_recorder"]).clip_recorder
    with TestClient(app) as client:
        recorder.configure(tmp_path / "clips", options())
        event_store.configure(tmp_path / "snapshots")
        with Session(get_engine()) as session:
            camera = Camera(name="Clip", source="sample", enabled=False)
            session.add(camera); session.commit(); session.refresh(camera); camera_id = camera.id
        frame = np.full((32, 40, 3), 120, dtype=np.uint8)
        now = time.time()
        recorder.on_frame(camera_id, frame, now, 10)
        event = event_store.persist(camera_id, EventDraft(type="person", severity="warning", snapshot=frame))
        recorder.on_frame(camera_id, frame, now + 11, 10)
        with Session(get_engine()) as session:
            stored = session.get(Event, event.id)
            assert stored.clip_path
        response = client.get(f"/api/events/{event.id}/clip")
        assert response.status_code == 200 and len(response.content) > 0


def test_retention_quota_and_codec_failures_are_contained(tmp_path):
    recorder = ClipRecorder(); recorder.configure(tmp_path, options(retention_days=1, quota_mb=1))
    old = tmp_path / "old.mp4"; old.write_bytes(b"x" * 100); os.utime(old, (1, 1))
    assert recorder.prune(now=2 * 86400) == 1 and not old.exists()
    recorder.configure(tmp_path, options(codec_preferences=["BAD!"]))
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    recorder.on_frame(3, frame, time.time(), 10)
    assert recorder.trigger(3, 1, "person", frame) is None
    assert "codec" in recorder.status()["errors"][3]


def test_recording_settings_api_persists_and_reconfigures(tmp_path):
    from guardlens.recording import clip_recorder
    with TestClient(app) as client:
        clip_recorder.configure(tmp_path / "clips", {"enabled": False})
        current = client.get("/api/recording")
        assert current.status_code == 200
        config = current.json()["config"]
        config.update({"enabled": True, "mode": "motion", "pre_roll_seconds": 2,
                       "post_roll_seconds": 3, "retention_days": 2, "quota_mb": 64})
        updated = client.patch("/api/recording", json=config)
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"]["enabled"] is True
        assert updated.json()["status"]["mode"] == "motion"
        again = client.get("/api/recording").json()["config"]
        assert again["pre_roll_seconds"] == 2 and again["quota_mb"] == 64
        config["codec_preferences"] = ["TOO-LONG"]
        assert client.patch("/api/recording", json=config).status_code == 422


def test_continuous_segment_links_event_and_finalizes_atomically(tmp_path):
    recorder = ClipRecorder(); recorder.configure(tmp_path, options(mode="continuous"))
    frame = np.full((24, 32, 3), 42, dtype=np.uint8); now = time.time()
    recorder.on_frame(9, frame, now, 10)
    name = recorder.link_event(9, 101, "person", frame)
    assert name and not (tmp_path / name).exists()
    assert list(tmp_path.glob("*.partial.*"))
    recorder.stop_camera(9)
    assert (tmp_path / name).is_file() and not list(tmp_path.glob("*.partial.*"))
