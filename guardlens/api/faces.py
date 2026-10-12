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


class PolicyBody(BaseModel):
    policy: Literal["label_only", "alert_unknown", "alert_watchlist"]


def _person_or_404(session: Session, person_id: int):
    person = session.get(Person, person_id)
    if not person: raise HTTPException(404, "person not found")
    return person


def _largest_face(image, allow_cropped: bool = True):
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    boxes = cascade.detectMultiScale(gray, 1.1, 5, minSize=(40, 40))
    if len(boxes) == 0:
        # Uploads may already be tightly cropped; live capture must prove that a
        # face is present so a background scene cannot become an identity.
        if not allow_cropped:
            raise HTTPException(422, "no face detected in current camera frame")
        h, w = image.shape[:2]
        if min(h, w) < 40: raise HTTPException(422, "image is too small for enrollment")
        return image
    x, y, w, h = max(boxes, key=lambda b: b[2] * b[3])
    return image[y:y+h, x:x+w]


def _save_enrollment(person_id: int, image, *, allow_cropped: bool = True) -> FaceImage:
    face = _largest_face(image, allow_cropped=allow_cropped)
    embedding = face_runtime.embedding(face).tolist()
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
    data = await image.read()
    if len(data) > 10 * 1024 * 1024: raise HTTPException(413, "image exceeds 10 MB")
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
