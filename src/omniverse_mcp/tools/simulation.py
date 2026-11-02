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


def _collision_dropped(extension: str | None, material: bool) -> str:
    """The warning for a collision an extension without #150 dropped: it answers success, having read no such key."""
    text = (
        f"WARNING: collision not set: the Kit extension is {extension or 'unknown'}, this server's is "
        f"{carried_version()}, and it doesn't know collision. Install this server's, {install_advice()}."
    )
    if material:
        text += " Its friction or restitution did apply the Collision API, so the prim collides."
    return text


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
    if r.get("collision") is not None:
        if r["collision"]:
            values.append("collision=on")
        else:
            values.append("collision=off (it had no collider)" if r.get("collider") is False else "collision=off")
    return values


def _also_changes(shared: dict[str, Any]) -> str:
    """The other prims a write into the prim's material reached, such as clones that inherit it: the extension sends
    the first few and the count."""
    count = int(shared["count"])
    prims = [str(p) for p in shared.get("prims", [])]
    named = ", ".join(prims) + (f" and {count - len(prims)} more" if count > len(prims) else "")
    return f"also changes {count} prim{'' if count == 1 else 's'}: {named}"


def _old_material(old: dict[str, Any]) -> str:
    """The older extension's shared material the call moved the prim off: deleted, with its folder once empty, or kept
    and why."""
    path = old["path"]
    if "deleted" not in old:
        return f"kept its old material, {path}: {old.get('kept', '')}"
    text = f"deleted its old material, {path}, which no prim binds now"
    folders = [p for p in old["deleted"] if p != path]
    return text + (f", and {', '.join(folders)}, left empty" if folders else "")


def _kit_app(r: dict[str, Any]) -> str:
    """The Kit app's name and version in one, as a bug form's "Kit app and version" asks: `Isaac-Sim Python 6.2.0`."""
    parts = [str(r[key]) for key in ("kit_app_name", "kit_app_version") if r.get(key) and r[key] != "unknown"]
    return " ".join(parts) or "unknown"


GIB = 1 << 30


def _missing(numbers: dict[str, Any]) -> str | None:
    """Why the extension gave no numbers for a line, or None when it gave them."""
    return str(numbers["missing"]) if "missing" in numbers else None


def _app_line(r: dict[str, Any]) -> str:
    app = r.get("app")
    if not app:
        return f"app = not measured: {r.get('app_missing') or 'no frame was timed'}"
    measured, asked = int(r.get("measured_frames", 0)), int(r.get("frames", 0))
    over = f"{measured} frames" if measured >= asked else f"{measured} of {asked} frames"
    return (
        f"app = {app['fps']:.1f} FPS (frame time mean {app['mean_ms']:.1f} ms, p50 {app['p50_ms']:.1f}, "
        f"p95 {app['p95_ms']:.1f}, worst {app['worst_ms']:.1f}) over {over} after {r.get('warmup', 0)}"
    )


def _physics_line(p: dict[str, Any]) -> str:
    text = (
        f"physics = {p['steps_per_second']:g} steps a simulated second, {p['steps_per_frame']:.1f} steps a frame, "
        f"{p['step_ms']:.1f} ms a step ({p['frame_ms']:.1f} ms a frame); simulated {p['simulated_seconds']:.2f} s in "
        f"{p['wall_seconds']:.2f} s"
    )
    return text + (f" ({p['ratio']:.2f} of real time)" if p.get("ratio") is not None else "")


def _memory_line(m: dict[str, Any]) -> str:
    """Hydra's use of device 0, and its total: the device's dedicated video memory, or Hydra's budget where it gives
    no such figure, each said by name."""
    used, total = m.get("used_bytes"), m.get("total_bytes")
    if used is None:
        return f"gpu_memory = not given by Hydra for {m.get('device', 'device 0')}"
    of = ""
    if total is not None:
        dedicated = m.get("total_kind") == "dedicated"
        of = (
            f" of {total / GIB:.1f} GiB of dedicated video memory"
            if dedicated
            else f" of a {total / GIB:.1f} GiB budget"
        )
    return f"gpu_memory = {used / GIB:.1f} GiB used{of} (Hydra's figures for device 0, {m.get('device', 'unknown')})"


def _stage_line(s: dict[str, Any]) -> str:
    text = f"stage = {s.get('prims', 0)} prims, {s.get('meshes', 0)} meshes"
    if s.get("instances"):
        text += f", {s['instances']} instances of {s.get('prototypes', 0)} prototypes"
    if s.get("point_instancers"):
        text += f", {s.get('point_instances', 0)} point instances in {s['point_instancers']} point instancers"
    return text


def _products_line(products: list[dict[str, Any]]) -> str:
    """The render products by kind and size, in the order each first comes: each renders every update."""
    if not products:
        return "render_products = none"
    groups: dict[tuple[str, str], int] = {}
    for product in products:
        size = "x".join(str(side) for side in product.get("resolution") or ["?", "?"])
        key = (str(product.get("kind", "render product")), size)
        groups[key] = groups.get(key, 0) + 1
    named = [f"{count} {kind}{'s' if count > 1 else ''} at {size}" for (kind, size), count in groups.items()]
    return f"render_products = {len(products)}: {', '.join(named)}"


