"""Agent plugin registry and runner (docs/12, docs/13 M2).

An *agent* is a small plugin that reacts to an event, a schedule, or an on-demand request and
returns *suggestions* (annotations on an event, a briefing, answers). Agents follow the same
discipline as detectors/rules/notifiers: drop a module into ``guardlens/agents/``, decorate the
class with ``@register_agent``, and it is auto-discovered, configurable from the UI via its
``param_schema``, budgeted, audited, and switched off on its own when its dependencies
(e.g. an AI provider) are missing. Agents are never per-frame, and in this release they are
suggest-only: they annotate and answer, they do not act on the world.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from sqlmodel import Session, select

from guardlens.events import AgentRun, Setting, get_engine, utcnow
from guardlens.schema import normalize_schema, validate_values
from guardlens.vlm_client import VlmUnavailable, vlm_client

logger = logging.getLogger("guardlens.agents")

_SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
# Settings every agent has; merged in front of the agent's own param_schema in the UI.
COMMON_SCHEMA: dict[str, dict] = {
    "enabled": {"type": "boolean", "default": False, "label": "Turned on"},
    "mode": {"type": "enum", "default": "suggest", "label": "What it may do",
             "help": "Agents only suggest for now: they add notes and answers, never take actions.",
             "enum": [{"value": "suggest", "label": "Suggest only"}]},
    "max_runs_per_hour": {"type": "integer", "default": 60, "min": 1, "max": 1000, "label": "Most runs per hour",
                          "help": "A safety cap so an agent can never flood the CPU or your AI quota."},
}
EVENT_SCHEMA: dict[str, dict] = {
    "min_severity": {"type": "enum", "default": "info", "label": "Only for alerts at least",
                     "enum": [{"value": "info", "label": "Info"}, {"value": "warning", "label": "Warning"},
                              {"value": "critical", "label": "Critical"}]},
    "event_types": {"type": "list[str]", "default": [], "label": "Only these alert types",
                    "help": "Leave empty to cover every type."},
}
SCHEDULE_SCHEMA: dict[str, dict] = {
    "daily_at": {"type": "HH:MM", "default": "23:30", "label": "Run every day at"},
}


@dataclass
class AgentContext:
    """Everything an agent may use; agents import nothing from the core directly."""
    agent_key: str
    params: dict
    vlm: Any = vlm_client

    @property
    def event_store(self):
        from guardlens.events.store import event_store
        return event_store


class Agent:
    key: str = ""
    label: str = ""
    description: str = ""
    param_schema: dict = {}
    triggers: tuple[str, ...] = ("event",)     # any of: event, schedule, on_demand
    requires_vlm: bool = False

    def setup(self, params: dict) -> None:
        """Called whenever the agent's settings change."""

    def on_event(self, event: dict, ctx: AgentContext) -> Optional[dict]:
        """Return an annotation (stored under event_metadata.agent.<key>) or None."""
        return None

    def run(self, ctx: AgentContext, trigger: str, payload: Optional[dict]) -> Optional[dict]:
        """Scheduled / on-demand entry point; the returned dict is stored in the audit log."""
        return None

    def available(self) -> tuple[bool, str]:
        if self.requires_vlm and not vlm_client.available:
            return False, "needs an AI provider (set a key such as GUARDLENS_NVIDIA_API_KEY)"
        return True, ""


_REGISTRY: dict[str, type[Agent]] = {}


def register_agent(cls: type[Agent]) -> type[Agent]:
    if not getattr(cls, "key", ""):
        raise ValueError("agent class needs a non-empty `key`")
    if cls.key in _REGISTRY:
        logger.warning("agent %r already registered; overriding", cls.key)
    _REGISTRY[cls.key] = cls
    return cls


def get_agent_class(key: str) -> Optional[type[Agent]]:
    return _REGISTRY.get(key)


