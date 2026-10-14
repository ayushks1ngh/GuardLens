import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { SchemaForm, defaultValues } from "../components/SchemaForm";
import {
  advancedFields, buildChoices, buildSourcePayload, fingerprint, primaryFields, withDevices, wizardState,
  type LocalDevice, type SourceChoice, type SourceType,
} from "../lib/sources";
import type { CameraFull, Meta, Values } from "../types";
import { describeCamera } from "./HealthPage";
import { CameraTest } from "../components/CameraTest";

interface PairingResult {
  stream_id: string; publisher_url: string; qr_data_uri: string; expires_at?: string | number;
}
interface ProbeResult { resolution: { width: number; height: number }; fps: number }
interface PairingStatus { stream_id: string; connected: boolean; revoked: boolean }

const errText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

function PairingBox({ label, pairing, onCreate, busy }: {
  label: string; pairing: PairingResult | null; onCreate: () => void; busy: boolean;
}) {
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!pairing) return;
    const tick = () => api<PairingStatus[]>("/api/pairing")
      .then((list) => setConnected(Boolean(list.find((p) => p.stream_id === pairing.stream_id)?.connected))).catch(() => undefined);
    tick();
    const t = window.setInterval(tick, 3000);
    return () => window.clearInterval(t);
  }, [pairing]);
  const secure = pairing ? pairing.publisher_url.startsWith("https://") || /^http:\/\/(localhost|127\.0\.0\.1)/.test(pairing.publisher_url) : true;
  return (
    <div className="pairing">
      {!pairing ? (
        <button type="button" className="primary" disabled={busy} onClick={onCreate}>Create secure link for “{label || "Browser camera"}”</button>
      ) : (
        <>
          <img className="qr" src={pairing.qr_data_uri} alt="QR code. Scan it with the phone you want to use as a camera." />
          <div>
            <p>Scan the code with the phone, or open this link on the device you want to use:</p>
            <p><a href={pairing.publisher_url} target="_blank" rel="noopener noreferrer">Open the camera page</a></p>
            <input type="text" readOnly aria-label="Pairing link" value={pairing.publisher_url} onFocus={(e) => e.currentTarget.select()} />
            <p className="hint">The link works once and expires in about 5 minutes. Allow camera access when the phone asks.</p>
            {!secure && <p className="error">This link is not HTTPS. Phones usually refuse to share their camera over plain HTTP; open GuardLens over HTTPS first.</p>}
            <p role="status" className={connected ? "ok-text" : "hint"}>{connected ? "The device is connected." : "Waiting for the device to connect…"}</p>
          </div>
        </>
      )}
    </div>
  );
}

