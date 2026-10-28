"""Finding the bridge token the Kit extension writes at startup.

`state_dir` and `token_path` mirror the extension's core/token.py; tests/test_bridge_token.py keeps them equal.
"""

import os
import sys
from pathlib import Path

ENV_TOKEN = "OMNIVERSE_MCP_TOKEN"
ENV_STATE_DIR = "OMNIVERSE_MCP_STATE_DIR"


def state_dir() -> Path:
    override = os.environ.get(ENV_STATE_DIR)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "omniverse-mcp"


def token_path(port: int) -> Path:
    return state_dir() / f"bridge-{port}.token"


def read_token(port: int) -> str | None:
    """OMNIVERSE_MCP_TOKEN if set, else the token file for this port, else None."""
    from_env = os.environ.get(ENV_TOKEN, "").strip()
    if from_env:
        return from_env
    try:
        return token_path(port).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
