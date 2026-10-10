# 04 — API Specification

All REST endpoints are JSON unless noted. Base path: `/api`. Live video uses MJPEG;
live events use SSE (with a WebSocket fallback). This is a v1 contract and is
expected to grow; additive changes only within a major version.

## Conventions

- Timestamps: ISO-8601 UTC.
- Errors: `{ "error": { "code": str, "message": str } }` with appropriate HTTP status.
- Pagination: `?limit=&offset=`; responses include `{ items, total, limit, offset }`.
- All write endpoints validate input via Pydantic/SQLModel schemas.

## Health & meta

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + per-camera status + model/device info |
| GET | `/api/config` | Non-secret runtime config (analyze-fps, enabled plugins) |

## Cameras

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cameras` | List cameras + live status (connected, fps) |
| POST | `/api/cameras` | Add camera `{ name, source, analyze_fps? }` |
| GET | `/api/cameras/{id}` | Get one camera |
| PATCH | `/api/cameras/{id}` | Update `{ name?, source?, enabled?, analyze_fps? }` |
| DELETE | `/api/cameras/{id}` | Remove camera (stops its worker) |

## Live video & events (streaming)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/stream/{camera_id}/mjpeg` | MJPEG stream for `<img src>` (the video); optional `?max_frames=1..10` bounds diagnostics/tests |
| GET | `/api/stream/{camera_id}/overlay` (SSE) | Lightweight per-frame metadata: alert flag, counts, track boxes |
| GET | `/api/events/stream` (SSE) | Global live feed of new events |
| GET | `/ws/overlay` (WS, fallback) | Same metadata over WebSocket if SSE unavailable |

> Rationale: the heavy pixels go over cheap MJPEG; only small JSON overlays go over
> SSE/WS. This replaces the original base64-per-frame-over-WS design.

## Zones

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/cameras/{id}/zones` | List zones for a camera |
| POST | `/api/cameras/{id}/zones` | Create `{ name, polygon:[[x,y],…] }` (normalized 0–1) |
| PATCH | `/api/zones/{id}` | Update name/polygon |
| DELETE | `/api/zones/{id}` | Delete zone |

## Rules

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/rules/types` | List available rule plugin types + their param schema |
| GET | `/api/rules` | List configured rules (filter `?camera_id=`) |
| POST | `/api/rules` | Create `{ type, name, camera_id?, zone_id?, severity, cooldown_seconds, params }` |
| PATCH | `/api/rules/{id}` | Update any field incl. `enabled`, `params` |
| DELETE | `/api/rules/{id}` | Delete rule |

Example create (loitering):
```json
{
  "type": "loitering",
  "name": "Lobby loitering > 10s",
  "camera_id": 1,
  "zone_id": 3,
  "severity": "warning",
  "cooldown_seconds": 30,
  "params": { "seconds": 10 }
}
```

## Events (history + workflow)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/events` | List/filter: `?camera_id=&type=&severity=&status=&from=&to=&limit=&offset=` |
| GET | `/api/events/{id}` | Event detail (+ notes) |
| POST | `/api/events/{id}/acknowledge` | Set status `acknowledged` |
| POST | `/api/events/{id}/resolve` | Set status `resolved` `{ note? }` |
| POST | `/api/events/{id}/notes` | Add a note `{ text }` |
| DELETE | `/api/events/{id}` | Delete event + evidence file |
| GET | `/history/...` | Static serving of snapshot/clip evidence |

## Faces (recognition)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/persons` | List enrolled persons |
| POST | `/api/persons` | Create `{ name, watchlist?, notes? }` |
| POST | `/api/persons/{id}/images` | Upload face image (multipart); computes + stores embedding |
| POST | `/api/persons/{id}/capture` | Enroll from a camera's current frame `{ camera_id }` |
| DELETE | `/api/persons/{id}` | Delete person + their embeddings |
| GET | `/api/faces/policy` / PATCH | Get/set global policy: `label_only` / `alert_unknown` / `alert_watchlist` |

## Notifiers

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/notifiers/types` | Available notifier plugin types + config schema |
| GET | `/api/notifiers` | List configured notifiers |
| POST | `/api/notifiers` | Create `{ type, config, enabled, min_severity }` |
| PATCH | `/api/notifiers/{id}` | Update |
| POST | `/api/notifiers/{id}/test` | Send a test notification |
| DELETE | `/api/notifiers/{id}` | Delete |

## Analytics

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/analytics/summary` | Totals + counts by type/severity/status |
| GET | `/api/analytics/timeline` | Event counts bucketed `?bucket=hour|day&from=&to=` |
| GET | `/api/analytics/by-camera` | Event counts per camera |

## Activity & daily report

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/activity` | Raw activity-log entries `?camera_id=&from=&to=&limit=&offset=` |
| GET | `/api/reports/daily?date=YYYY-MM-DD|today` | Get the daily report (generates + caches if missing) |
| POST | `/api/reports/daily/regenerate?date=YYYY-MM-DD|today` | Force regeneration (e.g., after choosing a different generator) |
| GET | `/api/reports/daily/download?date=...` or `/api/reports/daily/{date}/download` | Download the rendered text briefing |

Daily report payload (shape):
```json
{
  "date": "2026-10-09",
  "generator": "structured",
  "generated_at": "2026-10-09T18:00:05Z",
  "text": "Quiet overnight. 3 unknown visitors at the Lobby between 09:12–17:40...",
  "content": {
    "highlights": [
      { "time": "14:03", "camera": "Garden", "summary": "Dog detected (loose animal)", "event_id": 88 },
      { "time": "11:20", "camera": "Door 4", "summary": "Package left; still present at 13:10", "event_id": 91 }
    ],
    "per_camera": { "Lobby": { "people_seen": 14, "unknown_faces": 3, "known": ["Ayush"] } },
    "stats": { "total_events": 12, "by_type": { "unknown_face": 3, "abandoned_object": 1 } },
    "quiet_periods": [ { "camera": "Lobby", "from": "23:30", "to": "06:10" } ]
  }
}
```

## Event payload (shared shape)

```json
{
  "id": 123,
  "type": "zone_intrusion",
  "severity": "critical",
  "status": "new",
  "camera_id": 1,
  "rule_id": 7,
  "person_id": null,
  "snapshot_path": "/history/events/cam1_1739000000.jpg",
  "clip_path": null,
  "metadata": { "track_id": 42, "bbox": [0.1,0.2,0.3,0.5], "zone_id": 3 },
  "created_at": "2026-10-09T06:45:00Z",
  "acknowledged_at": null,
  "resolved_at": null
}
```
