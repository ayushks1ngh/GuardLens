"""Runs every detector plugin on the bundled sample video and prints what each one finds.

Usage: python scripts/check_detectors.py [video] [--frames N]
Exit code is non-zero when a detector that should work crashes or finds nothing it should.
"""
import sys
import time
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens.detectors import available_detectors, create_detector  # noqa: E402

CONFIGS = {
    "object": {"conf": 0.4, "imgsz": 640},
    "face": {"backend": "opencv", "min_size": 40},
    "motion": {"warmup_frames": 3},
    "hand_gesture": {},
    "open_vocab": {"classes": ["backpack"]},
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    video = Path(args[0]) if args else ROOT / "data" / "samples" / "mall_cctv.mp4"
    frames_wanted = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else 60
    cap = cv2.VideoCapture(str(video))
    frames = []
    while cap.isOpened() and len(frames) < frames_wanted:
        ok, frame = cap.read()
        if not ok:
            break
        for _ in range(4):  # skip frames so motion has something to see
            cap.grab()
        frames.append(frame)
    cap.release()
    print(f"{video.name}: {len(frames)} frames, {frames[0].shape[1]}x{frames[0].shape[0]}")
    failed = False
    for key in available_detectors():
        try:
            det = create_detector(key, CONFIGS.get(key, {}))
        except Exception as exc:  # optional dependency or model missing
            print(f"SKIP  {key:13s} cannot start: {type(exc).__name__}: {str(exc)[:90]}")
            continue
        found, started = {}, time.time()
        try:
            for frame in frames:
                for d in det.process_for_camera(1, frame):
                    found[d.class_name] = found.get(d.class_name, 0) + 1
        except Exception as exc:
            print(f"FAIL  {key:13s} crashed: {type(exc).__name__}: {exc}")
            failed = True
            continue
        ms = (time.time() - started) * 1000 / len(frames)
        print(f"OK    {key:13s} {ms:6.1f} ms/frame  found: {found or 'nothing'}")
        if key in ("object", "motion") and not found:
            print(f"FAIL  {key} found nothing on footage that has people and movement")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
