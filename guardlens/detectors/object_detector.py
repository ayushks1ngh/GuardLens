"""Object detection via Ultralytics YOLO (ADR-002).

⚠️ Ultralytics YOLO is AGPL-3.0. It lives strictly *behind* the ``Detector``
interface so it is swappable: point ``model_weights`` at a different model, or
drop in a non-AGPL detector plugin, with no core change (ADR-002 fallback path).

The model is loaded once per process and reused (shared instance, guarded by a
lock) — fixing the original's per-thread reload (architecture §4).
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

from guardlens.detectors import Detector, register
from guardlens.types import Detection

logger = logging.getLogger("guardlens.detectors.object")

# Process-wide shared model cache: weights path -> loaded model.
_MODEL_CACHE: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()
_INFERENCE_LOCKS: dict[str, threading.Lock] = {}


def _load_model(weights: str):
    """Load (or reuse) a YOLO model for the given weights, thread-safely."""
    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(weights)
        if model is None:
            from ultralytics import YOLO  # imported lazily (heavy dep)

            logger.info("loading YOLO model %s", weights)
            model = YOLO(weights)
            _MODEL_CACHE[weights] = model
            _INFERENCE_LOCKS[weights] = threading.Lock()
        return model


@register
class ObjectDetector(Detector):
    """YOLO/COCO object detector producing normalized ``Detection``s."""

    key = "object"

    def __init__(self) -> None:
        self._model = None
        self._weights = "yolov8n.pt"
        self._conf = 0.35
        self._device = "cpu"
        self._infer_lock: Optional[threading.Lock] = None

    def setup(self, config: dict) -> None:
        self._weights = config.get("weights", config.get("model_weights", self._weights))
        self._conf = float(config.get("conf", self._conf))
        self._device = config.get("device", self._device)
        self._model = _load_model(self._weights)
        self._infer_lock = _INFERENCE_LOCKS[self._weights]

    def process(self, frame: np.ndarray) -> list[Detection]:
        if self._model is None or frame is None:
            return []
        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return []
        with self._infer_lock:  # type: ignore[arg-type]
            results = self._model.predict(
                frame, conf=self._conf, device=self._device, verbose=False
            )
        detections: list[Detection] = []
        for res in results:
            names = res.names
            boxes = getattr(res, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                xyxy = box.xyxy[0].tolist()
                x1, y1, x2, y2 = xyxy
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())
                detections.append(
                    Detection(
                        class_name=names.get(cls_id, str(cls_id)),
                        confidence=conf,
                        bbox=(
                            _clamp(x1 / w),
                            _clamp(y1 / h),
                            _clamp(x2 / w),
                            _clamp(y2 / h),
                        ),
                    )
                )
        return detections


def _clamp(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v
