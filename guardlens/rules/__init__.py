"""Rule plugins + registry + rule engine (see docs/07-extensibility.md §3).

A ``Rule`` inspects a ``FrameContext`` and may emit an ``EventDraft``. Rules are
registered via ``@register_rule`` and configured at runtime with a ``RuleConfig``
whose free-form ``params`` ride in a JSON column — so new rule types need **no
schema migration** (ADR-007/ADR-011). ``GET /api/rules/types`` can expose each
rule's ``param_schema`` so the dashboard renders a config form without hardcoding
rule types.

The ``RuleEngine`` applies per-(rule, key) **cooldown** so a firing rule does not
flood events.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from guardlens.schema import normalize_schema
from guardlens.types import EventDraft, FrameContext

logger = logging.getLogger("guardlens.rules")


@dataclass
class RuleConfig:
    """Runtime configuration for one rule instance."""

    type: str
    severity: str = "warning"
    name: str = ""
    camera_id: Optional[int] = None
    zone_id: Optional[int] = None
    cooldown_seconds: float = 30.0
    params: dict[str, Any] = field(default_factory=dict)


class Rule:
    """Base interface every rule plugin implements."""

    key: str = ""
    param_schema: dict = {}

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig) -> Optional[EventDraft]:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, type[Rule]] = {}


def register_rule(cls: type[Rule]) -> type[Rule]:
    key = getattr(cls, "key", "") or ""
    if not key:
        raise ValueError(f"Rule {cls.__name__} must define a non-empty 'key'")
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        logger.warning("rule key %r already registered; overriding", key)
    _REGISTRY[key] = cls
    return cls


def get_rule_class(key: str) -> Optional[type[Rule]]:
    return _REGISTRY.get(key)


def available_rules() -> list[str]:
    return sorted(_REGISTRY.keys())


def rule_types() -> list[dict]:
    """Expose registered rule types + their param schemas (drives the UI form)."""
    return [
        {
            "key": k,
            "label": getattr(c, "label", "") or k.replace("_", " ").capitalize(),
            "description": (c.__doc__ or "").strip().splitlines()[0] if c.__doc__ else "",
            "param_schema": getattr(c, "param_schema", {}),
            "fields": normalize_schema(getattr(c, "param_schema", {})),
        }
        for k, c in sorted(_REGISTRY.items())
    ]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class RuleEngine:
    """Evaluates enabled rules against a FrameContext, enforcing cooldown."""

    def __init__(self, configs: Optional[list[RuleConfig]] = None):
        self._configs: list[RuleConfig] = configs or []
        self._rules: dict[str, Rule] = {}
        self._last_fired: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set_configs(self, configs: list[RuleConfig]) -> None:
        with self._lock:
            self._configs = list(configs)

    def _get_rule(self, key: str) -> Optional[Rule]:
        rule = self._rules.get(key)
        if rule is None:
            cls = _REGISTRY.get(key)
            if cls is None:
                logger.warning("no rule registered for key %r", key)
                return None
            rule = cls()
            self._rules[key] = rule
        return rule

    def evaluate(self, ctx: FrameContext, now: Optional[float] = None) -> list[EventDraft]:
        # Rules and cooldown state are shared by all camera workers. Serialize
        # evaluation so stateful rule plugins remain safe as the catalog grows.
        with self._lock:
            return self._evaluate_locked(ctx, now)

    def _evaluate_locked(
        self, ctx: FrameContext, now: Optional[float] = None
    ) -> list[EventDraft]:
        now = time.time() if now is None else now
        drafts: list[EventDraft] = []
        for cfg in self._configs:
            if cfg.camera_id is not None and cfg.camera_id != ctx.camera_id:
                continue
            rule = self._get_rule(cfg.type)
            if rule is None:
                continue
            try:
                draft = rule.evaluate(ctx, cfg)
            except Exception:  # a broken rule must never crash the pipeline
                logger.exception("rule %r raised during evaluate", cfg.type)
                continue
            if draft is None:
                continue
            if draft.snapshot is None:
                draft.snapshot = ctx.frame
            # Cooldown keyed by (camera, rule type, rule name).
            cd_key = (ctx.camera_id, cfg.type, cfg.name)
            last = self._last_fired.get(cd_key, 0.0)
            if now - last < cfg.cooldown_seconds:
                continue
            self._last_fired[cd_key] = now
            drafts.append(draft)
        return drafts


# Discover plugin modules automatically. A new ``*.py`` rule is imported
# without editing this registry; private/base modules are ignored.
def _discover_plugins() -> None:
    import importlib
    import pkgutil
    from pathlib import Path

    package = __name__
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if module.name.startswith("_") or module.name in {"base"}:
            continue
        importlib.import_module(f"{package}.{module.name}")


_discover_plugins()
