# 12 — Agents Research: What to Build on GuardLens

**Status:** Research only (2026-10-12). Nothing here is built. Feeds the build plan in
[`13-build-roadmap.md`](13-build-roadmap.md). Prices/specs are as found on 2026-10-12;
items marked **[UNVERIFIED]** came from a single/aggregator source or memory, **[EST]** are
engineering estimates. Benchmark on the real hardware before committing (§6).

**Invariant (unchanged):** every agent is a plugin + config + `param_schema`, never a core
edit. No agent may be able to break capture/analysis. Agents are event-triggered,
scheduled, or on-demand — **never per-frame**.

---

## 1. What the market actually ships (2025–2026)

Surveyed: Frigate (0.17/0.18), Home Assistant (AI Task, LLM Vision, Home Generative Agent),
Scrypted, NVIDIA VSS blueprint, Intel Live Video Alert Agent, cctvQL, DeepCamera; Google
Gemini for Home, Ring, Arlo, Wyze, Eufy, Reolink, UniFi AI Key; Verkada, Spot AI, Coram,
Lumana, Rhombus, Ambient.ai, Genetec, Avigilon, Milestone, Hikvision/Dahua, Conntour,
Twelve Labs.

| # | Pattern | Who ships it | How it works | Reported value | Known failure |
|---|---------|--------------|--------------|----------------|---------------|
| 1 | **VLM verification / threat triage** of rule-fired events | Frigate review summaries (`potential_threat_level` 0–2), NVIDIA VSS alert verification, Ambient Pulsar, Spot AI, Milestone | Cheap CV gate → VLM on a few frames → structured verdict (confirmed/rejected, threat, summary) | Vendor claims 30–95% false-alarm reduction (no independent evals) | Can suppress real alarms → must **fail open** |
| 2 | **Per-event descriptions** (title + summary on notification/event) | Frigate, Scrypted, Google, Ring, Arlo, Wyze, Milestone | Same call as #1. Frigate sends ≤20 small frames + tracker notes ("first seen", "stopped") as `annotated_frames`; per-camera "what's normal here" prompt | "Mostly accurate", good for at-a-glance triage | Hallucinated animals, "shotgun = garden tool"; small local models break JSON |
| 3 | **Natural-language footage search** | Verkada, Frigate, UniFi, Hikvision AcuSeek, Dahua WizSeek, Google Ask Home, Ring, Arlo, Wyze, Eufy, Reolink | CLIP-family embeddings of **object crops** (not full frames) + caption text + time/camera filters | Most consistently praised feature | Weak at counting/actions; text→image CLIP scores can't be thresholded for alerts |
| 4 | **Daily digest / shift recap** | Google Home Brief, Frigate report API, Scrypted Stories, NVIDIA VSS | Hierarchical: per-event summaries → text LLM aggregates | Liked in principle | **Most hallucination-prone** ("leaned toward fiction" — The Verge). Fix: build from verified DB records, cite event IDs |
| 5 | **Tool-calling camera chat agent** | Frigate 0.18 Chat, NVIDIA VSS 3.x (MCP), Home Generative Agent, cctvQL, Alexa+/Ring, Ask Home | LLM + typed tools over event DB + on-demand VLM on a specific frame | Became the top-level UI in Frigate and VSS in 2026 | Tool reliability on small models; per-camera access leaks (Frigate rc1 fix) |
| 6 | **Natural-language alert rules** | Verkada, Avigilon Visual Alerts, Rhombus Custom Events, Spot AI Iris, Dahua, UniFi, Intel agent | (a) embedding threshold (noisy), (b) gated VLM yes/no at a frequency, (c) few-shot classifier, or (d) **compile NL → deterministic rule** | High UX value | Continuous VLM polling is very expensive |
| 7 | **"Unusual activity" baseline + alert dedupe** | Ring Unusual Event Alerts, Single Event Alert | Learned per-camera normal patterns; merge similar alerts | Fewer, better alerts | Cold start, seasonality, "unusual ≠ threat" |
| 8 | **Response / deterrence playbooks** | Ring Active Warnings, Spot AI Remote Security Agent, Eufy, Rhombus relays, SimpliSafe/Deep Sentinel (human) | Escalation ladder: light → talk-down → staff/police; case record | Deterrence | Yelling at residents; liability. Everyone keeps a human in the loop |
| 9 | **Incident report drafts / evidence packs** | Verkada Incident Summary, Spot AI, Genetec | Timeline + snapshots + clips + narrative | Faster investigations | Study (SOUPS 2025): autonomous LLM incident summaries omitted key details 35%, factual errors 42% → **draft + human sign-off** |
| 10 | **Cross-camera re-ID timeline** | Verkada, Avigilon Appearance Search, Genetec, Coram | Appearance embeddings (OSNet / CLIP crops) + time/topology | Strong for investigations | Hard on low-res CPU setups; tenant-surveillance risk |
| 11 | **Site memory / context** | LLM Vision memory, Google Pet Memory, Frigate context prompt | Reference images + "normal here" text injected into prompts | Fewer false "suspicious" calls | Over-specific prompts skew results |
| 12 | **Time-boxed live VLM watch** | Frigate 0.18, Intel agent, LLM Vision stream analyzer | VLM loop on a live view | Useful on demand | Too costly always-on |
| 13 | **Face / LPR / visitor-delivery** | Ring Familiar Faces, Frigate (CPU face + LPR), Eufy, Ring Alexa+ Greetings | Embeddings / OCR / VLM context | Convenience | **Legal risk:** Ring disables faces in Illinois (BIPA), Texas, Portland; NY landlord biometric bills. Never grant access automatically |

