import type { ReportRow, Values } from "../types";

export interface CameraSummary { id: string; peakPeople: number; peakVehicles: number; known: string[]; unknownFaces: number; samples: number }
export interface Highlight { id: number; type: string; severity: string; cameraId: number; time: string }
export interface ReportView {
  date: string; eventCount: number; headline: string;
  byType: Record<string, number>; bySeverity: Record<string, number>;
  cameras: CameraSummary[]; highlights: Highlight[]; paragraphs: string[];
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : 0);
const counts = (v: unknown): Record<string, number> =>
  v && typeof v === "object" ? Object.fromEntries(Object.entries(v as Values).map(([k, n]) => [k, num(n)])) : {};

/** "person_detected" -> "Person detected". */
export function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Make the backend report structure safe and ready to render; tolerant of other generators' output. */
export function toReportView(report: ReportRow): ReportView {
  const c = report.content ?? {};
  const cameras = Object.entries((c.cameras as Record<string, Values> | undefined) ?? {}).map(([id, v]) => ({
    id, peakPeople: num(v.peak_people), peakVehicles: num(v.peak_vehicles),
    known: Array.isArray(v.known) ? v.known.map(String) : [], unknownFaces: num(v.unknown_faces), samples: num(v.samples),
  }));
  const highlights = (Array.isArray(c.highlights) ? (c.highlights as Values[]) : []).map((h) => ({
    id: num(h.id), type: String(h.type ?? ""), severity: String(h.severity ?? "info"),
    cameraId: num(h.camera_id), time: String(h.created_at ?? ""),
  }));
  const eventCount = num(c.event_count);
  const paragraphs = (report.text ?? "").split(/\n+/).map((l) => l.trim()).filter(Boolean);
  return {
    date: String(c.date ?? report.date), eventCount,
    headline: eventCount === 0 ? "A quiet day: no security events." : `${eventCount} security event${eventCount === 1 ? "" : "s"} recorded.`,
    byType: counts(c.events_by_type), bySeverity: counts(c.events_by_severity), cameras, highlights, paragraphs,
  };
}

/** One readable sentence for an activity sample. */
export function describeActivity(summary: Values): string {
  const parts: string[] = [];
  const people = num(summary.people);
  if (people) parts.push(`${people} ${people === 1 ? "person" : "people"}`);
  const v = summary.vehicles;
  const vehicles = typeof v === "object" && v ? Object.values(v as Values).reduce<number>((a, b) => a + num(b), 0) : num(v);
  if (vehicles) parts.push(`${vehicles} vehicle${vehicles === 1 ? "" : "s"}`);
  const known = Array.isArray(summary.known) ? summary.known.map(String) : [];
  if (known.length) parts.push(`recognised ${known.join(", ")}`);
  const unknown = num(summary.unknown_faces);
  if (unknown) parts.push(`${unknown} unknown face${unknown === 1 ? "" : "s"}`);
  return parts.length ? parts.join(", ") : "Nothing notable";
}

export function todayIso(now: Date = new Date()): string { return now.toISOString().slice(0, 10); }
