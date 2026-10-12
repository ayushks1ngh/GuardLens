import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ZonesPage } from "./ZonesPage";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ZonesPage", () => {
  it("saves a drawn polygon for the chosen camera", async () => {
    const calls: { url: string; method?: string; body?: unknown }[] = [];
    URL.createObjectURL = () => "blob:x"; URL.revokeObjectURL = () => {};
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      if (url.startsWith("/stream/")) return new Response(new Uint8Array([0xff, 0xd8, 1, 0xff, 0xd9]));
      if (url === "/api/cameras") return Response.json([{ id: 7, name: "Door", enabled: true }]);
      if (url === "/api/cameras/7/zones" && !init?.method) return Response.json([]);
      return Response.json({ id: 1 }, { status: 201 });
    }));
    render(<ZonesPage meta={null} />);
    fireEvent.click(await screen.findByText("Draw a new zone", {}, { timeout: 5000 }));
    fireEvent.change(screen.getByLabelText("Zone name"), { target: { value: "Porch" } });
    const surface = screen.getByRole("img", { name: "Click to place points" });
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect);
    for (const [x, y] of [[10, 10], [90, 10], [50, 80]]) fireEvent.click(surface, { clientX: x, clientY: y });
    fireEvent.click(screen.getByText("Save zone"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true), { timeout: 5000 });
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.url).toBe("/api/cameras/7/zones");
    expect(post.body).toEqual({ name: "Porch", polygon: [[0.1, 0.1], [0.9, 0.1], [0.5, 0.8]] });
  });
});
