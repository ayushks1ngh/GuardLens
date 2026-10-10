"""Camera source adapters and automatic registry discovery.

Capture workers consume this stable contract instead of knowing how a device or
transport opens frames. New transports (for example WebRTC in Improvement Phase B)
register a new adapter without changing capture or analysis code.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np


@dataclass
class SourceStatus:
    opened: bool = False
    fps: float = 0.0
    width: int = 0
    height: int = 0
    error: Optional[str] = None


class CameraSource:
    """Stable interface implemented by every camera transport adapter."""

    key: str = ""
    label: str = ""
    modes: list[dict[str, Any]] = []

    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.status = SourceStatus()

    @classmethod
    def validate_config(cls, config: dict[str, Any]) -> dict[str, Any]:
        return dict(config)

    def open(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def read(self) -> tuple[bool, Optional[np.ndarray]]:  # pragma: no cover
        raise NotImplementedError

    def rewind(self) -> bool:
        return False

    def close(self) -> None:
        pass

    @property
    def is_file(self) -> bool:
        return False


_REGISTRY: dict[str, type[CameraSource]] = {}


def register_source(cls: type[CameraSource]) -> type[CameraSource]:
    if not cls.key:
        raise ValueError(f"CameraSource {cls.__name__} must define key")
    _REGISTRY[cls.key] = cls
    return cls


def get_source_class(key: str) -> Optional[type[CameraSource]]:
    return _REGISTRY.get(key)


def create_source(
    key: str,
    config: Optional[dict[str, Any]] = None,
    *,
    legacy_source: Optional[str | int] = None,
) -> CameraSource:
    cls = get_source_class(key)
    if cls is None:
        raise KeyError(f"unknown camera source adapter {key!r}; available={sorted(_REGISTRY)}")
    merged = dict(config or {})
    if "source" not in merged and legacy_source is not None:
        merged["source"] = legacy_source
    return cls(cls.validate_config(merged))


def source_types() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": cls.label or key, "modes": cls.modes}
        for key, cls in sorted(_REGISTRY.items())
    ]


def _discover() -> None:
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not module.name.startswith("_") and module.name not in {"base"}:
            importlib.import_module(f"{__name__}.{module.name}")


_discover()
