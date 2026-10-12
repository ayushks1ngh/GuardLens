"""Open-vocabulary detector plumbing (model replaced by a fake) and pipeline isolation."""
from __future__ import annotations

import numpy as np
import pytest

from guardlens.detectors import available_detectors, create_detector
from guardlens.detectors.open_vocab_detector import OpenVocabDetector


class _Tensor(list):
    def tolist(self): return list(self)
    def item(self): return self[0]


class _Box:
    def __init__(self, xyxy, cls, conf):
        self.xyxy, self.cls, self.conf = [_Tensor(xyxy)], [_Tensor([cls])], [_Tensor([conf])]


class _Result:
    names = {0: "pen", 1: "purse"}
    boxes = [_Box([10, 20, 50, 80], 0, 0.8), _Box([0, 0, 200, 200], 1, 0.4)]


class _FakeWorld:
    def __init__(self, classes): self.classes = classes
    def predict(self, frame, **kw): return [_Result()]


def test_registered_and_detects_named_objects(monkeypatch):
    assert "open_vocab" in available_detectors()
    monkeypatch.setattr(OpenVocabDetector, "loader", staticmethod(lambda weights, classes: _FakeWorld(classes)))
    detector = create_detector("open_vocab", {"classes": ["pen", " purse "], "fps": 1, "camera_ids": [3]})
    assert detector.classes == ["pen", "purse"] and detector.applies_to(3) and not detector.applies_to(4)
    found = detector.process(np.zeros((100, 100, 3), dtype=np.uint8))
    assert [(d.class_name, round(d.confidence, 1)) for d in found] == [("pen", 0.8), ("purse", 0.4)]
    assert found[0].bbox == (0.1, 0.2, 0.5, 0.8) and found[1].bbox == (0.0, 0.0, 1.0, 1.0)  # clamped
    assert found[0].attributes["open_vocab"] is True
    assert detector.process(None) == []


def test_requires_classes():
    with pytest.raises(ValueError):
        create_detector("open_vocab", {"classes": []})


def test_a_broken_detector_does_not_stop_the_pipeline():
    from guardlens.analysis.pipeline import AnalysisManager
    class Cfg:
        detectors = [{"key": "open_vocab", "classes": []}, {"key": "object"}]
        model_weights = "yolov8n.pt"; device = "cpu"; analyze_fps = 5.0; rules = []
    from fastapi.testclient import TestClient
    from guardlens.app import app
    manager = AnalysisManager()
    with TestClient(app):
        manager.configure(Cfg())
    assert [d.key for d in manager._detectors] == ["object"]  # the bad one was skipped, the good one kept
