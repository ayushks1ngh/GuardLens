# 13 — Build Roadmap (post-2.0): UX, Agents, Search, Remote

**Status:** Plan agreed in part (2026-10-12). Decided: **M1 first**, frontend as a
**React/Vite rewrite** (supersedes ADR-008). Still open: agent act-vs-suggest, cloud
provider/budget, duplicate `Mall` camera cleanup. Research basis:
[`12-agents-research.md`](12-agents-research.md); earlier ideas: [`11-…`](11-roadmap-ux-hosting-agents.md).

Same discipline as [`05-roadmap.md`](05-roadmap.md): each milestone ends at a testable 🎯
gate; the system stays runnable throughout; the flexibility invariant
([`09` §5](09-session-recovery.md)) is re-checked at every gate.

---

## Step 0 — Housekeeping (~½ day)

- Fix `EventStore.delete_evidence` missing `select` import (`events/store.py:119`) — clip
  files are never deleted today; add a regression test.
- ADR-015: React/Vite dashboard supersedes ADR-008.
- Refresh `09-session-recovery.md` (stale "no commit created" notes).
- Duplicate `Mall` cameras: **waiting on user** (keep one / disable all / remove all; backup exists).

🎯 Gate 0: suite green incl. new test; docs consistent.

---

## M1 — No-JSON UX (React/Vite)

**1a. Backend schema contract** (foundation for every form, including agents later)
- One field-schema vocabulary for rules, detectors, notifiers, recording, agents:
  `type`, `label`, `help`, `unit`, `min/max/step`, `enum` (+labels), `default`, `required`,
  `widget` hint (`class_picker`, `zone_picker`, `line_draw`, `time_window`, `secret`).
- Normalizer keeps legacy schemas (`"float"`, `"list[str]"`, `"HH:MM"`) working — no plugin edits required.
- **Server-side validation** of rule `params` / notifier config against schema (none today).
- `GET /api/meta`: version, detector class vocabulary, enabled capabilities, VLM availability.
- CORS + configurable origin (split-ready).

**1b. Frontend scaffold**
- `frontend-app/` — Vite + React + TypeScript; typed API client with a single `API_BASE`.
- FastAPI serves the build at `/app`; old dashboard stays at `/` until parity.
- Docker build stage for the frontend.

**1c. Screens**
- `SchemaForm` renderer (toggles, sliders with units, dropdowns, chip pickers, canvas widgets).
- Live: grid columns 1/2/3, focus view, overlay, fullscreen, plain-language camera
  states (disabled / waiting for publisher / stale), per-camera analyze-FPS slider.
- Events: filter chips, inline snapshot + clip, ack/resolve/notes, critical alarm.
- Rules & zones: schema forms; zone polygon and line drawn on the camera frame.
- Cameras (port source wizard + WebRTC pairing), Faces, Notifiers (+ test send),
  Recording, Reports, Health (human-readable).
- Accessibility: labels, focus, keyboard nav, contrast.

🎯 Gate M1
- No JSON textarea or raw JSON shown anywhere in the new UI.
- Adding a dummy rule plugin with a `param_schema` produces a working form with **no frontend edit**.
- Invalid params are rejected by the API with a readable error.
- Parity checklist vs old dashboard passes → `/` switches to the new app.

---

## M2 — Agent foundation (plumbing, no LLM required)

- **AgentBus:** post-persist hook list in `EventStore.persist` (outside the lock) +
  `event.updated` messages on the SSE stream.
- **Scheduler loop** (lifespan-managed): nightly report, retention pruning, scheduled agents.
- **Shared `VlmClient`:** provider plugins (NIM, Anthropic, Gemini/OpenRouter, local
  Ollama/llama.cpp), roles (triage / chat / briefing), global + per-camera budgets, daily
  $ cap, circuit breaker + fallback chain, response cache. Replaces both duplicated clients.
