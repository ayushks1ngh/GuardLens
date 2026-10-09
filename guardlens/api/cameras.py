"""Camera CRUD API (see docs/04-api-spec.md)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from guardlens.capture.manager import manager
from guardlens.events import Camera, get_engine, utcnow

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


class CameraCreate(BaseModel):
    name: str
    source: str
    analyze_fps: Optional[float] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    source: Optional[str] = None
    enabled: Optional[bool] = None
    analyze_fps: Optional[float] = None


def _status_for(camera_id: int) -> dict:
    worker = manager.get_worker(camera_id)
    if not worker:
        return {"connected": False, "fps": 0.0, "running": False}
    return {"connected": worker.connected, "fps": round(worker.fps, 1), "running": True}


@router.get("")
def list_cameras():
    with Session(get_engine()) as session:
        cams = session.exec(select(Camera)).all()
        return [{**c.model_dump(), "status": _status_for(c.id)} for c in cams]


@router.post("", status_code=201)
def create_camera(body: CameraCreate):
    with Session(get_engine()) as session:
        cam = Camera(name=body.name, source=body.source, analyze_fps=body.analyze_fps)
        session.add(cam)
        session.commit()
        session.refresh(cam)
    if cam.enabled:
        manager.start_camera(cam.id, cam.source)
    return {**cam.model_dump(), "status": _status_for(cam.id)}


@router.get("/{camera_id}")
def get_camera(camera_id: int):
    with Session(get_engine()) as session:
        cam = session.get(Camera, camera_id)
        if not cam:
            raise HTTPException(404, "camera not found")
        return {**cam.model_dump(), "status": _status_for(cam.id)}


@router.patch("/{camera_id}")
def update_camera(camera_id: int, body: CameraUpdate):
    with Session(get_engine()) as session:
        cam = session.get(Camera, camera_id)
        if not cam:
            raise HTTPException(404, "camera not found")
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(cam, k, v)
        cam.updated_at = utcnow()
        session.add(cam)
        session.commit()
        session.refresh(cam)
        source, enabled = cam.source, cam.enabled

    # Reconcile worker with new state.
    if not enabled:
        manager.stop_camera(camera_id)
    elif "source" in data or "enabled" in data:
        manager.start_camera(camera_id, source)
    return {**cam.model_dump(), "status": _status_for(camera_id)}


@router.delete("/{camera_id}")
def delete_camera(camera_id: int):
    manager.stop_camera(camera_id)
    with Session(get_engine()) as session:
        cam = session.get(Camera, camera_id)
        if not cam:
            raise HTTPException(404, "camera not found")
        session.delete(cam)
        session.commit()
    return {"status": "deleted", "id": camera_id}
