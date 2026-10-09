"""Camera capture worker (see docs/02-architecture.md §2.1).

One worker per camera, running in its own thread. Keeps only the LATEST frame
(drops stale frames so the live view never lags). Reconnects with backoff on
stream drop. Video files are looped so they behave like a continuous feed —
ideal for development/testing against sample footage.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional, Union

import cv2
import numpy as np

logger = logging.getLogger("guardlens.capture")


class CaptureWorker:
    def __init__(
        self,
        camera_id: int,
        source: Union[int, str],
        shutdown_event: Optional[threading.Event] = None,
        loop_files: bool = True,
        reconnect_backoff: float = 2.0,
        max_backoff: float = 30.0,
    ):
        self.camera_id = camera_id
        self.source = source
        self.shutdown_event = shutdown_event or threading.Event()
        self.loop_files = loop_files
        self.reconnect_backoff = reconnect_backoff
        self.max_backoff = max_backoff

        self._lock = threading.Lock()
        self._latest: Optional[np.ndarray] = None
        self._latest_ts: float = 0.0
        self._connected = False
        self._fps: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._frames_read = 0

    # --- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.shutdown_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"capture-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.shutdown_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    # --- accessors ---------------------------------------------------------
    def get_latest(self) -> tuple[Optional[np.ndarray], float]:
        with self._lock:
            if self._latest is None:
                return None, 0.0
            return self._latest.copy(), self._latest_ts

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def fps(self) -> float:
        return self._fps

    def _resolve_source(self) -> Union[int, str]:
        s = self.source
        if isinstance(s, str) and s.isdigit():
            return int(s)
        return s

    def _is_file(self) -> bool:
        s = self.source
        return isinstance(s, str) and not s.isdigit() and "://" not in s

    # --- main loop ---------------------------------------------------------
    def _run(self) -> None:
        backoff = self.reconnect_backoff
        while not self.shutdown_event.is_set():
            src = self._resolve_source()
            cap = cv2.VideoCapture(src)
            if not cap.isOpened():
                self._connected = False
                logger.warning(
                    "[cam %s] cannot open source %r; retrying in %.0fs",
                    self.camera_id, self.source, backoff,
                )
                if self._wait_or_shutdown(backoff):
                    cap.release()
                    break
                backoff = min(backoff * 2, self.max_backoff)
                continue

            self._connected = True
            backoff = self.reconnect_backoff  # reset on success
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_interval = 1.0 / src_fps if src_fps > 0 else 1.0 / 30.0
            logger.info("[cam %s] connected (%.1f fps source)", self.camera_id, src_fps)

            last = time.time()
            while not self.shutdown_event.is_set():
                ok, frame = cap.read()
                if not ok or frame is None:
                    if self._is_file() and self.loop_files:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # loop sample video
                        continue
                    logger.warning("[cam %s] stream dropped; reconnecting", self.camera_id)
                    break
                with self._lock:
                    self._latest = frame
                    self._latest_ts = time.time()
                self._frames_read += 1

                # measured FPS (EMA)
                now = time.time()
                dt = now - last
                last = now
                if dt > 0:
                    inst = 1.0 / dt
                    self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst

                # pace to roughly source fps to avoid pegging a CPU core
                sleep = frame_interval - (time.time() - now)
                if sleep > 0:
                    time.sleep(sleep)

            cap.release()
            self._connected = False

        self._connected = False
        logger.info("[cam %s] capture stopped", self.camera_id)

    def _wait_or_shutdown(self, seconds: float) -> bool:
        """Sleep up to `seconds`, returning True if shutdown was requested."""
        return self.shutdown_event.wait(timeout=seconds)
