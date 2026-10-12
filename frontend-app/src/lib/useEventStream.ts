import { useEffect, useRef } from "react";
import { API_BASE } from "../api";
import type { EventRow } from "../types";

/** Subscribes to /api/events/stream (SSE; the browser reconnects and resumes automatically). */
export function useEventStream(onEvent: (event: EventRow) => void, onUpdate?: (event: EventRow) => void): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;
  const updater = useRef(onUpdate);
  updater.current = onUpdate;
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/api/events/stream`);
    source.onmessage = (message) => {
      try {
        const data = JSON.parse(message.data) as EventRow;
        if (data && typeof data.id === "number") handler.current(data);
      } catch { /* ignore malformed frames */ }
    };
    // Named event: an existing event was enriched (e.g. by an AI agent). Never a new alert.
    if (typeof source.addEventListener === "function") {
      source.addEventListener("event_updated", (message) => {
        try {
          const data = JSON.parse((message as MessageEvent).data) as EventRow;
          if (data && typeof data.id === "number") updater.current?.(data);
        } catch { /* ignore malformed frames */ }
      });
    }
    return () => source.close();
  }, []);
}
