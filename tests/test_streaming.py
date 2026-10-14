"""Streaming chat: words arrive as they are written; failures degrade cleanly."""
from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from guardlens.app import app
from guardlens.vlm_client import _SSE_DONE, VlmUnavailable, _sse_delta, vlm_client


def _line(text):
    return f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}".encode()


class Stream:
    def __init__(self, lines, status=200, break_after=None):
        self.status_code, self._lines, self._break_after, self.closed = status, lines, break_after, False

    def iter_lines(self):
        for i, line in enumerate(self._lines):
            if self._break_after is not None and i >= self._break_after:
                raise ConnectionError("dropped")
            yield line

    def close(self):
        self.closed = True


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("GUARDLENS_NVIDIA_API_KEY", "test")
    monkeypatch.setenv("GUARDLENS_GEMINI_API_KEY", "test")
    for name in ("GUARDLENS_OPENROUTER_API_KEY", "GUARDLENS_OLLAMA_URL"):
        monkeypatch.delenv(name, raising=False)
    vlm_client.configure({"budget": {"per_minute": 1000, "per_day": 10000, "per_camera_hour": 1000}})
    calls = {"urls": [], "script": []}
    original = vlm_client._stream

    def fake(url, headers, payload, timeout):
        calls["urls"].append(url)
        assert payload["stream"] is True
        return calls["script"].pop(0)

    vlm_client._stream = fake
    yield calls
    vlm_client._stream = original
    vlm_client.configure({})


def test_sse_line_parsing():
    assert _sse_delta(_line("Hel")) == "Hel"
    assert _sse_delta(b"data: [DONE]") is _SSE_DONE
    assert _sse_delta(b": keep-alive") is None and _sse_delta(b"") is None
    assert _sse_delta(b"data: {not json") is None
    assert _sse_delta(b'data: {"choices": []}') is None
    assert _sse_delta(b'data: {"choices": [{"delta": {"role": "assistant"}}]}') is None


def test_words_arrive_in_order_then_a_final_result(providers):
    stream = Stream([_line("Two "), _line("people "), _line("walk."), b"data: [DONE]"])
    providers["script"].append(stream)
    events = list(vlm_client.ask_stream(np.zeros((8, 8, 3), np.uint8), "what?"))
    assert [e["text"] for e in events if e["type"] == "delta"] == ["Two ", "people ", "walk."]
    done = events[-1]
    assert done["type"] == "done" and done["result"].text == "Two people walk." and stream.closed


def test_falls_back_to_the_next_provider_before_any_word(providers):
    providers["script"] += [Stream([], status=500), Stream([_line("ok"), b"data: [DONE]"])]
    events = list(vlm_client.ask_stream(None, "q"))
    assert events[-1]["result"].text == "ok" and len(providers["urls"]) == 2
    assert providers["urls"][0] != providers["urls"][1]  # a different provider answered


def test_a_dropped_connection_keeps_the_words_already_received(providers):
    providers["script"].append(Stream([_line("Someone is at "), _line("the door"), _line("never")], break_after=2))
    events = list(vlm_client.ask_stream(None, "q"))
    assert events[-1]["result"].text == "Someone is at the door …" and len(providers["urls"]) == 1


def test_all_providers_failing_raises(providers):
    providers["script"] += [Stream([], status=429), Stream([b"data: [DONE]"])]  # second one: empty answer
    with pytest.raises(VlmUnavailable) as info:
        list(vlm_client.ask_stream(None, "q"))
    assert info.value.kind == "failed"


def test_chat_stream_endpoint_sends_meta_words_and_the_cleaned_final_answer(providers):
    from sqlmodel import Session
    from guardlens.events import Camera, get_engine
    providers["script"].append(Stream([_line("Quiet. "), _line("See [E99999]."), b"data: [DONE]"]))
    with TestClient(app) as client:
        with Session(get_engine()) as session:
            session.add(Camera(name="Hall", source="none", enabled=False)); session.commit()
        response = client.post("/api/assistant/chat/stream", json={"question": "what happened today?"})
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
        events = [(b.split("\n")[0][7:], json.loads(b.split("\n")[1][6:])) for b in response.text.strip().split("\n\n")]
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done" and kinds.count("delta") == 2
    final = events[-1][1]
    assert "E99999" not in final["answer"] and final["answer"].startswith("Quiet.")  # unknown citation stripped
    assert final["provider"] and final["session_id"] == events[0][1]["session_id"]


def test_endpoint_reports_provider_failure_as_http_error_not_a_broken_stream(providers):
    providers["script"] += [Stream([], status=500), Stream([], status=500)]
    with TestClient(app) as client:
        response = client.post("/api/assistant/chat/stream", json={"question": "hi"})
    assert response.status_code == 502


def test_endpoint_without_any_provider_is_503(monkeypatch):
    for name in ("GUARDLENS_NVIDIA_API_KEY", "GUARDLENS_GEMINI_API_KEY", "GUARDLENS_OPENROUTER_API_KEY", "GUARDLENS_OLLAMA_URL"):
        monkeypatch.delenv(name, raising=False)
    vlm_client.configure({})
    with TestClient(app) as client:
        assert client.post("/api/assistant/chat/stream", json={"question": "hi"}).status_code == 503
