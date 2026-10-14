"""Download the face models into <data_dir>/models and verify their checksums.

  YuNet  (232 KB, MIT)  finds faces accurately
  SFace  (38.7 MB, Apache-2.0)  decides WHO a face is (replaces the weak pixel comparison)

Usage: python scripts/setup_face_model.py [--force]
GuardLens never downloads models by itself; without them it falls back to the older, less accurate methods.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens import models  # noqa: E402
from guardlens.detectors.face_detector import YUNET_FILE, YUNET_SHA256, YUNET_URL  # noqa: E402


def main() -> int:
    folder, force, failed = models.models_dir(), "--force" in sys.argv, False
    for name, url, digest in ((YUNET_FILE, YUNET_URL, YUNET_SHA256), (models.SFACE_FILE, models.SFACE_URL, models.SFACE_SHA256)):
        ok, message = models.download_verified(url, digest, folder / name, force=force)
        print(message)
        failed |= not ok
    if not failed:
        print("Restart GuardLens to use them. People enrolled earlier are re-embedded automatically at startup.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
