"""Camera CRUD, source discovery, and connection probing (Improvement Phase A)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlmodel import Session, select

from guardlens.capture.manager import manager
from guardlens.capture.sources import create_source, source_types
from guardlens.events import Camera, get_engine, utcnow

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class SourceInput(BaseModel):
    """Typed source input with legacy ``source`` compatibility."""

    source: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    source_type: str = Field(default="opencv", min_length=1, max_length=80)
    source_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def source_present(self):
        if self.source is None and not self.source_config:
            raise ValueError("source or source_config is required")
        return self


class CameraCreate(SourceInput):
    name: str = Field(min_length=1, max_length=120)
    analyze_fps: Optional[float] = Field(default=None, gt=0, le=60)


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    source: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    source_type: Optional[str] = Field(default=None, min_length=1, max_length=80)
    source_config: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    analyze_fps: Optional[float] = Field(default=None, gt=0, le=60)


class SourceProbe(SourceInput):
    pass


def _normalise_source(
    source_type: str,
    source_config: Optional[dict[str, Any]],
    source: Optional[str],
) -> tuple[str, dict[str, Any], str]:
    try:
        adapter = create_source(source_type, source_config, legacy_source=source)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, f"invalid camera source: {exc}") from exc
    legacy = getattr(adapter, "legacy_source", source or source_type)
    return source_type, adapter.config, str(legacy)


def _redact_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value
        host = parsed.hostname or "camera"
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port else ""
        # Userinfo and query parameters may contain passwords/tokens. The
        # operator response exposes only scheme, host, port, and path.
        return urlunsplit((parsed.scheme, f"{host}{port}", parsed.path, "", ""))
    except ValueError:
        return "<redacted camera URL>"


def _public_camera(camera: Camera) -> dict[str, Any]:
    data = camera.model_dump()
    config = dict(camera.source_config or {})
    if camera.source_type == "opencv" and config.get("mode") == "network":
        if "url" in config:
            config["url"] = _redact_url(str(config["url"]))
        data["source"] = _redact_url(camera.source)
    data["source_config"] = config
    return data


def _status_for(camera_id: int) -> dict[str, Any]:
    worker = manager.get_worker(camera_id)
    if not worker:
        return {
            "connected": False,
            "fps": 0.0,
            "running": False,
            "resolution": {"width": 0, "height": 0},
            "last_frame_age": None,
            "error": None,
        }
    width, height = worker.resolution
    return {
        "connected": worker.connected,
        "fps": round(worker.fps, 1),
        "running": True,
        "source_type": worker.source_type,
        "resolution": {"width": width, "height": height},
        "last_frame_age": round(worker.last_frame_age, 2)
        if worker.last_frame_age is not None else None,
        "error": worker.last_error,
    }


def _start_runtime(camera: Camera) -> None:
    manager.start_camera(
        camera.id,
        camera.source,
        camera.source_type,
        camera.source_config,
    )
    try:
        from guardlens.analysis.pipeline import analysis_manager

        if analysis_manager.active:
            analysis_manager.start_camera(camera.id)
    except Exception:
        # Capture must remain available if optional analysis is unavailable.
        pass


@router.get("/source-types")
def list_source_types():
    """Schema used by the Add Camera wizard; no source types are hardcoded in UI."""
    return source_types()


@router.get("/local-devices")
def list_local_devices():
    """List Linux video devices attached to the GuardLens host.

    Absence from this list does not prevent manually entering an OpenCV index.
    Browser/phone devices are publishers and arrive in Improvement Phase B.
    """
    devices = []
    for path in sorted(Path("/dev").glob("video*")):
        suffix = path.name.removeprefix("video")
        if suffix.isdigit():
            devices.append({"index": int(suffix), "path": str(path), "label": path.name})
    return devices


@router.post("/probe")
def probe_source(body: SourceProbe):
    """Open and read one frame without persisting or starting a camera."""
    source_type, config, source = _normalise_source(
        body.source_type, body.source_config, body.source
    )
    adapter = create_source(source_type, config, legacy_source=source)
    try:
        if not adapter.open():
            raise HTTPException(422, adapter.status.error or "could not open source")
        ok, frame = adapter.read()
        if not ok or frame is None:
            raise HTTPException(422, "source opened but did not produce a frame")
        height, width = frame.shape[:2]
        return {
            "ok": True,
            "source_type": source_type,
            "mode": config.get("mode"),
            "resolution": {"width": width, "height": height},
            "fps": round(adapter.status.fps, 2),
        }
    finally:
        adapter.close()


@router.get("")
def list_cameras():
    with Session(get_engine()) as session:
        cameras = session.exec(select(Camera)).all()
        return [
            {**_public_camera(camera), "status": _status_for(camera.id)}
            for camera in cameras
        ]


@router.post("", status_code=201)
def create_camera(body: CameraCreate):
    source_type, source_config, source = _normalise_source(
        body.source_type, body.source_config, body.source
    )
    with Session(get_engine()) as session:
        camera = Camera(
            name=body.name,
            source=source,
            source_type=source_type,
            source_config=source_config,
            analyze_fps=body.analyze_fps,
        )
        session.add(camera)
        session.commit()
        session.refresh(camera)
    if camera.enabled:
        _start_runtime(camera)
    return {**_public_camera(camera), "status": _status_for(camera.id)}


@router.get("/{camera_id}")
def get_camera(camera_id: int):
    with Session(get_engine()) as session:
        camera = session.get(Camera, camera_id)
        if not camera:
            raise HTTPException(404, "camera not found")
        return {**_public_camera(camera), "status": _status_for(camera.id)}


@router.patch("/{camera_id}")
def update_camera(camera_id: int, body: CameraUpdate):
    with Session(get_engine()) as session:
        camera = session.get(Camera, camera_id)
        if not camera:
            raise HTTPException(404, "camera not found")
        changes = body.model_dump(exclude_unset=True)
        source_changed = bool({"source", "source_type", "source_config"} & changes.keys())
        if source_changed:
            requested_config = changes.get("source_config")
            requested_source = changes.get("source")
            # A direct legacy source edit intentionally replaces the previous
            # mode-specific path/URL instead of being shadowed by stale JSON.
            if requested_source is not None and requested_config is None:
                requested_config = {"source": requested_source}
            source_type, source_config, source = _normalise_source(
                changes.get("source_type", camera.source_type),
                requested_config if requested_config is not None else camera.source_config,
                requested_source if requested_source is not None else camera.source,
            )
            changes.update(
                source=source,
                source_type=source_type,
                source_config=source_config,
            )
        for key, value in changes.items():
            setattr(camera, key, value)
        camera.updated_at = utcnow()
        session.add(camera)
        session.commit()
        session.refresh(camera)

    if not camera.enabled:
        manager.stop_camera(camera_id)
        try:
            from guardlens.analysis.pipeline import analysis_manager

            analysis_manager.stop_camera(camera_id)
        except Exception:
            pass
    elif source_changed or "enabled" in changes:
        _start_runtime(camera)
    return {**_public_camera(camera), "status": _status_for(camera_id)}


@router.delete("/{camera_id}")
def delete_camera(camera_id: int):
    try:
        from guardlens.analysis.pipeline import analysis_manager

        analysis_manager.stop_camera(camera_id)
    except Exception:
        pass
    manager.stop_camera(camera_id)
    from guardlens.streaming.stream import overlay_store

    overlay_store.remove(camera_id)
    with Session(get_engine()) as session:
        camera = session.get(Camera, camera_id)
        if not camera:
            raise HTTPException(404, "camera not found")
        webrtc_stream = (
            camera.source_config.get("stream_id")
            if camera.source_type == "webrtc" else None
        )
        session.delete(camera)
        session.commit()
    if webrtc_stream:
        try:
            from guardlens.capture.webrtc import pairing_service
            import asyncio
            asyncio.run(pairing_service.revoke(webrtc_stream))
        except Exception:
            pass
    return {"status": "deleted", "id": camera_id}
