import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthForm } from "./AuthScreens";

afterEach(() => vi.unstubAllGlobals());

function fill(code: boolean) {
  fireEvent.change(document.getElementById("auth-user")!, { target: { value: "owner" } });
  fireEvent.change(document.getElementById("auth-pass")!, { target: { value: "correct-horse-99" } });
  if (code) fireEvent.change(document.getElementById("auth-code")!, { target: { value: " ab12-cd34 " } });
  fireEvent.click(screen.getByRole("button", { name: "Create account" }));
}

describe("first-run setup code", () => {
  it("is asked for only when the server requires it, and is sent with the account", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 201, json: async () => ({ username: "owner" }) }));
    vi.stubGlobal("fetch", fetchMock);
    const done = vi.fn();
    render(<AuthForm mode="setup" onDone={done} setupCodeRequired />);
    expect(screen.getByLabelText("Setup code")).toBeTruthy();
    fill(true);
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string))
      .toEqual({ username: "owner", password: "correct-horse-99", setup_code: "ab12-cd34" });
  });
  it("is not shown (or sent) on the computer that runs GuardLens", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 201, json: async () => ({ username: "owner" }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthForm mode="setup" onDone={() => undefined} setupCodeRequired={false} />);
    expect(screen.queryByLabelText("Setup code")).toBeNull();
    fill(false);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(JSON.parse((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].body as string)).not.toHaveProperty("setup_code");
  });
  it("shows the server's message when the code is wrong", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 403, statusText: "", json: async () => ({ detail: "Enter the setup code shown in the terminal or log where GuardLens is running (look for “Setup code”)." }) })));
    render(<AuthForm mode="setup" onDone={() => undefined} setupCodeRequired />);
    fill(true);
    expect((await screen.findByRole("alert")).textContent).toMatch(/Enter the setup code shown in the terminal/);
  });
});
