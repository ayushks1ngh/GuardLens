# 16 — Future plan (finalized 2026-10-14)

Working rules: small slices, each = one problem + one fix + tests + one direct push to `main`; real-browser check for
every UI change; `docs/15-open-work.md` is the live status list; ask the user only for risky/irreversible things, big
scope choices, or hardware. Defaults chosen: Stage 1 first, retention 90 days, backups nightly/14 days.

## Stage 1 — Don't lose data
- [x] 1.1 Backups: nightly + "Back up now", prune after 14 days (newest 3 kept, foreign files never touched), download, restore script.
- [x] 1.2 Retention: events + pictures/clips older than 90 days removed; unresolved critical alerts always kept; "Clean up now".
- [x] UI: Settings → Data (backups, policies in plain words, disk use).
- [x] 1.3 Migrations: `guardlens/migrations.py` — version table, automatic backup before an upgrade, safe column repair, one transaction per numbered step (rolled back on failure). To change the schema: edit the model; if repair is not enough, append a `Migration`.
- [x] 1.4 First-run safety (revised): while no admin exists, anything relayed by a proxy/tunnel (X-Forwarded-For, CF-Connecting-IP, Tailscale headers) is refused with 403, so nobody can claim the admin account over the internet. NOT "localhost only": on WSL2/Docker your own browser arrives from a non-loopback address and would be locked out. Health now warns (not just informs) when login is off and the server is network-reachable, and asks for a backup after 2 days without one.
- Gate: ✅ met — tests restore a backup, upgrade an old-schema database (data kept, backup taken first), roll back a failing step, and prove retention spares protected alerts.

## Stage 2 — Smooth daily use
- [x] 2.1 Chat speed: streaming replies (`POST /api/assistant/chat/stream`, SSE; provider fallback before the first word; broken streams keep the words received). Measured in real Chromium: first words 0.5–0.7 s (was 8–20 s for the whole answer); the provider's free-tier queue can still spike (one run took 8.5 s). Image size was measured and is NOT the bottleneck. Model picker deferred: set `GUARDLENS_GEMINI_API_KEY` to add Gemini Flash to the fallback chain.
- [x] 2.2 Cameras: Settings → Cameras → Test runs `POST /api/cameras/{id}/test` (switched off / stalled / missing device + WSL usbipd steps / unreachable host:port / silent stream / waiting browser / missing file) and says what to do; Live tiles that are on but offline get "Why isn't it working?". [ ] 👤 phone setup guide + usbipd auto-attach helper — pending your hardware.
- [x] 2.3 Live polish: chat hint spacing; offline tiles link to the camera test; off tiles say they are switched off.
- [x] 2.4 Browser smoke suite: `scripts/browser_smoke.py` (12 steps, real Chromium) + a `browser` job in CI. Install: `pip install -r requirements-browser.txt && playwright install chromium`.
- Gate: browser suite green in CI; 👤 webcam and phone show live video.

## Stage 3 — Detection quality
- [x] 3.1 Better faces: YuNet backend (`python scripts/setup_face_model.py`, checksum-pinned, MIT model); falls back to Haar with its person-gate and a Health warning when not installed. Measured: group photo 29/29 faces (Haar 24, looser boxes); CCTV sample 0 false faces (Haar default 116). [ ] 👤 enrolment test with a few consenting real photos.
- [x] 3.2 Accuracy benchmark tool: `scripts/benchmark_detectors.py` (frames → draft labels → you correct → precision/recall/F1 per class), maths tested; first report `docs/benchmarks/2026-10-14-faces.md` (counts). [ ] 👤 label ~40 frames of your own cameras for real per-camera numbers.
- [x] 3.3 Triage evaluation plumbing: "Real alert" / "False alarm" buttons on every alert (`PUT /api/events/{id}/feedback`), progress counter under Settings → AI helpers → Alert triage, `scripts/eval_triage.py` reads your judgements from the database. Suppression stays OFF unless ≥ 50 real alerts judged and ≤ 1% would be hidden. [ ] 👤 judge alerts as they come in.
- [x] 3.4 Optional detectors: `scripts/setup_optional.py` shows what is ready and the exact next step; `--hand-model` downloads the MediaPipe hand model with a pinned checksum (shared verified downloader `guardlens/models.py`). Installing `mediapipe` itself stays a deliberate manual step (it ships its own OpenCV).
- Gate: ✅ report committed (docs/benchmarks/); per-camera numbers wait for your labels.

- [x] 3.5 (found during 3.1) Face recognition: the old "who is it" comparison was a 32×32 pixel vector. Replaced by SFace on YuNet-aligned faces (threshold 0.5; measured 98.9% same-person / 0.25% stranger matches, docs/benchmarks/); old enrolments re-embedded automatically; falls back to pixels with a Health warning if the model is missing.

## Stage 4 — Trust and security
- [ ] 4.1 Token scopes + expiry, sign-in audit log, per-account rate limits.
- [ ] 4.2 Remote access (Tailscale / Cloudflare tunnel) verified end to end.
- [ ] 4.3 Dependency refresh behind the full suite.
- Gate: /security-review on the diff with no open findings.

## Stage 5 — New capabilities (scope decided after Stage 4)
Response playbooks (human-confirmed), cross-camera re-identification, mobile layout + push notifications.
Each gets a short spec the user approves first.
