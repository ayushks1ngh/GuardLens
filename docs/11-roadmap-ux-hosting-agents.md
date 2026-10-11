# 11 — Roadmap: UX, Hosting, Agents & Improvements

**Status:** Planning only. Nothing here is built yet. This captures the ideas from the
2026-10-11/12 working sessions so they are not lost. Read, prioritize, then we turn
chosen items into phased work with acceptance gates (like `docs/05-roadmap.md`).

**Guiding invariant (unchanged):** every addition is a plugin + config + schema, never a
core rewrite. Nothing new may be able to break the whole project. Agents and UI follow
the same Detector/Rule/Notifier/Source plugin discipline already in place.

---

## 1. Hosting & deployment

### The hard constraint
GuardLens's backend is an **always-on process** (camera capture threads, YOLO inference,
WebRTC peers, MJPEG/SSE streams). Cameras are **on the local network** (`/dev/video*`,
`172.26.21.x`). This means:

- **Vercel / Netlify / serverless CANNOT run the backend.** No persistent processes, no
  long-lived connections, short function timeouts, no continuous CPU/GPU, no LAN access
  to cameras. They can only host the **frontend**.
- The **engine must run where the cameras are** (this PC, a home server, a mini-PC, a
  Raspberry Pi, etc.).

### Options
- **Option A — All local + secure tunnel (recommended first).** Backend and UI both
  served from the local machine (as today). For remote access, use **Cloudflare Tunnel**
  or **Tailscale** instead of fighting serverless limits. Simplest, most private, cameras
  always reachable, UI always matches backend.
- **Option B — Split (UI on Vercel, backend local via tunnel).** Nicer public URL, but
  adds CORS, a stable public backend endpoint, auth, and the UI is dead when the machine
  is off. More moving parts, same backend location requirement.
- **Reality:** Vercel = UI only, always. The engine stays local in both options.

### Work to become "split-ready" (do regardless of A/B)
- Single `API_BASE` constant in the frontend (currently 37 same-origin `/api/...` calls,
  no hardcoded host — clean, one central change).
- CORS configuration on the backend (allow the UI origin only).
- A small `/api/meta` for the UI to discover backend capabilities/version.

