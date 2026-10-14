"""CPU-safe face enrollment cache and embedding helpers."""
from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np
from sqlmodel import Session, select

from guardlens.events import FaceImage, Person, Setting, get_engine


class FaceRuntime:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: list[tuple[int, str, bool, np.ndarray]] = []
        self.faces_dir = Path("data/faces")
        self.threshold = 0.82

    def configure(self, faces_dir: Path, threshold: float = 0.82):
        self.faces_dir = Path(faces_dir); self.faces_dir.mkdir(parents=True, exist_ok=True)
        self.threshold = threshold
        self.reload()

    @staticmethod
    def embedding(face_bgr: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY) if face_bgr.ndim == 3 else face_bgr
        vec = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32).reshape(-1)
        vec -= vec.mean()
        norm = np.linalg.norm(vec)
        return vec / norm if norm else vec

    def reload(self):
        with Session(get_engine()) as session:
            rows = session.exec(select(FaceImage, Person).join(Person, FaceImage.person_id == Person.id)).all()
        entries = [(person.id, person.name, person.watchlist, np.asarray(img.embedding, dtype=np.float32)) for img, person in rows]
        with self._lock: self._entries = entries

    def match(self, embedding: np.ndarray):
        with self._lock: entries = list(self._entries)
        best, score = None, -1.0
        for person_id, name, watchlist, known in entries:
            if known.shape != embedding.shape: continue
            current = float(np.dot(embedding, known))
            if current > score: best, score = (person_id, name, watchlist), current
        return (*best, score) if best and score >= self.threshold else (None, "unknown", False, max(score, 0.0))

    def policy(self) -> str:
        with Session(get_engine()) as session:
            setting = session.get(Setting, "face_policy")
            return setting.value if setting else "label_only"


face_runtime = FaceRuntime()


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
