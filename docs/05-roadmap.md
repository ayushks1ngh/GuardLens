# 05 — Roadmap

Phased delivery. **Each phase ends at an acceptance gate** — a concrete, testable
checklist. We do not start a phase until the previous gate passes. Every phase
keeps the system runnable (no "big bang" integration at the end).

Legend: 🎯 = acceptance gate (must all pass to proceed).

---

## Phase 0 — Project skeleton & plumbing

**Build**
- Package layout per `02-architecture.md`.
- `config.py` (YAML + env), logging, `data/` dirs, `.gitignore`.
- FastAPI app with `/health`, static dashboard serving.
- SQLModel engine + migrations/table creation; empty tables from `03-data-model.md`.
- `requirements.txt`, `Dockerfile`, `docker-compose.yml`, run script.

**🎯 Gate 0**
- `python -m guardlens` (or script) starts the server with zero cameras.
- `GET /health` returns 200 with device info.
- DB file is created with all tables.
- Dashboard shell loads in the browser.

---

## Phase 1 — Capture, streaming & live dashboard

**Build**
- Capture worker (latest-frame, reconnect/backoff).
- Camera CRUD API + persistence.
- MJPEG stream endpoint + SSE overlay channel (alert flag/counts placeholder).
- Dashboard: live multi-camera grid, add/remove camera UI.

**🎯 Gate 1**
- Add a webcam (`source=0`) via the UI; its live MJPEG shows in the grid.
- Add a second source (video file) and both stream smoothly on CPU.
- Kill/restart a source → worker auto-reconnects.
- No base64-per-frame; CPU stays reasonable with 2 cameras.

---

## Phase 2 — Detection + tracking + rule engine foundation

**Build**
- `ObjectDetector` plugin (YOLO) with a **shared** model instance.
- Lightweight IoU/centroid tracker (stable track IDs).
- Detector + Rule plugin **registries** (the extensibility seam).
- Rule engine with cooldown/severity; wire detections → rules → `EventDraft`.
- Overlay SSE now emits real detections/counts.

**🎯 Gate 2**
- Live overlay shows person boxes + counts.
- A trivial `ObjectClassRule` (e.g., alert on `person`) produces an `EventDraft`
  (not yet persisted) visible in logs.
- Adding a dummy detector/rule via the registry requires **no core edits** (demonstrated).

---

## Phase 3 — Events, evidence & alert workflow

**Build**
- Event store: persist events + save JPEG snapshot; enforce cooldown.
- Events API: list/filter/paginate, detail, acknowledge, resolve, notes, delete.
- Dashboard: event timeline with filters + status actions; camera flashes on alert.
- `/api/events/stream` SSE pushes new events live.

**🎯 Gate 3**
- Triggering a rule writes an event + snapshot; it appears live in the timeline.
- Filter by camera/type/severity/status/time works.
- Acknowledge/resolve updates status and persists.
- Cooldown prevents event floods.

---

## Phase 4 — Real security rules (broad catalog)

**Build**
- `ZoneIntrusionRule` + zone CRUD + **canvas zone editor** in the dashboard.
- `LoiteringRule` (uses track dwell time).
- `LineCrossingRule` + in/out counters.
- `CrowdRule` (occupancy threshold).
- `ObjectClassRule` finalized with **real** model classes (fixes the original bug).
- `AnimalRule` (animal class present, optional zone).
- `AbandonedObjectRule` (movable object stationary, no person nearby, > N s).
- `VehicleRule` (vehicle class in zone).
- `PackageRule` (object left near a configured spot > N s).
- `AfterHoursRule` (person/vehicle during quiet hours).
- `FallRule` (optional: person box horizontal + down > N s).

All of the above are plugins registered via the rule registry — adding any further
rule later must still require **no core edits**.

**🎯 Gate 4**
- Draw a zone; walking into it raises a `zone_intrusion` event.
- Staying in zone > N s raises `loitering`.
- Crossing the line increments in/out counts correctly.
- Exceeding the crowd threshold raises `crowd`.
- Animal / vehicle / abandoned-object rules each fire on a suitable test clip.
- All thresholds editable from the UI; no restart required.
- `GET /api/rules/types` lists the full catalog with param schemas; the UI renders
  a config form for each **without hardcoding rule types**.

---

## Phase 5 — Face recognition

**Build**
- `FaceDetector` plugin (detect + embed + match) with in-memory embedding cache.
- Person & FaceImage persistence; enroll via upload and via live capture.
- `UnknownFaceRule` + face policy (`label_only` / `alert_unknown` / `alert_watchlist`).
- Dashboard: face enrollment panel; recognized names drawn on overlay.

**🎯 Gate 5**
- Enroll yourself; live view labels you by name.
- With policy `alert_unknown`, an unseen face raises an event with a snapshot.
- Watchlist policy raises an event when a flagged person appears.
- Deleting a person removes their embeddings and stops recognition.

---

## Phase 6 — Notifications & analytics

**Build**
- Notifier registry + `WebhookNotifier` (+ email stub); async, failure-isolated.
- Notifier config CRUD + test endpoint; `min_severity` filtering.
- Analytics endpoints (summary / timeline / by-camera).
- Dashboard: notification settings panel + analytics charts.

**🎯 Gate 6**
- A new event at/above `min_severity` POSTs to a configured webhook (verified with a test receiver).
- A failing webhook is logged and does **not** affect the pipeline.
- Analytics charts render correct counts over time / by type / by camera.

---

## Phase 7 — Activity log & daily report

**Build**
- Activity sampler: periodic per-camera scene summaries written to `activity_log`
  at a configurable interval (runs alongside the analysis pipeline).
- `ReportGenerator` interface + registry; default `StructuredReportGenerator`
  (templated narrative from `activity_log` + events).
- Reports API: `GET /api/reports/daily`, regenerate, download; report caching table.
- Dashboard: **Daily Report** panel (pick a date → view/download briefing);
  `/api/activity` browsing.
- Optional: hook a notifier to deliver the report at end of day.

**🎯 Gate 7**
- With cameras running, `activity_log` fills with periodic summaries.
- `GET /api/reports/daily?date=today` returns a coherent briefing: visitors/unknown
  faces, animals, abandoned/left objects, vehicles, quiet periods, notable events with
  snapshots.
- Regenerate produces a fresh report; download returns a readable file.
- The report generator is swappable (structured now; a VLM enricher could be added
  later) with **no change to callers or the API**.

---

## Phase 8 — Hardening & polish

**Build**
- End-to-end test pass; load test with multiple cameras.
- Input validation review, error handling, structured logs, `/health` detail.
- Activity-log retention/pruning; configurable sampling interval verified.
- Docker Compose one-command run verified from clean checkout.
- Docs updated to match the built system; sample `config.yaml` + seed data.

**🎯 Gate 8**
- `docker compose up` (or the run script) brings up a working system from scratch.
- Full happy-path demo (add camera → draw zone → trigger events across the broad
  catalog → recognize face → acknowledge/resolve → webhook → analytics → daily report)
  passes.
- No known crash paths; camera/model/notifier failures are contained.

---

## Flexibility checkpoints (verified every phase)

At each gate we re-confirm the core invariant:

- Can we add a **detector**, **rule**, and **notifier** without editing core files?
- Are new rule params handled purely via the JSON `params` column (no migration)?
- Are thresholds/model/FPS still config-driven (nothing newly hardcoded)?

If any answer is "no," we fix the seam before moving on.
