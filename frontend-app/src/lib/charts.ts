export interface Bar { label: string; value: number; pct: number }

/** Scale values to 0..100 relative to the largest (so the biggest bar fills the row). */
export function scaleBars(items: { label: string; value: number }[]): Bar[] {
  const max = Math.max(0, ...items.map((i) => i.value));
  return items.map((i) => ({ ...i, pct: max > 0 ? Math.round((i.value / max) * 1000) / 10 : 0 }));
}

/** Turn a { name: count } map into bars sorted high to low. */
export function barsFromCounts(counts: Record<string, number>, labelOf: (k: string) => string = (k) => k): Bar[] {
  return scaleBars(Object.entries(counts).map(([k, v]) => ({ label: labelOf(k), value: v })).sort((a, b) => b.value - a.value));
}

export type Range = "today" | "week" | "month";
export const RANGES: { value: Range; label: string }[] = [
  { value: "today", label: "Today, by hour" }, { value: "week", label: "Last 7 days" }, { value: "month", label: "Last 30 days" },
];

/** API query for a range. `now` is injectable for tests. */
export function rangeQuery(range: Range, now: Date = new Date()): { from: string; to: string; bucket: "hour" | "day" } {
  const dayStart = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const back = range === "today" ? 0 : range === "week" ? 6 : 29;
  const from = new Date(dayStart.getTime() - back * 86400000);
  return { from: from.toISOString(), to: now.toISOString(), bucket: range === "today" ? "hour" : "day" };
}

/** Fill gaps so quiet hours/days show as zero-height columns instead of vanishing. */
export function fillBuckets(points: { bucket: string; count: number }[], range: Range, now: Date = new Date()): Bar[] {
  const lookup = new Map(points.map((p) => [p.bucket, p.count]));
  const { from, bucket } = rangeQuery(range, now);
  const out: { label: string; value: number }[] = [];
  const start = new Date(from);
  if (bucket === "hour") {
    for (let h = 0; h <= now.getUTCHours(); h++) {
      const d = new Date(start.getTime() + h * 3600000);
      out.push({ label: `${String(h).padStart(2, "0")}:00`, value: lookup.get(d.toISOString().slice(0, 13) + ":00:00Z") ?? 0 });
    }
  } else {
    const days = range === "week" ? 7 : 30;
    for (let i = 0; i < days; i++) {
      const key = new Date(start.getTime() + i * 86400000).toISOString().slice(0, 10);
      out.push({ label: key.slice(5), value: lookup.get(key) ?? 0 });
    }
  }
  return scaleBars(out);
}
