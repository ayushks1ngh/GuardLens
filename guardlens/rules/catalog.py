"""Broad built-in security rule catalog (Phase 4).

All behavior is composed over normalized Detection/FrameContext data. Thresholds
live in RuleConfig.params, so tuning or adding fields requires no DB migration.
"""
from __future__ import annotations

from datetime import datetime
from math import hypot
from typing import Optional

from guardlens.rules import Rule, RuleConfig, register_rule
from guardlens.types import Detection, EventDraft, FrameContext, Zone


def _zone(ctx: FrameContext, cfg: RuleConfig) -> Optional[Zone]:
    zid = cfg.zone_id or cfg.params.get("zone_id")
    if zid is None:
        return None
    return next((z for z in ctx.zones if z.id == int(zid)), None)


def _inside(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon for normalized coordinates."""
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y):
            cross = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < cross:
                inside = not inside
        j = i
    return inside


def _matching(ctx: FrameContext, cfg: RuleConfig, defaults: set[str]) -> list[Detection]:
    classes = set(cfg.params.get("classes", defaults))
    min_conf = float(cfg.params.get("min_confidence", 0.0))
    zone = _zone(ctx, cfg)
    return [
        d for d in ctx.detections
        if d.class_name in classes
        and d.confidence >= min_conf
        and (zone is None or _inside(d.center(), zone.polygon))
    ]


def _draft(key: str, cfg: RuleConfig, matched: list[Detection], **metadata) -> EventDraft:
    return EventDraft(
        type=key,
        severity=cfg.severity,
        metadata={
            "count": len(matched),
            "classes": sorted({d.class_name for d in matched}),
            "track_ids": [d.track_id for d in matched if d.track_id is not None],
            # Normalized boxes (up to 5) so evidence crops can be indexed/searched later.
            "boxes": [{"class": d.class_name, "bbox": [round(float(v), 4) for v in d.bbox]} for d in matched[:5]],
            **metadata,
        },
    )


@register_rule
class ZoneIntrusionRule(Rule):
    key = "zone_intrusion"
    param_schema = {"classes": {"type": "list[str]", "default": ["person"], "label": "Objects to watch", "help": "Alert when one of these enters the zone."}}

    def evaluate(self, ctx, cfg):
        matched = _matching(ctx, cfg, {"person"})
        return _draft(self.key, cfg, matched, zone_id=cfg.zone_id) if matched else None


@register_rule
class LoiteringRule(Rule):
    key = "loitering"
    param_schema = {"seconds": {"type": "float", "default": 10, "min": 1, "max": 600, "step": 1, "label": "Stay time", "help": "Alert when someone stays in the zone this long."}, "classes": {"type": "list[str]", "default": ["person"], "label": "Objects to watch", "help": "Which kinds of objects this rule watches for."}}

    def __init__(self):
        self._first_seen: dict[tuple, float] = {}

    def evaluate(self, ctx, cfg):
        matched = _matching(ctx, cfg, {"person"})
        active = set()
        threshold = float(cfg.params.get("seconds", 10))
        for d in matched:
            if d.track_id is None:
                continue
            key = (ctx.camera_id, cfg.name, d.track_id)
            active.add(key)
            first = self._first_seen.setdefault(key, ctx.timestamp)
            if ctx.timestamp - first >= threshold:
                return _draft(self.key, cfg, [d], dwell_seconds=round(ctx.timestamp - first, 2), zone_id=cfg.zone_id)
        prefix = (ctx.camera_id, cfg.name)
        for key in list(self._first_seen):
            if key[:2] == prefix and key not in active:
                del self._first_seen[key]
        return None


@register_rule
class LineCrossingRule(Rule):
    key = "line_crossing"
    param_schema = {"line": {"type": "list[point]", "default": [[0.5, 0], [0.5, 1]], "label": "Counting line", "help": "Draw the line people cross to be counted in or out."}, "classes": {"type": "list[str]", "default": ["person"], "label": "Objects to watch", "help": "Which kinds of objects this rule watches for."}}

    def __init__(self):
        self._side: dict[tuple, float] = {}
        self._counts: dict[tuple, dict[str, int]] = {}

    @staticmethod
    def _line_side(point, a, b):
        return (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])

    def evaluate(self, ctx, cfg):
        line = cfg.params.get("line", [[0.5, 0], [0.5, 1]])
        if len(line) != 2:
            return None
        for d in _matching(ctx, cfg, {"person"}):
            if d.track_id is None:
                continue
            key = (ctx.camera_id, cfg.name, d.track_id)
            side = self._line_side(d.center(), line[0], line[1])
            previous = self._side.get(key)
            self._side[key] = side
            if previous is not None and previous * side < 0:
                direction = "in" if previous < side else "out"
                counter = self._counts.setdefault((ctx.camera_id, cfg.name), {"in": 0, "out": 0})
                counter[direction] += 1
                return _draft(self.key, cfg, [d], direction=direction, counters=dict(counter))
        return None


@register_rule
class CrowdRule(Rule):
    key = "crowd"
    param_schema = {"threshold": {"type": "int", "default": 5, "min": 1, "max": 200, "label": "Crowd size", "help": "Alert when at least this many are in view."}, "classes": {"type": "list[str]", "default": ["person"], "label": "Objects to watch", "help": "Which kinds of objects this rule watches for."}}

    def evaluate(self, ctx, cfg):
        matched = _matching(ctx, cfg, {"person"})
        return _draft(self.key, cfg, matched, threshold=int(cfg.params.get("threshold", 5))) if len(matched) >= int(cfg.params.get("threshold", 5)) else None


class _PresenceRule(Rule):
    defaults: set[str] = set()

    def evaluate(self, ctx, cfg):
        matched = _matching(ctx, cfg, self.defaults)
        return _draft(self.key, cfg, matched, zone_id=cfg.zone_id) if matched else None


@register_rule
class AnimalRule(_PresenceRule):
    key = "animal"
    defaults = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
    param_schema = {"classes": {"type": "list[str]", "default": sorted(defaults), "label": "Objects to watch", "help": "Which kinds of objects this rule watches for."}}


@register_rule
class VehicleRule(_PresenceRule):
    key = "vehicle"
    defaults = {"bicycle", "car", "motorcycle", "bus", "train", "truck", "boat"}
    param_schema = {"classes": {"type": "list[str]", "default": sorted(defaults), "label": "Objects to watch", "help": "Which kinds of objects this rule watches for."}}


@register_rule
class AfterHoursRule(_PresenceRule):
    key = "after_hours"
    defaults = {"person", "car", "motorcycle", "bus", "truck"}
    param_schema = {"start": {"type": "HH:MM", "default": "22:00", "label": "Quiet hours start"}, "end": {"type": "HH:MM", "default": "06:00", "label": "Quiet hours end"}, "classes": {"type": "list[str]", "default": sorted(defaults), "label": "Objects to watch", "help": "Alert when any of these appear during quiet hours."}}

    def evaluate(self, ctx, cfg):
        current = datetime.fromtimestamp(ctx.timestamp).strftime("%H:%M")
        start, end = cfg.params.get("start", "22:00"), cfg.params.get("end", "06:00")
        in_window = current >= start or current < end if start > end else start <= current < end
        return super().evaluate(ctx, cfg) if in_window else None


class _StationaryRule(Rule):
    defaults = {"backpack", "handbag", "suitcase", "bottle", "chair", "box"}

    def __init__(self):
        self._origin: dict[tuple, tuple[float, tuple[float, float]]] = {}

    def _eligible(self, detection, ctx, cfg) -> bool:
        return True

    def evaluate(self, ctx, cfg):
        seconds = float(cfg.params.get("seconds", 20))
        tolerance = float(cfg.params.get("movement_tolerance", 0.03))
        for d in _matching(ctx, cfg, self.defaults):
            if d.track_id is None or not self._eligible(d, ctx, cfg):
                continue
            key = (ctx.camera_id, cfg.name, d.track_id)
            started, origin = self._origin.setdefault(key, (ctx.timestamp, d.center()))
            if hypot(d.center()[0] - origin[0], d.center()[1] - origin[1]) > tolerance:
                self._origin[key] = (ctx.timestamp, d.center())
                continue
            if ctx.timestamp - started >= seconds:
                return _draft(self.key, cfg, [d], stationary_seconds=round(ctx.timestamp - started, 2))
        return None


@register_rule
class AbandonedObjectRule(_StationaryRule):
    key = "abandoned_object"
    param_schema = {
        "seconds": {"type": "float", "default": 20, "min": 1, "max": 3600, "label": "Left-alone time", "help": "Alert when an item stays still with nobody near it this long."},
        "movement_tolerance": {"type": "float", "default": 0.03, "min": 0, "max": 0.5, "step": 0.01, "label": "Movement allowed", "help": "How far (fraction of the picture) it may shift and still count as still."},
        "person_clearance": {"type": "float", "default": 0.15, "min": 0, "max": 1, "step": 0.01, "label": "Owner distance", "help": "A person closer than this counts as its owner."},
        "classes": {"type": "list[str]", "default": sorted(_StationaryRule.defaults), "label": "Objects to watch"},
    }

    def _eligible(self, detection, ctx, cfg):
        clearance = float(cfg.params.get("person_clearance", 0.15))
        center = detection.center()
        return not any(
            other.class_name == "person"
            and hypot(center[0] - other.center()[0], center[1] - other.center()[1]) < clearance
            for other in ctx.detections
        )


@register_rule
class PackageRule(_StationaryRule):
    key = "package"
    defaults = {"backpack", "handbag", "suitcase", "box"}
    param_schema = {
        "seconds": {"type": "float", "default": 10, "min": 1, "max": 3600, "label": "Left time", "help": "Alert when an item stays at the spot this long."},
        "movement_tolerance": {"type": "float", "default": 0.03, "min": 0, "max": 0.5, "step": 0.01, "label": "Movement allowed"},
        "spot": {"type": "point", "default": [0.5, 0.5], "label": "Drop-off spot", "help": "Where packages are left, for example the door."},
        "spot_radius": {"type": "float", "default": 0.2, "min": 0.01, "max": 1, "step": 0.01, "label": "Spot size"},
        "classes": {"type": "list[str]", "default": sorted(defaults), "label": "Objects to watch"},
    }

    def _eligible(self, detection, ctx, cfg):
        spot = cfg.params.get("spot")
        if spot is None:
            return True
        radius = float(cfg.params.get("spot_radius", 0.2))
        center = detection.center()
        return hypot(center[0] - float(spot[0]), center[1] - float(spot[1])) <= radius


@register_rule
class FallRule(Rule):
    key = "fall"
    param_schema = {"seconds": {"type": "float", "default": 2, "min": 0.5, "max": 120, "label": "Down time", "help": "Alert when a person stays lying down this long."}, "aspect_ratio": {"type": "float", "default": 1.2, "min": 0.5, "max": 4, "step": 0.1, "label": "Lying-down sensitivity", "help": "How much wider than tall a person must look to count as lying down."}}

    def __init__(self):
        self._horizontal_since: dict[tuple, float] = {}

    def evaluate(self, ctx, cfg):
        threshold = float(cfg.params.get("seconds", 2))
        ratio = float(cfg.params.get("aspect_ratio", 1.2))
        for d in _matching(ctx, cfg, {"person"}):
            x1, y1, x2, y2 = d.bbox
            horizontal = (x2 - x1) / max(y2 - y1, 1e-6) >= ratio
            key = (ctx.camera_id, cfg.name, d.track_id)
            if not horizontal:
                self._horizontal_since.pop(key, None)
                continue
            since = self._horizontal_since.setdefault(key, ctx.timestamp)
            if ctx.timestamp - since >= threshold:
                return _draft(self.key, cfg, [d], horizontal_seconds=round(ctx.timestamp - since, 2))
        return None
