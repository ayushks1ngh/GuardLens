"""Improvement Phase B: secure browser/WebRTC camera publishing."""
from __future__ import annotations

import asyncio
import time
from fractions import Fraction
from urllib.parse import parse_qs, urlsplit

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from fastapi.testclient import TestClient

from guardlens.app import app
from guardlens.capture.frame_hub import FrameHub, frame_hub
from guardlens.capture.sources import create_source, source_types
from guardlens.capture.webrtc import PairingService


class SyntheticVideoTrack(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self.counter = 0

    async def recv(self):
        self.counter += 1
        image = np.full((48, 64, 3), self.counter % 255, dtype=np.uint8)
        frame = av.VideoFrame.from_ndarray(image, format="bgr24")
        frame.pts = self.counter * 3000
        frame.time_base = Fraction(1, 90000)
        await asyncio.sleep(1 / 30)
        return frame


def test_webrtc_source_is_auto_discovered_and_frames_are_isolated():
    assert "webrtc" in {item["key"] for item in source_types()}
    hub = FrameHub()
    hub.register("one")
    hub.register("two")
    assert hub.publish("one", np.full((3, 4, 3), 11, dtype=np.uint8))
    assert hub.publish("two", np.full((5, 6, 3), 22, dtype=np.uint8))
    one, _, seq_one = hub.wait_for_frame("one", timeout=0.1)
    two, _, seq_two = hub.wait_for_frame("two", timeout=0.1)
    assert one.shape == (3, 4, 3) and int(one[0, 0, 0]) == 11 and seq_one == 1
    assert two.shape == (5, 6, 3) and int(two[0, 0, 0]) == 22 and seq_two == 1


def test_pairing_tokens_are_hashed_single_use_expiring_and_revocable():
    service = PairingService()
    session, token = service.create("Phone", ttl_seconds=30)
    assert token not in session.token_hash and len(session.token_hash) == 64
    assert service.consume(session.stream_id, token) is session
    try:
        service.consume(session.stream_id, token)
        raise AssertionError("single-use token was accepted twice")
    except ValueError as exc:
        assert "already been used" in str(exc)

    expired, expired_token = service.create("Old", ttl_seconds=30)
    expired.expires_at = time.time() - 1
    try:
        service.consume(expired.stream_id, expired_token)
        raise AssertionError("expired token was accepted")
    except ValueError as exc:
        assert "expired" in str(exc)

    revoked, revoked_token = service.create("Revoked", ttl_seconds=30)
    asyncio.run(service.revoke(revoked.stream_id))
    try:
        service.consume(revoked.stream_id, revoked_token)
        raise AssertionError("revoked token was accepted")
    except ValueError as exc:
        assert "unavailable" in str(exc)
    asyncio.run(service.close_all())


def test_pairing_api_never_lists_raw_token_and_serves_publisher():
    with TestClient(app) as client:
        created = client.post("/api/pairing", json={"label": "My phone", "ttl_seconds": 60})
        assert created.status_code == 201
        body = created.json()
        parsed = urlsplit(body["publisher_url"])
        query = parse_qs(parsed.fragment)
        token = query["token"][0]
        assert body["source_type"] == "webrtc"
        assert body["source_config"]["stream_id"] == body["stream_id"]
        listed = client.get("/api/pairing").text
        assert token not in listed and "token_hash" not in listed
        assert body["qr_data_uri"].startswith("data:image/svg+xml;base64,")
        assert client.get("/api/pairing").json()[0]["used"] is False
        page = client.get("/publish")
        assert page.status_code == 200 and "getUserMedia" in page.text
        revoked = client.delete(f"/api/pairing/{body['stream_id']}")
        assert revoked.status_code == 200


def test_webrtc_source_waits_for_publisher_then_reads_latest_frame():
    stream_id = "source_test"
    adapter = create_source("webrtc", {"mode": "publisher", "stream_id": stream_id, "frame_timeout_ms": 250})
    assert not adapter.open()
    frame_hub.register(stream_id)
    try:
        assert adapter.open()
        frame_hub.publish(stream_id, np.full((24, 32, 3), 77, dtype=np.uint8))
        ok, frame = adapter.read()
        assert ok and frame.shape == (24, 32, 3) and int(frame[0, 0, 0]) == 77
        assert adapter.status.width == 32 and adapter.status.height == 24
    finally:
        adapter.close()
        frame_hub.unregister(stream_id)


def test_real_webrtc_offer_delivers_synthetic_video():
    with TestClient(app) as client:
        pairing = client.post("/api/pairing", json={"label": "Synthetic browser"}).json()
        query = parse_qs(urlsplit(pairing["publisher_url"]).fragment)
        token = query["token"][0]
        stream_id = pairing["stream_id"]

        async def negotiate():
            peer = RTCPeerConnection()
            peer.addTrack(SyntheticVideoTrack())
            try:
                await peer.setLocalDescription(await peer.createOffer())
                response = client.post("/api/pairing/offer", json={
                    "stream_id": stream_id,
                    "token": token,
                    "sdp": peer.localDescription.sdp,
                    "type": peer.localDescription.type,
                })
                assert response.status_code == 200, response.text
                answer = response.json()
                await peer.setRemoteDescription(RTCSessionDescription(answer["sdp"], answer["type"]))
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    frame, _, _ = await asyncio.to_thread(frame_hub.wait_for_frame, stream_id, 0, 0.25)
                    if frame is not None:
                        assert frame.shape == (48, 64, 3)
                        return
                raise AssertionError("WebRTC video frame was not delivered")
            finally:
                await peer.close()

        asyncio.run(negotiate())
