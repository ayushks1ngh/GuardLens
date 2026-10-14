import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LivePage } from "./LivePage";

beforeEach(() => {
  vi.stubGlobal("EventSource", class { close() {} addEventListener() {} } as unknown as typeof EventSource);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })));
});
afterEach(() => vi.unstubAllGlobals());

describe("Live page", () => {
  it("has the Ask GuardLens chat on the right, beside the cameras", async () => {
    render(<LivePage meta={null} />);
    const chat = await screen.findByLabelText("Ask GuardLens", { selector: "aside" });
    expect(chat.textContent).toMatch(/Ask in your own words/);
    expect(chat.closest(".live-split")).toBeTruthy();
    expect(document.querySelector(".live-split > .live-grid")).toBeTruthy();
  });
});
