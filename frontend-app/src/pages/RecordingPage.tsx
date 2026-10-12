import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { SchemaForm } from "../components/SchemaForm";
import { RECORDING_FIELDS, describeRecording, withDefaults } from "../lib/recordingFields";
import type { Camera, FieldError, Meta, RecordingResponse, RecordingStatus, Values } from "../types";

export function RecordingPage(_props: { meta: Meta | null }) {
  const [values, setValues] = useState<Values | null>(null);
  const [status, setStatus] = useState<RecordingStatus | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState("");
  const [saved, setSaved] = useState("");

  const load = useCallback(async () => {
    const [r, c] = await Promise.all([api<RecordingResponse>("/api/recording"), api<Camera[]>("/api/cameras")]);
    setValues(withDefaults(r.config)); setStatus(r.status); setCameras(c);
  }, []);
  useEffect(() => { load().catch((e: Error) => setMessage(e.message)); }, [load]);

  const save = async () => {
    if (!values) return;
    setErrors([]); setMessage(""); setSaved("");
    try {
      const r = await api<RecordingResponse>("/api/recording", { method: "PATCH", json: withDefaults(values) });
      setValues(withDefaults(r.config)); setStatus(r.status); setSaved("Recording settings saved.");
    } catch (e) {
      if (e instanceof ApiError) { setErrors(e.fields); setMessage(e.message); } else setMessage("Could not save.");
    }
  };

  const name = (id: string) => cameras.find((c) => String(c.id) === id)?.name ?? `Camera ${id}`;
  const summary = status ? describeRecording(status, name) : null;

  return (
    <section>
      <header className="page-head"><h2>Recording</h2></header>
      {summary && (
        <div className="card" role="status">
          <h3><span className={`dot ${summary.tone === "ok" ? "ok" : summary.tone === "warn" ? "warn" : ""}`} aria-hidden /> {summary.headline}</h3>
          <ul className="plain">{summary.details.map((d) => <li key={d} className="hint">{d}</li>)}</ul>
          <button type="button" onClick={() => load().catch((e: Error) => setMessage(e.message))}>Refresh status</button>
        </div>
      )}
      {values && (
        <div className="card">
          <SchemaForm fields={RECORDING_FIELDS} values={values} errors={errors} onChange={setValues} />
          {message && <p className="error" role="alert">{message}</p>}
          {saved && <p className="hint" role="status">{saved}</p>}
          <div className="actions"><button type="button" className="primary" onClick={save}>Save settings</button></div>
          <p className="hint">Saving restarts any recording in progress.</p>
        </div>
      )}
      {!values && message && <p className="error" role="alert">{message}</p>}
    </section>
  );
}
