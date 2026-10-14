# 16 — Future plan (finalized 2026-10-14)

Working rules: small slices, each = one problem + one fix + tests + one direct push to `main`; real-browser check for
every UI change; `docs/15-open-work.md` is the live status list; ask the user only for risky/irreversible things, big
scope choices, or hardware. Defaults chosen: Stage 1 first, retention 90 days, backups nightly/14 days.

## Stage 1 — Don't lose data
- [x] 1.1 Backups: nightly + "Back up now", prune after 14 days (newest 3 kept, foreign files never touched), download, restore script.
- [x] 1.2 Retention: events + pictures/clips older than 90 days removed; unresolved critical alerts always kept; "Clean up now".
- [x] UI: Settings → Data (backups, policies in plain words, disk use).
- [ ] 1.3 Migrations: versioned schema upgrades (Alembic or a small migration table) with a baseline for the current database.
- [ ] 1.4 First-run safety: network access requires an admin account (listen on 127.0.0.1 until one exists).
- Gate: tests restore a backup and upgrade an old-schema copy of the real DB; retention proven not to delete protected alerts.

## Stage 2 — Smooth daily use
- [ ] 2.1 Chat speed: streaming replies, smaller frame, model picker (NVIDIA / Gemini Flash). Target first words < 3 s.
- [ ] 2.2 Cameras: "Test this camera" with plain diagnosis; phone setup guide; webcam auto-attach helper (usbipd). 👤 hardware check.
- [ ] 2.3 Live polish: chat hint overlap, fullscreen/focus, empty states that say which camera is off and why.
- [ ] 2.4 Browser smoke suite (Playwright) in CI: login, Live, Settings tabs, chat.
- Gate: browser suite green in CI; 👤 webcam and phone show live video.

## Stage 3 — Detection quality
- [ ] 3.1 Better faces (YuNet/SCRFD as an explicit setup step). 👤 a few consenting test photos.
- [ ] 3.2 Accuracy benchmark on labelled footage (misses + false alarms per detector).
- [ ] 3.3 Triage evaluation on ≥ 50 labelled alerts; suppression stays off unless ≤ 1% real alerts missed.
- [ ] 3.4 Optional detectors (gestures, open-vocab) as one-command installs.
- Gate: benchmark report committed under docs/.

## Stage 4 — Trust and security
- [ ] 4.1 Token scopes + expiry, sign-in audit log, per-account rate limits.
- [ ] 4.2 Remote access (Tailscale / Cloudflare tunnel) verified end to end.
- [ ] 4.3 Dependency refresh behind the full suite.
- Gate: /security-review on the diff with no open findings.

## Stage 5 — New capabilities (scope decided after Stage 4)
Response playbooks (human-confirmed), cross-camera re-identification, mobile layout + push notifications.
Each gets a short spec the user approves first.
