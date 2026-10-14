"""Measure detector accuracy on your own footage.

  1. python scripts/benchmark_detectors.py frames  clip.mp4 --every 60 --max 40 --out bench/mine
  2. python scripts/benchmark_detectors.py draft   bench/mine         # writes labels.draft.json + review/ pictures
  3. Fix the draft (delete wrong boxes, add missed ones) and save it as bench/mine/labels.json
     (boxes are pixels: [x1, y1, x2, y2]; one list per class per image)
  4. python scripts/benchmark_detectors.py run     bench/mine [--classes person face] [--report docs/benchmarks/mine.md]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens import benchmark  # noqa: E402
from guardlens.config import load_config  # noqa: E402
from guardlens.detectors import create_detector  # noqa: E402


def detectors():
    cfg = load_config()
    return [create_detector(d["key"], {k: v for k, v in d.items() if k != "key"}) for d in cfg.detectors if d["key"] != "motion"]


def cmd_frames(args) -> int:
    cap = cv2.VideoCapture(args.video)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    saved = index = 0
    while saved < args.max:
        ok, frame = cap.read()
        if not ok:
            break
        if index % args.every == 0:
            cv2.imwrite(str(out / f"{Path(args.video).stem}_{index:06d}.jpg"), frame)
            saved += 1
        index += 1
    print(f"Saved {saved} frames to {out}")
    return 0


def predict(folder: Path):
    dets = detectors()
    return {p.name: benchmark.run_detectors(cv2.imread(str(p)), dets) for p in benchmark.list_images(folder)}


def cmd_draft(args) -> int:
    folder = Path(args.folder)
    preds = predict(folder)
    draft = benchmark.to_labels(preds, args.conf)
    (folder / "labels.draft.json").write_text(json.dumps(draft, indent=1))
    review = folder / "review"; review.mkdir(exist_ok=True)
    for name, per in draft.items():
        image = cv2.imread(str(folder / name))
        for cls, boxes in per.items():
            for n, (x1, y1, x2, y2) in enumerate(boxes):
                cv2.rectangle(image, (x1, y1), (x2, y2), (0, 220, 255) if cls == "person" else (0, 255, 0), 2)
                cv2.putText(image, f"{cls}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.imwrite(str(review / name), image)
    print(f"Draft written: {folder / 'labels.draft.json'} ({len(draft)} images). Pictures to check: {review}")
    print("Correct it and save as labels.json, then run:  python scripts/benchmark_detectors.py run", folder)
    return 0


def cmd_run(args) -> int:
    folder = Path(args.folder)
    labels_path = folder / "labels.json"
    if not labels_path.exists():
        print(f"No {labels_path}. Run `draft` first, correct the draft, and save it as labels.json.")
        return 1
    labels = benchmark.load_labels(labels_path)
    preds = predict(folder)
    scores = benchmark.evaluate(preds, labels, args.classes, args.iou, args.conf)
    report = benchmark.markdown_report(folder.name, scores, len(labels), args.iou, args.conf)
    print(report)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(report)
        print(f"Report saved: {args.report}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("frames"); f.add_argument("video"); f.add_argument("--every", type=int, default=60)
    f.add_argument("--max", type=int, default=40); f.add_argument("--out", required=True); f.set_defaults(fn=cmd_frames)
    d = sub.add_parser("draft"); d.add_argument("folder"); d.add_argument("--conf", type=float, default=0.4); d.set_defaults(fn=cmd_draft)
    r = sub.add_parser("run"); r.add_argument("folder"); r.add_argument("--classes", nargs="*")
    r.add_argument("--iou", type=float, default=0.5); r.add_argument("--conf", type=float, default=0.4)
    r.add_argument("--report"); r.set_defaults(fn=cmd_run)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
