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
- Installed CV deps: opencv-python-headless 4.10, numpy 2.1.

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
