"""Core data contracts shared across the pipeline.

These are the stable "language" every plugin speaks (see docs/07-extensibility.md).
Detectors produce ``Detection``s, the pipeline assembles a ``FrameContext``, and
rules emit ``EventDraft``s. As long as a plugin produces/consumes these shapes it
fits — regardless of the model or logic inside it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# Normalized bounding box: (x1, y1, x2, y2) each in 0..1 relative to frame size.
BBox = tuple[float, float, float, float]


@dataclass
class Detection:
    """A single detected object/entity in a frame."""

    class_name: str
    confidence: float
    bbox: BBox
    track_id: Optional[int] = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox
        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def area(self) -> float:
        x1, y1, x2, y2 = self.bbox
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)


@dataclass
class Zone:
    """A polygon region on a camera, in normalized (0..1) coordinates."""

    id: int
    name: str
    polygon: list[tuple[float, float]]


@dataclass
class FrameContext:
    """Everything a rule needs to evaluate one analyzed frame."""

    camera_id: int
    timestamp: float
    frame_shape: tuple[int, int]  # (height, width)
    detections: list[Detection] = field(default_factory=list)
    tracks: dict[int, list[Detection]] = field(default_factory=dict)
    zones: list[Zone] = field(default_factory=list)
    frame: Optional[np.ndarray] = None  # BGR frame for snapshot evidence


@dataclass
class EventDraft:
    """A rule's output, before it is persisted as an Event."""

    type: str
    severity: str  # info | warning | critical
    metadata: dict[str, Any] = field(default_factory=dict)
    person_id: Optional[int] = None
    snapshot: Optional[np.ndarray] = None
