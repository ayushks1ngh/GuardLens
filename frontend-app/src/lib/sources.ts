import type { Field, Values } from "../types";

/** Shape returned by GET /api/cameras/source-types (a different vocabulary from the plugin Field schema). */
export interface SourceModeField {
  key: string; label: string; type?: string; default?: unknown; required?: boolean; options?: string[];
}
export interface SourceMode { key: string; label: string; fields: SourceModeField[] }
export interface SourceType { key: string; label: string; modes: SourceMode[] }
export interface LocalDevice { index: number; path: string; label: string }

export interface SourceChoice {
  id: string; sourceType: string; mode: string; title: string; description: string; fields: Field[]; pairing: boolean;
}

const FRIENDLY: Record<string, { title: string; description: string }> = {
  "opencv:device": { title: "This computer’s camera", description: "A webcam or capture card plugged into the GuardLens computer." },
  "opencv:network": { title: "IP camera or phone app", description: "An RTSP, HTTP or MJPEG address from a network camera." },
  "opencv:file": { title: "Video file", description: "A recorded video or the bundled sample, handy for testing." },
  "webrtc:publisher": { title: "Phone or laptop browser", description: "Open a secure link on the other device and share its camera." },
};

const PRIMARY = new Set(["device_index", "url", "path"]);

/** Convert a source-types field into the SchemaForm Field vocabulary. */
export function toField(raw: SourceModeField): Field {
  const base = { name: raw.key, label: raw.label, help: "", required: Boolean(raw.required), default: raw.default };
  if (raw.options?.length) return { ...base, type: "enum", enum: raw.options.map((o) => ({ value: o, label: o })) };
  switch (raw.type) {
    case "integer": return { ...base, type: "integer" };
    case "number": return { ...base, type: "number" };
    case "boolean": return { ...base, type: "boolean" };
    case "url": return { ...base, type: "url" };
    default: return { ...base, type: "string" };
  }
}

export function buildChoices(types: SourceType[]): SourceChoice[] {
  return types.flatMap((t) => t.modes.map((m): SourceChoice => {
    const id = `${t.key}:${m.key}`;
    const friendly = FRIENDLY[id];
    return {
      id, sourceType: t.key, mode: m.key,
      title: friendly?.title ?? m.label, description: friendly?.description ?? t.label,
      fields: m.fields.map(toField), pairing: t.key === "webrtc",
    };
  }));
}

/** Put the camera-chooser dropdown in place of the bare device index when the host lists devices. */
export function withDevices(fields: Field[], devices: LocalDevice[]): Field[] {
  if (!devices.length) return fields;
  return fields.map((f) => f.name === "device_index"
    ? { ...f, type: "enum", enum: devices.map((d) => ({ value: d.index, label: `${d.label} (camera ${d.index})` })), default: devices[0].index }
    : f);
}

export const primaryFields = (fields: Field[]): Field[] => fields.filter((f) => f.required || PRIMARY.has(f.name));
export const advancedFields = (fields: Field[]): Field[] => fields.filter((f) => !(f.required || PRIMARY.has(f.name)));

export function missingRequired(fields: Field[], values: Values): string[] {
  return fields.filter((f) => f.required && (values[f.name] === undefined || values[f.name] === null || String(values[f.name]).trim() === ""))
    .map((f) => f.label);
}

export interface Pairing { stream_id: string }

export function buildSourcePayload(choice: SourceChoice, values: Values, pairing?: Pairing | null): { source_type: string; source_config: Values } {
  const config: Values = { mode: choice.mode };
  if (choice.pairing) {
    if (pairing) config.stream_id = pairing.stream_id;
    return { source_type: choice.sourceType, source_config: config };
  }
  for (const f of choice.fields) {
    const v = values[f.name] ?? f.default;
    if (v === undefined || v === null || (typeof v === "string" && v.trim() === "")) continue;
    config[f.name] = typeof v === "string" ? v.trim() : v;
  }
  return { source_type: choice.sourceType, source_config: config };
}

export const fingerprint = (payload: unknown): string => JSON.stringify(payload);

export interface WizardInput {
  choice: SourceChoice | null; values: Values; pairing: Pairing | null; probedFingerprint: string | null; name: string;
}
export interface WizardState {
  canTest: boolean; canAdd: boolean; missing: string[]; stale: boolean; hint: string;
}

/**
 * Wizard rules: a source must pass a one-frame test before it can be saved, and editing the
 * source afterwards invalidates that test. Browser pairing has nothing to probe; creating the
 * link is the readiness signal.
 */
export function wizardState({ choice, values, pairing, probedFingerprint, name }: WizardInput): WizardState {
  if (!choice) return { canTest: false, canAdd: false, missing: [], stale: false, hint: "Choose where the video comes from." };
  const missing = choice.pairing ? [] : missingRequired(choice.fields, values);
  const nameOk = name.trim().length > 0;
  if (choice.pairing) {
    const ready = pairing !== null;
    return { canTest: false, canAdd: ready && nameOk, missing, stale: false,
      hint: !ready ? "Create the secure link first." : !nameOk ? "Give the camera a name." : "Ready to add." };
  }
  const current = fingerprint(buildSourcePayload(choice, values));
  const tested = probedFingerprint !== null;
  const stale = tested && probedFingerprint !== current;
  const canAdd = tested && !stale && nameOk && missing.length === 0;
  const hint = missing.length ? `Fill in: ${missing.join(", ")}.`
    : !tested ? "Test the connection to see a live check of this source."
    : stale ? "You changed the source. Test the connection again."
    : !nameOk ? "Give the camera a name." : "Ready to add.";
  return { canTest: missing.length === 0, canAdd, missing, stale, hint };
}
