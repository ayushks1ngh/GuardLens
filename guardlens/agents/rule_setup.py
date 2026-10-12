"""Rule setup helper: drafts an alert rule from a plain-language request (never saves it)."""
from __future__ import annotations

from typing import Optional

from guardlens import rulesetup
from guardlens.agents import Agent, AgentContext, register_agent


@register_agent
class RuleSetupAgent(Agent):
    """Turns “alert me if someone is at the back door after 10pm” into a draft rule to review."""
    key = "rule_setup"
    label = "Rule setup helper"
    description = "Turns a plain-language request into a draft alert rule, shows how often it would have fired, and waits for you to confirm."
    triggers = ("on_demand",)
    requires_vlm = True
    default_enabled = True

    def run(self, ctx: AgentContext, trigger: str, payload: Optional[dict]) -> dict:
        text = str((payload or {}).get("text", "")).strip()
        if len(text) < 5:
            return {"error": "Describe what you want to watch for."}
        result = ctx.vlm.ask(None, rulesetup.build_prompt(text), system=rulesetup.SYSTEM, max_tokens=500, temperature=0.1)
        raw = rulesetup.parse_proposal(result.text)
        if raw is None:
            return {"error": "I could not turn that into a rule. Try rephrasing it.", "provider": result.provider}
        proposal = rulesetup.validate_proposal(raw)
        preview = rulesetup.dry_run(proposal) if not proposal["problems"] else None
        return {"proposal": proposal, "preview": preview, "provider": result.provider, "model": result.model}
