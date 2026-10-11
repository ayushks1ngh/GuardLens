"""Short-lived browser pairing, WebRTC signaling, and frame ingestion."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from aiortc import RTCPeerConnection, RTCSessionDescription

from guardlens.capture.frame_hub import frame_hub


@dataclass
class PairingSession:
    stream_id: str
    token_hash: str
    expires_at: float
    label: str
    used: bool = False
    revoked: bool = False
    connected: bool = False
    reconnect_hash: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class PairingService:
    """Owns ephemeral tokens and active peers; raw tokens are returned only once."""

    def __init__(self, max_sessions: int = 32) -> None:
        self._sessions: dict[str, PairingSession] = {}
        self._peers: dict[str, RTCPeerConnection] = {}
        self._tasks: dict[str, set[asyncio.Task]] = {}
        self._lock = threading.Lock()
        self._max_sessions = max(1, max_sessions)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create(self, label: str = "Browser camera", ttl_seconds: int = 300) -> tuple[PairingSession, str]:
        ttl = max(30, min(int(ttl_seconds), 900))
        token = secrets.token_urlsafe(32)
        stream_id = secrets.token_urlsafe(18).replace("-", "_")
        session = PairingSession(
            stream_id=stream_id,
            token_hash=self._hash(token),
            expires_at=time.time() + ttl,
            label=(label.strip() or "Browser camera")[:100],
        )
        with self._lock:
            now = time.time()
            stale = [key for key, item in self._sessions.items() if item.revoked or (not item.used and item.expires_at <= now)]
            for key in stale:
                self._sessions.pop(key, None)
                frame_hub.unregister(key)
            if len(self._sessions) >= self._max_sessions:
                frame_hub.unregister(stream_id)
                raise ValueError("too many active pairing sessions")
            self._sessions[stream_id] = session
        frame_hub.register(stream_id)
        return session, token

    def consume(self, stream_id: str, token: str, reconnect: bool = False) -> PairingSession:
        with self._lock:
            session = self._sessions.get(stream_id)
            if session is None or session.revoked:
                raise ValueError("pairing session is unavailable")
            if reconnect:
                if not session.reconnect_hash or not secrets.compare_digest(
                    session.reconnect_hash, self._hash(token)
                ):
                    raise ValueError("invalid reconnect credential")
                return session
            if time.time() >= session.expires_at:
                session.revoked = True
                raise ValueError("pairing session has expired")
            if session.used:
                raise ValueError("pairing token has already been used")
            if not secrets.compare_digest(session.token_hash, self._hash(token)):
                raise ValueError("invalid pairing token")
            session.used = True
            return session

    def get(self, stream_id: str) -> Optional[PairingSession]:
        with self._lock:
            return self._sessions.get(stream_id)

    def list_public(self) -> list[dict]:
        with self._lock:
            sessions = list(self._sessions.values())
        return [self.public(session) for session in sessions]

    @staticmethod
    def public(session: PairingSession) -> dict:
        return {
            "stream_id": session.stream_id,
            "label": session.label,
            "expires_at": session.expires_at,
            "used": session.used,
            "revoked": session.revoked,
            "connected": session.connected,
        }

    async def accept_offer(self, stream_id: str, token: str, sdp: str, kind: str, reconnect: bool = False) -> dict:
        session = self.consume(stream_id, token, reconnect=reconnect)
        reconnect_token = secrets.token_urlsafe(32)
        session.reconnect_hash = self._hash(reconnect_token)
        peer = RTCPeerConnection()
        with self._lock:
            old_peer = self._peers.pop(stream_id, None)
            self._peers[stream_id] = peer
            self._tasks[stream_id] = set()
        if old_peer:
            await old_peer.close()

        @peer.on("track")
        def on_track(track):
            if track.kind != "video":
                return
            session.connected = True
            task = asyncio.create_task(self._consume_video(stream_id, track))
            with self._lock:
                self._tasks.setdefault(stream_id, set()).add(task)
            task.add_done_callback(lambda done: self._task_done(stream_id, done))

        @peer.on("connectionstatechange")
        async def on_state_change():
            session.connected = peer.connectionState in {"connected", "connecting"}
            if peer.connectionState in {"failed", "closed", "disconnected"}:
                session.connected = False
                if peer.connectionState in {"failed", "closed"}:
                    await peer.close()

        try:
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
            await peer.setLocalDescription(await peer.createAnswer())
        except Exception:
            await self.revoke(stream_id)
            raise
        return {
            "sdp": peer.localDescription.sdp,
            "type": peer.localDescription.type,
            "reconnect_token": reconnect_token,
        }

    async def _consume_video(self, stream_id: str, track) -> None:
        try:
            while True:
                frame = await track.recv()
                frame_hub.publish(stream_id, frame.to_ndarray(format="bgr24"))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        finally:
            session = self.get(stream_id)
            if session:
                session.connected = False

    def _task_done(self, stream_id: str, task: asyncio.Task) -> None:
        with self._lock:
            self._tasks.get(stream_id, set()).discard(task)

    async def revoke(self, stream_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(stream_id)
            peer = self._peers.pop(stream_id, None)
            tasks = list(self._tasks.pop(stream_id, set()))
            if session:
                session.revoked = True
                session.connected = False
        for task in tasks:
            task.cancel()
        if peer:
            await peer.close()
        frame_hub.unregister(stream_id)
        return session is not None

    async def close_all(self) -> None:
        with self._lock:
            stream_ids = list(self._sessions)
        for stream_id in stream_ids:
            await self.revoke(stream_id)


pairing_service = PairingService()
