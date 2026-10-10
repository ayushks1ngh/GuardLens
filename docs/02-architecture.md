# 02 — Architecture

## 1. Guiding principle: flexible by design

The hard requirement is that **adding a new capability must not require rewriting
the core**. We achieve this with three plugin registries — **Detectors**,
**Rules**, and **Notifiers** — plus a stable internal data contract (the
`Frame` → `Detection` → `Event` pipeline). Everything else plugs into those seams.

```
                         ┌────────────────────────────────────────────┐
                         │                  GuardLens core             │
                         │                                             │
  Camera sources         │   ┌──────────┐   Frame    ┌─────────────┐   │
  (webcam / RTSP /  ───► │   │ Capture  ├──────────► │  Analysis   │   │
   file)                 │   │  worker  │            │  pipeline   │   │
                         │   └────┬─────┘            └──────┬──────┘   │
                         │        │ latest frame            │ Detections│
                         │        ▼                         ▼           │
                         │   ┌──────────┐           ┌───────────────┐   │
   Live view  ◄──────────┼───┤  Stream  │           │  Rule engine  │   │
   (MJPEG/WS) │          │   │  broker  │           │ (Rule plugins)│   │
              │          │   └──────────┘           └──────┬────────┘   │
              │          │                                 │ Events     │
              │          │   ┌──────────────┐              ▼            │
   Dashboard ◄┼──────────┼───┤  Event store │◄──────┬──────────────┐    │
   (SPA)      │  REST/SSE│   │  (SQLite DB) │       │ Notifiers    │    │
              │          │   └──────────────┘       │ (plugins)    │    │
              │          │                          └──────────────┘    │
              │          └────────────────────────────────────────────┘
              │
              └─ REST + WebSocket/SSE (FastAPI)
```

## 2. Components

### 2.1 Capture sources + worker (`guardlens/capture/`)
- Auto-discovered `CameraSource` adapters implement `open/read/close/status`.
- Phase A `OpenCvSource` supports host device indexes, files, RTSP, HTTP, and MJPEG;
  Phase B adds a browser/WebRTC publisher adapter without changing analysis.
- One capture worker per camera, running in its own thread and consuming its adapter.
- Keeps only the **latest** frame (drops stale frames to avoid lag).
- Handles reconnect with backoff and reports adapter type, resolution, frame age/errors.
- Publishes the latest raw frame to the **stream broker** and **analysis pipeline**.

### 2.2 Analysis pipeline (`guardlens/analysis/`)
- Pulls the latest frame at the configured **analyze-FPS** (independent of capture FPS).
- Runs each enabled **Detector** plugin → produces a normalized list of `Detection`
  (class, confidence, bbox) plus optional structured outputs (e.g., face identities).
- Runs a lightweight **tracker** (IoU/centroid) to assign stable track IDs — needed
  for loitering and line-crossing.
- Passes the frame context (detections + tracks + timestamp + camera) to the rule engine.

### 2.3 Detector plugins (`guardlens/detectors/`)
- Interface: `Detector.process(frame) -> list[Detection]`.
- Built-in: `ObjectDetector` (YOLO/COCO), `FaceDetector` (detect + recognize).
- New detectors register themselves; the pipeline runs whatever is enabled in config.

### 2.4 Rule engine + Rule plugins (`guardlens/rules/`)
- Interface: `Rule.evaluate(context) -> Optional[EventDraft]`.
- `context` includes current detections, track history, zones, and per-rule params.
- Built-in rules: `ZoneIntrusionRule`, `LoiteringRule`, `LineCrossingRule`,
  `CrowdRule`, `ObjectClassRule`, `UnknownFaceRule`.
- The engine applies **cooldown** and **severity** before emitting an `Event`.

### 2.5 Event store (`guardlens/events/`)
- SQLModel over SQLite (file DB). Writes events + evidence (snapshot path).
- Provides query API (filter/paginate) and analytics aggregation.
- Swappable to Postgres by changing the connection URL (no code changes).

### 2.6 Notifier plugins (`guardlens/notifiers/`)
- Interface: `Notifier.send(event) -> None`.
- Built-in: `WebhookNotifier` (POST JSON). Stubs: `EmailNotifier`.
- Dispatched asynchronously; failures are isolated and logged, never fatal.

### 2.7 Stream broker (`guardlens/streaming/`)
- Serves the live view efficiently: an **MJPEG** HTTP endpoint per camera for the
  video itself (cheap, browser-native via `<img>`), and a **WebSocket/SSE** channel
  for lightweight metadata (alert flags, counts, track overlays).
- This replaces the original "base64 every frame over WS" approach.

### 2.8 API layer (`guardlens/api/`)
- FastAPI app exposing REST for config + events, SSE/WS for live updates,
  MJPEG for video, and static serving for the dashboard. See `04-api-spec.md`.

