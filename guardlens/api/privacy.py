"""Per-camera privacy: cameras marked "local only" never send frames to a cloud AI provider."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from guardlens.events import Camera, Setting, get_engine
from guardlens.vlm_client import vlm_client

router = APIRouter(prefix="/api/privacy", tags=["privacy"])
_KEY = "privacy"


def load_privacy() -> None:
    with Session(get_engine()) as session:
        row = session.get(Setting, _KEY)
    ids = (row.value or {}).get("local_only_cameras", []) if row else []
    vlm_client.set_local_only(ids)


class PrivacyBody(BaseModel):
    local_only_cameras: list[int] = Field(default_factory=list)


@router.get("")
def get_privacy():
    return {"local_only_cameras": vlm_client.local_only()}


@router.put("")
def put_privacy(body: PrivacyBody):
    with Session(get_engine()) as session:
        known = {c.id for c in session.exec(select(Camera)).all()}
        ids = sorted({i for i in body.local_only_cameras if i in known})
        row = session.get(Setting, _KEY) or Setting(key=_KEY)
        row.value = {"local_only_cameras": ids}
        session.add(row)
        session.commit()
    vlm_client.set_local_only(ids)
    return {"local_only_cameras": ids}
