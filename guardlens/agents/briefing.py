"""Daily briefing: a short plain-language summary of the day, linked to real alerts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from guardlens.agents import Agent, AgentContext, register_agent


@register_agent
class DailyBriefingAgent(Agent):
    """Writes the end-of-day briefing (falls back to the plain report without AI)."""
    key = "daily_briefing"
    label = "Daily briefing"
    description = "Every evening, writes a short plain-language summary of the day with links to the alerts it mentions."
    triggers = ("schedule", "on_demand")

    def run(self, ctx: AgentContext, trigger: str, payload: Optional[dict]) -> dict:
        from datetime import date as date_type
        from guardlens.api.reporting import _generate
        day = date_type.fromisoformat(payload["date"]) if payload and payload.get("date") \
            else datetime.now(timezone.utc).date()
        report = _generate(day, force=True, key="briefing")
        content = report.content or {}
        return {"date": day.isoformat(), "ai": bool(content.get("narrative")), "citations": content.get("citations", []),
                "fallback": content.get("fallback"), "provider": content.get("provider")}
