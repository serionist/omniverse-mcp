"""The server's command line and environment."""

import argparse
import os
from collections.abc import Mapping, Sequence

# Flags from before the rename (#8), refused with the name that replaced them rather than ignored.
RENAMED_FLAGS = {"--isaac-host": "--host", "--isaac-port": "--port"}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8211


def parse_args(argv: Sequence[str], environ: Mapping[str, str] = os.environ) -> argparse.Namespace:
    """Parse the server's flags. An unknown flag is an error. An empty OMNIVERSE_MCP_* variable counts as unset,
    since MCP clients expand an unset ${VAR} in their config to ""."""
    parser = argparse.ArgumentParser(
        prog="omniverse-mcp",
        description="Omniverse MCP server: drives a Kit app through its ovmcp.bridge extension, over MCP stdio.",
    )
    parser.add_argument("--host", default=environ.get("OMNIVERSE_MCP_HOST") or DEFAULT_HOST,
                        help=f"Kit extension host (default: OMNIVERSE_MCP_HOST, else {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=None,
                        help=f"Kit extension port (default: OMNIVERSE_MCP_PORT, else {DEFAULT_PORT})")
    parser.add_argument("--output-dir", default=environ.get("OMNIVERSE_MCP_OUTPUT_DIR") or "",
                        help="Directory for file outputs (default: OMNIVERSE_MCP_OUTPUT_DIR, else ./mcp_output)")
    for arg in argv:
        name = arg.split("=", 1)[0]
        if name in RENAMED_FLAGS:
            parser.error(f"{name} was renamed {RENAMED_FLAGS[name]}")
    args = parser.parse_args(list(argv))
    if args.port is None:
        port = environ.get("OMNIVERSE_MCP_PORT") or str(DEFAULT_PORT)
        try:
            args.port = int(port)
        except ValueError:
            parser.error(f"OMNIVERSE_MCP_PORT must be a port number, not {port!r}")
    return args
