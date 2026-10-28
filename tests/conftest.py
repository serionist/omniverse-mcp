"""Puts the Kit extension's folder and tools/ on sys.path, so tests import the extension's Kit-free core
(ovmcp.core) and the gate, hooks and setup scripts."""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
# Where the live suites find the bridge, read as the server reads it, so a Kit app of your own can keep 8211.
LIVE_HOST = os.environ.get("OMNIVERSE_MCP_HOST", "127.0.0.1")
LIVE_PORT = int(os.environ.get("OMNIVERSE_MCP_PORT", "8211"))
EXTENSION_ROOT = REPO_ROOT / "extension" / "ovmcp.bridge"
sys.path.insert(0, str(EXTENSION_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The live suites run only with OMNIVERSE_MCP_SIM=1 (plan D11). A Kit app that happens to answer on the bridge's
    port is someone's open stage, which the scenarios change, and the coverage floor must not depend on one."""
    if os.environ.get("OMNIVERSE_MCP_SIM") == "1":
        return
    skip = pytest.mark.skip(reason="a live suite: set OMNIVERSE_MCP_SIM=1, with a Kit app running ovmcp.bridge")
    for item in items:
        if item.get_closest_marker("sim") or item.get_closest_marker("scenario"):
            item.add_marker(skip)


@pytest.fixture
def state(tmp_path, monkeypatch):
    """A private token folder, and no token from the environment: never the developer's real ones."""
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path
