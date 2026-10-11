"""Independent pre/post-roll clip recording and retention service."""
from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("guardlens.recording")


@dataclass
class RecordingOptions:
    enabled: bool = False
    mode: str = "event"  # off | motion | event | continuous
    pre_roll_seconds: float = 5.0
    post_roll_seconds: float = 10.0
    max_clip_seconds: float = 120.0
    segment_seconds: float = 300.0
    retention_days: int = 7
    quota_mb: int = 2048
    codec_preferences: list[str] = field(default_factory=lambda: ["mp4v", "MJPG"])


@dataclass
class _ActiveClip:
    path: Path
    final_path: Path
    writer: object
    started_at: float
    last_trigger_at: float
    fps: float
    event_ids: list[int] = field(default_factory=list)


class ClipRecorder:
    """Consumes raw frames; detectors/rules never write video directly."""

    def __init__(self) -> None:
        self._options = RecordingOptions()
        self._clips_dir = Path("data/clips")
        self._buffers: dict[int, deque[tuple[float, np.ndarray]]] = {}
        self._active: dict[int, _ActiveClip] = {}
        self._errors: dict[int, str] = {}
        self._lock = threading.RLock()

    def configure(self, clips_dir: Path, options) -> None:
        values = options.model_dump() if hasattr(options, "model_dump") else dict(options or {})
        self._options = RecordingOptions(**values)
        if self._options.mode not in {"off", "motion", "event", "continuous"}:
            raise ValueError("recording mode must be off, motion, event, or continuous")
        self._clips_dir = Path(clips_dir)
        self._clips_dir.mkdir(parents=True, exist_ok=True)
        for partial in self._clips_dir.glob("*.partial.*"):
            partial.unlink(missing_ok=True)
        self.prune()

    @property
    def clips_dir(self) -> Path:
        return self._clips_dir

    def on_frame(self, camera_id: int, frame: np.ndarray, timestamp: float, fps: float = 0.0) -> None:
        if not self._options.enabled or self._options.mode == "off" or frame is None:
            return
        with self._lock:
            buffer = self._buffers.setdefault(camera_id, deque())
            buffer.append((timestamp, frame.copy()))
            cutoff = timestamp - self._options.pre_roll_seconds
            while buffer and buffer[0][0] < cutoff:
                buffer.popleft()

            active = self._active.get(camera_id)
            if self._options.mode == "continuous" and active is None:
                active = self._start(camera_id, timestamp, frame, fps or 10.0, [])
            if active:
                try:
                    active.writer.write(frame)
                except Exception as exc:
                    self._errors[camera_id] = f"clip write failed: {exc}"
                    self._close_locked(camera_id)
                    return
                duration = timestamp - active.started_at
                event_done = (
                    self._options.mode != "continuous"
                    and timestamp - active.last_trigger_at >= self._options.post_roll_seconds
                )
                segment_done = (
                    self._options.mode == "continuous"
                    and duration >= self._options.segment_seconds
                )
                if duration >= self._options.max_clip_seconds or event_done or segment_done:
                    self._close_locked(camera_id)

    def trigger(self, camera_id: int, event_id: int, event_type: str, frame: Optional[np.ndarray] = None) -> Optional[str]:
        if not self._options.enabled or self._options.mode in {"off", "continuous"}:
            return None
        if self._options.mode == "motion" and event_type != "motion":
            return None
        now = time.time()
        with self._lock:
            active = self._active.get(camera_id)
            if active:
                active.last_trigger_at = now
                if event_id not in active.event_ids:
                    active.event_ids.append(event_id)
                return active.final_path.name
            buffer = self._buffers.get(camera_id, deque())
            seed = frame if frame is not None else (buffer[-1][1] if buffer else None)
            if seed is None:
                self._errors[camera_id] = "event clip skipped: no frames available"
                return None
            fps = self._estimate_fps(buffer)
            active = self._start(camera_id, now, seed, fps, [event_id])
            if not active:
                return None
            for _, buffered in list(buffer):
                active.writer.write(buffered)
            return active.final_path.name


    def link_event(self, camera_id: int, event_id: int, event_type: str, frame: Optional[np.ndarray] = None) -> Optional[str]:
        """Return the event clip or current continuous segment without exposing writers."""
        with self._lock:
            if self._options.enabled and self._options.mode == "continuous":
                active = self._active.get(camera_id)
                if active:
                    if event_id not in active.event_ids:
                        active.event_ids.append(event_id)
                    return active.final_path.name
        return self.trigger(camera_id, event_id, event_type, frame)
    def _start(self, camera_id: int, timestamp: float, frame: np.ndarray, fps: float, event_ids: list[int]) -> Optional[_ActiveClip]:
        self.prune()
        if shutil.disk_usage(self._clips_dir).free < 50 * 1024 * 1024:
            self._errors[camera_id] = "clip recording disabled: less than 50 MB free"
            return None
        height, width = frame.shape[:2]
        for codec in self._options.codec_preferences:
            extension = ".avi" if codec == "MJPG" else ".mp4"
            base = f"cam-{camera_id}-{int(timestamp)}-{uuid.uuid4().hex[:8]}"
            final_path = self._clips_dir / f"{base}{extension}"
            path = self._clips_dir / f"{base}.partial{extension}"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), max(1.0, fps), (width, height))
            if writer.isOpened():
                active = _ActiveClip(path, final_path, writer, timestamp, timestamp, max(1.0, fps), event_ids)
                self._active[camera_id] = active
                self._errors.pop(camera_id, None)
                return active
            writer.release()
            path.unlink(missing_ok=True)
        self._errors[camera_id] = "no configured video codec could be opened"
        return None

    @staticmethod
    def _estimate_fps(buffer: deque[tuple[float, np.ndarray]]) -> float:
        if len(buffer) < 2:
            return 10.0
        duration = buffer[-1][0] - buffer[0][0]
        return max(1.0, min(60.0, (len(buffer) - 1) / duration)) if duration > 0 else 10.0

    def stop_camera(self, camera_id: int) -> None:
        with self._lock:
            self._close_locked(camera_id)
            self._buffers.pop(camera_id, None)

    def stop_all(self) -> None:
        with self._lock:
            for camera_id in list(self._active):
                self._close_locked(camera_id)
            self._buffers.clear()

    def _close_locked(self, camera_id: int) -> None:
        active = self._active.pop(camera_id, None)
        if active:
            active.writer.release()
            if active.path.is_file() and active.path.stat().st_size > 0:
                active.path.replace(active.final_path)
            else:
                active.path.unlink(missing_ok=True)

    def status(self) -> dict:
        with self._lock:
            return {
                "enabled": self._options.enabled,
                "mode": self._options.mode,
                "active": {camera_id: clip.final_path.name for camera_id, clip in self._active.items()},
                "errors": dict(self._errors),
                "clips": len(list(self._clips_dir.glob("*"))) if self._clips_dir.exists() else 0,
            }

    def prune(self, now: Optional[float] = None) -> int:
        if not self._clips_dir.exists():
            return 0
        now = time.time() if now is None else now
        active_paths = {clip.path for clip in self._active.values()}
        files = [p for p in self._clips_dir.iterdir() if p.is_file() and p not in active_paths]
        removed = 0
        cutoff = now - self._options.retention_days * 86400
        for path in files:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True); removed += 1
        files = sorted(
            (p for p in self._clips_dir.iterdir() if p.is_file() and p not in active_paths),
            key=lambda path: path.stat().st_mtime,
        )
        total = sum(path.stat().st_size for path in files)
        quota = self._options.quota_mb * 1024 * 1024
        for path in files:
            if total <= quota:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True); total -= size; removed += 1
        return removed


clip_recorder = ClipRecorder()
