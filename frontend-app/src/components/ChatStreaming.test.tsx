import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "./ChatPanel";
import { chatReducer, initialChat, type ChatResponse } from "../lib/chat";

const final: ChatResponse = { session_id: "s1", answer: "Two people walk by.", citations: [], frame_url: null, camera: "Door", provider: "nvidia", model: "m", events_used: [] };

describe("chat reducer streaming", () => {
  it("builds one assistant message from start, words and done", () => {
    let s = chatReducer(initialChat, { type: "ask", text: "who?" });
    s = chatReducer(s, { type: "stream_start", sessionId: "s1", frameUrl: "/history/a.jpg", camera: "Door" });
    s = chatReducer(s, { type: "stream_delta", text: "Two " });
    s = chatReducer(s, { type: "stream_delta", text: "people" });
    expect(s.messages.at(-1)).toMatchObject({ role: "assistant", text: "Two people", streaming: true, frameUrl: "/history/a.jpg" });
    expect(s.waiting).toBe(true);
    s = chatReducer(s, { type: "stream_done", response: final });
    expect(s.messages).toHaveLength(2);
    expect(s.messages.at(-1)).toMatchObject({ text: "Two people walk by.", streaming: false, provider: "nvidia" });
    expect(s.waiting).toBe(false);
  });
  it("an error replaces an empty half-written answer", () => {
    let s = chatReducer(initialChat, { type: "ask", text: "x" });
    s = chatReducer(s, { type: "stream_start", sessionId: "s", frameUrl: null, camera: null });
    s = chatReducer(s, { type: "fail", text: "boom" });
    expect(s.messages.map((m) => m.role)).toEqual(["user", "error"]);
  });
});

describe("ChatPanel streaming", () => {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const send = (text: string) => act(async () => { controller.enqueue(enc.encode(text)); await new Promise((r) => setTimeout(r, 20)); });

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/cameras") return { ok: true, status: 200, json: async () => [] };
      if (url === "/api/assistant/chat/stream") {
        return new Response(new ReadableStream<Uint8Array>({ start(c) { controller = c; } }), { status: 200, headers: { "content-type": "text/event-stream" } });
      }
      return { ok: true, status: 200, json: async () => ({}) };
    }));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows words as they arrive, then the final cleaned answer", async () => {
    render(<ChatPanel />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "who is there?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(controller).toBeDefined());
    await send('event: meta\ndata: {"session_id":"s1","frame_url":null,"camera":"Door"}\n\n');
    await send('event: delta\ndata: {"text":"Two "}\n\n');
    expect(await screen.findByText(/Two/)).toBeTruthy();
    expect(screen.queryByText(/Two people walk by/)).toBeNull();  // not finished yet
    await send('event: delta\ndata: {"text":"people [E99999]"}\n\n');
    await send(`event: done\ndata: ${JSON.stringify(final)}\n\n`);
    await act(async () => controller.close());
    expect(await screen.findByText("Two people walk by.")).toBeTruthy();
    expect(screen.queryByText(/E99999/)).toBeNull();
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true);  // empty draft again
  });

  it("shows a plain-language error when the stream ends early", async () => {
    render(<ChatPanel />);
    fireEvent.change(screen.getByLabelText("Your question"), { target: { value: "hi" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(controller).toBeDefined());
    await send('event: meta\ndata: {"session_id":"s1","frame_url":null,"camera":null}\n\n');
    await act(async () => controller.close());
    expect((await screen.findByRole("alert")).textContent).toMatch(/Something went wrong/);
  });
});
