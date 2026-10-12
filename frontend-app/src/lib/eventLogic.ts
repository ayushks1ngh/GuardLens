import type { EventRow } from "../types";

export type TimeRange = "any" | "1h" | "24h" | "7d";

export interface EventFilters {
  camera: number | null;
  type: string | null;
  severity: string | null;
  status: string | null;
  range: TimeRange;
}

export const NO_FILTERS: EventFilters = { camera: null, type: null, severity: null, status: null, range: "any" };

export const RANGE_LABELS: Record<TimeRange, string> = {
  any: "Any time", "1h": "Last hour", "24h": "Last 24 hours", "7d": "Last 7 days",
};
const RANGE_MS: Record<Exclude<TimeRange, "any">, number> = { "1h": 3_600_000, "24h": 86_400_000, "7d": 604_800_000 };

/** Server timestamps may lack a timezone marker; they are always UTC. */
export function parseServerTime(value: string): number {
  const hasZone = /(Z|[+-]\d\d:?\d\d)$/.test(value);
  return Date.parse(hasZone ? value : `${value}Z`);
}

export function rangeStart(range: TimeRange, nowMs: number): number | null {
  return range === "any" ? null : nowMs - RANGE_MS[range];
}

/** Turns filter-chip state into the /api/events query string (empty filters are omitted). */
export function buildEventQuery(filters: EventFilters, opts: { limit?: number; offset?: number; nowMs?: number } = {}): string {
  const q = new URLSearchParams();
  if (filters.camera !== null) q.set("camera_id", String(filters.camera));
  if (filters.type) q.set("type", filters.type);
  if (filters.severity) q.set("severity", filters.severity);
  if (filters.status) q.set("status", filters.status);
  const from = rangeStart(filters.range, opts.nowMs ?? Date.now());
  if (from !== null) q.set("from", new Date(from).toISOString());
  q.set("limit", String(opts.limit ?? 25));
  q.set("offset", String(opts.offset ?? 0));
  return q.toString();
}

export function matchesFilters(event: EventRow, filters: EventFilters, nowMs: number): boolean {
  if (filters.camera !== null && event.camera_id !== filters.camera) return false;
  if (filters.type && event.type !== filters.type) return false;
  if (filters.severity && event.severity !== filters.severity) return false;
  if (filters.status && event.status !== filters.status) return false;
  const from = rangeStart(filters.range, nowMs);
  return from === null || parseServerTime(event.created_at) >= from;
}

/** Live streams replay recent history on connect; only genuinely fresh events may sound the alarm. */
export const FRESH_WINDOW_MS = 60_000;

export function isNewCritical(event: Pick<EventRow, "id" | "severity" | "created_at">, seen: ReadonlySet<number>, nowMs: number): boolean {
  if (event.severity !== "critical" || seen.has(event.id)) return false;
  const created = parseServerTime(event.created_at);
  return Number.isFinite(created) && nowMs - created <= FRESH_WINDOW_MS;
}

export function humanizeType(type: string): string {
  const text = type.replace(/[_.-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : type;
}

export function timeAgo(value: string, nowMs: number = Date.now()): string {
  const then = parseServerTime(value);
  if (!Number.isFinite(then)) return "";
  const secs = Math.max(0, Math.round((nowMs - then) / 1000));
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)} h ago`;
  return new Date(then).toLocaleString();
}

export interface AgentNote { title?: string; summary?: string; threat?: string }

/** Defensive read of event_metadata.agent: agents may add one block, or several keyed blocks. */
export function readAgentNotes(meta: unknown): AgentNote[] {
  if (!meta || typeof meta !== "object") return [];
  const agent = (meta as Record<string, unknown>).agent;
  if (!agent || typeof agent !== "object") return [];
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : undefined);
  const pick = (o: unknown): AgentNote | null => {
    if (!o || typeof o !== "object") return null;
    const r = o as Record<string, unknown>;
    const note = { title: str(r.title), summary: str(r.summary), threat: str(r.threat ?? r.threat_level) };
    return note.title || note.summary || note.threat ? note : null;
  };
  const direct = pick(agent);
  if (direct) return [direct];
  return Object.values(agent as Record<string, unknown>).map(pick).filter((n): n is AgentNote => n !== null);
}

/** Merge a live event into the visible list (newest first), updating in place if already shown. */
export function mergeLiveEvent(list: EventRow[], event: EventRow, show: boolean): EventRow[] {
  const index = list.findIndex((e) => e.id === event.id);
  if (index >= 0) return list.map((e, i) => (i === index ? { ...e, ...event } : e));
  return show ? [event, ...list] : list;
}
