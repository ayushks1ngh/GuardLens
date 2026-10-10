"""Validate a camera source through the same adapter used by GuardLens.

Usage:
    python scripts/check_source.py "data/samples/mall_cctv.mp4"
    python scripts/check_source.py 0
    python scripts/check_source.py "http://192.168.1.42:8080/video"

The OpenCV adapter infers device/file/network mode from the legacy value. The
Add Camera wizard provides explicit typed configuration and the same one-frame
probe over HTTP.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow direct execution as documented: ``python scripts/check_source.py ...``.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from guardlens.capture.sources import create_source


def check(source: str) -> int:
    try:
        adapter = create_source("opencv", legacy_source=source)
    except Exception as exc:
        print(f"FAIL: invalid source {source!r}: {exc}")
        return 2

    try:
        if not adapter.open():
            print(f"FAIL: {adapter.status.error or 'could not open source'}")
            return 1
        ok, frame = adapter.read()
        if not ok or frame is None:
            print(f"FAIL: opened {source!r} but could not read a frame")
            return 1
        height, width = frame.shape[:2]
        print(
            f"OK: {adapter.display_source!r} -> {width}x{height} "
            f"@ {adapter.status.fps:.1f} fps (first frame read)"
        )
        return 0
    finally:
        adapter.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(check(sys.argv[1]))
