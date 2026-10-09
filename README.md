# GuardLens 2.0

An AI-powered security camera monitoring platform. Real-time object detection,
zone-based intrusion alerts, loitering detection, people counting, and face
recognition — with a clean event database, alert workflow, and a single-page
operator dashboard.

> This is a ground-up, improved rebuild of the original
> [GuardLens-AI prototype](https://github.com/anshulshukl/Guardlens-ai).
> See [`docs/00-overview.md`](docs/00-overview.md) for what changed and why.

## Status

🚧 **Pre-build.** This repository currently contains planning documentation only.
Implementation begins after the docs below are reviewed and approved.

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

## Quick principles

- **Flexible by design** — detectors, alert rules, notifiers, and report generators
  are plugins. Adding a new capability should never require rewriting the core.
- **CPU-first** — defaults run on a laptop with no GPU. GPU is an optional accelerator.
- **Real-world useful** — an always-on "AI monitor" for apartments: it detects people,
  animals, intrusions, loitering, abandoned objects, vehicles, and unknown faces across
  many cameras, and produces a **day-end report** of what happened. It's an assistive
  tool, not a legal replacement for a human guard.
