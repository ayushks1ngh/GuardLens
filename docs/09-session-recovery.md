# 09 — Session Recovery

**Purpose:** Pick up this build quickly after a break or an expired session, with no
memory of the previous conversation. Read this first; it tells you *where we are* and
*exactly how to resume*. Keep it current at the end of every working session.

> The agent has **no cross-session memory**. Everything needed to continue must live in
> the repo — this file plus `docs/08-build-log.md` are the source of truth.

---

## 1. 30-second status

| Field | Value |
|-------|-------|
| **Last completed phase** | Improvement Phase A implementation ✅; hardware/cleanup gate pending |
| **Next phase** | User-check source wizard + physical/phone URL; approve duplicate DB cleanup |
| **Working tree** | Phase A implemented on `main`; hardware/cleanup gate pending |
| **Tests** | 54/54 passing (47 baseline + 7 Phase A) |
| **Last updated** | 2026-10-10 |

**One-line resume:** run the isolated Phase A UI, verify the source wizard with the
sample plus any available webcam/IP-phone URL, then decide how to clean the old DB's 17
duplicate sample cameras. Do not begin Phase B until Gate A's physical check and cleanup
choice are recorded in `docs/10-improvement-plan.md`.

---

## 2. How to re-orient (do this on every return)

1. **Read the plan + state** (in order):
   - `docs/05-roadmap.md` — the phased plan and every acceptance **gate**.
   - `docs/08-build-log.md` — what was actually built per phase + fixes (newest at bottom).
   - This file (section 1) — the one-line "next step".
2. **Verify the tree is clean and tests pass** (see commands below). If red, fix before
   building anything new.
3. **Re-read the design seams before writing plugins:**
   `docs/02-architecture.md` (components + data flow) and
   `docs/07-extensibility.md` (the Detector/Rule/Notifier interfaces — the stable contract).
4. **Honor the flexibility invariant** (section 5) for anything you add.

### Verification commands (all time-boxed so nothing hangs)
```bash
cd /home/ayush/GuardLens
git log --oneline -10
git status
timeout 480 .venv/bin/python -m pytest -q        # expect 54 passed
timeout 30  .venv/bin/python -c "import cv2, torch; print(cv2.__version__, torch.__version__)"
timeout 30  .venv/bin/pip check
timeout 30  docker compose config
```

> **Testing/running rule:** always wrap potentially long or blocking commands in
> `timeout` (and avoid long-running background servers in the loop) — verification is
> via the deterministic pytest suite. This mirrors how Phase 0/1 were gated.

---

## 3. Reference repos (user-provided inputs to the build)

These are the external repos the build draws from. Full rationale in
`docs/06-tech-decisions.md` (ADRs) and `docs/00-overview.md`.

| Repo | Used for | Phase | Decision ref |
|------|----------|-------|--------------|
| [ultralytics/ultralytics](https://github.com/ultralytics/ultralytics) | Default object detector (YOLOv8), **behind the `Detector` plugin** | 2 | ADR-002 (AGPL caution; swappable) |
| [ultralytics/yolov5](https://github.com/ultralytics/yolov5) | Same YOLO family; interchangeable detector backend | 2 | ADR-002 |
| [ageitgey/face_recognition](https://github.com/ageitgey/face_recognition) | Optional replacement `FaceDetector` backend (MIT); OpenCV baseline is default | 5 | ADR-003 |
| [HackerShackOfficial/Smart-Security-Camera](https://github.com/HackerShackOfficial/Smart-Security-Camera) | Conceptual reference for monitoring/alerts (superseded by ADR-005 MJPEG+SSE) | — | `00-overview.md` |
| [dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV](https://github.com/dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV) | MOG2 motion filtering + motion clip lifecycle; README says MIT but license file was not found | Proposed C | ADR-013 / plan §2 |
| [kinivi/hand-gesture-recognition-mediapipe](https://github.com/kinivi/hand-gesture-recognition-mediapipe) | Apache-2.0 MediaPipe landmarks, static and temporal gesture classifiers | Proposed D/E | ADR-014 / plan §2 |
| [Kazuhito00/NARUTO-HandSignDetection](https://github.com/Kazuhito00/NARUTO-HandSignDetection) | MIT ONNX/YOLOX sign detector and sequence smoothing; not real sign language | Optional D/E | ADR-014 / plan §2 |

---

## 4. Phase checklist (tick as gates pass)

- [x] **Phase 0** — skeleton, config, DB models, `/health`, dashboard shell
- [x] **Phase 1** — capture workers, camera CRUD, MJPEG+SSE, live grid
- [x] **Phase 2** — object detector + tracker + detector/rule registries + rule engine
- [x] **Phase 3** — events, evidence, alert workflow
- [x] **Phase 4** — broad rule catalog (zone, loiter, line, crowd, animal, vehicle, …)
- [x] **Phase 5** — face recognition
- [x] **Phase 6** — notifications & analytics
- [x] **Phase 7** — activity log & daily report
- [x] **Phase 8** — hardening & polish


### Proposed post-2.0 phases (not started)

- [~] **A** — source registry/migration/wizard built; physical webcam + DB cleanup pending
- [ ] **B** — secure browser/WebRTC phone and laptop publishers
- [ ] **C** — MOG2 motion and pre/post-roll clip recording
- [ ] **D** — MediaPipe hand/gesture plugin foundation
- [ ] **E** — explicitly chosen sign-language vocabulary/model and evaluation
- [ ] **F** — multi-device soak, security, migration, and release hardening

Approval decisions are in `docs/10-improvement-plan.md` §5.
---

## 5. Flexibility invariant (never violate — checked every phase)

1. New **detector / rule / notifier** = new file + config, **never** a core edit.
2. New rule params ride in the **JSON `params`** column — **no DB migration**.
3. New rule types are **auto-discovered** by the API and rendered by the UI from their
   `param_schema` — the dashboard never hardcodes rule types.
4. Thresholds, model choice, analyze-FPS, and paths stay **config-driven**.

If a change would break any of these, fix the seam first, then make the change.

---

## 6. Post-roadmap facts and likely next work

- **Run:** `./run.sh` locally or `docker compose up --build`; open port 8080.
- **Validated:** 47 tests, real sample inference, two concurrent cameras, final Docker
  build, container `/health`, MJPEG, events/activity/reports, and clean shutdown.
- **CPU defaults:** YOLOv8n + OpenCV face baseline. Model weights download on first use;
  Compose persists them at `/app/models/yolov8n.pt`.
- **Face accuracy:** OpenCV embeddings are a deterministic baseline, not a biometric-grade
  system. The highest-value upgrade is an InsightFace/other backend plugin tested on the
  actual cameras, lighting, and viewing angles.
- **Tracking/rules:** The custom tracker and heuristic fall/abandoned/package rules are
  deliberately lightweight. Tune config against real clips before adding complexity.
- **Licensing:** Ultralytics is AGPL-3.0; revisit ADR-002 before commercial/network use.
- **Known warning:** pytest shows one upstream Starlette/AnyIO deprecation warning; it is
  non-blocking and should be revisited during a coordinated FastAPI/Starlette upgrade.
- **Git:** no commit was created because the user did not explicitly request one.

---

## 7. How to update this file (end of each session)

Before you stop, update:
- **Section 1** table (last completed phase, next phase, test count, date).
- **Section 1** one-line resume (the precise next action).
- **Section 4** checklist (tick the gate you just passed).
- Append the phase details to `docs/08-build-log.md` (built / gate / fixes / commit).

Keep it short. The goal: a cold start should take minutes, not an archaeology dig.
