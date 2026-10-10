"""Analysis pipeline (see docs/02-architecture.md §2.2).

One worker thread per camera. At the configured analyze-FPS it pulls the LATEST
frame from the capture worker, runs enabled Detector plugins, assigns stable
track IDs via the tracker, builds a FrameContext, runs the RuleEngine, and
publishes lightweight overlay metadata (boxes + counts + alert flag) over SSE.

Backpressure: always analyze the latest frame; never queue stale frames (§4).
In Phase 2 EventDrafts are logged (not yet persisted) — persistence is Phase 3.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from guardlens.analysis.tracker import CentroidTracker
from guardlens.capture.manager import manager
from guardlens.detectors import create_detector
from guardlens.rules import RuleEngine
from guardlens.streaming.stream import overlay_store
from guardlens.types import FrameContext

logger = logging.getLogger("guardlens.analysis")


class AnalysisWorker:
    """Runs detection + tracking + rules for one camera."""

    def __init__(
        self,
        camera_id: int,
        detectors,
        rule_engine: RuleEngine,
        analyze_fps: float,
        event_sink=None,
    ):
        self.camera_id = camera_id
        self._detectors = detectors
        self._engine = rule_engine
        self._event_sink = event_sink
        self._tracker = CentroidTracker()
        self._interval = 1.0 / analyze_fps if analyze_fps > 0 else 0.2
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_ts: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"analysis-{self.camera_id}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def analyze_once(self, frame, timestamp: float) -> FrameContext:
        """Run the full pipeline on a single frame (used by the loop + tests)."""
        detections = []
        for det in self._detectors:
            detections.extend(det.process(frame))
        detections = self._tracker.update(detections)

        h, w = frame.shape[:2]
        from guardlens.rules._policy import policy_store
        ctx = FrameContext(
            camera_id=self.camera_id,
            timestamp=timestamp,
            frame_shape=(h, w),
            detections=detections,
            tracks=self._tracker.histories(),
            zones=policy_store.zones_for(self.camera_id),
            frame=frame,
        )

        drafts = self._engine.evaluate(ctx, now=timestamp)
        self._publish_overlay(ctx, drafts)
        try:
            from guardlens.reporting.activity import activity_sampler
            activity_sampler.sample(ctx)
        except Exception:
            logger.exception("[cam %s] activity sampling failed; analysis continues", self.camera_id)
        for d in drafts:
            logger.info(
                "[cam %s] rule fired: type=%s severity=%s meta=%s",
                self.camera_id, d.type, d.severity, d.metadata,
            )
            if self._event_sink is not None:
                try:
                    self._event_sink(self.camera_id, d)
                except Exception:
                    logger.exception(
                        "[cam %s] failed to persist event %s; analysis continues",
                        self.camera_id, d.type,
                    )
        return ctx

    def _publish_overlay(self, ctx: FrameContext, drafts) -> None:
        counts: dict[str, int] = {}
        boxes = []
        for d in ctx.detections:
            counts[d.class_name] = counts.get(d.class_name, 0) + 1
            boxes.append({
                "class": d.class_name,
                "conf": round(d.confidence, 2),
                "bbox": [round(v, 4) for v in d.bbox],
                "track_id": d.track_id,
                "name": d.attributes.get("name"),
            })
        overlay_store.update(self.camera_id, {
            "counts": counts,
            "boxes": boxes,
            "alert": bool(drafts),
            "events": [{"type": d.type, "severity": d.severity} for d in drafts],
        })

    def _run(self) -> None:
        logger.info("[cam %s] analysis started (interval=%.3fs)", self.camera_id, self._interval)
        while not self._shutdown.is_set():
            start = time.time()
            worker = manager.get_worker(self.camera_id)
            if worker is None:
                break
            frame, ts = worker.get_latest()
            if frame is not None and ts != self._last_ts:
                self._last_ts = ts
                try:
                    self.analyze_once(frame, ts)
                except Exception:
                    logger.exception("[cam %s] analysis error", self.camera_id)
            elapsed = time.time() - start
            sleep = self._interval - elapsed
            self._shutdown.wait(timeout=max(sleep, 0.01))
        logger.info("[cam %s] analysis stopped", self.camera_id)


class AnalysisManager:
    """Owns analysis workers and builds detectors/rule engine from config."""

    def __init__(self):
        self._workers: dict[int, AnalysisWorker] = {}
        self._detectors = []
        self._engine = RuleEngine()
        self._analyze_fps = 6.0
        self._lock = threading.Lock()
        self._configured = False
        self._active = False

    def configure(self, config) -> None:
        """Instantiate enabled detectors + rule configs from app config."""
        from guardlens.rules import RuleConfig

        detectors = []
        for entry in getattr(config, "detectors", []):
            key = entry.get("key")
            if not key:
                continue
            merged = {
                "model_weights": config.model_weights,
                "device": config.device,
                **entry,
            }
            detectors.append(create_detector(key, merged))
        self._detectors = detectors
        self._analyze_fps = config.analyze_fps

        # Seed config rules only when the DB has none; API-managed persisted rules
        # then become the runtime source of truth.
        from guardlens.events import Rule as RuleModel
        from guardlens.events import get_engine
        from sqlmodel import Session, select
        raw_rules = getattr(config, "rules", []) or []
        with Session(get_engine()) as session:
            existing = session.exec(select(RuleModel)).first()
            if existing is None:
                for raw in raw_rules:
                    session.add(RuleModel(**raw))
                session.commit()
        from guardlens.rules._policy import policy_store
        policy_store.reload()
        self._engine.set_configs(policy_store.rules())
        self._configured = True

    @property
    def active(self) -> bool:
        return self._active and self._configured and bool(self._detectors)

    def set_rule_configs(self, configs) -> None:
        self._engine.set_configs(configs)

    def start_all(self) -> None:
        if not self._configured or not self._detectors:
            logger.info("analysis not started (no detectors configured)")
            return
        self._active = True
        for s in manager.status():
            self.start_camera(s["camera_id"])

    def start_camera(self, camera_id: int) -> None:
        with self._lock:
            existing = self._workers.get(camera_id)
            if existing:
                existing.stop()
            from guardlens.events.store import event_store
            w = AnalysisWorker(
                camera_id,
                self._detectors,
                self._engine,
                self._analyze_fps,
                event_sink=event_store.persist,
            )
            w.start()
            self._workers[camera_id] = w

    def stop_camera(self, camera_id: int) -> None:
        with self._lock:
            w = self._workers.pop(camera_id, None)
        if w:
            w.stop()

    def stop_all(self) -> None:
        self._active = False
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for w in workers:
            w.stop()


analysis_manager = AnalysisManager()
