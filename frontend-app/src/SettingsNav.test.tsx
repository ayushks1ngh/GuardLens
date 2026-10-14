import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { MAIN_PAGES, SETTINGS_PAGES } from "./pages/registry";

beforeEach(() => {
  vi.stubGlobal("EventSource", class { close() {} addEventListener() {} } as unknown as typeof EventSource);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true, status: 200,
    json: async () => (url === "/api/auth/status" ? { enabled: false, needs_setup: false, authenticated: false, username: null } : url === "/health" ? { version: "2", capabilities: {}, detectors: [] } : url === "/api/meta" ? { name: "g", version: "2", object_classes: [], capabilities: {}, plugins: { detectors: [], rules: [], notifiers: [] } } : /\/(recording|stream\/overlay)/.test(url) ? {} : []),
  })));
});
afterEach(() => vi.unstubAllGlobals());

describe("menu", () => {
  it("keeps the left menu short and puts the rest under Settings tabs", async () => {
    expect(MAIN_PAGES.map((p) => p.label)).toEqual(["Live", "Events", "Ask GuardLens", "Find footage", "Reports"]);
    expect(SETTINGS_PAGES.map((p) => p.label)).toEqual(
      ["Cameras", "Rules", "Zones", "Faces", "Notifications", "Recording", "AI helpers", "Security", "Health"]);
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("button").map((b) => b.textContent).slice(0, 6))
      .toEqual(["Live", "Events", "Ask GuardLens", "Find footage", "Reports", "Settings"]);
    expect(screen.queryByRole("tablist")).toBeNull();
    fireEvent.click(within(nav).getByRole("button", { name: "Settings" }));
    expect(screen.getAllByRole("tab")).toHaveLength(9);
    fireEvent.click(screen.getByRole("tab", { name: "Health" }));
    expect(screen.getByRole("tab", { name: "Health" }).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(within(nav).getByRole("button", { name: "Live" }));
    fireEvent.click(within(nav).getByRole("button", { name: "Settings" }));
    expect(screen.getByRole("tab", { name: "Health" }).getAttribute("aria-selected")).toBe("true"); // remembers the last tab
  });
});