function Wizard({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [types, setTypes] = useState<SourceType[]>([]);
  const [devices, setDevices] = useState<LocalDevice[]>([]);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [choice, setChoice] = useState<SourceChoice | null>(null);
  const [values, setValues] = useState<Values>({});
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [probedFp, setProbedFp] = useState<string | null>(null);
  const [pairing, setPairing] = useState<PairingResult | null>(null);
  const [name, setName] = useState("");
  const [fps, setFps] = useState(6);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    api<SourceType[]>("/api/cameras/source-types").then(setTypes).catch((e) => setMessage({ kind: "error", text: errText(e, "Could not load camera types.") }));
    api<LocalDevice[]>("/api/cameras/local-devices").then(setDevices).catch(() => setDevices([]));
  }, []);

  const choices = buildChoices(types);
  const fields = choice ? withDevices(choice.fields, devices) : [];
  const state = wizardState({ choice, values, pairing, probedFingerprint: probedFp, name });

  const pick = (c: SourceChoice) => {
    setChoice(c); setValues(defaultValues(withDevices(c.fields, devices)));
    setProbe(null); setProbedFp(null); setPairing(null); setMessage(null); setStep(2);
  };
  const change = (v: Values) => { setValues(v); setMessage(null); };

  const test = async () => {
    if (!choice) return;
    const payload = buildSourcePayload(choice, values);
    setBusy(true); setMessage(null); setProbe(null);
    try {
      const result = await api<ProbeResult>("/api/cameras/probe", { method: "POST", json: payload });
      setProbe(result); setProbedFp(fingerprint(payload));
      setMessage({ kind: "ok", text: `It works. The camera sent a picture ${result.resolution.width} by ${result.resolution.height} at about ${result.fps} frames per second.` });
    } catch (e) {
      setProbedFp(null); setMessage({ kind: "error", text: `Couldn’t get a picture: ${errText(e, "unknown problem")}` });
    }
    setBusy(false);
  };
  const createPairing = async () => {
    setBusy(true); setMessage(null);
    try { setPairing(await api<PairingResult>("/api/pairing", { method: "POST", json: { label: name.trim() || "Browser camera", ttl_seconds: 300 } })); }
    catch (e) { setMessage({ kind: "error", text: `Couldn’t create the link: ${errText(e, "unknown problem")}` }); }
    setBusy(false);
  };
  const add = async () => {
    if (!choice) return;
    setBusy(true); setMessage(null);
    try {
      await api("/api/cameras", { method: "POST", json: { name: name.trim(), analyze_fps: fps, ...buildSourcePayload(choice, values, pairing) } });
      onDone();
    } catch (e) { setMessage({ kind: "error", text: `Couldn’t add the camera: ${errText(e, "unknown problem")}` }); setBusy(false); }
  };

  const primary = primaryFields(fields), advanced = advancedFields(fields);
  const stepLabels = ["Source", "Connect", "Name & save"];
  return (
    <div className="card wizard">
      <ol className="steps" aria-label="Progress">
        {stepLabels.map((l, i) => <li key={l} aria-current={step === i + 1 ? "step" : undefined} className={step > i + 1 ? "done" : ""}>{i + 1}. {l}</li>)}
      </ol>

      {step === 1 && (
        <div>
          <h3>Where does the video come from?</h3>
          <div className="choices">
            {choices.map((c) => (
              <button key={c.id} type="button" className="choice" onClick={() => pick(c)}>
                <strong>{c.title}</strong><span className="hint">{c.description}</span>
              </button>
            ))}
            {!choices.length && !message && <p className="hint">Loading…</p>}
          </div>
        </div>
      )}

      {step === 2 && choice && (
        <div>
          <h3>{choice.title}</h3>
          <p className="hint">{choice.description}</p>
          {choice.pairing ? (
            <>
              <div className="field">
                <label htmlFor="wiz-pair-name">Camera name</label>
                <input id="wiz-pair-name" type="text" value={name} placeholder="Front door phone" onChange={(e) => setName(e.target.value)} />
              </div>
              <PairingBox label={name} pairing={pairing} onCreate={createPairing} busy={busy} />
            </>
          ) : (
            <>
              <SchemaForm fields={primary} values={values} onChange={change} />
              {advanced.length > 0 && (
                <details className="advanced">
                  <summary>Advanced settings</summary>
                  <SchemaForm fields={advanced} values={values} onChange={change} />
                </details>
              )}
              <div className="actions wrap">
                <button type="button" className="primary" disabled={busy || !state.canTest} onClick={test}>{busy ? "Testing…" : "Test connection"}</button>
              </div>
              {probe && !state.stale && <p className="ok-text">Test passed: {probe.resolution.width}×{probe.resolution.height}</p>}
            </>
          )}
          <p className="hint" aria-live="polite">{state.hint}</p>
          <div className="actions wrap">
            <button type="button" onClick={() => setStep(1)}>Back</button>
            <button type="button" className="primary" onClick={() => setStep(3)}
              disabled={choice.pairing ? !pairing : !(probedFp !== null && !state.stale && state.missing.length === 0)}>Next</button>
          </div>
        </div>
      )}

      {step === 3 && choice && (
        <div>
          <h3>Name it and save</h3>
          <div className="field">
            <label htmlFor="wiz-name">Camera name</label>
            <input id="wiz-name" type="text" value={name} placeholder="Front door" onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="wiz-fps">Checks per second</label>
            <div className="slider">
              <input id="wiz-fps" type="range" min={1} max={30} step={1} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
              <output>{fps} /sec</output>
            </div>
            <p className="hint">How often GuardLens looks for things. Higher is faster to react but uses more power.</p>
          </div>
          <p className="hint" aria-live="polite">{state.hint}</p>
          <div className="actions wrap">
            <button type="button" onClick={() => setStep(2)}>Back</button>
            <button type="button" className="primary" disabled={busy || !state.canAdd} onClick={add}>{busy ? "Adding…" : "Add camera"}</button>
          </div>
        </div>
      )}

      {message && <p className={message.kind === "ok" ? "ok-text" : "error"} role={message.kind === "error" ? "alert" : "status"}>{message.text}</p>}
      <div className="actions"><button type="button" onClick={onCancel}>Cancel</button></div>
    </div>
  );
}

