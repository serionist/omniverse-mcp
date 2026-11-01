"""Simulation and physics tools."""

import math
from importlib.metadata import version
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import carried_version, install_advice

from ._annotations import EDITS, READS, tool
from ._bridge import bridge_call
from ._params import PrimPath

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def _rounded(values: list[float]) -> list[float]:
    """A vector as the model reads it: a centre of mass from PhysX carries float32 noise past the fourth place."""
    return [round(v, 4) for v in values]


def _physics_values(r: dict[str, Any]) -> list[str]:
    """Each value set_physics_properties wrote, as the extension echoes it, so the model can confirm the call without
    reading the prim again; one left out comes back null and stays as it was."""
    values: list[str] = []
    if r.get("mass") is not None:
        mass = float(r["mass"])
        values.append(f"mass={mass}" + (" (unset, so density decides)" if mass == 0 else ""))
    if r.get("density") is not None:
        density = float(r["density"])
        values.append(f"density={density}" + (" (unset)" if density == 0 else ""))
    if r.get("friction") is not None:
        values.append(f"friction={float(r['friction'])} (static and dynamic)")
    if r.get("restitution") is not None:
        values.append(f"restitution={float(r['restitution'])}")
    return values


def _kit_app(r: dict[str, Any]) -> str:
    """The Kit app's name and version in one, as a bug form's "Kit app and version" asks: `Isaac-Sim Python 6.2.0`."""
    parts = [str(r[key]) for key in ("kit_app_name", "kit_app_version") if r.get(key) and r[key] != "unknown"]
    return " ".join(parts) or "unknown"


