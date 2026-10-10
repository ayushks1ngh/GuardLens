"""Deterministic CPU-only daily security briefing generator."""
from __future__ import annotations

from collections import Counter, defaultdict

from guardlens.reporting import ReportGenerator, register_generator


@register_generator
class StructuredReportGenerator(ReportGenerator):
    key = "structured"

    def generate(self, date, activity, events):
        event_types = Counter(e.type for e in events)
        severities = Counter(e.severity for e in events)
        per_camera = defaultdict(lambda: {"samples": 0, "peak_people": 0, "peak_vehicles": 0, "known": set(), "unknown_faces": 0})
        for row in activity:
            current = per_camera[row.camera_id]
            current["samples"] += 1
            current["peak_people"] = max(current["peak_people"], int(row.summary.get("people", 0)))
            vehicles = row.summary.get("vehicles", 0)
            if isinstance(vehicles, dict): vehicles = sum(vehicles.values())
            current["peak_vehicles"] = max(current["peak_vehicles"], int(vehicles))
            current["known"].update(row.summary.get("known", []))
            current["unknown_faces"] += int(row.summary.get("unknown_faces", 0))

        serial_cameras = {
            str(cid): {**values, "known": sorted(values["known"])}
            for cid, values in per_camera.items()
        }
        content = {
            "date": date.isoformat(), "event_count": len(events),
            "events_by_type": dict(event_types), "events_by_severity": dict(severities),
            "cameras": serial_cameras,
            "highlights": [
                {"id": e.id, "type": e.type, "severity": e.severity, "camera_id": e.camera_id,
                 "created_at": e.created_at.isoformat(), "snapshot_path": e.snapshot_path}
                for e in events if e.severity in {"warning", "critical"}
            ],
        }
        lines = [f"GuardLens daily briefing — {date.isoformat()}", f"Recorded {len(events)} security event(s) and {len(activity)} activity sample(s)."]
        if event_types: lines.append("Events: " + ", ".join(f"{k} {v}" for k, v in sorted(event_types.items())) + ".")
        else: lines.append("No security events were recorded.")
        for cid, values in sorted(serial_cameras.items()):
            known = ", ".join(values["known"]) or "none"
            lines.append(f"Camera {cid}: peak people {values['peak_people']}, peak vehicles {values['peak_vehicles']}, known visitors {known}, unknown-face observations {values['unknown_faces']}.")
        if severities.get("critical"): lines.append(f"Attention: {severities['critical']} critical event(s) require review.")
        return {"content": content, "text": "\n".join(lines)}
