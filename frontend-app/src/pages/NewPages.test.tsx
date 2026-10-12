import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentsPage } from "./AgentsPage";
import { AssistantPage } from "./AssistantPage";

type Call = { url: string; method: string; body?: string };
let calls: Call[] = [];
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

beforeEach(() => {
  calls = [];
  sessionStorage.clear();
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    if (url === "/api/agents") return ok([{
      key: "daily_briefing", label: "Daily briefing", description: "Writes a summary.", triggers: ["schedule", "on_demand"], requires_vlm: true,
      fields: [{ name: "enabled", type: "boolean", label: "Turned on", help: "", required: false }, { name: "daily_at", type: "time", label: "Run every day at", help: "", required: false }],
      config: { enabled: false, daily_at: "23:30" }, status: { state: "off", message: "Turned off." },
    }]);
    if (url === "/api/agents/ai") return ok({ available: false, providers: [{ name: "nvidia", label: "NVIDIA", model: "m", local: false, configured: false, paused: false }],
      budget: { per_minute: 20, used_last_minute: 0, per_day: 2000, used_today: 3, per_camera_hour: 60 } });
    if (url.startsWith("/api/agents/runs")) return ok([{ id: 1, agent_key: "daily_briefing", trigger: "on_demand", event_id: null, status: "ok", started_at: "2026-01-01T00:00:00", duration_ms: 1200, detail: {} }]);
    if (url === "/api/cameras") return ok([{ id: 1, name: "Door", enabled: true }]);
    if (url === "/api/privacy") return ok({ local_only_cameras: init?.method === "PUT" ? JSON.parse(init.body as string).local_only_cameras : [] });
    if (url === "/api/agents/daily_briefing") return ok({ config: { enabled: true, daily_at: "23:30" }, status: { state: "active", runs_last_hour: 0 } });
    if (url === "/api/agents/daily_briefing/run") return ok({ status: "unavailable", reason: "no key" });
    if (url === "/api/assistant/chat") return ok({ session_id: "s9", answer: "Nothing much.", citations: [12], frame_url: "/history/f.jpg", camera: "Door", provider: "nvidia", model: "m", events_used: [] });
    return ok({});
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("AgentsPage", () => {
  it("shows AI, privacy, toggles an agent and runs it", async () => {
    render(<AgentsPage meta={null} />);
    await screen.findByText("Daily briefing");
    expect(await screen.findByText(/3 of 2000 AI requests/)).toBeTruthy();
    expect(screen.getAllByText(/GUARDLENS_NVIDIA_API_KEY/).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByRole("switch", { name: /Keep Door video/ }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/privacy" && c.method === "PUT" && c.body === '{"local_only_cameras":[1]}')).toBe(true));
    fireEvent.click(screen.getByRole("switch", { name: "Turn on Daily briefing" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT" && c.body === '{"config":{"enabled":true}}')).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.queryByText("Turned on")).toBeNull();
    expect(screen.getByLabelText("Run every day at")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await screen.findByText("Could not run: no key.");
  });
});

describe("AssistantPage", () => {
  it("sends a question and shows answer, frame and citation chip", async () => {
    render(<AssistantPage meta={null} />);
    fireEvent.click(screen.getByRole("button", { name: "What happened today?" }));
    await screen.findByText("Nothing much.");
    expect(screen.getByRole("button", { name: "Alert #12" })).toBeTruthy();
    expect(screen.getByAltText(/picture the AI looked at/i)).toBeTruthy();
    const chat = calls.find((c) => c.url === "/api/assistant/chat")!;
    expect(JSON.parse(chat.body!)).toEqual({ question: "What happened today?", camera_id: null });
    expect(sessionStorage.getItem("guardlens.assistantSession")).toBe("s9");
    fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/assistant/sessions/s9")).toBe(true));
    expect(screen.queryByText("Nothing much.")).toBeNull();
  });
});
