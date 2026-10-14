"""Stage 3.2: the accuracy maths is right, and the draft -> correct -> score loop works end to end."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from guardlens import benchmark as b

SOLVAY = Path("tests/assets/solvay_conference.jpg")


def test_iou():
    assert b.iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert b.iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert b.iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(1 / 3)
    assert b.iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


def test_matching_is_one_to_one_and_most_confident_first():
    truths = [(0, 0, 10, 10)]
    # two detections on one object: one is right, the duplicate is a false alarm
    assert b.match([(0.9, (0, 0, 10, 10)), (0.8, (1, 1, 10, 10))], truths) == (1, 1, 0)
    assert b.match([], truths) == (0, 0, 1)                      # nothing found: one miss
    assert b.match([(0.9, (50, 50, 60, 60))], truths) == (0, 1, 1)  # wrong place: false alarm + miss
    assert b.match([(0.5, (0, 0, 10, 10))], []) == (0, 1, 0)


def test_evaluate_scores_per_class():
    labels = {"a.jpg": {"person": [(0, 0, 10, 10), (20, 20, 30, 30)], "face": [(1, 1, 4, 4)]}, "b.jpg": {"person": []}}
    preds = {"a.jpg": [("person", 0.9, (0, 0, 10, 10)), ("face", 0.9, (1, 1, 4, 4)), ("face", 0.8, (50, 50, 60, 60))],
             "b.jpg": [("person", 0.95, (5, 5, 9, 9))]}
    s = b.evaluate(preds, labels)
    assert s["person"] == {"true_positives": 1, "false_alarms": 1, "misses": 1, "precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert s["face"]["true_positives"] == 1 and s["face"]["false_alarms"] == 1 and s["face"]["recall"] == 1.0
    assert b.evaluate(preds, labels, min_conf=0.92)["person"]["true_positives"] == 0  # low-confidence detections ignored
    assert list(b.evaluate(preds, labels, classes=["face"])) == ["face"]


def test_draft_labels_round_trip_and_report():
    preds = {"x.jpg": [("person", 0.9, (1.4, 2.6, 30.2, 40.9)), ("car", 0.1, (0, 0, 5, 5))]}
    draft = b.to_labels(preds, min_conf=0.4)
    assert draft == {"x.jpg": {"person": [[1, 3, 30, 41]]}}
    report = b.markdown_report("demo", b.evaluate(preds, {"x.jpg": {"person": [(1, 3, 30, 41)]}}), 1, 0.5, 0.4)
    assert "| person | 1 | 0 | 0 | 100% | 100% | 1.00 |" in report


@pytest.mark.skipif(not SOLVAY.exists(), reason="test photo missing")
def test_command_line_loop_on_the_group_photo(tmp_path):
    from guardlens.detectors.face_detector import YUNET_FILE
    if not (Path("data/models") / YUNET_FILE).is_file():
        pytest.skip("run scripts/setup_face_model.py first")
    folder = tmp_path / "set"; folder.mkdir()
    cv2.imwrite(str(folder / "solvay.jpg"), cv2.imread(str(SOLVAY)))
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("GUARDLENS_DATA_DIR", "GUARDLENS_DB_URL")}  # the project's own data dir
    run = lambda *a: subprocess.run([sys.executable, "scripts/benchmark_detectors.py", *a], capture_output=True, text=True, timeout=180, env=env)
    assert "labels.json" in run("run", str(folder)).stdout  # no labels yet: tells you what to do
    draft = run("draft", str(folder))
    assert draft.returncode == 0, draft.stderr
    labels = json.loads((folder / "labels.draft.json").read_text())
    assert len(labels["solvay.jpg"]["face"]) >= 28 and (folder / "review" / "solvay.jpg").exists()
    (folder / "labels.json").write_text(json.dumps(labels))  # a human would correct it here
    done = run("run", str(folder), "--classes", "face", "--report", str(tmp_path / "r.md"))
    assert done.returncode == 0 and "| face |" in done.stdout and "100%" in done.stdout and (tmp_path / "r.md").exists()
