"""Browser/WebRTC push source backed by the process-wide latest-frame hub."""
from __future__ import annotations

from typing import Any

from guardlens.capture.frame_hub import frame_hub
from guardlens.capture.sources import CameraSource, register_source


@register_source
class WebRtcSource(CameraSource):
    key = "webrtc"
    label = "Paired phone or laptop browser"
    modes = [{
        "key": "publisher",
        "label": "Secure browser publisher",
        "fields": [
            {"key": "stream_id", "label": "Stream ID", "type": "text", "required": True},
            {"key": "frame_timeout_ms", "label": "Frame timeout", "type": "integer", "default": 5000},
        ],
    }]

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._stream_id = config["stream_id"]
        self._sequence = 0

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        clean = dict(config)
        clean["mode"] = "publisher"
        stream_id = str(clean.get("stream_id") or "").strip()
        if not stream_id or len(stream_id) > 128:
            raise ValueError("stream_id is required and must be at most 128 characters")
        if not all(char.isalnum() or char in "-_" for char in stream_id):
            raise ValueError("stream_id may contain only letters, numbers, hyphens, and underscores")
        timeout = int(clean.get("frame_timeout_ms", 5000))
        if timeout < 250 or timeout > 30000:
            raise ValueError("frame_timeout_ms must be between 250 and 30000")
        clean["stream_id"] = stream_id
        clean["frame_timeout_ms"] = timeout
        return clean

    def open(self) -> bool:
        if not frame_hub.exists(self._stream_id):
            self.status.opened = False
            self.status.error = "waiting for paired browser publisher"
            return False
        self.status.opened = True
        self.status.error = None
        return True

    def read(self):
        frame, _, sequence = frame_hub.wait_for_frame(
            self._stream_id,
            after_sequence=self._sequence,
            timeout=self.config["frame_timeout_ms"] / 1000.0,
        )
        if frame is None:
            self.status.error = "browser publisher frame timeout"
            return False, None
        self._sequence = sequence
        height, width = frame.shape[:2]
        self.status.width, self.status.height = width, height
        self.status.error = None
        return True, frame

    def close(self) -> None:
        self.status.opened = False

    @property
    def display_source(self) -> str:
        return f"webrtc:{self._stream_id[:8]}"

    @property
    def legacy_source(self) -> str:
        return self.display_source
