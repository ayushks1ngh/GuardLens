import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SearchPage } from "./SearchPage";
import { SecurityPage } from "./SecurityPage";
import { App } from "../App";
import { bearerExample, credentialProblem, screenFor, tokenUsedText } from "../lib/auth";
import { hitTitle, matchNote, progressText, searchErrorText } from "../lib/search";
import { takePendingEventId } from "../lib/navigate";

type Call = { url: string; method: string; body?: string };
let calls: Call[] = [];
let authStatus: Record<string, unknown>;
const ok = (body: unknown, status = 200) => ({ ok: true, status, json: async () => body });

beforeEach(() => {
  calls = [];
  authStatus = { enabled: true, needs_setup: false, authenticated: false, username: null };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
    if (url === "/api/search/status") return ok({ enabled: true, indexed_events: 2, events_with_pictures: 5, loading: false, reindexing: false, error: null });
    if (url === "/api/cameras") return ok([{ id: 1, name: "Door", enabled: true }]);
    if (url.startsWith("/api/search?")) return ok({ query: "van", results: [
      { event_id: 7, score: 0.4, source: "both", type: "vehicle_seen", camera: "Door", camera_id: 1, created_at: "2026-01-01T00:00:00", snapshot_path: "a.jpg", title: "White van" }] });
    if (url === "/api/auth/status") return ok(authStatus);
    if (url === "/api/auth/login") return ok({ username: "admin" });
    if (url === "/api/auth/tokens" && init?.method === "POST") return ok({ id: 3, name: "script", token: "tok_secret" }, 201);
    if (url === "/api/auth/tokens") return ok([{ id: 1, name: "ha", created_at: "2026-01-01T00:00:00", last_used_at: null }]);
    return ok({});
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("pure logic", () => {
  it("words search matches", () => {
    expect(matchNote("picture")).toBe("matched the picture");
    expect(matchNote("text")).toBe("matched the description");
    expect(matchNote("both")).toBe("matched both");
    expect(hitTitle({ title: null, type: "person_detected" })).toBe("Person detected");
    expect(progressText({ enabled: true, indexed_events: 3, events_with_pictures: 9, loading: false, reindexing: true, error: null })).toBe("Indexed 3 of 9 alerts");
    expect(searchErrorText(409)).toMatch(/turned off/);
    expect(searchErrorText(503)).toMatch(/isn't available/);
  });
  it("decides the screen from auth status", () => {
    const s = { enabled: false, needs_setup: false, authenticated: false, username: null };
    expect(screenFor(null)).toBe("loading");
    expect(screenFor({ ...s, needs_setup: true })).toBe("setup");
    expect(screenFor({ ...s, enabled: true })).toBe("login");
    expect(screenFor({ ...s, enabled: true, authenticated: true })).toBe("app");
    expect(screenFor(s)).toBe("app");
  });
  it("formats tokens and credential rules", () => {
    expect(tokenUsedText({ id: 1, name: "a", created_at: "", last_used_at: null })).toBe("Never used");
    expect(bearerExample("abc")).toBe("Authorization: Bearer abc");
    expect(credentialProblem("ab", "longenoughpw")).toMatch(/username/);
    expect(credentialProblem("admin", "short")).toMatch(/10/);
    expect(credentialProblem("admin", "longenoughpw")).toBeNull();
  });
});

describe("SearchPage", () => {
  it("searches and opens an alert", async () => {
    render(<SearchPage meta={null} />);
    fireEvent.change(await screen.findByLabelText("What are you looking for?"), { target: { value: "white van" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await screen.findByText("White van");
    expect(screen.getByText("matched both")).toBeTruthy();
    expect(calls.some((c) => c.url === "/api/search?q=white+van")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /Open alert: White van/ }));
    expect(takePendingEventId()).toBe(7);
  });
  it("offers to turn search on when off", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET", body: init?.body as string | undefined });
      if (url === "/api/search/status" || url === "/api/search/settings")
        return ok({ enabled: init?.method === "PUT", indexed_events: 0, events_with_pictures: 4, loading: false, reindexing: true, error: null });
      return ok([]);
    });
    render(<SearchPage meta={null} />);
    fireEvent.click(await screen.findByRole("button", { name: "Turn on" }));
    await screen.findByText(/Indexed 0 of 4 alerts/);
    expect(calls.some((c) => c.method === "PUT" && c.body === '{"enabled":true}')).toBe(true);
  });
});

describe("SecurityPage", () => {
  it("creates a token and shows it once", async () => {
    authStatus = { enabled: true, needs_setup: false, authenticated: true, username: "admin" };
    render(<SecurityPage meta={null} />);
    await screen.findByText("Login is on");
    await screen.findByText("ha");
    fireEvent.change(screen.getByLabelText("Token name"), { target: { value: "script" } });
    fireEvent.click(screen.getByRole("button", { name: "Create token" }));
    expect(((await screen.findByLabelText("New token")) as HTMLInputElement).value).toBe("tok_secret");
    expect(screen.getByText(/You won’t see this again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Turn login off" }));
    expect(screen.getByText(/Without login/)).toBeTruthy();
  });
});

describe("App auth gate", () => {
  it("shows login, then the app after signing in", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Sign in to GuardLens" });
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    authStatus = { enabled: true, needs_setup: false, authenticated: true, username: "admin" };
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Sign out/ })).toBeTruthy());
  });
});
