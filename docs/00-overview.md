# 00 — Overview

## What we are building

**GuardLens 2.0** is an **AI monitoring assistant** for places like apartment
complexes — an always-on "extra set of eyes" that watches many cameras at once
(something human guards physically cannot do) and gives staff a **daily briefing**
of what happened. It ingests one or more camera streams (webcam, RTSP/IP camera, or
video file), runs computer-vision analysis on each frame, applies a configurable set
of **alert rules**, records **events** (with snapshots) to a database, continuously
builds an **activity log** of what it sees, and can generate a **day-end report**.
Everything is presented through a single-page operator **dashboard** with a live
view, an event timeline, a daily report, and configuration panels.

### Positioning (honest framing)

This is an **assistive monitoring tool**, not a legal or complete replacement for a
security guard. A human guard reasons about novel situations; GuardLens reliably
**detects, records, and summarizes** activity across far more cameras than a person
can watch, and never gets tired. Think "an AI monitor that never blinks, plus a daily
briefing" — genuinely useful for apartments, and achievable on ordinary hardware.

It is a ground-up rebuild of the original prototype, designed to be:

- **Real-world useful** — the alerts map to real security concerns.
- **CPU-first** — runs on a laptop with no GPU; GPU is an optional accelerator.
- **Flexible by design** — new detectors, rules, and notifiers are plugins. The
  core never needs rewriting to add a capability. This is a hard requirement,
  not a nice-to-have (see [`07-extensibility.md`](07-extensibility.md)).

## Why — problems with the original prototype

The original [GuardLens-AI](https://github.com/anshulshukl/Guardlens-ai) was a useful
proof of concept but has concrete problems that block real use:

| # | Problem in the original | Impact | Fix in 2.0 |
|---|------------------------|--------|------------|
| 1 | "Sharp object" alert list includes classes that **don't exist** in the YOLOv8/COCO model (sword, dagger, machete, axe, blade…). | Most alerts can **never fire** — dead code. | Rule engine uses only real model classes; alerts are driven by meaningful rules (zones, loitering, counts), not a hardcoded word list. |
| 2 | History is a **flat JSON file**. | No querying, no filtering, no scale, race-prone concurrent writes. | Proper **SQLite** database via SQLModel; indexed, queryable, upgradeable to Postgres. |
| 3 | YOLO model **reloaded per camera thread**. | Wastes RAM/CPU; slow startup. | Single shared model instance; detection workers reuse it. |
| 4 | Frames shipped as **base64 over WebSocket** for every frame of every camera. | Heavy bandwidth/CPU; doesn't scale past a couple of cameras. | MJPEG stream endpoint + throttled WebSocket; snapshots stored by reference. |
| 5 | **No real event model** — only "sharp objects." | Not what security operators care about. | Zone intrusion, loitering, line-crossing / people counting, crowd threshold, unknown-face detection. |
| 6 | **BLIP VQA** is slow and unreliable on CPU. | Poor answers, blocks the event loop. | Dropped from the default build; may return later as an optional plugin. |
| 7 | **No alert workflow** — events just pile up. | Operators can't triage. | Events have status: `new → acknowledged → resolved`; notifications via webhook. |
| 8 | Everything hardcoded in `main.py`. | Hard to extend or test. | Modular packages; plugin registries for detectors / rules / notifiers. |

## Scope for this build (agreed)

- **Backend-focused** + a **strong single-page dashboard** (extend the existing
  HTML/JS dashboard; no full React rewrite yet).
- **CPU-only** target. No GPU assumed.
- Feature set (the "1–8" list, approved):
  1. Fixed, meaningful object detection (real classes only).
  2. Zone-based intrusion detection.
  3. Loitering detection.
  4. Line-crossing / entry-exit people counting.
  5. Crowd / occupancy threshold alerts.
  6. Proper event system + database.
  7. Alert workflow + notifications (webhook).
  8. Analytics (events over time / by type / by camera).
  9. **Face recognition** (enroll residents; flag unknown visitors) — explicitly requested.

### Expanded vision (apartment "AI guard")

Based on the apartment use-case, the catalog is broader than a fixed list. These are
all delivered as **plugins** (detectors + rules), so the set can grow freely:

- **People** — presence, counting, intrusion, loitering, unknown faces.
- **Animals** — dogs/cats/etc. (real model classes), e.g. "stray animal in lobby."
- **Lost / abandoned objects** — a bag/suitcase that stays still with no owner nearby
  for N seconds (left-luggage detection).
- **Vehicles** — car/bike/truck presence in driveways or restricted areas.
- **Packages / deliveries** — object left at a door for a period (useful for residents).
- **Falls (optional)** — a person who becomes horizontal and stays down (elderly care).
- **After-hours activity** — any person/vehicle during configured quiet hours.

### Day-end report (new subsystem)

GuardLens continuously writes an **activity log** (periodic per-camera scene summaries,
not just alerts) and can produce a **daily report**: a readable briefing of what
happened across all cameras (visitors, animals, packages left, quiet overnight periods,
notable events with snapshots). v1 builds this from **structured data + periodic scene
summaries** (fast, reliable, CPU-friendly). An optional **vision-language enricher** can
later add richer natural-language descriptions (see ADR-010) without changing the core.

## Explicit non-goals (for now)

- No full React/Vite frontend rewrite (dashboard stays single-page HTML/JS).
- No multi-tenant accounts / RBAC in v1 (single operator). Designed so it can be added.
- No cloud deployment / horizontal scaling in v1 (designed not to preclude it).
- No GPU-only models or TensorRT.
- VQA / natural-language "ask the camera" is deferred.

## Reference projects (studied / credited)

- [ageitgey/face_recognition](https://github.com/ageitgey/face_recognition) — MIT.
  Reference for the face-recognition UX (enroll → encode → compare).
- [HackerShackOfficial/Smart-Security-Camera](https://github.com/HackerShackOfficial/Smart-Security-Camera)
  — reference for motion-triggered capture + notification flow.
- [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) and
  [ultralytics/yolov5](https://github.com/ultralytics/yolov5) — detection models.
  **License caution: AGPL-3.0** — see [`06-tech-decisions.md`](06-tech-decisions.md).

- [dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV](https://github.com/dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV)
  — reference for MOG2 motion filtering and motion-triggered clip lifecycle. README
  claims MIT, but no root license file was found during review; do not copy source until
  licensing is verified.
- [kinivi/hand-gesture-recognition-mediapipe](https://github.com/kinivi/hand-gesture-recognition-mediapipe)
  — Apache-2.0 reference for MediaPipe landmarks, normalized keypoints, static TFLite
  classification, and temporal point-history gestures.
- [Kazuhito00/NARUTO-HandSignDetection](https://github.com/Kazuhito00/NARUTO-HandSignDetection)
  — MIT reference for an ONNX/YOLOX hand-sign detector and sequence/chattering logic.
  Its 14 NARUTO signs are fictional and are not a sign-language vocabulary.
