"""Face policy rule: unknown and watchlist alerts."""
from __future__ import annotations

from guardlens.detectors._face_runtime import face_runtime
from guardlens.rules import Rule, register_rule
from guardlens.types import EventDraft


@register_rule
class UnknownFaceRule(Rule):
    key = "unknown_face"
    param_schema = {"policy": {"type": "enum", "label": "When to alert", "help": "Overrides the global face policy for this rule.", "enum": [
        {"value": "label_only", "label": "Never (just label faces)"},
        {"value": "alert_unknown", "label": "Unknown faces"},
        {"value": "alert_watchlist", "label": "Watchlisted people"}]}}

    def evaluate(self, ctx, cfg):
        policy = cfg.params.get("policy") or face_runtime.policy()
        if policy == "label_only":
            return None
        for detection in ctx.detections:
            if detection.class_name != "face":
                continue
            person_id = detection.attributes.get("person_id")
            watchlist = bool(detection.attributes.get("watchlist"))
            should_alert = (policy == "alert_unknown" and person_id is None) or (policy == "alert_watchlist" and watchlist)
            if should_alert:
                return EventDraft(
                    type="unknown_face" if person_id is None else "watchlist_face",
                    severity=cfg.severity,
                    person_id=person_id,
                    metadata={
                        "name": detection.attributes.get("name", "unknown"),
                        "match_score": detection.attributes.get("match_score", 0),
                        "bbox": detection.bbox,
                    },
                )
        return None
