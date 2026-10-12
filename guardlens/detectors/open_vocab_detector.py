"""Open-vocabulary detector (YOLO-World): detect objects by *name*, no training.

Configure the words to look for, e.g. ``classes: [pen, purse, knife, blade]``. Heavier than the
default detector, so scope it with ``camera_ids`` and a low ``fps`` (see docs/07). The text
encoder and weights download on first use; if that fails only this detector is skipped.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

import numpy as np

from guardlens.detectors import Detector, register
from guardlens.types import Detection

logger = logging.getLogger("guardlens.detectors.open_vocab")


def _load_world(weights: str, classes: list[str]):
    from ultralytics import YOLOWorld  # heavy import, kept lazy
    model = YOLOWorld(weights)
    model.set_classes(classes)
    return model


@register
class OpenVocabDetector(Detector):
    """YOLO-World detector for arbitrary named objects."""

    key = "open_vocab"
    loader: Callable = staticmethod(_load_world)  # replaceable in tests

    def __init__(self) -> None:
        self._model = None
        self._conf = 0.25
        self._device = "cpu"
        self._imgsz = 640
        self._lock = threading.Lock()
        self.classes: list[str] = []

    def setup(self, config: dict) -> None:
        self.classes = [str(c).strip() for c in config.get("classes", []) if str(c).strip()]
        if not self.classes:
            raise ValueError("open_vocab needs a non-empty `classes` list, e.g. [pen, purse]")
        self._conf = float(config.get("conf", self._conf))
        self._device = config.get("device", self._device)
        self._imgsz = int(config.get("imgsz", self._imgsz))
        self._model = self.loader(config.get("weights", "yolov8s-worldv2.pt"), self.classes)

    def process(self, frame: np.ndarray) -> list[Detection]:
        if self._model is None or frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        with self._lock:
            results = self._model.predict(frame, conf=self._conf, device=self._device, imgsz=self._imgsz, verbose=False)
        out: list[Detection] = []
        for res in results:
            boxes = getattr(res, "boxes", None)
            if boxes is None:
                continue
            names = res.names
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                cls = int(box.cls[0].item())
                out.append(Detection(
                    class_name=names.get(cls, self.classes[cls] if cls < len(self.classes) else str(cls)),
                    confidence=float(box.conf[0].item()),
                    bbox=tuple(min(1.0, max(0.0, v)) for v in (x1 / w, y1 / h, x2 / w, y2 / h)),
                    attributes={"open_vocab": True},
                ))
        return out