function EditCamera({ camera, types, devices, onDone }: {
  camera: CameraFull; types: SourceType[]; devices: LocalDevice[]; onDone: () => void;
}) {
  const [name, setName] = useState(camera.name);
  const [enabled, setEnabled] = useState(camera.enabled);
  const [fps, setFps] = useState(camera.analyze_fps ?? 6);
  const config = (camera.source_config ?? {}) as Values;
  const choice = buildChoices(types).find((c) => c.sourceType === camera.source_type && c.mode === config.mode) ?? null;
  const editable = choice !== null && !choice.pairing;
  const fields = choice ? withDevices(choice.fields, devices) : [];
  // The server hides credentials in network URLs, so the URL box starts empty and is only sent if retyped.
  const [values, setValues] = useState<Values>(() => {
    const { mode: _m, url: _u, ...rest } = config; void _m; void _u;
    return rest;
  });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true); setError("");
    const body: Values = { name: name.trim(), enabled, analyze_fps: fps };
    if (choice && editable) {
      const payload = buildSourcePayload(choice, values);
      const urlField = fields.find((f) => f.name === "url");
      const sourceTouched = urlField ? Boolean(String(values.url ?? "").trim()) : fingerprint(payload.source_config) !== fingerprint({ mode: config.mode, ...Object.fromEntries(Object.entries(config).filter(([k]) => k !== "mode")) });
      if (sourceTouched) { body.source_type = payload.source_type; body.source_config = payload.source_config; }
    }
    try { await api(`/api/cameras/${camera.id}`, { method: "PATCH", json: body }); onDone(); }
    catch (e) { setError(errText(e, "Could not save changes.")); setBusy(false); }
  };
  const urlField = fields.find((f) => f.name === "url");
  const shown = urlField ? fields.map((f) => (f.name === "url" ? { ...f, required: false, placeholder: `Leave blank to keep ${String(config.url ?? "the current address")}` } : f)) : fields;
  return (
    <div className="card edit">
      <div className="field">
        <label htmlFor={`edit-name-${camera.id}`}>Camera name</label>
        <input id={`edit-name-${camera.id}`} type="text" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <label className="switch"><input type="checkbox" role="switch" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /><span>{enabled ? "Camera is on" : "Camera is off"}</span></label>
      <div className="field">
        <label htmlFor={`edit-fps-${camera.id}`}>Checks per second</label>
        <div className="slider">
          <input id={`edit-fps-${camera.id}`} type="range" min={1} max={30} step={1} value={fps} onChange={(e) => setFps(Number(e.target.value))} />
          <output>{fps} /sec</output>
        </div>
      </div>
      {editable && (
        <details className="advanced">
          <summary>Change the video source</summary>
          <SchemaForm fields={shown} values={values} onChange={setValues} />
        </details>
      )}
      {choice?.pairing && <p className="hint">To use a different phone or browser, delete this camera and add it again.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="actions">
        <button type="button" className="primary" disabled={busy || !name.trim()} onClick={save}>Save changes</button>
        <button type="button" onClick={onDone}>Cancel</button>
      </div>
    </div>
  );
}

