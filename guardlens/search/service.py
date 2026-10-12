"""Search index: background embedding of event evidence and hybrid query."""
from __future__ import annotations

import logging
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from sqlmodel import Session, select

from guardlens.events import Camera, Event, EventEmbedding, Setting, get_engine

logger = logging.getLogger("guardlens.search")
_KEY = "search"
DEFAULTS = {"enabled": False, "model": "ViT-B-32", "pretrained": "laion2b_s34b_b79k"}
_TIME_WORDS = re.compile(
    r"\b(yesterday|today|last night|overnight|this morning|this week|past week|last week|"
    r"(in|during|over)? ?the (last|past) \d+ ?(minutes?|mins?|hours?|hrs?|days?)|last hour|past hour)\b", re.I)
_VISION_WEIGHT, _TEXT_WEIGHT = 1.0, 0.35


def split_query(question: str) -> str:
    """Remove time words so only the visual description is embedded."""
    cleaned = _TIME_WORDS.sub(" ", question)
    return re.sub(r"\s+", " ", cleaned).strip() or question.strip()


def _crops(frame: np.ndarray, metadata: dict, limit: int = 3) -> list[np.ndarray]:
    h, w = frame.shape[:2]
    out = []
    for box in (metadata.get("boxes") or [])[:limit]:
        try:
            x1, y1, x2, y2 = box["bbox"]
        except (KeyError, TypeError, ValueError):
            continue
        pad = 0.1
        bw, bh = x2 - x1, y2 - y1
        x1, x2 = max(0.0, x1 - pad * bw), min(1.0, x2 + pad * bw)
        y1, y2 = max(0.0, y1 - pad * bh), min(1.0, y2 + pad * bh)
        crop = frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]
        if crop.shape[0] >= 16 and crop.shape[1] >= 16:
            out.append(crop)
    return out


