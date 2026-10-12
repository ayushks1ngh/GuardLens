"""Offline evaluation of triage quality against labelled history.

Each row is ``{"label": "real"|"false_alarm", "threat": 0|1|2|None, "false_alarm": "low|medium|high"}``.
The headline numbers mirror docs/12 §2.4: how many false alarms the AI would have flagged as
safe to ignore, and — the one that matters — how many *real* alerts it would have flagged
that way by mistake. Suppression stays off until the missed-real rate is near zero.
"""
from __future__ import annotations


def would_suppress(row: dict) -> bool:
    return row.get("threat") == 0 and row.get("false_alarm") == "high"


def evaluate_triage(rows: list[dict]) -> dict:
    real = [r for r in rows if r["label"] == "real"]
    false = [r for r in rows if r["label"] == "false_alarm"]
    caught = sum(would_suppress(r) for r in false)
    missed = sum(would_suppress(r) for r in real)
    unparsed = sum(r.get("threat") is None for r in rows)
    return {
        "events": len(rows), "real": len(real), "false_alarms": len(false),
        "false_alarm_reduction": round(caught / len(false), 3) if false else None,
        "missed_real_rate": round(missed / len(real), 3) if real else None,
        "unparsed_rate": round(unparsed / len(rows), 3) if rows else None,
        "safe_to_enable_suppression": bool(real) and missed / len(real) <= 0.01 and len(real) >= 50,
    }
