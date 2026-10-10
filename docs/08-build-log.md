# 08 — Build Log

Running record of each phase: what was built, how the acceptance gate was verified,
notable decisions/fixes, and the commit. Newest phases are appended at the bottom.

---

## Phase 0 — Project skeleton & plumbing ✅

**Commit:** `Phase 0: project skeleton, config, DB models, /health, dashboard shell`

**Built**
- FastAPI app (`guardlens/app.py`) with lifespan: loads config, initializes SQLite.
- Config loader (`guardlens/config.py`) — YAML + `GUARDLENS_*` env overrides (ADR-009).
- Core data contracts (`guardlens/types.py`): `Detection`, `Zone`, `FrameContext`, `EventDraft`.
- SQLModel schema (`guardlens/events/models.py`) — all 11 tables from docs/03-data-model.md.
- Dashboard shell (`frontend/index.html`) — neon style, tabs, health/config polling.
- `scripts/check_source.py` — validate any camera source (file/index/URL) before adding.
- Sample footage copied to `data/samples/mall_cctv.mp4` (1920x1080, 30fps, ~15s, H.264).
- Entry point `python -m guardlens`.

**Gate 0 — PASSED** (`tests/test_phase0.py`, 5/5)
- `/health` 200 with device info; `/api/config` returns runtime config.
- DB file created with all expected tables.
- Dashboard served at `/`.
- Sample video present.

**Notes**
- Dependencies split: Phase 0 installed web/DB/test subset for a fast gate; heavier
  CV deps (opencv, ultralytics) installed before Phase 1/2.
- Verification is via the pytest suite (deterministic, exits cleanly) — no long-running
  background servers in the loop.

---

## Phase 1 — Capture, streaming & live dashboard ✅

**Built**
- `CaptureWorker` (`guardlens/capture/worker.py`): one thread per camera, keeps only the
  LATEST frame (no lag), reconnect with exponential backoff, loops video files so sample
  footage behaves like a continuous live feed, measures FPS (EMA).
- `CameraManager` singleton (`guardlens/capture/manager.py`): starts/stops workers,
  reconciles with the DB, reports per-camera status.
- Streaming (`guardlens/streaming/stream.py`): MJPEG generator (ADR-005) + SSE overlay
  channel + an `OverlayStore` for lightweight per-camera metadata (populated in Phase 2).
- Camera CRUD API (`guardlens/api/cameras.py`) and stream routes (`guardlens/api/stream.py`).
- App wiring: workers start on lifespan startup, stop on shutdown; `/health` now reports
  live camera status.
- Dashboard Live panel: add-camera form, live MJPEG grid, per-camera connected/fps pills,
  remove button, alert-highlight via overlay SSE.
- Installed CV deps: opencv-python 4.10, numpy 2.1.

