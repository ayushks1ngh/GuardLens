"""Check (and where safe, install) GuardLens's optional detectors.

  python scripts/setup_optional.py              show what is ready and the exact next step for the rest
  python scripts/setup_optional.py --hand-model download + verify the MediaPipe hand model (7.8 MB)

Installing the Python packages is deliberately left to you: `mediapipe` brings its own OpenCV build and can replace
the one GuardLens pins, so do it in a virtualenv you can throw away and run `pip check` afterwards.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from guardlens import models  # noqa: E402
from guardlens.detectors.face_detector import YUNET_FILE  # noqa: E402


def has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def status() -> list[dict]:
    mdir = models.models_dir()
    face = (mdir / YUNET_FILE).is_file()
    hand_model = (mdir / models.HAND_FILE).is_file()
    return [
        {"feature": "Better face detection (YuNet)", "ready": face,
         "next": "" if face else "python scripts/setup_face_model.py"},
        {"feature": "Hand gestures (MediaPipe)", "ready": has("mediapipe") and hand_model,
         "next": " ".join(filter(None, [
             "" if has("mediapipe") else "pip install mediapipe   (then: pip check)",
             "" if hand_model else "python scripts/setup_optional.py --hand-model",
             f"then in config.yaml add:  - key: hand_gesture / landmarker_model: {mdir / models.HAND_FILE}"]))},
        {"feature": "Find any object by name (YOLO-World)", "ready": has("clip") and (ROOT / "yolov8s-worldv2.pt").is_file(),
         "next": "" if has("clip") else "pip install git+https://github.com/ultralytics/CLIP.git   then add `- key: open_vocab, classes: [backpack]` to config.yaml"},
    ]


def main() -> int:
    if "--hand-model" in sys.argv:
        ok, message = models.download_verified(models.HAND_URL, models.HAND_SHA256, models.models_dir() / models.HAND_FILE)
        print(message)
        return 0 if ok else 1
    for row in status():
        print(f"{'READY  ' if row['ready'] else 'NOT YET'}  {row['feature']}")
        if row["next"]:
            print(f"         next: {row['next']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
