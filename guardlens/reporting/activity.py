"""Periodic activity summaries persisted alongside the analysis pipeline."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlmodel import Session

from guardlens.events import ActivityLog, get_engine


class ActivitySampler:
    def __init__(self):
        self.interval = 10.0
        self.retention_days = 30
        self._last: dict[int, float] = {}
        self._lock = threading.Lock()

    def configure(self, interval: float, retention_days: int):
        self.interval = interval; self.retention_days = retention_days

    def sample(self, ctx) -> bool:
        with self._lock:
            last = self._last.get(ctx.camera_id, 0)
            if ctx.timestamp - last < self.interval: return False
            self._last[ctx.camera_id] = ctx.timestamp
        counts = {}
        known = set(); unknown_faces = 0
        for d in ctx.detections:
            counts[d.class_name] = counts.get(d.class_name, 0) + 1
            if d.class_name == "face":
                if d.attributes.get("person_id") is None: unknown_faces += 1
                elif d.attributes.get("name"): known.add(d.attributes["name"])
        vehicle_classes = {"bicycle", "car", "motorcycle", "bus", "train", "truck", "boat"}
        animal_classes = {"bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe"}
        summary = {
            "people": counts.get("person", 0),
            "vehicles": {k: v for k, v in counts.items() if k in vehicle_classes},
            "animals": {k: v for k, v in counts.items() if k in animal_classes},
            "known": sorted(known), "unknown_faces": unknown_faces,
            "classes": counts,
            "zones_active": [z.id for z in ctx.zones if any(_inside(d.center(), z.polygon) for d in ctx.detections)],
        }
        stamp = datetime.fromtimestamp(ctx.timestamp, timezone.utc)
        with Session(get_engine()) as session:
            session.add(ActivityLog(camera_id=ctx.camera_id, timestamp=stamp, summary=summary)); session.commit()
        return True


def _inside(point, polygon):
    x, y = point; inside = False; j = len(polygon)-1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi: inside = not inside
        j=i
    return inside


activity_sampler = ActivitySampler()
