"""
Isaac Sim MCP Server

Standalone MCP server that bridges AI assistants to a running Isaac Sim instance
via the isaacsim.mcp.bridge extension.

Design principles:
- Images are always saved as PNG files, returning paths (never base64 inline).
- Scene/prim data uses grep-friendly prim-block text format.
- Any response > FILE_THRESHOLD chars is written to a file, returning a relative path.
- Small responses are returned inline as text.

Usage:
    python -m isaac_sim_mcp
    python -m isaac_sim_mcp --isaac-host 127.0.0.1 --isaac-port 8211
"""

import argparse
import base64
import json
import logging
import os

from mcp.server.fastmcp import FastMCP

from .client import IsaacSimClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CLI args (parsed before FastMCP takes stdio)
# ---------------------------------------------------------------------------

_parser = argparse.ArgumentParser(description="Isaac Sim MCP Server", add_help=False)
_parser.add_argument("--isaac-host", default="127.0.0.1", help="Isaac Sim extension host")
_parser.add_argument("--isaac-port", type=int, default=8211, help="Isaac Sim extension port")
_parser.add_argument("--output-dir", default="", help="Directory for file-based outputs (scene dumps, recordings)")
_args, _remaining = _parser.parse_known_args()

# Output dir defaults to ./mcp_output relative to CWD
OUTPUT_DIR = _args.output_dir or os.path.join(os.getcwd(), "mcp_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Responses longer than this are written to files
FILE_THRESHOLD = 1000

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Isaac Sim",
    instructions=(
        "Connected to NVIDIA Isaac Sim 5.1. Controls USD scene, simulation, viewport, robots.\n"
        "Use Context7 MCP (library 'isaac-sim/isaacsim') before writing execute_script code.\n\n"
        "OUTPUT: Images saved as PNGs. Large text written to files. Paths are project-relative.\n"
        "Use Read tool to view images and large responses.\n\n"
        "Data uses prim-block format: [/prim/path] headers, key = value lines. Grep-friendly."
    ),
)

_client = IsaacSimClient(host=_args.isaac_host, port=_args.isaac_port)


# ---------------------------------------------------------------------------
# Helpers (passed to tool modules via Helpers object)
# ---------------------------------------------------------------------------

class _Helpers:
    """Shared helper methods passed to tool registration functions."""

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        self.capture_counter = 0
        self.response_counter = 0

    def rel(self, path: str) -> str:
        """Convert absolute path to project-relative using mcp_output/... shorthand."""
        try:
            return os.path.relpath(path, os.getcwd()).replace("\\", "/")
        except ValueError:
            return path

    def save_png(self, image_base64: str, prefix: str = "capture") -> str:
        """Decode base64 PNG and save to mcp_output/captures/. Returns relative path."""
        cap_dir = os.path.join(self.output_dir, "captures")
        os.makedirs(cap_dir, exist_ok=True)
        self.capture_counter += 1
        filename = f"{prefix}_{self.capture_counter:04d}.png"
        filepath = os.path.join(cap_dir, filename)
        try:
            data = base64.b64decode(image_base64)
        except Exception as e:
            return f"ERROR: Failed to decode image data: {e}"
        with open(filepath, "wb") as f:
            f.write(data)
        return self.rel(filepath)

    def text_response(self, text: str, label: str = "output") -> str:
        """Return text inline if short, or write to file and return path."""
        if len(text) <= FILE_THRESHOLD:
            return text
        out_dir = os.path.join(self.output_dir, "responses")
        os.makedirs(out_dir, exist_ok=True)
        self.response_counter += 1
        filename = f"{label}_{self.response_counter:04d}.txt"
        filepath = os.path.join(out_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(text)
        line_count = text.count("\n") + 1
        return f"Wrote {label} ({len(text):,} chars, {line_count} lines) -> {self.rel(filepath)}"


_helpers = _Helpers(OUTPUT_DIR)

# ---------------------------------------------------------------------------
# Register all tools from submodules
# ---------------------------------------------------------------------------

from .tools import register_all
register_all(mcp, _client, _helpers)


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("isaac://scene/tree")
def scene_tree_resource() -> str:
    """Current scene hierarchy."""
    try:
        resp = _client.scene_tree("/", 5, fmt="text")
        if resp["status"] == "error":
            return f"Error: {resp['error']}"
        return resp["result"]["text"]
    except Exception as e:
        return f"Error: Isaac Sim not reachable - {e}"


@mcp.resource("isaac://sim/state")
def sim_state_resource() -> str:
    """Current simulation state."""
    try:
        resp = _client.sim_state()
        if resp["status"] == "error":
            return f"Error: {resp['error']}"
        return json.dumps(resp["result"], indent=2)
    except Exception as e:
        return f"Error: Isaac Sim not reachable - {e}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
