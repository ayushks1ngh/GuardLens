"""FastAPI application assembly (see docs/02-architecture.md).

Phase 0 provides: app lifespan (config load + DB init), a /health endpoint,
runtime config endpoint, and static serving of the single-page dashboard and
evidence snapshots. Later phases mount camera/event/face/rule/report routers.
"""
from __future__ import annotations

import logging
import platform
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from guardlens import __version__
from guardlens.config import ROOT, load_config
from guardlens.capture.manager import manager
from guardlens.events import init_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("guardlens")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GuardLens %s starting up...", __version__)
    cfg = load_config()
    state["config"] = cfg
    logger.info("Config loaded. Device=%s, analyze_fps=%s", cfg.device, cfg.analyze_fps)

    init_engine(cfg.resolved_db_url())
    logger.info("Database ready at %s", cfg.resolved_db_url())

    from guardlens.events.store import event_store
    event_store.configure(cfg.snapshots_dir())
    from guardlens.recording import clip_recorder
    from guardlens.events import Setting, get_engine
    from sqlmodel import Session
    with Session(get_engine()) as session:
        stored_recording = session.get(Setting, "recording")
        if stored_recording is None:
            stored_recording = Setting(key="recording", value=cfg.recording.model_dump())
            session.add(stored_recording); session.commit()
        recording_values = stored_recording.value
    clip_recorder.configure(cfg.clips_dir(), recording_values)
    from guardlens.detectors._face_runtime import face_runtime
    face_runtime.configure(cfg.faces_dir())
    from guardlens.notifiers import dispatcher
    dispatcher.reload()
    from guardlens.reporting.activity import activity_sampler
    activity_sampler.configure(
        cfg.reporting.activity_interval_seconds,
        cfg.reporting.retention_days,
    )
    from guardlens.reporting import reporting_runtime
    reporting_runtime.generator = cfg.reporting.generator
    from guardlens.reporting.maintenance import prune_activity
    pruned = prune_activity(cfg.reporting.retention_days)
    if pruned:
        logger.info("Pruned %s expired activity rows", pruned)

    # Shared AI client, privacy settings, scheduler and agents.
    from guardlens.agents import agent_runner
    from guardlens.api.privacy import load_privacy
    from guardlens.events.store import event_store as _event_store
    from guardlens.scheduler import scheduler
    from guardlens.vlm_client import vlm_client
    vlm_client.configure(cfg.vlm)
    from guardlens import auth as _auth
    _auth.auth_state.load()
    load_privacy()
    agent_runner.reload()
    _event_store.add_listener(agent_runner.on_event)
    from guardlens.search import search_service
    search_service.configure(cfg.snapshots_dir())
    _event_store.add_listener(search_service.on_event)
    scheduler.add_job("activity-retention", lambda: prune_activity(cfg.reporting.retention_days), every=3600)
    scheduler.add_job("clip-retention", lambda: __import__("guardlens.recording", fromlist=["clip_recorder"]).clip_recorder.prune(), every=3600)
    scheduler.add_job("nightly-report", lambda: __import__("guardlens.api.reporting", fromlist=["_generate"])._generate(
        __import__("datetime").datetime.now(__import__("datetime").timezone.utc).date(), force=True), daily_at="23:55")
    scheduler.add_job("chat-frames", lambda: __import__("guardlens.assistant", fromlist=["prune_chat_frames"]).prune_chat_frames(cfg.snapshots_dir()), every=3600)
    agent_runner.attach_scheduler(scheduler)
    scheduler.start()

    # Start capture workers for enabled cameras.
    manager.start_all()
    logger.info("Camera workers started: %s", manager.status())

    # Configure + start the analysis pipeline (detectors + tracker + rules).
    if cfg.analysis_enabled:
        try:
            from guardlens.analysis.pipeline import analysis_manager
            analysis_manager.configure(cfg)
            analysis_manager.start_all()
            logger.info("Analysis pipeline started.")
        except Exception:
            logger.exception("analysis pipeline failed to start (continuing without it)")
    else:
        logger.info("Analysis pipeline disabled by configuration.")

    yield

    logger.info("GuardLens shutting down...")
    try:
        scheduler.stop()
        _event_store.remove_listener(agent_runner.on_event)
    except Exception:
        logger.exception("error stopping scheduler")
    try:
        from guardlens.analysis.pipeline import analysis_manager
        analysis_manager.stop_all()
    except Exception:
        logger.exception("error stopping analysis pipeline")
    try:
        from guardlens.capture.webrtc import pairing_service
        await pairing_service.close_all()
    except Exception:
        logger.exception("error stopping WebRTC publishers")
    manager.stop_all()


