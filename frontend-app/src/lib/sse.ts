export interface SseEvent { event: string; data: unknown }

/** Parses one "event: x\ndata: {...}" block of a server-sent-events stream; null for comments/blank/garbled blocks. */
export function parseSseBlock(block: string): SseEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  if (!data.length) return null;
  try { return { event, data: JSON.parse(data.join("\n")) }; } catch { return null; }
}

/** Reads a fetch() response body as server-sent events, calling onEvent for each complete one. */
export async function readSse(response: Response, onEvent: (e: SseEvent) => void): Promise<void> {
  if (!response.body) throw new Error("This browser cannot stream responses.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const parsed = parseSseBlock(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      if (parsed) onEvent(parsed);
    }
    if (done) break;
  }
  const tail = parseSseBlock(buffer);
  if (tail) onEvent(tail);
}