def schema_for(cls: type[Agent]) -> dict:
    schema = dict(COMMON_SCHEMA)
    if "event" in cls.triggers:
        schema.update(EVENT_SCHEMA)
    if "schedule" in cls.triggers:
        schema.update(SCHEDULE_SCHEMA)
    schema.update(cls.param_schema)
    return schema


def agent_types() -> list[dict]:
    return [
        {
            "key": k, "label": c.label or k.replace("_", " ").capitalize(),
            "description": c.description or ((c.__doc__ or "").strip().splitlines()[0] if c.__doc__ else ""),
            "triggers": list(c.triggers), "requires_vlm": c.requires_vlm,
            "fields": normalize_schema(schema_for(c)),
        }
        for k, c in sorted(_REGISTRY.items())
    ]


def _discover() -> None:
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if module.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{module.name}")
        except Exception:
            logger.exception("failed to load agent module %s", module.name)


class AgentRunner:
    """Owns agent instances, their stored settings, budgets, and the audit log."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._configs: dict[str, dict] = {}
        self._hour: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="agent")
        self._scheduler = None

    # -- settings --------------------------------------------------------
    @staticmethod
    def _setting_key(key: str) -> str:
        return f"agent:{key}"

    def config_for(self, key: str) -> dict:
        cls = get_agent_class(key)
        if cls is None:
            return {}
        stored: dict = {}
        with Session(get_engine()) as session:
            row = session.get(Setting, self._setting_key(key))
            if row and isinstance(row.value, dict):
                stored = row.value
        defaults = {name: spec.get("default") for name, spec in schema_for(cls).items() if "default" in spec}
        return {**defaults, **stored}

    def save_config(self, key: str, values: dict) -> dict:
        cls = get_agent_class(key)
        if cls is None:
            raise KeyError(key)
        errors = validate_values(schema_for(cls), values)
        if errors:
            raise ValueError(errors)
        merged = {**self.config_for(key), **values}
        with Session(get_engine()) as session:
            row = session.get(Setting, self._setting_key(key)) or Setting(key=self._setting_key(key))
            row.value = merged
            session.add(row)
            session.commit()
        self.reload()
        return merged

    def reload(self) -> None:
        """Rebuild agent instances from stored settings and re-register scheduled jobs."""
        agents, configs = {}, {}
        for key, cls in _REGISTRY.items():
            config = self.config_for(key)
            instance = self._agents.get(key) or cls()
            try:
                instance.setup(config)
            except Exception:
                logger.exception("agent %s setup failed", key)
                config = {**config, "enabled": False}
            agents[key], configs[key] = instance, config
        with self._lock:
            self._agents, self._configs = agents, configs
        self._sync_schedule()

    def _sync_schedule(self) -> None:
        if self._scheduler is None:
            return
        self._scheduler.remove_prefix("agent:")
        for key, agent in self._agents.items():
            config = self._configs[key]
            if "schedule" in agent.triggers and config.get("enabled") and config.get("daily_at"):
                self._scheduler.add_job(
                    f"agent:{key}", lambda k=key: self.run_now(k, "schedule"), daily_at=config["daily_at"])

    def attach_scheduler(self, scheduler) -> None:
        self._scheduler = scheduler
        self._sync_schedule()

    # -- status ------------------------------------------------------------
    def status(self, key: str) -> dict:
        agent, config = self._agents.get(key), self._configs.get(key, {})
        if agent is None:
            return {"state": "unknown", "message": "Unknown agent."}
        ok, why = agent.available()
        if not config.get("enabled"):
            return {"state": "off", "message": "Turned off."}
        if not ok:
            return {"state": "unavailable", "message": f"On, but waiting: {why}."}
        with self._lock:
            used = len(self._hour[key])
        return {"state": "active", "message": "Active.", "runs_last_hour": used}

    # -- execution -----------------------------------------------------
    def _budget_ok(self, key: str, limit: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._hour[key]
            while q and now - q[0] > 3600:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def _log(self, key: str, trigger: str, event_id: Optional[int], status: str, started: float, detail: dict) -> None:
        try:
            with Session(get_engine()) as session:
                session.add(AgentRun(
                    agent_key=key, trigger=trigger, event_id=event_id, status=status,
                    duration_ms=int((time.time() - started) * 1000), detail=detail))
                session.commit()
        except Exception:
            logger.exception("could not write agent audit row")

    def _execute(self, key: str, trigger: str, event: Optional[dict], payload: Optional[dict] = None) -> dict:
        agent, config = self._agents[key], self._configs[key]
        started, event_id = time.time(), (event or {}).get("id")
        ok, why = agent.available()
        if not ok:
            self._log(key, trigger, event_id, "unavailable", started, {"reason": why})
            return {"status": "unavailable", "reason": why}
        if not self._budget_ok(key, int(config.get("max_runs_per_hour") or 60)):
            self._log(key, trigger, event_id, "budget", started, {"reason": "hourly run limit reached"})
            return {"status": "budget"}
        ctx = AgentContext(agent_key=key, params=config)
        try:
            if trigger == "event" and event is not None:
                annotation = agent.on_event(event, ctx)
                if annotation is None:
                    self._log(key, trigger, event_id, "skipped", started, {})
                    return {"status": "skipped"}
                annotation = {**annotation, "created_at": utcnow().isoformat(), "mode": config.get("mode", "suggest")}
                ctx.event_store.annotate(event["id"], key, annotation)
                self._log(key, trigger, event_id, "ok", started, {
                    k: annotation[k] for k in ("provider", "model", "verdict", "threat", "repeat_of", "unusual") if k in annotation})
                return {"status": "ok", "annotation": annotation}
            result = agent.run(ctx, trigger, payload) or {}
            self._log(key, trigger, event_id, "ok", started, result if isinstance(result, dict) else {})
            return {"status": "ok", "result": result}
        except VlmUnavailable as exc:
            self._log(key, trigger, event_id, "unavailable", started, {"reason": exc.reason})
            return {"status": "unavailable", "reason": exc.reason}
        except Exception as exc:
            logger.exception("agent %s failed", key)
            self._log(key, trigger, event_id, "error", started, {"error": f"{type(exc).__name__}: {exc}"[:300]})
            return {"status": "error", "error": str(exc)}

    def on_event(self, payload: dict) -> None:
        """Event-store listener: hand the event to every enabled, matching agent (async)."""
        for key, agent in list(self._agents.items()):
            config = self._configs.get(key, {})
            if not config.get("enabled") or "event" not in agent.triggers:
                continue
            if (payload.get("event_metadata") or {}).get("agent", {}).get(key):
                continue  # already handled; keeps agents idempotent
            types = config.get("event_types") or []
            if types and payload.get("type") not in types:
                continue
            floor = _SEVERITY_RANK.get(config.get("min_severity", "info"), 0)
            if _SEVERITY_RANK.get(payload.get("severity", "info"), 0) < floor:
                continue
            self._pool.submit(self._execute, key, "event", payload)

    def run_now(self, key: str, trigger: str = "on_demand", payload: Optional[dict] = None) -> dict:
        if key not in self._agents:
            raise KeyError(key)
        if trigger == "on_demand" and "on_demand" not in self._agents[key].triggers \
                and "schedule" not in self._agents[key].triggers:
            return {"status": "skipped", "reason": "this agent does not run on demand"}
        return self._execute(key, trigger, None, payload)

    def runs(self, key: Optional[str] = None, limit: int = 50) -> list[AgentRun]:
        with Session(get_engine()) as session:
            stmt = select(AgentRun)
            if key:
                stmt = stmt.where(AgentRun.agent_key == key)
            return list(session.exec(stmt.order_by(AgentRun.started_at.desc(), AgentRun.id.desc()).limit(limit)).all())


agent_runner = AgentRunner()
_discover()
