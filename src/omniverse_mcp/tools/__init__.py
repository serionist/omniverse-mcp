"""
MCP tool modules.

Each module has a register(mcp, client, helpers) function that registers
its tools with the MCPServer instance.
"""

from typing import TYPE_CHECKING

from mcp.server.mcpserver import MCPServer

from ..client import BridgeClient
from . import camera, misc, recording, robot, scene, simulation, usd_advanced

if TYPE_CHECKING:
    from ..server import Helpers


def register_all(mcp: MCPServer, client: BridgeClient, helpers: "Helpers") -> None:
    """Register all tool modules with the MCP server."""
    scene.register(mcp, client, helpers)
    camera.register(mcp, client, helpers)
    robot.register(mcp, client, helpers)
    simulation.register(mcp, client, helpers)
    recording.register(mcp, client, helpers)
    usd_advanced.register(mcp, client, helpers)
    misc.register(mcp, client, helpers)
