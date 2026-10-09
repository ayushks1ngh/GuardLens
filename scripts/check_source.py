"""Validate a camera source (file path, index, or URL) before adding it.

Usage:
    python scripts/check_source.py "data/samples/mall_cctv.mp4"
    python scripts/check_source.py 0
    python scripts/check_source.py "http://192.168.1.42:8080/video"

Note (WSL2): a phone stream on your home Wi-Fi (192.168.x.x) is NOT reachable
from WSL2 by default. Use a recorded file, or enable mirrored networking
(see docs/06-tech-decisions.md / README). File sources always work.
"""
from __future__ import annotations

import sys


def check(source: str) -> int:
    try:
        import cv2
    except ImportError:
        print("ERROR: opencv not installed. Run: pip install -r requirements.txt")
        return 2

    src: object = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        print(f"FAIL: could not open source {source!r}")
        return 1

    ok, frame = cap.read()
    if not ok or frame is None:
        print(f"FAIL: opened {source!r} but could not read a frame")
        cap.release()
        return 1

    h, w = frame.shape[:2]
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"OK: {source!r} -> {w}x{h} @ {fps:.1f} fps (first frame read)")
    cap.release()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(check(sys.argv[1]))
