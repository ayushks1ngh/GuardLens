"""Zone and rule CRUD with schema-driven plugin discovery (Phase 4)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from guardlens.events import Camera, Rule, Zone, get_engine
from guardlens.rules import get_rule_class, rule_types
from guardlens.rules._policy import policy_store
from guardlens.schema import error_detail, validate_values

router = APIRouter(tags=["rules"])


def _refresh_runtime() -> None:
    policy_store.reload()
    try:
        from guardlens.analysis.pipeline import analysis_manager
        analysis_manager.set_rule_configs(policy_store.rules())
    except Exception:
        pass


def _check_params(rule_class, params) -> None:
    problems = validate_values(getattr(rule_class, "param_schema", {}), params)
    if problems:
        raise HTTPException(422, error_detail(problems))


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    polygon: list[tuple[float, float]] = Field(min_length=3)

    @field_validator("polygon")
    @classmethod
    def normalized(cls, value):
        if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in value):
            raise ValueError("polygon coordinates must be normalized 0..1")
        return value


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    polygon: Optional[list[tuple[float, float]]] = Field(default=None, min_length=3)

    @field_validator("polygon")
    @classmethod
    def normalized(cls, value):
        if value is not None and any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in value):
            raise ValueError("polygon coordinates must be normalized 0..1")
        return value


class RuleCreate(BaseModel):
    type: str
    name: str = Field(min_length=1, max_length=120)
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    severity: Literal["info", "warning", "critical"] = "warning"
    cooldown_seconds: float = Field(default=30, ge=0)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    severity: Optional[Literal["info", "warning", "critical"]] = None
    cooldown_seconds: Optional[float] = Field(default=None, ge=0)
    params: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None


@router.get("/api/cameras/{camera_id}/zones")
def list_zones(camera_id: int):
    with Session(get_engine()) as session:
        if not session.get(Camera, camera_id):
            raise HTTPException(404, "camera not found")
        return session.exec(select(Zone).where(Zone.camera_id == camera_id)).all()


@router.post("/api/cameras/{camera_id}/zones", status_code=201)
def create_zone(camera_id: int, body: ZoneCreate):
    with Session(get_engine()) as session:
        if not session.get(Camera, camera_id):
            raise HTTPException(404, "camera not found")
        zone = Zone(camera_id=camera_id, name=body.name, polygon=[list(p) for p in body.polygon])
        session.add(zone); session.commit(); session.refresh(zone)
    _refresh_runtime()
    return zone


@router.patch("/api/zones/{zone_id}")
def update_zone(zone_id: int, body: ZoneUpdate):
    with Session(get_engine()) as session:
        zone = session.get(Zone, zone_id)
        if not zone:
            raise HTTPException(404, "zone not found")
        for key, value in body.model_dump(exclude_unset=True).items():
            setattr(zone, key, [list(p) for p in value] if key == "polygon" else value)
        session.add(zone); session.commit(); session.refresh(zone)
    _refresh_runtime()
    return zone


@router.delete("/api/zones/{zone_id}")
def delete_zone(zone_id: int):
    with Session(get_engine()) as session:
        zone = session.get(Zone, zone_id)
        if not zone:
            raise HTTPException(404, "zone not found")
        rules = session.exec(select(Rule).where(Rule.zone_id == zone_id)).all()
        for rule in rules:
            rule.zone_id = None; session.add(rule)
        session.delete(zone); session.commit()
    _refresh_runtime()
    return {"status": "deleted", "id": zone_id}


@router.get("/api/rules/types")
def list_rule_types():
    return rule_types()


class ProposeBody(BaseModel):
    text: str = Field(min_length=5, max_length=500)


class PreviewBody(BaseModel):
    type: str
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    cooldown_seconds: float = Field(default=30, ge=0)
    params: dict[str, Any] = Field(default_factory=dict)
    hours: float = Field(default=72, ge=1, le=720)


@router.post("/api/rules/propose")
def propose_rule(body: ProposeBody):
    """Draft a rule from plain language. Nothing is saved; confirm by POSTing it to /api/rules."""
    from guardlens.agents import agent_runner
    outcome = agent_runner.run_now("rule_setup", "on_demand", {"text": body.text})
    if outcome["status"] == "unavailable":
        raise HTTPException(503, f"The AI helper is not available: {outcome.get('reason', 'no provider')}")
    if outcome["status"] == "disabled":
        raise HTTPException(409, "The rule setup helper is turned off. Turn it on in Agents.")
    if outcome["status"] == "budget":
        raise HTTPException(429, "The AI helper has reached its hourly limit.")
    if outcome["status"] != "ok":
        raise HTTPException(502, "The AI helper failed. Try again.")
    result = outcome["result"]
    if "error" in result:
        raise HTTPException(422, result["error"])
    return result


@router.post("/api/rules/preview")
def preview_rule(body: PreviewBody):
    """How often would this rule have fired over the last N hours of stored activity?"""
    from guardlens import rulesetup
    rule_class = get_rule_class(body.type)
    if rule_class is None:
        raise HTTPException(422, f"unknown rule type: {body.type}")
    _check_params(rule_class, body.params)
    return rulesetup.dry_run(body.model_dump(exclude={"hours"}), body.hours)


@router.get("/api/rules")
def list_rules(camera_id: Optional[int] = None):
    with Session(get_engine()) as session:
        stmt = select(Rule)
        if camera_id is not None:
            stmt = stmt.where(Rule.camera_id == camera_id)
        return session.exec(stmt.order_by(Rule.created_at)).all()


@router.post("/api/rules", status_code=201)
def create_rule(body: RuleCreate):
    rule_class = get_rule_class(body.type)
    if not rule_class:
        raise HTTPException(422, f"unknown rule type: {body.type}")
    _check_params(rule_class, body.params)
    with Session(get_engine()) as session:
        if body.camera_id is not None and not session.get(Camera, body.camera_id):
            raise HTTPException(404, "camera not found")
        if body.zone_id is not None:
            zone = session.get(Zone, body.zone_id)
            if not zone:
                raise HTTPException(404, "zone not found")
            if body.camera_id is not None and zone.camera_id != body.camera_id:
                raise HTTPException(422, "zone does not belong to the selected camera")
        rule = Rule(**body.model_dump())
        session.add(rule); session.commit(); session.refresh(rule)
    _refresh_runtime()
    return rule


@router.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate):
    with Session(get_engine()) as session:
        rule = session.get(Rule, rule_id)
        if not rule:
            raise HTTPException(404, "rule not found")
        changes = body.model_dump(exclude_unset=True)
        if "params" in changes:
            rule_class = get_rule_class(rule.type)
            if rule_class:
                _check_params(rule_class, changes["params"])
        camera_id = changes.get("camera_id", rule.camera_id)
        zone_id = changes.get("zone_id", rule.zone_id)
        if camera_id is not None and not session.get(Camera, camera_id):
            raise HTTPException(404, "camera not found")
        if zone_id is not None:
            zone = session.get(Zone, zone_id)
            if not zone:
                raise HTTPException(404, "zone not found")
            if camera_id is not None and zone.camera_id != camera_id:
                raise HTTPException(422, "zone does not belong to the selected camera")
        for key, value in changes.items():
            setattr(rule, key, value)
        session.add(rule); session.commit(); session.refresh(rule)
    _refresh_runtime()
    return rule


@router.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int):
    with Session(get_engine()) as session:
        rule = session.get(Rule, rule_id)
        if not rule:
            raise HTTPException(404, "rule not found")
        session.delete(rule); session.commit()
    _refresh_runtime()
    return {"status": "deleted", "id": rule_id}
