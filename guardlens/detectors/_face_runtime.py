"""Face enrolment cache, embeddings and matching.

Recognition backends: ``sface`` (OpenCV's SFace network on a YuNet-aligned face; used when its model file is installed)
and ``pixels`` (a 32x32 grey-pixel vector; the fallback, easily fooled by lighting). On a 29-face photo under lighting,
shift and blur changes SFace at threshold 0.5 recognised the same face 98.9% of the time and matched strangers 0.25% of
the time; the pixel method at its 0.82 threshold recognised only 62%.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from sqlmodel import Session, select

from guardlens.events import FaceImage, Person, Setting, get_engine

logger = logging.getLogger("guardlens.faces")

SFACE_DIM = 128
THRESHOLDS = {"sface": 0.5, "pixels": 0.82}


def faces_on_people(detections: list) -> list:
    """Drop face detections whose centre is not inside any detected person.

    Haar cascades fire on rooftops, foliage and luggage; a real face belongs to a person box.
    Only called when a person-capable detector ran on the same frame.
    """
    people = [d.bbox for d in detections if d.class_name == "person"]

    def on_person(box) -> bool:
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        return any(p[0] <= cx <= p[2] and p[1] <= cy <= p[3] for p in people)

    return [d for d in detections if d.class_name != "face" or on_person(d.bbox)]


def _unit(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


class FaceRuntime:
    def __init__(self):
        self._lock = threading.Lock()
        self._cv_lock = threading.Lock()  # OpenCV's network objects are not thread-safe
        self._entries: list[tuple[int, str, bool, np.ndarray]] = []
        self.faces_dir = Path("data/faces")
        self.threshold = THRESHOLDS["pixels"]
        self._sface = None
        self._yunet = None

    # -- setup ----------------------------------------------------------------------------------------------------
    def configure(self, faces_dir: Path, threshold: Optional[float] = None, models_dir: Optional[Path] = None):
        from guardlens import models
        from guardlens.detectors.face_detector import YUNET_FILE

        self.faces_dir = Path(faces_dir); self.faces_dir.mkdir(parents=True, exist_ok=True)
        self._sface = self._yunet = None
        if models_dir is not None:
            sface, yunet = Path(models_dir) / models.SFACE_FILE, Path(models_dir) / YUNET_FILE
            if sface.is_file() and yunet.is_file():
                try:
                    self._sface = cv2.FaceRecognizerSF.create(str(sface), "")
                    self._yunet = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.7, 0.3, 5000)
                except cv2.error:
                    logger.exception("Could not load the face recognition model; using the simple pixel method")
                    self._sface = self._yunet = None
            else:
                logger.warning("Face recognition model not installed: using the older, less accurate pixel method. "
                               "Install it with: python scripts/setup_face_model.py")
        self.threshold = threshold if threshold is not None else THRESHOLDS[self.backend]
        self.reload()

    @property
    def backend(self) -> str:
        return "sface" if self._sface is not None else "pixels"

    @property
    def dimension(self) -> int:
        return SFACE_DIM if self._sface is not None else 32 * 32

    # -- embeddings -----------------------------------------------------------------------------------------------
    @staticmethod
    def embedding(face_bgr: np.ndarray) -> np.ndarray:
        """The simple pixel embedding (fallback backend)."""
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY) if face_bgr.ndim == 3 else face_bgr
        vec = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32).reshape(-1)
        vec -= vec.mean()
        return _unit(vec)

    def embed_detection(self, frame: np.ndarray, row: Optional[np.ndarray], crop: np.ndarray) -> np.ndarray:
        """Embedding for a face found in ``frame``: ``row`` is YuNet's detection row (15 numbers), when there is one."""
        if self._sface is not None and row is not None:
            with self._cv_lock:
                return _unit(self._sface.feature(self._sface.alignCrop(frame, np.asarray(row, dtype=np.float32))))
        return self.embedding(crop) if self._sface is None else self._embed_unaligned(crop)

    def _embed_unaligned(self, crop: np.ndarray) -> np.ndarray:
        with self._cv_lock:
            return _unit(self._sface.feature(cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)))

    def embed_image(self, image: np.ndarray) -> tuple[np.ndarray, bool]:
        """Embed the largest face in an uploaded or stored picture. Returns (embedding, a face was found).

        A picture with no detectable face (e.g. an already tightly cropped photo) is embedded whole.
        """
        h, w = image.shape[:2]
        if self._yunet is not None:
            with self._cv_lock:
                self._yunet.setInputSize((w, h))
                _, rows = self._yunet.detect(image)
            if rows is not None and len(rows):
                row = max(rows, key=lambda r: r[2] * r[3])
                return self.embed_detection(image, row, image), True
        else:
            cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            boxes = cascade.detectMultiScale(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 1.1, 5, minSize=(40, 40))
            if len(boxes):
                x, y, bw, bh = max(boxes, key=lambda b: b[2] * b[3])
                return self.embedding(image[y:y + bh, x:x + bw]), True
        return (self._embed_unaligned(image) if self._sface is not None else self.embedding(image)), False

    # -- enrolled people ------------------------------------------------------------------------------------------
    def reload(self):
        with Session(get_engine()) as session:
            rows = session.exec(select(FaceImage, Person).join(Person, FaceImage.person_id == Person.id)).all()
            entries = []
            for img, person in rows:
                vec = np.asarray(img.embedding, dtype=np.float32)
                if vec.size != self.dimension:  # enrolled under another method: re-embed from the saved picture
                    fresh = self._reembed(img)
                    if fresh is not None:
                        img.embedding = fresh.tolist(); session.add(img); vec = fresh
                entries.append((person.id, person.name, person.watchlist, vec))
            session.commit()
        with self._lock:
            self._entries = entries

    def _reembed(self, img: FaceImage) -> Optional[np.ndarray]:
        path = self.faces_dir / img.image_path
        image = cv2.imread(str(path)) if path.is_file() else None
        if image is None:
            logger.warning("Cannot re-embed %s: picture missing; this person will not match until re-enrolled", img.image_path)
            return None
        logger.warning("Re-embedding %s for the %s face method", img.image_path, self.backend)
        return self.embed_image(image)[0]

    def match(self, embedding: np.ndarray):
        with self._lock:
            entries = list(self._entries)
        best, score = None, -1.0
        for person_id, name, watchlist, known in entries:
            if known.shape != embedding.shape:
                continue
            current = float(np.dot(_unit(embedding), _unit(known)))
            if current > score:
                best, score = (person_id, name, watchlist), current
        return (*best, score) if best and score >= self.threshold else (None, "unknown", False, max(score, 0.0))

    def policy(self) -> str:
        with Session(get_engine()) as session:
            setting = session.get(Setting, "face_policy")
            return setting.value if setting else "label_only"


face_runtime = FaceRuntime()
