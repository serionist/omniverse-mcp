"""
Omniverse MCP Server

Standalone MCP server that bridges AI assistants to a running NVIDIA Omniverse Kit app
(Isaac Sim, USD Composer, ...) via its ovmcp.bridge extension.

Design principles:
- Images are always saved as PNG files, returning paths (never base64 inline).
- Scene/prim data uses grep-friendly prim-block text format.
- Any response > FILE_THRESHOLD chars is written to a file, returning a relative path.
- Small responses are returned inline as text.

Usage:
    omniverse-mcp
    omniverse-mcp --host 127.0.0.1 --port 8211
    python -m omniverse_mcp

Flags default to OMNIVERSE_MCP_HOST, OMNIVERSE_MCP_PORT and OMNIVERSE_MCP_OUTPUT_DIR. Importing this module does
nothing: main() reads the flags, and create_server() builds a server, as the tests do.
"""

import base64
import binascii
import json
import os
import sys
import threading
from collections.abc import Callable, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from .client import BridgeClient
from .config import parse_args
from .tools import register_all
from .tools._bridge import bridge_call

# Responses longer than this are written to files
FILE_THRESHOLD = 1000

INSTRUCTIONS = (
    "Connected to an NVIDIA Omniverse Kit app (Isaac Sim, USD Composer, ...). "
    "Controls USD scene, simulation, viewport, robots.\n"
    "Use Context7 MCP (library 'isaac-sim/isaacsim') before writing execute_script code.\n\n"
    "OUTPUT: Images saved as PNGs. Large text written to files. Paths are project-relative.\n"
    "Use Read tool to view images and large responses.\n\n"
    "Data uses prim-block format: [/prim/path] headers, key = value lines. Grep-friendly."
)


class Helpers:
    """The output folder the tools write images and long text to, and the counters that name the files.

    The SDK runs tools on worker threads, several at once, so the counters are taken under a lock.
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.capture_counter = 0
        self.response_counter = 0
        self._lock = threading.Lock()

    def rel(self, path: str) -> str:
        """Convert absolute path to project-relative using mcp_output/... shorthand."""
        try:
            return os.path.relpath(path, os.getcwd()).replace("\\", "/")
        except ValueError:
            return path

    def _next(self, counter: str) -> int:
        with self._lock:
            value = getattr(self, counter) + 1
            setattr(self, counter, value)
            return value

    def next_capture(self) -> int:
        """The next capture number, taken once: a tool naming several files after one capture takes it first."""
        return self._next("capture_counter")

    def write(self, path: str, data: str | bytes) -> None:
        """Write a file under the output folder, making its folder. SDK v2 shows the model only the tool's name for an
        exception that isn't a ToolError, so a folder that can't be written says which path, and why."""
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            if isinstance(data, bytes):
                with open(path, "wb") as f:
                    f.write(data)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(data)
        except OSError as e:
            raise ToolError(f"Could not write {self.rel(path)}: {e}") from e

    def save_png(self, image_base64: str, prefix: str = "capture", number: int | None = None) -> str:
        """Decode base64 PNG and save to mcp_output/captures/, named with number or the next capture number. Returns
        the relative path; ToolError on bad data or a folder that can't be written."""
        try:
            data = base64.b64decode(image_base64)
        except (binascii.Error, ValueError) as e:
            raise ToolError(f"Failed to decode image data: {e}") from e
        n = self.next_capture() if number is None else number
        filepath = os.path.join(self.output_dir, "captures", f"{prefix}_{n:04d}.png")
        self.write(filepath, data)
        return self.rel(filepath)

    def text_response(self, text: str, label: str = "output") -> str:
        """Return text inline if short, or write to file and return path."""
        if len(text) <= FILE_THRESHOLD:
            return text
        filepath = os.path.join(self.output_dir, "responses", f"{label}_{self._next('response_counter'):04d}.txt")
        self.write(filepath, text)
        line_count = text.count("\n") + 1
        return f"Wrote {label} ({len(text):,} chars, {line_count} lines) -> {self.rel(filepath)}"


def create_server(host: str, port: int, output_dir: str, client: BridgeClient | None = None) -> MCPServer:
    """The MCP server, its tools and resources, talking to the bridge at host:port; client stands in for tests."""
    bridge = client or BridgeClient(host=host, port=port)
    mcp = MCPServer("omniverse", instructions=INSTRUCTIONS, version=version("omniverse-mcp"))
    register_all(mcp, bridge, Helpers(output_dir))

    def _resource(fn: Callable[..., dict[str, Any]], *args: Any, **kwargs: Any) -> dict[str, Any]:
        # The tools' own call, its ToolError re-raised as what a resource raises.
        try:
            return bridge_call(fn, *args, **kwargs)["result"]
        except ToolError as e:
            raise ResourceError(str(e)) from e

    @mcp.resource("omniverse://scene/tree")
    def scene_tree_resource() -> str:
        """Current scene hierarchy."""
        return _resource(bridge.scene_tree, "/", 5, fmt="text")["text"]

    @mcp.resource("omniverse://sim/state")
    def sim_state_resource() -> str:
        """Current simulation state."""
        return json.dumps(_resource(bridge.sim_state), indent=2)

    return mcp


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    # Output dir defaults to ./mcp_output relative to CWD
    output_dir = args.output_dir or os.path.join(os.getcwd(), "mcp_output")
    # The extension writes some files there itself (dump_scene), and doesn't make the folder.
    os.makedirs(output_dir, exist_ok=True)
    create_server(args.host, args.port, output_dir).run()


if __name__ == "__main__":
    main()
