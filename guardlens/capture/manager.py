"""Camera manager: owns capture workers and keeps them in sync with the DB.

Single source of truth at runtime for which cameras are running. The analysis
pipeline (Phase 2+) reads latest frames from here.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from sqlmodel import Session, select

from guardlens.capture.worker import CaptureWorker
from guardlens.events import Camera, get_engine

logger = logging.getLogger("guardlens.capture.manager")


class CameraManager:
    def __init__(self):
        self._workers: dict[int, CaptureWorker] = {}
        self._lock = threading.Lock()

    def start_all(self) -> None:
        with Session(get_engine()) as session:
            cameras = session.exec(select(Camera).where(Camera.enabled == True)).all()  # noqa: E712
        for cam in cameras:
            self.start_camera(cam.id, cam.source)

    def start_camera(self, camera_id: int, source: str) -> None:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing:
                existing.stop()
            worker = CaptureWorker(camera_id=camera_id, source=source)
            worker.start()
            self._workers[camera_id] = worker
        logger.info("started worker for camera %s", camera_id)

    def stop_camera(self, camera_id: int) -> None:
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()
            logger.info("stopped worker for camera %s", camera_id)

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()

    def get_worker(self, camera_id: int) -> Optional[CaptureWorker]:
        with self._lock:
            return self._workers.get(camera_id)

    def status(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "camera_id": cid,
                    "connected": w.connected,
                    "fps": round(w.fps, 1),
                }
                for cid, w in self._workers.items()
            ]


# Module-level singleton used by the app and routers.
manager = CameraManager()
