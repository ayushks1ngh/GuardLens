export interface SearchHit {
  event_id: number; score: number; source: "picture" | "text" | "both" | string;
  type: string; severity?: string; camera: string; camera_id: number; created_at: string;
  snapshot_path?: string | null; title?: string | null;
}
export interface SearchStatus {
  enabled: boolean; model?: string; indexed_events: number; events_with_pictures: number;
  loading: boolean; reindexing: boolean; queued?: number; error: string | null;
}

export const EXAMPLE_QUERIES = ["person in a red jacket", "white van yesterday", "someone at the door last 3 hours"];

export const OFF_EXPLANATION =
  "Footage search is off. Turning it on downloads a ~350 MB picture-understanding model the first time and indexes your existing alerts on this computer. Nothing is sent to the cloud.";

export function matchNote(source: string): string {
  if (source === "both") return "matched both";
  if (source === "text") return "matched the description";
  return "matched the picture";
}

export function hitTitle(hit: Pick<SearchHit, "title" | "type">): string {
  if (hit.title && hit.title.trim()) return hit.title;
  const t = hit.type.replace(/_/g, " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
}

export function isBusy(s: SearchStatus | null): boolean { return !!s && s.enabled && (s.loading || s.reindexing); }

export function progressText(s: SearchStatus): string {
  return `Indexed ${s.indexed_events} of ${s.events_with_pictures} alerts`;
}

export function searchErrorText(status: number | undefined, message?: string): string {
  if (status === 409) return "Footage search is turned off. Turn it on above to search your alerts.";
  if (status === 503) return "The picture-understanding model isn't available right now. It may still be downloading, so try again in a minute.";
  if (status === 422) return "Type at least two characters to search.";
  return message ? `Search failed: ${message}` : "Search failed. Check that GuardLens is running and try again.";
}
