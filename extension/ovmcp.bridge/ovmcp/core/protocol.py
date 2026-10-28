"""What the bridge tells the MCP server about itself in /health."""

# Raised when the server and the extension stop understanding each other's requests. The server's copy is
# omniverse_mcp.client.PROTOCOL; tests/test_bridge_token.py keeps them equal.
PROTOCOL = 1

EXTENSION_NAME = "ovmcp.bridge"

_version = "unknown"


def version_from_ext_id(ext_id: str) -> str:
    """Kit hands on_startup an id of the form '<name>-<version>'."""
    prefix = EXTENSION_NAME + "-"
    return ext_id[len(prefix) :] if ext_id.startswith(prefix) else "unknown"


def set_extension_version(version: str) -> None:
    global _version
    _version = version


def extension_version() -> str:
    return _version
