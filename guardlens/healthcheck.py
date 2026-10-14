"""Plain-language list of things that need attention, each with a suggested fix."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
import shutil
from pathlib import Path

from sqlmodel import Session, select

from guardlens.events import Camera, get_engine


def _issue(level: str, area: str, message: str, fix: str) -> dict:
    return {"level": level, "area": area, "message": message, "fix": fix}


def collect_issues(data_dir: Path) -> list[dict]:
    from guardlens import auth
    from guardlens.agents import agent_runner, agent_types
    from guardlens.capture.manager import manager
    from guardlens.recording import clip_recorder
    from guardlens.scheduler import scheduler
    from guardlens.vlm_client import vlm_client

    out: list[dict] = []
    status = {s["camera_id"]: s for s in manager.status()}
    with Session(get_engine()) as session:
        cameras = session.exec(select(Camera)).all()
    for camera in cameras:
        if not camera.enabled:
            continue
        s = status.get(camera.id)
        if s is None or not s["connected"]:
            if camera.source_type == "webrtc":
                fix = "Open the pairing link on the phone or browser again; browser cameras only stream while the page is open."
            elif str(camera.source).startswith(("0", "1", "2", "/dev/video")):
                fix = "Check the camera is plugged in. On WSL, re-attach it with: usbipd attach --wsl --busid <id>."
            else:
                fix = "Check the camera is on, on the same network, and that its address has not changed."
            out.append(_issue("warning", "camera", f"“{camera.name}” is not sending video.", fix))
        elif s["last_frame_age"] is not None and s["last_frame_age"] > 10:
            out.append(_issue("warning", "camera", f"“{camera.name}” has stopped updating.", "Reload the camera from the Live page."))
    free = shutil.disk_usage(data_dir).free
    if free < 500 * 1024 ** 2:
        out.append(_issue("critical", "disk", f"Only {free // 1024 ** 2} MB of disk space is left.", "Delete old clips or lower the recording retention."))
    elif free < 2 * 1024 ** 3:
        out.append(_issue("warning", "disk", f"Disk space is getting low ({free // 1024 ** 3} GB left).", "Lower the recording retention or free some space."))
    for camera_id, message in (clip_recorder.status().get("errors") or {}).items():
        out.append(_issue("warning", "recording", f"Recording problem on camera {camera_id}: {message}", "Check the Recording page and the camera."))
    providers = vlm_client.status()["providers"]
    configured = [p for p in providers if p["configured"]]
    if configured and all(p["paused"] for p in configured):
        out.append(_issue("warning", "ai", "Every AI provider is temporarily paused after repeated failures.", "It retries automatically; free tiers are often busy."))
    for spec in agent_types():
        state = agent_runner.status(spec["key"])
        if state["state"] == "unavailable":
            out.append(_issue("info", "agents", f"{spec['label']} is on but waiting: {state['message']}", "Set an AI provider key on the server (see Agents)."))
    for job in scheduler.jobs():
        if job["last_status"].startswith("error"):
            out.append(_issue("warning", "scheduler", f"Background job “{job['name']}” failed last time.", "Check the server log."))
    from guardlens import maintenance
    from guardlens.config import load_config as _cfg
    if _cfg().backup.enabled:
        recent = maintenance.list_backups(_cfg())
        newest = datetime.fromisoformat(recent[0]["created_at"]) if recent else None
        if newest is None or datetime.now(timezone.utc) - newest > timedelta(days=2):
            out.append(_issue("info", "backup", "There has been no database backup in the last 2 days.",
                              "Open Settings > Data and press Back up now. Automatic backups run nightly at "
                              f"{_cfg().backup.daily_at} while GuardLens is running."))
    if not auth.auth_state.enabled:
        from guardlens.config import load_config
        exposed = bool(os.environ.get("GUARDLENS_PUBLIC_URL")) or load_config().host not in ("127.0.0.1", "localhost", "::1")
        out.append(_issue("warning" if exposed else "info", "security", "Login is off: anyone who can reach this server can see the cameras.",
                          "Create the administrator account in Security before using a tunnel or sharing the address."))
    return out
