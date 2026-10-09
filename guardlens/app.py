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

from fastapi import FastAPI
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

    # Start capture workers for enabled cameras.
    manager.start_all()
    logger.info("Camera workers started: %s", manager.status())

    yield

    logger.info("GuardLens shutting down...")
    manager.stop_all()


def create_app() -> FastAPI:
    app = FastAPI(title="GuardLens 2.0", version=__version__, lifespan=lifespan)

    # Serve evidence snapshots.
    snapshots = Path(load_config().snapshots_dir())
    app.mount("/history", StaticFiles(directory=str(snapshots)), name="history")

    # Routers
    from guardlens.api.cameras import router as cameras_router
    from guardlens.api.stream import router as stream_router

    app.include_router(cameras_router)
    app.include_router(stream_router)

    @app.get("/health")
    async def health():
        cfg = state.get("config")
        return {
            "status": "ok",
            "version": __version__,
            "python": platform.python_version(),
            "device": getattr(cfg, "device", "unknown"),
            "analyze_fps": getattr(cfg, "analyze_fps", None),
            "cameras": manager.status(),
        }

    @app.get("/api/config")
    async def get_runtime_config():
        cfg = state.get("config")
        if not cfg:
            return {"error": {"code": "not_ready", "message": "Config not loaded yet"}}
        return {
            "analyze_fps": cfg.analyze_fps,
            "device": cfg.device,
            "model_weights": cfg.model_weights,
            "detectors": cfg.detectors,
            "reporting": cfg.reporting.model_dump(),
        }

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        index = ROOT / "frontend" / "index.html"
        if index.exists():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse("<h1>GuardLens</h1><p>Dashboard not found.</p>", status_code=404)

    return app


app = create_app()
