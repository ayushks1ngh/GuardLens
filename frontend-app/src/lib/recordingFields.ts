import type { Field, RecordingStatus, Values } from "../types";

/**
 * /api/recording exposes no field schema (its settings come from a plain Pydantic model),
 * so the descriptions are written here. Ranges mirror guardlens/api/recording.py.
 */
export const RECORDING_FIELDS: Field[] = [
  { name: "enabled", type: "boolean", label: "Recording", required: false, default: false,
    help: "Master switch. When off, nothing is saved to disk." },
  { name: "mode", type: "enum", label: "What to record", required: false, default: "event",
    help: "“Only when something happens” saves a clip around each alert.",
    enum: [
      { value: "off", label: "Nothing" },
      { value: "motion", label: "Whenever there is movement" },
      { value: "event", label: "Only when something happens (alerts)" },
      { value: "continuous", label: "Everything, all the time" },
    ] },
  { name: "pre_roll_seconds", type: "number", label: "Include video from before", required: false, default: 5,
    min: 0, max: 60, step: 1, unit: "seconds", widget: "slider", help: "How much video leading up to the trigger is kept." },
  { name: "post_roll_seconds", type: "number", label: "Keep recording after", required: false, default: 10,
    min: 0, max: 300, step: 5, unit: "seconds", widget: "slider", help: "How long to keep recording once the trigger has ended." },
  { name: "max_clip_seconds", type: "number", label: "Longest single clip", required: false, default: 120,
    min: 1, max: 3600, step: 10, unit: "seconds", help: "A clip is cut off at this length." },
  { name: "segment_seconds", type: "number", label: "Split continuous recording every", required: false, default: 300,
    min: 10, max: 3600, step: 10, unit: "seconds", help: "Only used by “Everything, all the time”." },
  { name: "retention_days", type: "integer", label: "Delete recordings older than", required: false, default: 7,
    min: 0, max: 3650, step: 1, unit: "days", help: "Use 0 to keep nothing beyond the current clip." },
  { name: "quota_mb", type: "integer", label: "Disk space limit", required: false, default: 2048,
    min: 1, step: 256, unit: "MB", help: "The oldest clips are removed first when this is exceeded." },
  { name: "codec_preferences", type: "string_list", label: "Video formats to try", required: false, default: ["mp4v", "MJPG"],
    help: "Four-letter codes, tried in order. Leave as is unless clips will not play." },
];

/** Settings with defaults filled in, ready for the full-body PATCH the API expects. */
export function withDefaults(config: Values): Values {
  const out: Values = {};
  for (const f of RECORDING_FIELDS) out[f.name] = config[f.name] ?? f.default;
  return out;
}

export interface StatusSummary { tone: "ok" | "warn" | "off"; headline: string; details: string[] }

export function describeRecording(status: RecordingStatus, cameraName: (id: string) => string = (id) => `Camera ${id}`): StatusSummary {
  const details: string[] = [];
  const active = Object.keys(status.active ?? {});
  const errors = Object.entries(status.errors ?? {});
  if (active.length) details.push(`Recording right now: ${active.map(cameraName).join(", ")}.`);
  for (const [id, err] of errors) details.push(`${cameraName(id)} could not record: ${err}`);
  details.push(`${status.clips} saved file${status.clips === 1 ? "" : "s"} on disk.`);
  if (!status.enabled) return { tone: "off", headline: "Recording is switched off", details };
  if (errors.length) return { tone: "warn", headline: "Recording is on, but there are problems", details };
  return { tone: "ok", headline: active.length ? "Recording is on and capturing video" : "Recording is on and waiting for something to record", details };
}
