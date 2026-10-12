"""Natural-language rule setup: validation, dry-run replay, and the propose/preview API."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens import rulesetup
from guardlens.agents import agent_runner
from guardlens.app import app
from guardlens.events import ActivityLog, Camera, Zone, get_engine
from guardlens.vlm_client import vlm_client


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
    seen = {"answer": "{}", "prompts": []}

    def post(url, headers, payload, timeout):
        seen["prompts"].append(payload["messages"][-1]["content"][0]["text"])
        return Reply(seen["answer"])

    original = vlm_client._post
    vlm_client._post = post
    yield seen
    vlm_client._post = original
    vlm_client.configure({})


def _setup():
    with Session(get_engine()) as session:
        camera = Camera(name="Back door", source="none", enabled=False)
        session.add(camera); session.commit(); session.refresh(camera)
        zone = Zone(camera_id=camera.id, name="Doorstep", polygon=[(0, 0), (1, 0), (1, 1)])
        session.add(zone); session.commit(); session.refresh(zone)
        return camera.id, zone.id


def _samples(camera_id, hits, hours=2, interval=10):
    """Activity rows: ``hits`` = list of (minutes_ago, summary)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(get_engine()) as session:
        for minutes_ago, summary in hits:
            session.add(ActivityLog(camera_id=camera_id, timestamp=now - timedelta(minutes=minutes_ago), summary=summary))
        session.commit()


def test_parse_and_validate_flags_every_kind_of_problem():
    assert rulesetup.parse_proposal("Sure: {\"type\": \"crowd\"} done")["type"] == "crowd"
    assert rulesetup.parse_proposal("nothing") is None
    with TestClient(app):
        cam, zone = _setup()
        good = rulesetup.validate_proposal({"type": "crowd", "camera_id": cam, "severity": "critical",
                                            "cooldown_seconds": 60, "params": {"threshold": 4, "classes": ["person"]}})
        assert good["problems"] == [] and good["severity"] == "critical"
        bad = rulesetup.validate_proposal({"type": "teleport", "camera_id": 99999, "params": {}})
        assert len(bad["problems"]) == 2
        noisy = rulesetup.validate_proposal({"type": "crowd", "zone_id": 99999, "params": {
            "threshold": "many", "classes": ["unicorn"], "bogus": 1}})
        text = " ".join(noisy["problems"])
        assert "zone) does not exist" in text and "unicorn" in text and "bogus" in text and "number" in text
        assert "bogus" not in noisy["params"]
        assert rulesetup.validate_proposal({"type": "crowd", "severity": "apocalyptic"})["severity"] == "warning"


def test_dry_run_counts_cooldown_and_rule_types():
    with TestClient(app):
        cam, zone = _setup()
        person = {"classes": {"person": 1}, "zones_active": []}
        crowd = {"classes": {"person": 6}, "zones_active": [zone]}
        _samples(cam, [(30, person), (29.9, person), (20, crowd), (19.5, crowd), (10, crowd)])
        rule = {"type": "crowd", "camera_id": cam, "zone_id": None, "cooldown_seconds": 60, "params": {"threshold": 5}}
        result = rulesetup.dry_run(rule, hours=1)
        assert result["supported"] and result["samples_checked"] == 5
        assert result["would_fire"] == 2  # 20min and 10min; the 19.5min repeat is inside the 60s cooldown? no: 30s gap
        assert rulesetup.dry_run({**rule, "params": {"threshold": 7}}, 1)["would_fire"] == 0
        intrusion = rulesetup.dry_run({"type": "zone_intrusion", "camera_id": cam, "zone_id": zone,
                                       "cooldown_seconds": 0, "params": {}}, 1)
        assert intrusion["would_fire"] == 3
        assert not rulesetup.dry_run({"type": "fall", "camera_id": cam, "cooldown_seconds": 0, "params": {}})["supported"]
        empty = rulesetup.dry_run({**rule, "camera_id": 99999}, 1)
        assert empty["would_fire"] == 0 and "nothing to preview" in empty["note"]


def test_loitering_needs_consecutive_samples():
    state = {"interval": 10}
    rule = {"type": "loitering", "zone_id": 7, "params": {"seconds": 30}}
    stamp = datetime.now()
    inside = {"classes": {"person": 1}, "zones_active": [7]}
    outside = {"classes": {"person": 1}, "zones_active": []}
    results = [rulesetup.sample_hits(rule, s, stamp, state) for s in (inside, inside, outside, inside, inside, inside)]
    assert results == [False, False, False, False, False, True]


def test_after_hours_window_uses_local_time():
    rule = {"type": "after_hours", "params": {"start": "22:00", "end": "06:00"}}
    summary = {"classes": {"person": 1}}
    night = datetime(2026, 1, 1, 23, 30)
    noon = datetime(2026, 1, 1, 12, 0)
    assert rulesetup.sample_hits(rule, summary, night, {}) and not rulesetup.sample_hits(rule, summary, noon, {})


def test_propose_endpoint_returns_validated_draft_with_preview_and_never_saves(ai):
    with TestClient(app) as client:
        cam, zone = _setup()
        _samples(cam, [(5, {"classes": {"person": 1}, "zones_active": [zone]})])
        agent_runner._hour.clear()
        ai["answer"] = json.dumps({"type": "zone_intrusion", "name": "Back door watch", "camera_id": cam, "zone_id": zone,
                                   "severity": "critical", "cooldown_seconds": 30, "params": {"classes": ["person"]},
                                   "explanation": "Alert when a person enters the doorstep."})
        before = len(client.get("/api/rules").json())
        draft = client.post("/api/rules/propose", json={"text": "alert me if anyone is on the back door step"}).json()
        assert draft["proposal"]["problems"] == [] and draft["proposal"]["zone_id"] == zone
        assert draft["preview"]["supported"] and draft["preview"]["would_fire"] == 1
        assert len(client.get("/api/rules").json()) == before  # drafting never saves
        assert "Back door" in ai["prompts"][-1] and "zone_intrusion" in ai["prompts"][-1]
        # the user then confirms through the ordinary rules API
        created = client.post("/api/rules", json={k: draft["proposal"][k] for k in (
            "type", "name", "camera_id", "zone_id", "severity", "cooldown_seconds", "params")})
        assert created.status_code == 201


def test_propose_endpoint_handles_bad_answers_and_disabled_helper(ai):
    with TestClient(app) as client:
        agent_runner._hour.clear()
        ai["answer"] = "I cannot do that"
        assert client.post("/api/rules/propose", json={"text": "do something odd please"}).status_code == 422
        ai["answer"] = json.dumps({"type": "teleport", "params": {}})
        draft = client.post("/api/rules/propose", json={"text": "make a teleport rule please"}).json()
        assert draft["proposal"]["problems"] and draft["preview"] is None
        assert client.post("/api/rules/propose", json={"text": "hi"}).status_code == 422
        agent_runner.save_config("rule_setup", {"enabled": False})
        assert client.post("/api/rules/propose", json={"text": "alert on anyone at night"}).status_code == 409
        agent_runner.save_config("rule_setup", {"enabled": True})


def test_preview_endpoint_validates_params():
    with TestClient(app) as client:
        cam, _ = _setup()
        ok = client.post("/api/rules/preview", json={"type": "crowd", "camera_id": cam, "params": {"threshold": 3}})
        assert ok.status_code == 200 and ok.json()["supported"]
        assert client.post("/api/rules/preview", json={"type": "crowd", "params": {"threshold": "x"}}).status_code == 422
        assert client.post("/api/rules/preview", json={"type": "nope", "params": {}}).status_code == 422
