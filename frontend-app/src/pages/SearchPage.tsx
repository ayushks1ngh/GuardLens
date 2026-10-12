import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, API_BASE, ApiError } from "../api";
import { requestNavigate } from "../lib/navigate";
import {
  EXAMPLE_QUERIES, OFF_EXPLANATION, hitTitle, isBusy, matchNote, progressText, searchErrorText,
  type SearchHit, type SearchStatus,
} from "../lib/search";
import { timeAgo } from "../lib/eventLogic";
import type { Camera, Meta } from "../types";

export function SearchPage({ meta: _meta }: { meta: Meta | null }) {
  const [status, setStatus] = useState<SearchStatus | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [query, setQuery] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [heading, setHeading] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => api<SearchStatus>("/api/search/status").then(setStatus).catch(() => undefined), []);
  useEffect(() => { refresh(); api<Camera[]>("/api/cameras").then(setCameras).catch(() => undefined); }, [refresh]);
  const polling = isBusy(status);
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [polling, refresh]);

  const turnOn = async () => {
    setError(null);
    try { setStatus(await api<SearchStatus>("/api/search/settings", { method: "PUT", json: { enabled: true } })); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not turn search on."); }
  };

  const run = async (path: string, title: string) => {
    setBusy(true); setError(null);
    try {
      const res = await api<{ results: SearchHit[] }>(path);
      setHits(res.results); setHeading(title);
    } catch (e) {
      setHits(null);
      setError(e instanceof ApiError ? searchErrorText(e.status, e.message) : searchErrorText(undefined));
      if (e instanceof ApiError && e.status === 409) refresh();
    } finally { setBusy(false); }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q.length < 2) { setError(searchErrorText(422)); return; }
    const params = new URLSearchParams({ q });
    if (cameraId) params.set("camera_id", cameraId);
    run(`/api/search?${params}`, `Results for “${q}”`);
  };

  return (
    <section className="search-page">
      <div className="page-head"><h2>Find footage</h2></div>
      {status && !status.enabled && (
        <div className="card" role="status">
          <p style={{ marginTop: 0 }}>{OFF_EXPLANATION}</p>
          <button type="button" className="primary" onClick={turnOn}>Turn on</button>
        </div>
      )}
      {status && polling && (
        <div className="card" role="status">
          {status.loading ? "Getting the search model ready… " : "Indexing your alerts… "}{progressText(status)}
        </div>
      )}
      {status?.enabled && status.error && <p className="error" role="alert">Search had a problem: {status.error}</p>}
      <form className="card row-inline wrap" onSubmit={submit}>
        <label htmlFor="search-q" className="sr-only">What are you looking for?</label>
        <input id="search-q" type="search" className="grow" value={query} placeholder="Describe what you are looking for"
          onChange={(e) => setQuery(e.target.value)} />
        <label htmlFor="search-cam" className="sr-only">Camera</label>
        <select id="search-cam" value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
          <option value="">All cameras</option>
          {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button type="submit" className="primary" disabled={busy}>Search</button>
        <p className="hint" style={{ flexBasis: "100%" }}>
          Try: {EXAMPLE_QUERIES.map((q, i) => (
            <span key={q}>{i > 0 ? ", " : ""}<button type="button" className="link" onClick={() => setQuery(q)}>“{q}”</button></span>
          ))}. Time words like “yesterday” or “last 3 hours” work too.
        </p>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {busy && <p className="hint">Searching…</p>}
      {hits && !busy && (
        <>
          <h3>{heading}</h3>
          {hits.length === 0 ? <p className="hint">Nothing matched. Try different words or a wider time.</p> : (
            <ul className="result-grid">
              {hits.map((h) => (
                <li key={h.event_id} className="card result-card">
                  <button type="button" className="thumb-btn" onClick={() => requestNavigate("events", h.event_id)}
                    aria-label={`Open alert: ${hitTitle(h)}, ${h.camera}`}>
                    {h.snapshot_path
                      ? <img src={`${API_BASE}/history/${encodeURIComponent(h.snapshot_path)}`} alt="" loading="lazy" />
                      : <span className="feed-off">No picture</span>}
                  </button>
                  <strong>{hitTitle(h)}</strong>
                  <div className="hint">{h.camera} · {timeAgo(h.created_at)}</div>
                  <div className="hint">{matchNote(h.source)}</div>
                  <button type="button" onClick={() => run(`/api/search/similar/${h.event_id}`, `Similar to “${hitTitle(h)}”`)}>Find similar</button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
