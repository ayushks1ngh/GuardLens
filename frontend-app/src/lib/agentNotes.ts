import { readAgentNotes } from "./eventLogic";

export type ThreatTone = "ok" | "warn" | "crit";
export interface ThreatPill { label: string; tone: ThreatTone }

/** Triage verdict 0/1/2 in plain words. Unknown values show no pill rather than a guess. */
export function threatPill(threat: unknown): ThreatPill | null {
  if (threat === 0) return { label: "Harmless", tone: "ok" };
  if (threat === 1) return { label: "Worth a look", tone: "warn" };
  if (threat === 2) return { label: "Needs attention", tone: "crit" };
  return null;
}

export interface AgentView {
  title?: string; summary?: string; pill?: ThreatPill | null; suggestion?: string; repeatOf?: number; legacyThreat?: string;
}

const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : undefined);
const obj = (v: unknown): Record<string, unknown> | null => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null);

/** Builds what the Events screen shows from event_metadata.agent (triage, unusual-activity, anything else). */
export function readAgentViews(meta: unknown): AgentView[] {
  const agent = obj(obj(meta)?.agent);
  if (!agent) return [];
  const views: AgentView[] = [];
  const triage = obj(agent.event_triage);
  if (triage) {
    const suggested = str(triage.suggested_severity);
    views.push({
      title: str(triage.title), summary: str(triage.summary), pill: threatPill(triage.threat),
      suggestion: suggested ? `AI suggests treating this as ${suggested}` : undefined,
    });
  }
  const unusual = obj(agent.unusual_activity);
  if (unusual) {
    const rep = unusual.repeat_of;
    const repeatOf = typeof rep === "number" ? rep : undefined;
    // Triage already supplies title/summary when present; avoid repeating the same words.
    views.push({ title: triage ? undefined : str(unusual.title), summary: triage ? undefined : str(unusual.summary), repeatOf });
  }
  const { event_triage: _t, unusual_activity: _u, ...rest } = agent;
  void _t; void _u;
  for (const n of readAgentNotes({ agent: rest })) views.push({ title: n.title, summary: n.summary, legacyThreat: n.threat });
  return views.filter((v) => v.title || v.summary || v.pill || v.suggestion || v.repeatOf !== undefined || v.legacyThreat);
}