function sourceSummary(camera: CameraFull, types: SourceType[]): string {
  const config = (camera.source_config ?? {}) as Values;
  const choice = buildChoices(types).find((c) => c.sourceType === camera.source_type && c.mode === config.mode);
  const detail = config.url ?? config.path ?? (config.device_index !== undefined ? `camera ${String(config.device_index)}` : "");
  return [choice?.title ?? camera.source_type ?? "Camera", detail && String(detail)].filter(Boolean).join(" · ");
}

export function CamerasPage({ meta: _meta }: { meta: Meta | null }) {
  const [cameras, setCameras] = useState<CameraFull[] | null>(null);
  const [types, setTypes] = useState<SourceType[]>([]);
  const [devices, setDevices] = useState<LocalDevice[]>([]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [testing, setTesting] = useState<number | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => api<CameraFull[]>("/api/cameras").then(setCameras).catch(() => setError("Can’t reach the server.")), []);
  useEffect(() => {
    void load();
    api<SourceType[]>("/api/cameras/source-types").then(setTypes).catch(() => undefined);
    api<LocalDevice[]>("/api/cameras/local-devices").then(setDevices).catch(() => undefined);
    const t = window.setInterval(load, 5000);
    return () => window.clearInterval(t);
  }, [load]);

  const remove = async (id: number) => {
    try { await api(`/api/cameras/${id}`, { method: "DELETE" }); setConfirmDelete(null); await load(); }
    catch (e) { setError(errText(e, "Could not delete the camera.")); }
  };

  return (
    <section>
      <div className="page-head">
        <h2>Cameras</h2>
        {!adding && <button type="button" className="primary" onClick={() => { setAdding(true); setEditing(null); }}>Add a camera</button>}
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {adding && <Wizard onCancel={() => setAdding(false)} onDone={() => { setAdding(false); void load(); }} />}
      <ul className="list">
        {(cameras ?? []).map((camera) => {
          const state = describeCamera(camera, camera.status ? { camera_id: camera.id, source_type: camera.source_type ?? "", ...camera.status } : undefined);
          return (
            <li key={camera.id} className="cam-item">
              <div className="row">
                <span className={`dot ${state.tone}`} aria-hidden />
                <div className="grow">
                  <strong>{camera.name}</strong>
                  <p className="hint">{sourceSummary(camera, types)} · {state.text}</p>
                </div>
                <button type="button" onClick={() => setTesting(testing === camera.id ? null : camera.id)} aria-expanded={testing === camera.id}>Test</button>
                <button type="button" onClick={() => setEditing(editing === camera.id ? null : camera.id)} aria-expanded={editing === camera.id}>Edit</button>
                {confirmDelete !== camera.id && <button type="button" className="danger" onClick={() => setConfirmDelete(camera.id)}>Delete</button>}
              </div>
              {confirmDelete === camera.id && (
                <div className="confirm" role="alertdialog" aria-label={`Confirm deleting ${camera.name}`}>
                  <span>Delete “{camera.name}”? This cannot be undone.</span>
                  <button type="button" className="danger" onClick={() => remove(camera.id)}>Yes, delete it</button>
                  <button type="button" onClick={() => setConfirmDelete(null)}>Keep it</button>
                </div>
              )}
              {testing === camera.id && <CameraTest cameraId={camera.id} cameraName={camera.name} />}
              {editing === camera.id && <EditCamera camera={camera} types={types} devices={devices} onDone={() => { setEditing(null); void load(); }} />}
            </li>
          );
        })}
        {cameras && !cameras.length && !adding && <li className="hint">No cameras yet. Choose “Add a camera” to get started.</li>}
      </ul>
    </section>
  );
}
