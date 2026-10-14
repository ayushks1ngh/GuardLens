"""Plain-language "why is this camera not working?" for a saved camera (Stage 2.2)."""
from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

DEFAULT_PORTS = {"rtsp": 554, "rtsps": 322, "http": 80, "https": 443}


def tcp_reachable(host: str, port: int, timeout: float = 3.0) -> Optional[str]:
    """None when a connection opens, else a short reason."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return None
    except socket.gaierror:
        return "the name could not be found"
    except socket.timeout:
        return "no answer (timed out)"
    except OSError as exc:
        return exc.strerror or "connection refused"


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _hostport(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or DEFAULT_PORTS.get(parts.scheme, 80)
    return host, port, f"{host}:{port}"


def diagnose(
    camera: dict[str, Any], status: dict[str, Any], *,
    reach: Callable[[str, int], Optional[str]] = tcp_reachable,
    wsl: Callable[[], bool] = lambda: False,
    publisher_connected: Callable[[str], bool] = lambda stream_id: False,
) -> dict[str, Any]:
    """Run the checks that fit this camera's kind and return {ok, summary, checks, advice}."""
    checks: list[dict] = []
    advice: list[str] = []
    cfg = dict(camera.get("source_config") or {})
    kind = camera.get("source_type")
    mode = cfg.get("mode")

    if not camera.get("enabled", True):
        return {"ok": False, "summary": "This camera is switched off.",
                "checks": [_check("Camera is switched on", False, "It is turned off")],
                "advice": ["Turn it on with the switch on the Live page."]}
    checks.append(_check("Camera is switched on", True, "Yes"))

    age, connected = status.get("last_frame_age"), bool(status.get("connected"))
    if connected and age is not None and age <= 5:
        res = status.get("resolution") or {}
        detail = f"{res.get('width', 0)}×{res.get('height', 0)} at {status.get('fps', 0)} frames per second"
        checks.append(_check("Video is arriving", True, detail))
        return {"ok": True, "summary": f"Working: {detail}.", "checks": checks, "advice": []}
    if connected:
        checks.append(_check("Video is arriving", False, f"The last picture was {age if age is not None else 'a while'} seconds ago"))
        advice.append("The camera connected but stopped sending pictures. Reload it from the Live page; if it keeps happening, check the network or cable.")

    if kind == "webrtc":
        stream_id = str(cfg.get("stream_id", ""))
        live = publisher_connected(stream_id)
        checks.append(_check("A phone or browser is sending video", live,
                             "Yes" if live else "Nothing is connected right now"))
        if not live:
            advice += ["Open Settings → Cameras → Add a camera → phone or browser, then press “Open the camera page” on the device you want to use.",
                       "Pairing links work for 5 minutes and the page must be opened over https (or localhost)."]
    elif mode == "device":
        index = int(cfg.get("device_index", 0))
        node = Path(f"/dev/video{index}")
        exists = node.exists()
        checks.append(_check(f"Camera device /dev/video{index} exists", exists, "Yes" if exists else "It is not there"))
        if not exists:
            advice.append("WSL2 cannot see USB or laptop webcams by itself. In an administrator PowerShell run: usbipd attach --wsl --busid <your camera's id> (see usbipd list), then in WSL: sudo modprobe uvcvideo."
                          if wsl() else "Check that the camera is plugged in, then press Reload.")
        else:
            usable = os.access(node, os.R_OK | os.W_OK)
            checks.append(_check("This program may use the device", usable, "Yes" if usable else "Permission denied"))
            advice.append("Add your user to the video group (sudo usermod -aG video $USER) and log in again." if not usable
                          else "Another program may be using the camera. Close other apps that use it, then press Reload.")
    elif mode == "network":
        host, port, label = _hostport(str(cfg.get("url", "")))
        if not host:
            checks.append(_check("Address is valid", False, "The address is empty or malformed"))
            advice.append("Edit the camera and enter a full address such as http://192.168.1.20:8080/video.")
        else:
            problem = reach(host, port)
            checks.append(_check(f"Can reach {label}", problem is None, "Yes" if problem is None else problem))
            if problem:
                advice += [f"GuardLens cannot reach {label}: {problem}.",
                           "Check that the camera or phone app is running and that this computer is on the same network. Phones change address when they reconnect — look up the current one in the app."]
                if wsl():
                    advice.append("WSL2 has its own network; a phone on your Wi-Fi may need WSL mirrored networking or a port forward to reach it.")
            else:
                advice.append("The address answers but no video is coming. Check the path at the end of the address (often /video, /stream or /h264) and any username and password.")
    elif mode == "file":
        path = Path(str(cfg.get("path", "")))
        ok = path.is_file() and os.access(path, os.R_OK)
        checks.append(_check("Video file can be read", ok, "Yes" if ok else "The file was not found or is not readable"))
        if not ok:
            advice.append("Check the file path on the computer that runs GuardLens.")

    if status.get("error"):
        checks.append(_check("What the camera reported", False, str(status["error"])))
    if not advice:
        advice.append("Press Reload on the Live page. If it still fails, open Settings → Health for details.")
    return {"ok": False, "summary": "Not working yet — " + (advice[0] if len(advice) == 1 else "see the steps below."),
            "checks": checks, "advice": advice}
