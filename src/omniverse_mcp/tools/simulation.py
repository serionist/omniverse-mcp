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


def _rounded(values: list[float]) -> list[float]:
    """A vector as the model reads it: a centre of mass from PhysX carries float32 noise past the fourth place."""
    return [round(v, 4) for v in values]


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
        prim_path: Annotated[str, Field(description="The rigid body's prim path, a robot's link among them")],
        force: Annotated[
            list[float],
            Field(description="[fx, fy, fz]: an impulse in N s, or a force in N for one physics step"),
        ],
        position: Annotated[
            list[float] | None,
            Field(description="World-space point to push at; the body's centre of mass when omitted"),
        ] = None,
        impulse: Annotated[
            bool,
            Field(
                description="True for an impulse in N s, False for a force in N for one physics step. For a sustained "
                "push, give an impulse of force times seconds"
            ),
        ] = False,
    ) -> str:
        """Push a rigid body through PhysX, so its mass counts. The simulation must be playing or paused. A push on an
        articulation's link, such as a robot's, moves the robot through its joints: a floating robot touching nothing
        changes speed by the impulse over its whole mass; a fixed robot's link turns about its joints, and on the
        ground friction takes some of the push. Refused for a disabled or kinematic body, for one a fixed joint holds
        to the world (a fixed robot's base), and under PhysX's Direct GPU API (#68)."""
        resp = bridge_call(client.apply_force, prim_path, force, position, impulse)
        r = resp["result"]
        mode = "impulse" if r.get("impulse") else "force"
        text = f"Applied {mode} {_rounded(r['force'])} to {r['prim_path']}"
        # A 0.2.0 extension answers no `at`, and its `method` says whether PhysX or a velocity nudge did it.
        if r.get("at") and r.get("position") is not None:
            return f"{text} at {_rounded(r['position'])} ({r['at']})"
        return f"{text} (method: {r.get('method', 'unknown')})"

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
