import { describe, expect, it } from "vitest";
import { parseSseBlock, readSse, type SseEvent } from "./sse";

const streamOf = (chunks: string[]) => new Response(new ReadableStream({
  start(controller) { const enc = new TextEncoder(); chunks.forEach((c) => controller.enqueue(enc.encode(c))); controller.close(); },
}));

describe("server-sent events", () => {
  it("parses a block, ignores comments and garbage", () => {
    expect(parseSseBlock('event: delta\ndata: {"text":"hi"}')).toEqual({ event: "delta", data: { text: "hi" } });
    expect(parseSseBlock('data: {"a":1}')).toEqual({ event: "message", data: { a: 1 } });
    expect(parseSseBlock(": keep-alive")).toBeNull();
    expect(parseSseBlock("event: x\ndata: {broken")).toBeNull();
  });
  it("reassembles events split across network chunks, including multi-byte text", async () => {
    const got: SseEvent[] = [];
    await readSse(streamOf(['event: delta\nda', 'ta: {"text":"ca', 'fé ☕"}\n\nevent: done\ndata: {"ok":true}\n\n']), (e) => got.push(e));
    expect(got).toEqual([{ event: "delta", data: { text: "café ☕" } }, { event: "done", data: { ok: true } }]);
  });
  it("delivers a final event even without the trailing blank line", async () => {
    const got: SseEvent[] = [];
    await readSse(streamOf(['event: done\ndata: {"n":1}']), (e) => got.push(e));
    expect(got).toHaveLength(1);
  });
});
