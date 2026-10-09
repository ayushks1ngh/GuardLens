# 01 — Product Requirements Document (PRD)

## 1. Summary

GuardLens 2.0 turns ordinary cameras (webcam, IP/RTSP, or video file) into an
intelligent monitoring assistant for places like apartment complexes. It watches
live video across many cameras at once, understands what is happening using computer
vision, raises **meaningful alerts** based on configurable rules, records every alert
as an **event** with evidence, keeps a continuous **activity log**, can produce a
**day-end report**, and gives an operator a single-page dashboard to monitor, triage,
and configure everything. It is an **assistive tool** (not a legal replacement for a
human guard): it never blinks, watches more cameras than a person can, and briefs
staff on what happened.

## 2. Goals & success criteria

| Goal | Success criterion |
|------|-------------------|
| Detect real security situations | Zone intrusion, loitering, crowding, line-crossing, animal/vehicle/abandoned-object, and unknown-face events fire correctly in manual testing. |
| Run with no special hardware | Full pipeline runs on a CPU-only laptop at ≥ 5 analyzed FPS per camera (configurable). |
| Never lose an event | Every triggered alert is persisted with a snapshot and is queryable later. |
| Brief staff on the day | A day-end report summarizes activity + events across all cameras for any date. |
| Operator can triage | Events can be filtered, acknowledged, and resolved from the dashboard. |
| Extensible without rewrites | A new detector / rule / notifier / report-enricher can be added as a plugin without editing core files. |

## 3. Users

- **Operator** (primary) — watches the dashboard, responds to alerts, acknowledges/resolves.
- **Administrator** — adds cameras, draws zones, defines rules, enrolls faces, configures notifications.
- (In v1 these are the same person; the design does not preclude splitting later.)

## 4. User stories

### Monitoring
- As an operator, I see all my cameras live in one grid.
- As an operator, I get an immediate visual + list alert when a rule triggers.
- As an operator, I can click an event to see the snapshot and details.

### Triage / workflow
- As an operator, I can acknowledge an event so colleagues know it's being handled.
- As an operator, I can resolve an event and optionally add a note.
- As an operator, I can filter events by camera, type, severity, status, and time range.

### Configuration
- As an admin, I can add/remove a camera by source (index, RTSP URL, or file path).
- As an admin, I can draw one or more detection zones on a camera and attach rules.
- As an admin, I can set thresholds (loitering seconds, crowd count, line direction).
- As an admin, I can enroll a known person from an uploaded image or a live capture.
- As an admin, I can choose whether unknown faces, known faces, or a specific person trigger alerts.
- As an admin, I can configure a webhook to receive notifications.

### Analytics
- As an operator, I can see counts of events over time, by type, and by camera.

## 5. Functional requirements

### FR-1 Camera management
- FR-1.1 Add a camera with a name and source (`0`, RTSP URL, or file path).
- FR-1.2 List, update, enable/disable, and remove cameras.
- FR-1.3 Auto-reconnect on stream drop with backoff.

### FR-2 Detection
- FR-2.1 Run object detection per camera at a configurable analyze-FPS.
- FR-2.2 Expose detected objects (class, confidence, bounding box) to the rule engine.
- FR-2.3 Maintain lightweight multi-object tracking (stable IDs) to support loitering/line-crossing.

### FR-3 Rule engine (alert rules)
- FR-3.1 **Zone intrusion** — alert when a tracked person's box enters a defined polygon.
- FR-3.2 **Loitering** — alert when a tracked person remains in a zone/frame longer than N seconds.
- FR-3.3 **Line-crossing / counting** — count persons crossing a virtual line; expose in/out counts; alert optionally.
- FR-3.4 **Crowd / occupancy** — alert when person count in a zone/frame exceeds a threshold.
- FR-3.5 **Object class** — alert when a configured class (e.g., `knife` if the model supports it) appears. Replaces the old dead "sharp object" list using only real classes.
- FR-3.6 **Animal presence** — alert when an animal class (dog/cat/…) appears, optionally scoped to a zone.
- FR-3.7 **Abandoned / lost object** — alert when a movable object (bag/suitcase/backpack) stays still with no person nearby for N seconds.
- FR-3.8 **Vehicle presence** — alert when a vehicle class appears in a zone (e.g., driveway).
- FR-3.9 **Package / delivery** — alert when an object is left near a configured spot (door) for N seconds.
- FR-3.10 **Fall detection (optional)** — alert when a person's bounding box becomes horizontal and remains down for N seconds.
- FR-3.11 **After-hours activity** — alert on any person/vehicle during configured quiet hours.
- FR-3.12 Each rule has: enabled flag, severity, cooldown, target camera(s), optional zone, and JSON params.
- FR-3.13 Rules are evaluated per frame; triggering creates an event (subject to cooldown).
- FR-3.14 Rule types are **discoverable** (the API lists available types + param schemas); the catalog can grow via plugins without UI or schema changes.

