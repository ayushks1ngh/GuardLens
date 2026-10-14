"""Every detector plugin, run for real on synthetic frames and (when present) the sample video."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from guardlens.detectors import available_detectors, create_detector
from guardlens.detectors._face_runtime import faces_on_people
from guardlens.types import Detection

SAMPLE = Path("data/samples/mall_cctv.mp4")


def _frames(count=30, step=4):
    cap = cv2.VideoCapture(str(SAMPLE))
    out = []
    while len(out) < count:
        ok, frame = cap.read()
        if not ok:
            break
        for _ in range(step):
            cap.grab()
        out.append(frame)
    cap.release()
    return out


def test_all_plugins_are_registered():
    assert {"object", "face", "motion", "hand_gesture", "open_vocab"} <= set(available_detectors())


def test_motion_sees_a_moving_block_and_ignores_a_still_scene():
    det = create_detector("motion", {"warmup_frames": 3, "min_area": 0.01})
    still = np.full((240, 320, 3), 90, dtype=np.uint8)
    assert all(det.process_for_camera(1, still) == [] for _ in range(10))
    found = []
    for x in range(0, 200, 20):
        frame = still.copy()
        cv2.rectangle(frame, (x, 80), (x + 90, 200), (255, 255, 255), -1)
        found += det.process_for_camera(1, frame)
    assert found and found[0].class_name == "motion"


def test_motion_state_is_per_camera():
    det = create_detector("motion", {"warmup_frames": 2})
    blank = np.zeros((120, 160, 3), dtype=np.uint8)
    for _ in range(5):
        det.process_for_camera(1, blank)
    moving = blank.copy(); cv2.rectangle(moving, (20, 20), (140, 100), (255, 255, 255), -1)
    assert det.process_for_camera(2, moving) == []  # camera 2 has no history yet: warm-up, not a false alarm


def test_face_detector_starts_and_handles_empty_frames():
    det = create_detector("face", {"backend": "opencv"})
    assert det.process(np.zeros((240, 320, 3), dtype=np.uint8)) == []
    assert det.require_person is True and det._min_neighbors >= 8


def test_faces_must_sit_on_a_person():
    person = Detection(class_name="person", confidence=0.9, bbox=(0.4, 0.2, 0.6, 0.9))
    on_person = Detection(class_name="face", confidence=1.0, bbox=(0.45, 0.22, 0.55, 0.32))
    on_roof = Detection(class_name="face", confidence=1.0, bbox=(0.05, 0.05, 0.12, 0.12))
    kept = faces_on_people([person, on_person, on_roof])
    assert on_person in kept and on_roof not in kept and person in kept
    assert faces_on_people([on_roof]) == []  # object detector ran and found nobody: no face is believable


@pytest.mark.skipif(not SAMPLE.exists() or not Path("yolov8n.pt").exists(), reason="sample video / weights not present")
def test_object_detector_finds_people_and_cars_in_the_sample():
    det = create_detector("object", {"conf": 0.4, "imgsz": 640})
    seen = set()
    for frame in _frames(12):
        seen |= {d.class_name for d in det.process(frame)}
    assert {"person", "car"} <= seen
    for d in det.process(_frames(1)[0]):
        assert 0 <= d.bbox[0] < d.bbox[2] <= 1 and 0 <= d.bbox[1] < d.bbox[3] <= 1 and 0 < d.confidence <= 1


class _Fake:
    def __init__(self, key, detections, require_person=False):
        self.key, self._out, self.require_person = key, detections, require_person

    def should_process(self, camera_id, timestamp):
        return True

    def process_for_camera(self, camera_id, frame):
        return list(self._out)


def _analyse(detectors):
    from guardlens.analysis.pipeline import AnalysisWorker
    from guardlens.rules import RuleEngine
    worker = AnalysisWorker(1, detectors, RuleEngine([]), analyze_fps=5)
    return [d.class_name for d in worker.analyze_once(np.zeros((100, 100, 3), dtype=np.uint8), 1000.0).detections]


def test_pipeline_drops_faces_that_are_not_on_a_person():
    person = Detection(class_name="person", confidence=0.9, bbox=(0.4, 0.2, 0.6, 0.9))
    on_person = Detection(class_name="face", confidence=1.0, bbox=(0.45, 0.22, 0.55, 0.32))
    on_roof = Detection(class_name="face", confidence=1.0, bbox=(0.05, 0.05, 0.12, 0.12))
    assert sorted(_analyse([_Fake("object", [person]), _Fake("face", [on_person, on_roof], True)])) == ["face", "person"]
    # object detector found nobody -> faces are not believable
    assert _analyse([_Fake("object", []), _Fake("face", [on_roof], True)]) == []
    # no object detector on this camera -> nothing to cross-check, faces pass through
    assert _analyse([_Fake("face", [on_roof], True)]) == ["face"]


def test_hand_gesture_without_mediapipe_degrades_instead_of_crashing():
    det = create_detector("hand_gesture", {})
    assert det.process(np.zeros((120, 160, 3), dtype=np.uint8)) == []
