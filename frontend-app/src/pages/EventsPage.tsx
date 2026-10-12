import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, API_BASE, ApiError } from "../api";
import { isMuted, playAlarm, setMuted, unlockAudio } from "../lib/alarm";
import {
  NO_FILTERS, RANGE_LABELS, buildEventQuery, humanizeType, isNewCritical, matchesFilters, mergeLiveEvent,
  readAgentNotes, timeAgo, type EventFilters, type TimeRange,
} from "../lib/eventLogic";
import { useEventStream } from "../lib/useEventStream";
import type { CameraFull, EventPage, EventRow, Meta } from "../types";

const PAGE_SIZE = 25;
const SEVERITIES = ["critical", "warning", "info"];
const STATUSES = [{ v: "new", l: "New" }, { v: "acknowledged", l: "Acknowledged" }, { v: "resolved", l: "Resolved" }];

function ChipGroup({ label, options, value, onChange }: {
  label: string; options: { value: string; label: string }[]; value: string | null; onChange: (v: string | null) => void;
}) {
  return (
    <div className="chip-group" role="group" aria-label={label}>
      <span className="chip-group-label">{label}</span>
      <button type="button" className="fchip" aria-pressed={value === null} onClick={() => onChange(null)}>Any</button>
      {options.map((o) => (
        <button key={o.value} type="button" className="fchip" aria-pressed={value === o.value} onClick={() => onChange(value === o.value ? null : o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

function AgentBlock({ meta }: { meta: unknown }) {
  const notes = readAgentNotes(meta);
  if (!notes.length) return null;
  return (
    <div className="agent-note" aria-label="Assistant analysis">
      {notes.map((n, i) => (
        <div key={i}>
          {n.title && <strong>{n.title}</strong>}
          {n.threat && <span className="badge warning"> Threat: {n.threat}</span>}
          {n.summary && <p>{n.summary}</p>}
        </div>
      ))}
    </div>
  );
}

function EventCard({ event, cameraName, onChanged, onDeleted }: {
  event: EventRow; cameraName: string; onChanged: (e: EventRow) => void; onDeleted: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<EventRow | null>(null);
  const [clip, setClip] = useState(false);
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadDetail = useCallback(() => api<EventRow>(`/api/events/${event.id}`).then(setDetail).catch(() => undefined), [event.id]);
  useEffect(() => { if (open) void loadDetail(); }, [open, loadDetail]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await action(); } catch (e) { setError(e instanceof ApiError ? e.message : "That did not work. Please try again."); }
    setBusy(false);
  };
  const acknowledge = () => run(async () => { onChanged(await api<EventRow>(`/api/events/${event.id}/acknowledge`, { method: "POST" })); });
  const resolve = () => run(async () => {
    const body = note.trim() ? { note: note.trim() } : {};
    onChanged(await api<EventRow>(`/api/events/${event.id}/resolve`, { method: "POST", json: body }));
    setNote(""); await loadDetail();
  });
  const addNote = () => run(async () => {
    await api(`/api/events/${event.id}/notes`, { method: "POST", json: { text: note.trim() } });
    setNote(""); await loadDetail();
  });
  const remove = () => run(async () => { await api(`/api/events/${event.id}`, { method: "DELETE" }); onDeleted(event.id); });

  const sevClass = event.severity === "critical" || event.severity === "warning" || event.severity === "info" ? event.severity : "info";
  const notes = (detail?.notes ?? []);
  const panelId = `event-${event.id}-panel`;
  return (
    <li className={`event-card sev-${sevClass}`}>
      <div className="event-head">
        <span className={`badge ${sevClass}`}>{event.severity}</span>
        <strong className="grow">{humanizeType(event.type)}</strong>
        <span className={`status-pill status-${event.status}`}>{event.status}</span>
      </div>
      <p className="hint">{cameraName} · {timeAgo(event.created_at)}</p>
      <AgentBlock meta={event.event_metadata} />
      {event.snapshot_path && (
        <img className="event-snap" loading="lazy" alt={`Snapshot of ${humanizeType(event.type)} on ${cameraName}`}
          src={`${API_BASE}/history/${encodeURIComponent(event.snapshot_path)}`} />
      )}
      <div className="actions wrap">
        {event.status === "new" && <button type="button" disabled={busy} onClick={acknowledge}>Acknowledge</button>}
        {event.status !== "resolved" && <button type="button" disabled={busy} onClick={resolve}>Mark resolved</button>}
        {event.clip_path && <button type="button" aria-pressed={clip} onClick={() => setClip(!clip)}>{clip ? "Hide clip" : "Play clip"}</button>}
        <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>{open ? "Hide notes" : "Notes"}</button>
        {!confirming && <button type="button" className="danger" onClick={() => setConfirming(true)}>Delete</button>}
      </div>
      {confirming && (
        <div className="confirm" role="alertdialog" aria-label="Confirm delete">
          <span>Delete this event and its snapshot and clip? This cannot be undone.</span>
          <button type="button" className="danger" disabled={busy} onClick={remove}>Yes, delete it</button>
          <button type="button" onClick={() => setConfirming(false)}>Keep it</button>
        </div>
      )}
      {clip && event.clip_path && (
        <video className="event-clip" controls autoPlay preload="metadata" src={`${API_BASE}/api/events/${event.id}/clip`}>
          Your browser can’t play this clip.
        </video>
      )}
      {open && (
        <div id={panelId} className="notes">
          {notes.length ? (
            <ul className="list">{notes.map((n) => <li key={n.id} className="hint">{timeAgo(n.created_at)}: {n.text}</li>)}</ul>
          ) : <p className="hint">No notes yet.</p>}
          <label className="sr-only" htmlFor={`note-${event.id}`}>Note</label>
          <div className="row-inline">
            <input id={`note-${event.id}`} type="text" value={note} maxLength={2000} placeholder="Write a note…" onChange={(e) => setNote(e.target.value)} />
            <button type="button" disabled={busy || !note.trim()} onClick={addNote}>Add note</button>
          </div>
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
    </li>
  );
}

export function EventsPage({ meta: _meta }: { meta: Meta | null }) {
  const [filters, setFilters] = useState<EventFilters>(NO_FILTERS);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [total, setTotal] = useState(0);
  const [cameras, setCameras] = useState<CameraFull[]>([]);
  const [knownTypes, setKnownTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [muted, setMutedState] = useState(isMuted());
  const [alarm, setAlarm] = useState<EventRow | null>(null);
  const seen = useRef<Set<number>>(new Set());
  const filtersRef = useRef(filters);
  filtersRef.current = filters;

  useEffect(() => { api<CameraFull[]>("/api/cameras").then(setCameras).catch(() => undefined); }, []);
  // Any click unlocks browser audio so a later alarm can actually sound.
  useEffect(() => {
    const unlock = () => unlockAudio();
    document.addEventListener("click", unlock, { once: true });
    return () => document.removeEventListener("click", unlock);
  }, []);

  const addTypes = (rows: EventRow[]) => setKnownTypes((prev) => [...new Set([...prev, ...rows.map((r) => r.type)])].sort());

  const load = useCallback(async (offset: number) => {
    setLoading(true); setLoadError("");
    try {
      const page = await api<EventPage>(`/api/events?${buildEventQuery(filters, { limit: PAGE_SIZE, offset })}`);
      page.items.forEach((e) => seen.current.add(e.id));
      setEvents((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total); addTypes(page.items);
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : "Could not load events.");
    }
    setLoading(false);
  }, [filters]);
  useEffect(() => { void load(0); }, [load]);

  useEventStream((event) => {
    const fresh = isNewCritical(event, seen.current, Date.now());
    const known = seen.current.has(event.id);
    seen.current.add(event.id);
    if (fresh) { setAlarm(event); playAlarm(); }
    addTypes([event]);
    const show = matchesFilters(event, filtersRef.current, Date.now());
    setEvents((list) => mergeLiveEvent(list, event, show && !known));
    if (show && !known) setTotal((t) => t + 1);
  });

  const toggleMute = () => { const next = !muted; setMuted(next); setMutedState(next); if (!next) unlockAudio(); };
  const cameraName = useMemo(() => {
    const names = new Map(cameras.map((c) => [c.id, c.name]));
    return (id: number) => names.get(id) ?? `Camera ${id}`;
  }, [cameras]);
  const set = <K extends keyof EventFilters>(key: K, value: EventFilters[K]) => setFilters((f) => ({ ...f, [key]: value }));
  const filtered = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);

  return (
    <section className="events-page">
      <div className="page-head">
        <h2>Events</h2>
        <div className="actions">
          <button type="button" aria-pressed={muted} onClick={toggleMute}>{muted ? "Alarm sound: off" : "Alarm sound: on"}</button>
          <button type="button" onClick={() => { unlockAudio(); playAlarm(); }} disabled={muted}>Test sound</button>
        </div>
      </div>

      {alarm && (
        <div className="alarm-banner" role="alert">
          <strong>Critical alert:</strong> {humanizeType(alarm.type)} on {cameraName(alarm.camera_id)}
          <button type="button" onClick={() => setAlarm(null)}>Dismiss</button>
        </div>
      )}

      <div className="card filters" aria-label="Filters">
        <ChipGroup label="Camera" value={filters.camera === null ? null : String(filters.camera)}
          options={cameras.map((c) => ({ value: String(c.id), label: c.name }))} onChange={(v) => set("camera", v === null ? null : Number(v))} />
        <ChipGroup label="Type" value={filters.type} options={[...new Set([...knownTypes, ...(filters.type ? [filters.type] : [])])].map((t) => ({ value: t, label: humanizeType(t) }))}
          onChange={(v) => set("type", v)} />
        <ChipGroup label="Severity" value={filters.severity} options={SEVERITIES.map((s) => ({ value: s, label: humanizeType(s) }))} onChange={(v) => set("severity", v)} />
        <ChipGroup label="Status" value={filters.status} options={STATUSES.map((s) => ({ value: s.v, label: s.l }))} onChange={(v) => set("status", v)} />
        <ChipGroup label="When" value={filters.range === "any" ? null : filters.range}
          options={(Object.keys(RANGE_LABELS) as TimeRange[]).filter((r) => r !== "any").map((r) => ({ value: r, label: RANGE_LABELS[r] }))}
          onChange={(v) => set("range", (v ?? "any") as TimeRange)} />
        {filtered && <button type="button" onClick={() => setFilters(NO_FILTERS)}>Clear all filters</button>}
      </div>

      <p className="hint" aria-live="polite">{loading && !events.length ? "Loading…" : `Showing ${events.length} of ${total} event${total === 1 ? "" : "s"}`}</p>
      {loadError && <p className="error" role="alert">{loadError}</p>}
      <ul className="list">
        {events.map((event) => (
          <EventCard key={event.id} event={event} cameraName={cameraName(event.camera_id)}
            onChanged={(updated) => setEvents((list) => list.map((e) => (e.id === updated.id ? { ...e, ...updated } : e)))}
            onDeleted={(id) => { setEvents((list) => list.filter((e) => e.id !== id)); setTotal((t) => Math.max(0, t - 1)); }} />
        ))}
        {!events.length && !loading && !loadError && (
          <li className="hint">{filtered ? "No events match these filters." : "No events yet. They will appear here the moment something is detected."}</li>
        )}
      </ul>
      {events.length < total && (
        <button type="button" disabled={loading} onClick={() => load(events.length)}>{loading ? "Loading…" : "Load more"}</button>
      )}
    </section>
  );
}
