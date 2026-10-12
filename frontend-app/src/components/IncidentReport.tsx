import { useState } from "react";
import { api, ApiError } from "../api";
import { Markdown } from "../lib/markdown";

export interface IncidentData { event_id: number; narrative?: string; provider?: string | null; markdown: string }

export function IncidentReport({ eventId }: { eventId: number }) {
  const [report, setReport] = useState<IncidentData | null>(null);
  const [ai, setAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");

  const load = async (withAi: boolean) => {
    setBusy(true); setError(""); setNote("");
    try { setReport(await api<IncidentData>(`/api/events/${eventId}/incident-report?ai=${withAi}`)); setAi(withAi); }
    catch (e) { setError(e instanceof ApiError ? e.message : "Could not build the report. Please try again."); }
    setBusy(false);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(report?.markdown ?? ""); setNote("Copied."); }
    catch { setNote("Could not copy. Select the text and copy it by hand."); }
  };
  const download = () => {
    if (!report) return;
    const url = URL.createObjectURL(new Blob([report.markdown], { type: "text/markdown" }));
    const a = document.createElement("a");
    a.href = url; a.download = `incident-${eventId}.md`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="incident">
      {!report && <button type="button" disabled={busy} onClick={() => load(false)}>{busy ? "Building report…" : "Incident report"}</button>}
      {error && <p className="error" role="alert">{error}</p>}
      {report && (
        <section className="incident-panel" aria-label="Incident report">
          <div className="actions wrap">
            <button type="button" onClick={copy}>Copy</button>
            <button type="button" onClick={download}>Download .md</button>
            <button type="button" onClick={() => { setReport(null); setAi(false); setNote(""); }}>Close report</button>
          </div>
          <label className="switch">
            <input type="checkbox" checked={ai} disabled={busy} onChange={(e) => load(e.target.checked)} />
            <span>Add AI summary</span>
          </label>
          <p className="hint">Turning this on sends the alert text to your AI provider so it can write a short summary.</p>
          {note && <p role="status" className="hint">{note}</p>}
          <Markdown text={report.markdown} />
        </section>
      )}
    </div>
  );
}
