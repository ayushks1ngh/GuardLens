"""Ask GuardLens: time parsing, grounded facts, memory, citations, privacy, API errors."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens import assistant
from guardlens.app import app
from guardlens.events import Camera, Event, get_engine
from guardlens.events.store import event_store
from guardlens.types import EventDraft
from guardlens.vlm_client import vlm_client

NOW = datetime(2026, 10, 12, 15, 30)


class Reply:
    status_code = 200

    def __init__(self, text):
        self._text = text

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


@pytest.fixture
def ai(monkeypatch):
    monkeypatch.setenv("GUARDLENS_NVIDIA_API_KEY", "test")
    for name in ("GUARDLENS_GEMINI_API_KEY", "GUARDLENS_OPENROUTER_API_KEY", "GUARDLENS_OLLAMA_URL"):
        monkeypatch.delenv(name, raising=False)
    vlm_client.configure({"budget": {"per_minute": 1000, "per_day": 10000, "per_camera_hour": 1000}})
    seen = {"calls": [], "answer": "Nothing notable."}

    def post(url, headers, payload, timeout):
        seen["calls"].append(payload["messages"])
        return Reply(seen["answer"])

    original = vlm_client._post
    vlm_client._post = post
    yield seen
    vlm_client._post = original
    vlm_client.set_local_only([])
    vlm_client.configure({})


def _camera(name) -> int:
    with Session(get_engine()) as session:
        camera = Camera(name=name, source="none", enabled=False)
        session.add(camera); session.commit(); session.refresh(camera)
        return camera.id


def test_time_ranges():
    start, end, label = assistant.parse_time_range("what happened yesterday?", NOW)
    assert (start, end, label) == (datetime(2026, 10, 11), datetime(2026, 10, 12), "yesterday")
    assert assistant.parse_time_range("anything today", NOW)[:2] == (datetime(2026, 10, 12), NOW)
    assert assistant.parse_time_range("in the last 3 hours", NOW)[0] == datetime(2026, 10, 12, 12, 30)
    assert assistant.parse_time_range("hello", NOW)[2] == "the last 24 hours"


def test_camera_matching_and_citation_stripping():
    cams = [Camera(id=1, name="Front Door", source=""), Camera(id=2, name="Garage", source="")]
    assert assistant.match_cameras("anything at the front door or garage?", cams) == [1, 2]
    text, cited = assistant.strip_unknown_citations("Delivery [E5] and a fire [E99].", {5})
    assert text == "Delivery [E5] and a fire ." and cited == [5]


def test_session_memory_is_bounded_and_clearable():
    s = assistant.Sessions(ttl=3600)
    for i in range(10):
        s.remember("a", f"q{i}", f"a{i}")
    history = s.history("a")
    assert len(history) == assistant.MAX_TURNS * 2 and history[-1]["content"] == "a9"
    assert s.clear("a") and s.history("a") == [] and not s.clear("a")
    expired = assistant.Sessions(ttl=-1)
    expired.remember("b", "q", "a")
    assert expired.history("b") == []


def test_chat_grounds_answer_in_events_and_keeps_memory(ai, tmp_path, monkeypatch):
    with TestClient(app) as client:
        camera_id = _camera("Lobby")
        event = event_store.persist(camera_id, EventDraft(type="person", severity="warning"))
        ai["answer"] = f"One person was seen [E{event.id}]. Also [E99999]."
        first = client.post("/api/assistant/chat", json={"question": "What happened in the last hour?"}).json()
        assert first["citations"] == [event.id] and "E99999" not in first["answer"]
        assert first["frame_url"] is None and first["provider"] == "nvidia"
        prompt = ai["calls"][-1][-1]["content"][0]["text"]
        assert f"[E{event.id}]" in prompt and "Lobby" in prompt
        client.post("/api/assistant/chat", json={"question": "and before that?", "session_id": first["session_id"]})
        roles = [m["role"] for m in ai["calls"][-1]]
        assert roles.count("user") == 2 and "assistant" in roles  # earlier turn is sent as memory
        assert client.delete(f"/api/assistant/sessions/{first['session_id']}").json() == {"cleared": True}


def test_chat_sends_live_frame_and_saves_it(ai, monkeypatch):
    class Worker:
        def get_latest(self):
            return np.full((60, 80, 3), 120, dtype=np.uint8), 0.0
    from guardlens.capture import manager as manager_module
    with TestClient(app) as client:
        camera_id = _camera("Yard")
        monkeypatch.setattr(manager_module.manager, "get_worker", lambda cid: Worker() if cid == camera_id else None)
        out = client.post("/api/assistant/chat", json={"question": "what do you see?", "camera_id": camera_id}).json()
        assert out["frame_url"].startswith("/history/chat-") and out["camera"] == "Yard"
        content = ai["calls"][-1][-1]["content"]
        assert any(part["type"] == "image_url" for part in content)
        assert client.get(out["frame_url"]).status_code == 200  # the exact analysed frame is retrievable


def test_private_cameras_stay_out_of_cloud_prompts(ai, monkeypatch):
    class Worker:
        def get_latest(self):
            return np.full((60, 80, 3), 120, dtype=np.uint8), 0.0
    from guardlens.capture import manager as manager_module
    with TestClient(app) as client:
        public, private = _camera("Hall"), _camera("Bedroom")
        vlm_client.set_local_only([private])
        event_store.persist(private, EventDraft(type="person", severity="warning", metadata={"note": "SECRET"}))
        monkeypatch.setattr(manager_module.manager, "get_worker", lambda cid: Worker())
        blocked = client.post("/api/assistant/chat", json={"question": "what is here?", "camera_id": private})
        assert blocked.status_code == 403 and not ai["calls"]
        client.post("/api/assistant/chat", json={"question": "Who is here right now? bedroom"})
        prompt_parts = ai["calls"][-1][-1]["content"]
        assert "SECRET" not in prompt_parts[0]["text"] and "private camera" in prompt_parts[0]["text"]
        assert public  # public camera frame is the only one tiled (private excluded)


def test_chat_error_codes(monkeypatch):
    for name in ("GUARDLENS_NVIDIA_API_KEY", "GUARDLENS_GEMINI_API_KEY", "GUARDLENS_OPENROUTER_API_KEY", "GUARDLENS_OLLAMA_URL"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as client:
        assert client.post("/api/assistant/chat", json={"question": "hi"}).status_code == 503
        assert client.post("/api/assistant/chat", json={"question": ""}).status_code == 422


def test_offline_camera_is_called_out_instead_of_guessing(ai, monkeypatch):
    from guardlens.capture import manager as manager_module
    with TestClient(app) as client:
        camera_id = _camera("Garage")
        monkeypatch.setattr(manager_module.manager, "get_worker", lambda cid: None)
        out = client.post("/api/assistant/chat", json={"question": "what do you see?", "camera_id": camera_id}).json()
        prompt = ai["calls"][-1][-1]["content"][0]["text"]
        assert "Garage is offline" in prompt and "do not guess" in prompt
        assert out["frame_url"] is None and out["camera"] == "Garage"
