"""The server's command line and environment."""

import argparse
import os
from collections.abc import Mapping, Sequence

# Flags from before the rename (#8), refused with the name that replaced them rather than ignored.
RENAMED_FLAGS = {"--isaac-host": "--host", "--isaac-port": "--port"}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8211


def parse_args(argv: Sequence[str], environ: Mapping[str, str] = os.environ) -> argparse.Namespace:
    """Parse the server's flags, or `extension <action>` (command "extension"; None for the server). An unknown flag
    is an error. An empty OMNIVERSE_MCP_* variable counts as unset, since MCP clients expand an unset ${VAR} in their
    config to ""."""
    argv = list(argv)
    # The command is routed by its first word rather than as an argparse subcommand, which would read a mistyped
    # flag's value as an unknown command.
    if argv[:1] == ["extension"]:
        extension = argparse.ArgumentParser(
            prog="omniverse-mcp extension", description="The Kit extension ovmcp.bridge of this release."
        )
        extension.add_argument(
            "action",
            choices=["install", "path"],
            help="install: copy it to your user data folder, in place of an older one; path: print that folder, which "
            "Kit's extension search paths need",
        )
        return extension.parse_args(argv[1:], argparse.Namespace(command="extension"))
    parser = argparse.ArgumentParser(
        prog="omniverse-mcp",
        description="Omniverse MCP server: drives a Kit app through its ovmcp.bridge extension, over MCP stdio.",
        epilog="omniverse-mcp extension install|path: install the Kit extension of this release, or print where it "
        "is installed.",
    )
    parser.add_argument(
        "--host",
        default=environ.get("OMNIVERSE_MCP_HOST") or DEFAULT_HOST,
        help=f"Kit extension host (default: OMNIVERSE_MCP_HOST, else {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port", type=int, default=None, help=f"Kit extension port (default: OMNIVERSE_MCP_PORT, else {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--output-dir",
        default=environ.get("OMNIVERSE_MCP_OUTPUT_DIR") or "",
        help="Directory for file outputs (default: OMNIVERSE_MCP_OUTPUT_DIR, else ./mcp_output)",
    )
    for arg in argv:
        name = arg.split("=", 1)[0]
        if name in RENAMED_FLAGS:
            parser.error(f"{name} was renamed {RENAMED_FLAGS[name]}")
    args = parser.parse_args(argv, argparse.Namespace(command=None))
    if args.port is None:
        port = environ.get("OMNIVERSE_MCP_PORT") or str(DEFAULT_PORT)
        try:
            args.port = int(port)
        except ValueError:
            parser.error(f"OMNIVERSE_MCP_PORT must be a port number, not {port!r}")
    return args
