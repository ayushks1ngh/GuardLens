"""M2: shared VLM client, scheduler, event hooks/annotations, agent registry/runner/API."""
from __future__ import annotations

import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.agents import Agent, agent_runner, agent_types, register_agent
from guardlens.app import app
from guardlens.events import Camera, Event, get_engine
from guardlens.events.store import event_bus, event_store
from guardlens.scheduler import Scheduler
from guardlens.types import EventDraft
from guardlens.vlm import keyword_hits
from guardlens.vlm_client import ProviderSpec, VlmClient, VlmUnavailable, tile_images

FRAME = np.full((60, 80, 3), 90, dtype=np.uint8)


class FakeResponse:
    def __init__(self, status=200, text="a person at the door"):
        self.status_code = status
        self._text = text

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def make_client(monkeypatch, responses, budget=None, breaker=3):
    """Client with two keyed providers whose HTTP replies are scripted per provider URL."""
    monkeypatch.setenv("FAKE_A_KEY", "a")
    monkeypatch.setenv("FAKE_B_KEY", "b")
    client = VlmClient()
    client.configure({
        "providers": [
            {"name": "a", "base_url": "http://a", "key_env": "FAKE_A_KEY", "default_model": "ma"},
            {"name": "b", "base_url": "http://b", "key_env": "FAKE_B_KEY", "default_model": "mb"},
            {"name": "loc", "base_url": "http://l", "default_model": "ml", "local": True, "url_env": "FAKE_LOCAL_URL"},
        ],
        "chain": ["a", "b", "loc"], "budget": budget or {}, "breaker_failures": breaker,
    })
    calls = []

    def post(url, headers, payload, timeout):
        host = url.split("/chat")[0]
        calls.append(host)
        reply = responses[host]
        return reply.pop(0) if isinstance(reply, list) and len(reply) > 1 else (reply[0] if isinstance(reply, list) else reply)

    client._post = post
    client.calls = calls
    return client


def test_vlm_falls_back_when_first_provider_busy(monkeypatch):
    client = make_client(monkeypatch, {"http://a": FakeResponse(503), "http://b": FakeResponse(text="two cars")})
    result = client.ask(FRAME, "what?")
    assert (result.provider, result.text) == ("b", "two cars")
    assert client.calls == ["http://a", "http://b"]


def test_vlm_breaker_pauses_failing_provider(monkeypatch):
    client = make_client(monkeypatch, {"http://a": FakeResponse(503), "http://b": FakeResponse()}, breaker=2)
    for _ in range(3):
        client.ask(FRAME, "q")
    assert client.calls.count("http://a") == 2  # paused after 2 failures, third call skipped it
    assert next(p for p in client.status()["providers"] if p["name"] == "a")["paused"]


def test_vlm_budget_per_minute_and_camera(monkeypatch):
    client = make_client(monkeypatch, {"http://a": FakeResponse(), "http://b": FakeResponse()},
                         budget={"per_minute": 2, "per_camera_hour": 1})
    client.ask(FRAME, "q", camera_id=1)
    with pytest.raises(VlmUnavailable) as camera_limit:
        client.ask(FRAME, "q", camera_id=1)
    assert camera_limit.value.kind == "budget"
    client.ask(FRAME, "q", camera_id=2)
    with pytest.raises(VlmUnavailable) as minute_limit:
        client.ask(FRAME, "q", camera_id=3)
    assert "per-minute" in minute_limit.value.reason


def test_local_only_camera_never_reaches_cloud(monkeypatch):
    client = make_client(monkeypatch, {"http://a": FakeResponse(), "http://b": FakeResponse()})
    client.set_local_only([7])
    with pytest.raises(VlmUnavailable) as blocked:
        client.ask(FRAME, "q", camera_id=7)
    assert blocked.value.kind == "privacy" and client.calls == []
    assert client.ask(FRAME, "q", camera_id=8).provider == "a"
    monkeypatch.setenv("FAKE_LOCAL_URL", "http://l")
    client._post = lambda url, h, p, t: FakeResponse(text="local answer")
    assert client.ask(FRAME, "q", camera_id=7).provider == "loc"


def test_vlm_cache_and_no_provider(monkeypatch):
    client = make_client(monkeypatch, {"http://a": FakeResponse()})
    first = client.ask(FRAME, "same", cache=True)
    again = client.ask(FRAME, "same", cache=True)
    assert not first.cached and again.cached and client.calls == ["http://a"]
    monkeypatch.delenv("FAKE_A_KEY"); monkeypatch.delenv("FAKE_B_KEY")
    with pytest.raises(VlmUnavailable) as none:
        client.ask(FRAME, "different")
    assert none.value.kind == "unconfigured"


def test_tile_images_and_keyword_negation():
    grid = tile_images([FRAME] * 3)
    assert grid.shape[0] > 0 and grid.shape[1] > FRAME.shape[1]
    assert keyword_hits("Yes, a knife is on the table.", ["knife"]) == ["knife"]
    assert keyword_hits("No knife visible.", ["knife"]) == []
    assert keyword_hits("There is no one here but a knife lies on the floor", ["knife"]) == ["knife"]


def test_scheduler_runs_due_jobs_and_isolates_failures():
    s = Scheduler(tick_seconds=1)
    ran = []
    s.add_job("ok", lambda: ran.append(1), every=0.01)
    s.add_job("boom", lambda: 1 / 0, every=0.01)
    time.sleep(0.05)
    assert s.run_due() == 2 and ran == [1]
    status = {j["name"]: j["last_status"] for j in s.jobs()}
    assert status["ok"] == "ok" and status["boom"].startswith("error")
    with pytest.raises(ValueError):
        s.add_job("bad", lambda: None)
    assert s.run_now("ok") and not s.run_now("missing")


