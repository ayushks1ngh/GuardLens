import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { PointsCanvas, type Point } from "../components/PointsCanvas";
import { SnapshotStatus } from "../components/SnapshotStatus";
import { useSnapshot } from "../lib/snapshot";
import { zonePayload, zoneProblem } from "../lib/zones";
import type { Camera, Meta, ZoneRow } from "../types";

interface Draft { id?: number; name: string; polygon: Point[] }

export function ZonesPage(_props: { meta: Meta | null }) {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState<number | null>(null);
  const [zones, setZones] = useState<ZoneRow[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [message, setMessage] = useState("");
  const snapshot = useSnapshot(cameraId);

  useEffect(() => {
    api<Camera[]>("/api/cameras").then((list) => { setCameras(list); setCameraId((c) => c ?? list[0]?.id ?? null); })
      .catch((e: Error) => setMessage(e.message));
  }, []);

  const load = useCallback(async () => {
    if (cameraId === null) { setZones([]); return; }
    setZones(await api<ZoneRow[]>(`/api/cameras/${cameraId}/zones`));
  }, [cameraId]);
  useEffect(() => { setDraft(null); load().catch((e: Error) => setMessage(e.message)); }, [load]);

  const save = async () => {
    if (!draft || cameraId === null) return;
    const problem = zoneProblem(draft.name, draft.polygon);
    if (problem) { setMessage(problem); return; }
    setMessage("");
    try {
      const body = zonePayload(draft.name, draft.polygon);
      if (draft.id) await api(`/api/zones/${draft.id}`, { method: "PATCH", json: body });
      else await api(`/api/cameras/${cameraId}/zones`, { method: "POST", json: body });
      setDraft(null); await load();
    } catch (e) { setMessage(e instanceof ApiError ? e.message : "Could not save the zone."); }
  };

  const remove = async (zone: ZoneRow) => {
    if (!window.confirm(`Delete the zone “${zone.name}”? Rules that used it will apply to the whole picture instead.`)) return;
    try { await api(`/api/zones/${zone.id}`, { method: "DELETE" }); await load(); }
    catch (e) { setMessage(e instanceof ApiError ? e.message : "Could not delete the zone."); }
  };

  return (
    <section>
      <header className="page-head">
        <h2>Zones</h2>
        <label>
          <span className="sr-only">Camera</span>
          <select value={cameraId ?? ""} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : null)}>
            {!cameras.length && <option value="">No cameras yet</option>}
            {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      </header>
      <p className="hint">A zone is an area of the picture, such as a doorway or driveway. Rules can watch just one zone.</p>

      {cameraId !== null && !draft && (
        <p><button type="button" className="primary" onClick={() => { setMessage(""); setDraft({ name: "", polygon: [] }); }}>Draw a new zone</button></p>
      )}

      {draft && (
        <div className="card">
          <h3>{draft.id ? "Edit zone" : "New zone"}</h3>
          <div className="schema-form">
            <div className="field">
              <label htmlFor="zone-name">Zone name</label>
              <input id="zone-name" value={draft.name} placeholder="Front door" onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </div>
            <div className="field">
              <span className="label">Outline</span>
              <PointsCanvas background={snapshot.url} closed points={draft.polygon} onChange={(polygon) => setDraft({ ...draft, polygon })} />
              <SnapshotStatus loading={snapshot.loading} error={snapshot.error} hasImage={!!snapshot.url} onRefresh={snapshot.refresh} />
            </div>
          </div>
          {message && <p className="error" role="alert">{message}</p>}
          <div className="actions">
            <button type="button" className="primary" onClick={save}>Save zone</button>
            <button type="button" onClick={() => { setDraft(null); setMessage(""); }}>Cancel</button>
          </div>
        </div>
      )}

      {!draft && message && <p className="error" role="alert">{message}</p>}
      <ul className="list">
        {zones.map((zone) => (
          <li key={zone.id} className="row">
            <div className="grow">
              <strong>{zone.name}</strong>
              <div className="hint">{zone.polygon.length} corners</div>
            </div>
            <button type="button" onClick={() => { setMessage(""); setDraft({ id: zone.id, name: zone.name, polygon: zone.polygon.map(([x, y]) => [x, y] as Point) }); }}>Edit</button>
            <button type="button" onClick={() => remove(zone)}>Delete</button>
          </li>
        ))}
        {cameraId !== null && !zones.length && <li className="hint">No zones for this camera yet.</li>}
      </ul>
    </section>
  );
}
