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
| GET | `/api/cameras` | List cameras + adapter/status (connected, fps, resolution, freshness, error) |
| GET | `/api/cameras/source-types` | Source adapter/mode schemas for the Add Camera wizard |
| GET | `/api/cameras/local-devices` | Host `/dev/video*` devices when exposed |
| POST | `/api/cameras/probe` | Validate/open/read one frame without persisting a camera |
| POST | `/api/cameras` | Add legacy `{name,source}` or typed `{name,source_type,source_config,analyze_fps?}` |
| GET | `/api/cameras/{id}` | Get one camera and detailed runtime source status |
| PATCH | `/api/cameras/{id}` | Update metadata, source config, enabled state, or analyze FPS |
| DELETE | `/api/cameras/{id}` | Remove camera (stops its worker) |

## Live video & events (streaming)

| Method | Path | Purpose |
|--------|------|---------|

## Browser/WebRTC pairing

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/pairing` | Create 30–900s single-use pairing link + inline SVG QR; token is URL-fragment-only |
| GET | `/api/pairing` | Non-secret pairing status (`used`, `connected`, `revoked`, expiry) |
| POST | `/api/pairing/offer` | WebRTC offer/answer signaling; HTTPS required outside localhost |
| DELETE | `/api/pairing/{stream_id}` | Revoke publisher, reconnect credential, media peer, and frame channel |
| GET | `/publish#...` | Permission-gated phone/laptop publisher with camera/quality selection |

Initial tokens and rotating reload credentials are stored only as hashes in memory.
Signaling bodies and active sessions are bounded. LAN-only ICE is the current scope;
internet/NAT publishing requires an intentionally configured TURN/auth deployment.
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

## Recording

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/recording` | Effective persisted recording config plus active clips/errors |
| PATCH | `/api/recording` | Atomically apply validated mode, pre/post-roll, retention, quota, codecs |

Settings persist in the existing JSON `setting` table (no schema migration). Changing
settings finalizes active writers first. Recording defaults off; operators explicitly
enable event, motion, or segmented continuous mode.

## Vision chat (optional VLM; ADR-010 seam)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/vision/status` | Whether a VLM is configured + model name |
| POST | `/api/vision/ask` | `{ camera_id, question }` → sends that camera's current frame to a cloud VLM and returns a text answer |

The model and key are configuration-only: `GUARDLENS_NVIDIA_API_KEY` (required to enable)
and optional `GUARDLENS_VLM_MODEL` (default `meta/llama-3.2-11b-vision-instruct`). The
key is read from the environment, never persisted or logged. **Asking transmits the
selected camera's frame to the external provider** — opt-in and inert without a key.
The `vlm_watch` rule reuses this to raise a `vlm_alert` event when the model reports
configured keywords (e.g. knife, scissors, weapon) on a person/motion trigger, running
the slow cloud call off the analysis loop.

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
| GET | `/api/events/{id}/clip` | Stream/download finalized MP4/AVI clip evidence |
| DELETE | `/api/events/{id}` | Delete event + unshared evidence files |
| GET | `/history/...` | Static serving of snapshot evidence |

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

---

## Post-2.0 API additions (docs/13)

All endpoints below require login once it is enabled (`docs/14`), except where noted.

| Area | Endpoints |
|------|-----------|
| Discovery | `GET /api/meta`, `GET /healthz` (public), `GET /api/health/issues` |
| Schema-driven settings | `GET /api/rules/types`, `/api/notifiers/types`, `/api/agents` → each type has `fields` (label/help/unit/min/max/enum/widget); invalid settings → `422 {detail:{message, errors:[{field,message}]}}` |
| Cameras | `GET /api/cameras/{id}/snapshot` (JPEG) |
| People | `PATCH /api/persons/{id}` |
| Events | `GET /api/events/stream` (SSE: new events as default messages; `event: event_updated` for agent annotations; fresh connections no longer replay history), `GET /api/events/{id}/incident-report?ai=` |
| Agents | `GET /api/agents`, `PUT /api/agents/{key}`, `POST /api/agents/{key}/run`, `GET /api/agents/runs`, `GET /api/agents/ai`, `GET /api/agents/scheduler` |
| Privacy | `GET/PUT /api/privacy` (cameras that never send video to a cloud AI) |
| Assistant | `POST /api/assistant/chat`, `DELETE /api/assistant/sessions/{id}` |
| Rules | `POST /api/rules/propose` (AI draft, never saves), `POST /api/rules/preview` (dry-run replay) |
| Notifications | `GET/PUT /api/notifiers/routing` (quiet hours) |
| Search | `GET /api/search`, `GET /api/search/similar/{id}`, `GET /api/search/status`, `PUT /api/search/settings`, `POST /api/search/reindex` |
| Auth | `GET /api/auth/status` (public), `POST /api/auth/setup|login|logout` (public), `PUT /api/auth/password|settings`, `GET/POST/DELETE /api/auth/tokens` |
