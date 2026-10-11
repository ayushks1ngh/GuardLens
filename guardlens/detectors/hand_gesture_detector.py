"""Optional MediaPipe hand-landmark detector with pluggable vocabularies."""
from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from guardlens.detectors import Detector, register
from guardlens.gestures import create_vocabulary
from guardlens.types import Detection

logger = logging.getLogger("guardlens.detectors.hand")


@register
class HandGestureDetector(Detector):
    key = "hand_gesture"

    def __init__(self) -> None:
        self._available = False
        self._reason = "not configured"
        self._landmarker = None
        self._vocabulary = None

    def setup(self, config: dict[str, Any]) -> None:
        vocabulary_key = config.get("vocabulary", "basic_gestures")
        self._vocabulary = create_vocabulary(vocabulary_key, config.get("vocabulary_config", {}))
        model_path = str(config.get("landmarker_model", ""))
        try:
            import mediapipe as mp
            if not model_path:
                self._reason = "landmarker_model is required; no model is downloaded implicitly"
                logger.warning("hand gesture detector disabled: %s", self._reason)
                return
            options = mp.tasks.vision.HandLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=model_path),
                running_mode=mp.tasks.vision.RunningMode.IMAGE,
                num_hands=int(config.get("max_hands", 2)),
                min_hand_detection_confidence=float(config.get("min_detection_confidence", 0.5)),
                min_hand_presence_confidence=float(config.get("min_presence_confidence", 0.5)),
            )
            self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
            self._mp = mp
            self._available = True
            self._reason = ""
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self._reason = str(exc)
            logger.warning("hand gesture detector disabled: %s", exc)

    @property
    def status(self) -> dict:
        return {"available": self._available, "reason": self._reason}

    def process(self, frame: np.ndarray) -> list[Detection]:
        if not self._available or self._landmarker is None or frame is None:
            return []
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect(image)
        output = []
        for index, hand in enumerate(result.hand_landmarks):
            landmarks = [(float(p.x), float(p.y), float(p.z)) for p in hand]
            xs = [p[0] for p in landmarks]; ys = [p[1] for p in landmarks]
            gesture, confidence = self._vocabulary.classify(landmarks)
            handedness = "unknown"
            if index < len(result.handedness) and result.handedness[index]:
                handedness = result.handedness[index][0].category_name
            output.append(Detection(
                class_name="hand", confidence=max(0.0, min(1.0, confidence or 1.0)),
                bbox=(max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys))),
                attributes={
                    "landmarks": landmarks,
                    "handedness": handedness,
                    "static_gesture": gesture,
                    "dynamic_gesture": None,
                    "vocabulary": self._vocabulary.key,
                    "confidence": confidence,
                    "scope": self._vocabulary.scope,
                },
            ))
        return output

    def teardown(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
