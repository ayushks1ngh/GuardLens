# 17 — Stage 5 specs (for approval — nothing here is built yet)

Each item says what it is, what it costs, the risk, and a recommendation. Say "approve", "change X" or "skip" per item.
Facts used: the only notifier today is **webhook** (with quiet hours); the dashboard has 4 responsive rules; face
recognition (SFace) and tracking exist per camera; AI is suggest-only by design.

---
## A. Response playbooks (human-confirmed actions)
**What:** when an alert matches a rule, GuardLens can *offer* an action — call a webhook (e.g. turn on a Home Assistant
light/siren, ring a Shelly relay), send a snapshot to a chat/ntfy, or start a longer recording — and a person confirms it.

**How it would work**
- A *playbook* = trigger (rule or alert type + minimum severity + cameras + time window) → one or more *steps*
  (webhook with a template, "send snapshot to notifier X", "record 2 minutes").
- **Default mode: suggest-only.** The alert gets a button "Run: Turn on porch light"; nothing happens until someone presses it
  (works from the dashboard and, later, from a notification link).
- **Auto-run is opt-in per playbook and limited to low-risk steps** (notifications, recording). Anything that touches the
  physical world (sirens, locks) can never auto-run in v1.
- Safeguards: per-playbook cooldown and daily cap, a global kill switch, a dry-run ("what would this do?"), every run
  written to the audit log with who pressed it, and webhooks may only target addresses you list (no open SSRF).
- UI: Settings → Playbooks (plain-language builder, no JSON), a "Run" button on alerts, history list.
- Tests: trigger matching, confirmation required, cooldown/cap, kill switch, SSRF allow-list, audit entry per run.

**Effort:** ~2 sessions. **Risk:** medium (acts on the world) — mitigated by suggest-only default.
**Recommendation:** approve v1 = suggest-only + webhook + snapshot steps; defer auto-run until you have used it for a while.
**Questions:** which devices do you actually want to trigger (Home Assistant? something else)?

---
## B. Cross-camera "same person" (re-identification)
**What:** link a person seen on camera A with the same person later on camera B ("this person walked from the gate to the
garage") and show it on the alert and in a timeline.

**Options**
1. **Face-based linking (recommended first):** reuse SFace embeddings; link tracks whose face embeddings match (threshold 0.5)
   within a time window. Accurate when faces are visible; useless from behind/at a distance.
2. **Appearance-based (clothing/body) re-ID:** needs a person re-ID model (e.g. OSNet, ~10 MB ONNX) — works without faces
   but is much less reliable (same clothes, lighting changes) and raises more false links.
3. Both, face first, appearance only as a weak hint labelled "possibly".

**Privacy and honesty:** opt-in per camera; identities are never named unless the person is enrolled; the UI says
"possibly the same person" with the match strength; no cross-site tracking; data is covered by retention (90 days).
**Effort:** option 1 ~1–2 sessions; option 2 +2 sessions and needs your labelled footage to measure.
**Recommendation:** approve option 1 only; measure on your own footage (benchmark tool) before considering option 2.

---
## C. Mobile layout + push notifications
**What:** the dashboard comfortable on a phone, and alerts that reach the phone when the page is closed.

**How**
- **Mobile layout (low risk):** audit at 390 px wide (nav becomes a bottom bar, Live tiles one per row, chat as a drawer,
  Settings tabs scroll), plus browser tests at phone size. ~1 session.
- **Push:** installable web app (manifest + service worker) with Web Push (VAPID keys generated on the server, subscriptions
  stored per signed-in user, quiet hours respected). Requires **https** and works on Android Chrome; **iOS needs the app added to
  the Home Screen first** (an Apple restriction). Fallback that works today on any phone: the existing webhook → ntfy.sh/Telegram.
  Push is ~2 sessions; I can only test the delivery path with a simulated push service, so 👤 you verify on your phone.
- A notification shows type, camera, time and a small picture, and opens that alert.

**Effort:** mobile ~1 session; push ~2 sessions. **Risk:** low; push content never includes more than a short text + picture.
**Recommendation:** approve mobile layout now (clear value); approve push after you decide whether ntfy via webhook is enough.

---
## Suggested order if you approve all: C (mobile layout) → B1 (face linking) → A (playbooks v1) → C (push).
