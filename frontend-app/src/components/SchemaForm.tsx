import { useState } from "react";
import type { Field, FieldError, Values } from "../types";
import { PointsCanvas, type Point } from "./PointsCanvas";

interface Props {
  fields: Field[];
  values: Values;
  onChange: (values: Values) => void;
  errors?: FieldError[];
  /** Vocabulary for class_picker widgets (from /api/meta). */
  objectClasses?: string[];
  /** Snapshot shown behind point/line widgets. */
  background?: string;
}

/** Initial values from field defaults, so a new plugin form starts sensible. */
export function defaultValues(fields: Field[]): Values {
  const out: Values = {};
  for (const field of fields) if (field.default !== undefined) out[field.name] = field.default;
  return out;
}

function ChipList({ value, onChange, suggestions, id }: {
  value: string[]; onChange: (v: string[]) => void; suggestions?: string[]; id: string;
}) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const item = raw.trim();
    if (item && !value.includes(item)) onChange([...value, item]);
    setDraft("");
  };
  return (
    <div className="chips">
      {value.map((item) => (
        <span key={item} className="chip">
          {item}
          <button type="button" aria-label={`Remove ${item}`} onClick={() => onChange(value.filter((v) => v !== item))}>×</button>
        </span>
      ))}
      <input
        id={id}
        list={suggestions ? `${id}-options` : undefined}
        value={draft}
        placeholder="Add…"
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); } }}
        onBlur={() => add(draft)}
      />
      {suggestions && (
        <datalist id={`${id}-options`}>
          {suggestions.filter((s) => !value.includes(s)).map((s) => <option key={s} value={s} />)}
        </datalist>
      )}
    </div>
  );
}

function KeyValue({ value, onChange }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void }) {
  const rows = Object.entries(value);
  return (
    <div className="kv">
      {rows.map(([key, val], index) => (
        <div key={index} className="kv-row">
          <input aria-label="Name" value={key} onChange={(e) => {
            const next = rows.map(([k, v], i): [string, string] => (i === index ? [e.target.value, v] : [k, v]));
            onChange(Object.fromEntries(next));
          }} />
          <input aria-label="Value" value={val} onChange={(e) => onChange({ ...value, [key]: e.target.value })} />
          <button type="button" aria-label="Remove" onClick={() => { const { [key]: _drop, ...rest } = value; void _drop; onChange(rest); }}>×</button>
        </div>
      ))}
      <button type="button" onClick={() => onChange({ ...value, "": "" })}>Add</button>
    </div>
  );
}

function Control({ field, value, set, objectClasses, background, id }: {
  field: Field; value: unknown; set: (v: unknown) => void; objectClasses?: string[]; background?: string; id: string;
}) {
  const effective = value ?? field.default;
  switch (field.type) {
    case "boolean":
      return (
        <label className="switch">
          <input id={id} type="checkbox" role="switch" checked={Boolean(effective)} onChange={(e) => set(e.target.checked)} />
          <span>{effective ? "On" : "Off"}</span>
        </label>
      );
    case "number":
    case "integer": {
      const step = field.step ?? (field.type === "integer" ? 1 : 0.1);
      const parse = (raw: string) => (raw === "" ? undefined : field.type === "integer" ? parseInt(raw, 10) : parseFloat(raw));
      const unit = field.unit ? <span className="unit">{field.unit}</span> : null;
      if (field.widget === "slider" && field.min !== undefined && field.max !== undefined) {
        return (
          <div className="slider">
            <input id={id} type="range" min={field.min} max={field.max} step={step}
              value={Number(effective ?? field.min)} onChange={(e) => set(parse(e.target.value))} />
            <output>{String(effective ?? field.min)}{unit}</output>
          </div>
        );
      }
      return (
        <div className="number">
          <input id={id} type="number" min={field.min} max={field.max} step={step}
            value={effective === undefined || effective === null ? "" : String(effective)}
            onChange={(e) => set(parse(e.target.value))} />
          {unit}
        </div>
      );
    }
    case "enum":
      return (
        <select id={id} value={String(effective ?? "")} onChange={(e) => {
          const choice = field.enum?.find((c) => String(c.value) === e.target.value);
          set(choice ? choice.value : e.target.value);
        }}>
          {effective === undefined && <option value="">Choose…</option>}
          {field.enum?.map((c) => <option key={String(c.value)} value={String(c.value)}>{c.label}</option>)}
        </select>
      );
    case "time":
      return <input id={id} type="time" value={String(effective ?? "")} onChange={(e) => set(e.target.value)} />;
    case "string_list":
      return (
        <ChipList id={id} value={(effective as string[] | undefined) ?? []} onChange={set}
          suggestions={field.widget === "class_picker" ? objectClasses : undefined} />
      );
    case "points":
      return (
        <PointsCanvas background={background} points={(effective as Point[] | undefined) ?? []} onChange={set}
          maxPoints={field.widget === "line_draw" ? 2 : undefined} closed={field.widget === "polygon_draw"} />
      );
    case "point":
      return (
        <PointsCanvas background={background} maxPoints={1}
          points={effective ? [effective as Point] : []} onChange={(p) => set(p[0])} />
      );
    case "object":
      return <KeyValue value={(effective as Record<string, string> | undefined) ?? {}} onChange={set} />;
    default:
      return (
        <input id={id} type={field.widget === "secret" ? "password" : field.type === "url" ? "url" : "text"}
          value={String(effective ?? "")} placeholder={field.placeholder}
          autoComplete={field.widget === "secret" ? "new-password" : undefined}
          onChange={(e) => set(e.target.value)} />
      );
  }
}

/** Renders any plugin's settings from its field schema. No plugin-specific code lives here. */
export function SchemaForm({ fields, values, onChange, errors = [], objectClasses, background }: Props) {
  const byField = new Map(errors.map((e) => [e.field, e.message]));
  return (
    <div className="schema-form">
      {fields.map((field) => {
        const id = `field-${field.name}`;
        const error = byField.get(field.name);
        return (
          <div key={field.name} className={`field${error ? " has-error" : ""}`}>
            <label htmlFor={id}>{field.label}{field.required && <span aria-hidden> *</span>}</label>
            <Control id={id} field={field} value={values[field.name]} objectClasses={objectClasses} background={background}
              set={(v) => {
                const next = { ...values };
                if (v === undefined) delete next[field.name]; else next[field.name] = v;
                onChange(next);
              }} />
            {field.help && <p className="hint">{field.help}</p>}
            {error && <p className="error" role="alert">{error}</p>}
          </div>
        );
      })}
    </div>
  );
}