**Gate 1 — PASSED** (`tests/test_phase1.py`, 5 tests + Phase 0's 5 = 10 total)
- Worker connects to the sample file and reads valid frames.
- Video file loops (frames keep updating past clip length).
- Camera CRUD works; worker connects; disable stops it; delete removes it (404 after).
- MJPEG endpoint returns `multipart/x-mixed-replace` with JPEG chunks.
- Two sources run concurrently.
- A bad source never connects but does not crash (reconnect/backoff contained).

**Fixes during the loop**
- MJPEG generator could block forever if a source never produced frames → added a 20s
  no-frame cap so streaming responses can't hang.
- Shared `manager` singleton leaked workers between tests → added an autouse conftest
  fixture that stops all workers after each test.
- Verified the sample video opens via `scripts/check_source.py`: 1920x1080 @ 30fps.

---
## Phase 2 — Detection, tracking & rule-engine foundation ✅

**Built**
- Detector plugin interface + automatic package discovery (`guardlens/detectors/`):
  adding a detector is a new plugin file + config, with no registry/core edit.
- `ObjectDetector`: Ultralytics YOLO behind the detector contract, normalized boxes,
  config-driven weights/device/confidence, one process-wide model instance, and a
  shared inference lock for safe multi-camera use.
- Pure-Python `CentroidTracker`: greedy same-class IoU/centroid matching, stable track
  IDs, bounded histories, and stale-track expiry.
- Rule plugin interface + automatic discovery, `param_schema` exposure, and
  `ObjectClassRule` using only real model classes and free-form JSON/config params.
- Failure-isolated `RuleEngine` with per-camera/rule cooldown and synchronized shared
  state for multi-camera workers.
- Analysis pipeline: latest-frame sampling at configured analyze-FPS, detectors →
  tracker → `FrameContext` → rules; Phase 2 logs `EventDraft`s (persistence is Phase 3).
- Overlay SSE now carries counts, normalized boxes, confidence, track IDs, alert state,
  and fired-rule summaries. The dashboard draws them over MJPEG on a canvas.
- Camera CRUD starts/stops analysis workers dynamically; app lifespan starts/stops the
  analysis manager. `analysis_enabled` provides a config/env lifecycle switch.
- CPU-first dependency pinning: Torch/Torchvision CPU wheels; YOLO weights are ignored
  by git and downloaded once. Added bounded MJPEG diagnostics (`?max_frames=1..10`).

**Gate 2 — PASSED** (`tests/test_phase2.py`; full suite 18/18)
- Real YOLO inference on the sample CCTV frame detected people and cars.
- Pipeline assigned stable IDs and populated overlay boxes/counts.
- Configured `ObjectClassRule` emitted/logged an `EventDraft` and set alert state.
- Dummy detector and rule plugins registered and ran without core edits; rule schemas
  were auto-exposed from the registry.
- Cooldown suppresses repeated drafts; a broken rule is isolated from the pipeline.
- Production-style smoke: dynamically added sample camera connected, detected 4 people
  + 3 cars (7 boxes), fired a warning, served MJPEG, and shut down cleanly.

**Validation**
- Phase 0/1 regressions: **10 passed**.
- Phase 2 fast seam tests: **7 passed**.
- Phase 2 real-inference test: **1 passed**.
- Full suite: **18 passed** in 6.59s (one upstream Starlette deprecation warning).
- `pip check`: no broken requirements; imports report OpenCV 4.10.0,
  Torch 2.5.1+cpu, CUDA unavailable (as intended).
- Python compile and dashboard JavaScript syntax checks passed.

**Fixes during the loop**
- Existing Phase 1 infinite-MJPEG test could hang under Starlette `TestClient` because
  the client buffers endless streams → added an optional bounded response for tests
  while production remains infinite by default.
- Tests previously used the real `data/guardlens.db`, accumulating cameras across runs
  → moved tests to an isolated temporary DB/data directory and clean both capture and
  analysis singletons after every test.
- Initial Ultralytics install pulled CUDA packages and full OpenCV unexpectedly →
  restored/pinned CPU-only Torch and a consistent OpenCV distribution.
- Explicit built-in imports violated the documented "drop in a plugin file" invariant
  → replaced them with automatic module discovery.

---
## Phase 3 — Events, evidence & alert workflow ✅

**Built**
- Thread-safe event store with atomic SQLite persistence and JPEG evidence cleanup.
- Filtered/paginated event APIs, detail, notes, acknowledge/resolve, deletion, and SSE.
- Analysis persists drafts through an injected, failure-isolated event sink.
- Live dashboard timeline with filters, snapshots, status actions, and SSE refresh.

**Gate 3 — PASSED** (`tests/test_phase3.py`, 5 tests)
- Events and snapshots persist; filters/workflow survive DB round trips.
- Deletion removes evidence; event-store failure does not stop analysis.
- Rule-engine cooldown prevents floods before persistence.

---

## Phase 4 — Security rule catalog & zones ✅

**Built**
- Zone CRUD, normalized live-video canvas editor, and cached frame-time policy data.
- Persisted rule CRUD with immediate runtime reload and camera/zone validation.
- Auto-discovered plugins: zone intrusion, loitering, line crossing/counters, crowd,
  animal, vehicle, abandoned object, package spot, after-hours, fall, and object class.
- Schema-driven dashboard rule forms; params stay in JSON with no migrations.

**Gate 4 — PASSED** (`tests/test_phase4.py`, 7 tests)
- Synthetic motion/dwell/occupancy/class scenarios verify the catalog deterministically.
- Abandoned objects require person clearance; package rules support a configured spot.
- CRUD/schema discovery and normalized-coordinate validation pass.

---

## Phase 5 — Face recognition ✅

**Built**
- Auto-discovered `FaceDetector` with an OpenCV CPU baseline backend, normalized
  embeddings, matching cache, recognized-name overlays, and swappable backend contract.
- Person creation/list/delete, upload/live enrollment, safe filenames, image validation,
  watchlist state, and global label/unknown/watchlist policy.
- `UnknownFaceRule` emits unknown/watchlist drafts according to policy.

**Gate 5 — PASSED** (`tests/test_phase5.py`, 5 tests)
- Enrollment, matching, cache refresh, policy alerts, invalid uploads, and deletion pass.
- Live capture refuses frames where no face is detected.

**Decision refinement:** OpenCV is the deterministic no-extra-download CPU default.
InsightFace/`face_recognition` remain replaceable higher-accuracy backends (ADR-003).

---

## Phase 6 — Notifications & analytics ✅

**Built**
- Auto-discovered notifier registry, async bounded thread-pool dispatch, severity filters,
  webhook notifier, config CRUD/test endpoint, validation, and secret-redacted responses.
- Summary, timeline, and by-camera analytics APIs plus dashboard visual bars.
- Invalid/failing notifier configurations are isolated from startup and event persistence.

**Gate 6 — PASSED** (`tests/test_phase6.py`, 4 tests)
- Severity routing, successful delivery, failure isolation, CRUD, and analytics verified
  with local test plugins only (no external data transmission).

---

## Phase 7 — Activity log & daily report ✅

**Built**
- Configurable activity sampler with flexible JSON scene summaries and retention pruning.
- Auto-discovered report-generator registry and deterministic structured generator.
- Activity browsing/pagination; cached daily reports; regenerate and download APIs;
  `date=today` and ISO dates supported. Dashboard report controls included.

**Gate 7 — PASSED** (`tests/test_phase7.py`, 3 tests)
- Sampling interval, counts/identities, coherent report content, cache/regeneration,
  download, and generator swappability pass.

---

## Phase 8 — Hardening & polish ✅

**Built**
- Input constraints, zone ownership checks, richer health data, stale-overlay cleanup,
  notifier URL/timeout validation/redaction, activity retention, and version `2.0.0`.
- SSE plus WebSocket overlay fallback; bounded MJPEG diagnostic mode.
- Complete operator SPA: live tracked overlays, event workflow, live zone editor,
  schema-driven rules, face enrollment/policy, notifiers, analytics, daily reports.
- `run.sh`, Dockerfile, `.dockerignore`, and Docker Compose with persistent data and
  model-weight volumes; CPU Torch wheels pinned to avoid CUDA bloat.
- Isolated temporary test DB/data and worker cleanup prevent state/thread leakage.

**Gate 8 — PASSED** (`tests/test_phase8.py`, 5 tests; **47/47 total**)
- Full API happy path passes: camera → zone/rule → event/snapshot → acknowledge/resolve
  → analytics → daily report/download.
- Real default-runtime smoke detected people, cars, and faces; persisted events/activity;
  served MJPEG; generated a report; and shut down cleanly.
- Two-camera real-inference load smoke: both streams connected near source FPS, both
  produced 9 overlay boxes and durable events using the shared locked YOLO model.
- Final `guardlens:2.0.0` image built successfully; Compose config validates.
- Python compile, dashboard JavaScript syntax, `pip check`, shell syntax, and diff
  whitespace checks pass.

**Known non-blocking warning**
- Test runs emit one upstream Starlette deprecation warning for AnyIO's
  `BlockingPortal` alias. It does not affect behavior; revisit when upgrading FastAPI/
  Starlette together.

---

## Post-2.0 research — multi-device cameras, recording & hand/sign input 📋

**Status:** Planning only; no implementation started.

**Requested direction**
- Add local webcams, phones, laptops, IP/RTSP/HTTP cameras, and files through one
  guided camera workflow, with all existing detection/rules/events/reports applied.
- Add motion/event/continuous recording and hand/sign recognition.
- Keep docs/recovery/reference licensing current throughout implementation.

**Research findings**
- `-CCTV-Style-Motion-Detection-using-OpenCV`: useful MOG2/morphology/contour and
  no-motion-buffer clip pattern; it does not provide multi-device networking. README
  says MIT but no root license file was found, so source copying is not approved.
- `hand-gesture-recognition-mediapipe`: Apache-2.0; strong template for MediaPipe hand
  landmarks, normalized keypoints, TFLite static gestures, and 16-frame motion history.
  Included vocabulary is basic gestures, not complete sign language.
- `NARUTO-HandSignDetection`: MIT; YOLOX-Nano ONNX detects 14 fictional hand signs and
  demonstrates sequence reset/chattering suppression. It is not sign language.
- Browser phone/laptop publishing should use permissioned `getUserMedia` + WebRTC;
  non-local browser camera access requires HTTPS. RTSP/MJPEG remains a pull adapter.

**Proposed plan**
- Added `docs/10-improvement-plan.md` with Phases A–F and measurable gates.
- Added proposed ADR-012 (source adapters/WebRTC), ADR-013 (clip recorder), and ADR-014
  (vocabulary-scoped gesture plugins).
- Implementation waits for decisions on LAN/internet scope, camera onboarding order,
  recording modes/retention, target sign language/scope, and optional NARUTO demo.

**Session hygiene**
- Updated README docs index, overview references, ADR/open questions, and recovery.
- Stopped the temporary high-CPU manual demo before planning.

---
