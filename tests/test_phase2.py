"""Phase 2 acceptance-gate tests.

Gate 2:
- Live overlay shows person boxes + counts (detector produces real detections;
  overlay store is populated by the pipeline).
- A trivial ObjectClassRule (alert on `person`) produces an EventDraft.
- Adding a dummy detector/rule via the registry requires NO core edits
  (demonstrated by registering throwaway plugins here and using them).
- The tracker assigns stable IDs across frames.
- Rule-engine cooldown prevents event floods.
"""
from __future__ import annotations

import time

import cv2
import numpy as np
import pytest

from guardlens.analysis.pipeline import AnalysisWorker
from guardlens.analysis.tracker import CentroidTracker
from guardlens.detectors import Detector, available_detectors, create_detector, register
from guardlens.rules import (
    Rule,
    RuleConfig,
    RuleEngine,
    available_rules,
    register_rule,
    rule_types,
)
from guardlens.streaming.stream import overlay_store
from guardlens.types import Detection, EventDraft, FrameContext

SAMPLE = "data/samples/mall_cctv.mp4"


def _sample_frame():
    cap = cv2.VideoCapture(SAMPLE)
    ok, frame = cap.read()
    cap.release()
    assert ok and frame is not None
    return frame


# ---------------------------------------------------------------------------
# Detector + rule registries (the extensibility seam)
# ---------------------------------------------------------------------------
def test_builtin_plugins_registered():
    assert "object" in available_detectors()
    assert "object_class" in available_rules()


def test_add_dummy_detector_without_core_edits():
    """Registering a new detector needs only @register — no core file changes."""

    @register
    class _DummyDetector(Detector):
        key = "dummy_test_detector"

        def process(self, frame):
            return [Detection(class_name="unicorn", confidence=0.99, bbox=(0.1, 0.1, 0.2, 0.2))]

    assert "dummy_test_detector" in available_detectors()
    det = create_detector("dummy_test_detector", {})
    out = det.process(np.zeros((10, 10, 3), dtype="uint8"))
    assert out and out[0].class_name == "unicorn"


def test_add_dummy_rule_without_core_edits():
    @register_rule
    class _AlwaysRule(Rule):
        key = "always_test_rule"
        param_schema = {"foo": {"type": "str"}}

        def evaluate(self, ctx, cfg):
            return EventDraft(type=self.key, severity=cfg.severity, metadata={"ok": True})

    assert "always_test_rule" in available_rules()
    # Auto-exposed with its schema for the UI to render.
    keys = {rt["key"] for rt in rule_types()}
    assert "always_test_rule" in keys


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------
def test_tracker_assigns_stable_ids():
    trk = CentroidTracker(iou_threshold=0.3)
    d1 = [Detection(class_name="person", confidence=0.9, bbox=(0.10, 0.10, 0.20, 0.40))]
    out1 = trk.update(d1)
    first_id = out1[0].track_id
    assert first_id is not None

    # Slightly moved box next frame → same track id.
    d2 = [Detection(class_name="person", confidence=0.9, bbox=(0.12, 0.11, 0.22, 0.41))]
    out2 = trk.update(d2)
    assert out2[0].track_id == first_id


# ---------------------------------------------------------------------------
# Rule engine: object class rule + cooldown
# ---------------------------------------------------------------------------
def test_object_class_rule_fires_on_person():
    cfg = RuleConfig(type="object_class", severity="warning", name="p",
                     cooldown_seconds=0.0, params={"classes": ["person"]})
    eng = RuleEngine([cfg])
    dets = [Detection(class_name="person", confidence=0.9, bbox=(0.1, 0.1, 0.2, 0.4))]
    ctx = FrameContext(camera_id=1, timestamp=time.time(), frame_shape=(100, 100),
                       detections=dets)
    drafts = eng.evaluate(ctx)
    assert len(drafts) == 1
    assert drafts[0].type == "object_class"
    assert drafts[0].metadata["count"] == 1


def test_rule_engine_cooldown_prevents_floods():
    cfg = RuleConfig(type="object_class", severity="warning", name="p",
                     cooldown_seconds=100.0, params={"classes": ["person"]})
    eng = RuleEngine([cfg])
    dets = [Detection(class_name="person", confidence=0.9, bbox=(0.1, 0.1, 0.2, 0.4))]
    ctx = FrameContext(camera_id=1, timestamp=1000.0, frame_shape=(100, 100), detections=dets)
    first = eng.evaluate(ctx, now=1000.0)
    second = eng.evaluate(ctx, now=1001.0)   # within cooldown
    third = eng.evaluate(ctx, now=1200.0)    # after cooldown
    assert len(first) == 1 and len(second) == 0 and len(third) == 1


def test_broken_rule_does_not_crash_engine():
    @register_rule
    class _BoomRule(Rule):
        key = "boom_test_rule"

        def evaluate(self, ctx, cfg):
            raise RuntimeError("boom")

    cfg = RuleConfig(type="boom_test_rule", severity="info", name="b", cooldown_seconds=0.0)
    eng = RuleEngine([cfg])
    ctx = FrameContext(camera_id=1, timestamp=time.time(), frame_shape=(100, 100), detections=[])
    assert eng.evaluate(ctx) == []  # exception swallowed, pipeline survives


# ---------------------------------------------------------------------------
# Full pipeline on a real frame: boxes + counts in the overlay + draft logged
# ---------------------------------------------------------------------------
@pytest.mark.slow
def test_pipeline_detects_people_and_populates_overlay():
    frame = _sample_frame()
    detector = create_detector("object", {"model_weights": "yolov8n.pt", "device": "cpu"})
    cfg = RuleConfig(type="object_class", severity="warning", name="person-watch",
                     cooldown_seconds=0.0, params={"classes": ["person"]})
    engine = RuleEngine([cfg])

    worker = AnalysisWorker(camera_id=99, detectors=[detector],
                            rule_engine=engine, analyze_fps=6.0)
    ctx = worker.analyze_once(frame, timestamp=time.time())

    # Real detections present and tracked.
    assert len(ctx.detections) > 0
    assert any(d.class_name == "person" for d in ctx.detections)
    assert all(d.track_id is not None for d in ctx.detections)

    # Overlay store populated with boxes + counts for the live view.
    ov = overlay_store.get(99)
    assert ov.get("boxes")
    assert ov.get("counts", {}).get("person", 0) >= 1
    assert ov.get("alert") is True  # person present → ObjectClassRule fired
