# 07 — Extensibility Guide

This is the most important design document. The core requirement is:

> **Adding a new capability must never require rewriting the core.**

We meet this with three plugin types — **Detectors**, **Rules**, **Notifiers** —
each discovered through a registry, plus a stable data contract between them.
Below are the proposed interfaces (final signatures may refine slightly during
implementation, but the shape is fixed).

---

## 1. Core data contracts (the stable "language")

```python
# guardlens/types.py  (illustrative)
from dataclasses import dataclass, field

@dataclass
class Detection:
    class_name: str              # e.g. "person", "knife", "face"
    confidence: float
    bbox: tuple[float, float, float, float]   # normalized x1,y1,x2,y2 (0..1)
    track_id: int | None = None  # filled by the tracker
    attributes: dict = field(default_factory=dict)  # free-form (e.g. {"person_id": 5, "name": "Ayush"})

@dataclass
class FrameContext:
    camera_id: int
    timestamp: float
    frame_shape: tuple[int, int]        # h, w
    detections: list[Detection]
    tracks: dict[int, list[Detection]]  # track_id -> recent history
    zones: list["Zone"]                 # zones defined for this camera

@dataclass
class EventDraft:
    type: str
    severity: str                       # info | warning | critical
    metadata: dict                      # bbox, track_id, counts, etc.
    person_id: int | None = None
    snapshot: "ndarray | None" = None   # the frame to persist as evidence
```

Everything downstream speaks in `Detection` / `FrameContext` / `EventDraft`.
As long as a plugin produces/consumes these, it fits — regardless of what model
or logic it uses internally.

---

## 2. Camera source plugins

```python
from guardlens.capture.sources import CameraSource, register_source

@register_source
class WebRtcSource(CameraSource):
    key = "webrtc"
    modes = [{"key": "paired_browser", "fields": []}]
    def open(self) -> bool: ...
    def read(self): ...                 # -> (ok, BGR ndarray)
    def close(self) -> None: ...
```

Source modules are auto-discovered. `GET /api/cameras/source-types` exposes adapter/mode
schemas to the source wizard. Capture and analysis consume only the source contract, so
adding WebRTC or another transport does not edit the core frame pipeline. Credentials
remain in persisted `source_config` but are redacted from operator API responses.

---

## 3. Detector plugins

```python
# guardlens/detectors/base.py
class Detector:
    key: str                 # unique id, e.g. "object", "face"
    def setup(self, config: dict) -> None: ...        # load model once
    def process(self, frame) -> list[Detection]: ...  # per analyzed frame
    def teardown(self) -> None: ...
```

Register:
```python
from guardlens.detectors import register

@register
class FireSmokeDetector(Detector):
    key = "fire_smoke"
    def setup(self, config): self.model = load_model(config["weights"])
    def process(self, frame): return self._infer(frame)
```

Enable in `config.yaml`:
```yaml
detectors:
  - key: object
  - key: face
  - key: fire_smoke          # <- new capability, zero core edits
    weights: models/fire.onnx
```

**To add a detector:** create a file in `detectors/`, implement `Detector`,
decorate with `@register`, enable in config. The analysis pipeline runs all
enabled detectors and merges their `Detection`s into the `FrameContext`.

---

## 4. Rule plugins

```python
# guardlens/rules/base.py
class Rule:
    key: str                 # e.g. "zone_intrusion", "loitering"
    param_schema: dict       # JSON schema for params (drives the UI form)
    def evaluate(self, ctx: FrameContext, cfg: "RuleConfig") -> EventDraft | None: ...
```

Example — a brand-new rule with **no schema migration** (params ride in JSON):
```python
@register_rule
class AfterHoursRule(Rule):
    key = "after_hours"
    param_schema = {"start": "HH:MM", "end": "HH:MM"}
    def evaluate(self, ctx, cfg):
        if self._in_window(cfg.params) and any(d.class_name == "person" for d in ctx.detections):
            return EventDraft(type=self.key, severity=cfg.severity,
                              metadata={"count": len(ctx.detections)})
        return None
```

Create it in the UI/API:
```json
{ "type": "after_hours", "name": "No one after 22:00",
  "camera_id": 1, "severity": "critical",
  "params": { "start": "22:00", "end": "06:00" } }
```

**To add a rule:** create a file in `rules/`, implement `Rule`, register it, done.
`GET /api/rules/types` auto-exposes it (with its `param_schema`) so the dashboard
can render a config form **without hardcoding the rule in the UI**.

---

## 5. Notifier plugins

```python
# guardlens/notifiers/base.py
class Notifier:
    key: str                 # e.g. "webhook", "telegram", "mqtt"
    config_schema: dict
    def setup(self, config: dict) -> None: ...
    def send(self, event: dict) -> None: ...   # must be failure-isolated
```

```python
@register_notifier
class TelegramNotifier(Notifier):
    key = "telegram"
    config_schema = {"bot_token": "str(env)", "chat_id": "str"}
    def send(self, event): post_to_telegram(self.cfg, event)
```

**To add a notifier:** implement `send`, register, configure via
`POST /api/notifiers`. Dispatch is async and isolated — a broken notifier can
never crash the pipeline.

---

## 6. Other swap points

- **Report generator (ADR-010):** implement the `ReportGenerator` interface, register,
  and select via config. The default `structured` generator is deterministic/CPU-only;
  a `VlmReportEnricher` (local small model or cloud API) can be added later with **no
  change to the activity sampler, the API, or the dashboard**.

  ```python
  # guardlens/reporting/base.py
  class ReportGenerator:
      key: str                                  # "structured", "vlm", ...
      def generate(self, date, activity, events) -> dict: ...   # -> {text, content}
  ```

- **Detection model / license (ADR-002):** swap the detector plugin or point it at a
  different ONNX model via config — no core change. This is how we escape AGPL if needed.
- **Face backend (ADR-003):** the default OpenCV backend is dependency-free and
  CPU-safe; a stronger InsightFace, `face_recognition`, or other backend can replace it
  while preserving the same `Detection.attributes` contract.
- **Tracker (ADR-004):** custom IoU tracker now; ByteTrack later behind the same seam.
- **Database (ADR-006):** change the connection URL (SQLite → Postgres).
- **Frontend (ADR-008):** API is the stable boundary; the dashboard can be rewritten
  later without backend changes.

---

## 7. The rules we hold ourselves to (checked every phase)

1. New detector/rule/notifier = **new file + config**, never a core edit.
2. New rule parameters live in the **JSON `params`** column — **no DB migration**.
3. New rule types are **auto-discovered** by the API and rendered by the UI from
   their `param_schema` — the dashboard does not hardcode rule types.
4. Thresholds, model choice, FPS, and paths stay **config-driven**.

If a change would violate any of these, we fix the extensibility seam first,
then make the change. That is what keeps GuardLens "not limited to things" —
open to whatever we (or future contributors) want to add.
