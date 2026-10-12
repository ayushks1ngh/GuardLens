"""Phase 3 acceptance tests: persistence, evidence, filtering, workflow, SSE bus."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.events import Camera, Event, get_engine
from guardlens.events.store import event_bus, event_store
from guardlens.types import EventDraft


def _camera() -> int:
    with Session(get_engine()) as session:
        camera = Camera(name="Test", source="none", enabled=False)
        session.add(camera)
        session.commit()
        session.refresh(camera)
        return camera.id


def test_persist_event_with_snapshot_and_bus():
    with TestClient(app):
        camera_id = _camera()
        before = event_bus._sequence
        frame = np.full((40, 60, 3), 127, dtype=np.uint8)
        event = event_store.persist(
            camera_id,
            EventDraft(type="object_class", severity="warning", metadata={"count": 1}, snapshot=frame),
        )
        assert event.id is not None
        assert event.snapshot_path
        assert (event_store._snapshots_dir / event.snapshot_path).exists()
        pushed = event_bus.after(before)
        assert pushed and pushed[-1]["id"] == event.id


def test_event_filters_pagination_and_detail():
    with TestClient(app) as client:
        camera_id = _camera()
        event_store.persist(camera_id, EventDraft(type="person", severity="critical"))
        event_store.persist(camera_id, EventDraft(type="vehicle", severity="info"))
        response = client.get("/api/events", params={"severity": "critical", "limit": 1})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1 and len(body["items"]) == 1
        event_id = body["items"][0]["id"]
        detail = client.get(f"/api/events/{event_id}").json()
        assert detail["type"] == "person" and detail["notes"] == []


def test_acknowledge_resolve_and_notes_persist():
    with TestClient(app) as client:
        event_id = event_store.persist(_camera(), EventDraft(type="person", severity="warning")).id
        acknowledged = client.post(f"/api/events/{event_id}/acknowledge")
        assert acknowledged.status_code == 200
        assert acknowledged.json()["status"] == "acknowledged"
        note = client.post(f"/api/events/{event_id}/notes", json={"text": "Checked camera"})
        assert note.status_code == 201
        resolved = client.post(f"/api/events/{event_id}/resolve", json={"note": "All clear"})
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"
        detail = client.get(f"/api/events/{event_id}").json()
        assert [n["text"] for n in detail["notes"]] == ["Checked camera", "All clear"]
        assert client.post(f"/api/events/{event_id}/acknowledge").status_code == 409


def test_delete_event_removes_snapshot_and_row():
    with TestClient(app) as client:
        event = event_store.persist(
            _camera(),
            EventDraft(type="person", severity="warning", snapshot=np.zeros((10, 10, 3), dtype=np.uint8)),
        )
        evidence = event_store._snapshots_dir / event.snapshot_path
        assert evidence.exists()
        assert client.delete(f"/api/events/{event.id}").status_code == 200
        assert not evidence.exists()
        assert client.get(f"/api/events/{event.id}").status_code == 404


def test_analysis_event_sink_failure_is_isolated():
    from guardlens.analysis.pipeline import AnalysisWorker
    from guardlens.detectors import Detector
    from guardlens.rules import RuleConfig, RuleEngine
    from guardlens.types import Detection

    class FakeDetector(Detector):
        def process(self, frame):
            return [Detection("person", 0.9, (0.1, 0.1, 0.5, 0.8))]

    def broken_sink(*args):
        raise OSError("disk unavailable")

    worker = AnalysisWorker(
        7,
        [FakeDetector()],
        RuleEngine([RuleConfig(type="object_class", cooldown_seconds=0, params={"classes": ["person"]})]),
        6,
        event_sink=broken_sink,
    )
    ctx = worker.analyze_once(np.zeros((100, 100, 3), dtype=np.uint8), 1000.0)
    assert ctx.detections and ctx.detections[0].track_id is not None


def test_delete_evidence_removes_unshared_clip_only(tmp_path):
    from guardlens.recording import clip_recorder
    with TestClient(app):
        clip_recorder.configure(tmp_path / "clips", {"enabled": False})
        event_store.configure(tmp_path / "snapshots")
        camera_id = _camera()
        clips = clip_recorder.clips_dir
        clips.mkdir(parents=True, exist_ok=True)
        (clips / "solo.mp4").write_bytes(b"x")
        (clips / "shared.mp4").write_bytes(b"x")
        with Session(get_engine()) as session:
            events = [Event(camera_id=camera_id, type="person", severity="info", clip_path=name)
                      for name in ("solo.mp4", "shared.mp4", "shared.mp4")]
            session.add_all(events)
            session.commit()
            for event in events:
                session.refresh(event)
        event_store.delete_evidence(events[0])
        assert not (clips / "solo.mp4").exists()
        event_store.delete_evidence(events[1])
        assert (clips / "shared.mp4").exists()  # another event still references it
