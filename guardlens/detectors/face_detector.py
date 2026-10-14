"""CPU face detector behind the Detector plugin contract. Backends: ``yunet`` (default when its model is installed) and
the older OpenCV ``opencv`` Haar cascade, which is the automatic fallback.

The backend seam intentionally isolates detection/embedding. A future InsightFace or face_recognition implementation can
emit the same Detection attributes without changing the pipeline, rule engine, APIs, or dashboard.

YuNet (OpenCV Zoo, MIT licence) is a small CNN: on a 29-face test photo it finds all 29 where the Haar cascade finds 24 and
boxes them tighter. Its model file is an explicit setup step: ``python scripts/setup_face_model.py`` (checksum-verified).
"""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from guardlens.config import ROOT
from guardlens.detectors import Detector, register
from guardlens.detectors._face_runtime import face_runtime
from guardlens.types import Detection

logger = logging.getLogger("guardlens.detectors.face")

YUNET_FILE = "face_detection_yunet_2023mar.onnx"
YUNET_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/" + YUNET_FILE


def default_model_path(data_dir: str | Path | None = None) -> Path:
    from guardlens.config import load_config
    return Path(data_dir or load_config().data_dir) / "models" / YUNET_FILE


@register
class FaceDetector(Detector):
    key = "face"

    def setup(self, config: dict) -> None:
        wanted = config.get("backend", "yunet")
        self._yunet = None
        self.backend = "opencv"
        if wanted == "yunet":
            model = Path(config.get("model") or default_model_path())
            if not model.is_absolute():
                model = ROOT / model
            if model.is_file():
                self._score = float(config.get("score_threshold", 0.7))
                self._nms = float(config.get("nms_threshold", 0.3))
                self._yunet = cv2.FaceDetectorYN.create(str(model), "", (320, 320), self._score, self._nms, 5000)
                self.backend = "yunet"
            else:
                logger.warning("Face model %s is not installed: using the older OpenCV detector, which misses faces and "
                               "sees false ones. Install it with: python scripts/setup_face_model.py", model)
        # Smallest face (pixels) to report. YuNet is accurate on small faces; the Haar cascade is not.
        self._min_size = int(config.get("min_size", 20 if self.backend == "yunet" else 40))
        if self.backend == "opencv":
            cascade_path = config.get("cascade") or (cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self._cascade = cv2.CascadeClassifier(cascade_path)
            if self._cascade.empty():
                raise RuntimeError(f"cannot load face cascade: {cascade_path}")
            self._scale_factor = float(config.get("scale_factor", 1.1))
            self._min_neighbors = int(config.get("min_neighbors", 8))
        # Keep a face only when it sits inside a detected person (needs the object detector on the same camera). The
        # Haar cascade needs this guard (it fires on rooftops and foliage); YuNet rarely does, so it is off by default there.
        self.require_person = bool(config.get("require_person", self.backend == "opencv"))

    def _boxes(self, frame: np.ndarray) -> list[tuple]:
        height, width = frame.shape[:2]
        if self._yunet is not None:
            self._yunet.setInputSize((width, height))
            _, rows = self._yunet.detect(frame)
            found = [] if rows is None else [(int(r[0]), int(r[1]), int(r[2]), int(r[3]), float(r[-1]), r) for r in rows]
        else:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._cascade.detectMultiScale(gray, scaleFactor=self._scale_factor, minNeighbors=self._min_neighbors,
                                                   minSize=(self._min_size, self._min_size))
            found = [(int(x), int(y), int(w), int(h), 1.0, None) for x, y, w, h in faces]
        return [b for b in found if min(b[2], b[3]) >= self._min_size]

    def process(self, frame: np.ndarray) -> list[Detection]:
        height, width = frame.shape[:2]
        output = []
        for x, y, w, h, score, row in self._boxes(frame):
            x, y = max(0, x), max(0, y)
            crop = frame[y:y + h, x:x + w]
            if crop.size == 0:
                continue
            person_id, name, watchlist, match = face_runtime.match(face_runtime.embed_detection(frame, row, crop))
            output.append(Detection(
                class_name="face", confidence=round(min(1.0, max(0.0, score)), 3),
                bbox=(x / width, y / height, min(1.0, (x + w) / width), min(1.0, (y + h) / height)),
                attributes={"person_id": person_id, "name": name, "watchlist": watchlist,
                            "match_score": round(match, 3), "backend": self.backend},
            ))
        return output