### Prerequisites before ANY non-localhost exposure
- **Authentication** (none today): login + API tokens/sessions. Non-negotiable.
- **TLS** (dev cert flow exists via `scripts/setup_dev_tls.sh`; use a real CA/reverse
  proxy or the tunnel's TLS in production).
- Privacy review: the VLM features transmit frames to an external provider.
- Licensing: Ultralytics YOLO is AGPL-3.0 (ADR-002) — matters if hosted as a service.

### Suggested hosting phases
1. Keep all-local; add `API_BASE` + CORS (split-ready, zero behavior change).
2. Add auth (login + tokens).
3. Add secure remote access via Cloudflare Tunnel / Tailscale.
4. (Optional) Host the UI on Vercel pointed at the tunneled backend.

---

## 2. Frontend: polish vs rewrite

Two paths; decide before large UI investment.

- **Polish the current single-page HTML (ADR-008).** Fast, no new deps, continuity.
  Good for incremental UX wins now.
- **Rewrite as React/Vite component app.** Much better for complex UX, schema-driven
  forms, and Vercel hosting. Bigger effort; supersedes ADR-008. The REST API is the
  stable boundary, so a rewrite needs **no backend change**.

**Recommendation:** do the UX overhaul (§3) on the current HTML now for immediate value;
choose React only if we commit to Vercel hosting + heavier UI. Keep the API contract
stable so either path works.

---

## 3. UX / UI overhaul (the main pain point)

**Problem:** the Settings/Rules areas expect users to type numbers and raw JSON and to
understand code. A dashboard user should never see JSON.

### Principles
- **Config as data, not code.** Every configurable thing (rules, detectors, recording,
  notifiers, agents) exposes a `param_schema`; the UI **generates friendly forms** from
  it. Add a capability → its settings form appears automatically. No JSON textareas.
- **Plain language + help text** on every control; no code/keys visible.
- **Guided flows** (the Add Camera wizard is the model to extend everywhere).

### Concrete UI work
- **Schema-driven form renderer:** booleans→toggles, numbers→sliders/steppers with
  units, enums→dropdowns, arrays→chip pickers. Replace the rule-params JSON textarea.
- **Settings redesign:** labeled cards, toggles, sliders; remove raw number/JSON inputs.
- **Per-camera controls** (started): on/off switch, fullscreen, stream reload/self-heal,
  overlay badge. Add: analyze-FPS slider (backend already supports per-detector fps),
  grid column control (1/2/3), single-camera focus view.
- **Events UX:** inline snapshot + (for `vlm_alert`) the VLM answer; "Explain this event"
  button (reuses the VLM); filters as chips; sound/visual alarm on critical.
- **Vision chat:** show the exact analyzed frame beside each answer; keep the clear
  "which camera am I asking" indicator (added).
- **Status/health panel:** camera freshness, recorder state, VLM availability, publisher
  status — human-readable, not raw JSON.
- **Accessibility:** labels, focus states, keyboard nav, color-contrast on alerts.

---

## 4. Agents

**Definition split (important):**
- **VLM reasoning agents** — LLM + camera data + tools. Powerful, but each action is a
  cloud call (latency + cost); the free NVIDIA tier 503s under light load. Use
  event-triggered or on-demand, **never per-frame**.
- **Deterministic automation agents** — local, instant, free, never fail. Underrated.
- **Background workers** — periodic monitor/summarize loops.

### Architecture (keeps the invariant)
Add an **`Agent` plugin registry** mirroring Detector/Rule/Notifier:
- Each agent = a self-contained plugin with a declared **capability + param_schema**,
  auto-discovered, **toggle on/off in the UI**, with a **bounded execution budget**
  (max calls/min, cooldowns) so it can never flood the CPU or the cloud quota.
- Agents are **event-triggered or on-demand/scheduled**, never per-frame.
- Agents **degrade gracefully**: if the VLM/key is absent, the agent disables itself and
  nothing else breaks.
- Guardrail setting per agent: **suggest-only** vs **allowed-to-act** (record/notify).

### Recommended agent set (value-per-effort on this hardware)

**Tier 1 — reuse existing VLM, occasional calls (recommended first):**
- **A. Scene Q&A agent** — the chat, upgraded with short conversation memory and
  cross-camera questions ("which camera has a person now?"). High value, low effort.
- **B. Event triage agent** — on each event, ask the VLM "describe this; how serious;
  real threat or false alarm?" and attach a plain-language summary + confidence to the
  event. Turns raw boxes into "person left a bag near the door at 11pm." One call/event.
- **C. Daily briefing agent** — natural-language end-of-day summary from the day's
  events/activity ("Quiet day. 3 deliveries, one unknown face at 2pm, no overnight
  alerts."). Runs once/day. Reuses the report generator seam (ADR-010).

**Tier 2 — deterministic, free, instant:**
- **D. Watch/automation agent** — plain-language automations ("person in zone after
  10pm → alert + record + notify"). A friendly front-end over the rule engine. No cloud.
- **E. Notification routing agent** — choose channel by severity (log / push / webhook).

**Tier 3 — heavier / more guardrails (later):**
- **F. Natural-language setup agent** — "watch my front door for packages" → creates the
  camera/zone/rule. Great UX; needs careful LLM→config mapping + confirmation guardrails.
- **G. Search agent** — "show everyone who came between 2–4pm" → mostly deterministic DB
  queries with an LLM parsing the question.

### Explicitly avoid (for now)
- Per-frame LLM agents (latency/cost death on free tier).
- Autonomous agents that act destructively (delete/arm/disarm) without confirmation.
- Anything requiring a cloud LLM budget not yet provisioned.

### Open decisions for agents
1. **Cloud budget/appetite** — Tier 1 is occasional calls (OK on free tier); heavier
   needs a paid key. Which end?
2. **Act vs suggest** — may agents act automatically (record/notify/arm) or only
   suggest/answer and wait for confirmation? Sets guardrail scope.
3. **Which set first** — recommended: **A (upgraded) + B + C + D**.

---

## 5. Detection accuracy backlog

Stock YOLOv8n = 80 COCO classes only. **Pen, purse, arbitrary "sharp objects" are not
labelable** by it; knife/scissors exist but are weak on nano. Bigger stock models
(m/l) are too heavy on this CPU (~250–400 ms/frame).

Options (run any heavy/custom model **scoped to one camera at low FPS** so live stays fast):
- **YOLO-World open-vocabulary plugin** — detect by text prompts ("pen", "purse",
  "blade"), no training. Heavier CPU; best quick path to arbitrary objects.
- **Custom-trained YOLO** — most accurate for your exact items; needs ~150–300 labelled
  images/class + a GPU/Colab training run. Plugin side is trivial (point weights via
  config). Data collection is the real work.
- **Pre-trained specialized models** (e.g. knife/weapon from HuggingFace/Roboflow) —
  verify license + quality before integrating.
- **VLM as the "any object" answer** — already works: ask the chat "is there anything
  sharp?" instead of maintaining a custom always-on detector.

---

## 6. Reliability / ops backlog

- **WSL USB webcam** drops on sleep/restart → re-run `usbipd attach --wsl --busid 2-7`.
- **WSL eth0 IP** can change → Windows `netsh portproxy connectaddress` needs updating;
  consider a helper script or mirrored-networking mode.
- **Camera `enabled` state persists** across restarts (a prior "off" stays off) —
  expected but surprised us twice; surface it clearly in the UI.
- **Phone IP-camera URL** changes with DHCP; browser/WebRTC avoids that but needs HTTPS.
- **Stale WebRTC cameras** whose publisher disconnected should auto-clean or show
  "waiting for publisher" clearly.
- **Server restart vs open streams:** browser MJPEG/SSE connections kept the old process
  alive on shutdown; the detached `scripts/testing_server.sh` + PID handling mitigates
  this. A proper service manager (systemd/pm2-style) would be cleaner.

---

## 7. Security & privacy backlog

- **Auth** before any non-localhost exposure (login + tokens).
- **Secrets:** keys live only in gitignored `.env`; never commit. (Enforced; verified
  with `git grep` before pushes.) Rotate any key that was ever shared.
- **VLM privacy:** chat/triage send frames to an external provider — make this explicit
  and per-camera opt-in; consider a self-hosted VLM later.
- **CORS** locked to the UI origin when split.
- **Rate limits** on vision/pairing endpoints (pairing already bounded).

---

## 8. Testing still pending (from prior phases)

- Real motion/recording playback + low-disk/restart recovery on hardware.
- Enabled MediaPipe/ASL model with signer-disjoint accuracy/latency evaluation.
- Extended multi-device soak with recording + enabled detectors.

---

## 9. Suggested overall order (proposal, not locked)

1. **UX overhaul (§3)** on current HTML — schema-driven forms, no JSON, friendly
   Settings. Immediate value, low risk.
2. **Split-ready (§1)** — `API_BASE` + CORS, no behavior change.
3. **Agent registry + Tier-1 agents (A/B/C/D)** — reuse VLM, bounded budgets.
4. **Auth (§7)** — required before remote.
5. **Remote access via tunnel (§1)**; optional UI-on-Vercel after.
6. **Accuracy (§5)** — YOLO-World or custom model, scoped low-FPS.
7. Ongoing: reliability (§6), pending tests (§8).

Each item ships as additive plugins/config with its own acceptance gate; nothing above
requires rewriting the core.

---

## 10. Decisions needed from the user (to turn this into a build plan)

1. Hosting: all-local-with-tunnel (A) or split UI-on-Vercel (B)?
2. Frontend: polish current HTML, or rewrite as React/Vite?
3. Agents: cloud budget (free/occasional vs paid), act-vs-suggest, and which set first?
4. Accuracy: YOLO-World (no training) vs custom-trained (needs data+GPU)?
5. First milestone to build next?
