import { describe, expect, it } from "vitest";
import { readAgentViews, threatPill } from "./agentNotes";
import { budgetText, runDetailText, runResultText, settingsFields, statusLine, toggleCamera } from "./agentsLogic";
import { chatErrorText, chatReducer, initialChat, type ChatResponse } from "./chat";
import { applyEventUpdate } from "./eventLogic";
import type { EventRow } from "../types";

const ev = (o: Partial<EventRow>): EventRow => ({ id: 1, type: "intrusion", severity: "warning", status: "new", camera_id: 1, created_at: "2026-01-01T00:00:00", ...o });

describe("agent wording", () => {
  it("describes status", () => {
    expect(statusLine({ state: "off" }, false)).toBe("Off");
    expect(statusLine({ state: "active", runs_last_hour: 1 }, true)).toBe("Active (1 run in the last hour)");
    expect(statusLine({ state: "unavailable", message: "On, but waiting: needs an AI provider." }, true)).toBe("On, but waiting: needs an AI provider");
  });
  it("describes run results without raw JSON", () => {
    expect(runResultText({ status: "ok", result: { date: "2026-01-01", ai: true, citations: [1, 2] } })).toContain("linking 2 alerts");
    expect(runResultText({ status: "unavailable", reason: "no key" })).toBe("Could not run: no key.");
    expect(runResultText({ status: "budget" })).toMatch(/hourly limit/);
    expect(runResultText({ status: "error", error: "Boom" })).not.toContain("Boom");
  });
  it("describes activity rows", () => {
    expect(runDetailText({ status: "ok", trigger: "event", event_id: 7, detail: { threat: 2, provider: "nvidia" } })).toBe("Alert #7 · needs attention · via nvidia");
  });
  it("misc helpers", () => {
    expect(budgetText({ per_minute: 20, used_last_minute: 1, per_day: 2000, used_today: 5, per_camera_hour: 60 })).toContain("5 of 2000");
    expect(settingsFields([{ name: "enabled" }, { name: "x" }] as never).map((f) => f.name)).toEqual(["x"]);
    expect(toggleCamera([1], 2, true)).toEqual([1, 2]);
    expect(toggleCamera([1, 2], 1, false)).toEqual([2]);
  });
});

describe("triage display", () => {
  it("maps threat to pill", () => {
    expect(threatPill(0)?.label).toBe("Harmless");
    expect(threatPill(1)?.label).toBe("Worth a look");
    expect(threatPill(2)?.label).toBe("Needs attention");
    expect(threatPill(null)).toBeNull();
  });
  it("reads triage and repeat info", () => {
    const views = readAgentViews({ agent: {
      event_triage: { title: "Delivery", summary: "Courier at door", threat: 0, suggested_severity: "info" },
      unusual_activity: { repeat_of: 4, title: "Repeat alert" },
    } });
    expect(views[0]).toMatchObject({ title: "Delivery", suggestion: "AI suggests treating this as info" });
    expect(views[0].pill?.label).toBe("Harmless");
    expect(views[1].repeatOf).toBe(4);
    expect(readAgentViews({})).toEqual([]);
  });
});

describe("event_updated", () => {
  it("updates in place and never inserts", () => {
    const list = [ev({ id: 1 }), ev({ id: 2 })];
    const out = applyEventUpdate(list, { ...ev({ id: 2, severity: "critical" }), event_metadata: { agent: {} }, kind: "event.updated" } as EventRow);
    expect(out).toHaveLength(2);
    expect(out[1].severity).toBe("critical");
    expect(out[1]).not.toHaveProperty("kind");
    expect(applyEventUpdate(list, ev({ id: 9 }))).toEqual(list);
  });
});

describe("chat reducer", () => {
  const resp: ChatResponse = { session_id: "s1", answer: "Two people.", citations: [3], frame_url: "/history/a.jpg", camera: "Door", provider: "nvidia", model: "m", events_used: [] };
  it("flows ask, answer, fail, reset", () => {
    let s = chatReducer(initialChat, { type: "ask", text: "hi" });
    expect(s.waiting).toBe(true);
    s = chatReducer(s, { type: "answer", response: resp });
    expect(s).toMatchObject({ waiting: false, sessionId: "s1" });
    expect(s.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(s.messages[1].citations).toEqual([3]);
    s = chatReducer(s, { type: "fail", text: "x" });
    expect(s.messages[2].role).toBe("error");
    expect(chatReducer(s, { type: "reset" })).toEqual(initialChat);
  });
  it("friendly errors", () => {
    expect(chatErrorText(503)).toMatch(/No AI/);
    expect(chatErrorText(429)).toMatch(/busy/);
    expect(chatErrorText(403)).toMatch(/this device/);
    expect(chatErrorText(502)).toMatch(/try again/);
  });
});
