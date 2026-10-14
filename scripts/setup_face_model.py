"""Download the YuNet face-detection model (232 KB, MIT licence) into <data_dir>/models and verify its checksum.

Usage: python scripts/setup_face_model.py [--force]
GuardLens never downloads models by itself; without this file the face detector falls back to the older Haar cascade.
"""
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens.detectors.face_detector import YUNET_SHA256, YUNET_URL, default_model_path  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    target = default_model_path()
    if target.is_file() and sha256(target) == YUNET_SHA256 and "--force" not in sys.argv:
        print(f"Already installed and verified: {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    print(f"Downloading {YUNET_URL}")
    with urllib.request.urlopen(YUNET_URL, timeout=60) as response:  # noqa: S310 (fixed https URL)
        partial.write_bytes(response.read())
    if sha256(partial) != YUNET_SHA256:
        partial.unlink(missing_ok=True)
        print("Checksum mismatch: the download is not the expected model. Nothing was installed.")
        return 1
    partial.replace(target)
    print(f"Installed and verified: {target}\nRestart GuardLens to use it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
