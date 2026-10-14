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
- [x] 4.1 API tokens are read-only or full access and can expire (defaults in the UI: read-only, 90 days; existing tokens stay full/never-expire); read-only tokens are refused on any write and on account/token/audit endpoints; audit log (sign-ins, failures, password/token/login changes; no secrets; 180 days, 10k rows max) shown under Settings → Security; per-account throttle (10 failures / 5 min from any address) on top of the per-address one. (The per-account throttle is keyed by account + address, so a stranger cannot lock the owner out — fixed after review.)
- [x] 4.2 (partly) Remote access: behaviour behind a proxy is covered by automated tests (see docs/14 table). [ ] 👤 one real tunnel session from outside your network — needs your Tailscale/Cloudflare account.
- [x] 4.3 Dependency audit + refresh: pip-audit found 6 advisories in python-multipart 0.0.20 (face-photo upload parsing), several in Starlette 0.41.3 (Host header, multipart DoS, Range DoS, more) and 1 in pytest. Upgraded to fastapi 0.143.1 / starlette 1.3.1 / python-multipart 0.0.32 / pytest 9.0.3. (A first pass at starlette 1.0.1 still had 4 open advisories; the re-audit caught it and 1.3.1 fixed them.) All 227 tests, e2e (48/48 with AI) and the browser suite (15/15) pass; `pip-audit -r requirements.txt` reports none. Weekly `audit.yml` keeps checking. Not fixed: `setuptools` in the dev venv (build tool, not shipped); torch CPU wheels cannot be audited via PyPI.
- Gate: ✅ independent security review of everything since Stage 1 (fresh reviewer, code only). It found 1 high, 2 medium, 5 low issues; all verified by reading/tests and **all fixed**, each with a test that failed before the fix:
  1. HIGH `/ws/overlay` WebSocket skipped login (the HTTP middleware never sees WebSockets) → now checks login, closes 1008.
  2. MEDIUM read-only tokens could download the database backup (password hash, camera passwords, notifier secrets) → all `/api/data/*` need full access.
  3. MEDIUM/LOW anyone could lock the admin out with 10 wrong passwords; unbounded limiter memory → throttle per account+address, empty keys swept, hard cap.
  4. LOW first-run takeover on a network-reachable server + two simultaneous setups both succeeding → one-time setup code for non-local clients, atomic account creation.
  5. LOW `/api/client-log`: terminal control characters, global limit silenceable by one address, body size → sanitised, per-address limit, 8 KB cap.
  6. LOW a password typed into the username box was kept in the audit log → only existing account names are recorded.
  7. LOW face upload read the whole body and trusted image dimensions → bounded read, PNG/JPEG header dimension check (8000 px / 40 MP).
  8. INFO camera Test is a TCP probe of the camera's own address (full-access users only) — accepted. Also: backup-name regex now `fullmatch`.

## Stage 5 — New capabilities (scope decided after Stage 4)
Response playbooks (human-confirmed), cross-camera re-identification, mobile layout + push notifications.
Each gets a short spec the user approves first.
