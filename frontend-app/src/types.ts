/** Canonical field description produced by the backend (guardlens/schema.py). */
export type FieldType =
  | "boolean" | "integer" | "number" | "string" | "url" | "time" | "enum"
  | "string_list" | "points" | "point" | "object" | "any";

export interface EnumChoice { value: string | number; label: string }

export interface Field {
  name: string;
  type: FieldType;
  label: string;
  help: string;
  required: boolean;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  placeholder?: string;
  enum?: EnumChoice[];
  widget?: string;
}

export type Values = Record<string, unknown>;

export interface PluginType { key: string; label: string; description?: string; fields: Field[] }

export interface Camera { id: number; name: string; enabled: boolean; source_type?: string }

export interface RuleRow {
  id: number; type: string; name: string; camera_id: number | null; zone_id: number | null;
  severity: "info" | "warning" | "critical"; cooldown_seconds: number;
  params: Values; enabled: boolean;
}

export interface Meta {
  name: string; version: string; object_classes: string[];
  capabilities: Record<string, boolean>;
  plugins: { detectors: string[]; rules: string[]; notifiers: string[] };
}

export interface FieldError { field: string; message: string }
