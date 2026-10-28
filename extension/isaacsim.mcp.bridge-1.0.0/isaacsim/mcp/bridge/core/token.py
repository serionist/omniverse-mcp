"""The bridge token: made at startup, written where the MCP server running as the same user can read it.

`state_dir` and `token_path` must give the same answer as `isaac_sim_mcp/bridge_token.py` on the server side;
`tests/test_bridge_token.py` keeps them equal.
"""

import os
import secrets
import sys
from pathlib import Path

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


def new_token() -> str:
    return secrets.token_urlsafe(32)


def write_token(port: int, token: str) -> Path:
    """Write the token readable by this user only, replacing the file in one step so a reader never sees half."""
    path = token_path(port)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    if sys.platform != "win32":
        # O_CREAT keeps the mode of a file left over from an earlier run.
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def remove_token(port: int, token: str) -> None:
    """Remove the token file, unless it now holds another instance's token."""
    path = token_path(port)
    try:
        if path.read_text(encoding="utf-8").strip() == token:
            path.unlink()
    except OSError:
        pass
