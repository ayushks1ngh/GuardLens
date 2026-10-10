"""Phase 5 acceptance tests: enrollment cache, matching, policy, deletion."""
from __future__ import annotations

import cv2
import numpy as np
from fastapi.testclient import TestClient

from guardlens.app import app
from guardlens.detectors import available_detectors, create_detector
from guardlens.detectors._face_runtime import face_runtime
from guardlens.rules import RuleConfig, RuleEngine, available_rules
from guardlens.types import Detection, FrameContext


def face_image(seed=1):
    rng = np.random.default_rng(seed)
    image = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    ok, data = cv2.imencode(".jpg", image)
    assert ok
    return image, data.tobytes()


def test_face_plugins_auto_discovered_and_backend_setup():
    assert "face" in available_detectors()
    assert "unknown_face" in available_rules()
    detector = create_detector("face", {"backend": "opencv", "min_size": 20})
    assert detector.process(np.zeros((100, 100, 3), dtype=np.uint8)) == []


def test_enroll_match_list_and_delete():
    with TestClient(app) as client:
        person = client.post("/api/persons", json={"name": "Ayush", "watchlist": True}).json()
        image, encoded = face_image()
        upload = client.post(
            f"/api/persons/{person['id']}/images",
            files={"image": ("face.jpg", encoded, "image/jpeg")},
        )
        assert upload.status_code == 201, upload.text
        people = client.get("/api/persons").json()
        assert people[0]["image_count"] == 1
        pid, name, watchlist, score = face_runtime.match(face_runtime.embedding(image))
        assert pid == person["id"] and name == "Ayush" and watchlist and score > 0.8
        assert client.delete(f"/api/persons/{person['id']}").status_code == 200
        assert client.get("/api/persons").json() == []
        assert face_runtime.match(face_runtime.embedding(image))[0] is None


def test_invalid_image_rejected():
    with TestClient(app) as client:
        person = client.post("/api/persons", json={"name": "P"}).json()
        response = client.post(f"/api/persons/{person['id']}/images", files={"image": ("x.txt", b"bad", "text/plain")})
        assert response.status_code == 422


def test_unknown_and_watchlist_policies():
    unknown = Detection("face", 1.0, (0.1, 0.1, 0.3, 0.3), attributes={"person_id": None, "name": "unknown"})
    known = Detection("face", 1.0, (0.1, 0.1, 0.3, 0.3), attributes={"person_id": 2, "name": "Watched", "watchlist": True})
    context = lambda d: FrameContext(camera_id=1, timestamp=1, frame_shape=(100, 100), detections=[d])
    engine = RuleEngine([RuleConfig(type="unknown_face", severity="critical", cooldown_seconds=0, params={"policy": "alert_unknown"})])
    assert engine.evaluate(context(unknown))[0].type == "unknown_face"
    engine = RuleEngine([RuleConfig(type="unknown_face", severity="critical", cooldown_seconds=0, params={"policy": "alert_watchlist"})])
    draft = engine.evaluate(context(known))[0]
    assert draft.type == "watchlist_face" and draft.person_id == 2


def test_face_policy_api_persists():
    with TestClient(app) as client:
        assert client.patch("/api/faces/policy", json={"policy": "alert_unknown"}).status_code == 200
        assert client.get("/api/faces/policy").json()["policy"] == "alert_unknown"
