"""Download the YuNet face-detection model (232 KB, MIT licence) into <data_dir>/models and verify its checksum.

Usage: python scripts/setup_face_model.py [--force]
GuardLens never downloads models by itself; without this file the face detector falls back to the older Haar cascade.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens.detectors.face_detector import YUNET_SHA256, YUNET_URL, default_model_path  # noqa: E402
from guardlens.models import download_verified  # noqa: E402


def main() -> int:
    ok, message = download_verified(YUNET_URL, YUNET_SHA256, default_model_path(), force="--force" in sys.argv)
    print(message + ("\nRestart GuardLens to use it." if ok and message.startswith("Installed") else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
