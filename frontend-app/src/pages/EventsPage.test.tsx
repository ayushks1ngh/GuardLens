import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventsPage } from "./EventsPage";

const nowIso = () => new Date().toISOString();
let handler: ((e: MessageEvent) => void) | null = null;
class FakeSource {
  set onmessage(fn: (e: MessageEvent) => void) { handler = fn; }
  close() { handler = null; }
}

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("EventSource", FakeSource);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const body = url.startsWith("/api/events?") ? { items: [], total: 0, limit: 25, offset: 0 } : [{ id: 1, name: "Door", enabled: true }];
    return { ok: true, status: 200, json: async () => body };
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("EventsPage", () => {
  it("shows a visual alert for a new critical event and none for a warning", async () => {
    render(<EventsPage meta={null} />);
    await waitFor(() => expect(handler).not.toBeNull());
    handler!({ data: JSON.stringify({ id: 5, type: "intrusion", severity: "warning", status: "new", camera_id: 1, created_at: nowIso() }) } as MessageEvent);
    await screen.findByText("Intrusion", { selector: "strong" });
    expect(screen.queryByRole("alert")).toBeNull();
    handler!({ data: JSON.stringify({ id: 6, type: "weapon", severity: "critical", status: "new", camera_id: 1, created_at: nowIso() }) } as MessageEvent);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Critical alert: Weapon on Camera 1|Critical alert: Weapon on Door/);
  });

  it("remembers the mute choice", async () => {
    render(<EventsPage meta={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Alarm sound: on" }));
    expect(localStorage.getItem("guardlens.alarmMuted")).toBe("1");
    expect(screen.getByRole("button", { name: "Alarm sound: off" })).toBeTruthy();
  });
});
