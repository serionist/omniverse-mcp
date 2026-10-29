"""Simulation and physics tools."""

from importlib.metadata import version
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import carried_version, install_command

from ._annotations import EDITS, READS
from ._bridge import bridge_call
from ._params import PrimPath

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=EDITS)
    def sim_control(
        action: Annotated[Literal["play", "pause", "stop", "step"], Field(description="What to do")],
    ) -> str:
        """Control simulation: play, pause, stop, or step."""
        resp = bridge_call(client.sim_control, action)
        r = resp["result"]
        return f"'{r['action']}' executed. Sim is now: {r['current_state']}"

    @mcp.tool(annotations=READS)
    def get_sim_state() -> str:
        """Get simulation state: playing/paused/stopped, time, FPS, prim count, up axis, and the versions of the Kit
        extension and this server, with what to run when they differ."""
        resp = bridge_call(client.sim_state)
        r = resp["result"]
        server = version("omniverse-mcp")
        extension = client.extension_version or "unknown"
        carried = carried_version()
        lines = [
            f"state = {r.get('state', 'unknown')}",
            f"up_axis = {r.get('up_axis', '?')}",
            f"time = {r.get('sim_time', 0):.3f}s",
            f"fps = {r.get('fps', 0):.1f}",
            f"prim_count = {r.get('prim_count', 0)}",
            f"meters_per_unit = {r.get('meters_per_unit', 1.0)}",
            f"extension_version = {extension}",
            f"server_version = {server}",
        ]
        if extension != carried:
            lines.append(
                f"note = the Kit extension is {extension} and this server's is {carried}: install the server's, "
                f"{install_command()}, then restart Kit"
            )
        return "\n".join(lines)

    @mcp.tool(annotations=EDITS)
    def set_physics_properties(
        prim_path: PrimPath,
        mass: Annotated[
            float | None, Field(ge=0, description="Mass in kg (applies MassAPI); 0 unsets it, so density decides")
        ] = None,
        density: Annotated[
            float | None,
            Field(ge=0, description="Density in kg/m^3 (applies MassAPI); 0 unsets it; a mass set wins over it"),
        ] = None,
        friction: Annotated[float | None, Field(ge=0, description="Static and dynamic friction coefficient")] = None,
        restitution: Annotated[
            float | None, Field(ge=0, le=1, description="Bounciness: 0 no bounce, 1 full bounce")
        ] = None,
    ) -> str:
        """Set physics material properties on a prim."""
        resp = bridge_call(client.set_physics_properties, prim_path, mass, density, friction, restitution)
        r = resp["result"]
        return f"Physics on {r['prim_path']}: {', '.join(r['applied'])}"

    @mcp.tool(annotations=EDITS)
    def apply_force(
        prim_path: Annotated[str, Field(description="The rigid body's prim path")],
        force: Annotated[list[float], Field(description="[fx, fy, fz] in newtons, or N*s for an impulse")],
        position: Annotated[
            list[float] | None,
            Field(description="World-space point to apply it at; the world origin when omitted, for now (#25)"),
        ] = None,
        impulse: Annotated[
            bool, Field(description="True for an instant impulse, False for a continuous force")
        ] = False,
    ) -> str:
        """Apply a force or impulse to a rigid body. Sim must be playing."""
        resp = bridge_call(client.apply_force, prim_path, force, position, impulse)
        r = resp["result"]
        mode = "impulse" if r.get("impulse") else "force"
        return f"Applied {mode} {r['force']} to {r['prim_path']} (method: {r['method']})"

    @mcp.tool(annotations=READS)
    def raycast(
        origin: Annotated[list[float], Field(description="[x, y, z] start point")],
        direction: Annotated[list[float], Field(description="[dx, dy, dz] direction; it is normalised")],
        max_distance: Annotated[float, Field(gt=0, description="The longest the ray goes")] = 1000.0,
    ) -> str:
        """Cast a ray into the scene and return what it hits. Useful for spatial queries."""
        resp = bridge_call(client.raycast, origin, direction, max_distance)
        r = resp["result"]
        if not r["hit"]:
            return "No hit"
        lines = [
            f"Hit: {r.get('prim_path', 'unknown')}",
            f"Position: {r['position'][0]:.4f}, {r['position'][1]:.4f}, {r['position'][2]:.4f}",
            f"Normal: {r['normal'][0]:.4f}, {r['normal'][1]:.4f}, {r['normal'][2]:.4f}",
            f"Distance: {r['distance']:.4f}m",
        ]
        return "\n".join(lines)

    @mcp.tool(annotations=EDITS)
    def draw_debug(
        shape: Annotated[
            Literal["line", "lines", "sphere", "points"],
            Field(description='What to draw: "lines" joins the points in order'),
        ],
        color: Annotated[list[float] | None, Field(description="[r, g, b] colour in 0-1; red when omitted")] = None,
        duration: Annotated[
            float,
            Field(gt=0, description="How long it shows, in seconds from the call, whether the simulation plays or not"),
        ] = 5.0,
        start: Annotated[list[float] | None, Field(description='For "line": its start [x, y, z]')] = None,
        end: Annotated[list[float] | None, Field(description='For "line": its end [x, y, z]')] = None,
        center: Annotated[list[float] | None, Field(description='For "sphere": its centre [x, y, z]')] = None,
        radius: Annotated[float, Field(gt=0, description='For "sphere": its radius')] = 0.1,
        points: Annotated[
            list[list[float]] | None, Field(description='For "points" and "lines": a list of [x, y, z]')
        ] = None,
        size: Annotated[
            float, Field(gt=0, description='For "points": how far each point\'s cross reaches, in stage units')
        ] = 0.05,
    ) -> str:
        """Draw debug lines in the viewport, 2 pixels wide, for `duration` seconds: a line, a polyline, a sphere as
        three crossing lines, or a small cross per point.

        Isaac Sim draws with isaacsim.util.debug_draw, turned on at the first call. Its clear takes every line drawn
        with it, so when a drawing expires, lines other code drew with it go too. Other Kit apps draw with
        omni.debugdraw when they have it. A new stage drops the old one's drawings."""
        kwargs: dict[str, Any] = {"duration": duration}
        if color is not None:
            kwargs["color"] = color
        if start is not None:
            kwargs["start"] = start
        if end is not None:
            kwargs["end"] = end
        if center is not None:
            kwargs["center"] = center
        if radius != 0.1:
            kwargs["radius"] = radius
        if points is not None:
            kwargs["points"] = points
        if size != 0.05:
            kwargs["size"] = size

        resp = bridge_call(client.draw_debug, shape, **kwargs)
        r = resp["result"]
        drawn: list[dict[str, Any]] = r.get("drawn", [])
        labels = [str(d.get("type", d)) for d in drawn]
        text = f"Drew {len(drawn)} debug element(s): {', '.join(labels)}"
        # A 0.2.0 bridge answers neither: its drawing lasted a frame, so no duration is claimed for it.
        if r.get("duration") is not None:
            text += f", for {float(r['duration'])} s"
        if r.get("backend"):
            text += f" ({r['backend']})"
        return text
