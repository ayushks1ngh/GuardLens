import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DataPage, backupText, retentionText } from "./DataPage";

const status = {
  backups: [{ name: "guardlens-auto-20261014-033000.db", kind: "auto", size_mb: 2.4, created_at: "2026-10-14T03:30:00+00:00" }],
  storage: { database_mb: 2.4, pictures_mb: 1.1, clips_mb: 0, backups_mb: 5 },
  backup_policy: { enabled: true, daily_at: "03:30", keep_days: 14 },
  retention_policy: { enabled: true, events_days: 90 },
};
let calls: { url: string; method: string }[] = [];
beforeEach(() => {
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET" });
    const body = url === "/api/data/backups" && init?.method === "POST" ? { name: "guardlens-manual-1.db" }
      : url === "/api/data/cleanup" ? { events_removed: 3, backups_removed: 0 } : status;
    return { ok: true, status: 200, json: async () => body };
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("DataPage", () => {
  it("says the policies in plain words", () => {
    expect(retentionText({ enabled: true, events_days: 90 })).toMatch(/older than 90 days.*critical are always kept/);
    expect(retentionText({ enabled: false, events_days: 90 })).toMatch(/kept forever/);
    expect(backupText({ enabled: true, daily_at: "03:30", keep_days: 14 })).toMatch(/every day at 03:30.*14 days/);
  });
  it("lists backups, makes one, and cleans up", async () => {
    render(<DataPage meta={null} />);
    await screen.findByText(/Automatic · 2.4 MB/);
    fireEvent.click(screen.getByRole("button", { name: "Back up now" }));
    await screen.findByText(/Backup saved: guardlens-manual-1.db/);
    fireEvent.click(screen.getByRole("button", { name: "Clean up now" }));
    await screen.findByText("Removed 3 old events.");
    expect(calls.filter((c) => c.method === "POST").map((c) => c.url)).toEqual(["/api/data/backups", "/api/data/cleanup"]);
    fireEvent.click(screen.getByRole("button", { name: /Delete backup from/ }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});
