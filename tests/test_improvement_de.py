"""Improvement D/E: flexible gesture foundation and bounded ASL scope."""
from __future__ import annotations

import json
import subprocess

import numpy as np

from guardlens.detectors import available_detectors, create_detector
from guardlens.gestures import create_vocabulary, normalized_features, vocabularies
from guardlens.rules import RuleConfig, RuleEngine, rule_types
from guardlens.types import Detection, FrameContext


def hand_landmarks(open_hand=True):
    points=[(0.5,0.8,0.0)]*21
    points=list(points)
    for tip,pip in zip((4,8,12,16,20),(3,6,10,14,18)):
        points[pip]=(0.5,0.55,0.0); points[tip]=(0.5,0.25 if open_hand else 0.7,0.0)
    return points


def hand(gesture, confidence=0.9, vocabulary="basic_gestures"):
    return Detection("hand", confidence, (0.1,0.1,0.5,0.7), attributes={
        "landmarks": hand_landmarks(), "handedness":"Right",
        "static_gesture":gesture, "dynamic_gesture":None,
        "vocabulary":vocabulary, "confidence":confidence,
    })


def test_vocabulary_registry_and_basic_classifier():
    available={item["key"]:item for item in vocabularies()}
    assert {"basic_gestures","asl_static"} <= set(available)
    assert "excludes" in available["asl_static"]["scope"]
    basic=create_vocabulary("basic_gestures")
    assert basic.classify(hand_landmarks(True))[0] == "open_palm"
    assert normalized_features(hand_landmarks()).shape == (63,)


def test_hand_detector_missing_optional_backend_isolated():
    assert "hand_gesture" in available_detectors()
    detector=create_detector("hand_gesture", {"vocabulary":"basic_gestures"})
    assert detector.status["available"] is False
    assert detector.process(np.zeros((20,20,3),dtype=np.uint8)) == []


def test_gesture_rules_and_stable_sequence_suppress_chatter():
    keys={item["key"] for item in rule_types()}
    assert {"gesture_detected","help_gesture","gesture_sequence"} <= keys
    detected=RuleEngine([RuleConfig(type="gesture_detected",name="palm",cooldown_seconds=0,params={"gestures":["open_palm"]})])
    ctx=FrameContext(camera_id=1,timestamp=1,frame_shape=(10,10),detections=[hand("open_palm")])
    assert detected.evaluate(ctx,now=1)[0].type == "gesture_detected"

    sequence=RuleEngine([RuleConfig(type="gesture_sequence",name="help",cooldown_seconds=0,params={"sequence":["H","I"],"stable_frames":2})])
    outputs=[]; timestamp=1
    for value in ("H","H","H","I","I"):
        ctx=FrameContext(camera_id=2,timestamp=timestamp,frame_shape=(10,10),detections=[hand(value,vocabulary="asl_static")])
        outputs.extend(sequence.evaluate(ctx,now=timestamp)); timestamp+=0.1
    assert [item.type for item in outputs] == ["gesture_sequence"]


def test_asl_adapter_is_unknown_without_operator_supplied_model():
    asl=create_vocabulary("asl_static", {})
    assert asl.available is False
    assert asl.classify(hand_landmarks()) == ("unknown",0.0)


def test_offline_evaluator_reports_measured_scope(tmp_path):
    path=tmp_path/"predictions.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in [
        {"expected":"A","predicted":"A","confidence":.9,"signer":"one"},
        {"expected":"B","predicted":"unknown","confidence":.2,"signer":"two"},
    ]))
    result=subprocess.run([".venv/bin/python","scripts/evaluate_gestures.py",str(path)],capture_output=True,text=True,timeout=10,check=True)
    report=json.loads(result.stdout)
    assert report["samples"] == 2 and report["accuracy"] == .5 and report["unknown_rate"] == .5


def test_detector_scope_and_fps_are_generic_plugin_controls():
    from guardlens.detectors import Detector, register, create_detector
    from guardlens.types import Detection

    @register
    class ScopedDetector(Detector):
        key = "test_scoped_detector"
        def setup(self, config): pass
        def process(self, frame): return [Detection("scoped", 1, (0, 0, 1, 1))]

    detector = create_detector("test_scoped_detector", {"camera_ids": [2], "fps": 2})
    assert not detector.should_process(1, 1.0)
    assert detector.should_process(2, 1.0)
    assert not detector.should_process(2, 1.2)
    assert detector.should_process(2, 1.5)
