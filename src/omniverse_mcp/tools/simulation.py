"""Simulation and physics tools."""

from typing import Annotated, Any, Literal

from pydantic import Field

from ._annotations import EDITS, READS
from ._bridge import bridge_call
from ._params import PrimPath


def register(mcp, client, h):
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
        """Get simulation state: playing/paused/stopped, time, FPS, prim count, up axis."""
        resp = bridge_call(client.sim_state)
        r = resp["result"]
        lines = [
            f"state = {r.get('state', 'unknown')}",
            f"up_axis = {r.get('up_axis', '?')}",
            f"time = {r.get('sim_time', 0):.3f}s",
            f"fps = {r.get('fps', 0):.1f}",
            f"prim_count = {r.get('prim_count', 0)}",
            f"meters_per_unit = {r.get('meters_per_unit', 1.0)}",
        ]
        return "\n".join(lines)

    @mcp.tool(annotations=EDITS)
    def set_physics_properties(
        prim_path: PrimPath,
        mass: Annotated[float | None, Field(gt=0, description="Mass in kg (applies MassAPI)")] = None,
        density: Annotated[float | None, Field(gt=0, description="Density in kg/m^3 (applies MassAPI)")] = None,
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
            list[float] | None, Field(description="World-space point to apply it at; the center of mass when omitted")
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
        direction: Annotated[list[float], Field(description="[dx, dy, dz] direction; it is normalized")],
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
        shape: Annotated[Literal["line", "sphere", "points"], Field(description="What to draw")],
        color: Annotated[list[float] | None, Field(description="[r, g, b] in 0-1; red when omitted")] = None,
        duration: Annotated[float, Field(gt=0, description="How long it shows, in seconds")] = 5.0,
        start: Annotated[list[float] | None, Field(description='For "line": its start [x, y, z]')] = None,
        end: Annotated[list[float] | None, Field(description='For "line": its end [x, y, z]')] = None,
        center: Annotated[list[float] | None, Field(description='For "sphere": its center [x, y, z]')] = None,
        radius: Annotated[float, Field(gt=0, description='For "sphere": its radius')] = 0.1,
        points: Annotated[list[list[float]] | None, Field(description='For "points": a list of [x, y, z]')] = None,
        size: Annotated[float, Field(gt=0, description='For "points": the point size')] = 5.0,
    ) -> str:
        """Draw debug visualization in the viewport (lines, spheres, points)."""
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
        if size != 5.0:
            kwargs["size"] = size

        resp = bridge_call(client.draw_debug, shape, **kwargs)
        r = resp["result"]
        drawn = r.get("drawn", [])
        labels = [d.get("type", str(d)) if isinstance(d, dict) else str(d) for d in drawn]
        return f"Drew {len(drawn)} debug element(s): {', '.join(labels)}"
