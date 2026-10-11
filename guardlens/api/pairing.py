"""LAN-first browser camera pairing and WebRTC signaling API."""
from __future__ import annotations

import base64
import io
import os
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from guardlens.capture.webrtc import pairing_service

router = APIRouter(prefix="/api/pairing", tags=["pairing"])


class PairingCreate(BaseModel):
    label: str = Field(default="Browser camera", max_length=100)
    ttl_seconds: int = Field(default=300, ge=30, le=900)


class OfferBody(BaseModel):
    stream_id: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    token: str = Field(min_length=32, max_length=256)
    sdp: str = Field(min_length=10, max_length=1_000_000)
    type: str = Field(default="offer", pattern="^offer$")
    reconnect: bool = False


def _publisher_base(request: Request) -> str:
    # Prefer an explicitly configured public base (needed when the phone must reach a
    # LAN HTTPS address different from how the operator opened the dashboard, e.g. WSL).
    public = os.environ.get("GUARDLENS_PUBLIC_URL", "").strip().rstrip("/")
    if public:
        return public
    return str(request.base_url).rstrip("/")


@router.post("", status_code=201)
def create_pairing(body: PairingCreate, request: Request):
    try:
        session, token = pairing_service.create(body.label, body.ttl_seconds)
    except ValueError as exc:
        raise HTTPException(429, str(exc)) from exc
    query = urlencode({"stream_id": session.stream_id, "token": token})
    publisher_url = f"{_publisher_base(request)}/publish#{query}"
    import qrcode
    import qrcode.image.svg
    image = qrcode.make(publisher_url, image_factory=qrcode.image.svg.SvgPathImage)
    output = io.BytesIO(); image.save(output)
    qr_data_uri = "data:image/svg+xml;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    return {
        **pairing_service.public(session),
        "publisher_url": publisher_url,
        "qr_data_uri": qr_data_uri,
        "source_type": "webrtc",
        "source_config": {"mode": "publisher", "stream_id": session.stream_id},
    }


@router.get("")
def list_pairings():
    return pairing_service.list_public()


@router.post("/offer")
async def accept_offer(body: OfferBody, request: Request):
    host = request.url.hostname or ""
    if request.url.scheme != "https" and host not in {"127.0.0.1", "localhost", "testserver"}:
        raise HTTPException(400, "browser publishing requires HTTPS outside localhost")
    try:
        return await pairing_service.accept_offer(
            body.stream_id, body.token, body.sdp, body.type, reconnect=body.reconnect
        )
    except ValueError as exc:
        raise HTTPException(401, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, f"WebRTC negotiation failed: {exc}") from exc



@router.delete("/{stream_id}")
async def revoke_pairing(stream_id: str):
    if not await pairing_service.revoke(stream_id):
        raise HTTPException(404, "pairing session not found")
    return {"status": "revoked", "stream_id": stream_id}
