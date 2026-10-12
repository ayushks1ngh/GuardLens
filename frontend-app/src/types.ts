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

// --- Zones / Faces / Notifiers / Recording / Reports (M1c) ---
export interface ZoneRow { id: number; camera_id: number; name: string; polygon: [number, number][] }

export interface PersonRow { id: number; name: string; watchlist: boolean; notes?: string | null; image_count: number }
export type FacePolicy = "label_only" | "alert_unknown" | "alert_watchlist";

export type Severity = "info" | "warning" | "critical";
export interface NotifierRow {
  id: number; type: string; enabled: boolean; min_severity: Severity;
  config: { endpoint?: string | null; configured_keys?: string[] };
}
export interface NotifierType { key: string; label: string; fields: Field[] }

export interface RecordingStatus {
  enabled: boolean; mode: string; active: Record<string, string>; errors: Record<string, string>; clips: number;
}
export interface RecordingResponse { config: Values; status: RecordingStatus }

export interface ReportRow { id: number; date: string; generated_at: string; generator: string; content: Values; text: string }
export interface ActivityRow { id: number; camera_id: number; timestamp: string; summary: Values }
export interface TimelinePoint { bucket: string; count: number }
export interface CameraCount { camera_id: number; count: number }
export interface AnalyticsSummary {
  total: number; by_type: Record<string, number>; by_severity: Record<string, number>; by_status: Record<string, number>;
}

/* ---- M1c: Live / Events / Cameras ---- */
export interface CameraRuntime {
  connected: boolean; fps: number; running: boolean; source_type?: string;
  last_frame_age: number | null; error: string | null;
}
export interface CameraFull extends Camera {
  source_config?: Record<string, unknown>; analyze_fps?: number | null; status?: CameraRuntime;
}

export type Severity = "info" | "warning" | "critical";
export type EventStatus = "new" | "acknowledged" | "resolved";

export interface EventNote { id: number; event_id: number; text: string; created_at: string }
export interface EventRow {
  id: number; type: string; severity: Severity | string; status: EventStatus | string; camera_id: number;
  snapshot_path?: string | null; clip_path?: string | null;
  event_metadata?: Record<string, unknown>; created_at: string;
  acknowledged_at?: string | null; resolved_at?: string | null; notes?: EventNote[];
}
export interface EventPage { items: EventRow[]; total: number; limit: number; offset: number }

export interface OverlayBox { class: string; conf: number; bbox: [number, number, number, number]; track_id?: number | null }
export interface OverlayInfo {
  counts?: Record<string, number>; boxes?: OverlayBox[]; alert?: boolean; connected?: boolean; fps?: number;
}