- **Agent registry** (`guardlens/agents/`, auto-discovered) with `param_schema` → forms in
  M1 for free; `AgentConfig` storage (enabled, mode `suggest|act`, budget, params).
- **Annotation API:** `PATCH` agent annotations into `event_metadata.agent.<key>`;
  `EventNote.author`; **audit log** of every agent output/action.
- Per-camera **"never send frames to cloud"** flag.

🎯 Gate M2
- A dummy agent subscribes to events, respects its budget/cooldown, writes an annotation
  shown in the UI, and is toggled from a generated form — no core edits.
- Removing the VLM key disables VLM agents only; the pipeline is unaffected.
- Provider outage (simulated 503s) trips the breaker and falls back.

---

## Spike — local vs cloud VLM benchmark (~1 day, before M3)

50 real event keyframes; local Moondream 2 / Qwen3-VL-2B / SmolVLM2 / Florence-2 /
Gemma 3n vs Claude Haiku 5.5 / Gemini Flash-Lite / current NIM. Record latency + accuracy;
pick per-role providers. Results appended to `08-build-log.md`.

---

## M3 — Tier-1 agents (suggest-only)

- **A. Event Triage:** keyframes (grid) + tracker/rule notes → structured verdict, threat
  0–2, title/summary on the event and notification. Enrich + escalate only; fail open.
  Absorbs `vlm_watch`. Scene text treated as untrusted.
- **B. Daily Briefing:** LLM `ReportGenerator` over structured data + triage captions,
  every claim linked to event IDs; `structured` fallback; runtime-selectable generator.
- **D. Unusual-Activity & Dedupe:** per-camera hour-of-week baselines, outlier flags,
  merge near-duplicate alerts. Fully local.
- **C. Ask GuardLens (chat v2):** typed tools (search events, recap range, look now,
  compare cameras), conversation memory, shows analysed frame, cites events.
- **Eval harness:** labelled set from our own history; report false-alarm reduction,
  missed-alert rate, latency, cost; runs in CI on prompt/model change (offline fixtures).

🎯 Gate M3
- Triage annotates ≥95% of eligible events within budget; never hides an event.
- Missed-true-alert rate measured and recorded; suppression stays off unless ≤1%.
- Briefing for a test day cites only real event IDs (automated check).
- Chat answers a scripted question set with correct event citations.

---

## M4 — Footage search

- Embedding detector/agent: one best crop per track + frame → SigLIP2/MobileCLIP2 (ONNX,
  CPU) → sqlite-vec; triage captions → FTS5.
- Hybrid search API + UI ("person in red jacket, lobby, yesterday 2–4pm"); "find similar".
- **E. Search agent** in chat (LLM parses the query into filters + vector search).

🎯 Gate M4: scripted queries return expected events on the sample + recorded clips;
indexing stays within CPU budget alongside live analysis.

---

## M5 — Auth + remote access

- Login + API tokens/sessions; all mutating endpoints protected; CORS locked to UI origin.
- Remote via Tailscale (or Cloudflare Tunnel for a public URL); optional UI on Vercel.
- Rate limits on vision/pairing/agent endpoints.

🎯 Gate M5: unauthenticated requests rejected; remote dashboard works over the tunnel;
no secrets in logs or responses.

---

## M6 — Tier-2/3 agents & accuracy

- **F. NL Rule Setup** (structured output → validation → 72 h dry-run → confirm).
- **H. Notification Router**, **G. Incident Report Drafter**, **N. Health/Ops Agent**.
- **YOLOE** open-vocabulary detector plugin scoped per camera; **I. Custom Visual Condition**.
- Only after auth + explicit opt-in: **J. Response Playbooks** (human-confirmed by default).

---

## Ongoing

- Pending physical gates: multi-phone HTTPS soak, recording playback/low-disk/restart,
  MediaPipe/ASL model evaluation (`09` final checklist).
- Privacy: face features opt-in and region-aware; retention limits; VLM data-flow disclosure.
