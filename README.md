# GuardLens 2.0

An AI-powered security camera monitoring platform. Real-time object detection,
zone-based intrusion alerts, loitering detection, people counting, and face
recognition — with a clean event database, alert workflow, and a single-page
operator dashboard.

> This is a ground-up, improved rebuild of the original
> [GuardLens-AI prototype](https://github.com/anshulshukl/Guardlens-ai).
> See [`docs/00-overview.md`](docs/00-overview.md) for what changed and why.

## Status

✅ **Roadmap phases 0–8 implemented and acceptance-tested.** GuardLens now includes
camera capture/streaming, YOLO object detection, tracking, configurable security rules,
event evidence/workflow, face enrollment/policies, notifications, analytics, activity
sampling, and daily reports. See [`docs/08-build-log.md`](docs/08-build-log.md) for gate
evidence and [`docs/09-session-recovery.md`](docs/09-session-recovery.md) for the latest
handoff.

🚧 **Post-2.0 Improvements A–F are implemented, with final physical/model gates pending.**
Typed host/file/RTSP/HTTP/MJPEG sources, secure LAN-first browser/WebRTC pairing, motion
and event/continuous clips, gesture vocabulary plugins, bounded static-ASL adapters,
and release hardening are present. Automated suites and Docker validation pass; real
multi-phone soak, enabled MediaPipe/model accuracy, and final operator checks remain.
See [`docs/09-session-recovery.md`](docs/09-session-recovery.md) for exact gate status.

## Run

Local (creates/uses `.venv`):
```bash
./run.sh
```
Then open <http://localhost:8080>. The default config uses CPU inference and the bundled
sample can be added as `data/samples/mall_cctv.mp4`. YOLO weights download once on first
analysis startup. For LAN browser-camera testing, generate explicit development TLS with
`scripts/setup_dev_tls.sh <LAN-IP>` and trust the generated certificate on each device;
use a real CA/reverse proxy for production.

Docker:
```bash
docker compose up --build
```
Runtime state lives under `data/`; the Compose model volume keeps downloaded weights
across restarts. Ultralytics is AGPL-3.0—review ADR-002 before commercial/network use.

## Documentation

Read these in order:

| Doc | Purpose |
|-----|---------|
| [`docs/00-overview.md`](docs/00-overview.md) | What we're building and why; comparison to the original |
| [`docs/01-prd.md`](docs/01-prd.md) | Product Requirements — goals, users, features, requirements |
| [`docs/02-architecture.md`](docs/02-architecture.md) | System architecture, components, data flow, plugin model |
| [`docs/03-data-model.md`](docs/03-data-model.md) | Database schema and entities |
| [`docs/04-api-spec.md`](docs/04-api-spec.md) | REST / WebSocket / SSE API contract |
| [`docs/05-roadmap.md`](docs/05-roadmap.md) | Phased delivery plan with acceptance gates |
| [`docs/06-tech-decisions.md`](docs/06-tech-decisions.md) | ADRs: model choices, licensing, tradeoffs |
| [`docs/07-extensibility.md`](docs/07-extensibility.md) | How to add new detectors, rules, and notifiers without rewrites |
| [`docs/08-build-log.md`](docs/08-build-log.md) | Running record of each phase: what was built, gate results, fixes |
| [`docs/09-session-recovery.md`](docs/09-session-recovery.md) | **Start here when resuming** — current status and how to pick up where we left off |
| [`docs/10-improvement-plan.md`](docs/10-improvement-plan.md) | Proposed multi-device camera, recording, and hand/sign roadmap |

## Quick principles

- **Flexible by design** — detectors, alert rules, notifiers, and report generators
  are plugins. Adding a new capability should never require rewriting the core.
- **CPU-first** — defaults run on a laptop with no GPU. GPU is an optional accelerator.
- **Real-world useful** — an always-on "AI monitor" for apartments: it detects people,
  animals, intrusions, loitering, abandoned objects, vehicles, and unknown faces across
  many cameras, and produces a **day-end report** of what happened. It's an assistive
  tool, not a legal replacement for a human guard.