**Cross-cutting lessons (everyone at scale converged on these):**
1. Two-stage: cheap CV gate → VLM **only on gated events**.
2. Send tracker/rule metadata with the pixels (cheaper, more accurate).
3. Strict structured output; **fail open** on timeout/parse error/low confidence.
4. CLIP crops for search; VLM for reasoning. Don't alert on raw CLIP text scores.
5. Digests from structured records, LLM only phrases, every claim cites an event ID.
6. Agents call typed tools (MCP-style), not raw SQL; per-camera ACLs.
7. LLMs never auto-actuate safety-critical actions.
8. Local-first; cloud only for selected frames; biometrics opt-in and region-gated.

---

## 2. Building blocks

### 2.1 Cloud VLM cost per event (1×720p image, ~150 in / ~100 out tokens)

| Model | $/1M in / out | ≈ $ per 1,000 events | Notes |
|-------|---------------|----------------------|-------|
| **Claude Haiku 5.5** `claude-haiku-5-5` | $0.10 / $0.50 (verified, Anthropic reference) | ~$0.19 [EST] | Set `output_config.effort: "low"`; image ≈ (w/28)×(h/28) ≈ 1.2k tokens |
| Claude Sonnet 5.5 `claude-sonnet-5-5` | $2 / $10 (verified) | ~$4 [EST] | Agent brain / hard cases / briefing |
| Claude Opus 5.5 `claude-opus-5-5` | $4 / $20 (verified) | ~$8 [EST] | Low-volume NL rule authoring |
| Gemini 2.5 Flash-Lite | $0.10 / $0.40 [UNVERIFIED] | ~$0.08 | Cheapest; native video |
| Groq Llama 4 Scout | ~$0.11 / $0.34 [UNVERIFIED] | ~$0.15 | Very low latency |
| NVIDIA NIM free (current) | free, ~40 RPM, "not for production" | $0 | Explains our 503s; keep as dev fallback only |

**Takeaway:** per-event triage costs cents per camera per day. **Privacy, availability and
rate limits are the constraints, not money.** Example envelope: 4 cameras × 300 events/day
× 3 frames ≈ $0.7/day on Haiku 5.5 [EST].

### 2.2 Local VLMs (CPU-only laptop)

No vendor publishes CPU latency; all below are **[EST]** until benchmarked. Frigate's docs
state CPU VLM inference is "not recommended". Plan for **seconds per call, async only**.

| Model | Size | License | Est. CPU / image | Fit |
|-------|------|---------|------------------|-----|
| **Moondream 2** | ~1.9B | Apache-2.0 [UNVERIFIED] | 3–8 s | Built-in detect/point/query → presence checks |
| **Qwen3-VL-2B/4B Instruct** (GGUF) | 2/4B | Apache-2.0 [verify card] | 5–25 s | Best quality per param; Frigate's recommended local model |
| **SmolVLM2** 256M/500M/2.2B | tiny–2.2B | Apache-2.0 [UNVERIFIED] | 1–10 s | Fast, weak; native multi-frame |
| **Florence-2-base** | 0.23B | MIT | 1–3 s | Caption + phrase-grounding + OCR (not chat) → search indexing |
| Gemma 3n E2B | ~2B eff. | Gemma terms | 3–8 s | Edge-designed encoder |
| MiniCPM-V 4.6 | 1.3B | MiniCPM license | 3–6 s | OCR/multi-image; check license |
| Moondream 3, Qwen2.5-VL-3B, Phi-4-MM | — | BSL / non-commercial / MIT | no CPU path / slow | Avoid on this box |

