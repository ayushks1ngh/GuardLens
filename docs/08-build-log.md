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

## Improvement Phase A — source abstraction (implementation checkpoint) ✅/🧪

**Built**
- Auto-discovered `CameraSource` registry with stable open/read/close/status contract.
- Backward-compatible `OpenCvSource` modes: host device, file, RTSP/HTTP/MJPEG network.
- Additive SQLite migration adds `camera.source_type` and JSON `source_config` without
  deleting or rewriting old camera rows; source-type index included.
- Legacy `{name, source}` API remains valid; typed source API is validated before save.
- Source-type schema, Linux local-device discovery, and one-frame non-persisting probe APIs.
- Probe-first Add Camera wizard for host, network/phone-camera-app, and file sources;
  browser/WebRTC pairing is explicitly deferred to Phase B.
- Camera status includes adapter type, resolution, frame freshness, and source error.
- Network credentials and query tokens are redacted from API responses.
- `scripts/check_source.py` now uses the same adapter registry as runtime capture.

**Automated validation — PASSED**
- `tests/test_improvement_a.py`: 7 tests for registry extensibility, source modes,
  typed/legacy CRUD, one-frame probe, detailed status, migration, redaction, and wizard.
- Fixed a capture-status race found during recovery: a source now becomes `connected`
  only after its first frame, so resolution/freshness status is internally consistent.
- Full suite: **55/55 passed**; Python/frontend syntax, `pip check`, Compose config pass.
- Real local HTTP/MJPEG integration: network adapter read a 1920×1080 frame.
- Sample file adapter/CLI: 1920×1080 @ 30 FPS.

**Gate A still awaiting user input**
- Physical host webcam passed: Windows `USB2.0 HD UVC WebCam` was attached to WSL2;
  source probe, sustained dual-source capture, REST status, two-frame MJPEG, and
  disable/re-enable recovery all passed at 640×480 MJPEG.
- Hardware testing exposed a WSL USB/IP compatibility issue: default YUYV opened but
  timed out. Device sources now validate and apply configurable pixel format,
  resolution, and capture FPS, with MJPEG 640×480 @ 30 FPS as safe defaults.
- A real phone IP-camera app URL and real RTSP camera should be tested when available.
- Existing real DB still has 17 duplicate enabled sample cameras; no rows were changed.
  A verified backup exists under `data/backups/`; user must approve archive/fresh DB vs
  disable-all vs keep-one cleanup.

---

## Post-2.0 Improvements B–F — implementation checkpoint ✅/🧪

**Phase B — browser/WebRTC cameras**
- Added pinned `aiortc==1.15.0` and `qrcode==8.2`, auto-discovered `WebRtcSource`,
  latest-frame push hub, permission-gated publisher page, inline QR/link wizard, camera
  and quality selection, encrypted offer/answer media, revocation, and reconnect.
- Initial tokens expire, are single-use and hashed; rotating reload credentials are also
  hashed. Credentials stay in URL fragments (never HTTP access logs), camera JSON, or
  list APIs. Signaling size/session caps and HTTPS-off-localhost enforcement are tested.
- Shared inference uses non-blocking admission: busy models cause a frame skip, never a
  stale queue. Real aiortc synthetic video and 3-publisher isolation/soak checks pass.

**Phase C — motion and clips**
- Added per-camera MOG2 detector + motion rule plugins and independent `ClipRecorder`.
- Selectable event/motion/continuous modes; bounded pre/post-roll, max length, segmented
  continuous clips, codec fallback, retention/quota/low-disk handling.
- Active clips use partial filenames and atomically finalize; startup removes abandoned
  partials. Events reference finalized clips; shared clips survive until last event is
  removed. Clip API and dashboard player added.

**Phases D/E — gestures and bounded ASL**
- Added optional MediaPipe Tasks hand detector, auto-discovered gesture vocabularies,
  model-free basic gestures, generic detection/help/sequence rules, stable-frame and
  chatter suppression, structured overlay attributes, and offline evaluation tooling.
- Added operator-supplied ONNX `asl_static` adapter scoped to isolated static ASL
  fingerspelling. No model is bundled/downloaded and no accuracy/full-translation claim
  is made. Missing MediaPipe/model files disable only that plugin.

**Phase F — automated hardening**
- Added optional TLS launch config and explicit `scripts/setup_dev_tls.sh` (no silent
  trust-store changes), security/CSP/permission headers, signaling bounds, pairing
  caps/expiry/revoke cleanup, legacy DB upgrade test, clip crash recovery, direct
  three-publisher soak script, and container/runtime storage updates.
