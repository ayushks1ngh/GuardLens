"""OpenCV CPU face detector backend behind the Detector plugin contract.

The backend seam intentionally isolates detection/embedding. A future
InsightFace or face_recognition implementation can emit the same Detection
attributes without changing the pipeline, rule engine, APIs, or dashboard.
"""
from __future__ import annotations

import cv2
import numpy as np

from guardlens.detectors import Detector, register
from guardlens.detectors._face_runtime import face_runtime
from guardlens.types import Detection


@register
class FaceDetector(Detector):
    key = "face"

    def setup(self, config: dict) -> None:
        cascade_path = config.get("cascade") or (cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self._cascade = cv2.CascadeClassifier(cascade_path)
        if self._cascade.empty():
            raise RuntimeError(f"cannot load face cascade: {cascade_path}")
        self._scale_factor = float(config.get("scale_factor", 1.1))
        self._min_neighbors = int(config.get("min_neighbors", 8))
        # Keep a face only when it sits inside a detected person (needs the object detector on the same camera).
        self.require_person = bool(config.get("require_person", True))
        self._min_size = int(config.get("min_size", 40))
        self._backend = config.get("backend", "opencv")

    def process(self, frame: np.ndarray) -> list[Detection]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=self._scale_factor, minNeighbors=self._min_neighbors,
            minSize=(self._min_size, self._min_size),
        )
        height, width = frame.shape[:2]
        output = []
        for x, y, w, h in faces:
            crop = frame[y:y+h, x:x+w]
            person_id, name, watchlist, score = face_runtime.match(face_runtime.embedding(crop))
            output.append(Detection(
                class_name="face", confidence=1.0,
                bbox=(x/width, y/height, (x+w)/width, (y+h)/height),
                attributes={
                    "person_id": person_id, "name": name, "watchlist": watchlist,
                    "match_score": round(score, 3), "backend": self._backend,
                },
            ))
        return output