Latency is dominated by image tokens: crop to the YOLO box, downscale to 448–512 px, cap
output to ~60 JSON tokens.

### 2.3 Search, open-vocabulary detection, storage

- **Embeddings:** MobileCLIP2-S2 (fast; research license — check) or **SigLIP2-B**
  (Apache-2.0, safer); ~10–150 ms/crop on CPU [EST]. Embed **one best crop per track** +
  the frame, plus the triage caption as text.
- **Store:** **sqlite-vec** (same `.db`; ~25–70 ms KNN at 100k vectors; normalize + L2) +
  SQLite **FTS5** over captions → hybrid search. LanceDB only beyond ~1M vectors.
- **Open-vocab detection:** **YOLOE** (text prompts compiled into the head → YOLO-speed;
  AGPL like current YOLO). Grounding DINO / OWLv2 only for keyframe verification (1–5 s).
- **Speech (optional, later):** faster-whisper small int8 (~7× real-time CPU), Piper /
  Kokoro TTS for pre-rendered talk-down phrases.

### 2.4 Design patterns that apply

1. **Fixed pipelines for hot paths, tool-calling agents only for interactive work.**
   Triage is a deterministic pipeline; chat/search/setup are tool-calling agents.
2. **One MCP server over the GuardLens API** (`list_cameras`, `get_snapshot`,
   `search_events`, `get_event`, `get_clip_keyframes`, `ask_vlm`, `propose_rule`,
   gated `apply_rule`, `silence_camera`). Serves the in-app agent, Claude Desktop/Code,
   and local Ollama agents alike.
3. **NL → rule:** structured output → Pydantic + semantic validation (zone exists, class
   in vocabulary) → **dry-run against last 24–72 h** ("would have fired N times") → user
   confirms.
4. **Budgets:** per-camera token bucket, global daily $ cap, pHash/CLIP dedupe (skip if
   ≥0.95 similar to last verified frame of the track), answer cache, per-provider circuit
   breaker with fallback chain (cloud → second cloud → NIM free → local).
5. **Prompt injection via scene text** is a demonstrated attack (e.g. 15.8% goal-hijack on
   GPT-4V, arXiv 2408.03554). VLM output is **data, never instructions**: constrained
   JSON/enums only; VLM may **escalate but not silently suppress** armed-zone alerts; VLM
   output never triggers mutating tools.
6. **Hallucination control:** 2-of-3 keyframe consensus, cross-check with the YOLO box,
   ask yes/no presence questions for decisions; free text only for captions/briefings.
7. **Evaluation:** labelled set from our own history (300–1,000 events). Track
   false-alarm reduction, **missed-true-alert rate (target ≤1%)**, p50/p95 latency,
   $/1k events. Re-run on every model/prompt change.
8. **Current model caveat:** `llama-3.2-11b-vision` is single-image oriented
   [UNVERIFIED] → tile keyframes into one grid image (Scrypted montage pattern).

---

## 3. What GuardLens already has to plug into (code map)

| Need | Exists | Gap |
|------|--------|-----|
| Plugin registry pattern | Detectors, rules, notifiers, sources, report generators, gestures — all `pkgutil` auto-discovered | No `Agent` registry; schema vocabularies inconsistent across registries |
| Event trigger | `EventStore.persist` (`events/store.py:49`) → `event_bus.publish` + notifier dispatch | `EventBus` is a replay deque only — **no subscriber hooks**, no "event updated" messages |
| Annotate events | `Event.event_metadata` JSON, `EventNote` | **No API to update metadata**; notes have no author/agent field |
| Data | Event, ActivityLog (per-camera counts/known/unknown/zones), Person, Zone, Rule, Report, clips, snapshots, live `get_latest()` frame + overlay store | Analytics loads all rows into Python |
| VLM | `vlm.py` watcher (per-camera busy + cooldown), `api/vision.py` chat | Duplicated clients, one provider, env-only config, no global budget, thread-per-call, crude negation check |
| Reporting | `ReportGenerator` seam, lazy cached `Report` | Generator not switchable at runtime; no schedule |
| Background work | Analysis/capture threads, notifier pool | **No scheduler** (retention runs only at startup) |
| Config | `Setting` key→JSON rows | No generic settings router |
| Rule creation | `POST /api/rules`, zone validation, hot reload | **`params` never validated against `param_schema`** |
| Safety | WebRTC pairing tokens | **No auth** anywhere — blocks any "act" agent and remote access |
| Bug found | `EventStore.delete_evidence` uses `select` without importing it (`store.py:119`) → clip files never deleted (error swallowed) | Fix in Step 0 |

