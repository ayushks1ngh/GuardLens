import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { SchemaForm } from "../components/SchemaForm";
import {
  PROVIDER_ENV, budgetText, canRunNow, formatDuration, providerState, runDetailText, runResultText, runStatusWord,
  settingsFields, statusLine, toggleCamera, type AgentInfo, type AgentRunRow, type AiStatus,
} from "../lib/agentsLogic";
import { timeAgo } from "../lib/eventLogic";
import type { Camera, FieldError, Meta, Values } from "../types";

function AiCard() {
  const [ai, setAi] = useState<AiStatus | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api<AiStatus>("/api/agents/ai").then(setAi).catch(() => setError("Could not check the AI connection.")); }, []);
  return (
    <section className="card" aria-labelledby="ai-heading">
      <h3 id="ai-heading">AI connection</h3>
      {error && <p className="error" role="alert">{error}</p>}
      {ai && (
        <>
          <p>{ai.available ? "At least one AI service is ready." : "No AI service is connected yet, so agents that need AI are waiting."}</p>
          <ul className="list">
            {ai.providers.map((p) => (
              <li key={p.name} className="row">
                <div className="grow">
                  <strong>{p.label}</strong>
                  <p className="hint">
                    {providerState(p)}
                    {!p.configured && PROVIDER_ENV[p.name] && <> · set <code>{PROVIDER_ENV[p.name]}</code> on the server</>}
                    {p.configured && <> · model {p.model}</>}
                  </p>
                </div>
                <span className={`badge ${p.configured && !p.paused ? "info" : "warning"}`}>{p.configured ? (p.paused ? "paused" : "ready") : "off"}</span>
              </li>
            ))}
          </ul>
          <p className="hint">{budgetText(ai.budget)}</p>
        </>
      )}
      <p className="hint">
        Keys are set in the server’s environment (for example <code>GUARDLENS_NVIDIA_API_KEY</code>, <code>GUARDLENS_GEMINI_API_KEY</code> or{" "}
        <code>GUARDLENS_OPENROUTER_API_KEY</code>), then restart GuardLens. They are never entered or shown here. Free tiers can be busy, so GuardLens
        tries the next service automatically.
      </p>
    </section>
  );
}