### 2.9 Activity log & report generator (`guardlens/reporting/`)
- An **activity sampler** writes periodic per-camera scene summaries to the
  `activity_log` table (counts of people/animals/vehicles, recognized persons, active
  zones) at a configurable interval — a continuous record of "what was happening,"
  independent of whether an alert fired.
- A **report generator** aggregates the activity log + events for a date into a
  readable **daily report**. It is pluggable (`ReportGenerator` interface): v1 uses a
  `StructuredReportGenerator` (templated narrative from data); an optional
  `VlmReportEnricher` can add natural-language scene descriptions later (ADR-010)
  without changing callers.

### 2.10 Dashboard (`frontend/`)
- Single-page HTML/JS (keeps the original style). Talks only to the API layer.
- Panels: live grid, event timeline, zone editor (canvas), rules, face enrollment,
  notifications, analytics, daily report.

## 3. Data flow (one alert, end to end)

1. Capture worker grabs frame F from camera C.
2. Analysis pipeline runs detectors → detections D; tracker assigns IDs.
3. Rule engine evaluates each enabled rule for C against D + track history.
4. `ZoneIntrusionRule` matches → emits an `EventDraft` (type, severity, bbox, snapshot).
5. Event store checks cooldown, saves snapshot JPEG, writes the `Event` row.
6. Notifier dispatch fires `WebhookNotifier` with the event payload.
7. SSE pushes a "new event" message; dashboard updates timeline + flashes camera C.

## 4. Concurrency model

- **Capture threads:** one per camera (blocking I/O on OpenCV).
- **Analysis:** worker per camera (or a shared pool) consuming latest frames.
- **Shared model instances:** detectors load once and are reused (thread-safe calls
  or a per-model lock), fixing the original per-thread reload.
- **API:** async FastAPI; DB writes via a thread-pool to avoid blocking the loop.
- **Backpressure:** always analyze the latest frame; never queue stale frames.

## 5. Configuration

- `config.yaml` (or env overrides) controls: cameras, model choice, analyze-FPS,
  snapshot/clip paths, DB URL, enabled detectors/rules/notifiers, thresholds.
- Nothing security-relevant (thresholds, classes, FPS) is hardcoded.

## 6. Technology stack

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.12 | matches host |
| Web | FastAPI + Uvicorn | async, same family as original |
| CV | OpenCV | capture + drawing |
| Detection | Ultralytics YOLO (default) / pluggable | **AGPL** — fallback documented in ADRs |
| Tracking | lightweight IoU/centroid tracker | pure Python/NumPy, CPU-cheap |
| Face | OpenCV baseline / pluggable InsightFace or `face_recognition` | ADR-003 |
| DB/ORM | SQLModel + SQLite | Postgres-compatible |
| Frontend | HTML/CSS/JS single page | extends original dashboard |
| Packaging | venv + script, and Docker Compose | one-command run |

## 7. Directory layout (target)

```
GuardLens/
├── docs/                     # these documents
├── guardlens/                # backend package
│   ├── api/                  # FastAPI routes (cameras, events, faces, rules, stream)
│   ├── capture/              # camera capture workers
│   ├── analysis/             # pipeline + tracker
│   ├── detectors/            # Detector plugins (object, face) + registry
│   ├── rules/                # Rule plugins (zone, loiter, line, crowd, class, face) + engine
│   ├── notifiers/            # Notifier plugins (webhook, email stub) + registry
│   ├── events/               # Event store, models, analytics
│   ├── reporting/            # Activity sampler + daily report generator (pluggable)
│   ├── streaming/            # MJPEG + SSE broker
│   ├── config.py             # config loading/validation
│   └── app.py                # app assembly + lifespan
├── frontend/                 # single-page dashboard
├── data/                     # SQLite db, snapshots, face embeddings (gitignored)
├── config.yaml               # default config
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 8. How this stays flexible (the point)

- **Add a detector** (e.g., fire/smoke, license plate): drop a file in `detectors/`,
  implement the interface, register it, enable in config. Pipeline picks it up.
- **Add a rule** (e.g., "person in zone after hours"): drop a file in `rules/`,
  implement `evaluate`, register, configure. Engine runs it.
- **Add a notifier** (e.g., Telegram, MQTT): implement `send`, register, configure.
- **Add a report generator/enricher** (e.g., a VLM-based narrative): implement the
  `ReportGenerator` interface, register, select in config.
- **Swap the DB**: change the connection URL.
- **Swap the detection model**: change config; the `Detection` contract is stable.

No core file edits required for any of the above — enforced by the registry pattern.
See [`07-extensibility.md`](07-extensibility.md) for concrete interfaces.
