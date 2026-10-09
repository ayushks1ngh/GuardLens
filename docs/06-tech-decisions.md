# 06 — Technical Decisions (ADRs)

Short architecture decision records. Each: context → decision → consequences.

---

## ADR-001 — Web framework: FastAPI

**Context:** Need async HTTP + WebSocket/SSE + static serving; original used FastAPI.
**Decision:** Keep **FastAPI + Uvicorn**.
**Consequences:** Familiar, async-friendly, great validation via Pydantic. Carries over
knowledge from the original. No downside for this scope.

---

## ADR-002 — Detection model & the AGPL licensing caution ⚠️

**Context:** The original uses **Ultralytics YOLOv8**. Ultralytics YOLO (v5/v8/11) is
licensed **AGPL-3.0**. AGPL's network clause means that if you distribute the software
*or offer it as a network service*, you may be required to release your complete
corresponding source under AGPL. For a hobby/local tool this is usually fine; for a
product you sell or host for others, it can be a problem.

**Decision:**
- Default to **Ultralytics YOLO** for development quality/speed, **behind the
  `Detector` plugin interface** so it is swappable.
- Document the AGPL obligation prominently.
- Provide a **permissive fallback path**: the detector interface allows plugging a
  non-AGPL model (e.g., an MIT/Apache-licensed detector or a plain ONNX model run via
  `onnxruntime`) without touching the core. Choice is config-driven.

**Consequences:** We get YOLO's quality now, but we are never locked to AGPL — if
licensing becomes a concern, swap the detector plugin and change one config value.
This is a concrete payoff of the plugin architecture.

---

## ADR-003 — Face recognition library

