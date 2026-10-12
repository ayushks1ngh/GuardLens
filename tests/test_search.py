"""Footage search with a deterministic colour 'CLIP' so no model download is needed."""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from guardlens.app import app
from guardlens.events import Camera, Event, EventEmbedding, get_engine
from guardlens.events.store import event_store
from guardlens.search import search_service
from guardlens.search.service import _crops, split_query
from guardlens.types import EventDraft

COLORS = {"red": (0, 0, 255), "green": (0, 255, 0), "blue": (255, 0, 0)}  # BGR


class ColourEmbedder:
    """Image vector = normalised mean RGB; text vector built from colour words."""
    name = "colour-test"

    def encode_images(self, frames):
        out = []
        for f in frames:
            b, g, r = f.reshape(-1, 3).mean(axis=0)
            v = np.array([r, g, b], dtype=np.float32)
            out.append(v / max(np.linalg.norm(v), 1e-9))
        return np.stack(out)

    def encode_text(self, text):
        v = np.zeros(3, dtype=np.float32)
        for i, word in enumerate(("red", "green", "blue")):
            if word in text.lower():
                v[i] = 1
        return v / max(np.linalg.norm(v), 1e-9)


@pytest.fixture
def search(tmp_path):
    with TestClient(app) as client:
        event_store.configure(tmp_path / "snap")
        search_service.configure(tmp_path / "snap")
        search_service.set_embedder(ColourEmbedder())
        search_service._settings["enabled"] = True
        search_service._matrix = None
        yield client
        search_service._settings["enabled"] = False
        search_service._embedder = None
        search_service._matrix = None


def _event(camera_id, colour, type_="person", metadata=None):
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    frame[:] = COLORS[colour]
    event = event_store.persist(camera_id, EventDraft(type=type_, severity="info", snapshot=frame, metadata=metadata or {}))
    search_service.index_event(event.id)
    return event


def _camera(name="Search cam") -> int:
    with Session(get_engine()) as session:
        camera = Camera(name=name, source="none", enabled=False)
        session.add(camera); session.commit(); session.refresh(camera)
        return camera.id


def test_query_splitting_and_crops():
    assert split_query("person in a red jacket yesterday") == "person in a red jacket"
    assert split_query("white van in the last 3 hours") == "white van"
    frame = np.full((100, 200, 3), 50, dtype=np.uint8)
    crops = _crops(frame, {"boxes": [{"class": "person", "bbox": [0.1, 0.1, 0.5, 0.9]}, {"bbox": "bad"}, {"bbox": [0.5, 0.5, 0.505, 0.505]}]})
    assert len(crops) == 1 and crops[0].shape[0] > 50  # bad / tiny boxes skipped


def test_search_ranks_by_picture_and_finds_similar(search):
    camera_id = _camera()
    red, green = _event(camera_id, "red"), _event(camera_id, "green")
    found = search.get("/api/search", params={"q": "something red"}).json()["results"]
    assert found[0]["event_id"] == red.id and found[0]["source"] == "picture"
    assert found[0]["score"] > [r for r in found if r["event_id"] == green.id][0]["score"]
    top = search.get("/api/search", params={"q": "green thing"}).json()["results"]
    assert top[0]["event_id"] == green.id
    twin = _event(camera_id, "red")
    sim = search.get(f"/api/search/similar/{red.id}").json()["results"]
    assert sim[0]["event_id"] == twin.id and red.id not in [r["event_id"] for r in sim]


def test_search_filters_and_text_blend(search):
    cam_a, cam_b = _camera("Alpha"), _camera("Beta")
    a, b = _event(cam_a, "blue"), _event(cam_b, "blue")
    only_b = search.get("/api/search", params={"q": "blue", "camera_id": cam_b}).json()["results"]
    assert [r["event_id"] for r in only_b] == [b.id]
    event_store.annotate(a.id, "event_triage", {"title": "Courier with parcel", "summary": "A courier leaves a box."})
    by_text = search.get("/api/search", params={"q": "courier parcel"}).json()["results"]
    assert by_text and by_text[0]["event_id"] == a.id and by_text[0]["source"] in ("text", "both")
    assert by_text[0]["title"] == "Courier with parcel" and by_text[0]["score"] > by_text[1]["score"]
    assert search.get("/api/search", params={"q": "blue", "from": "2999-01-01T00:00:00"}).json()["results"] == []


def test_indexing_stores_frame_and_crop_vectors_and_is_idempotent(search):
    camera_id = _camera()
    event = _event(camera_id, "red", metadata={"boxes": [{"class": "person", "bbox": [0.0, 0.0, 1.0, 1.0]}]})
    with Session(get_engine()) as session:
        kinds = sorted(r.kind for r in session.exec(select(EventEmbedding).where(EventEmbedding.event_id == event.id)))
    assert kinds == ["crop", "frame"]
    assert search_service.index_event(event.id) == 0  # already indexed
    assert search_service.index_event(event.id, force=True) == 2
    status = search_service.status()
    assert status["indexed_events"] >= 1 and status["enabled"]


def test_search_api_off_and_settings(tmp_path):
    with TestClient(app) as client:
        search_service._settings["enabled"] = False
        assert client.get("/api/search", params={"q": "red"}).status_code == 409
        assert client.post("/api/search/reindex").status_code == 409
        assert client.get("/api/search/status").json()["enabled"] is False
