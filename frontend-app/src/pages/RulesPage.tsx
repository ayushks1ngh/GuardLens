import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { SchemaForm, defaultValues } from "../components/SchemaForm";
import { RuleAssist, PreviewControl } from "../components/RuleAssist";
import { useSnapshot } from "../lib/snapshot";
import type { Camera, FieldError, Meta, PluginType, RuleRow, Values, ZoneRow } from "../types";

const SEVERITIES = [
  { value: "info", label: "Info" }, { value: "warning", label: "Warning" }, { value: "critical", label: "Critical" },
] as const;

interface Draft {
  id?: number; type: string; name: string; camera_id: number | null; zone_id?: number | null;
  severity: RuleRow["severity"]; cooldown_seconds: number; params: Values;
}

export function RulesPage({ meta }: { meta: Meta | null }) {
  const [types, setTypes] = useState<PluginType[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState("");
  const [zones, setZones] = useState<ZoneRow[]>([]);
  const draftCamera = draft?.camera_id ?? null;
  const snapshot = useSnapshot(draft ? draftCamera : null);
  useEffect(() => {
    if (draftCamera === null) { setZones([]); return; }
    api<ZoneRow[]>(`/api/cameras/${draftCamera}/zones`).then(setZones).catch(() => setZones([]));
  }, [draftCamera]);

  const load = useCallback(async () => {
    const [t, c, r] = await Promise.all([
      api<PluginType[]>("/api/rules/types"), api<Camera[]>("/api/cameras"), api<RuleRow[]>("/api/rules"),
    ]);
    setTypes(t); setCameras(c); setRules(r);
  }, []);
  useEffect(() => { load().catch((e) => setMessage(String(e.message))); }, [load]);

  const typeOf = useMemo(() => new Map(types.map((t) => [t.key, t])), [types]);
  const activeType = draft ? typeOf.get(draft.type) : undefined;
  const cameraName = (id: number | null) => (id === null ? "All cameras" : cameras.find((c) => c.id === id)?.name ?? `Camera ${id}`);

  const startNew = (type: string) => {
    const plugin = typeOf.get(type);
    setErrors([]); setMessage("");
    setDraft({
      type, name: plugin?.label ?? type, camera_id: null, severity: "warning",
      cooldown_seconds: 30, params: defaultValues(plugin?.fields ?? []),
    });
  };

  const save = async () => {
    if (!draft) return;
    setErrors([]); setMessage("");
    const { id, ...body } = draft;
    try {
      if (id) await api(`/api/rules/${id}`, { method: "PATCH", json: { name: body.name, camera_id: body.camera_id, zone_id: body.zone_id ?? null, severity: body.severity, cooldown_seconds: body.cooldown_seconds, params: body.params } });
      else await api("/api/rules", { method: "POST", json: body });
      setDraft(null); await load();
    } catch (e) {
      if (e instanceof ApiError) { setErrors(e.fields); setMessage(e.message); } else setMessage("Could not save the rule");
    }
  };

  const toggle = async (rule: RuleRow) => {
    await api(`/api/rules/${rule.id}`, { method: "PATCH", json: { enabled: !rule.enabled } }); await load();
  };
  const remove = async (rule: RuleRow) => {
    if (!window.confirm(`Delete “${rule.name}”?`)) return;
    await api(`/api/rules/${rule.id}`, { method: "DELETE" }); await load();
  };

  return (
    <section>
      <header className="page-head">
        <h2>Alert rules</h2>
        <label>
          <span className="sr-only">Add a rule</span>
          <select value="" onChange={(e) => e.target.value && startNew(e.target.value)}>
            <option value="">+ Add a rule…</option>
            {types.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}
          </select>
        </label>
      </header>

      <RuleAssist types={types} cameras={cameras} onSaved={() => { void load(); }}
        onEdit={(p) => { setErrors([]); setMessage(""); setDraft({ type: p.type, name: p.name, camera_id: p.camera_id, zone_id: p.zone_id, severity: p.severity, cooldown_seconds: p.cooldown_seconds, params: p.params ?? {} }); }} />

      {draft && activeType && (
        <div className="card">
          <h3>{draft.id ? "Edit rule" : `New rule: ${activeType.label}`}</h3>
          {activeType.description && <p className="hint">{activeType.description}</p>}
          <div className="schema-form">
            <div className="field"><label htmlFor="rule-name">Name</label>
              <input id="rule-name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
            <div className="field"><label htmlFor="rule-camera">Applies to</label>
              <select id="rule-camera" value={draft.camera_id ?? ""} onChange={(e) => setDraft({ ...draft, camera_id: e.target.value ? Number(e.target.value) : null, zone_id: null })}>
                <option value="">All cameras</option>
                {cameras.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select></div>
            {draft.camera_id !== null && (
              <div className="field"><label htmlFor="rule-zone">Watch area</label>
                <select id="rule-zone" value={draft.zone_id ?? ""} onChange={(e) => setDraft({ ...draft, zone_id: e.target.value ? Number(e.target.value) : null })}>
                  <option value="">Whole picture</option>
                  {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
                </select>
                <p className="hint">{zones.length ? "Only this part of the picture triggers the rule." : "No zones drawn for this camera yet. Add them on the Zones page."}</p></div>
            )}
            <div className="field"><label htmlFor="rule-severity">How serious</label>
              <select id="rule-severity" value={draft.severity} onChange={(e) => setDraft({ ...draft, severity: e.target.value as Draft["severity"] })}>
                {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select></div>
            <div className="field"><label htmlFor="rule-cooldown">Wait between alerts</label>
              <div className="slider"><input id="rule-cooldown" type="range" min={0} max={600} step={5} value={draft.cooldown_seconds}
                onChange={(e) => setDraft({ ...draft, cooldown_seconds: Number(e.target.value) })} />
                <output>{draft.cooldown_seconds}<span className="unit">seconds</span></output></div>
              <p className="hint">After an alert, stay quiet this long to avoid floods.</p></div>
          </div>
          <SchemaForm fields={activeType.fields} values={draft.params} errors={errors}
            objectClasses={meta?.object_classes} background={snapshot.url} onChange={(params) => setDraft({ ...draft, params })} />
          <PreviewControl draft={draft} />
          {message && <p className="error" role="alert">{message}</p>}
          <div className="actions">
            <button type="button" className="primary" onClick={save}>Save rule</button>
            <button type="button" onClick={() => { setDraft(null); setErrors([]); setMessage(""); }}>Cancel</button>
          </div>
        </div>
      )}

      {!draft && message && <p className="error" role="alert">{message}</p>}
      <ul className="list">
        {rules.map((rule) => (
          <li key={rule.id} className="row">
            <label className="switch"><input type="checkbox" role="switch" aria-label={`${rule.name} enabled`} checked={rule.enabled} onChange={() => toggle(rule)} /></label>
            <div className="grow">
              <strong>{rule.name}</strong>
              <div className="hint">{typeOf.get(rule.type)?.label ?? rule.type} · {cameraName(rule.camera_id)}</div>
            </div>
            <span className={`badge ${rule.severity}`}>{rule.severity}</span>
            <button type="button" onClick={() => { setErrors([]); setMessage(""); setDraft({ ...rule }); }}>Edit</button>
            <button type="button" onClick={() => remove(rule)}>Delete</button>
          </li>
        ))}
        {!rules.length && <li className="hint">No rules yet. Add one above.</li>}
      </ul>
    </section>
  );
}
