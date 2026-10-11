"""Rules over structured hand-gesture detections."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from guardlens.rules import Rule, RuleConfig, register_rule
from guardlens.types import EventDraft, FrameContext


def _gestures(ctx: FrameContext, minimum: float):
    return [
        detection for detection in ctx.detections
        if detection.class_name == "hand"
        and float(detection.attributes.get("confidence", detection.confidence)) >= minimum
        and detection.attributes.get("static_gesture", "unknown") != "unknown"
    ]


@register_rule
class GestureDetectedRule(Rule):
    key = "gesture_detected"
    param_schema = {
        "gestures": {"type": "array", "default": ["open_palm"]},
        "vocabulary": {"type": "string", "default": "basic_gestures"},
        "min_confidence": {"type": "number", "default": 0.7, "min": 0, "max": 1},
    }

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig):
        wanted = set(cfg.params.get("gestures", ["open_palm"]))
        vocabulary = cfg.params.get("vocabulary")
        matched = [
            item for item in _gestures(ctx, float(cfg.params.get("min_confidence", 0.7)))
            if item.attributes.get("static_gesture") in wanted
            and (not vocabulary or item.attributes.get("vocabulary") == vocabulary)
        ]
        if not matched:
            return None
        return EventDraft(type=self.key, severity=cfg.severity, metadata={
            "gestures": [item.attributes["static_gesture"] for item in matched],
            "vocabulary": matched[0].attributes.get("vocabulary"),
        })


@register_rule
class HelpGestureRule(GestureDetectedRule):
    key = "help_gesture"
    param_schema = {
        "gestures": {"type": "array", "default": ["help"]},
        "min_confidence": {"type": "number", "default": 0.8, "min": 0, "max": 1},
    }

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig):
        draft = super().evaluate(ctx, cfg)
        if draft:
            draft.type = self.key
        return draft


@register_rule
class GestureSequenceRule(Rule):
    key = "gesture_sequence"
    param_schema = {
        "sequence": {"type": "array", "default": ["H", "E", "L", "P"]},
        "window_seconds": {"type": "number", "default": 10, "min": 1, "max": 120},
        "stable_frames": {"type": "integer", "default": 3, "min": 1, "max": 30},
        "min_confidence": {"type": "number", "default": 0.75, "min": 0, "max": 1},
    }

    def __init__(self):
        self._history = defaultdict(deque)
        self._last = {}
        self._streak = defaultdict(int)

    def evaluate(self, ctx: FrameContext, cfg: RuleConfig):
        items = _gestures(ctx, float(cfg.params.get("min_confidence", 0.75)))
        if not items:
            return None
        gesture = max(items, key=lambda item: item.attributes.get("confidence", 0)).attributes["static_gesture"]
        key = (ctx.camera_id, cfg.name)
        if self._last.get(key) == gesture:
            self._streak[key] += 1
        else:
            self._last[key] = gesture; self._streak[key] = 1
        if self._streak[key] < int(cfg.params.get("stable_frames", 3)):
            return None
        history = self._history[key]; now = ctx.timestamp or time.time()
        window = float(cfg.params.get("window_seconds", 10))
        while history and now - history[0][0] > window:
            history.popleft()
        if not history or history[-1][1] != gesture:
            history.append((now, gesture))
        sequence = list(cfg.params.get("sequence", ["H", "E", "L", "P"]))
        observed = [value for _, value in history]
        if len(observed) < len(sequence) or observed[-len(sequence):] != sequence:
            return None
        history.clear()
        return EventDraft(type=self.key, severity=cfg.severity, metadata={"sequence": sequence})
