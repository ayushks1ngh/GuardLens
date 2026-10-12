import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { SchemaForm } from "./SchemaForm";
import type { Field, FieldError, Values } from "../types";

export function QuietHours() {
  const [fields, setFields] = useState<Field[]>([]);
  const [values, setValues] = useState<Values>({});
  const [errors, setErrors] = useState<FieldError[]>([]);
  const [message, setMessage] = useState("");
  const [ok, setOk] = useState(false);
  useEffect(() => {
    api<{ fields: Field[]; values: Values }>("/api/notifiers/routing")
      .then((r) => { setFields(r.fields); setValues(r.values); })
      .catch(() => setMessage("Could not load quiet hours."));
  }, []);
  const save = async () => {
    setErrors([]); setMessage(""); setOk(false);
    try { const r = await api<{ values: Values }>("/api/notifiers/routing", { method: "PUT", json: { values } }); setValues(r.values); setOk(true); }
    catch (e) { if (e instanceof ApiError) { setErrors(e.fields); setMessage(e.message); } else setMessage("Could not save."); }
  };
  return (
    <div className="card quiet-hours">
      <h3>Quiet hours</h3>
      <p className="hint">Choose when GuardLens should hold back less urgent notifications.</p>
      {fields.length > 0 && <SchemaForm fields={fields} values={values} errors={errors} onChange={(v) => { setValues(v); setOk(false); }} />}
      {message && <p className="error" role="alert">{message}</p>}
      {ok && <p role="status" className="hint">Saved.</p>}
      {fields.length > 0 && <div className="actions"><button type="button" className="primary" onClick={save}>Save quiet hours</button></div>}
    </div>
  );
}