def _on_off(value: Any) -> str:
    return "on" if value else "off"


def _conditions_line(c: dict[str, Any]) -> str:
    """What two answers are compared by: the machine, the app, the renderer and the timeline; the limiter; and what
    Isaac Sim's throttling turns on and off around play and stop."""
    machine: list[str] = [str(c["gpu"])] if c.get("gpu") else []
    machine.append(f"{_kit_app(c)} (Kit {c.get('kit_version') or 'unknown'})")
    if c.get("renderer"):
        mode = f" ({c['render_mode']})" if c.get("render_mode") else ""
        machine.append(f"renderer {c['renderer']}{mode}")
    machine.append(str(c.get("timeline", "unknown")))
    if c.get("headless") is not None:
        machine.append("headless" if c["headless"] else "with a window")
    if c.get("fixed_time_stepping") is True:
        rate = c.get("time_codes_per_second")
        machine.append(f"fixed time steps of 1/{float(rate):g} s" if rate else "fixed time steps")
    elif c.get("fixed_time_stepping") is False:
        machine.append("time steps by the wall clock")
    # The extension lifts only a limiter that is on, and leaves one off or not set as it is.
    if c.get("rate_limit_lifted"):
        frequency = c.get("rate_limit_frequency")
        at = f" at {frequency:g} Hz" if isinstance(frequency, int | float) else ""
        limiter = f"rate limit lifted for the measurement (it was on{at})"
    elif c.get("rate_limit") is False:
        limiter = "rate limit off"
    elif c.get("rate_limit") is None:
        limiter = "rate limit not set, so left as it was"
    else:
        limiter = f"rate limit {c['rate_limit']!r}, left as it was"
    throttling = [
        f"async rendering {_on_off(c.get('async_rendering'))}",
        f"eco mode {_on_off(c.get('eco_mode'))}",
    ]
    for key, name in (("sleep_ms_on_focus", "sleepMsOnFocus"), ("sleep_ms_out_of_focus", "sleepMsOutOfFocus")):
        if c.get(key):
            throttling.append(f"{name} {c[key]} ms")
    return f"conditions = {', '.join(machine)}; {limiter}; {', '.join(throttling)}"


