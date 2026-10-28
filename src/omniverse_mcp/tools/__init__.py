"""
MCP tool modules.

Each module has a register(mcp, client, helpers) function that registers
its tools with the FastMCP server instance.
"""

from mcp.server.fastmcp import FastMCP

from ..client import IsaacSimClient
from . import camera, misc, recording, robot, scene, simulation, usd_advanced


def register_all(mcp: FastMCP, client: IsaacSimClient, helpers) -> None:
    """Register all tool modules with the MCP server."""
    scene.register(mcp, client, helpers)
    camera.register(mcp, client, helpers)
    robot.register(mcp, client, helpers)
    simulation.register(mcp, client, helpers)
    recording.register(mcp, client, helpers)
    usd_advanced.register(mcp, client, helpers)
    misc.register(mcp, client, helpers)
