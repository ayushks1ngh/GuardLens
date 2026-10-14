import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";

export interface Diagnosis {
  ok: boolean; summary: string; checks: { name: string; ok: boolean; detail: string }[]; advice: string[];
}

/** "Test this camera": runs the server's checks and shows what is wrong and what to do, in plain words. */
export function CameraTest({ cameraId, cameraName }: { cameraId: number; cameraName: string }) {
  const [result, setResult] = useState<Diagnosis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    setBusy(true); setError(null);
    try { setResult(await api<Diagnosis>(`/api/cameras/${cameraId}/test`, { method: "POST" })); }
    catch (e) { setResult(null); setError(e instanceof ApiError ? e.message : "The test could not run."); }
    finally { setBusy(false); }
  }, [cameraId]);
  useEffect(() => { void run(); }, [run]);  // opening the panel runs the test

  return (
    <div className="camera-test">
      {busy && <p className="hint" role="status">Testing {cameraName}…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {result && (
        <div className={`card diagnosis ${result.ok ? "ok" : "bad"}`} role="status" aria-label={`Result for ${cameraName}`}>
          <p><strong>{result.summary}</strong></p>
          <ul className="checks">
            {result.checks.map((c) => (
              <li key={c.name}><span aria-hidden>{c.ok ? "✓" : "✗"}</span> <span className="sr-only">{c.ok ? "Passed:" : "Failed:"}</span> {c.name} — {c.detail}</li>
            ))}
          </ul>
          <button type="button" onClick={() => void run()} disabled={busy}>Run again</button>
          {result.advice.length > 0 && (
            <>
              <p className="hint" style={{ marginBottom: 4 }}>What to do:</p>
              <ol>{result.advice.map((a) => <li key={a}>{a}</li>)}</ol>
            </>
          )}
        </div>
      )}
    </div>
  );
}