class SearchService:
    def __init__(self) -> None:
        self._settings = dict(DEFAULTS)
        self._embedder = None
        self._factory: Callable[[dict], object] = None  # set lazily to avoid importing torch at startup
        self._snapshots = Path("data/snapshots")
        self._queue: "queue.Queue[int]" = queue.Queue(maxsize=5000)
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._matrix: Optional[np.ndarray] = None   # cached (n, dim)
        self._owners: list[tuple[int, str]] = []    # (event_id, kind) per matrix row
        self._error = ""
        self._loading = False
        self._reindexing = False

    # -- lifecycle -----------------------------------------------------
    def configure(self, snapshots_dir: Path) -> None:
        self._snapshots = Path(snapshots_dir)
        with Session(get_engine()) as session:
            row = session.get(Setting, _KEY)
        self._settings = {**DEFAULTS, **((row.value or {}) if row else {})}
        self._embedder = None
        self._matrix = None
        if self._settings["enabled"]:
            self._ensure_worker()

    def set_embedder(self, embedder) -> None:
        """Inject an embedder (tests, or a custom backend); skips the model download."""
        self._embedder = embedder

    def update_settings(self, changes: dict) -> dict:
        self._settings = {**self._settings, **changes}
        with Session(get_engine()) as session:
            row = session.get(Setting, _KEY) or Setting(key=_KEY)
            row.value = self._settings
            session.add(row)
            session.commit()
        if "model" in changes or "pretrained" in changes:
            self._embedder = None
        if self._settings["enabled"]:
            self._ensure_worker()
        return self._settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.get("enabled"))

    def _ensure_worker(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="search-index", daemon=True)
        self._thread.start()

    def _get_embedder(self):
        if self._embedder is None:
            self._loading = True
            try:
                from guardlens.search.embedder import create_embedder
                self._embedder = (self._factory or create_embedder)(self._settings)
                self._error = ""
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"[:200]
                logger.exception("could not load the search model")
                raise
            finally:
                self._loading = False
        return self._embedder

    # -- indexing --------------------------------------------------------
    def on_event(self, payload: dict) -> None:
        """Event-store listener."""
        if self.enabled and payload.get("snapshot_path"):
            try:
                self._queue.put_nowait(int(payload["id"]))
            except queue.Full:
                logger.warning("search index queue full; event %s not indexed", payload.get("id"))
            self._ensure_worker()

    def _loop(self) -> None:
        while self.enabled:
            try:
                event_id = self._queue.get(timeout=2)
            except queue.Empty:
                continue
            try:
                self.index_event(event_id)
            except Exception:
                logger.exception("indexing event %s failed", event_id)

    def index_event(self, event_id: int, force: bool = False) -> int:
        """Embed an event's snapshot and crops. Returns the number of vectors stored."""
        embedder = self._get_embedder()
        with Session(get_engine()) as session:
            event = session.get(Event, event_id)
            if event is None or not event.snapshot_path:
                return 0
            existing = session.exec(select(EventEmbedding).where(EventEmbedding.event_id == event_id)).all()
            if existing and not force:
                return 0
            path = self._snapshots / Path(event.snapshot_path).name
            frame = cv2.imread(str(path)) if path.is_file() else None
            if frame is None:
                return 0
            images = [frame] + _crops(frame, event.event_metadata or {})
            kinds = ["frame"] + ["crop"] * (len(images) - 1)
            vectors = embedder.encode_images(images)
            for row in existing:
                session.delete(row)
            for kind, vec in zip(kinds, vectors):
                session.add(EventEmbedding(event_id=event_id, kind=kind, model=embedder.name,
                                           dim=int(vec.shape[0]), vector=vec.astype(np.float32).tobytes()))
            session.commit()
        self._matrix = None  # rebuild cache lazily
        return len(images)

    def reindex_all(self) -> None:
        """Index every event that has a snapshot but no vectors yet (runs in the background)."""
        if self._reindexing:
            return
        self._reindexing = True

        def run():
            try:
                with Session(get_engine()) as session:
                    done = set(session.exec(select(EventEmbedding.event_id)).all())
                    ids = [e for e in session.exec(select(Event.id).where(Event.snapshot_path != None)).all() if e not in done]  # noqa: E711
                for event_id in ids:
                    if not self.enabled:
                        break
                    try:
                        self.index_event(event_id)
                    except Exception:
                        logger.exception("reindex of event %s failed", event_id)
            finally:
                self._reindexing = False

        threading.Thread(target=run, name="search-reindex", daemon=True).start()

    def status(self) -> dict:
        with Session(get_engine()) as session:
            indexed = len(set(session.exec(select(EventEmbedding.event_id)).all()))
            eligible = len(session.exec(select(Event.id).where(Event.snapshot_path != None)).all())  # noqa: E711
        return {
            "enabled": self.enabled, "model": f"{self._settings['model']}/{self._settings['pretrained']}",
            "indexed_events": indexed, "events_with_pictures": eligible,
            "loading": self._loading, "reindexing": self._reindexing,
            "queued": self._queue.qsize(), "error": self._error,
        }

    # -- querying --------------------------------------------------------
    def _load_matrix(self) -> tuple[np.ndarray, list[tuple[int, str]]]:
        with self._lock:
            if self._matrix is None:
                with Session(get_engine()) as session:
                    rows = session.exec(select(EventEmbedding)).all()
                if rows:
                    dim = rows[0].dim
                    rows = [r for r in rows if r.dim == dim]
                    self._matrix = np.stack([np.frombuffer(r.vector, dtype=np.float32) for r in rows])
                    self._owners = [(r.event_id, r.kind) for r in rows]
                else:
                    self._matrix, self._owners = np.zeros((0, 1), dtype=np.float32), []
            return self._matrix, self._owners

    def _rank(self, scores: np.ndarray, owners: list[tuple[int, str]], crop_bonus: float = 0.0) -> dict[int, float]:
        best: dict[int, float] = {}
        for score, (event_id, kind) in zip(scores.tolist(), owners):
            value = score + (crop_bonus if kind == "crop" else 0.0)
            if value > best.get(event_id, -1.0):
                best[event_id] = value
        return best

    def search(self, query: str, *, camera_id: Optional[int] = None, start: Optional[datetime] = None,
               end: Optional[datetime] = None, limit: int = 24) -> list[dict]:
        visual = split_query(query)
        matrix, owners = self._load_matrix()
        vision: dict[int, float] = {}
        if len(owners) and self.enabled:
            vector = self._get_embedder().encode_text(visual)
            if vector.shape[0] == matrix.shape[1]:
                vision = self._rank(matrix @ vector, owners, crop_bonus=0.01)
        words = {w for w in re.findall(r"[a-z0-9]+", visual.lower()) if len(w) > 2}
        with Session(get_engine()) as session:
            stmt = select(Event)
            if camera_id is not None:
                stmt = stmt.where(Event.camera_id == camera_id)
            if start is not None:
                stmt = stmt.where(Event.created_at >= start)
            if end is not None:
                stmt = stmt.where(Event.created_at < end)
            events = {e.id: e for e in session.exec(stmt).all()}
            names = {c.id: c.name for c in session.exec(select(Camera)).all()}
        results = []
        for event_id, event in events.items():
            note = ((event.event_metadata or {}).get("agent") or {}).get("event_triage") or {}
            text = " ".join(str(x) for x in (event.type, note.get("title", ""), note.get("summary", ""),
                                             " ".join(note.get("concerns") or []), names.get(event.camera_id, ""))).lower()
            overlap = sum(1 for w in words if w in text) / len(words) if words else 0.0
            sight = vision.get(event_id)
            if sight is None and overlap == 0:
                continue
            score = _VISION_WEIGHT * (sight or 0.0) + _TEXT_WEIGHT * overlap
            results.append({
                "event_id": event_id, "score": round(float(score), 4),
                "source": "both" if sight is not None and overlap else "picture" if sight is not None else "text",
                "type": event.type, "severity": event.severity, "camera": names.get(event.camera_id, str(event.camera_id)),
                "camera_id": event.camera_id, "created_at": event.created_at.isoformat(),
                "snapshot_path": event.snapshot_path, "title": note.get("title"),
            })
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def similar(self, event_id: int, limit: int = 12) -> list[dict]:
        matrix, owners = self._load_matrix()
        mine = [i for i, (e, k) in enumerate(owners) if e == event_id and k == "frame"]
        if not mine:
            return []
        scores = self._rank(matrix @ matrix[mine[0]], owners)
        scores.pop(event_id, None)
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        with Session(get_engine()) as session:
            names = {c.id: c.name for c in session.exec(select(Camera)).all()}
            out = []
            for other, score in top:
                e = session.get(Event, other)
                if e:
                    out.append({"event_id": other, "score": round(float(score), 4), "source": "picture", "type": e.type,
                                "severity": e.severity, "camera": names.get(e.camera_id, str(e.camera_id)),
                                "camera_id": e.camera_id, "created_at": e.created_at.isoformat(),
                                "snapshot_path": e.snapshot_path, "title": None})
        return out


search_service = SearchService()
