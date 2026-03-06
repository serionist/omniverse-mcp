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
import os
import time

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent, ImageContent

from .client import IsaacSimClient

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
# Helpers
# ---------------------------------------------------------------------------

_capture_counter = 0


def _rel(path: str) -> str:
    """Convert absolute path to project-relative using mcp_output/... shorthand."""
    try:
        return os.path.relpath(path, os.getcwd()).replace("\\", "/")
    except ValueError:
        return path


def _save_png(image_base64: str, prefix: str = "capture") -> str:
    """Decode base64 PNG and save to mcp_output/captures/. Returns relative path."""
    global _capture_counter
    cap_dir = os.path.join(OUTPUT_DIR, "captures")
    os.makedirs(cap_dir, exist_ok=True)
    _capture_counter += 1
    filename = f"{prefix}_{_capture_counter:04d}.png"
    filepath = os.path.join(cap_dir, filename)
    with open(filepath, "wb") as f:
        f.write(base64.b64decode(image_base64))
    return _rel(filepath)


def _text_response(text: str, label: str = "output") -> str:
    """Return text inline if short, or write to file and return path."""
    if len(text) <= FILE_THRESHOLD:
        return text
    out_dir = os.path.join(OUTPUT_DIR, "responses")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{label}_{int(time.time())}.txt"
    filepath = os.path.join(out_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(text)
    line_count = text.count("\n") + 1
    return f"Wrote {label} ({len(text):,} chars, {line_count} lines) -> {_rel(filepath)}"


# ---------------------------------------------------------------------------
# Tool: execute_script
# ---------------------------------------------------------------------------

@mcp.tool()
def execute_script(code: str) -> str:
    """Execute Python inside the running Isaac Sim instance.

    The script has access to: omni, carb, Usd, UsdGeom, UsdLux, UsdPhysics, Sdf, Gf.
    Assign to 'result' to return data. stdout/stderr are captured.

    Use Context7 MCP (library: isaac-sim/isaacsim) to look up the correct API calls.
    """
    resp = _client.execute(code)
    if resp["status"] == "error":
        parts = [f"ERROR: {resp['error']}"]
        if resp.get("traceback"):
            parts.append(f"\nTraceback:\n{resp['traceback']}")
        if resp.get("stdout"):
            parts.append(f"\nStdout:\n{resp['stdout']}")
        if resp.get("stderr"):
            parts.append(f"\nStderr:\n{resp['stderr']}")
        return "\n".join(parts)

    r = resp["result"]
    parts = []
    if r.get("stdout"):
        parts.append(f"Stdout:\n{r['stdout']}")
    if r.get("stderr"):
        parts.append(f"Stderr:\n{r['stderr']}")
    if r.get("return_value") is not None:
        parts.append(f"Return value:\n{json.dumps(r['return_value'], indent=2)}")
    text = "\n".join(parts) or "Script executed successfully (no output)"
    return _text_response(text, "script")


# ---------------------------------------------------------------------------
# Tool: get_scene_tree
# ---------------------------------------------------------------------------

@mcp.tool()
def get_scene_tree(root: str = "/", max_depth: int = 5) -> str:
    """Get the USD scene hierarchy as grep-friendly prim-block text.

    Each prim shows: path, type, world position. For large scenes, use dump_scene
    which also includes properties and bounding boxes.

    Args:
        root: Starting prim path (default "/")
        max_depth: Traversal depth (default 5, max 15)
    """
    resp = _client.scene_tree(root, min(max_depth, 15), fmt="text")
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    text = r["text"]
    return _text_response(text, "scene_tree")


# ---------------------------------------------------------------------------
# Tool: dump_scene
# ---------------------------------------------------------------------------

@mcp.tool()
def dump_scene(
    root: str = "/",
    max_depth: int = 15,
    include_properties: bool = True,
    filter_types: list[str] | None = None,
    property_filter: list[str] | None = None,
) -> str:
    """Dump the full scene graph to a text file in prim-block format.

    Writes ALL prims with properties, bounding boxes, and transforms to a grep-friendly file.
    Returns the file path. Use your Read tool to examine specific parts.

    Args:
        root: Starting prim path
        max_depth: Max traversal depth (default 15)
        include_properties: Include all USD properties per prim
        filter_types: Only include prims of these types (e.g., ["Mesh", "Xform"])
        property_filter: Only include properties containing these substrings (e.g., ["joint", "pos"])
    """
    resp = _client.scene_dump(
        OUTPUT_DIR, root, max_depth, include_properties,
        filter_types or [], property_filter=property_filter,
    )
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Dumped {r['prim_count']} prims ({r['file_size_bytes']:,} bytes) -> {_rel(r['file_path'])}"


# ---------------------------------------------------------------------------
# Tool: get_prim_properties
# ---------------------------------------------------------------------------

@mcp.tool()
def get_prim_properties(prim_path: str) -> str:
    """Get all properties of a specific prim in prim-block text format.

    Returns grep-friendly text with type, position, bounding box, and all USD properties.

    Args:
        prim_path: Full USD path (e.g., "/World/Robot")
    """
    resp = _client.prim_properties(prim_path, fmt="text")
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    text = resp["result"]["text"]
    return _text_response(text, f"prim_{prim_path.replace('/', '_')}")


# ---------------------------------------------------------------------------
# Tool: get_prim_bounds
# ---------------------------------------------------------------------------

@mcp.tool()
def get_prim_bounds(prim_path: str) -> str:
    """Get the bounding box of a prim (center, dimensions, min/max corners, diagonal).

    Use this for spatial reasoning -- understanding sizes, overlap, distances.

    Args:
        prim_path: Full USD path
    """
    resp = _client.prim_bounds(prim_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return (
        f"[{r['prim_path']}]\n"
        f"center = {r['center'][0]:.4f}, {r['center'][1]:.4f}, {r['center'][2]:.4f}\n"
        f"dimensions = {r['dimensions'][0]:.4f}, {r['dimensions'][1]:.4f}, {r['dimensions'][2]:.4f}\n"
        f"min = {r['min'][0]:.4f}, {r['min'][1]:.4f}, {r['min'][2]:.4f}\n"
        f"max = {r['max'][0]:.4f}, {r['max'][1]:.4f}, {r['max'][2]:.4f}\n"
        f"diagonal = {r['diagonal']:.4f}"
    )


# ---------------------------------------------------------------------------
# Tool: set_prim_transform
# ---------------------------------------------------------------------------

@mcp.tool()
def set_prim_transform(
    prim_path: str,
    position: list[float] | None = None,
    rotation: list[float] | None = None,
    scale: list[float] | float | None = None,
) -> str:
    """Set position/rotation/scale of a prim.

    Args:
        prim_path: Full USD path
        position: [x, y, z] in meters
        rotation: Euler [rx, ry, rz] degrees or quaternion [w, x, y, z]
        scale: Uniform (float) or [sx, sy, sz]
    """
    resp = _client.set_transform(prim_path, position, rotation, scale)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    return f"Transform updated for {prim_path}"


# ---------------------------------------------------------------------------
# Tool: create_prim
# ---------------------------------------------------------------------------

@mcp.tool()
def create_prim(
    prim_path: str,
    prim_type: str = "Xform",
    usd_path: str | None = None,
    position: list[float] | None = None,
    rotation: list[float] | None = None,
    scale: list[float] | float | None = None,
    enable_physics: bool = False,
) -> str:
    """Create a new prim in the scene.

    Types: Cube, Sphere, Cylinder, Cone, Capsule, Xform, Camera, DistantLight, SphereLight, etc.
    Or load a USD file via usd_path.

    Args:
        prim_path: Where to create (e.g., "/World/MyCube")
        prim_type: USD type name
        usd_path: Optional USD file to load as reference
        position: Optional [x, y, z]
        rotation: Optional euler or quaternion
        scale: Optional scale
        enable_physics: Add RigidBody + Collision APIs
    """
    kwargs = {}
    if usd_path:
        kwargs["usd_path"] = usd_path
    if position is not None:
        kwargs["position"] = position
    if rotation is not None:
        kwargs["rotation"] = rotation
    if scale is not None:
        kwargs["scale"] = scale
    if enable_physics:
        kwargs["enable_physics"] = True

    resp = _client.create_prim(prim_path, prim_type, **kwargs)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Created {r['type']} at {r['prim_path']}"


# ---------------------------------------------------------------------------
# Tool: delete_prim
# ---------------------------------------------------------------------------

@mcp.tool()
def delete_prim(prim_path: str) -> str:
    """Delete a prim and all its children.

    Args:
        prim_path: Full USD path to delete
    """
    resp = _client.delete_prim(prim_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    return f"Deleted {prim_path}"


# ---------------------------------------------------------------------------
# Tool: set_material
# ---------------------------------------------------------------------------

@mcp.tool()
def set_material(
    prim_path: str,
    color: list[float],
    opacity: float = 1.0,
    roughness: float = 0.5,
    metallic: float = 0.0,
    material_path: str = "",
) -> str:
    """Apply a PBR material (OmniPBR) to a prim with color and surface properties.

    Creates a material automatically and binds it to the target prim.
    Color values can be 0-1 floats or 0-255 ints (auto-detected).

    Args:
        prim_path: Target prim to apply material to
        color: [r, g, b] diffuse color. Use 0-1 floats (e.g., [1,0,0] for red) or 0-255 ints
        opacity: 0.0 (transparent) to 1.0 (opaque), default 1.0
        roughness: 0.0 (glossy/mirror) to 1.0 (rough/matte), default 0.5
        metallic: 0.0 (plastic/dielectric) to 1.0 (metal), default 0.0
        material_path: Custom material prim path (auto-generated under /World/Looks/ if omitted)
    """
    resp = _client.set_material(prim_path, color, opacity, roughness, metallic, material_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Material {r['material_path']} -> {r['prim_path']} (color=[{r['color'][0]:.2f},{r['color'][1]:.2f},{r['color'][2]:.2f}], roughness={r['roughness']}, metallic={r['metallic']})"


# ---------------------------------------------------------------------------
# Tool: clone_prim
# ---------------------------------------------------------------------------

@mcp.tool()
def clone_prim(
    source_path: str,
    target_path: str,
    count: int = 1,
    offset: list[float] | None = None,
) -> str:
    """Deep-copy a prim (and all children) to a new path. Supports batch cloning.

    Args:
        source_path: Prim to clone (e.g., "/World/MyCube")
        target_path: Destination path (e.g., "/World/MyCube_Copy")
        count: Number of copies (default 1). Paths auto-suffixed: _01, _02, ...
        offset: [x, y, z] per-copy offset. Each clone shifts by this amount from the previous.
    """
    resp = _client.clone_prim(source_path, target_path, count, offset)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    clones = r["clones"]
    if len(clones) == 1:
        return f"Cloned {source_path} -> {clones[0]}"
    return f"Cloned {source_path} -> {len(clones)} copies:\n" + "\n".join(f"  {c}" for c in clones)


# ---------------------------------------------------------------------------
# Tool: set_visibility
# ---------------------------------------------------------------------------

@mcp.tool()
def set_visibility(prim_path: str, visible: bool = True) -> str:
    """Show or hide a prim (and its descendants).

    Args:
        prim_path: Target prim
        visible: True to show, False to hide
    """
    resp = _client.set_visibility(prim_path, visible)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    state = "visible" if r["visible"] else "hidden"
    return f"{r['prim_path']} is now {state}"


# ---------------------------------------------------------------------------
# Tool: save_scene
# ---------------------------------------------------------------------------

@mcp.tool()
def save_scene(file_path: str = "") -> str:
    """Save the current scene to a USD file.

    Args:
        file_path: Destination file path. If empty, saves to current file (overwrite).
    """
    resp = _client.save_scene(file_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Scene saved ({r['action']}) -> {r['file_path']}"


# ---------------------------------------------------------------------------
# Tool: new_scene
# ---------------------------------------------------------------------------

@mcp.tool()
def new_scene() -> str:
    """Create a fresh empty scene with a /World root prim and Y-up axis."""
    resp = _client.new_scene()
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    return "New scene created with /World root prim (Y-up)"


# ---------------------------------------------------------------------------
# Tool: create_robot
# ---------------------------------------------------------------------------

@mcp.tool()
def create_robot(
    robot_type: str,
    prim_path: str = "",
    position: list[float] | None = None,
    rotation: list[float] | None = None,
) -> str:
    """Spawn a robot from Isaac Sim's asset library.

    Available: franka, ur10, carter, jetbot, g1, go1, go2, h1, spot, anymal.
    Or provide a full USD path as robot_type.

    Args:
        robot_type: Robot name or USD path
        prim_path: Scene path (auto-generated if empty)
        position: [x, y, z] spawn position
        rotation: Euler or quaternion
    """
    resp = _client.create_robot(robot_type, prim_path, position, rotation)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    parts = [f"Robot '{r['robot_type']}' created at {r['prim_path']}"]
    parts.append(f"USD: {r['usd_path']}")
    if r.get("joints"):
        parts.append(f"Joints: {len(r['joints'])}")
        for j in r["joints"][:10]:
            parts.append(f"  {j['path']} ({j['type']})")
        if len(r["joints"]) > 10:
            parts.append(f"  ... and {len(r['joints']) - 10} more")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Tool: get_robot_info
# ---------------------------------------------------------------------------

@mcp.tool()
def get_robot_info(prim_path: str) -> str:
    """Get robot joint info: names, types, limits, DOF count. Pure USD, no sim needed.

    Args:
        prim_path: Root prim of the robot (e.g., "/World/G1")
    """
    resp = _client.get_robot_info(prim_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    lines = [
        f"Robot: {r['prim_path']}",
        f"Articulation: {r['is_articulation']}",
        f"DOF: {r['dof_count']}",
        f"Links: {r['link_count']}",
        f"Joints ({len(r['joints'])}):",
    ]
    for j in r["joints"]:
        limits = ""
        if j.get("lower") is not None and j.get("upper") is not None:
            limits = f" [{j['lower']:.1f}, {j['upper']:.1f}]"
        drive = ""
        if j.get("drive_type"):
            drive = f" drive={j['drive_type']}"
        lines.append(f"  {j['name']} ({j['type']}{limits}{drive})")
    text = "\n".join(lines)
    return _text_response(text, "robot_info")


# ---------------------------------------------------------------------------
# Tool: get_joint_states
# ---------------------------------------------------------------------------

@mcp.tool()
def get_joint_states(prim_path: str) -> str:
    """Get current joint positions and velocities. Requires sim to have been played at least once.

    Args:
        prim_path: Root prim of the robot
    """
    resp = _client.get_joint_states(prim_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    lines = [f"Joint states for {r['prim_path']} ({r['dof_count']} DOF):"]
    names = r.get("joint_names", [])
    positions = r.get("positions", [])
    velocities = r.get("velocities", [])
    for i in range(len(positions)):
        name = names[i] if i < len(names) else f"joint_{i}"
        pos = positions[i]
        vel = velocities[i] if i < len(velocities) else 0.0
        lines.append(f"  {name}: pos={pos:.4f} vel={vel:.4f}")
    text = "\n".join(lines)
    return _text_response(text, "joint_states")


# ---------------------------------------------------------------------------
# Tool: set_joint_targets
# ---------------------------------------------------------------------------

@mcp.tool()
def set_joint_targets(
    prim_path: str,
    targets: dict[str, float] | list[float] | None = None,
) -> str:
    """Set joint drive position targets. Works without articulation initialization.

    Args:
        prim_path: Root prim of the robot
        targets: Joint targets as {joint_name: value} dict or [v0, v1, ...] list.
                 Values in degrees for revolute, meters for prismatic joints.
    """
    resp = _client.set_joint_targets(prim_path, targets)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    lines = [f"Set {r['targets_set']} joint targets on {r['prim_path']}"]
    if r.get("failed"):
        lines.append(f"Failed: {r['failed']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: set_physics_properties
# ---------------------------------------------------------------------------

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
    resp = _client.set_physics_properties(prim_path, mass, density, friction, restitution)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"Physics on {r['prim_path']}: {', '.join(r['applied'])}"


# ---------------------------------------------------------------------------
# Tool: apply_force
# ---------------------------------------------------------------------------

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
    resp = _client.apply_force(prim_path, force, position, impulse)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    mode = "impulse" if r.get("impulse") else "force"
    return f"Applied {mode} {r['force']} to {r['prim_path']} (method: {r['method']})"


# ---------------------------------------------------------------------------
# Tool: raycast
# ---------------------------------------------------------------------------

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
    resp = _client.raycast(origin, direction, max_distance)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
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


# ---------------------------------------------------------------------------
# Tool: draw_debug
# ---------------------------------------------------------------------------

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

    resp = _client.draw_debug(shape, **kwargs)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    drawn = r.get("drawn", [])
    labels = [d.get("type", str(d)) if isinstance(d, dict) else str(d) for d in drawn]
    return f"Drew {len(drawn)} debug element(s): {', '.join(labels)}"


# ---------------------------------------------------------------------------
# Tool: sim_control
# ---------------------------------------------------------------------------

@mcp.tool()
def sim_control(action: str) -> str:
    """Control simulation: play, pause, stop, or step.

    Args:
        action: "play" | "pause" | "stop" | "step"
    """
    resp = _client.sim_control(action)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return f"'{r['action']}' executed. Sim is now: {r['current_state']}"


# ---------------------------------------------------------------------------
# Tool: get_sim_state
# ---------------------------------------------------------------------------

@mcp.tool()
def get_sim_state() -> str:
    """Get simulation state: playing/paused/stopped, time, FPS, prim count, up axis."""
    resp = _client.sim_state()
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
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


# ---------------------------------------------------------------------------
# Tool: capture_viewport
# ---------------------------------------------------------------------------

@mcp.tool()
def capture_viewport(
    width: int = 1280,
    height: int = 720,
    camera_path: str = "",
) -> str:
    """Capture the viewport and save 3 files for scene understanding:

    1. **Viewport image** (PNG) -- what the camera sees
    2. **Bounding boxes** (TXT) -- screen-space bounding boxes mapping each visible prim to pixel coordinates
    3. **Instance segmentation** (PNG) -- each prim rendered as a unique color, with a legend mapping colors to prim paths

    Use files 2 and 3 to understand which prim is where in the viewport image.

    Args:
        width: Image width (default 1280)
        height: Image height (default 720)
        camera_path: Camera prim path (default: active viewport)
    """
    resp = _client.capture_viewport(width, height, camera_path)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"

    r = resp["result"]
    lines = []

    # 1. Save viewport image
    filepath = _save_png(r["image_base64"], "viewport")
    lines.append(f"Viewport: {r['width']}x{r['height']} -> {filepath}")

    # 2. Save screen-space bounding boxes
    bboxes = r.get("screen_bboxes", [])
    if bboxes:
        bbox_dir = os.path.join(OUTPUT_DIR, "captures")
        os.makedirs(bbox_dir, exist_ok=True)
        bbox_path = os.path.join(bbox_dir, f"viewport_{_capture_counter:04d}_bboxes.txt")
        with open(bbox_path, "w", encoding="utf-8") as f:
            f.write(f"# Screen-space bounding boxes ({r['width']}x{r['height']})\n")
            f.write(f"# Format: [x_min, y_min, x_max, y_max] in pixels\n\n")
            for b in bboxes:
                sb = b["screen_bbox"]
                f.write(f"[{b['prim_path']}]\n")
                f.write(f"type = {b['type']}\n")
                f.write(f"screen_bbox = [{sb[0]}, {sb[1]}, {sb[2]}, {sb[3]}]\n")
                f.write(f"world_center = {b['world_center']}\n")
                f.write(f"world_dimensions = {b['world_dimensions']}\n\n")
        lines.append(f"Bounding boxes ({len(bboxes)} prims) -> {_rel(bbox_path)}")
    else:
        lines.append("Bounding boxes: none (no visible prims)")

    # 3. Save instance segmentation image + legend
    seg_b64 = r.get("segmentation_base64")
    legend = r.get("segmentation_legend", {})
    if seg_b64:
        seg_path = _save_png(seg_b64, f"viewport_{_capture_counter:04d}_segmentation")
        legend_path = seg_path.replace(".png", "_legend.txt")
        abs_legend = os.path.join(os.getcwd(), legend_path) if not os.path.isabs(legend_path) else legend_path
        with open(abs_legend, "w", encoding="utf-8") as f:
            f.write("# Instance segmentation color legend\n")
            f.write("# Format: prim_path = [R, G, B]\n\n")
            for prim_path, color in legend.items():
                f.write(f"{prim_path} = [{color[0]}, {color[1]}, {color[2]}]\n")
        lines.append(f"Segmentation -> {seg_path}")
        lines.append(f"Color legend ({len(legend)} prims) -> {_rel(abs_legend)}")
    else:
        lines.append("Segmentation: not available (omni.syntheticdata may not be loaded)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: set_camera
# ---------------------------------------------------------------------------

@mcp.tool()
def set_camera(position: list[float], target: list[float] | None = None) -> str:
    """Set the viewport camera position and optionally aim it at a target point.

    Args:
        position: [x, y, z] camera position in world space
        target: [x, y, z] point to look at (optional)
    """
    resp = _client.camera_set(position, target)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    msg = f"Camera at {r['position']}"
    if r.get("target"):
        msg += f" looking at {r['target']}"
    return msg


# ---------------------------------------------------------------------------
# Tool: look_at_prim
# ---------------------------------------------------------------------------

@mcp.tool()
def look_at_prim(
    prim_path: str,
    distance: float | None = None,
    azimuth: float = 45.0,
    elevation: float = 30.0,
) -> str:
    """Point the viewport camera at a prim from a given angle.

    Auto-computes distance from object size if not specified.
    Azimuth 0=front, 90=right, 180=back, 270=left.

    Args:
        prim_path: Target prim to look at
        distance: Camera distance (auto if omitted)
        azimuth: Horizontal angle in degrees (0=front)
        elevation: Vertical angle in degrees above horizontal
    """
    resp = _client.camera_look_at(prim_path, distance, azimuth, elevation)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    return (
        f"Camera at {r['camera_position']} looking at {r['target']}\n"
        f"Distance: {r['distance']}m, Azimuth: {r['azimuth']}deg, Elevation: {r['elevation']}deg"
    )


# ---------------------------------------------------------------------------
# Tool: inspect_prim
# ---------------------------------------------------------------------------

@mcp.tool()
def inspect_prim(
    prim_path: str,
    angles: list[str] | None = None,
    width: int = 800,
    height: int = 600,
    distance: float | None = None,
) -> str:
    """Orbit-capture: take screenshots from multiple angles around a prim.

    Saves each angle as a PNG file. Use Read tool to view images.

    Args:
        prim_path: Target prim
        angles: List of angle names: "front", "right", "back", "left", "top", "perspective"
                (default: front, right, back, left, top)
        width: Image width per capture
        height: Image height per capture
        distance: Camera distance (auto-computed from object size if omitted)
    """
    resp = _client.camera_inspect(prim_path, angles, width, height, distance)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"

    r = resp["result"]
    lines = [f"Inspect {prim_path} (dist={r['distance']}m)"]
    for cap in r["captures"]:
        if "error" in cap:
            lines.append(f"  {cap['angle']}: ERROR {cap['error']}")
        else:
            filepath = _save_png(cap["image_base64"], f"inspect_{cap['angle']}")
            lines.append(f"  {cap['angle']}: {filepath}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool: start_recording
# ---------------------------------------------------------------------------

@mcp.tool()
def start_recording(
    fps: int = 5,
    width: int = 640,
    height: int = 480,
    camera_path: str = "",
    track_prims: list[str] | None = None,
    property_filter: list[str] | None = None,
) -> str:
    """Start recording simulation frames to disk.

    Captures a screenshot every 1/fps seconds while the simulation is playing.
    Frames are saved as PNGs in mcp_output/recordings/. Use stop_recording when done,
    then get_recording_frame to review any frame.

    Optionally tracks prim state (transforms, properties) alongside video frames.
    State is written to a grep-friendly state.txt in prim-block format.

    Args:
        fps: Capture rate (default 5 = one frame every 0.2s)
        width: Frame width
        height: Frame height
        camera_path: Camera to record from (default: active viewport)
        track_prims: Prim paths to track state for (includes descendants). E.g. ["/World/G1"]
        property_filter: Only record properties containing these substrings. E.g. ["joint", "pos", "vel"]
    """
    rec_dir = os.path.join(OUTPUT_DIR, "recordings")
    resp = _client.recording_start(
        rec_dir, fps, width, height, camera_path,
        track_prims=track_prims, property_filter=property_filter,
    )
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    msg = f"Recording {r['session_id']} at {r['fps']}fps -> {_rel(r['output_dir'])}"
    if r.get("track_prims"):
        msg += f"\nTracking {r['track_prims']} prims"
    msg += "\nCall sim_control('play') to start."
    return msg


# ---------------------------------------------------------------------------
# Tool: stop_recording
# ---------------------------------------------------------------------------

@mcp.tool()
def stop_recording() -> str:
    """Stop the active recording session.

    Returns session info and frame count. Use get_recording_frame to review frames.
    """
    resp = _client.recording_stop()
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"
    r = resp["result"]
    msg = f"Stopped. {r['frame_count']} frames, {r['duration_seconds']}s -> {_rel(r['output_dir'])}"
    if r.get("state_file"):
        msg += f"\nState: {_rel(r['state_file'])}"
    return msg


# ---------------------------------------------------------------------------
# Tool: get_recording_frame
# ---------------------------------------------------------------------------

@mcp.tool()
def get_recording_frame(
    frame_index: int = 0,
    session_dir: str = "",
) -> str:
    """Get a specific frame from a recording session. Saves as PNG file.

    Args:
        frame_index: Frame number (0-based)
        session_dir: Session directory (uses last recording if empty)
    """
    resp = _client.recording_frame(session_dir, frame_index)
    if resp["status"] == "error":
        return f"ERROR: {resp['error']}"

    r = resp["result"]
    filepath = _save_png(r["image_base64"], f"frame_{r['frame_index']:04d}")

    meta = f"Frame {r['frame_index']}"
    if "sim_time" in r:
        meta += f" t={r['sim_time']:.3f}s"
    return f"{meta} -> {filepath}"


# ---------------------------------------------------------------------------
# Tool: manage_extensions
# ---------------------------------------------------------------------------

@mcp.tool()
def manage_extensions(
    action: str = "list",
    extension_id: str = "",
    search: str = "",
    enabled_only: bool = False,
) -> str:
    """List, enable, or disable Isaac Sim extensions.

    Args:
        action: "list", "enable", or "disable"
        extension_id: Required for enable/disable
        search: Filter extension list by name (for action="list")
        enabled_only: Only show enabled extensions (for action="list")
    """
    if action == "list":
        resp = _client.extensions_list(enabled_only, search)
        if resp["status"] == "error":
            return f"ERROR: {resp['error']}"
        r = resp["result"]
        lines = [f"Extensions ({r['count']} found):"]
        for ext in r["extensions"][:50]:
            status = "ON " if ext["enabled"] else "OFF"
            lines.append(f"  [{status}] {ext['id']} v{ext['version']}")
        if r["count"] > 50:
            lines.append(f"  ... and {r['count'] - 50} more")
        text = "\n".join(lines)
        return _text_response(text, "extensions")
    else:
        if not extension_id:
            return "ERROR: extension_id is required for enable/disable"
        resp = _client.extensions_manage(extension_id, action)
        if resp["status"] == "error":
            return f"ERROR: {resp['error']}"
        r = resp["result"]
        return f"Extension {r['extension_id']}: {r['action']}d (enabled={r['enabled']})"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

@mcp.resource("isaac://scene/tree")
def scene_tree_resource() -> str:
    """Current scene hierarchy."""
    resp = _client.scene_tree("/", 5, fmt="text")
    if resp["status"] == "error":
        return f"Error: {resp['error']}"
    return resp["result"]["text"]


@mcp.resource("isaac://sim/state")
def sim_state_resource() -> str:
    """Current simulation state."""
    resp = _client.sim_state()
    if resp["status"] == "error":
        return f"Error: {resp['error']}"
    return json.dumps(resp["result"], indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
