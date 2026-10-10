# 03 — Data Model

Backing store: **SQLite** via **SQLModel** (SQLAlchemy under the hood). The schema
is written to be Postgres-compatible so the only change needed to scale up is the
connection URL. All timestamps are stored in UTC.

## Entity overview

```
Camera 1───* Zone
Camera 1───* Rule        (a rule may also be global / camera-less)
Camera 1───* Event
Camera 1───* ActivityLog
Rule   1───* Event
Zone   1───* Rule        (optional: a rule may reference a zone)
Person 1───* FaceImage
Person 1───* Event       (optional: event may reference a recognized person)
Event  1───* EventNote
Report (per date; derived from ActivityLog + Event)
```

## Tables

### `camera`
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| name | str | human label |
| source | str | backward-compatible display/open value (`"0"`, URL, or file path) |
| source_type | str | adapter registry key; `opencv` in Phase A |
| source_config | JSON | typed adapter config: mode plus device index, URL, path, timeouts, etc. |
| enabled | bool | default true |
| analyze_fps | float | per-camera override, nullable |
| created_at | datetime | |
| updated_at | datetime | |

### `zone`
A polygon region on a camera, used by rules.
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| camera_id | int FK → camera | |
| name | str | |
| polygon | JSON | list of `[x, y]` points in normalized (0–1) coords |
| created_at | datetime | |

> Normalized coordinates keep zones valid regardless of stream resolution.

### `rule`
A configured alert rule instance.
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| type | str | plugin key: `zone_intrusion`, `loitering`, `line_crossing`, `crowd`, `object_class`, `unknown_face`, … |
| name | str | |
| camera_id | int FK → camera, nullable | null = applies to all cameras |
| zone_id | int FK → zone, nullable | for zone-scoped rules |
| enabled | bool | |
| severity | str | `info` / `warning` / `critical` |
| cooldown_seconds | float | min gap between events from this rule |
| params | JSON | rule-specific config (e.g., `{ "seconds": 10 }`, `{ "max_count": 5 }`, `{ "line": [[x1,y1],[x2,y2]], "direction": "in" }`, `{ "classes": ["knife"] }`, `{ "policy": "unknown" }`) |
| created_at | datetime | |

> Making `params` a JSON blob is what lets **new rule types be added without schema
> migrations**. The core only needs `type` + `params`.

### `event`
A recorded alert.
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| type | str | mirrors rule type / detector that fired |
| severity | str | `info` / `warning` / `critical` |
| status | str | `new` / `acknowledged` / `resolved` |
| camera_id | int FK → camera | |
| rule_id | int FK → rule, nullable | |
| person_id | int FK → person, nullable | set for face events |
| snapshot_path | str | JPEG evidence path |
| clip_path | str, nullable | optional short clip |
| metadata | JSON | bbox, track_id, counts, confidence, etc. |
| created_at | datetime | indexed |
| acknowledged_at | datetime, nullable | |
| resolved_at | datetime, nullable | |

Indexes: `(camera_id, created_at)`, `(type)`, `(status)`, `(severity)`.

### `event_note`
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| event_id | int FK → event | |
| text | str | |
| created_at | datetime | |

### `person` (face enrollment)
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| name | str | |
| watchlist | bool | if true, recognition of this person can trigger an alert |
| notes | str, nullable | |
| created_at | datetime | |

### `face_image`
Enrolled face sample + its embedding.
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| person_id | int FK → person | |
| image_path | str | stored sample image |
| embedding | BLOB/JSON | face embedding vector |
| created_at | datetime | |

> Embeddings are also cached in memory at startup for fast live comparison.

### `notifier_config`
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| type | str | `webhook`, `email`, … |
| enabled | bool | |
| config | JSON | e.g. `{ "url": "https://…" }` (secrets referenced via env where possible) |
| min_severity | str | only notify at/above this severity |
| created_at | datetime | |

### `setting` (key/value)
Flexible app settings that shouldn't need a migration.
| Column | Type | Notes |
|--------|------|-------|
| key | str PK | |
| value | JSON | |

### `activity_log`
Periodic per-camera scene summary (the continuous record used for daily reports).
Written by the activity sampler at a configurable interval, independent of alerts.
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| camera_id | int FK → camera | |
| timestamp | datetime | indexed |
| summary | JSON | e.g. `{ "people": 2, "animals": {"dog": 1}, "vehicles": 0, "known": ["Ayush"], "unknown_faces": 1, "zones_active": [3] }` |

Index: `(camera_id, timestamp)`, `(timestamp)`.

> `summary` is a JSON blob so new counted categories (new detector outputs) need
> **no schema change** — the report generator just reads whatever keys exist.

### `report`
A generated daily report (cached so it isn't recomputed each view).
| Column | Type | Notes |
|--------|------|-------|
| id | int PK | |
| date | date | the day covered; unique |
| generated_at | datetime | |
| generator | str | which `ReportGenerator` produced it (e.g. `structured`, `vlm`) |
| content | JSON | structured sections (highlights, per-camera, timeline, stats) |
| text | str | rendered human-readable briefing |

## Design notes

- **JSON `params`/`metadata`/`config` columns** are the main flexibility lever:
  new rule types, detector outputs, and notifier settings need **no schema change**.
- **Normalized polygon/line coords** make zones resolution-independent.
- **Status + timestamps** on events implement the triage workflow and analytics.
- Evidence (images/clips) lives on disk under `data/`; the DB stores paths only.
