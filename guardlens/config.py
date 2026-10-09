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


class Config(BaseModel):
    """Validated application configuration."""

    host: str = "0.0.0.0"
    port: int = 8080

    # Storage
    data_dir: str = str(ROOT / "data")
    db_url: str = ""  # derived from data_dir if empty

    # Analysis
    analyze_fps: float = 6.0
    model_weights: str = "yolov8n.pt"
    device: str = "cpu"

    # Enabled plugins (keys resolved against the registries)
    detectors: list[dict[str, Any]] = Field(default_factory=lambda: [{"key": "object"}])
    notifiers: list[dict[str, Any]] = Field(default_factory=list)

    reporting: ReportingConfig = Field(default_factory=ReportingConfig)

    def snapshots_dir(self) -> Path:
        return Path(self.data_dir) / "snapshots"

    def faces_dir(self) -> Path:
        return Path(self.data_dir) / "faces"

    def resolved_db_url(self) -> str:
        if self.db_url:
            return self.db_url
        return f"sqlite:///{Path(self.data_dir) / 'guardlens.db'}"


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Override top-level scalar keys from GUARDLENS_<KEY> env vars."""
    for key in ("host", "port", "data_dir", "db_url", "analyze_fps", "model_weights", "device"):
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
    return cfg
