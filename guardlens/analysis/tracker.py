"""Lightweight IoU/centroid tracker (ADR-004).

Assigns stable ``track_id``s across frames so higher-level rules (loitering,
line-crossing) have continuity. Pure Python/NumPy, detector-agnostic, CPU-cheap.
Greedy IoU matching with a small "max age" so a track survives a few missed
frames. Can be swapped for ByteTrack later behind the same seam (OQ-3).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from guardlens.types import BBox, Detection


def _iou(a: BBox, b: BBox) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _centroid_distance(a: BBox, b: BBox) -> float:
    ax = (a[0] + a[2]) / 2.0
    ay = (a[1] + a[3]) / 2.0
    bx = (b[0] + b[2]) / 2.0
    by = (b[1] + b[3]) / 2.0
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


@dataclass
class _Track:
    track_id: int
    bbox: BBox
    class_name: str
    age: int = 0           # frames since last matched
    hits: int = 1
    history: list[Detection] = field(default_factory=list)


class CentroidTracker:
    """Greedy IoU tracker. One instance per camera."""

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_centroid_distance: float = 0.08,
        max_age: int = 15,
        history_len: int = 60,
    ):
        self.iou_threshold = iou_threshold
        self.max_centroid_distance = max_centroid_distance
        self.max_age = max_age
        self.history_len = history_len
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def update(self, detections: list[Detection]) -> list[Detection]:
        """Assign track_ids in-place and return the same detections list."""
        unmatched_tracks = set(self._tracks.keys())
        matched_track_ids: set[int] = set()

        # Build candidate (iou, det_idx, track_id) pairs, match greedily.
        candidates = []
        for di, det in enumerate(detections):
            for tid, trk in self._tracks.items():
                iou = _iou(det.bbox, trk.bbox)
                distance = _centroid_distance(det.bbox, trk.bbox)
                if (
                    det.class_name == trk.class_name
                    and (iou >= self.iou_threshold or distance <= self.max_centroid_distance)
                ):
                    # Prefer overlap first, then the nearest centroid.
                    score = iou + max(0.0, 1.0 - distance)
                    candidates.append((score, di, tid))
        candidates.sort(reverse=True)

        used_dets: set[int] = set()
        for score, di, tid in candidates:
            if di in used_dets or tid in matched_track_ids:
                continue
            det = detections[di]
            det.track_id = tid
            trk = self._tracks[tid]
            trk.bbox = det.bbox
            trk.age = 0
            trk.hits += 1
            trk.history.append(det)
            if len(trk.history) > self.history_len:
                trk.history.pop(0)
            matched_track_ids.add(tid)
            unmatched_tracks.discard(tid)
            used_dets.add(di)

        # New tracks for unmatched detections.
        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            tid = self._next_id
            self._next_id += 1
            det.track_id = tid
            self._tracks[tid] = _Track(
                track_id=tid, bbox=det.bbox, class_name=det.class_name, history=[det]
            )

        # Age out stale tracks.
        for tid in list(unmatched_tracks):
            trk = self._tracks[tid]
            trk.age += 1
            if trk.age > self.max_age:
                del self._tracks[tid]

        return detections

    def histories(self) -> dict[int, list[Detection]]:
        """Map track_id -> recent detection history (for FrameContext.tracks)."""
        return {tid: list(trk.history) for tid, trk in self._tracks.items()}
