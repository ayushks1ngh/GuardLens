import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { QuietHours } from "../components/QuietHours";
import { SchemaForm, defaultValues } from "../components/SchemaForm";
import type { FieldError, Meta, NotifierRow, NotifierType, Severity, Values } from "../types";

export const SEVERITY_CHOICES: { value: Severity; label: string }[] = [
  { value: "info", label: "Everything (info and above)" },
  { value: "warning", label: "Warnings and critical" },
  { value: "critical", label: "Critical only" },
];

/** Plain-language outcome of a test send. */
export function describeTest(result: { ok: true } | { ok: false; error: string }): string {
  return result.ok
    ? "Test sent. Check the destination to confirm it arrived."
    : `The test did not go through: ${result.error.replace(/^notifier failed:\s*/i, "")}`;
}

interface Draft {
  id?: number; type: string; enabled: boolean; min_severity: Severity;
  config: Values; changeConfig: boolean;
}

export function NotifiersPage(_props: { meta: Meta | null }) {
  const [types, setTypes] = useState<NotifierType[]>([]);
  const [rows, setRows] = useState<NotifierRow[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState("");
  const [results, setResults] = useState<Record<number, string>>({});

  const load = useCallback(async () => {
    const [t, r] = await Promise.all([api<NotifierType[]>("/api/notifiers/types"), api<NotifierRow[]>("/api/notifiers")]);
    setTypes(t); setRows(r);
  }, []);
  useEffect(() => { load().catch((e: Error) => setMessage(e.message)); }, [load]);

  const typeOf = useMemo(() => new Map(types.map((t) => [t.key, t])), [types]);
  const activeType = draft ? typeOf.get(draft.type) : undefined;

  const startNew = (key: string) => {
    setErrors([]); setMessage("");
    setDraft({ type: key, enabled: true, min_severity: "warning", config: defaultValues(typeOf.get(key)?.fields ?? []), changeConfig: true });
  };

  const save = async () => {
    if (!draft) return;
    setErrors([]); setMessage("");
    try {
      if (draft.id) {
        const body: Record<string, unknown> = { enabled: draft.enabled, min_severity: draft.min_severity };
        if (draft.changeConfig) body.config = draft.config;
        await api(`/api/notifiers/${draft.id}`, { method: "PATCH", json: body });
      } else {
        await api("/api/notifiers", { method: "POST", json: { type: draft.type, config: draft.config, enabled: draft.enabled, min_severity: draft.min_severity } });
      }
      setDraft(null); await load();
    } catch (e) {
      if (e instanceof ApiError) { setErrors(e.fields); setMessage(e.message); } else setMessage("Could not save.");
    }
  };

  const toggle = async (row: NotifierRow) => {
    await api(`/api/notifiers/${row.id}`, { method: "PATCH", json: { enabled: !row.enabled } }); await load();
  };
  const remove = async (row: NotifierRow) => {
    if (!window.confirm(`Delete this ${typeOf.get(row.type)?.label ?? row.type} notifier?`)) return;
    await api(`/api/notifiers/${row.id}`, { method: "DELETE" }); await load();
  };
  const test = async (row: NotifierRow) => {
    setResults((r) => ({ ...r, [row.id]: "Sending a test…" }));
    let text: string;
    try { await api(`/api/notifiers/${row.id}/test`, { method: "POST" }); text = describeTest({ ok: true }); }
    catch (e) { text = describeTest({ ok: false, error: e instanceof Error ? e.message : "unknown problem" }); }
    setResults((r) => ({ ...r, [row.id]: text }));
  };

  return (
    <section>
      <header className="page-head">
        <h2>Notifications</h2>
        <label>
          <span className="sr-only">Add a notifier</span>
          <select value="" onChange={(e) => e.target.value && startNew(e.target.value)}>
            <option value="">+ Add a destination…</option>
            {types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </label>
      </header>
      <p className="hint">Notifiers send alerts somewhere outside GuardLens, such as a webhook.</p>

      {draft && activeType && (
        <div className="card">
          <h3>{draft.id ? `Edit ${activeType.label}` : `New ${activeType.label}`}</h3>
          <div className="schema-form">
            <div className="field"><label htmlFor="notifier-severity">Send me</label>
              <select id="notifier-severity" value={draft.min_severity} onChange={(e) => setDraft({ ...draft, min_severity: e.target.value as Severity })}>
                {SEVERITY_CHOICES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select></div>
            <div className="field">
              <label className="switch"><input type="checkbox" role="switch" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />
                <span>{draft.enabled ? "On" : "Off"}</span></label>
            </div>
          </div>
          {draft.id && !draft.changeConfig ? (
            <p><button type="button" onClick={() => setDraft({ ...draft, changeConfig: true, config: defaultValues(activeType.fields) })}>Change connection settings</button>
              <span className="hint block">Saved connection details are hidden for safety. Changing them means entering them again.</span></p>
          ) : (
            <SchemaForm fields={activeType.fields} values={draft.config} errors={errors} onChange={(config) => setDraft({ ...draft, config })} />
          )}
          {message && <p className="error" role="alert">{message}</p>}
          <div className="actions">
            <button type="button" className="primary" onClick={save}>Save</button>
            <button type="button" onClick={() => { setDraft(null); setErrors([]); setMessage(""); }}>Cancel</button>
          </div>
        </div>
      )}

      {!draft && message && <p className="error" role="alert">{message}</p>}
      <ul className="list">
        {rows.map((row) => (
          <li key={row.id} className="row wrap">
            <label className="switch"><input type="checkbox" role="switch" aria-label={`${typeOf.get(row.type)?.label ?? row.type} enabled`} checked={row.enabled} onChange={() => toggle(row)} /></label>
            <div className="grow">
              <strong>{typeOf.get(row.type)?.label ?? row.type}</strong>
              <div className="hint">
                {row.config.endpoint ? `${row.config.endpoint} · ` : ""}
                {SEVERITY_CHOICES.find((s) => s.value === row.min_severity)?.label}
              </div>
              {results[row.id] && <div className="hint" role="status">{results[row.id]}</div>}
            </div>
            <button type="button" onClick={() => test(row)}>Send test</button>
            <button type="button" onClick={() => { setErrors([]); setMessage(""); setDraft({ id: row.id, type: row.type, enabled: row.enabled, min_severity: row.min_severity, config: {}, changeConfig: false }); }}>Edit</button>
            <button type="button" onClick={() => remove(row)}>Delete</button>
          </li>
        ))}
        {!rows.length && <li className="hint">No notifiers yet. Add one above.</li>}
      </ul>
      <QuietHours />
    </section>
  );
}