function PrivacyCard() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [ids, setIds] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api<Camera[]>("/api/cameras").then(setCameras).catch(() => setError("Could not load cameras."));
    api<{ local_only_cameras: number[] }>("/api/privacy").then((p) => setIds(p.local_only_cameras)).catch(() => setError("Could not load privacy settings."));
  }, []);
  const change = async (id: number, localOnly: boolean) => {
    const next = toggleCamera(ids, id, localOnly);
    setError(""); setSaved(false);
    try {
      const res = await api<{ local_only_cameras: number[] }>("/api/privacy", { method: "PUT", json: { local_only_cameras: next } });
      setIds(res.local_only_cameras); setSaved(true);
    } catch (e) { setError(e instanceof ApiError ? e.message : "Could not save. Please try again."); }
  };
  return (
    <section className="card" aria-labelledby="privacy-heading">
      <h3 id="privacy-heading">Privacy</h3>
      <p className="hint">Leaving the device means a picture from the camera is sent over the internet to an outside AI company so it can describe it.</p>
      {!cameras.length && <p className="hint">No cameras yet.</p>}
      <ul className="list">
        {cameras.map((c) => (
          <li key={c.id} className="row">
            <strong className="grow">{c.name}</strong>
            <label className="switch">
              <input type="checkbox" role="switch" checked={ids.includes(c.id)} onChange={(e) => change(c.id, e.target.checked)}
                aria-label={`Keep ${c.name} video on this device (never send to cloud AI)`} />
              <span>Keep this camera’s video on this device (never send to cloud AI)</span>
            </label>
          </li>
        ))}
      </ul>
      {saved && <p className="ok-text" role="status">Saved.</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}

function Activity({ agentKey, refreshKey }: { agentKey: string; refreshKey: number }) {
  const [runs, setRuns] = useState<AgentRunRow[] | null>(null);
  useEffect(() => {
    api<AgentRunRow[]>(`/api/agents/runs?agent=${encodeURIComponent(agentKey)}&limit=8`).then(setRuns).catch(() => setRuns([]));
  }, [agentKey, refreshKey]);
  return (
    <div className="agent-activity">
      <h4>Recent activity</h4>
      {runs === null ? <p className="hint">Loading…</p> : !runs.length ? <p className="hint">Nothing yet.</p> : (
        <ul className="list">
          {runs.map((r) => (
            <li key={r.id} className="hint">
              {timeAgo(r.started_at)} · <strong>{runStatusWord(r.status)}</strong> · {formatDuration(r.duration_ms)}
              {runDetailText(r) && <> · {runDetailText(r)}</>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface FeedbackSummary { judged: number; real: number; false_alarms: number; with_ai_notes: number; needed_real: number; evaluation: { safe_to_enable_suppression: boolean; missed_real_rate: number | null } }

export function feedbackText(f: FeedbackSummary): string {
  if (f.real < f.needed_real) {
    return `You have judged ${f.judged} alerts (${f.real} real, ${f.false_alarms} false alarms). Judge at least ${f.needed_real} real ones on the Events page (“Real alert” / “False alarm”) before the AI is allowed to hide anything.`;
  }
  const missed = f.evaluation.missed_real_rate;
  return f.evaluation.safe_to_enable_suppression
    ? "Enough alerts judged, and the AI would have hidden almost no real alert."
    : `Enough alerts judged, but the AI would have hidden ${missed === null ? "some" : `${Math.round(missed * 100)}% of`} real alerts, so hiding stays off.`;
}

function JudgedProgress() {
  const [f, setF] = useState<FeedbackSummary | null>(null);
  useEffect(() => { api<FeedbackSummary>("/api/events/feedback/summary").then(setF).catch(() => undefined); }, []);
  if (!f) return null;
  return <p className="hint" role="status">{feedbackText(f)}</p>;
}

function AgentCard({ agent, onUpdated }: { agent: AgentInfo; onUpdated: (a: AgentInfo) => void }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Values>(agent.config);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [runText, setRunText] = useState("");
  const [refresh, setRefresh] = useState(0);
  const enabled = Boolean(agent.config.enabled);

  const save = async (config: Values, success: string) => {
    setBusy(true); setErrors([]); setMessage("");
    try {
      const res = await api<{ config: Values; status: AgentInfo["status"] }>(`/api/agents/${agent.key}`, { method: "PUT", json: { config } });
      onUpdated({ ...agent, config: res.config, status: res.status });
      setValues(res.config); setMessage(success);
    } catch (e) {
      if (e instanceof ApiError) { setErrors(e.fields); setMessage(e.fields.length ? "Please fix the highlighted settings." : e.message); }
      else setMessage("Could not save. Please try again.");
    }
    setBusy(false);
  };
  const run = async () => {
    setBusy(true); setRunText("Running…");
    try {
      setRunText(runResultText(await api(`/api/agents/${agent.key}/run`, { method: "POST", json: {} })));
    } catch (e) { setRunText(e instanceof ApiError ? e.message : "Could not start it. Please try again."); }
    setRefresh((n) => n + 1); setBusy(false);
  };
  const panel = `agent-${agent.key}-settings`;
  return (
    <section className="card agent-card" aria-labelledby={`agent-${agent.key}-title`}>
      <div className="row-inline between">
        <h3 id={`agent-${agent.key}-title`}>{agent.label}</h3>
        <label className="switch">
          <input type="checkbox" role="switch" checked={enabled} disabled={busy} aria-label={`Turn on ${agent.label}`}
            onChange={(e) => save({ enabled: e.target.checked }, e.target.checked ? "Turned on." : "Turned off.")} />
          <span>{enabled ? "On" : "Off"}</span>
        </label>
      </div>
      <p>{agent.description}</p>
      <p className="hint" aria-live="polite">{statusLine(agent.status, enabled)}</p>
      <div className="actions wrap">
        <button type="button" aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}>{open ? "Hide settings" : "Settings"}</button>
        {canRunNow(agent.triggers) && <button type="button" disabled={busy} onClick={run}>Run now</button>}
      </div>
      {runText && <p className="hint" role="status">{runText}</p>}
      {open && (
        <div id={panel} className="agent-settings">
          <SchemaForm fields={settingsFields(agent.fields)} values={values} onChange={setValues} errors={errors} />
          <button type="button" className="primary" disabled={busy} onClick={() => save(values, "Settings saved.")}>Save</button>
        </div>
      )}
      {message && <p className={errors.length ? "error" : "ok-text"} role="status">{message}</p>}
      {agent.key === "event_triage" && <JudgedProgress />}
      <Activity agentKey={agent.key} refreshKey={refresh} />
    </section>
  );
}

export function AgentsPage({ meta: _meta }: { meta: Meta | null }) {
  const [agents, setAgents] = useState<AgentInfo[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<AgentInfo[]>("/api/agents").then(setAgents).catch(() => setError("Could not load agents."));
  }, []);
  useEffect(load, [load]);
  return (
    <section className="agents-page">
      <div className="page-head"><h2>Agents</h2></div>
      <p className="hint">Agents are helpers that look at your alerts and write short notes. For now they only suggest; they never change anything on their own.</p>
      <AiCard />
      <PrivacyCard />
      {error && <p className="error" role="alert">{error}</p>}
      {agents === null && !error && <p className="hint">Loading…</p>}
      {agents?.map((a) => (
        <AgentCard key={a.key} agent={a} onUpdated={(u) => setAgents((list) => (list ?? []).map((x) => (x.key === u.key ? u : x)))} />
      ))}
    </section>
  );
}