**Context:** User referenced [`face_recognition`](https://github.com/ageitgey/face_recognition)
(MIT). Alternative is `insightface` (ONNX, often more accurate, easy wheels).

Tradeoffs:
- **`face_recognition` (dlib):** MIT, well-known, simple API. **But** installing dlib
  on some systems needs a C++ toolchain/CMake and can be slow/painful; CPU speed is modest.
- **`insightface` (ONNX via onnxruntime):** pip-installable wheels, good CPU performance,
  strong accuracy. Slightly larger model download.

**Decision:** Put face recognition behind the `FaceDetector` plugin interface and
support both. **Default = `insightface`** for easier install and better CPU performance;
`face_recognition` available as an alternate backend (honors the user's referenced repo).
Final default confirmed during Phase 5 after a quick install smoke-test on this machine.

**Consequences:** We satisfy the user's reference while avoiding dlib build pain as the
default. Backend is swappable via config.

---

## ADR-004 — Object tracking: lightweight built-in tracker

**Context:** Loitering and line-crossing need stable IDs across frames. Options: use
YOLO/Ultralytics built-in tracking (ByteTrack), or a small custom IoU/centroid tracker.
**Decision:** Start with a **small IoU/centroid tracker** (pure Python/NumPy) so tracking
is independent of the detector choice (keeps ADR-002 swap freedom) and is CPU-cheap.
Allow upgrading to ByteTrack later behind the same interface.
**Consequences:** Minimal deps, detector-agnostic, good enough for a handful of people
per frame. Can be upgraded without API changes.

---

## ADR-005 — Streaming: MJPEG for video + SSE for metadata

**Context:** Original sent **base64 JPEG of every frame of every camera over a single
WebSocket** — heavy and non-scaling.
**Decision:** Serve video as **MJPEG** (`multipart/x-mixed-replace`) consumed by a plain
`<img>` tag; send only small JSON overlays (alert flag, counts, boxes) over **SSE** (WS fallback).
**Consequences:** Much lower CPU/bandwidth; browser-native video; clean separation of
"pixels" from "events." Slightly more endpoints, documented in the API spec.

---

## ADR-006 — Database: SQLModel on SQLite (Postgres-ready)

**Context:** Original stored history as a flat JSON file (no queries, race-prone).
**Decision:** **SQLModel** (SQLAlchemy + Pydantic) on **SQLite** by default; schema kept
Postgres-compatible; swap via connection URL.
**Consequences:** Real queries, filtering, pagination, analytics. Zero-config local file
DB; a clear path to Postgres with no code changes.

---

## ADR-007 — Flexibility via plugin registries

**Context:** The #1 requirement: never rewrite the core to add a capability.
**Decision:** Three registries — **Detectors**, **Rules**, **Notifiers** — with stable
interfaces and a JSON `params`/`config` convention so new types need **no schema migration**.
**Consequences:** New capabilities = new plugin file + config. Enforced as a gate check
every phase (see `05-roadmap.md`). This is the backbone of the whole design.

---

## ADR-008 — Keep the single-page HTML/JS dashboard (for now)

**Context:** User wants to keep the current frontend style, add UI only as features need it.
**Decision:** Extend the existing **single-page HTML/CSS/JS** dashboard; talk to the API
only. Defer any React/Vite rewrite.
**Consequences:** Faster delivery, continuity with the original look. If the UI grows
complex, we can migrate to a component framework later without backend changes (the API
contract is the stable boundary).

---

## ADR-009 — Config-driven everything

**Context:** Original hardcoded classes, FPS, thresholds in `main.py`.
**Decision:** All of it (cameras, model, analyze-FPS, paths, thresholds, enabled plugins)
comes from `config.yaml` + env overrides, validated at startup.
**Consequences:** No code edits to tune behavior; environments differ by config only;
secrets come from env, never committed.

---

## ADR-010 — Daily report: structured-first, VLM-optional

**Context:** The product should produce a day-end briefing of "everything that
happened." A truly free-form understanding of any moment needs a vision-language
model (VLM), which is slow on CPU-only hardware.

**Decision:**
- Introduce a **`ReportGenerator` plugin interface** and an **activity sampler** that
  writes periodic per-camera scene summaries to `activity_log`.
- Default **`StructuredReportGenerator`**: builds the briefing deterministically from
  `activity_log` + `event` data (templated narrative). Fast, reliable, fully CPU-friendly.
- Keep a seam for an optional **`VlmReportEnricher`** that adds natural-language scene
  descriptions later — running only on **sampled keyframes / events** (not every frame),
  and optionally via a **cloud VLM API** so richer reports are possible without a GPU.

**Consequences:** We ship a solid, accurate report now with zero GPU dependency, and
richer narrative is a drop-in upgrade later with no change to callers or the API. The
report quality scales with hardware/budget without re-architecting.

---

## ADR-011 — Broad detector/rule catalog as plugins (no fixed list)

**Context:** The apartment "AI guard" must detect "most things" — people, animals,
lost/abandoned objects, vehicles, packages, falls, after-hours activity — and must not
be limited to a fixed set now or in the future.

**Decision:** Treat the catalog as an **open set of plugins**. People/animal/vehicle/
object detection come from the object detector's real classes; higher-level behaviors
(abandoned object, package-left, fall, after-hours) are **Rule plugins** composed over
detections + tracks. New categories = new plugin + config, never a core/schema change.
The API exposes available types + param schemas so the dashboard renders them
dynamically.

**Consequences:** The catalog can grow indefinitely without touching the core, the DB
schema, or the UI code. This directly satisfies the "keep it open to change long-term"
requirement.

---

## Open questions (to confirm during build)

- **OQ-1:** Final face backend default (insightface vs face_recognition) — decided after
  Phase 5 install smoke-test on this CPU-only machine.
- **OQ-2:** Short **clip** recording (not just snapshots) — snapshots in Phase 3,
  optional clips as a later enhancement.
- **OQ-3:** Whether to adopt ByteTrack over the custom tracker if accuracy is insufficient.
- **OQ-4:** Activity-log sampling interval (e.g. every 5–10s/camera) and retention window.
- **OQ-5:** Optional VLM enricher via a local small model vs a cloud API — revisit after
  the structured report works.
