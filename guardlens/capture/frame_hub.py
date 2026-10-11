"""Thread-safe latest-frame channels for push camera transports."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass
class _Channel:
    condition: threading.Condition = field(default_factory=threading.Condition)
    frame: Optional[np.ndarray] = None
    timestamp: float = 0.0
    sequence: int = 0
    closed: bool = False


class FrameHub:
    """Routes publisher frames to source adapters without queues or stale buildup."""

    def __init__(self) -> None:
        self._channels: dict[str, _Channel] = {}
        self._lock = threading.Lock()

    def register(self, stream_id: str) -> None:
        with self._lock:
            channel = self._channels.get(stream_id)
            if channel is None or channel.closed:
                self._channels[stream_id] = _Channel()

    def unregister(self, stream_id: str) -> None:
        with self._lock:
            channel = self._channels.pop(stream_id, None)
        if channel:
            with channel.condition:
                channel.closed = True
                channel.condition.notify_all()

    def exists(self, stream_id: str) -> bool:
        with self._lock:
            return stream_id in self._channels

    def publish(self, stream_id: str, frame: np.ndarray) -> bool:
        with self._lock:
            channel = self._channels.get(stream_id)
        if channel is None or channel.closed:
            return False
        with channel.condition:
            channel.frame = frame.copy()
            channel.timestamp = time.time()
            channel.sequence += 1
            channel.condition.notify_all()
        return True

    def wait_for_frame(
        self, stream_id: str, after_sequence: int = 0, timeout: float = 5.0
    ) -> tuple[Optional[np.ndarray], float, int]:
        with self._lock:
            channel = self._channels.get(stream_id)
        if channel is None:
            return None, 0.0, after_sequence
        deadline = time.monotonic() + timeout
        with channel.condition:
            while (
                not channel.closed
                and channel.sequence <= after_sequence
                and time.monotonic() < deadline
            ):
                channel.condition.wait(max(0.0, deadline - time.monotonic()))
            if channel.closed or channel.frame is None or channel.sequence <= after_sequence:
                return None, 0.0, after_sequence
            return channel.frame.copy(), channel.timestamp, channel.sequence


frame_hub = FrameHub()
