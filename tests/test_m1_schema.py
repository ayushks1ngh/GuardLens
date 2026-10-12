"""M1a: shared field-schema vocabulary, server-side validation, /api/meta."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from guardlens.app import app
from guardlens.events import Camera, get_engine
from guardlens.rules import Rule, register_rule, rule_types
from guardlens.schema import normalize_schema, validate_values


def test_normalizes_every_legacy_dialect():
    fields = {f["name"]: f for f in normalize_schema({
        "a": {"type": "float", "default": 1}, "b": {"type": "int"}, "c": {"type": "list[str]"},
        "classes": {"type": "list[str]"}, "line": {"type": "list[point]"},
        "start": {"type": "HH:MM"}, "url": {"type": "url", "required": True},
        "mode": {"type": "enum", "values": ["x", "y"]}, "cooldown_seconds": {"type": "number", "min": 1, "max": 9},
        "api_token": {"type": "str(env)"}, "weird": "HH:MM",
    })}
    assert fields["a"]["type"] == "number" and fields["b"]["type"] == "integer"
    assert fields["c"]["type"] == "string_list" and "widget" not in fields["c"]
    assert fields["classes"]["widget"] == "class_picker" and fields["line"]["widget"] == "line_draw"
    assert fields["start"]["widget"] == "time_of_day" and fields["weird"]["type"] == "time"
    assert fields["mode"]["enum"][0] == {"value": "x", "label": "X"}
    assert fields["cooldown_seconds"]["widget"] == "slider" and fields["cooldown_seconds"]["unit"] == "seconds"
    assert fields["api_token"]["widget"] == "secret" and fields["a"]["label"] == "A"


def test_validation_messages_are_readable():
    schema = {"seconds": {"type": "float", "min": 1, "max": 60}, "classes": {"type": "list[str]"},
              "start": {"type": "HH:MM"}, "on": {"type": "boolean"}, "n": {"type": "int"}}
    assert validate_values(schema, {"seconds": 5, "classes": ["person"], "start": "22:00", "on": True, "n": 3}) == []
    bad = {e["field"]: e["message"] for e in validate_values(
        schema, {"seconds": 0, "classes": "person", "start": "25:00", "on": "yes", "n": 1.5})}
    assert set(bad) == {"seconds", "classes", "start", "on", "n"}
    assert "at least 1" in bad["seconds"]
    assert validate_values(schema, {"extra": 1}) == []  # unknown keys are allowed


def test_rule_types_expose_fields_and_api_rejects_bad_params():
    assert all("fields" in t and "label" in t for t in rule_types())
    with TestClient(app) as client:
        with Session(get_engine()) as session:
            camera = Camera(name="Schema", source="none", enabled=False)
            session.add(camera); session.commit(); session.refresh(camera); cid = camera.id
        body = {"type": "crowd", "name": "c", "camera_id": cid, "params": {"threshold": "many"}}
        response = client.post("/api/rules", json=body)
        assert response.status_code == 422
        assert response.json()["detail"]["errors"][0]["field"] == "threshold"
        body["params"] = {"threshold": 4}
        created = client.post("/api/rules", json=body)
        assert created.status_code == 201
        assert client.patch(f"/api/rules/{created.json()['id']}", json={"params": {"threshold": -1.5}}).status_code == 422


def test_new_plugin_gets_a_form_with_no_core_edit():
    @register_rule
    class SpikeRule(Rule):
        """Detects spikes (test plugin)."""
        key = "m1_spike"
        param_schema = {"level": {"type": "number", "label": "Spike level", "min": 0, "max": 10, "unit": "units"}}
        def evaluate(self, ctx, cfg): return None
    entry = next(t for t in rule_types() if t["key"] == "m1_spike")
    assert entry["description"] == "Detects spikes (test plugin)."
    assert entry["fields"][0]["widget"] == "slider" and entry["fields"][0]["label"] == "Spike level"


def test_notifier_config_is_schema_validated():
    with TestClient(app) as client:
        bad = client.post("/api/notifiers", json={"type": "webhook", "name": "w", "config": {"url": "ftp://x"}})
        assert bad.status_code == 422
        types = client.get("/api/notifiers/types").json()
        assert types[0]["fields"][0]["name"]


def test_meta_endpoint_describes_capabilities():
    with TestClient(app) as client:
        meta = client.get("/api/meta").json()
        assert meta["name"] == "GuardLens" and "person" in meta["object_classes"]
        assert "crowd" in meta["plugins"]["rules"] and "webhook" in meta["plugins"]["notifiers"]
        assert set(meta["capabilities"]) >= {"vlm", "recording", "analysis", "https"}


def test_react_app_is_served_when_built():
    import pytest
    from guardlens.config import ROOT
    if not (ROOT / "frontend-app" / "dist" / "index.html").exists():
        pytest.skip("frontend-app not built")
    with TestClient(app) as client:
        page = client.get("/app/")
        assert page.status_code == 200 and '<div id="root">' in page.text
        assert client.get("/").status_code == 200  # classic dashboard still served