def _camera() -> int:
    with Session(get_engine()) as session:
        camera = Camera(name="Agent", source="none", enabled=False)
        session.add(camera); session.commit(); session.refresh(camera)
        return camera.id


def _annotation(event_id, key, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        with Session(get_engine()) as session:
            meta = session.get(Event, event_id).event_metadata or {}
        if key in (meta.get("agent") or {}):
            return meta["agent"][key]
        time.sleep(0.05)
    return None


@register_agent
class DummyAgent(Agent):
    """Echo agent used to prove the registry needs no core edits."""
    key = "m2_dummy"
    label = "Dummy"
    param_schema = {"greeting": {"type": "string", "default": "hi", "label": "Greeting"}}

    def on_event(self, event, ctx):
        return {"title": f"{ctx.params['greeting']} {event['type']}", "verdict": "ok"}


@register_agent
class NeedsAi(Agent):
    key = "m2_needs_ai"
    requires_vlm = True
    def on_event(self, event, ctx):
        return {"title": "never"}


def test_agent_annotates_events_and_is_audited():
    with TestClient(app) as client:
        agent_runner.save_config("m2_dummy", {"enabled": True, "greeting": "yo", "event_types": ["m2_a"]})
        camera_id = _camera()
        before = event_bus._sequence
        hit = event_store.persist(camera_id, EventDraft(type="m2_a", severity="info"))
        miss = event_store.persist(camera_id, EventDraft(type="m2_other", severity="info"))
        note = _annotation(hit.id, "m2_dummy")
        assert note["title"] == "yo m2_a" and note["mode"] == "suggest" and "created_at" in note
        time.sleep(0.3)
        with Session(get_engine()) as session:
            assert "agent" not in (session.get(Event, miss.id).event_metadata or {})
        updates = [i for i in event_bus.after(before) if i.get("kind") == "event.updated"]
        assert updates and updates[-1]["id"] == hit.id
        runs = client.get("/api/agents/runs", params={"agent": "m2_dummy"}).json()
        assert runs[0]["status"] == "ok" and runs[0]["event_id"] == hit.id
        agent_runner.save_config("m2_dummy", {"enabled": False})


def test_agent_budget_unavailable_and_idempotence():
    with TestClient(app):
        agent_runner._hour.clear()
        agent_runner.save_config("m2_dummy", {"enabled": True, "event_types": [], "max_runs_per_hour": 1})
        agent_runner.save_config("m2_needs_ai", {"enabled": True})
        camera_id = _camera()
        first = event_store.persist(camera_id, EventDraft(type="m2_b", severity="info"))
        assert _annotation(first.id, "m2_dummy")
        second = event_store.persist(camera_id, EventDraft(type="m2_b", severity="info"))
        time.sleep(0.5)
        statuses = {r.status for r in agent_runner.runs("m2_dummy", 10)}
        assert "budget" in statuses  # hourly cap stopped the second run
        with Session(get_engine()) as session:
            assert "agent" not in (session.get(Event, second.id).event_metadata or {})
        assert agent_runner.status("m2_needs_ai")["state"] == "unavailable"
        assert {r.status for r in agent_runner.runs("m2_needs_ai", 5)} <= {"unavailable"}
        agent_runner.save_config("m2_dummy", {"enabled": False, "max_runs_per_hour": 60})
        agent_runner.save_config("m2_needs_ai", {"enabled": False})


def test_listener_failure_never_breaks_persistence():
    def bad(_payload): raise RuntimeError("nope")
    with TestClient(app):
        event_store.add_listener(bad)
        try:
            event = event_store.persist(_camera(), EventDraft(type="m2_c", severity="info"))
            assert event.id is not None
        finally:
            event_store.remove_listener(bad)


def test_agents_api_lists_configures_and_validates():
    with TestClient(app) as client:
        listing = {a["key"]: a for a in client.get("/api/agents").json()}
        dummy = listing["m2_dummy"]
        names = [f["name"] for f in dummy["fields"]]
        assert {"enabled", "mode", "max_runs_per_hour", "min_severity", "event_types", "greeting"} <= set(names)
        assert agent_types() and dummy["status"]["state"] in {"off", "active"}
        assert client.put("/api/agents/m2_dummy", json={"config": {"mode": "act"}}).status_code == 422
        assert client.put("/api/agents/m2_dummy", json={"config": {"max_runs_per_hour": 0}}).status_code == 422
        ok = client.put("/api/agents/m2_dummy", json={"config": {"greeting": "hello", "enabled": False}})
        assert ok.status_code == 200 and ok.json()["config"]["greeting"] == "hello"
        assert client.put("/api/agents/nope", json={"config": {}}).status_code == 404
        assert client.get("/api/agents/scheduler").status_code == 200
        assert "providers" in client.get("/api/agents/ai").json()


def test_privacy_api_persists_local_only_cameras():
    from guardlens.vlm_client import vlm_client
    with TestClient(app) as client:
        camera_id = _camera()
        saved = client.put("/api/privacy", json={"local_only_cameras": [camera_id, 99999]}).json()
        assert saved["local_only_cameras"] == [camera_id]
        assert vlm_client.local_only() == [camera_id]
        client.put("/api/privacy", json={"local_only_cameras": []})
        assert client.get("/api/privacy").json()["local_only_cameras"] == []
