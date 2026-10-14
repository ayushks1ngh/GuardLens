import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { feedbackText } from "./AgentsPage";
import { EventsPage } from "./EventsPage";

const event = { id: 5, type: "person_detected", severity: "warning", status: "new", camera_id: 1, created_at: new Date().toISOString(), event_metadata: {} as Record<string, unknown> };
let calls: { url: string; method: string; body?: string }[] = [];

beforeEach(() => {
  calls = [];
  vi.stubGlobal("EventSource", class { close() {} addEventListener() {} } as unknown as typeof EventSource);
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    const ok = (b: unknown) => ({ ok: true, status: 200, json: async () => b });
    if (url.startsWith("/api/events?")) return ok({ items: [event], total: 1, limit: 25, offset: 0 });
    if (url === "/api/events/5/feedback") {
      const label = JSON.parse(init!.body as string).label;
      event.event_metadata = label ? { feedback: { label } } : {};
      return ok({ ...event });
    }
    if (url === "/api/cameras") return ok([{ id: 1, name: "Door", enabled: true }]);
    return ok([]);
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("judging alerts", () => {
  it("marks an alert real, switches to false alarm, and clears by pressing again", async () => {
    render(<EventsPage meta={null} />);
    const real = await screen.findByRole("button", { name: "Real alert" });
    fireEvent.click(real);
    await waitFor(() => expect(screen.getByRole("button", { name: "Real alert" }).getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(screen.getByRole("button", { name: "False alarm" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "False alarm" }).getAttribute("aria-pressed")).toBe("true"));
    fireEvent.click(screen.getByRole("button", { name: "False alarm" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "False alarm" }).getAttribute("aria-pressed")).toBe("false"));
    expect(calls.filter((c) => c.url.endsWith("/feedback")).map((c) => JSON.parse(c.body!).label)).toEqual(["real", "false_alarm", null]);
  });
  it("tells the person how far along they are, in plain words", () => {
    const base = { judged: 12, real: 8, false_alarms: 4, with_ai_notes: 10, needed_real: 50, evaluation: { safe_to_enable_suppression: false, missed_real_rate: null } };
    expect(feedbackText(base)).toMatch(/judged 12 alerts \(8 real, 4 false alarms\).*at least 50 real/);
    expect(feedbackText({ ...base, real: 60, evaluation: { safe_to_enable_suppression: false, missed_real_rate: 0.05 } })).toMatch(/hidden 5% of real alerts, so hiding stays off/);
    expect(feedbackText({ ...base, real: 60, evaluation: { safe_to_enable_suppression: true, missed_real_rate: 0 } })).toMatch(/almost no real alert/);
  });
});

describe("missing pictures", () => {
  it("shows a plain note instead of a broken image when the file is gone", async () => {
    event.event_metadata = {};
    (event as Record<string, unknown>).snapshot_path = "gone.jpg";
    render(<EventsPage meta={null} />);
    const img = await screen.findByAltText(/Snapshot of/);
    fireEvent.error(img);
    expect(await screen.findByText(/picture for this alert is no longer available/)).toBeTruthy();
    expect(screen.queryByAltText(/Snapshot of/)).toBeNull();
    delete (event as Record<string, unknown>).snapshot_path;
  });
});
