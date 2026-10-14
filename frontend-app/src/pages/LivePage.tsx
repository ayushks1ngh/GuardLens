import { ChatPanel } from "../components/ChatPanel";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_BASE } from "../api";
import { boxLabel, boxStyle, boxTone, countsText } from "../lib/overlay";
import { isNewCritical } from "../lib/eventLogic";
import { readPref, writePref } from "../lib/storage";
import { useEventStream } from "../lib/useEventStream";
import type { CameraFull, Meta, OverlayInfo } from "../types";
import { describeCamera } from "./HealthPage";

const DEFAULT_ANALYZE_FPS = 6;
const HIGHLIGHT_MS = 10_000;

/** Reconnect delay for a failed video stream: 2s, 4s, 8s … capped at 15s. */
export function retryDelay(attempt: number): number {
  return Math.min(15_000, 2000 * 2 ** Math.max(0, attempt));
}

export function useOverlays(): Record<string, OverlayInfo> {
  const [data, setData] = useState<Record<string, OverlayInfo>>({});
  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const source = new EventSource(`${API_BASE}/api/stream/overlay`);
    source.onmessage = (m) => { try { setData(JSON.parse(m.data)); } catch { /* skip bad frame */ } };
    return () => source.close();
  }, []);
  return data;
}

function VideoFeed({ camera, overlay, reloadToken }: { camera: CameraFull; overlay?: OverlayInfo; reloadToken: string }) {
  const [attempt, setAttempt] = useState(0);
  const [nonce, setNonce] = useState(0);
  const [ratio, setRatio] = useState(16 / 9);
  const [failed, setFailed] = useState(false);
  const timer = useRef<number>();
  const reload = useCallback(() => { setFailed(false); setNonce((n) => n + 1); }, []);

  // Reload when the camera comes back online or the user asks for a refresh.
  const firstRun = useRef(true);
  useEffect(() => {
    if (firstRun.current) { firstRun.current = false; return; }
    setAttempt(0); reload();
  }, [reloadToken, reload]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const onError = () => {
    setFailed(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { setAttempt((a) => a + 1); setNonce((n) => n + 1); }, retryDelay(attempt));
  };
  const boxes = overlay?.boxes ?? [];
  return (
    <div className="feed" style={{ aspectRatio: String(ratio) }}>
      <img key={nonce} alt={`Live video from ${camera.name}`} src={`${API_BASE}/stream/${camera.id}/mjpeg?r=${nonce}`}
        onLoad={(e) => { const i = e.currentTarget; if (i.naturalWidth) setRatio(i.naturalWidth / i.naturalHeight); setFailed(false); setAttempt(0); }}
        onError={onError} />
      <div className="feed-boxes" aria-hidden>
        {boxes.map((b, i) => (
          <div key={b.track_id ?? i} className={`feed-box tone-${boxTone(b)}`} style={boxStyle(b)}>
            <span className="feed-box-label">{boxLabel(b)}</span>
          </div>
        ))}
      </div>
      {boxes.length > 0 && <span className="feed-counts" aria-hidden>{countsText(overlay?.counts)}</span>}
      {failed && <div className="feed-msg" role="status">Video interrupted. Reconnecting…</div>}
    </div>
  );
}

function FpsSlider({ camera, onSaved }: { camera: CameraFull; onSaved: () => void }) {
  const saved = camera.analyze_fps ?? DEFAULT_ANALYZE_FPS;
  const [value, setValue] = useState(saved);
  const [state, setState] = useState<"" | "saving" | "saved" | "error">("");
  useEffect(() => setValue(saved), [saved]);
  useEffect(() => {
    if (value === saved) return;
    const t = window.setTimeout(async () => {
      setState("saving");
      try { await api(`/api/cameras/${camera.id}`, { method: "PATCH", json: { analyze_fps: value } }); setState("saved"); onSaved(); }
      catch { setState("error"); }
    }, 700);
    return () => window.clearTimeout(t);
  }, [value, saved, camera.id, onSaved]);
  const id = `fps-${camera.id}`;
  return (
    <div className="fps">
      <label htmlFor={id}>Checks per second</label>
      <div className="slider">
        <input id={id} type="range" min={1} max={30} step={1} value={value} onChange={(e) => setValue(Number(e.target.value))}
          aria-describedby={`${id}-help`} />
        <output>{value} /sec</output>
      </div>
      <p id={`${id}-help`} className="hint" aria-live="polite">
        {state === "saving" ? "Saving…" : state === "error" ? "Could not save." : state === "saved" ? "Saved. Applies the next time this camera restarts." : "Higher spots things faster but uses more computer power."}
      </p>
    </div>
  );
}

function Tile({ camera, overlay, alert, focused, onFocus, onChanged }: {
  camera: CameraFull; overlay?: OverlayInfo; alert: boolean; focused: boolean; onFocus: () => void; onChanged: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(0);
  const state = describeCamera(camera, camera.status ? { camera_id: camera.id, source_type: camera.source_type ?? "", ...camera.status } : undefined);
  const counts = Object.entries(overlay?.counts ?? {});
  const online = Boolean(camera.status?.connected);

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    try { await api(`/api/cameras/${camera.id}`, { method: "PATCH", json: { enabled } }); } catch { /* state refresh shows truth */ }
    setBusy(false); onChanged();
  };
  const fullscreen = () => {
    const el = ref.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.();
  };
  return (
    <article ref={ref} className={`tile${alert ? " tile-alert" : ""}`} aria-label={camera.name}>
      <header className="tile-head">
        <span className={`dot ${state.tone}`} aria-hidden />
        <strong className="grow">{camera.name}</strong>
        <label className="switch">
          <input type="checkbox" role="switch" checked={camera.enabled} disabled={busy} aria-label={`${camera.name} on or off`}
            onChange={(e) => toggle(e.target.checked)} />
          <span>{camera.enabled ? "On" : "Off"}</span>
        </label>
      </header>
      {camera.enabled ? <VideoFeed camera={camera} overlay={overlay} reloadToken={`${online}-${manual}`} />
        : <div className="feed feed-off" style={{ aspectRatio: "16 / 9" }}><span>Camera is switched off</span></div>}
      {alert && <div className="tile-alert-msg" role="alert">Critical alert on this camera</div>}
      <p className="hint">{state.text}</p>
      {counts.length > 0 && (
        <ul className="counts" aria-label="Currently seen">
          {counts.map(([name, n]) => <li key={name} className="badge info">{n} {name}</li>)}
        </ul>
      )}
      <div className="actions wrap">
        <button type="button" onClick={onFocus}>{focused ? "Back to grid" : "Focus"}</button>
        <button type="button" onClick={fullscreen}>Fullscreen</button>
        {camera.enabled && <button type="button" onClick={() => setManual((n) => n + 1)}>Reload video</button>}
      </div>
      <FpsSlider camera={camera} onSaved={onChanged} />
    </article>
  );
}

export function LivePage({ meta: _meta }: { meta: Meta | null }) {
  const [cameras, setCameras] = useState<CameraFull[] | null>(null);
  const [error, setError] = useState("");
  const [columns, setColumns] = useState<1 | 2 | 3>(() => (["1", "2", "3"].includes(readPref("guardlens.liveColumns") ?? "") ? Number(readPref("guardlens.liveColumns")) as 1 | 2 | 3 : 2));
  const [focus, setFocus] = useState<number | null>(null);
  const [alerts, setAlerts] = useState<Record<number, number>>({});
  const seen = useRef<Set<number>>(new Set());
  const overlays = useOverlays();

  const refresh = useCallback(() => {
    api<CameraFull[]>("/api/cameras").then((c) => { setCameras(c); setError(""); }).catch(() => setError("Can’t reach the server."));
  }, []);
  useEffect(() => { refresh(); const t = window.setInterval(refresh, 5000); return () => window.clearInterval(t); }, [refresh]);

  useEventStream((event) => {
    if (!isNewCritical(event, seen.current, Date.now())) { seen.current.add(event.id); return; }
    seen.current.add(event.id);
    setAlerts((a) => ({ ...a, [event.camera_id]: Date.now() + HIGHLIGHT_MS }));
    window.setTimeout(() => setAlerts((a) => {
      if ((a[event.camera_id] ?? 0) > Date.now()) return a;
      const { [event.camera_id]: _gone, ...rest } = a; void _gone; return rest;
    }), HIGHLIGHT_MS + 100);
  });

  const pickColumns = (n: 1 | 2 | 3) => { setColumns(n); writePref("guardlens.liveColumns", String(n)); };
  const shown = (cameras ?? []).filter((c) => focus === null || c.id === focus);
  const focusedMissing = focus !== null && cameras !== null && !shown.length;
  useEffect(() => { if (focusedMissing) setFocus(null); }, [focusedMissing]);

  return (
    <section className="live-page">
      <div className="page-head">
        <h2>Live view</h2>
        {focus === null && (
          <div className="seg" role="group" aria-label="Cameras per row">
            {([1, 2, 3] as const).map((n) => (
              <button key={n} type="button" aria-pressed={columns === n} onClick={() => pickColumns(n)}>{n} per row</button>
            ))}
          </div>
        )}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {cameras && !cameras.length && <p className="hint">No cameras yet. Add one on the Cameras page.</p>}
      <div className="live-split">
        <div className="live-grid" style={{ ["--cols" as string]: focus === null ? columns : 1 }}>
          {shown.map((camera) => (
            <Tile key={camera.id} camera={camera} overlay={overlays[String(camera.id)]} alert={(alerts[camera.id] ?? 0) > Date.now()}
              focused={focus === camera.id} onFocus={() => setFocus(focus === camera.id ? null : camera.id)} onChanged={refresh} />
          ))}
        </div>
        <aside className="live-chat" aria-label="Ask GuardLens">
          <ErrorBoundary label="The chat"><ChatPanel compact /></ErrorBoundary>
        </aside>
      </div>
    </section>
  );
}