- Added persisted recording settings API/UI through the existing JSON `setting` seam;
  runtime mode/retention/quota changes need no schema migration. Per-camera analyze FPS
  and generic detector `camera_ids`/`fps` scope are now honored.
- Validation: **78/78 tests passed**, `pip check`, Python + dashboard/publisher syntax,
  Compose config, 10-second 3-publisher soak, and Docker image build with aiortc/PyAV.

**Final gates still requiring operator hardware/data**
- Two real phone/laptop publishers + host camera under HTTPS with unplug/reload recovery.
- Real motion/recording playback and extended low-disk/restart check.
- Enabled MediaPipe landmarker + licensed gesture/ASL model on clips/live camera;
  signer-disjoint accuracy/latency evaluation.
- Extended three-device all-feature resource soak and final dashboard review.
- Local DB cleanup remains pending explicit destructive-action choice; verified backup exists.

No commit was created because the user did not explicitly request one.

## Interactive testing session — VLM chat, phone IP camera, tuning, UI

**Built**
- Optional vision-language integration (ADR-010 seam): `guardlens/api/vision.py`
  (`/api/vision/ask`, `/api/vision/status`) powers a dashboard "Ask the camera" chat
  panel; `guardlens/vlm.py` + `rules/vlm_watch_rule.py` raise `vlm_alert` events when a
  configured VLM reports keywords (knife/scissors/weapon) off the analysis loop.
- VLM is env/config-only: `GUARDLENS_NVIDIA_API_KEY` + optional `GUARDLENS_VLM_MODEL`
  (default `meta/llama-3.2-11b-vision-instruct`, chosen for ~1s latency vs a slow
  reasoning model that hit free-tier 503s). Keys load from a gitignored `.env`.
- Object detector gained `imgsz` config; model/conf are config-driven (tested n/m).
- Dashboard: per-camera on/off switch, fullscreen, stream reload + self-heal, overlay
  badge, zone draw mode (start/undo/clear + zone list), rule on/off switches, recording
  controls with switch, and a camera chat panel that auto-syncs the camera dropdown.
- Phone used as a camera two ways: verified **IP-camera URL** (network source, works
  over WSL NAT) and **browser/WebRTC** path enabled via dev TLS (`setup_dev_tls.sh`),
  `GUARDLENS_PUBLIC_URL`, and a Windows portproxy for inbound reach.
- `scripts/testing_server.sh` runs a detached local server loading `.env` (key, TLS,
  public URL) so secrets never pass on the CLI.

**Operational notes / honest limits**
- Stock YOLO is limited to 80 COCO classes: pen/"purse" are not labelable; knife and
  scissors exist but are weak on nano. The VLM chat covers arbitrary-object questions.
- The cloud VLM transmits frames to the provider (documented, opt-in).
- WSL USB webcam and NAT inbound both need manual host steps (usbipd attach; portproxy).

**Live manual verification (this environment)**
- Webcam (USB/IP over WSL usbipd), Mall sample, and a phone IP camera all streamed with
  detection overlays.
- Phone **browser/WebRTC pairing verified end to end**: dev TLS cert for the LAN IP,
  `GUARDLENS_PUBLIC_URL`, a Windows `netsh portproxy` (LAN:9443 → WSL:9443) + firewall
  rule, cert trusted on the phone, QR scanned, pairing token consumed, and a `webrtc`
  camera created. (WebRTC frames flow only while the publisher page stays open.)
- VLM "ask the camera" chat answered correctly per-selected-camera on webcam and phone.

**Housekeeping**
- Purged ~2,630 accumulated sample events/snapshots (1.4 GB → ~0) after DB backup;
  scoped the broad `person-watch` rule to a single camera to stop the flood.
- `.env`, `data/tls/`, `*.key`, `data/*.pid`, and `.kiro/` are gitignored; no key is in
  any committable file (verified with `git grep`).

---

## Post-2.0 roadmap (docs/13) — Step 0 + M1a/M1b checkpoint

**Decisions (2026-10-12):** M1 first; React/Vite (ADR-015); agents suggest-only; free cloud
tiers only for now; no duplicated code (single schema module, later a single VLM client).
DB had no duplicate cameras left (already cleaned earlier), so no cleanup was needed.

**Built**
- Fixed `EventStore.delete_evidence` (missing `select` import silently kept unshared clips on
  disk) + regression test.
- `guardlens/schema.py`: one field-schema vocabulary. Normalizes every legacy dialect
  (`float`/`number`, `list[str]`/`array`, `HH:MM`, `point`, enum `values`) into canonical
  fields (label, help, unit, min/max/step, enum choices, widget hint) and validates values.
  Rule/notifier type listings now include `label`, `description`, `fields`; the raw
  `param_schema` is unchanged for back-compat. Built-in rules got labels/help/ranges.
