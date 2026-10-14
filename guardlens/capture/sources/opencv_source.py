"""OpenCV pull-source adapter: host devices, files, RTSP, HTTP and MJPEG."""
from __future__ import annotations

from pathlib import Path
import sys
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
                {"key": "pixel_format", "label": "Pixel format", "type": "select", "default": "MJPG", "options": ["MJPG", "YUYV", "AUTO"]},
                {"key": "width", "label": "Width", "type": "integer", "default": 640},
                {"key": "height", "label": "Height", "type": "integer", "default": 480},
                {"key": "capture_fps", "label": "Capture FPS", "type": "integer", "default": 30},
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
            pixel_format = str(clean.get("pixel_format", "MJPG")).upper()
            if pixel_format not in {"MJPG", "YUYV", "AUTO"}:
                raise ValueError("pixel_format must be MJPG, YUYV, or AUTO")
            clean["pixel_format"] = pixel_format
            for key, default, minimum, maximum in (
                ("width", 640, 1, 7680),
                ("height", 480, 1, 4320),
                ("capture_fps", 30, 1, 240),
            ):
                try:
                    value = int(clean.get(key, default))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{key} must be an integer") from exc
                if value < minimum or value > maximum:
                    raise ValueError(f"{key} must be between {minimum} and {maximum}")
                clean[key] = value
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

    def _open_hint(self) -> str:
        """Plain-language next step for the most common reasons a camera will not open."""
        if self._mode == "device" and sys.platform.startswith("linux"):
            if not Path(f"/dev/video{self._value}").exists():
                wsl = "microsoft" in Path("/proc/version").read_text(errors="ignore").lower() if Path("/proc/version").exists() else False
                if wsl:
                    return (f" — /dev/video{self._value} does not exist. WSL2 cannot see USB/laptop webcams; "
                            "use a phone or browser camera (Add a camera > Phone) or attach the webcam with usbipd")
                return f" — /dev/video{self._value} does not exist; check that the camera is plugged in"
            return " — the device exists but could not be opened; another program may be using it, or you may lack permission (video group)"
        if self._mode == "network":
            host = urlsplit(str(self._value)).netloc.rpartition("@")[2] or "the address"
            return f" — could not reach {host}; check the address, that the camera/app is running, and that both are on the same network"
        if self._mode == "file":
            return " — the file was not found or is not a video"
        return ""

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
            backend = cv2.CAP_V4L2 if self._mode == "device" and sys.platform.startswith("linux") else cv2.CAP_ANY
            self._capture = cv2.VideoCapture(self._value, backend)
            if self._mode == "device" and self._capture.isOpened():
                pixel_format = self.config["pixel_format"]
                if pixel_format != "AUTO":
                    self._capture.set(
                        cv2.CAP_PROP_FOURCC,
                        cv2.VideoWriter_fourcc(*pixel_format),
                    )
                self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config["width"])
                self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config["height"])
                self._capture.set(cv2.CAP_PROP_FPS, self.config["capture_fps"])

        if not self._capture.isOpened():
            self.status.opened = False
            self.status.error = f"could not open {self.display_source!r}" + self._open_hint()
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