### FR-4 Face recognition
- FR-4.1 Enroll a person: name + one or more face images → stored face embeddings.
- FR-4.2 Recognize faces in the live feed; label known persons.
- FR-4.3 Policy options: alert on **unknown** faces, alert on a **specific watchlisted** person, or label-only (no alert).
- FR-4.4 Manage enrolled persons (list, add images, delete).

### FR-5 Events & evidence
- FR-5.1 Persist every triggered alert as an event: type, severity, camera, timestamp, snapshot path, rule reference, metadata.
- FR-5.2 Store a JPEG snapshot (and optionally a short clip) as evidence.
- FR-5.3 Enforce per-rule cooldown to avoid event floods.

### FR-6 Alert workflow
- FR-6.1 Event status lifecycle: `new → acknowledged → resolved`.
- FR-6.2 Operators can change status and attach a note.
- FR-6.3 Query/filter events by camera, type, severity, status, time range; paginated.

### FR-7 Notifications
- FR-7.1 On a new event, fire configured notifiers (v1: webhook; stubs for email/others).
- FR-7.2 Notifier failures must not crash the pipeline (isolated, logged).

### FR-8 Analytics
- FR-8.1 Aggregate counts: events over time (bucketed), by type, by camera, by severity.

### FR-9 Activity log & daily report (apartment "AI guard" briefing)
- FR-9.1 Continuously record an **activity log**: periodic per-camera scene summaries
  (timestamp, person/animal/vehicle counts, recognized persons, active zones) at a
  configurable interval — not only alert events.
- FR-9.2 Generate a **daily report** for a given date: a readable briefing aggregating
  the activity log + events across all cameras (visitors seen, unknown faces, animals,
  abandoned/left objects, vehicles, quiet periods, notable events with snapshots).
- FR-9.3 v1 report is built from **structured data + templated narrative** (CPU-friendly,
  deterministic). The report generator is pluggable so a vision-language enricher can be
  added later without changing callers (see ADR-010).
- FR-9.4 Reports are viewable in the dashboard and retrievable via API; optionally
  delivered via a notifier at end of day.

### FR-10 Dashboard (single page)
- FR-10.1 Live multi-camera grid with alert highlighting.
- FR-10.2 Event timeline with filters and status actions.
- FR-10.3 Config panels: cameras, zones (draw on canvas), rules, face enrollment, notifications.
- FR-10.4 Analytics charts.
- FR-10.5 **Daily Report** panel: pick a date, view/download the briefing.

## 6. Non-functional requirements

- **NFR-1 Performance:** CPU-only, ≥ 5 analyzed FPS/camera on a typical laptop with the default model; streaming decoupled from analysis so the live view stays smooth.
- **NFR-2 Reliability:** camera drop or model/notifier error must never crash the server; auto-recover.
- **NFR-3 Extensibility:** detectors, rules, and notifiers are plugins discovered via a registry (see `07-extensibility.md`). Adding one requires no core edits.
- **NFR-4 Portability:** one-command run (script and/or Docker Compose); SQLite default, Postgres-compatible.
- **NFR-5 Configurability:** all thresholds, FPS, model choice, and paths are config-driven (env + config file), not hardcoded.
- **NFR-6 Security/Privacy:** face data stored locally; secrets via env; input validation on all API inputs; no secrets echoed in logs.
- **NFR-7 Observability:** structured logs; a `/health` endpoint; per-camera status surfaced to the dashboard.

## 7. Constraints & assumptions

- No GPU available; models must be CPU-viable.
- Single host, single operator for v1.
- Model licensing must be documented and a permissive fallback must exist (see ADRs).

## 8. Out of scope (v1)

Full React frontend, multi-tenant auth/RBAC, cloud autoscaling, GPU/TensorRT, VQA.
All are intentionally left possible by the architecture.