def create_app() -> FastAPI:
    app = FastAPI(title="GuardLens 2.0", version=__version__, lifespan=lifespan)

    # Serve evidence snapshots.
    snapshots = Path(load_config().snapshots_dir())
    app.mount("/history", StaticFiles(directory=str(snapshots)), name="history")

    origins = load_config().cors_origins
    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
            expose_headers=["Last-Event-ID"],
        )

    from fastapi.responses import JSONResponse

    from guardlens import auth as _auth

    @app.middleware("http")
    async def require_login(request, call_next):
        if _auth.auth_state.enabled and not _auth.is_public(request.url.path, request.method):
            user = await __import__("asyncio").to_thread(_auth.authenticate, request.headers, request.cookies)
            if user is None:
                return JSONResponse({"detail": "login required"}, status_code=401)
            request.state.user = user
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self' ws: wss:; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'",
        )
        if request.url.scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    # Routers
    from guardlens.api.agents import router as agents_router
    from guardlens.api.assistant import router as assistant_router
    from guardlens.api.auth import router as auth_router
    from guardlens.api.cameras import router as cameras_router
    from guardlens.api.events import router as events_router
    from guardlens.api.faces import router as faces_router
    from guardlens.api.operations import router as operations_router
    from guardlens.api.pairing import router as pairing_router
    from guardlens.api.privacy import router as privacy_router
    from guardlens.api.recording import router as recording_router
    from guardlens.api.search import router as search_router
    from guardlens.api.reporting import router as reporting_router
    from guardlens.api.rules import router as rules_router
    from guardlens.api.stream import router as stream_router
    from guardlens.api.vision import router as vision_router

    app.include_router(auth_router)
    app.include_router(agents_router)
    app.include_router(assistant_router)
    app.include_router(privacy_router)
    app.include_router(cameras_router)
    app.include_router(events_router)
    app.include_router(faces_router)
    app.include_router(operations_router)
    app.include_router(pairing_router)
    app.include_router(recording_router)
    app.include_router(search_router)
    app.include_router(reporting_router)
    app.include_router(rules_router)
    app.include_router(stream_router)
    app.include_router(vision_router)

    @app.get("/publish", response_class=HTMLResponse)
    async def publisher():
        page = ROOT / "frontend" / "publish.html"
        if page.exists():
            return HTMLResponse(page.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>Publisher not found.</h1>", status_code=404)

    @app.get("/api/health/issues")
    async def health_issues():
        from guardlens.healthcheck import collect_issues
        cfg = state.get("config")
        return await __import__("asyncio").to_thread(collect_issues, Path(cfg.data_dir if cfg else "data"))

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    @app.get("/health")
    async def health(request: Request):
        cfg = state.get("config")
        if _auth.auth_state.enabled and await __import__("asyncio").to_thread(
                _auth.authenticate, request.headers, request.cookies) is None:
            return {"status": "ok"}  # no camera details for signed-out callers
        return {
            "status": "ok",
            "version": __version__,
            "python": platform.python_version(),
            "device": getattr(cfg, "device", "unknown"),
            "analysis_enabled": getattr(cfg, "analysis_enabled", False),
            "analyze_fps": getattr(cfg, "analyze_fps", None),
            "detectors": [d.get("key") for d in getattr(cfg, "detectors", [])],
            "cameras": manager.status(),
            "recording": __import__("guardlens.recording", fromlist=["clip_recorder"]).clip_recorder.status(),
            "browser_publishers": __import__("guardlens.capture.webrtc", fromlist=["pairing_service"]).pairing_service.list_public(),
        }

    @app.get("/api/meta")
    async def meta():
        """Capability discovery for the UI: version, vocabularies, and optional features."""
        import os

        from guardlens.coco import COCO_CLASSES
        from guardlens.notifiers import notifier_types
        from guardlens.rules import rule_types

        cfg = state.get("config")
        return {
            "name": "GuardLens",
            "version": __version__,
            "object_classes": COCO_CLASSES,
            "capabilities": {
                "vlm": __import__("guardlens.vlm_client", fromlist=["vlm_client"]).vlm_client.available,
                "recording": bool(getattr(getattr(cfg, "recording", None), "enabled", False)),
                "analysis": bool(getattr(cfg, "analysis_enabled", False)),
                "https": bool(getattr(cfg, "ssl_certfile", "")),
            },
            "plugins": {
                "detectors": [d.get("key") for d in getattr(cfg, "detectors", [])],
                "rules": [r["key"] for r in rule_types()],
                "notifiers": [n["key"] for n in notifier_types()],
                "agents": [a["key"] for a in __import__("guardlens.agents", fromlist=["agent_types"]).agent_types()],
            },
        }

    @app.get("/api/config")
    async def get_runtime_config():
        cfg = state.get("config")
        if not cfg:
            return {"error": {"code": "not_ready", "message": "Config not loaded yet"}}
        return {
            "analyze_fps": cfg.analyze_fps,
            "analysis_enabled": cfg.analysis_enabled,
            "device": cfg.device,
            "model_weights": cfg.model_weights,
            "detectors": cfg.detectors,
            "rules": cfg.rules,
            "reporting": cfg.reporting.model_dump(),
            "recording": cfg.recording.model_dump(),
        }

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        index = ROOT / "frontend" / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>GuardLens</h1><p>Dashboard not found.</p>", status_code=404)

    # New React dashboard (built from frontend-app/). Absent in a bare checkout: the classic
    # dashboard at "/" keeps working until the build exists.
    ui_dist = ROOT / "frontend-app" / "dist"
    if (ui_dist / "index.html").exists():
        app.mount("/app", StaticFiles(directory=str(ui_dist), html=True), name="app")

    return app


app = create_app()
