"""Model files GuardLens never downloads by itself: one checksum-verified downloader for the setup scripts."""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

HAND_FILE = "hand_landmarker.task"
HAND_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"
HAND_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/" + HAND_FILE


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def models_dir(data_dir: str | Path | None = None) -> Path:
    from guardlens.config import load_config
    return Path(data_dir or load_config().data_dir) / "models"


def download_verified(url: str, expected_sha256: str, target: Path, *, force: bool = False) -> tuple[bool, str]:
    """Fetch ``url`` to ``target`` only if its SHA-256 matches. Returns (ok, message); nothing is kept on a mismatch."""
    if target.is_file() and sha256(target) == expected_sha256 and not force:
        return True, f"Already installed and verified: {target}"
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (fixed https URLs from this module)
            partial.write_bytes(response.read())
    except OSError as exc:
        partial.unlink(missing_ok=True)
        return False, f"Download failed ({exc}). Check the internet connection and try again."
    if sha256(partial) != expected_sha256:
        partial.unlink(missing_ok=True)
        return False, "Checksum mismatch: the download is not the expected file. Nothing was installed."
    partial.replace(target)
    return True, f"Installed and verified: {target}"
