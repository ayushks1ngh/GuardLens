"""Replaceable hand-gesture vocabulary plugins."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any, Optional

import numpy as np


class GestureVocabulary:
    key: str = ""
    label: str = ""
    scope: str = ""

    def setup(self, config: dict[str, Any]) -> None:
        pass

    def classify(self, landmarks: list[tuple[float, float, float]]) -> tuple[str, float]:
        return "unknown", 0.0


_REGISTRY: dict[str, type[GestureVocabulary]] = {}


def register_vocabulary(cls: type[GestureVocabulary]) -> type[GestureVocabulary]:
    if not cls.key:
        raise ValueError("gesture vocabulary must define a key")
    _REGISTRY[cls.key] = cls
    return cls


def create_vocabulary(key: str, config: Optional[dict] = None) -> GestureVocabulary:
    cls = _REGISTRY.get(key)
    if cls is None:
        raise KeyError(f"unknown gesture vocabulary {key!r}; available={sorted(_REGISTRY)}")
    vocabulary = cls(); vocabulary.setup(config or {}); return vocabulary


def vocabularies() -> list[dict]:
    return [{"key": key, "label": cls.label, "scope": cls.scope} for key, cls in sorted(_REGISTRY.items())]


def normalized_features(landmarks: list[tuple[float, float, float]]) -> np.ndarray:
    points = np.asarray(landmarks, dtype=np.float32)
    if points.shape != (21, 3):
        raise ValueError("hand landmarks must contain 21 xyz points")
    points = points - points[0]
    scale = float(np.max(np.linalg.norm(points[:, :2], axis=1))) or 1.0
    return (points / scale).reshape(-1)


def _discover() -> None:
    for module in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if not module.name.startswith("_") and module.name != "base":
            importlib.import_module(f"{__name__}.{module.name}")


_discover()
