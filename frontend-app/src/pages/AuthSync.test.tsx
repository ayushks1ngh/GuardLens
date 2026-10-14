import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

let status: Record<string, unknown>;
const ok = (body: unknown, code = 200) => ({ ok: true, status: code, json: async () => body });

beforeEach(() => {
  status = { enabled: false, needs_setup: true, authenticated: false, username: null };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/auth/status") return ok(status);
    if (url === "/api/auth/setup" && init?.method === "POST") {
      status = { enabled: true, needs_setup: false, authenticated: true, username: "admin" };
      return ok({ username: "admin" }, 201);
    }
    if (url === "/api/auth/tokens") return ok([]);
    if (url === "/api/cameras") return ok([]);
    if (url === "/api/events") return ok([]);
    return ok({});
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("creating the account from the Security page", () => {
  it("updates the app shell: the 'Login is off' banner goes away and Sign out appears", async () => {
    render(<App />);
    expect(await screen.findByText(/Login is off: anyone on your network/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Security" }));
    await screen.findByRole("heading", { name: "Create the administrator account" });
    fireEvent.change(document.getElementById("auth-user")!, { target: { value: "admin" } });
    fireEvent.change(document.getElementById("auth-pass")!, { target: { value: "correct-horse-99" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(screen.queryByText(/Login is off: anyone on your network/)).toBeNull());
    expect(screen.getByRole("button", { name: /Sign out \(admin\)/ })).toBeTruthy();
  });
});