- Server-side validation of rule `params` and notifier config (readable per-field 422s).
- `GET /api/meta` (version, class vocabulary, capabilities, plugin keys); `cors_origins` config.
- `frontend-app/` (Vite + React + TS, pinned deps): typed `api.ts` with single `API_BASE`,
  generic `SchemaForm` (toggle, slider, stepper, chips + class picker, time, enum, key/value,
  click-to-place point/line/polygon canvas — no JSON anywhere), Rules page (create/edit/
  enable/delete), Health page (plain-language camera states). Served at `/app`; classic
  dashboard remains at `/`. Dockerfile gained a Node build stage.

**Verification:** 86 pytest + 5 vitest pass; `tsc --noEmit` clean; production build served
and smoke-tested on a temp server (`/app/`, `/api/meta`, `/api/rules/types`).
**Not yet verified:** visual/browser check of the new UI (no browser in the sandbox).

**Remaining M1c:** Live grid/focus, Events (inline snapshot/clip, filters), Cameras wizard,
zones on camera frame, Faces, Notifiers, Recording, Reports; parity checklist → switch `/`.

---

## Roadmap docs/13 — M1c, M2–M6 built (2026-10-12/13)

**M1c — React screens** (`frontend-app/`, served at `/app/`): Live (grid, focus, fullscreen,
analyze-FPS, self-heal, critical highlight), Events (filter chips, evidence, notes, SSE, alarm,
AI notes, incident report), Cameras wizard + pairing, Rules (schema forms, plain-words drafting,
preview), Zones (draw on camera snapshot), Faces, Notifications (+ quiet hours), Recording,
Reports + charts, Agents + AI connection + privacy, Ask GuardLens chat, Find footage, Security
(login, tokens), Health (+ "needs attention"). Built by parallel worktree agents and merged;
page registry (`pages/registry.ts`) means a screen is one file + one line.
Backend gaps closed on the way: `GET /api/cameras/{id}/snapshot`, `PATCH /api/persons/{id}`,
live `analyze_fps` apply, **SSE no longer replays history on connect** (it re-sounded old
critical alarms), event metadata now carries normalized `boxes`.

**M2 — agent foundation:** `guardlens/vlm_client.py` (single AI client: NVIDIA/Gemini/OpenRouter
free tiers + local Ollama, fallback chain, per-minute/day/camera budgets, circuit breaker, cache,
per-camera "local only"); `guardlens/agents/` (auto-discovered plugins, suggest-only, hourly
budgets, `AgentRun` audit log, `param_schema` → generated forms); `EventStore.add_listener/
annotate` + named SSE `event_updated`; `guardlens/scheduler.py` (retention, nightly report,
agent schedules); `/api/agents`, `/api/privacy`.

**M3 — agents:** event triage (structured verdict, untrusted-scene system prompt, fail-open,
escalate-only *suggestion*), daily briefing (citation-grounded, invented ids stripped, private
cameras excluded, falls back to the structured report), repeats + unusual-hour-of-week flags
(no AI), Ask GuardLens chat (retrieval in code, memory, live frames, analysed frame saved),
`scripts/eval_triage.py` + `evaluation.py` (false-alarm reduction and missed-real rate;
suppression stays off until ≤1% over ≥50 real alerts).

**M4 — search:** `guardlens/search/` OpenCLIP ViT-B/32 (CPU) embeddings of snapshots + object
crops stored in SQLite, hybrid picture + caption query, find-similar. Off until enabled.

**M5 — auth:** scrypt passwords, HttpOnly SameSite cookie sessions, hashed API tokens, login
rate limit, middleware protecting API/streams/snapshots, `GUARDLENS_AUTH_DISABLE=1` recovery,
`docs/14-remote-access.md`. Fixed on the way: naive/aware datetime compare found by tests.

**M6:** natural-language rule drafting with validation + **dry-run replay over stored activity**
(never saves), quiet-hours notification routing, incident-report drafts, `/api/health/issues`.
Fixed on the way: `dispatcher.reload()` edit bug caught by tests.

**Verification:** 145 pytest; frontend vitest + tsc + build per branch; and
`scripts/e2e_smoke.py` against a real server (real YOLOv8n on the sample video → events →
evidence → agents degrade without a key → real CLIP search → login). It caught two real gaps
(object_class events lacked boxes; a wrong endpoint in the script itself).

**Not done / deliberately deferred:** response playbooks (actions need hardware + human-confirm
design; agents stay suggest-only), cross-camera re-ID, YOLO-World/YOLOE open-vocabulary detector
(needs the `clip` package + weights; tracked in docs/13), physical-hardware gates from docs/09.
