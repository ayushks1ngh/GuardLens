import { Fragment, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { requestNavigate } from "../lib/navigate";
import {
  describePreview, friendlyRuleError, hasProblems, proposalToRuleBody, summarizeProposal,
  type Preview, type Proposal,
} from "../lib/ruleDraft";
import type { Camera, PluginType, Values, ZoneRow } from "../types";

function ErrorLine({ error }: { error: { text: string; helperOff: boolean } | null }) {
  if (!error) return null;
  return (
    <p className="error" role="alert">
      {error.text}{" "}
      {error.helperOff && <button type="button" className="link" onClick={() => requestNavigate("agents")}>Open Agents</button>}
    </p>
  );
}

/** "Preview" for a rule being edited by hand: how often would it have fired recently. */
export function PreviewControl({ draft }: {
  draft: { type: string; camera_id: number | null; zone_id?: number | null; cooldown_seconds: number; params: Values };
}) {
  const [hours, setHours] = useState(72);
  const [text, setText] = useState("");
  const [error, setError] = useState<{ text: string; helperOff: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setError(null); setText("");
    try {
      const pv = await api<Preview>("/api/rules/preview", {
        method: "POST",
        json: { type: draft.type, camera_id: draft.camera_id, zone_id: draft.zone_id ?? null, cooldown_seconds: draft.cooldown_seconds, params: draft.params, hours },
      });
      setText(describePreview(pv));
    } catch (e) {
      setError(friendlyRuleError(e instanceof ApiError ? e.status : 0, e instanceof ApiError ? e.message : ""));
    }
    setBusy(false);
  };
  return (
    <div className="preview-control">
      <div className="row-inline">
        <label htmlFor="preview-hours">Test against the last</label>
        <select id="preview-hours" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          <option value={24}>24 hours</option><option value={72}>72 hours</option><option value={168}>7 days</option>
        </select>
        <button type="button" disabled={busy} onClick={run}>{busy ? "Checking…" : "Preview"}</button>
      </div>
      {text && <p role="status" className="preview-result">{text}</p>}
      <ErrorLine error={error} />
    </div>
  );
}

export function RuleAssist({ types, cameras, onSaved, onEdit }: {
  types: PluginType[]; cameras: Camera[]; onSaved: () => void; onEdit: (p: Proposal) => void;
}) {
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [zones, setZones] = useState<ZoneRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ text: string; helperOff: boolean } | null>(null);
  const [saved, setSaved] = useState("");

  const cameraId = proposal?.camera_id ?? null;
  useEffect(() => {
    if (cameraId === null) { setZones([]); return; }
    api<ZoneRow[]>(`/api/cameras/${cameraId}/zones`).then(setZones).catch(() => setZones([]));
  }, [cameraId]);

  const fail = (e: unknown) => setError(e instanceof ApiError ? friendlyRuleError(e.status, e.message) : { text: "Something went wrong. Please try again.", helperOff: false });

  const draft = async () => {
    setBusy(true); setError(null); setProposal(null); setPreview(null); setSaved("");
    try {
      const p = await api<Proposal>("/api/rules/propose", { method: "POST", json: { text: text.trim() } });
      setProposal(p);
      if (!hasProblems(p)) {
        api<Preview>("/api/rules/preview", { method: "POST", json: { type: p.type, camera_id: p.camera_id, zone_id: p.zone_id ?? null, cooldown_seconds: p.cooldown_seconds, params: p.params, hours: 72 } })
          .then(setPreview).catch(() => setPreview(null));
      }
    } catch (e) { fail(e); }
    setBusy(false);
  };

  const save = async () => {
    if (!proposal) return;
    setBusy(true); setError(null);
    try {
      await api("/api/rules", { method: "POST", json: proposalToRuleBody(proposal) });
      setSaved(`Saved “${proposal.name}”. It is active now.`);
      setProposal(null); setPreview(null); setText(""); onSaved();
    } catch (e) { fail(e); }
    setBusy(false);
  };

  const summary = proposal ? summarizeProposal(proposal, types, cameras, zones) : null;
  return (
    <div className="card rule-assist">
      <h3>Describe it in plain words</h3>
      <label htmlFor="rule-words" className="hint">Say what you want to be told about, and the AI helper will draft a rule for you to check.</label>
      <textarea id="rule-words" rows={3} value={text} maxLength={1000} onChange={(e) => setText(e.target.value)}
        placeholder="Tell me when anyone is at the back door after 10pm" />
      <div className="actions">
        <button type="button" className="primary" disabled={busy || !text.trim()} onClick={draft}>{busy && !proposal ? "Drafting…" : "Draft a rule"}</button>
      </div>
      <ErrorLine error={error} />
      {saved && <p role="status" className="hint">{saved}</p>}
      {proposal && summary && (
        <div className="proposal" aria-label="Drafted rule">
          <h4>{proposal.name}</h4>
          <dl className="summary">
            <dt>Kind of rule</dt><dd>{summary.typeLabel}</dd>
            <dt>Where</dt><dd>{summary.where}</dd>
            <dt>How serious</dt><dd>{summary.severity}</dd>
            <dt>Wait between alerts</dt><dd>{summary.wait}</dd>
            {summary.settings.map((s) => (<Fragment key={s.label}><dt>{s.label}</dt><dd>{s.text}</dd></Fragment>))}
          </dl>
          {proposal.explanation && <p>{proposal.explanation}</p>}
          {hasProblems(proposal) && (
            <div className="problems" role="alert">
              <strong>This draft needs fixing before it can be saved:</strong>
              <ul>{proposal.problems!.map((p, i) => <li key={i}>{p}</li>)}</ul>
            </div>
          )}
          {preview && <p role="status" className="preview-result">{describePreview(preview)}</p>}
          <div className="actions">
            <button type="button" className="primary" disabled={busy || hasProblems(proposal)} onClick={save}>Looks right — save rule</button>
            <button type="button" onClick={() => onEdit(proposal)}>{hasProblems(proposal) ? "Edit settings" : "Edit settings first"}</button>
          </div>
        </div>
      )}
    </div>
  );
}
