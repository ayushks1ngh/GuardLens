"""Phase 1 acceptance-gate tests.

Gate 1:
- Add a camera (file source); worker connects and reads frames.
- Two sources run concurrently.
- Camera CRUD (list/get/update/delete) works and reconciles workers.
- MJPEG endpoint streams multipart data.
- Video files loop (continuous feed) and reconnect logic is exercised.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from guardlens.app import app
from guardlens.capture.worker import CaptureWorker

SAMPLE = "data/samples/mall_cctv.mp4"


def _wait_connected(worker: CaptureWorker, timeout=10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        frame, _ = worker.get_latest()
        if worker.connected and frame is not None:
            return True
        time.sleep(0.2)
    return False


def test_worker_reads_frames():
    w = CaptureWorker(camera_id=999, source=SAMPLE)
    w.start()
    try:
        assert _wait_connected(w), "worker did not connect/read frames"
        frame, ts = w.get_latest()
        assert frame is not None
        assert frame.shape[0] > 0 and frame.shape[1] > 0
        assert ts > 0
    finally:
        w.stop()


def test_worker_loops_file():
    """A short file source should keep producing frames beyond its length."""
    w = CaptureWorker(camera_id=998, source=SAMPLE, loop_files=True)
    w.start()
    try:
        assert _wait_connected(w)
        _, ts1 = w.get_latest()
        time.sleep(2.0)
        _, ts2 = w.get_latest()
        assert ts2 > ts1, "frames should keep updating (file looped)"
    finally:
        w.stop()


def test_camera_crud_and_stream():
    with TestClient(app) as client:
        # create
        r = client.post("/api/cameras", json={"name": "Mall", "source": SAMPLE})
        assert r.status_code == 201, r.text
        cam = r.json()
        cid = cam["id"]

        # list
        assert any(c["id"] == cid for c in client.get("/api/cameras").json())

        # get
        assert client.get(f"/api/cameras/{cid}").status_code == 200

        # worker should connect
        connected = False
        for _ in range(50):
            s = client.get(f"/api/cameras/{cid}").json()["status"]
            if s["connected"]:
                connected = True
                break
            time.sleep(0.2)
        assert connected, "camera worker did not connect"

        # MJPEG streams multipart bytes (bounded: read a couple of chunks then stop)
        with client.stream("GET", f"/stream/{cid}/mjpeg?max_frames=2") as resp:
            assert resp.status_code == 200
            assert "multipart/x-mixed-replace" in resp.headers["content-type"]
            got = b""
            for i, chunk in enumerate(resp.iter_bytes()):
                got += chunk
                if (b"image/jpeg" in got or b"--frame" in got) or i > 20:
                    break
            assert b"image/jpeg" in got or b"--frame" in got

        # update (disable) stops the worker
        r = client.patch(f"/api/cameras/{cid}", json={"enabled": False})
        assert r.status_code == 200

        # delete
        assert client.delete(f"/api/cameras/{cid}").status_code == 200
        assert client.get(f"/api/cameras/{cid}").status_code == 404


def test_two_sources_concurrent():
    w1 = CaptureWorker(camera_id=1001, source=SAMPLE)
    w2 = CaptureWorker(camera_id=1002, source=SAMPLE)
    w1.start()
    w2.start()
    try:
        assert _wait_connected(w1)
        assert _wait_connected(w2)
        f1, _ = w1.get_latest()
        f2, _ = w2.get_latest()
        assert f1 is not None and f2 is not None
    finally:
        w1.stop()
        w2.stop()


def test_bad_source_does_not_crash():
    w = CaptureWorker(camera_id=1003, source="/nonexistent/path.mp4",
                      reconnect_backoff=0.2, max_backoff=0.4)
    w.start()
    try:
        time.sleep(1.0)
        assert not w.connected  # never connects, but no crash
        frame, _ = w.get_latest()
        assert frame is None
    finally:
        w.stop()


def test_open_failures_explain_what_to_do():
    from guardlens.capture.sources import create_source
    net = create_source("opencv", {"mode": "network", "url": "http://user:pw@10.255.254.1:9/video", "timeout_ms": 250})
    assert net.open() is False
    assert "could not reach 10.255.254.1:9" in net.status.error and "pw" not in net.status.error
    dev = create_source("opencv", {"mode": "device", "device_index": 97})
    assert dev.open() is False
    assert "/dev/video97 does not exist" in dev.status.error
    gone = create_source("opencv", {"mode": "file", "path": "/nonexistent/clip.mp4"})
    assert gone.open() is False and "not found" in gone.status.error
