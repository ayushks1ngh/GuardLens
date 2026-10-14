"""Person enrollment, face samples, live capture, and face policy API."""
from __future__ import annotations

import uuid
from typing import Literal, Optional

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from guardlens.capture.manager import manager
from guardlens.detectors._face_runtime import face_runtime
from guardlens.events import FaceImage, Person, Setting, get_engine

router = APIRouter(prefix="/api", tags=["faces"])


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    watchlist: bool = False
    notes: Optional[str] = Field(default=None, max_length=1000)


class PersonUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    watchlist: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class CaptureBody(BaseModel):
    camera_id: int


def peek_dimensions(data: bytes):
    """(width, height) read from a PNG or JPEG header without decoding it, so a tiny file that declares a gigantic
    canvas (a decompression bomb) is refused before it can use gigabytes of memory. None for other formats."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):  # a start-of-frame marker
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + length
    return None


class PolicyBody(BaseModel):
    policy: Literal["label_only", "alert_unknown", "alert_watchlist"]


def _person_or_404(session: Session, person_id: int):
    person = session.get(Person, person_id)
    if not person: raise HTTPException(404, "person not found")
    return person


def _save_enrollment(person_id: int, image, *, allow_cropped: bool = True) -> FaceImage:
    h, w = image.shape[:2]
    embedding, found = face_runtime.embed_image(image)
    if not found:
        # Uploads may already be tightly cropped; live capture must prove that a face is present so a
        # background scene cannot become an identity.
        if not allow_cropped:
            raise HTTPException(422, "no face detected in current camera frame")
        if min(h, w) < 40:
            raise HTTPException(422, "image is too small for enrollment")
    embedding = embedding.tolist()
    filename = f"person-{person_id}-{uuid.uuid4().hex[:10]}.jpg"
    path = face_runtime.faces_dir / filename
    if not cv2.imwrite(str(path), image): raise HTTPException(500, "failed to save enrollment image")
    try:
        with Session(get_engine()) as session:
            _person_or_404(session, person_id)
            row = FaceImage(person_id=person_id, image_path=filename, embedding=embedding)
            session.add(row); session.commit(); session.refresh(row)
    except Exception:
        path.unlink(missing_ok=True); raise
    face_runtime.reload()
    return row


@router.get("/persons")
def list_persons():
    with Session(get_engine()) as session:
        people = session.exec(select(Person).order_by(Person.name)).all()
        return [{**p.model_dump(), "image_count": len(session.exec(select(FaceImage).where(FaceImage.person_id == p.id)).all())} for p in people]


@router.post("/persons", status_code=201)
def create_person(body: PersonCreate):
    with Session(get_engine()) as session:
        person = Person(**body.model_dump()); session.add(person); session.commit(); session.refresh(person); return person


@router.patch("/persons/{person_id}")
def update_person(person_id: int, body: PersonUpdate):
    with Session(get_engine()) as session:
        person = session.get(Person, person_id)
        if not person:
            raise HTTPException(404, "person not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(person, key, value)
        session.add(person); session.commit(); session.refresh(person)
        return person


@router.post("/persons/{person_id}/images", status_code=201)
async def upload_face(person_id: int, image: UploadFile = File(...)):
    limit = 10 * 1024 * 1024
    data = await image.read(limit + 1)  # never pull more than the limit into memory
    if len(data) > limit: raise HTTPException(413, "image exceeds 10 MB")
    size = peek_dimensions(data)
    if size and (max(size) > 8000 or size[0] * size[1] > 40_000_000):
        raise HTTPException(413, f"image dimensions are too large ({size[0]}x{size[1]}); use a photo under 8000 px / 40 megapixels")
    decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None: raise HTTPException(422, "invalid image")
    return _save_enrollment(person_id, decoded)


@router.post("/persons/{person_id}/capture", status_code=201)
def capture_face(person_id: int, body: CaptureBody):
    worker = manager.get_worker(body.camera_id)
    if not worker: raise HTTPException(404, "camera is not running")
    frame, _ = worker.get_latest()
    if frame is None: raise HTTPException(409, "camera has no frame yet")
    return _save_enrollment(person_id, frame, allow_cropped=False)


@router.delete("/persons/{person_id}")
def delete_person(person_id: int):
    with Session(get_engine()) as session:
        person = _person_or_404(session, person_id)
        images = session.exec(select(FaceImage).where(FaceImage.person_id == person_id)).all()
        for image in images:
            (face_runtime.faces_dir / image.image_path).unlink(missing_ok=True); session.delete(image)
        session.delete(person); session.commit()
    face_runtime.reload()
    return {"status": "deleted", "id": person_id}


@router.get("/faces/policy")
def get_policy(): return {"policy": face_runtime.policy()}


@router.patch("/faces/policy")
def set_policy(body: PolicyBody):
    with Session(get_engine()) as session:
        row = session.get(Setting, "face_policy") or Setting(key="face_policy")
        row.value = body.policy; session.add(row); session.commit()
    return {"policy": body.policy}
