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
| **Last completed phase** | docs/13 roadmap M1–M6 built and verified end-to-end (see docs/08 tail) ✅ |
| **Next phase** | Operator review in a real browser; physical gates (docs/09 checklist); optional YOLO-World detector; eval triage on real labelled alerts before enabling any suppression |
| **Working tree** | A–F + VLM/UI work on `main`, being committed; secrets gitignored |
| **Tests** | 163 pytest + 72 vitest; `python scripts/e2e_smoke.py` for the real-server walkthrough |
| **Last updated** | 2026-10-14 — see `docs/15-open-work.md` for the ranked to-do list |

**One-line resume:** server runs via `./scripts/testing_server.sh` (reads gitignored
`.env` for the VLM key + optional TLS). Webcam needs `usbipd attach --wsl --busid 2-7`;
phone works as an IP camera (`http://<phone-ip>:8080/video`) and, over dev HTTPS +
Windows portproxy, as a browser/WebRTC publisher. VLM "ask the camera" chat and the
`vlm_watch` sharp-object rule are live when the key is set.

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
timeout 600 .venv/bin/python -m pytest -q        # expect 86 passed
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

- **Optional MediaPipe caution:** current `mediapipe==1.1.0` declares
  `opencv-contrib-python` 5.x while GuardLens pins OpenCV 4.10. Do not install it into
  the production venv until that OpenCV line is reconciled and revalidated; use an
  isolated environment for model evaluation. The default app remains fully functional
  with `hand_gesture` disabled.
- [x] **Phase 4** — broad rule catalog (zone, loiter, line, crowd, animal, vehicle, …)
- [x] **Phase 5** — face recognition
- [x] **Phase 6** — notifications & analytics
- [x] **Phase 7** — activity log & daily report
- [x] **Phase 8** — hardening & polish


### Post-2.0 phases (implementation complete; physical/model gates noted)

- [~] **A** — source registry/migration/wizard + physical webcam pass; DB cleanup choice pending
- [~] **B** — secure browser/WebRTC publishers built/tested; real multi-device gate pending
- [~] **C** — motion/clip system built/tested; final operator/physical gate pending
- [~] **D** — hand/gesture foundation built; enabled MediaPipe model/live gate pending
- [~] **E** — bounded static-ASL adapter/evaluation built; licensed model accuracy gate pending
- [~] **F** — automated hardening/Docker/soak pass; extended physical release soak pending

Applied product decisions and exact pending checks are in `docs/10-improvement-plan.md` §4–5.
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
- **Validated:** 78 tests, real sample inference, physical WSL webcam, source wizard,
  synthetic aiortc media, 3 isolated publishers, motion/clip playback/recovery, legacy
  migration, final Docker build, container `/health`, events/activity/reports, and clean shutdown.
- **Final physical/model gates:** use configured HTTPS and two phones/laptops plus host
  camera; test unplug/reload, recording playback/retention, then run
  `timeout 3600 .venv/bin/python scripts/soak_publishers.py --seconds 1800 --publishers 3`.
  MediaPipe/ASL checks require an intentionally licensed landmarker/classifier and unseen-
  signer evaluation via `scripts/evaluate_gestures.py`; no model/accuracy is bundled.
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
- **Git:** work is committed on `main`. New UI: `cd frontend-app && npm ci && npm run build` (served at `/app`), `npm run dev` for hot reload, `npm test`.

---

## 7. How to update this file (end of each session)

Before you stop, update:
- **Section 1** table (last completed phase, next phase, test count, date).
- **Section 1** one-line resume (the precise next action).
- **Section 4** checklist (tick the gate you just passed).
- Append the phase details to `docs/08-build-log.md` (built / gate / fixes / commit).

Keep it short. The goal: a cold start should take minutes, not an archaeology dig.

## Final physical/model acceptance checklist

1. Configure `GUARDLENS_SSL_CERTFILE` and `GUARDLENS_SSL_KEYFILE`; open the HTTPS LAN URL.
2. Pair two phone/laptop browsers by QR plus one host/IP camera. Confirm separate moving
   images, overlays, frame ages, revoke, browser reload reconnect, and physical disconnect.
3. Enable recording in `config.yaml`; trigger motion/event clips and confirm pre/post-roll,
   playback/download, restart recovery, retention/quota, and a controlled low-disk test.
4. If gesture support is desired, install a compatible MediaPipe build intentionally,
   provide a licensed Hand Landmarker task model, then enable `hand_gesture`. For ASL,
   also provide a licensed static classifier + labels and evaluate unseen signers with
   `scripts/evaluate_gestures.py`. Do not label it continuous ASL translation.
5. Run an extended resource soak with the actual selected detectors/recording and record
   CPU, RSS, bandwidth, disk growth, reconnects, and cross-camera leakage observations.
6. Choose duplicate DB cleanup: retain one (recommended), disable all, or remove all 17
   `Mall` rows. Backup: `data/backups/guardlens-before-camera-dedup-20261010-191921.db`.

---

## 8. Known limitations & improvement backlog (as of 2026-10-11)

Honest list of what to improve next; none of these block current use.

### Detection accuracy
- Stock YOLOv8n = 80 COCO classes only. **Pen, purse, arbitrary "sharp objects" are
  not labelable.** Options: (a) YOLO-World open-vocabulary detector plugin (prompt by
  text, heavier CPU), (b) custom-trained YOLO on collected/labelled images (needs ~150–
  300 images/class + a GPU/Colab run), run scoped at low FPS so it does not slow live.
- Bigger stock models (m/l) are too heavy on this CPU (~250–400 ms/frame). Keep nano
  live; reserve heavy/custom models for one camera at low analyze-FPS.

### VLM chat
- Depends on a cloud key and transmits frames out; free NVIDIA tier returns 503 under
  load. Consider: a self-hosted VLM later, response caching, and showing the exact frame
  that was analyzed next to each answer.

### Reliability / ops
- WSL USB webcam drops on sleep/restart → must re-run `usbipd attach --wsl --busid 2-7`.
- WSL eth0 IP can change → the Windows portproxy `connectaddress` then needs updating.
- Camera `enabled` state persists across restarts (a prior "off" stays off) — expected,
  but surprised us twice; consider surfacing it clearly in the UI.
- Phone IP-camera URL changes with DHCP; browser/WebRTC avoids that but needs HTTPS.

### UI/UX ideas not yet built
- Show vlm_alert snapshot + answer inline; "Explain this event" button (reuse VLM).
- Per-camera analyze-FPS slider (backend already supports per-detector fps/scope).
- Grid column control + single-camera focus; sound/visual alarm on critical events.
- Auto-revoke/clean stale webrtc cameras whose publisher disconnected.

### Testing still pending
- Real motion/recording playback + low-disk/restart; enabled MediaPipe/ASL model with
  signer-disjoint accuracy; extended multi-device soak.
