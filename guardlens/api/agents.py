"""Agent management: list, configure, run on demand, audit log, scheduler status."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from guardlens.agents import agent_runner, agent_types, get_agent_class
from guardlens.scheduler import scheduler
from guardlens.schema import error_detail
from guardlens.vlm_client import vlm_client

router = APIRouter(prefix="/api/agents", tags=["agents"])


class ConfigBody(BaseModel):
    config: dict[str, Any]


class RunBody(BaseModel):
    payload: Optional[dict[str, Any]] = Field(default=None)


@router.get("")
def list_agents():
    return [
        {**spec, "config": agent_runner.config_for(spec["key"]), "status": agent_runner.status(spec["key"])}
        for spec in agent_types()
    ]


@router.get("/runs")
def agent_runs(agent: Optional[str] = None, limit: int = Query(50, ge=1, le=500)):
    return agent_runner.runs(agent, limit)


@router.get("/scheduler")
def scheduler_status():
    return scheduler.jobs()


@router.get("/ai")
def ai_status():
    return vlm_client.status()


@router.put("/{key}")
def configure_agent(key: str, body: ConfigBody):
    if get_agent_class(key) is None:
        raise HTTPException(404, "unknown agent")
    try:
        merged = agent_runner.save_config(key, body.config)
    except ValueError as exc:
        raise HTTPException(422, error_detail(exc.args[0])) from exc
    return {"config": merged, "status": agent_runner.status(key)}


@router.post("/{key}/run")
def run_agent(key: str, body: RunBody = RunBody()):
    if get_agent_class(key) is None:
        raise HTTPException(404, "unknown agent")
    return agent_runner.run_now(key, "on_demand", body.payload)
