"""Puts the Kit extension's folder on sys.path, so tests import its Kit-free core (isaacsim.mcp.bridge.core)."""

import sys
from pathlib import Path

import pytest

EXTENSION_ROOT = Path(__file__).resolve().parents[1] / "extension" / "isaacsim.mcp.bridge-1.0.0"
sys.path.insert(0, str(EXTENSION_ROOT))


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private token folder, and no token from the environment: never the developer's real ones."""
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path
