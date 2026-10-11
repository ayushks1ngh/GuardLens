"""Rule that asks a VLM about the scene when a trigger class is present.

Detection stays fast: the rule only submits the frame to the background VLM watcher,
which calls the cloud model off the analysis loop and raises a `vlm_alert` event if the
answer matches configured keywords (e.g. knife, scissors, blade, weapon).
"""
from __future__ import annotations

from guardlens.rules import Rule, RuleConfig, register_rule
from guardlens.types import FrameContext
from guardlens.vlm import vlm_watcher


@register_rule
class VlmWatchRule(Rule):
    key = "vlm_watch"
    param_schema = {
        "trigger_classes": {"type": "array", "default": ["person", "motion"]},
        "prompt": {"type": "string", "default": "Look carefully. Is anyone holding or is there any sharp or dangerous object (knife, scissors, blade, weapon)? Answer yes or no and name the object."},
        "keywords": {"type": "array", "default": ["knife", "scissors", "blade", "weapon", "sharp"]},
        "cooldown_seconds": {"type": "number", "default": 20, "min": 5, "max": 600},
    }

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig):
        if ctx.frame is None or not vlm_watcher.available:
            return None
        triggers = set(cfg.params.get("trigger_classes", ["person", "motion"]))
        if not any(d.class_name in triggers for d in ctx.detections):
            return None
        vlm_watcher.submit(
            ctx.camera_id,
            ctx.frame,
            str(cfg.params.get("prompt", "")),
            list(cfg.params.get("keywords", [])),
            cfg.severity,
            float(cfg.params.get("cooldown_seconds", 20)),
        )
        return None  # the watcher raises the event asynchronously on a hit