def _unit(direction: list[float]) -> list[float]:
    """direction scaled to length 1, as raycast_closest's unit_dir asks. Isaac Sim 6.2's PhysX scales it itself;
    other builds are untried, and a zero one has no direction to cast along."""
    if len(direction) != 3:
        raise ToolError(f"direction must be [dx, dy, dz], got {direction}")
    if not all(math.isfinite(d) for d in direction):
        raise ToolError(f"direction must be 3 finite numbers, got {direction}")
    # hypot scales as it goes: squaring first underflows a tiny direction to zero and overflows a huge one.
    length = math.hypot(*direction)
    if not math.isfinite(length):
        raise ToolError(f"direction {direction} is too long to take the length of: give a shorter one")
    if length == 0:
        raise ToolError("direction is [0, 0, 0]: give the way the ray goes, of any length but zero")
    return [float(d) / length for d in direction]


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, EDITS)
    def sim_control(
        action: Annotated[Literal["play", "pause", "stop", "step"], Field(description="What to do")],
    ) -> str:
        """Play, pause, stop or step the simulation's timeline, and return the state it is left in.

        play starts or resumes physics; pause holds it where it is; stop rewinds the timeline, and physics puts bodies
        back where play found them; step plays for two app updates, then pauses. A robot's first play cooks its
        collision meshes, and Kit answers nothing until that ends. get_sim_state reads the state without changing it;
        get_robot_info's joint states and apply_force need it playing or paused.
        """
        resp = bridge_call(client.sim_control, action)
        r = resp["result"]
        return f"'{r['action']}' executed. Sim is now: {r['current_state']}"

    @tool(mcp, READS)
    def get_sim_state() -> str:
        """Get the simulation's state and the stage's frame of reference: playing, paused or stopped, the timeline's
        time, the up axis, meters_per_unit, the prim count; the Kit app, its version, Kit's version and the OS Kit
        runs on; and the versions of the Kit extension and this server.

        fps is the timeline's time codes per second, not a render rate. When the two versions differ, the answer names
        the command that installs the matching extension; while a recording runs whose frames stopped early, it says
        why. sim_control changes the state.
        """
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
            # The Kit app, for a bug report (#105): an extension from before it sends none, which reads unknown.
            f"kit_app = {_kit_app(r)}",
            f"kit_version = {r.get('kit_version') or 'unknown'}",
            f"kit_os = {r.get('kit_os') or 'unknown'}",
            f"extension_version = {extension}",
            f"server_version = {server}",
        ]
        if r.get("recording_note"):
            lines.append(f"recording_note = {r['recording_note']}")
        if extension != carried:
            lines.append(
                f"note = the Kit extension is {extension} and this server's is {carried}: install the server's, "
                f"{install_advice()}"
            )
        return "\n".join(lines)

    @tool(mcp, EDITS)
    def set_physics_properties(
        prim_path: PrimPath,
        mass: Annotated[
            float | None, Field(ge=0, description="Mass in kg (applies MassAPI); 0 unsets it, so density decides")
        ] = None,
        density: Annotated[
            float | None,
            Field(ge=0, description="Density in kg/m^3 (applies MassAPI); 0 unsets it; a mass set wins over it"),
        ] = None,
        friction: Annotated[
            float | None, Field(ge=0, description="Friction coefficient, set as both static and dynamic friction")
        ] = None,
        restitution: Annotated[
            float | None, Field(ge=0, le=1, description="Bounciness: 0 no bounce, 1 full bounce")
        ] = None,
    ) -> str:
        """Set a prim's mass or density, and its friction or restitution, for PhysX; a value left out stays as it is.

        Mass or density goes through MassAPI and makes the prim a rigid body (RigidBodyAPI) if it isn't one, so a
        static collider starts to fall when the simulation plays. Friction or restitution adds the Collision API if
        missing, and sets them on a physics material, /World/PhysicsMaterials/<prim name>_PhysMat, bound to the prim
        for physics only. That material starts from the body's own: the physics material bound to it before, else the
        physics scene's default, else PhysX's (friction 0.5, restitution 0), so the one left out, and anything else the
        replaced material held, stays. Prims of the same name share it, so setting one sets all its values on the
        rest. The answer gives each value set and the APIs applied. For the prim's look, use set_material; to make a
        new prim physical in one call, create_prim with enable_physics.
        """
        resp = bridge_call(client.set_physics_properties, prim_path, mass, density, friction, restitution)
        r = resp["result"]
        values = _physics_values(r)
        if not values:
            return f"Nothing set on {r['prim_path']}: give mass, density, friction or restitution"
        text = f"Physics on {r['prim_path']}: {', '.join(values)}"
        # The extension names RigidBodyAPI and CollisionAPI only when it added them: the prim became a body or a
        # collider in this call.
        if r.get("applied"):
            text += f"; applied {', '.join(r['applied'])}"
        return text

    @tool(mcp, EDITS)
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
        """Push a rigid body through PhysX with a force or an impulse, so its mass counts. The simulation must be
        playing or paused. A push on an articulation's link, such as a robot's, moves the robot through its joints: a
        floating robot touching nothing changes speed by the impulse over its whole mass; a fixed robot's link turns
        about its joints, and on the ground friction takes some of the push. The answer gives the point pushed at and
        the path the push took: method: physx, PhysX's own push, or method: tensor. With /physics/suppressReadback on,
        as Isaac Sim's GPU device sets it for PhysX's Direct GPU API, the push goes through PhysX's tensor API. Under
        that API a second push on a body before the next physics step replaces the first, so push once per body per
        step, combining pushes into one; pushes on different bodies each land. Refused for a prim without RigidBodyAPI,
        a disabled or kinematic body, and one a fixed joint holds to the world (a fixed robot's base). To place a body
        rather than push it, use set_prim_transform."""
        resp = bridge_call(client.apply_force, prim_path, force, position, impulse)
        r = resp["result"]
        mode = "impulse" if r.get("impulse") else "force"
        text = f"Applied {mode} {_rounded(r['force'])} to {r['prim_path']}"
        details: list[str] = []
        # A 0.2.0 extension answers no `at`, and its `method` says whether PhysX or a velocity nudge did it.
        if r.get("at") and r.get("position") is not None:
            text += f" at {_rounded(r['position'])}"
            details.append(r["at"])
        # physx or tensor: under the tensor API a second push on the body before the next step replaces this one.
        details.append(f"method: {r.get('method', 'unknown')}")
        return f"{text} ({', '.join(details)})"

    @tool(mcp, READS)
    def raycast(
        origin: Annotated[list[float], Field(description="[x, y, z] start point in world space")],
        direction: Annotated[
            list[float],
            Field(description="[dx, dy, dz] direction in world space, of any length but zero"),
        ],
        max_distance: Annotated[float, Field(gt=0, description="The longest the ray goes, in stage units")] = 1000.0,
    ) -> str:
        """Cast a ray through PhysX and return the closest collider it hits: its prim, the hit point, the surface
        normal and the distance in stage units, or "No hit".

        Use it to find what lies along a line, such as the ground under a point or what a robot faces; get_prim_bounds
        measures a prim you already know. Only colliders (the Collision API, which create_prim's enable_physics adds)
        are hit, not plain meshes. PhysX needs to know the scene: play or step the simulation once first, or it may
        find nothing, or fail. The prim named is the rigid body hit, or a static collider itself.
        """
        resp = bridge_call(client.raycast, origin, _unit(direction), max_distance)
        r = resp["result"]
        if not r["hit"]:
            return "No hit"
        lines = [
            f"Hit: {r.get('prim_path', 'unknown')}",
            f"Position: {r['position'][0]:.4f}, {r['position'][1]:.4f}, {r['position'][2]:.4f}",
            f"Normal: {r['normal'][0]:.4f}, {r['normal'][1]:.4f}, {r['normal'][2]:.4f}",
            f"Distance: {r['distance']:.4f} stage units",
        ]
        return "\n".join(lines)

    @tool(mcp, EDITS)
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

        Use it to mark points, rays or paths, such as a raycast's hit, for a capture or the user to see: on Isaac Sim
        6.x the lines show in capture_viewport's image. Nothing is added to the stage. In Isaac Sim, when a drawing
        expires, lines other code drew with isaacsim.util.debug_draw go too. A new stage drops the old one's
        drawings."""
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
