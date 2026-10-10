"""Phase 4 acceptance tests: zones, behavior catalog, runtime CRUD/schema."""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from guardlens.app import app
from guardlens.rules import RuleConfig, RuleEngine, available_rules
from guardlens.types import Detection, FrameContext, Zone

ZONE = Zone(id=1, name="door", polygon=[(0, 0), (0.6, 0), (0.6, 1), (0, 1)])


def ctx(detections, ts=1000.0, zones=None):
    return FrameContext(camera_id=1, timestamp=ts, frame_shape=(100, 100), detections=detections, zones=zones or [])


def det(name="person", box=(0.1, 0.1, 0.2, 0.4), tid=1):
    return Detection(name, 0.9, box, track_id=tid)


def test_catalog_auto_discovered():
    expected = {"zone_intrusion", "loitering", "line_crossing", "crowd", "object_class", "animal", "vehicle", "abandoned_object", "package", "after_hours", "fall"}
    assert expected <= set(available_rules())


def test_zone_intrusion_and_crowd():
    intrusion = RuleEngine([RuleConfig(type="zone_intrusion", zone_id=1, cooldown_seconds=0)])
    assert intrusion.evaluate(ctx([det()], zones=[ZONE]))[0].type == "zone_intrusion"
    assert intrusion.evaluate(ctx([det(box=(0.8, 0.1, 0.9, 0.4))], zones=[ZONE])) == []
    crowd = RuleEngine([RuleConfig(type="crowd", cooldown_seconds=0, params={"threshold": 2})])
    draft = crowd.evaluate(ctx([det(tid=1), det(box=(0.3, 0.1, 0.4, 0.4), tid=2)]))[0]
    assert draft.metadata["count"] == 2


def test_loitering_and_line_crossing():
    loiter = RuleEngine([RuleConfig(type="loitering", name="l", zone_id=1, cooldown_seconds=0, params={"seconds": 5})])
    assert loiter.evaluate(ctx([det()], 1000, [ZONE]), now=1000) == []
    assert loiter.evaluate(ctx([det()], 1006, [ZONE]), now=1006)[0].type == "loitering"

    line = RuleEngine([RuleConfig(type="line_crossing", name="x", cooldown_seconds=0, params={"line": [[0.5, 0], [0.5, 1]]})])
    assert line.evaluate(ctx([det(box=(0.2, 0.2, 0.3, 0.6))], 1000), now=1000) == []
    draft = line.evaluate(ctx([det(box=(0.7, 0.2, 0.8, 0.6))], 1001), now=1001)[0]
    assert draft.metadata["direction"] in {"in", "out"}
    assert sum(draft.metadata["counters"].values()) == 1


def test_animal_vehicle_stationary_and_fall_rules():
    for rule_type, detection in [("animal", det("dog")), ("vehicle", det("car"))]:
        engine = RuleEngine([RuleConfig(type=rule_type, cooldown_seconds=0)])
        assert engine.evaluate(ctx([detection]))[0].type == rule_type

    stationary = RuleEngine([RuleConfig(type="abandoned_object", name="bag", cooldown_seconds=0, params={"seconds": 2})])
    bag = det("backpack")
    assert stationary.evaluate(ctx([bag], 1000), now=1000) == []
    assert stationary.evaluate(ctx([bag], 1003), now=1003)[0].type == "abandoned_object"

    fall = RuleEngine([RuleConfig(type="fall", name="fall", cooldown_seconds=0, params={"seconds": 1, "aspect_ratio": 1.2})])
    person = det("person", box=(0.1, 0.3, 0.8, 0.6))
    assert fall.evaluate(ctx([person], 1000), now=1000) == []
    assert fall.evaluate(ctx([person], 1002), now=1002)[0].type == "fall"


def test_zone_and_rule_crud_are_schema_driven():
    with TestClient(app) as client:
        camera = client.post("/api/cameras", json={"name": "Door", "source": "bad://", "analyze_fps": 2}).json()
        client.patch(f"/api/cameras/{camera['id']}", json={"enabled": False})
        zone = client.post(f"/api/cameras/{camera['id']}/zones", json={"name": "Entry", "polygon": [[0,0],[1,0],[1,1],[0,1]]})
        assert zone.status_code == 201
        zid = zone.json()["id"]
        rule = client.post("/api/rules", json={
            "type": "zone_intrusion", "name": "Entry alert", "camera_id": camera["id"],
            "zone_id": zid, "severity": "critical", "cooldown_seconds": 5,
            "params": {"classes": ["person"]}
        })
        assert rule.status_code == 201
        rid = rule.json()["id"]
        types = client.get("/api/rules/types").json()
        assert any(item["key"] == "zone_intrusion" for item in types)
        assert client.patch(f"/api/rules/{rid}", json={"params": {"classes": ["person", "car"]}}).json()["params"]["classes"] == ["person", "car"]
        assert client.delete(f"/api/rules/{rid}").status_code == 200
        assert client.delete(f"/api/zones/{zid}").status_code == 200


def test_stationary_rules_honor_people_and_package_spot():
    bag = det("backpack", box=(0.45, 0.45, 0.55, 0.55), tid=20)
    nearby = det("person", box=(0.50, 0.45, 0.60, 0.75), tid=21)
    abandoned = RuleEngine([RuleConfig(
        type="abandoned_object", name="clearance", cooldown_seconds=0,
        params={"seconds": 1, "person_clearance": 0.2},
    )])
    assert abandoned.evaluate(ctx([bag, nearby], 1000), now=1000) == []
    assert abandoned.evaluate(ctx([bag, nearby], 1002), now=1002) == []

    package = RuleEngine([RuleConfig(
        type="package", name="spot", cooldown_seconds=0,
        params={"seconds": 1, "spot": [0.9, 0.9], "spot_radius": 0.05},
    )])
    assert package.evaluate(ctx([bag], 1000), now=1000) == []
    assert package.evaluate(ctx([bag], 1002), now=1002) == []


def test_invalid_zone_rejected():
    with TestClient(app) as client:
        camera = client.post("/api/cameras", json={"name": "Off", "source": "x"}).json()
        assert client.post(f"/api/cameras/{camera['id']}/zones", json={"name": "bad", "polygon": [[0,0],[2,0],[0,1]]}).status_code == 422
