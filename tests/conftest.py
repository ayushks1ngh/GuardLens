"""Shared test fixtures."""
from __future__ import annotations

import pytest

from guardlens.capture.manager import manager


@pytest.fixture(autouse=True)
def _clean_camera_workers():
    """Ensure no leftover capture workers leak between tests (shared singleton)."""
    yield
    manager.stop_all()
