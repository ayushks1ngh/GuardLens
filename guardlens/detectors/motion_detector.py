"""MOG2 motion detector plugin with configurable filtering and zones."""
from __future__ import annotations

import cv2
import numpy as np

from guardlens.detectors import Detector, register
from guardlens.types import Detection


@register
class MotionDetector(Detector):
    key = "motion"

    def __init__(self) -> None:
        self._subtractors = {}
        self._frames = {}
        self._history = 300
        self._variance = 16.0
        self._shadows = True
        self._min_area = 0.01
        self._threshold = 200
        self._kernel = 3
        self._warmup = 15
        self._learning_rate = -1.0

    def setup(self, config: dict) -> None:
        self._history = int(config.get("history", 300))
        self._variance = float(config.get("variance_threshold", 16.0))
        self._shadows = bool(config.get("detect_shadows", True))
        self._min_area = float(config.get("min_area", 0.01))
        self._threshold = int(config.get("mask_threshold", 200))
        self._kernel = max(1, int(config.get("morphology_kernel", 3)))
        self._warmup = max(0, int(config.get("warmup_frames", 15)))
        self._learning_rate = float(config.get("learning_rate", -1.0))
        self._subtractors.clear()
        self._frames.clear()

    def process(self, frame: np.ndarray) -> list[Detection]:
        return self.process_for_camera(0, frame)

    def process_for_camera(self, camera_id: int, frame: np.ndarray) -> list[Detection]:
        if frame is None:
            return []
        subtractor = self._subtractors.get(camera_id)
        if subtractor is None:
            subtractor = cv2.createBackgroundSubtractorMOG2(
                history=self._history,
                varThreshold=self._variance,
                detectShadows=self._shadows,
            )
            self._subtractors[camera_id] = subtractor
            self._frames[camera_id] = 0
        height, width = frame.shape[:2]
        mask = subtractor.apply(frame, learningRate=self._learning_rate)
        self._frames[camera_id] += 1
        if self._frames[camera_id] <= self._warmup:
            return []
        _, mask = cv2.threshold(mask, self._threshold, 255, cv2.THRESH_BINARY)
        kernel = np.ones((self._kernel, self._kernel), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        detections = []
        frame_area = float(width * height)
        for contour in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            x, y, w, h = cv2.boundingRect(contour)
            area = (w * h) / frame_area
            if area < self._min_area:
                continue
            detections.append(Detection(
                class_name="motion",
                confidence=min(1.0, area / max(self._min_area, 1e-6)),
                bbox=(x / width, y / height, (x + w) / width, (y + h) / height),
                attributes={"area_ratio": round(area, 5)},
            ))
        return detections
