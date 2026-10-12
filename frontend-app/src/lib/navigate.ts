/** Tiny cross-page navigation: App.tsx listens for this event; no router needed. */
let pendingEventId: number | null = null;

export function requestNavigate(page: string, eventId?: number): void {
  pendingEventId = eventId ?? null;
  window.dispatchEvent(new CustomEvent("guardlens:navigate", { detail: { page, eventId } }));
}

/** The Events page calls this once on mount to learn which alert the user came to see. */
export function takePendingEventId(): number | null {
  const id = pendingEventId;
  pendingEventId = null;
  return id;
}
