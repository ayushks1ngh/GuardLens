"""Motion event rule; clip writing remains in the independent recorder service."""
from __future__ import annotations

from guardlens.rules import Rule, RuleConfig, register_rule
from guardlens.rules.geometry import point_in_polygon
from guardlens.types import EventDraft, FrameContext


@register_rule
class MotionRule(Rule):
    key = "motion"
    param_schema = {
        "min_confidence": {"type": "number", "default": 0.2, "min": 0, "max": 1},
        "zone_only": {"type": "boolean", "default": False},
    }

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig):
        minimum = float(cfg.params.get("min_confidence", 0.2))
        motions = [d for d in ctx.detections if d.class_name == "motion" and d.confidence >= minimum]
        if cfg.params.get("zone_only") and ctx.zones:
            motions = [
                detection for detection in motions
                if any(point_in_polygon(detection.center(), zone.polygon) for zone in ctx.zones)
            ]
        if not motions:
            return None
        return EventDraft(
            type="motion",
            severity=cfg.severity,
            metadata={"regions": len(motions), "max_confidence": max(d.confidence for d in motions)},
        )