---

## 4. Agent catalogue for GuardLens

Scored for **this** project: CPU-only host, apartment use case, existing rule engine.
Value/Effort/Risk: H/M/L. "Cloud" = needs a VLM/LLM call.

### Tier 1 — build first (high value, reuse what exists)

| Agent | What it does | Trigger | Cloud? | Value | Effort | Risk | Notes |
|-------|--------------|---------|--------|-------|--------|------|-------|
| **A. Event Triage** | For each rule-fired event: 2–4 keyframes (grid) + tracker/rule notes → `{title, summary, threat 0–2, verdict, confidence, concerns}` attached to the event; drives notification wording and severity | Event persisted (filtered by type/severity; never on its own `vlm_*` events) | Yes (local fallback) | H | M | M | **Enrich + escalate only; fail open.** Suppression only after eval proves ≤1% missed alerts. Replaces/absorbs `vlm_watch` |
| **B. Daily Briefing** | Natural-language end-of-day summary over structured counts + triage captions; every sentence links event IDs | Scheduled (nightly) / on demand | Yes, text-only (or small local LLM) | H | L | L | New `ReportGenerator` with `structured` fallback — no API change |
| **C. Ask GuardLens (chat v2)** | Tool-calling chat: search events, recap a time range, look at a camera now, compare cameras; shows the analysed frame; cites events | On demand | Yes | H | M | L–M | Upgrade of current chat; same tools later exposed via MCP |
| **D. Unusual-Activity & Dedupe** | Per-camera, per-hour-of-week baselines of class/event counts → flag z-score outliers; merge near-duplicate alerts into one | Scheduled + on event | **No** | M–H | L | L | Deterministic, free, CPU-trivial (Ring's two most-liked features) |

### Tier 2 — after search/auth foundations

| Agent | What it does | Cloud? | Value | Effort | Risk | Notes |
|-------|--------------|--------|-------|--------|------|-------|
| **E. Footage Search** | "person in red jacket near lobby 2–4pm" → CLIP crops + caption FTS + filters; "find similar" from any event | Embeddings local; optional LLM to parse the query | H | M | L | Needs embedding pipeline + sqlite-vec |
| **F. NL Rule Setup** | "Watch the front door for packages after 6pm" → camera/zone/rule draft → schema validation → **dry-run vs last 72 h** → confirm | Yes (low volume) | H | M–H | M | Compiles to existing deterministic rules; LLM never runs per-frame |
| **G. Incident Report Drafter** | One click: timeline + snapshots + clips + triage verdicts + narrative → editable draft for manager/police | Yes | M | M | M | Draft only; human sign-off (35–42% error rates in studies) |
| **H. Notification Router** | Route by severity/threat/time/camera: log → push → webhook → digest-only; quiet hours; batching | No | M | L | L | Deterministic; upgrades the notifier dispatcher |
| **I. Custom Visual Condition** | NL condition ("gate left open") checked by VLM yes/no on gated frames at a set frequency, N-of-M confirm, cooldown | Yes | M | M | M | Rhombus/Avigilon pattern; budget-bounded; open-vocab YOLOE can replace many cases for free |

### Tier 3 — later / heavier guardrails

| Agent | What it does | Value | Risk | Why later |
|-------|--------------|-------|------|-----------|
| **J. Response Playbooks** | Escalation ladder (lights/relay → pre-recorded talk-down → notify staff) | M | **H** | Needs auth, hardware backchannel, human confirmation; liability |
| **K. Timed Live Watch** | "Watch the pool gate for 30 min" VLM loop with hard time and budget cap | M | M | Costly; on-demand only |
| **L. Site Memory** | Reference images/context (resident cars, staff uniforms, pets, delivery vans) injected into triage prompts | M | M | Improves A; privacy review needed |
| **M. Cross-camera Timeline** | Follow one subject across cameras via crop embeddings | M | H | Hard on CPU/low-res; tenant-surveillance risk |
| **N. Health/Ops Agent** | Watches camera freshness, disk, recorder, VLM availability; plain-language fixes ("webcam detached — run usbipd attach") | M | L | Deterministic; good UX win, could move up |
| **O. Voice Q&A** | faster-whisper + chat + Piper | L | L | Nice-to-have |

### Explicitly avoid
- Per-frame or always-on LLM/VLM loops.
- Automatic access decisions (doors, "doorman") or destructive actions without confirmation.
- Face recognition of tenants by default — keep opt-in, consent-based, region-aware.
- LLM-only digests not grounded in DB records.

---

## 5. Recommended agent architecture

```
Event persisted ──► AgentBus (post-persist hooks, off the store lock)
                        │
Scheduler (cron-like) ──┤──► AgentRunner ── per-agent budget / cooldown / enabled
On-demand (UI/API) ─────┘        │               mode: suggest | act(allow-listed)
                                 ▼
                         Agent plugin (registry, param_schema → UI form)
                                 │ uses
              ┌──────────────────┼─────────────────────┐
              ▼                  ▼                     ▼
     VlmClient (shared)   Tools (typed, ACL'd)   Annotations + AuditLog
     providers + roles    search_events, frame,  event.metadata.agent.*,
     budget, breaker,     recap, propose_rule…   who/what/when, reversible
     fallback chain,      (also served via MCP)
     per-camera "local only"
```

- **Agent plugin interface (proposal):** `key`, `label`, `param_schema`, `triggers`
  (`event` filter / `schedule` / `on_demand`), `requires` (`vlm`, `llm`, none),
  `handle(trigger, ctx) -> AgentResult` (annotations, suggestions, actions).
- **Modes:** `suggest` (default) writes annotations/suggestions only; `act` may perform
  only allow-listed, reversible actions (start recording, send notification).
- **Degrade gracefully:** missing key/provider → agent reports "unavailable" and disables
  itself; nothing else changes.
- **Every agent output is reviewable** in the UI (event card shows triage verdict, source
  frames, model, cost) and recorded in an audit log.

---

## 6. First spike before choosing providers (~1 day)

1. Export 50 real GuardLens event crops/keyframes (mixed true/false alarms).
2. Benchmark locally: Moondream 2, Qwen3-VL-2B Q4, SmolVLM2-500M, Florence-2-base,
   Gemma 3n E2B — encode/prompt/generate time + yes/no accuracy.
3. Same set on Claude Haiku 5.5, Gemini Flash-Lite, current NIM model.
4. Choose per-role providers (triage / chat / briefing) from measured numbers.

---

## 7. Decisions needed

1. **Act vs suggest** — recommended: suggest-only through Tier 1.
2. **Cloud provider + budget** — recommended: Haiku 5.5 or Gemini Flash-Lite for triage,
   daily $ cap, NIM free as fallback, per-camera "local only" switch.
3. **Which Tier-1 set first** — recommended: A (triage) + B (briefing) + D (unusual/dedupe),
   then C (chat v2).

## Sources (selected)

Frigate GenAI/review/semantic search docs and 0.18 release notes; Scrypted AI Summaries;
NVIDIA VSS 2.4/3.2 docs; Intel Live Video Alert Agent; Home Assistant AI Task; LLM Vision;
home-generative-agent; cctvQL; Verkada search blog; UniFi AI Key help; Rhombus Custom
Events; Avigilon Visual Alerts; Spot AI Remote Security Agent / Iris; Ambient Pulsar;
Milestone Hafnia VLM; Ring/Google/Arlo/Wyze/Eufy/Reolink announcements and reviews (The
Verge, Wirecutter, Android Authority, Tom's Guide); SOUPS 2025 (Kramer et al.) on LLM
incident summaries; arXiv 2408.03554, 2510.09849 (visual prompt injection); Anthropic
Claude pricing/vision docs; sqlite-vec docs; MobileCLIP2 / SigLIP2 model cards;
faster-whisper README. Full URL lists are in the research session notes summarized here.
