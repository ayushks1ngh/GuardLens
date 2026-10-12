import type { Camera, Field, PluginType, RuleRow, Values, ZoneRow } from "../types";

export interface Proposal {
  type: string; name: string; camera_id: number | null; zone_id: number | null;
  severity: RuleRow["severity"]; cooldown_seconds: number; params: Values;
  explanation?: string; problems?: string[];
}
export interface Preview {
  supported: boolean; hours: number; samples_checked?: number; would_fire?: number; examples?: string[]; note?: string;
}
export interface ProposalSummary {
  typeLabel: string; where: string; severity: string; wait: string; settings: { label: string; text: string }[];
}

const SEVERITY_WORDS: Record<string, string> = { info: "Info (low)", warning: "Warning (medium)", critical: "Critical (high)" };

export function describeWait(seconds: number): string {
  if (seconds <= 0) return "No pause between alerts";
  if (seconds < 60) return `${Math.round(seconds)} seconds`;
  const minutes = seconds / 60;
  return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)} minute${minutes === 1 ? "" : "s"}`;
}

/** One setting value in words people use, never raw JSON. */
export function formatFieldValue(field: Field | undefined, value: unknown): string {
  if (value === undefined || value === null || value === "") return "Not set";
  if (field?.type === "boolean") return value ? "On" : "Off";
  if (field?.type === "enum") return field.enum?.find((c) => String(c.value) === String(value))?.label ?? String(value);
  if (Array.isArray(value)) {
    if (field?.type === "points") return value.length ? `${value.length} points drawn` : "Not set";
    return value.length ? value.join(", ") : "None";
  }
  if (typeof value === "object") return "Customised";
  return field?.unit ? `${value} ${field.unit}` : String(value);
}

export function summarizeProposal(p: Proposal, types: PluginType[], cameras: Camera[], zones: ZoneRow[]): ProposalSummary {
  const plugin = types.find((t) => t.key === p.type);
  const camera = p.camera_id === null ? "All cameras" : cameras.find((c) => c.id === p.camera_id)?.name ?? "A camera that is no longer listed";
  const zone = p.zone_id === null || p.zone_id === undefined ? null : zones.find((z) => z.id === p.zone_id)?.name ?? "a drawn area";
  const settings = Object.entries(p.params ?? {}).map(([name, value]) => {
    const field = plugin?.fields.find((f) => f.name === name);
    return { label: field?.label ?? name.replace(/_/g, " "), text: formatFieldValue(field, value) };
  });
  return {
    typeLabel: plugin?.label ?? p.type,
    where: zone ? `${camera}, in the area “${zone}”` : camera,
    severity: SEVERITY_WORDS[p.severity] ?? p.severity,
    wait: describeWait(p.cooldown_seconds),
    settings,
  };
}

export function describePreview(pv: Preview, formatTime: (iso: string) => string = (iso) => new Date(iso).toLocaleString()): string {
  if (!pv.supported) return pv.note ?? "A preview is not available for this kind of rule.";
  if (!pv.samples_checked) return pv.note ?? "There is no recorded activity in this period yet, so there is nothing to preview.";
  const hours = Math.round(pv.hours);
  const n = pv.would_fire ?? 0;
  let text = n === 0 ? `Over the last ${hours} hours this would not have alerted at all.`
    : `Over the last ${hours} hours this would have alerted ${n} time${n === 1 ? "" : "s"}.`;
  if (pv.examples?.length) text += ` For example: ${pv.examples.map(formatTime).join("; ")}.`;
  return text;
}

/** Friendly wording for the statuses the rule helper can return. */
export function friendlyRuleError(status: number, message: string): { text: string; helperOff: boolean } {
  switch (status) {
    case 503: return { text: "The AI helper isn’t available right now. Check that an AI provider is set up, or create the rule by hand.", helperOff: false };
    case 429: return { text: "The AI helper has reached its hourly limit. Please try again later.", helperOff: false };
    case 409: return { text: "The rule helper is turned off. Turn it on in Agents to use plain-words rules.", helperOff: true };
    case 422: return { text: message || "That couldn’t be turned into a rule. Try describing it differently.", helperOff: false };
    default: return { text: message || "Something went wrong. Please try again.", helperOff: false };
  }
}

export function proposalToRuleBody(p: Proposal) {
  return { type: p.type, name: p.name, camera_id: p.camera_id, zone_id: p.zone_id ?? null, severity: p.severity, cooldown_seconds: p.cooldown_seconds, params: p.params ?? {} };
}
export const hasProblems = (p: Proposal) => (p.problems?.length ?? 0) > 0;
