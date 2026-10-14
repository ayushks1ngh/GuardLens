"""Stage 3.4: model downloads are checksum-verified and optional features report their next step."""
from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path

from guardlens import models


def _fake_download(monkeypatch, payload: bytes):
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload))


def test_good_download_is_installed_and_second_call_is_a_no_op(tmp_path, monkeypatch):
    data = b"model-bytes"
    _fake_download(monkeypatch, data)
    target = tmp_path / "m" / "x.onnx"
    ok, msg = models.download_verified("https://example.test/x", hashlib.sha256(data).hexdigest(), target)
    assert ok and target.read_bytes() == data and msg.startswith("Installed") and not list(target.parent.glob("*.part"))
    monkeypatch.setattr(models.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not download again")))
    assert models.download_verified("https://example.test/x", hashlib.sha256(data).hexdigest(), target)[1].startswith("Already")


def test_tampered_download_is_refused_and_leaves_nothing_behind(tmp_path, monkeypatch):
    _fake_download(monkeypatch, b"evil")
    target = tmp_path / "x.onnx"
    ok, msg = models.download_verified("https://example.test/x", hashlib.sha256(b"good").hexdigest(), target)
    assert not ok and "Checksum mismatch" in msg and not target.exists() and not list(tmp_path.glob("*.part"))


def test_network_failure_is_reported_in_plain_words(tmp_path, monkeypatch):
    def down(*a, **k): raise OSError("no route")
    monkeypatch.setattr(models.urllib.request, "urlopen", down)
    ok, msg = models.download_verified("https://example.test/x", "0" * 64, tmp_path / "x")
    assert not ok and "Download failed" in msg and "internet connection" in msg


def test_a_corrupt_existing_file_is_replaced(tmp_path, monkeypatch):
    target = tmp_path / "x"; target.write_bytes(b"corrupt")
    _fake_download(monkeypatch, b"fresh")
    assert models.download_verified("https://example.test/x", hashlib.sha256(b"fresh").hexdigest(), target)[0]
    assert target.read_bytes() == b"fresh"


def test_optional_status_lists_every_feature_with_a_next_step():
    spec = importlib.util.spec_from_file_location("setup_optional", Path("scripts/setup_optional.py"))
    script = importlib.util.module_from_spec(spec); spec.loader.exec_module(script)
    rows = script.status()
    assert [r["feature"] for r in rows] == ["Better face detection (YuNet)", "Hand gestures (MediaPipe)", "Find any object by name (YOLO-World)"]
    for row in rows:
        assert row["ready"] or row["next"]  # never "not ready" without saying what to do
