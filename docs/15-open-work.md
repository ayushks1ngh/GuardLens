# 15 — Open work (audit of 2026-10-14)

What is still to be done, ranked. Items marked ✅ were closed in the same audit.

## Done in this audit
- ✅ One UI: the old `frontend/index.html` and `/classic` are removed; `/` redirects to `/app/`.
- ✅ Detectors checked on the real sample video (`python scripts/check_detectors.py`, `tests/test_detectors.py`).
  Finding: the Haar face detector hallucinated 116 "faces" in 60 frames of a faceless scene. Faces must now sit
  inside a detected person (`require_person`, pipeline gate) and the default `min_neighbors` is 8.
- ✅ Real-browser check of the login flow (Playwright + Chromium, https, real keystrokes): create account, sign out,
  sign in, reload all work. Entry page is now `Cache-Control: no-cache`; HSTS only for the configured public host;
  `/api/client-log` cannot forge log lines; startup warns when login is off and the server is network-reachable.
- ✅ CI (`.github/workflows/ci.yml`), lint clean-up, stale agent worktrees removed.

## Backend — still to do
See `docs/16-future-plan.md` for the staged plan and checkboxes.

1. **Schema migrations.** Tables come from `create_all`; any model change breaks an existing `guardlens.db`.
   Add Alembic (or a small versioned-migration table) before the next model change.
2. ✅ **Retention for events and snapshots** — done (`retention.events_days`, default 90; unresolved critical alerts kept).
3. ✅ **Backups** — done (nightly + manual, Settings → Data, `scripts/restore_backup.py`).
4. **Chat latency.** One non-streaming call, 10–20 s on the NVIDIA 11B vision model. Options: SSE/streaming responses,
   downscale the frame before sending, try Gemini Flash (already supported: `GUARDLENS_GEMINI_API_KEY`), cache answers
   per (camera, minute).
5. **Triage suppression** stays OFF until `scripts/eval_triage.py` shows ≤1% missed real alerts on ≥50 labelled alerts.
6. **Face recognition quality.** Haar is a weak detector; a modern one (YuNet / SCRFD ONNX) needs a model download
   (the repo rule is "no implicit downloads", so make it an explicit setup step like the search model).
7. **Hand gestures.** `mediapipe` is not in `requirements.txt` and needs a model file; the detector degrades to "off".
8. **open_vocab detector** needs `pip install git+https://github.com/ultralytics/CLIP.git`.
9. **Deferred by design:** response playbooks (human-confirmed actions) and cross-camera re-identification.
10. **Auth hardening:** per-token scopes, token expiry, audit log of sign-ins, rate limit by account as well as client IP.
11. **Network exposure default.** The server listens on `0.0.0.0` with login off until an admin is created (a warning is
    logged). Consider forcing first-run setup, or defaulting the host to `127.0.0.1`.
12. **Dependency refresh.** `fastapi` 0.115 → 0.143 etc. is pinned and works; update deliberately with the test suite.
13. **Physical gates** from docs/09 (multi-phone soak, MediaPipe accuracy, operator checks) cannot be done in CI.

## Frontend — still to do
- Live detection boxes now carry labels; add tests/visual checks for the Cameras wizard, Faces, Notifications, Recording.
- Chat panel: streaming text and a stop button once the backend streams.
- A Playwright smoke suite in CI (the login flow was verified manually with Playwright; keep it as a script).