def _performance_text(r: dict[str, Any]) -> str:
    """get_performance's answer, the number a target reads first, then a line for each other, then the conditions and
    the notes; a number Kit couldn't give says so on its own line."""
    lines = [_app_line(r)]
    halves = r.get("halves")
    if halves:
        lines.append(f"settled = first half {halves['first_ms']:.1f} ms, second half {halves['second_ms']:.1f} ms")
    gpu = r.get("gpu_render") or {"missing": "not measured"}
    lines.append(
        f"gpu_render = {_missing(gpu)}"
        if _missing(gpu)
        else f"gpu_render = mean {gpu['mean_ms']:.1f} ms, p95 {gpu['p95_ms']:.1f}"
    )
    physics = r.get("physics") or {"missing": "not measured"}
    lines.append(f"physics = {_missing(physics)}" if _missing(physics) else _physics_line(physics))
    memory = r.get("gpu_memory") or {"missing": "not measured"}
    lines.append(f"gpu_memory = {_missing(memory)}" if _missing(memory) else _memory_line(memory))
    lines.append(_stage_line(r.get("stage") or {}))
    lines.append(_products_line(r.get("render_products") or []))
    lines.append(_conditions_line(r.get("conditions") or {}))
    notes: list[str] = r.get("notes") or []
    lines.extend(f"note = {note}" for note in notes)
    return "\n".join(lines)


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

        fps is the timeline's time codes per second, not a render rate: get_performance measures the frame rate. When
        the two versions differ, the answer names the command that installs the matching extension; while a recording
        runs whose frames stopped early, it says why. sim_control changes the state.
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

    @tool(mcp, READS)
    def get_performance(
        frames: Annotated[
            int, Field(ge=2, le=2000, description="App updates to time, after the warm-up: 120 take 8 s at 15 FPS")
        ] = 120,
        warmup: Annotated[
            int,
            Field(
                ge=0,
                le=600,
                description="App updates to let pass first, once the stage has loaded, so shaders and caches settle",
            ),
        ] = 30,
    ) -> str:
        """Measure how fast the Kit app runs the open stage: the app loop's frames per second and frame time (mean,
        p50, p95, worst) over `frames` app updates after `warmup`; the GPU's render time a frame; while the simulation
        plays, the physics steps a frame, their time and the simulated-to-real ratio; GPU memory; the stage's prim,
        mesh and instance counts; the render products (cameras, lidars) rendering every update; and the conditions to
        compare two answers by: the GPU, the Kit app, the renderer, the timeline, headless or not, the frame-rate
        limiter, async rendering and eco mode.

        Use it to check a frame-rate target, such as 15 FPS with a robot's sensors on, and to see what each cut of the
        scene gains. Play the simulation first, with the sensors on, so physics and rendering run as they will; a
        stopped timeline gives no physics numbers. Measure alone: a capture called meanwhile waits for the measurement,
        and any other call's work counts in its frames. It waits for the stage to finish loading, and stops at 90 s,
        answering what it measured.

        While it measures, Kit's frame-rate limiter is lifted and put back after, so a playing stage with fixed time
        steps runs faster than real time for those seconds, and a robot driven from outside falls behind meanwhile.
        The render a capture keeps for the next one is released first, so the next capture sets up its view again.
        The answer notes when the run's two halves differ by more than 10% (measure again), when eco mode on a still
        timeline makes the stage read faster than it plays, and when a recording's camera counts in the numbers. The
        numbers are this machine's and GPU's: measure where the target must be met."""
        resp = bridge_call(client.performance, frames, warmup)
        return _performance_text(resp["result"])

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
        collision: Annotated[
            bool | None,
            Field(
                description="true makes the prim a collider (the Collision API), with no rigid body, such as a floor; "
                "false turns its collision off and keeps the API"
            ),
        ] = None,
    ) -> str:
        """Set a prim's mass or density, friction or restitution, or make it a collider or turn its collision off, for
        PhysX; a value left out stays as it is.

        collision=true makes a static collider, such as a floor something should land on, with no rigid body and no
        physics material: only a Cube, Sphere, Capsule, Cylinder, Cone, Mesh or Plane collides, so an Xform is refused,
        its error naming the shapes under it. A Mesh that moves with a rigid body, its own or an ancestor's, not
        kinematic, gets a convexHull approximation unless one is set, as PhysX can't simulate a triangle mesh there.
        collision=false turns physics:collisionEnabled off and keeps the API. Mass or density goes through MassAPI and
        makes the prim a rigid body (RigidBodyAPI) if it isn't one, so a static collider starts to fall when the
        simulation plays. Friction or restitution adds the Collision API if missing, and sets them on the prim's own
        physics material, a child named PhysMat (/World/Cube/PhysMat for /World/Cube), bound to the prim for physics
        only; delete_prim removes it with the prim. That material starts from the body's own: the physics material
        bound to it before, else the physics scene's default, else PhysX's (friction 0.5, restitution 0), so the one
        left out, and anything else the replaced material held, stays. A copy made with clone_prim takes its own with
        it. A clone that inherits from its source, as Isaac Sim's cloner makes them, follows the source's material
        until a call on the clone, and the answer names the prims a call changes so. An instance or an inactive prim
        can hold no material of its own, so friction or restitution on one is refused, as collision is on an inactive
        prim or one inside an instance. A prim on an older extension's shared /World/PhysicsMaterials/<prim
        name>_PhysMat moves to its own, and the call that moves the last prim off it deletes it. A call with friction
        or restitution reads the whole stage, about 1 s per 100,000 prims. The answer gives each value set, collision
        on or off, the material and the APIs applied, the rigid body a collider moves with, and whether the older
        shared material was deleted or kept, and why. For the prim's look, use set_material; to make a new prim
        physical in one call, create_prim with enable_physics.
        """
        resp = bridge_call(client.set_physics_properties, prim_path, mass, density, friction, restitution, collision)
        r = resp["result"]
        values = _physics_values(r)
        # An extension without #150 drops collision unread and answers success.
        dropped = collision is not None and "collision" not in r
        if not values and not dropped:
            return f"Nothing set on {r['prim_path']}: give mass, density, friction, restitution or collision"
        text = f"Physics on {r['prim_path']}: {', '.join(values) or 'nothing set'}"
        # An extension of 0.3.0 or older sends no material, nor the two clauses after the APIs.
        if r.get("material"):
            text += f"; material {r['material']}"
        # The extension names RigidBodyAPI and CollisionAPI only when it added them: the prim became a body or a
        # collider in this call.
        if r.get("applied"):
            text += f"; applied {', '.join(r['applied'])}"
        if r.get("also_changes"):
            text += f"; {_also_changes(r['also_changes'])}"
        if r.get("approximation"):
            text += f"; approximation {r['approximation']}"
        if r.get("body"):
            text += f"; part of the rigid body {r['body']}"
        if r.get("old_material"):
            text += f"; {_old_material(r['old_material'])}"
        if dropped:
            material = friction is not None or restitution is not None
            text += "\n" + _collision_dropped(client.extension_version, material)
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
        measures a prim you already know. Only colliders (the Collision API, which set_physics_properties'
        collision=True or create_prim's enable_physics adds) are hit, not plain meshes. PhysX needs to know the scene:
        play or step the simulation once first, or it may find nothing, or fail. The prim named is the rigid body hit,
        or a static collider itself.
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
