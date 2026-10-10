"""Detector plugins + registry (see docs/07-extensibility.md §2).

A ``Detector`` turns a raw BGR frame into a list of normalized ``Detection``s.
Detectors register themselves via ``@register``; the analysis pipeline runs
whatever is enabled in config. Adding a new detector means dropping a file here
and decorating it — **no core edits** (the flexibility invariant, ADR-007).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import numpy as np

from guardlens.types import Detection

logger = logging.getLogger("guardlens.detectors")


class Detector:
    """Base interface every detector plugin implements."""

    key: str = ""

    def setup(self, config: dict) -> None:
        """Load the model once (called before first use)."""

    def process(self, frame: np.ndarray) -> list[Detection]:  # pragma: no cover
        raise NotImplementedError

    def teardown(self) -> None:
        """Release resources (optional)."""


# ---------------------------------------------------------------------------
# Registry: maps key -> Detector class. The extensibility seam.
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, type[Detector]] = {}


def register(cls: type[Detector]) -> type[Detector]:
    """Class decorator: register a detector under its ``key``."""
    key = getattr(cls, "key", "") or ""
    if not key:
        raise ValueError(f"Detector {cls.__name__} must define a non-empty 'key'")
    if key in _REGISTRY and _REGISTRY[key] is not cls:
        logger.warning("detector key %r already registered; overriding", key)
    _REGISTRY[key] = cls
    return cls


def get_detector_class(key: str) -> Optional[type[Detector]]:
    return _REGISTRY.get(key)


def available_detectors() -> list[str]:
    return sorted(_REGISTRY.keys())


def create_detector(key: str, config: dict) -> Detector:
    """Instantiate + set up a registered detector by key."""
    cls = _REGISTRY.get(key)
    if cls is None:
        raise KeyError(f"unknown detector key {key!r}; available: {available_detectors()}")
    inst = cls()
    inst.setup(config)
    return inst


# Discover plugin modules automatically. A new ``*.py`` plugin file is imported
# without editing this registry; private/base modules are ignored.
def _discover_plugins() -> None:
    import importlib
    import pkgutil
    from pathlib import Path

    package = __name__
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if module.name.startswith("_") or module.name in {"base"}:
            continue
        importlib.import_module(f"{package}.{module.name}")


_discover_plugins()
