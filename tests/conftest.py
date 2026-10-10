"""Shared test fixtures.

Tests run against an **isolated temporary database** (not the real
``data/guardlens.db``) so camera/event rows never leak between runs. We also
stop capture + analysis workers after each test so the shared singletons don't
leak threads (and, since Phase 2, don't leave YOLO analysis loops running).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a throwaway data dir + DB BEFORE anything imports config.
_TMP_DIR = tempfile.mkdtemp(prefix="guardlens-test-")
os.environ["GUARDLENS_DATA_DIR"] = _TMP_DIR
os.environ["GUARDLENS_DB_URL"] = f"sqlite:///{Path(_TMP_DIR) / 'test.db'}"
# Unit/API tests exercise analysis explicitly; do not load YOLO in every
# TestClient lifespan. Dedicated Phase 2 tests still run real inference.
os.environ["GUARDLENS_ANALYSIS_ENABLED"] = "false"

from guardlens.capture.manager import manager  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_workers():
    """Stop capture + analysis workers after each test (shared singletons)."""
    yield
    manager.stop_all()
    try:
        from guardlens.analysis.pipeline import analysis_manager
        analysis_manager.stop_all()
    except Exception:
        pass
    # Keep every test deterministic: remove all rows/tables; the next app
    # lifespan recreates them through init_engine().
    try:
        from sqlmodel import SQLModel
        from guardlens.events import get_engine
        SQLModel.metadata.drop_all(get_engine())
    except Exception:
        pass
