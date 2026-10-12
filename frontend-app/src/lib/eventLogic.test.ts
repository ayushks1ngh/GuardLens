import { describe, expect, it } from "vitest";
import { NO_FILTERS, buildEventQuery, isNewCritical, matchesFilters, mergeLiveEvent, readAgentNotes, parseServerTime } from "./eventLogic";
import type { EventRow } from "../types";

const NOW = Date.parse("2026-10-13T12:00:00Z");
const ev = (over: Partial<EventRow> = {}): EventRow => ({
  id: 1, type: "intrusion", severity: "critical", status: "new", camera_id: 2, created_at: "2026-10-13T11:59:50", ...over,
});

describe("buildEventQuery", () => {
  it("omits empty filters and always pages", () => {
    expect(buildEventQuery(NO_FILTERS, { nowMs: NOW })).toBe("limit=25&offset=0");
  });
  it("maps chip state to query parameters", () => {
    const q = new URLSearchParams(buildEventQuery({ camera: 3, type: "loitering", severity: "critical", status: "new", range: "1h" }, { nowMs: NOW, limit: 10, offset: 20 }));
    expect(q.get("camera_id")).toBe("3");
    expect(q.get("type")).toBe("loitering");
    expect(q.get("severity")).toBe("critical");
    expect(q.get("status")).toBe("new");
    expect(q.get("from")).toBe("2026-10-13T11:00:00.000Z");
    expect(q.get("limit")).toBe("10");
    expect(q.get("offset")).toBe("20");
  });
  it("keeps camera id 0 as a real filter", () => {
    expect(buildEventQuery({ ...NO_FILTERS, camera: 0 }, { nowMs: NOW })).toContain("camera_id=0");
  });
});

describe("matchesFilters", () => {
  it("applies every active chip", () => {
    expect(matchesFilters(ev(), { ...NO_FILTERS, severity: "critical", camera: 2 }, NOW)).toBe(true);
    expect(matchesFilters(ev(), { ...NO_FILTERS, camera: 9 }, NOW)).toBe(false);
    expect(matchesFilters(ev({ created_at: "2026-10-10T00:00:00Z" }), { ...NO_FILTERS, range: "24h" }, NOW)).toBe(false);
  });
});

describe("isNewCritical (alarm gating)", () => {
  it("sounds only for fresh, unseen critical events", () => {
    expect(isNewCritical(ev(), new Set(), NOW)).toBe(true);
    expect(isNewCritical(ev({ severity: "warning" }), new Set(), NOW)).toBe(false);
    expect(isNewCritical(ev(), new Set([1]), NOW)).toBe(false);
  });
  it("ignores old critical events replayed on reconnect", () => {
    expect(isNewCritical(ev({ created_at: "2026-10-13T09:00:00Z" }), new Set(), NOW)).toBe(false);
  });
  it("treats timestamps without a zone as UTC", () => {
    expect(parseServerTime("2026-10-13T12:00:00")).toBe(NOW);
  });
});

describe("mergeLiveEvent", () => {
  it("prepends new matching events, updates known ones, skips non-matching", () => {
    const list = [ev({ id: 1 })];
    expect(mergeLiveEvent(list, ev({ id: 2 }), true).map((e) => e.id)).toEqual([2, 1]);
    expect(mergeLiveEvent(list, ev({ id: 2 }), false)).toEqual(list);
    expect(mergeLiveEvent(list, ev({ id: 1, status: "resolved" }), false)[0].status).toBe("resolved");
  });
});

describe("readAgentNotes", () => {
  it("renders nothing for missing or odd data", () => {
    expect(readAgentNotes(undefined)).toEqual([]);
    expect(readAgentNotes({ agent: "x" })).toEqual([]);
    expect(readAgentNotes({ agent: { a: 5 } })).toEqual([]);
  });
  it("reads a single block or keyed blocks", () => {
    expect(readAgentNotes({ agent: { title: "T", summary: "S", threat: "high" } })).toEqual([{ title: "T", summary: "S", threat: "high" }]);
    expect(readAgentNotes({ agent: { triage: { summary: "S" }, other: { title: "O" } } })).toHaveLength(2);
  });
});
