"""OpenCV pull-source adapter: host devices, files, RTSP, HTTP and MJPEG."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import cv2

from guardlens.capture.sources import CameraSource, register_source


@register_source
class OpenCvSource(CameraSource):
    key = "opencv"
    label = "Local, file, RTSP or HTTP camera"
    modes = [
        {
            "key": "device",
            "label": "Camera attached to the GuardLens computer",
            "fields": [
                {"key": "device_index", "label": "Device index", "type": "integer", "default": 0},
            ],
        },
        {
            "key": "network",
            "label": "IP camera / phone camera URL",
            "fields": [
                {"key": "url", "label": "RTSP, HTTP or MJPEG URL", "type": "url", "required": True},
            ],
        },
        {
            "key": "file",
            "label": "Video file or bundled sample",
            "fields": [
                {"key": "path", "label": "Video path", "type": "text", "required": True},
            ],
        },
    ]

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._capture = None
        self._mode = config["mode"]
        self._value = self._resolve_value(config)

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        clean = dict(config)
        source = clean.get("source")
        mode = clean.get("mode") or cls._infer_mode(source)
        if mode not in {"device", "network", "file"}:
            raise ValueError("mode must be device, network, or file")
        clean["mode"] = mode

        if mode == "device":
            raw = clean.get("device_index", source if source is not None else 0)
            try:
                index = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("device_index must be an integer") from exc
            if index < 0 or index > 99:
                raise ValueError("device_index must be between 0 and 99")
            clean["device_index"] = index
        elif mode == "network":
            url = str(clean.get("url") or source or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in {"rtsp", "rtsps", "http", "https"} or not parsed.netloc:
                raise ValueError("network URL must use rtsp://, rtsps://, http://, or https://")
            clean["url"] = url
        else:
            path = str(clean.get("path") or source or "").strip()
            if not path:
                raise ValueError("file path is required")
            clean["path"] = path

        timeout = int(clean.get("timeout_ms", 5000))
        if timeout < 250 or timeout > 30000:
            raise ValueError("timeout_ms must be between 250 and 30000")
        clean["timeout_ms"] = timeout
        # ``source`` is only a legacy input bridge. Persist one canonical typed
        # value (device_index/url/path) so credentials cannot leak via a duplicate.
        clean.pop("source", None)
        return clean

    @staticmethod
    def _infer_mode(source: Any) -> str:
        if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
            return "device"
        value = str(source or "")
        if "://" in value:
            return "network"
        return "file"

    @staticmethod
    def _resolve_value(config: dict[str, Any]):
        mode = config["mode"]
        if mode == "device":
            return int(config["device_index"])
        return config["url"] if mode == "network" else config["path"]

    @property
    def is_file(self) -> bool:
        return self._mode == "file"

    def open(self) -> bool:
        self.close()
        timeout = self.config["timeout_ms"]
        if self._mode == "network":
            # FFmpeg honors these properties and returns control for unreachable
            # sources. Other backends may ignore them; worker reconnect/backoff
            # and command/test timeouts remain additional safety boundaries.
            params = [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, timeout,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, timeout,
            ]
            self._capture = cv2.VideoCapture(self._value, cv2.CAP_FFMPEG, params)
        else:
            self._capture = cv2.VideoCapture(self._value)

        if not self._capture.isOpened():
            self.status.opened = False
            self.status.error = f"could not open {self.display_source!r}"
            self.close()
            return False
        self.status.opened = True
        self.status.error = None
        self.status.fps = float(self._capture.get(cv2.CAP_PROP_FPS) or 30.0)
        self.status.width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.status.height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        return True

    def read(self):
        if self._capture is None:
            return False, None
        return self._capture.read()

    def rewind(self) -> bool:
        return bool(self._capture is not None and self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0))

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        self.status.opened = False

    @property
    def display_source(self) -> str:
        if self._mode == "device":
            return str(self.config["device_index"])
        if self._mode == "network":
            parsed = urlsplit(self.config["url"])
            host = parsed.hostname or "camera"
            port = f":{parsed.port}" if parsed.port else ""
            return f"{parsed.scheme}://{host}{port}{parsed.path}"
        return self.config["path"]

    @property
    def legacy_source(self) -> str:
        return str(self._value)
