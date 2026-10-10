"""ObjectClassRule — alert when configured object classes are present.

This fixes the original's bug (ADR-011 / overview issue #1): it alerts only on
**real model classes** (e.g. COCO "person", "car", "dog") rather than a hardcoded
word list of classes the model can never output. The classes to watch are passed
as JSON ``params`` — no schema migration to add or change them.
"""
from __future__ import annotations

from typing import Optional

from guardlens.rules import Rule, RuleConfig, register_rule
from guardlens.types import EventDraft, FrameContext


@register_rule
class ObjectClassRule(Rule):
    key = "object_class"
    param_schema = {
        "classes": {"type": "list[str]", "help": "model class names to alert on, e.g. ['person']"},
        "min_confidence": {"type": "float", "default": 0.0},
        "min_count": {"type": "int", "default": 1},
    }

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig) -> Optional[EventDraft]:
        watch = set(cfg.params.get("classes", []))
        if not watch:
            return None
        min_conf = float(cfg.params.get("min_confidence", 0.0))
        min_count = int(cfg.params.get("min_count", 1))

        matched = [
            d for d in ctx.detections
            if d.class_name in watch and d.confidence >= min_conf
        ]
        if len(matched) < min_count:
            return None

        return EventDraft(
            type=self.key,
            severity=cfg.severity,
            metadata={
                "classes": sorted({d.class_name for d in matched}),
                "count": len(matched),
                "track_ids": [d.track_id for d in matched if d.track_id is not None],
            },
            snapshot=ctx.frame,
        )
