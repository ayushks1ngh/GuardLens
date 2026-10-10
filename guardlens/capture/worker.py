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

import numpy as np

from guardlens.capture.sources import create_source

logger = logging.getLogger("guardlens.capture")


class CaptureWorker:
    def __init__(
        self,
        camera_id: int,
        source: Union[int, str],
        source_type: str = "opencv",
        source_config: Optional[dict] = None,
        shutdown_event: Optional[threading.Event] = None,
        loop_files: bool = True,
        reconnect_backoff: float = 2.0,
        max_backoff: float = 30.0,
    ):
        self.camera_id = camera_id
        self.source = source
        self.source_type = source_type
        self.source_config = dict(source_config or {})
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
        self._width = 0
        self._height = 0
        self._last_error: Optional[str] = None

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

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def resolution(self) -> tuple[int, int]:
        return self._width, self._height

    @property
    def last_frame_age(self) -> Optional[float]:
        if not self._latest_ts:
            return None
        return max(0.0, time.time() - self._latest_ts)

    # --- main loop ---------------------------------------------------------
    def _run(self) -> None:
        backoff = self.reconnect_backoff
        while not self.shutdown_event.is_set():
            try:
                adapter = create_source(
                    self.source_type,
                    self.source_config,
                    legacy_source=self.source,
                )
            except Exception as exc:
                self._connected = False
                self._last_error = str(exc)
                logger.error("[cam %s] invalid source config: %s", self.camera_id, exc)
                break

            if not adapter.open():
                self._connected = False
                self._last_error = adapter.status.error or "source open failed"
                logger.warning(
                    "[cam %s] %s; retrying in %.0fs",
                    self.camera_id, self._last_error, backoff,
                )
                adapter.close()
                if self._wait_or_shutdown(backoff):
                    break
                backoff = min(backoff * 2, self.max_backoff)
                continue

            self._connected = True
            self._last_error = None
            backoff = self.reconnect_backoff
            src_fps = adapter.status.fps or 30.0
            self._width, self._height = adapter.status.width, adapter.status.height
            frame_interval = 1.0 / src_fps if src_fps > 0 else 1.0 / 30.0
            logger.info(
                "[cam %s] connected via %s (%dx%d @ %.1f fps)",
                self.camera_id, self.source_type, self._width, self._height, src_fps,
            )

            last = time.time()
            while not self.shutdown_event.is_set():
                ok, frame = adapter.read()
                if not ok or frame is None:
                    if adapter.is_file and self.loop_files and adapter.rewind():
                        continue
                    self._last_error = "frame read failed; reconnecting"
                    logger.warning("[cam %s] %s", self.camera_id, self._last_error)
                    break
                height, width = frame.shape[:2]
                self._width, self._height = width, height
                with self._lock:
                    self._latest = frame
                    self._latest_ts = time.time()
                self._frames_read += 1

                now = time.time()
                dt = now - last
                last = now
                if dt > 0:
                    inst = 1.0 / dt
                    self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst

                sleep = frame_interval - (time.time() - now)
                if sleep > 0:
                    time.sleep(sleep)

            adapter.close()
            self._connected = False

        self._connected = False
        logger.info("[cam %s] capture stopped", self.camera_id)

    def _wait_or_shutdown(self, seconds: float) -> bool:
        """Sleep up to `seconds`, returning True if shutdown was requested."""
        return self.shutdown_event.wait(timeout=seconds)
