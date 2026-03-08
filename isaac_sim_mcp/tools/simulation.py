"""Simulation and physics tools."""

from typing import Any


def register(mcp, client, h):
    def _call(fn, *args, **kwargs):
        """Call client method with connection error handling."""
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "error": f"Isaac Sim connection failed: {e}"}
        return resp

    def _check_error(resp):
        """Check response for errors, including traceback."""
        if resp["status"] == "error":
            msg = f"ERROR: {resp['error']}"
            tb = resp.get("traceback", "")
            if tb:
                # Include first 5 lines of traceback for diagnosis
                tb_lines = tb.strip().split("\n")
                msg += "\n" + "\n".join(tb_lines[-5:])
            return msg
        return None

    @mcp.tool()
    def sim_control(action: str) -> str:
        """Control simulation: play, pause, stop, or step.

        Args:
            action: "play" | "pause" | "stop" | "step"
        """
        resp = _call(client.sim_control, action)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"'{r['action']}' executed. Sim is now: {r['current_state']}"

    @mcp.tool()
    def get_sim_state() -> str:
        """Get simulation state: playing/paused/stopped, time, FPS, prim count, up axis."""
        resp = _call(client.sim_state)
        err = _check_error(resp)
        if err:
            return err
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

    @mcp.tool()
    def set_physics_properties(
        prim_path: str,
        mass: float | None = None,
        density: float | None = None,
        friction: float | None = None,
        restitution: float | None = None,
    ) -> str:
        """Set physics material properties on a prim.

        Args:
            prim_path: Target prim
            mass: Mass in kg (applies MassAPI)
            density: Density in kg/m^3 (applies MassAPI)
            friction: Static/dynamic friction coefficient (0-1)
            restitution: Bounciness (0=no bounce, 1=full bounce)
        """
        resp = _call(client.set_physics_properties, prim_path, mass, density, friction, restitution)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"Physics on {r['prim_path']}: {', '.join(r['applied'])}"

    @mcp.tool()
    def apply_force(
        prim_path: str,
        force: list[float],
        position: list[float] | None = None,
        impulse: bool = False,
    ) -> str:
        """Apply a force or impulse to a rigid body. Sim must be playing.

        Args:
            prim_path: Rigid body prim
            force: [fx, fy, fz] in Newtons (force) or N*s (impulse)
            position: World-space application point (default: center of mass)
            impulse: True for impulse (instantaneous), False for force (continuous)
        """
        resp = _call(client.apply_force, prim_path, force, position, impulse)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        mode = "impulse" if r.get("impulse") else "force"
        return f"Applied {mode} {r['force']} to {r['prim_path']} (method: {r['method']})"

    @mcp.tool()
    def raycast(
        origin: list[float],
        direction: list[float],
        max_distance: float = 1000.0,
    ) -> str:
        """Cast a ray into the scene and return what it hits. Useful for spatial queries.

        Args:
            origin: [x, y, z] start point
            direction: [dx, dy, dz] ray direction (will be normalized)
            max_distance: Maximum ray length (default 1000m)
        """
        resp = _call(client.raycast, origin, direction, max_distance)
        err = _check_error(resp)
        if err:
            return err
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

    @mcp.tool()
    def draw_debug(
        shape: str,
        color: list[float] | None = None,
        duration: float = 5.0,
        start: list[float] | None = None,
        end: list[float] | None = None,
        center: list[float] | None = None,
        radius: float = 0.1,
        points: list[list[float]] | None = None,
        size: float = 5.0,
    ) -> str:
        """Draw debug visualization in the viewport (lines, spheres, points).

        Args:
            shape: "line", "sphere", or "points"
            color: [r, g, b] in 0-1 range (default: red)
            duration: Display duration in seconds
            start: Line start [x,y,z] (for shape="line")
            end: Line end [x,y,z] (for shape="line")
            center: Sphere center [x,y,z] (for shape="sphere")
            radius: Sphere radius (for shape="sphere")
            points: List of [x,y,z] points (for shape="points")
            size: Point size (for shape="points")
        """
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

        resp = _call(client.draw_debug, shape, **kwargs)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        drawn = r.get("drawn", [])
        labels = [d.get("type", str(d)) if isinstance(d, dict) else str(d) for d in drawn]
        return f"Drew {len(drawn)} debug element(s): {', '.join(labels)}"
