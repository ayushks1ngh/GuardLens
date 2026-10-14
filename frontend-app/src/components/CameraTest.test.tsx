import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CameraTest } from "./CameraTest";

afterEach(() => vi.unstubAllGlobals());

const bad = {
  ok: false, summary: "Not working yet — see the steps below.",
  checks: [{ name: "Camera is switched on", ok: true, detail: "Yes" }, { name: "Can reach 10.0.0.9:8080", ok: false, detail: "no answer (timed out)" }],
  advice: ["Check that the phone app is running.", "Phones change address when they reconnect."],
};

describe("CameraTest", () => {
  it("runs on open, lists passed and failed checks and what to do, and can run again", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, json: async () => bad }));
    vi.stubGlobal("fetch", fetchMock);
    render(<CameraTest cameraId={3} cameraName="Phone" />);
    expect(await screen.findByText(/Not working yet/)).toBeTruthy();
    expect(screen.getByText(/Can reach 10.0.0.9:8080 — no answer \(timed out\)/)).toBeTruthy();
    expect(screen.getAllByText(/Failed:/)).toHaveLength(1);
    expect(screen.getByText("Phones change address when they reconnect.")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/cameras/3/test", expect.objectContaining({ method: "POST" }));
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    await screen.findByText(/Not working yet/);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("shows a readable error when the server cannot be asked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, statusText: "x", json: async () => ({ detail: "camera not found" }) })));
    render(<CameraTest cameraId={9} cameraName="Gone" />);
    expect((await screen.findByRole("alert")).textContent).toBe("camera not found");
  });
});
