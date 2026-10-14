"""Stage 2.2: "Test this camera" gives a plain reason and a next step for every kind of camera."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.camera_diagnosis import diagnose, tcp_reachable
from guardlens.events import Camera, get_engine

OFFLINE = {"connected": False, "fps": 0.0, "last_frame_age": None, "error": None, "resolution": {"width": 0, "height": 0}}
LIVE = {"connected": True, "fps": 7.9, "last_frame_age": 0.1, "error": None, "resolution": {"width": 640, "height": 480}}


def cam(kind="opencv", enabled=True, **config):
    return {"name": "X", "enabled": enabled, "source_type": kind, "source_config": config}


def test_working_camera_reports_resolution_and_speed():
    out = diagnose(cam(mode="device", device_index=0), LIVE)
    assert out["ok"] and "640×480 at 7.9 frames per second" in out["summary"] and out["advice"] == []


def test_switched_off_camera_says_so_first():
    out = diagnose(cam(enabled=False, mode="device", device_index=0), OFFLINE)
    assert not out["ok"] and "switched off" in out["summary"] and "switch on the Live page" in out["advice"][0]


def test_stalled_video_is_not_called_working():
    out = diagnose(cam(mode="network", url="http://h:1/v"), {**LIVE, "last_frame_age": 42.0}, reach=lambda h, p: None)
    assert not out["ok"] and any("42.0 seconds ago" in c["detail"] for c in out["checks"])


def test_missing_webcam_on_wsl_gets_the_usbipd_steps():
    out = diagnose(cam(mode="device", device_index=97), OFFLINE, wsl=lambda: True)
    text = " ".join(out["advice"])
    assert not out["ok"] and "/dev/video97" in out["checks"][1]["name"] and "usbipd attach" in text and "modprobe uvcvideo" in text


def test_missing_webcam_off_wsl_just_says_plug_it_in():
    out = diagnose(cam(mode="device", device_index=97), OFFLINE, wsl=lambda: False)
    assert "plugged in" in " ".join(out["advice"]) and "usbipd" not in " ".join(out["advice"])


def test_unreachable_phone_names_the_address_and_never_leaks_the_password():
    out = diagnose(cam(mode="network", url="http://user:secret@192.168.1.20:8080/video"), OFFLINE,
                   reach=lambda h, p: "no answer (timed out)", wsl=lambda: True)
    text = str(out)
    assert "192.168.1.20:8080" in text and "no answer (timed out)" in text and "secret" not in text and "user:" not in text
    assert "same network" in text and "mirrored networking" in text


def test_reachable_but_silent_camera_points_at_the_path_and_login():
    out = diagnose(cam(mode="network", url="rtsp://10.0.0.5/live"), OFFLINE, reach=lambda h, p: None)
    assert any(c["ok"] and "10.0.0.5:554" in c["name"] for c in out["checks"])  # rtsp default port
    assert "path at the end of the address" in " ".join(out["advice"])


def test_browser_camera_waiting_for_a_publisher():
    waiting = diagnose(cam("webrtc", mode="publisher", stream_id="abc"), {**OFFLINE})
    assert "Nothing is connected" in str(waiting) and "5 minutes" in str(waiting)
    sending = diagnose(cam("webrtc", mode="publisher", stream_id="abc"), OFFLINE, publisher_connected=lambda s: s == "abc")
    assert any(c["ok"] and "sending video" in c["name"] for c in sending["checks"])


def test_file_camera(tmp_path):
    real = tmp_path / "v.mp4"; real.write_bytes(b"x")
    assert diagnose(cam(mode="file", path=str(real)), OFFLINE)["checks"][1]["ok"] is True
    assert "not found" in str(diagnose(cam(mode="file", path=str(tmp_path / "gone.mp4")), OFFLINE))


def test_empty_address_and_worker_error_are_reported():
    out = diagnose(cam(mode="network", url=""), {**OFFLINE, "error": "could not open 'x'"})
    assert "empty or malformed" in str(out) and "could not open 'x'" in str(out)


def test_tcp_reachable_against_a_closed_local_port():
    assert tcp_reachable("127.0.0.1", 9, timeout=0.5) is not None
    assert tcp_reachable("no-such-host.invalid", 80, timeout=0.5) is not None


def test_api_endpoint_diagnoses_a_saved_camera_and_404s_for_unknown_ones():
    with TestClient(app) as client:
        with Session(get_engine()) as session:
            camera = Camera(name="Gone clip", source="/nonexistent/none.mp4", enabled=True)
            session.add(camera); session.commit(); session.refresh(camera)
            cid = camera.id
        out = client.post(f"/api/cameras/{cid}/test").json()
        assert out["ok"] is False and set(out) == {"ok", "summary", "checks", "advice"}
        assert "not found" in str(out)
        assert client.post("/api/cameras/999999/test").status_code == 404
