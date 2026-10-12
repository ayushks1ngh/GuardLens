import type { Field, Values } from "../types";

export interface AgentStatus { state: string; message?: string; runs_last_hour?: number }
export interface AgentInfo {
  key: string; label: string; description: string; triggers: string[]; requires_vlm: boolean;
  fields: Field[]; config: Values; status: AgentStatus;
}
export interface AgentRunRow {
  id: number; agent_key: string; trigger: string; event_id: number | null; status: string;
  started_at: string; duration_ms: number; detail: Record<string, unknown> | null;
}
export interface ProviderInfo { name: string; label: string; model: string; local: boolean; configured: boolean; paused: boolean }
export interface AiStatus {
  available: boolean; providers: ProviderInfo[];
  budget: { per_minute: number; used_last_minute: number; per_day: number; used_today: number; per_camera_hour: number };
}

/** One plain sentence for the card's status line. */
export function statusLine(status: AgentStatus | undefined, enabled: boolean): string {
  if (!status || status.state === "unknown") return "Status unknown.";
  if (!enabled || status.state === "off") return "Off";
  if (status.state === "unavailable") {
    const why = (status.message ?? "").replace(/^on, but waiting:\s*/i, "").replace(/\.$/, "");
    return `On, but waiting: ${why || "something it needs is missing"}`;
  }
  const n = status.runs_last_hour;
  return typeof n === "number" ? `Active (${n} run${n === 1 ? "" : "s"} in the last hour)` : "Active";
}

export const canRunNow = (triggers: string[]) => triggers.includes("on_demand") || triggers.includes("schedule");

/** Readable result of POST /api/agents/{key}/run. */
export function runResultText(res: { status?: string; reason?: string; error?: string; result?: Record<string, unknown> }): string {
  switch (res.status) {
    case "ok": {
      const r = res.result ?? {};
      if (typeof r.date === "string") {
        const n = Array.isArray(r.citations) ? r.citations.length : 0;
        const how = r.ai ? "written by AI" : "built without AI (AI was not available)";
        return `Briefing for ${r.date} is ready, ${how}, linking ${n} alert${n === 1 ? "" : "s"}.`;
      }
      return "Finished successfully.";
    }
    case "skipped": return res.reason ? `Nothing to do: ${res.reason}.` : "Nothing to do right now.";
    case "unavailable": return `Could not run: ${res.reason || "the AI service is not available"}.`;
    case "budget": return "Not run: this agent has used its hourly limit. Try again later or raise the limit in Settings.";
    case "error": return "It ran into a problem. Details are in recent activity.";
    default: return "Done.";
  }
}

const STATUS_WORDS: Record<string, string> = {
  ok: "Worked", skipped: "Nothing to do", budget: "Hit its hourly limit", unavailable: "AI not available", error: "Problem",
};
export const runStatusWord = (s: string) => STATUS_WORDS[s] ?? s;

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** Short human detail for an activity row. */
export function runDetailText(run: Pick<AgentRunRow, "status" | "trigger" | "event_id" | "detail">): string {
  const d = run.detail ?? {};
  const parts: string[] = [];
  if (run.event_id != null) parts.push(`Alert #${run.event_id}`);
  else if (run.trigger === "on_demand") parts.push("Run by you");
  else if (run.trigger === "schedule") parts.push("Scheduled");
  if (typeof d.reason === "string") parts.push(d.reason);
  if (typeof d.error === "string") parts.push("a problem occurred");
  if (typeof d.threat === "number") parts.push(["harmless", "worth a look", "needs attention"][d.threat] ?? "");
  if (typeof d.repeat_of === "number") parts.push(`repeat of #${d.repeat_of}`);
  if (typeof d.provider === "string") parts.push(`via ${d.provider}`);
  return parts.filter(Boolean).join(" · ");
}

export const PROVIDER_ENV: Record<string, string> = {
  nvidia: "GUARDLENS_NVIDIA_API_KEY", gemini: "GUARDLENS_GEMINI_API_KEY", openrouter: "GUARDLENS_OPENROUTER_API_KEY",
  ollama: "GUARDLENS_OLLAMA_URL",
};

export function providerState(p: ProviderInfo): string {
  if (!p.configured) return p.local ? "Not set up" : "No key set";
  return p.paused ? "Paused for a moment after errors" : "Ready";
}

export function budgetText(b: AiStatus["budget"]): string {
  return `${b.used_today} of ${b.per_day} AI requests used today · ${b.used_last_minute} of ${b.per_minute} in the last minute`;
}

/** Settings shown in the form: everything except the on/off switch, which lives on the card. */
export const settingsFields = (fields: Field[]) => fields.filter((f) => f.name !== "enabled");

export function toggleCamera(ids: number[], id: number, localOnly: boolean): number[] {
  const rest = ids.filter((i) => i !== id);
  return localOnly ? [...rest, id].sort((a, b) => a - b) : rest;
}
