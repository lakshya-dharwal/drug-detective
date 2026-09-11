"""Test config: put the backend package root on sys.path and isolate the store."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture(autouse=True)
def isolated_experience_store(tmp_path, monkeypatch):
    """Every test gets its own empty JSONL store — never the developer's real one."""
    monkeypatch.setenv("AGENT_EXPERIENCE_PATH", str(tmp_path / "experience.jsonl"))
    yield
