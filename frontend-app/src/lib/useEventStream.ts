import { useEffect, useRef } from "react";
import { API_BASE } from "../api";
import type { EventRow } from "../types";

/** Subscribes to /api/events/stream (SSE; the browser reconnects and resumes automatically). */
export function useEventStream(onEvent: (event: EventRow) => void): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/api/events/stream`);
    source.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as EventRow;
        if (data && typeof data.id === "number") handler.current(data);
      } catch { /* ignore malformed frames */ }
    };
    return () => source.close();
  }, []);
}
