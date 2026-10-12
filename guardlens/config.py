"""Configuration loading and validation.

All runtime behaviour is config-driven (ADR-009). Values come from a YAML file
(default ``config.yaml``) with environment-variable overrides. Nothing security-
relevant (thresholds, model choice, FPS, paths) is hardcoded in the core.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


class ReportingConfig(BaseModel):
    activity_interval_seconds: float = 10.0
    retention_days: int = 30
    generator: str = "structured"



class RecordingConfig(BaseModel):
    enabled: bool = False
    mode: str = "event"
    pre_roll_seconds: float = Field(default=5.0, ge=0, le=60)
    post_roll_seconds: float = Field(default=10.0, ge=0, le=300)
    max_clip_seconds: float = Field(default=120.0, ge=1, le=3600)
    segment_seconds: float = Field(default=300.0, ge=10, le=3600)
    retention_days: int = Field(default=7, ge=0, le=3650)
    quota_mb: int = Field(default=2048, ge=1)
    codec_preferences: list[str] = Field(default_factory=lambda: ["mp4v", "MJPG"])

class Config(BaseModel):
    """Validated application configuration."""

    host: str = "0.0.0.0"
    port: int = 8080
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    # Origins allowed to call the API from another host (split UI hosting). Empty = same-origin only.
    cors_origins: list[str] = Field(default_factory=list)

    # Storage
    data_dir: str = str(ROOT / "data")
    db_url: str = ""  # derived from data_dir if empty

    # Analysis
    analysis_enabled: bool = True
    analyze_fps: float = 6.0
    model_weights: str = "yolov8n.pt"
    device: str = "cpu"

    # Enabled plugins (keys resolved against the registries)
    detectors: list[dict[str, Any]] = Field(default_factory=lambda: [{"key": "object"}])
    rules: list[dict[str, Any]] = Field(default_factory=list)
    notifiers: list[dict[str, Any]] = Field(default_factory=list)

    # AI provider chain / budgets (see guardlens/vlm_client.py); keys come from the environment.
    vlm: dict[str, Any] = Field(default_factory=dict)

    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    recording: RecordingConfig = Field(default_factory=RecordingConfig)

    def snapshots_dir(self) -> Path:
        return Path(self.data_dir) / "snapshots"

    def faces_dir(self) -> Path:
        return Path(self.data_dir) / "faces"


    def clips_dir(self) -> Path:
        return Path(self.data_dir) / "clips"
    def resolved_db_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{Path(self.data_dir) / 'guardlens.db'}"


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Override top-level scalar keys from GUARDLENS_<KEY> env vars."""
    for key in (
        "host", "port", "data_dir", "db_url", "analysis_enabled",
        "analyze_fps", "model_weights", "device", "ssl_certfile", "ssl_keyfile",
    ):
        env_key = f"GUARDLENS_{key.upper()}"
        if env_key in os.environ:
            data[key] = os.environ[env_key]
    return data


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    """Load config from YAML (if present) + env overrides."""
    data: dict[str, Any] = {}
    cfg_path = Path(path) if path else (ROOT / "config.yaml")
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    data = _apply_env_overrides(data)
    cfg = Config(**data)

    # Ensure runtime dirs exist.
    Path(cfg.data_dir).mkdir(parents=True, exist_ok=True)
    cfg.snapshots_dir().mkdir(parents=True, exist_ok=True)
    cfg.faces_dir().mkdir(parents=True, exist_ok=True)
    cfg.clips_dir().mkdir(parents=True, exist_ok=True)
    return cfg
