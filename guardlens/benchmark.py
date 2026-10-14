"""Detector accuracy against human-checked labels (Stage 3.2): precision, recall and F1 per class.

Labels are pixel boxes ``{"photo.jpg": {"person": [[x1, y1, x2, y2], ...], "face": [...]}}``. A detection counts as right
(true positive) when it overlaps an unmatched label of the same class with IoU >= 0.5; extra detections are false alarms,
unmatched labels are misses.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

Box = tuple[float, float, float, float]
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match(preds: list[tuple[float, Box]], truths: list[Box], threshold: float = 0.5) -> tuple[int, int, int]:
    """Greedy one-to-one matching, most confident detection first. Returns (true positives, false alarms, misses)."""
    free = list(range(len(truths)))
    tp = 0
    for _conf, box in sorted(preds, key=lambda p: -p[0]):
        best, best_iou = None, threshold
        for i in free:
            value = iou(box, truths[i])
            if value >= best_iou:
                best, best_iou = i, value
        if best is not None:
            free.remove(best)
            tp += 1
    return tp, len(preds) - tp, len(free)


def evaluate(predictions: dict[str, list[tuple[str, float, Box]]], labels: dict[str, dict[str, list[Box]]],
             classes: Optional[Iterable[str]] = None, threshold: float = 0.5, min_conf: float = 0.0) -> dict[str, dict]:
    """Per-class counts and scores over every labelled image. Images without labels for a class count as 'none there'."""
    wanted = sorted(set(classes) if classes else {c for per in labels.values() for c in per})
    result = {}
    for cls in wanted:
        tp = fp = fn = 0
        for image, truth_by_class in labels.items():
            preds = [(conf, box) for c, conf, box in predictions.get(image, []) if c == cls and conf >= min_conf]
            a, b, c = match(preds, [tuple(t) for t in truth_by_class.get(cls, [])], threshold)
            tp, fp, fn = tp + a, fp + b, fn + c
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result[cls] = {"true_positives": tp, "false_alarms": fp, "misses": fn, "precision": round(precision, 3),
                       "recall": round(recall, 3), "f1": round(f1, 3)}
    return result


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)


def run_detectors(image, detectors) -> list[tuple[str, float, Box]]:
    """Run detector plugins on one BGR image; boxes come back in pixels."""
    height, width = image.shape[:2]
    found = []
    for detector in detectors:
        for d in detector.process_for_camera(0, image):
            if d.class_name == "motion":
                continue
            x1, y1, x2, y2 = d.bbox
            found.append((d.class_name, float(d.confidence), (x1 * width, y1 * height, x2 * width, y2 * height)))
    return found


def to_labels(predictions: dict[str, list[tuple[str, float, Box]]], min_conf: float = 0.4) -> dict[str, dict[str, list[list[int]]]]:
    """Turn detector output into a draft label file for a human to correct (delete wrong boxes, add missed ones)."""
    draft: dict[str, dict[str, list[list[int]]]] = {}
    for image, preds in predictions.items():
        per: dict[str, list[list[int]]] = {}
        for cls, conf, box in preds:
            if conf >= min_conf:
                per.setdefault(cls, []).append([round(v) for v in box])
        draft[image] = per
    return draft


def load_labels(path: Path) -> dict[str, dict[str, list[Box]]]:
    raw = json.loads(path.read_text())
    return {image: {cls: [tuple(map(float, b)) for b in boxes] for cls, boxes in per.items()} for image, per in raw.items()}


def markdown_report(name: str, scores: dict[str, dict], images: int, threshold: float, min_conf: float) -> str:
    lines = [f"# Detector benchmark — {name}", "",
             f"{images} labelled images, a detection is right when it overlaps a label with IoU ≥ {threshold}, "
             f"detections below confidence {min_conf} ignored.", "",
             "| class | right | false alarms | missed | precision | recall | F1 |", "|---|---|---|---|---|---|---|"]
    for cls, s in scores.items():
        lines.append(f"| {cls} | {s['true_positives']} | {s['false_alarms']} | {s['misses']} | {s['precision']:.0%} | {s['recall']:.0%} | {s['f1']:.2f} |")
    lines += ["", "*Precision = of what it reported, how much was real. Recall = of what was really there, how much it found.*", ""]
    return "\n".join(lines)
