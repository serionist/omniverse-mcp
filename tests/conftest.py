"""Puts the Kit extension's folder on sys.path, so tests import its Kit-free core (ovmcp.core)."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = REPO_ROOT / "extension" / "ovmcp.bridge"
sys.path.insert(0, str(EXTENSION_ROOT))


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private token folder, and no token from the environment: never the developer's real ones."""
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path
