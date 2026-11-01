"""Every tool once, through SDK v2's in-memory MCP client against the mock bridge: the route it calls, what it sends,
and the text the model reads back from a canned answer. tests/test_contract.py pins what the tools accept; this pins
what they do with it."""

import asyncio
import math
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import golden
import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from omniverse_mcp import kit_extension
from omniverse_mcp.client import BridgeClient
from omniverse_mcp.server import create_server
from omniverse_mcp.tools.simulation import _unit

from .mock_bridge import MockIsaacServer

HANDSHAKE = {"status": "success", "result": {"protocol": 1, "extension_version": "1.0.0"}}
# The 8-byte PNG signature: enough for the server, which writes the bytes as they come.
PNG = "iVBORw0KGgo="
# Stands for the server's output folder in what a case expects sent: each test has its own.
OUTPUT = "<output>"
# /scene/face_count_tree's text for a robot of one mesh, as the extension writes it, its `# total:` line last.
TREE = (
    "# face_count_tree root=/World/Robot\n\n[/World/Robot]\ntype = Xform\nsubtree_faces = 6\n\n"
    "[/World/Robot/Body]\ntype = Mesh\nfaces = 6\nvertices = 8\ntriangles = 12\n\n# total: 6 faces in 1 meshes"
)


@dataclass(frozen=True)
class Case:
    tool: str
    args: dict[str, Any]
    route: str
    answer: dict[str, Any]
    sent: dict[str, Any]  # what the first request's body must hold, at least
    says: tuple[str, ...]  # what the tool's text must hold
    # The routes the tool calls after the first, in order, each with its answer: a merged tool asks two (#77).
    more: tuple[tuple[str, dict[str, Any]], ...] = ()

    def __str__(self) -> str:
        return self.tool


CASES = [
    # Scene
    Case(
        "get_scene_tree",
        {"root": "/World"},
        "/scene/tree",
        {"text": "[/World]\ntype = Xform\n"},
        {"root": "/World", "max_depth": 5, "format": "text"},
        ("[/World]", "type = Xform"),
    ),
    Case(
        "get_prim_properties",
        {"prim_path": "/World/Cube"},
        "/scene/prim",
        {"text": "[/World/Cube]\ntype = Cube\n"},
        # The bridge sends text only when asked; without it the tool would read a key that isn't there.
        {"prim_path": "/World/Cube", "format": "text"},
        ("type = Cube",),
    ),
    Case(
        "get_prim_bounds",
        {"prim_path": "/World/Cube"},
        "/scene/bounds",
        {
            "prim_path": "/World/Cube",
            "center": [0, 0, 0.5],
            "dimensions": [1, 1, 1],
            "min": [-0.5, -0.5, 0],
            "max": [0.5, 0.5, 1],
            "diagonal": 1.7320508,
        },
        {"prim_path": "/World/Cube"},
        ("center = 0.0000, 0.0000, 0.5000", "diagonal = 1.7321"),
    ),
    Case(
        "set_prim_transform",
        {"prim_path": "/World/Cube", "position": [1, 2, 3], "scale": 2.0},
        "/scene/transform",
        {},
        {"prim_path": "/World/Cube", "position": [1, 2, 3], "scale": 2.0},
        ("Transform updated for /World/Cube",),
    ),
    Case(
        "create_prim",
        {"prim_path": "/World/Cube", "prim_type": "Cube", "position": [0, 0, 1], "enable_physics": True},
        "/scene/create",
        {"prim_path": "/World/Cube", "type": "Cube"},
        {"prim_path": "/World/Cube", "prim_type": "Cube", "position": [0, 0, 1], "enable_physics": True},
        ("Created Cube at /World/Cube",),
    ),
    Case(
        "delete_prim",
        {"prim_path": "/World/Cube"},
        "/scene/delete",
        {"prim_path": "/World/Cube", "message": "Prim deleted", "checked": True},
        {"prim_path": "/World/Cube"},
        ("Deleted /World/Cube",),
    ),
    Case(
        "set_material",
        {"prim_path": "/World/Cube", "color": [1, 0, 0], "opacity": 0.5},
        "/scene/material",
        {
            "prim_path": "/World/Cube",
            "material_path": "/World/Looks/Cube_Mat",
            "color": [1, 0, 0],
            "opacity": 0.5,
            "roughness": 0.5,
            "metallic": 0.0,
        },
        {"prim_path": "/World/Cube", "color": [1, 0, 0], "opacity": 0.5},
        ("Material /World/Looks/Cube_Mat -> /World/Cube", "opacity=0.5"),
    ),
    Case(
        "clone_prim",
        {"source_path": "/World/Cube", "target_path": "/World/Row", "count": 2, "offset": [2, 0, 0]},
        "/scene/clone",
        {"clones": ["/World/Row_001", "/World/Row_002"]},
        {"source_path": "/World/Cube", "target_path": "/World/Row", "count": 2, "offset": [2, 0, 0]},
        ("2 copies", "/World/Row_002"),
    ),
    Case(
        "set_visibility",
        {"prim_path": "/World/Cube", "visible": False},
        "/scene/visibility",
        {"prim_path": "/World/Cube", "visible": False},
        {"prim_path": "/World/Cube", "visible": False},
        ("/World/Cube is now hidden",),
    ),
    Case(
        "save_scene",
        {"file_path": "scene.usd"},
        "/scene/save",
        {"action": "save_as", "file_path": "scene.usd"},
        {"file_path": "scene.usd"},
        ("Scene saved (save_as) -> scene.usd",),
    ),
    Case(
        "open_scene",
        {"file_path": "C:/Scenes/room.usda"},
        "/scene/open",
        {
            "file_path": "C:/Scenes/room.usda",
            "replaced": None,
            "up_axis": "Z",
            "up_axis_authored": True,
            "meters_per_unit": 1.0,
            "meters_per_unit_authored": True,
            "default_prim": "/World",
            "prim_count": 14,
            "package": False,
            "writable": True,
            "stopped": False,
            "recording_note": None,
        },
        {"file_path": "C:/Scenes/room.usda"},
        ("Opened C:/Scenes/room.usda\nup_axis = Z\nmeters_per_unit = 1.0\ndefault_prim = /World\nprim_count = 14",),
    ),
    Case("new_scene", {}, "/scene/new", {}, {}, ("New scene created",)),
    # Geometry and USD
    Case(
        "get_mesh_stats",
        {"prim_path": "/World/Robot"},
        "/scene/mesh_stats",
        {
            "prim_path": "/World/Robot",
            "mesh_count": 1,
            "total_faces": 6,
            "total_vertices": 8,
            "total_triangles": 12,
            "meshes": [{"path": "/World/Robot/Body", "faces": 6, "vertices": 8, "triangles": 12}],
        },
        {"prim_path": "/World/Robot"},
        (
            "[/World/Robot]\nmeshes = 1\ntotal_faces = 6\ntotal_vertices = 8\ntotal_triangles = 12\n\n"
            "# face_count_tree root=/World/Robot\n\n[/World/Robot]\ntype = Xform\nsubtree_faces = 6\n\n"
            "[/World/Robot/Body]\ntype = Mesh\nfaces = 6\nvertices = 8\ntriangles = 12",
        ),
        more=(("/scene/face_count_tree", {"text": TREE, "total_faces": 6, "mesh_count": 1}),),
    ),
    Case(
        "compare_prims",
        {"prim_path_a": "/World/A", "prim_path_b": "/World/B"},
        "/scene/compare",
        {
            "a": {
                "label": "/World/A",
                "mesh_count": 2,
                "total_faces": 100,
                "total_vertices": 80,
                "total_triangles": 200,
                "bounds_center": [0, 0, 0],
                "bounds_dimensions": [1, 1, 1],
                "materials": ["/World/Looks/M"],
            },
            "b": {
                "label": "/World/B",
                "mesh_count": 1,
                "total_faces": 40,
                "total_vertices": 30,
                "total_triangles": 80,
                "bounds_center": [0, 0, 0],
                "bounds_dimensions": [1, 1, 1],
                "materials": [],
            },
            "delta": {"faces": -60, "face_reduction_pct": -60.0, "vertices": -50, "triangles": -120, "meshes": -1},
        },
        {"prim_path_a": "/World/A", "prim_path_b": "/World/B"},
        ("=== A: /World/A ===", "materials: none", "faces: -60 (-60.0%)"),
    ),
    Case(
        "flatten_usd",
        {"output_path": "flat.usd", "input_path": "in.usd"},
        "/scene/flatten",
        {"input_path": "in.usd", "layer_count": 3, "output_path": "flat.usd"},
        {"output_path": "flat.usd", "input_path": "in.usd"},
        ("Flattened in.usd (3 layers) -> flat.usd",),
    ),
    Case(
        "export_prim_as_file",
        {"prim_path": "/World/Cube", "output_path": "cube.usdc"},
        "/scene/export",
        {
            "prim_path": "/World/Cube",
            "output_path": "cube.usdc",
            "target_root": "/Cube",
            "materials_included": 1,
            "up_axis": "Z",
        },
        {"prim_path": "/World/Cube", "output_path": "cube.usdc"},
        ("Exported /World/Cube -> cube.usdc", "Up: Z"),
    ),
    Case(
        "set_variant_selection",
        {"prim_path": "/World/Asset", "variant_set": "model", "variant_name": "shell"},
        "/scene/variant_selection",
        {
            "prim_path": "/World/Asset",
            "variant_set": "model",
            "new_selection": "shell",
            "old_selection": "full",
            "available_variants": ["full", "shell"],
        },
        {"prim_path": "/World/Asset", "variant_set": "model", "variant_name": "shell"},
        ("model=shell (was: full)",),
    ),
    Case(
        "create_variant_structure",
        {"prim_path": "/World/Asset", "variant_set_name": "model", "variant_names": ["full", "shell"]},
        "/scene/create_variant_structure",
        {
            "prim_path": "/World/Asset",
            "variant_set_name": "model",
            "variants_created": ["full", "shell"],
            "default_selection": "full",
        },
        {"prim_path": "/World/Asset", "variant_set_name": "model", "variant_names": ["full", "shell"]},
        ("Created variant set 'model' on /World/Asset", "Default: full"),
    ),
    Case(
        "update_material_paths",
        {"old_prefix": "/Old/Looks", "new_prefix": "/World/Looks"},
        "/scene/update_material_paths",
        {"updated_count": 2, "updated_prims": ["/World/A"], "old_prefix": "/Old/Looks", "new_prefix": "/World/Looks"},
        {"old_prefix": "/Old/Looks", "new_prefix": "/World/Looks", "prim_path": "/"},
        ("Updated 2 references in 1 prims", "  /World/A"),
    ),
    # Robots
    Case(
        "create_robot",
        {"robot_type": "franka", "position": [0, 0, 0]},
        "/robot/create",
        {
            "robot_type": "franka",
            "prim_path": "/World/Franka",
            "usd_path": "franka.usd",
            "joints": [{"path": "/World/Franka/joint1", "type": "RevoluteJoint"}],
        },
        {"robot_type": "franka", "position": [0, 0, 0]},
        ("Robot 'franka' created at /World/Franka", "/World/Franka/joint1 (RevoluteJoint)"),
    ),
    Case(
        "get_robot_info",
        {"prim_path": "/World/Franka"},
        "/robot/info",
        {
            "prim_path": "/World/Franka",
            "is_articulation": True,
            "dof_count": 1,
            "link_count": 2,
            "joints": [
                {"name": "joint1", "type": "RevoluteJoint", "lower_limit": -1, "upper_limit": 1, "drive_angular": True}
            ],
        },
        {"prim_path": "/World/Franka"},
        (
            "DOF: 1",
            "Joints (1):\n  joint1 (RevoluteJoint [-1.0, 1.0] drive=angular)\nJoint states (1 DOF, from physics: ",
            "set_joint_targets takes degrees):\n  joint1: pos=0.5000 vel=0.2500",
        ),
        more=(
            (
                "/robot/joint_states",
                {
                    "prim_path": "/World/Franka",
                    "dof_count": 1,
                    "names": ["joint1"],
                    "positions": [0.5],
                    "velocities": [0.25],
                },
            ),
        ),
    ),
    Case(
        "set_joint_targets",
        {"prim_path": "/World/Franka", "targets": {"joint1": 0.5}},
        "/robot/joint_targets",
        {"prim_path": "/World/Franka", "targets_set": 1, "failed": ["joint9"]},
        {"prim_path": "/World/Franka", "targets": {"joint1": 0.5}},
        ("Set 1 joint targets on /World/Franka", "Failed: ['joint9']"),
    ),
    # Camera
    Case(
        "capture_viewport",
        {"width": 64, "height": 48},
        "/sim/capture",
        {
            "width": 64,
            "height": 48,
            "image_base64": PNG,
            "lighting_mode": "stage",
            "screen_bboxes": [
                {
                    "prim_path": "/World/Cube",
                    "type": "Cube",
                    "screen_bbox": [1, 2, 30, 40],
                    "world_center": [0, 0, 0],
                    "world_dimensions": [1, 1, 1],
                }
            ],
            "segmentation_base64": PNG,
            "segmentation_legend": {"/World/Cube": [255, 0, 0]},
        },
        {"width": 64, "height": 48},
        ("Viewport: 64x48 (lighting: stage)", "Bounding boxes (1 prims)", "Color legend (1 prims)"),
    ),
    Case(
        "set_camera",
        {"position": [5, 3, 5], "target": [0, 0, 0]},
        "/camera/set",
        {"position": [5, 3, 5], "target": [0, 0, 0]},
        {"position": [5, 3, 5], "target": [0, 0, 0]},
        ("Camera at [5, 3, 5] looking at [0, 0, 0]",),
    ),
    Case(
        "inspect_prim",
        {"prim_path": "/World/Cube", "angles": ["front", "top"], "zoom_offset": -0.3},
        "/camera/inspect",
        {
            "distance": 2.5,
            "zoom_offset": -0.3,
            "lighting_mode": "stage",
            "captures": [{"angle": "front", "image_base64": PNG}, {"angle": "top", "error": "invented failure"}],
        },
        {"prim_path": "/World/Cube", "angles": ["front", "top"], "zoom_offset": -0.3},
        ("Inspect /World/Cube (dist=2.5 stage units, zoom_offset=-0.3)", "top: ERROR invented failure"),
    ),
    Case(
        "viewport_light",
        {"action": "get"},
        "/viewport/light",
        {
            "lighting_mode": "stage",
            "available_modes": ["off", "camera", "stage"],
            "has_scene_lights": True,
            "scene_lights": [{"path": "/World/Sun", "type": "DistantLight", "intensity": 1000}],
        },
        {"action": "get"},
        ("Lighting mode: stage", "/World/Sun (DistantLight, intensity=1000)"),
    ),
    # Simulation and physics
    Case(
        "sim_control",
        {"action": "play"},
        "/sim/control",
        {"action": "play", "current_state": "playing"},
        {"action": "play"},
        ("'play' executed. Sim is now: playing",),
    ),
    Case(
        "get_sim_state",
        {},
        "/sim/state",
        {
            "state": "stopped",
            "up_axis": "Z",
            "sim_time": 0.0,
            "fps": 60.0,
            "prim_count": 3,
            "meters_per_unit": 1.0,
            "kit_app_name": "Isaac-Sim Python",
            "kit_app_version": "6.2.0",
            "kit_version": "110.4.0+feature.386251.187cf21b.gl",
            "kit_os": "Windows-11-10.0.26300-SP0",
        },
        {},
        # The mock bridge's handshake answers extension 1.0.0, another release than this server's.
        (
            "state = stopped",
            "up_axis = Z",
            "kit_app = Isaac-Sim Python 6.2.0\nkit_version = 110.4.0+feature.386251.187cf21b.gl\n"
            "kit_os = Windows-11-10.0.26300-SP0\nextension_version = 1.0.0",
            "note = the Kit extension is 1.0.0",
            f"install the server's, {kit_extension.install_advice()}",
        ),
    ),
    Case(
        "set_physics_properties",
        {"prim_path": "/World/Cube", "mass": 0, "friction": 0.4},
        "/physics/properties",
        # The extension echoes each value it was sent, null for one left out.
        {
            "prim_path": "/World/Cube",
            "applied": ["MassAPI", "PhysicsMaterial"],
            "mass": 0.0,
            "density": None,
            "friction": 0.4,
            "restitution": None,
        },
        {"prim_path": "/World/Cube", "mass": 0, "friction": 0.4},
        (
            "Physics on /World/Cube: mass=0.0 (unset, so density decides), friction=0.4 (static and dynamic); "
            "applied MassAPI, PhysicsMaterial",
        ),
    ),
    Case(
        "apply_force",
        {"prim_path": "/World/Cube", "force": [0, 0, 10], "impulse": True},
        "/physics/apply_force",
        {
            "prim_path": "/World/Cube",
            "force": [0.0, 0.0, 10.0],
            # A centre of mass from PhysX carries float32 noise; the tool rounds it away.
            "position": [0.0, 0.10000000149011612, 2.0],
            "at": "centre of mass",
            "impulse": True,
            "method": "physx",
        },
        {"prim_path": "/World/Cube", "force": [0, 0, 10], "impulse": True},
        ("Applied impulse [0.0, 0.0, 10.0] to /World/Cube at [0.0, 0.1, 2.0] (centre of mass, method: physx)",),
    ),
    Case(
        "raycast",
        {"origin": [0, 0, 5], "direction": [0, 0, -1]},
        "/physics/raycast",
        {"hit": True, "prim_path": "/World/Ground", "position": [0, 0, 0], "normal": [0, 0, 1], "distance": 5.0},
        {"origin": [0, 0, 5], "direction": [0, 0, -1], "max_distance": 1000.0},
        ("Hit: /World/Ground", "Distance: 5.0000 stage units"),
    ),
    Case(
        "draw_debug",
        {"shape": "lines", "points": [[0, 0, 0], [0, 0, 1]], "size": 0.1},
        "/debug/draw",
        {"drawn": [{"type": "lines", "segments": 1}], "backend": "isaacsim.util.debug_draw", "duration": 5.0},
        {"type": "lines", "points": [[0, 0, 0], [0, 0, 1]], "size": 0.1, "duration": 5.0},
        ("Drew 1 debug element(s): lines, for 5.0 s (isaacsim.util.debug_draw)",),
    ),
    # Recording
    Case(
        "start_recording",
        {"fps": 10, "track_prims": ["/World/G1"]},
        "/recording/start",
        {
            "session_id": "rec_1",
            "fps": 10,
            "output_dir": "rec_1",
            "resolution": [640, 480],
            "camera_path": "/OmniverseKit_Persp",
            "render_product": "/Render/OmniverseKit/HydraTextures/ovmcp_recording_0",
            "track_prims": ["/World/G1", "/World/G1/base"],
        },
        {"output_dir": str(Path(OUTPUT) / "recordings"), "fps": 10, "track_prims": ["/World/G1"]},
        ("Recording rec_1 at 10fps, 640x480 from /OmniverseKit_Persp", "Tracking 2 prims"),
    ),
    Case(
        "stop_recording",
        {},
        "/recording/stop",
        {
            "frame_count": 3,
            "duration_seconds": 0.6,
            "simulation_seconds": 0.4,
            "idle_seconds": 0.15,
            "output_dir": "rec_1",
            "state_file": "rec_1/state.txt",
        },
        {},
        (
            "Stopped. 3 frames, 0.6s: 0.40 s of simulation played, 0.15 s stopped or paused -> ",
            "State: rec_1/state.txt",
        ),
    ),
    Case(
        "get_recording_frame",
        {"frame_index": 2},
        "/recording/frame",
        {"frame_index": 2, "image_base64": PNG, "sim_time": 0.4},
        {"frame_index": 2},
        ("Frame 2 t=0.400s -> ",),
    ),
    # Extensions, logs, scripts
    Case(
        "manage_extensions",
        {"action": "list", "search": "ovmcp"},
        "/extensions/list",
        {"count": 1, "extensions": [{"id": "ovmcp.bridge", "version": "0.1.0", "enabled": True}]},
        {"search": "ovmcp"},
        ("Extensions (1 found):", "[ON ] ovmcp.bridge v0.1.0"),
    ),
    Case(
        "get_logs",
        {"count": 5, "min_level": "warn", "channel": "omni.physx"},
        "/logs",
        {
            "entries": [{"level": "warn", "channel": "omni.physx", "msg": "invented warning"}],
            "count": 1,
            "total_captured": 9,
            "buffer_size": 2000,
        },
        {"count": 5, "min_level": "warn", "channel": "omni.physx"},
        ("Log entries (1/9 total, buffer=2000):", "[WARN ] omni.physx: invented warning"),
    ),
    Case(
        "execute_script",
        {"code": "print('hi'); result = 2"},
        "/execute",
        {"stdout": "hi\n", "stderr": "", "return_value": 2},
        {"code": "print('hi'); result = 2"},
        ("Stdout:\nhi", "Return value:\n2"),
    ),
]


@pytest.fixture(scope="module")
def bridge():
    mock = MockIsaacServer()
    mock.set_response("/bridge", HANDSHAKE)
    mock.start()
    yield mock
    mock.stop()


def test_every_tool_has_a_case():
    tools = set(asyncio.run(golden.contract())["tools"])
    cases = [case.tool for case in CASES]
    assert len(cases) == len(set(cases)), "a tool has two cases"
    assert sorted(tools - set(cases)) == [], "these tools have no case"
    assert sorted(set(cases) - tools) == [], "these cases name no tool"


def _check(case: Case, bridge: MockIsaacServer, tmp_path: Path) -> str:
    """Calls the case's tool, checks its requests and its text, and returns the text."""
    for route, answer in ((case.route, case.answer), *case.more):
        bridge.set_response(route, {"status": "success", "result": answer})
    bridge.requests.clear()
    client = BridgeClient(port=bridge.port, token="invented-test-token")
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool(case.tool, case.args)

        result = asyncio.run(call())
    finally:
        client.close()

    text = "\n".join(getattr(c, "text", "") for c in result.content)
    assert not result.is_error, text
    calls = [(path, body) for _, path, body in bridge.requests if path != "/bridge"]
    assert [path for path, _ in calls] == [case.route, *(route for route, _ in case.more)]
    body = calls[0][1]
    sent = {k: v.replace(OUTPUT, str(tmp_path)) if isinstance(v, str) else v for k, v in case.sent.items()}
    assert {k: body.get(k) for k in sent} == sent
    for part in case.says:
        assert part in text
    return text


@pytest.mark.parametrize("case", CASES, ids=str)
def test_the_tool_calls_its_route_and_reads_the_answer(case: Case, bridge: MockIsaacServer, tmp_path: Path):
    _check(case, bridge, tmp_path)


def test_manage_extensions_enables_one(bridge: MockIsaacServer, tmp_path: Path):
    # The table's case lists; enabling takes the other route.
    _check(
        Case(
            "manage_extensions",
            {"action": "enable", "extension_id": "omni.invented"},
            "/extensions/manage",
            {"extension_id": "omni.invented", "action": "enable", "enabled": True},
            {"extension_id": "omni.invented", "action": "enable"},
            ("Extension omni.invented: enabled (enabled=True)",),
        ),
        bridge,
        tmp_path,
    )


def test_draw_debug_reads_a_0_2_0_bridges_answer(bridge: MockIsaacServer, tmp_path: Path):
    # A 0.2.0 bridge answers neither backend nor duration; its drawing lasted a frame, so none is claimed.
    text = _check(
        Case(
            "draw_debug",
            {"shape": "line", "start": [0, 0, 0], "end": [1, 0, 0], "duration": 2.0},
            "/debug/draw",
            {"drawn": [{"type": "line", "start": [0, 0, 0], "end": [1, 0, 0]}]},
            {"type": "line", "start": [0, 0, 0], "end": [1, 0, 0], "duration": 2.0},
            ("Drew 1 debug element(s): line",),
        ),
        bridge,
        tmp_path,
    )
    assert text == "Drew 1 debug element(s): line"


def test_draw_debug_says_how_long_each_drawing_shows(bridge: MockIsaacServer, tmp_path: Path):
    answer = {"drawn": [{"type": "point"}, {"type": "point"}], "backend": "omni.debugdraw", "duration": 0.25}
    _check(
        Case(
            "draw_debug",
            {"shape": "points", "points": [[0, 0, 0], [1, 1, 1]], "duration": 0.25},
            "/debug/draw",
            answer,
            {"type": "points", "points": [[0, 0, 0], [1, 1, 1]], "duration": 0.25},
            ("Drew 2 debug element(s): point, point, for 0.25 s (omni.debugdraw)",),
        ),
        bridge,
        tmp_path,
    )


def test_apply_force_at_a_given_point(bridge: MockIsaacServer, tmp_path: Path):
    _check(
        Case(
            "apply_force",
            {"prim_path": "/World/Cube", "force": [5, 0, 0], "position": [0, 0, 1.5]},
            "/physics/apply_force",
            {
                "prim_path": "/World/Cube",
                "force": [5.0, 0.0, 0.0],
                "position": [0.0, 0.0, 1.5],
                "at": "given",
                "impulse": False,
                "method": "physx",
            },
            {"prim_path": "/World/Cube", "force": [5, 0, 0], "position": [0, 0, 1.5], "impulse": False},
            ("Applied force [5.0, 0.0, 0.0] to /World/Cube at [0.0, 0.0, 1.5] (given, method: physx)",),
        ),
        bridge,
        tmp_path,
    )


def test_apply_force_names_the_tensor_api_when_the_push_went_through_it(bridge: MockIsaacServer, tmp_path: Path):
    # With /physics/suppressReadback on (#68), where a second push on the body before the next step replaces this one.
    text = _check(
        Case(
            "apply_force",
            {"prim_path": "/World/Cube", "force": [10, 0, 0], "impulse": True},
            "/physics/apply_force",
            {
                "prim_path": "/World/Cube",
                "force": [10.0, 0.0, 0.0],
                "position": [1.0, 0.5, 0.0],
                "at": "centre of mass",
                "impulse": True,
                "method": "tensor",
            },
            {"prim_path": "/World/Cube", "force": [10, 0, 0], "impulse": True},
            (),
        ),
        bridge,
        tmp_path,
    )
    assert text == "Applied impulse [10.0, 0.0, 0.0] to /World/Cube at [1.0, 0.5, 0.0] (centre of mass, method: tensor)"


def _physics_answer(**sent: Any) -> dict[str, Any]:
    """The extension's answer to set_physics_properties: the APIs it applied, each value echoed, null if unsent, and
    the material it bound for friction or restitution (#113)."""
    applied = []
    if "mass" in sent or "density" in sent:
        applied.append("MassAPI")
    material = {}
    if "friction" in sent or "restitution" in sent:
        applied.append("PhysicsMaterial")
        material = {"material": "/World/RedCube/PhysMat"}
    values = {k: sent.get(k) for k in ("mass", "density", "friction", "restitution")}
    return {"prim_path": "/World/RedCube", "applied": applied, **values, **material}


@pytest.mark.parametrize(
    ("args", "says"),
    [
        # Scenarios 15.1 to 15.3: each value as the extension set it.
        ({"mass": 5.0}, "Physics on /World/RedCube: mass=5.0; applied MassAPI"),
        (
            {"friction": 0.8, "restitution": 0.3},
            "Physics on /World/RedCube: friction=0.8 (static and dynamic), restitution=0.3; "
            "material /World/RedCube/PhysMat; applied PhysicsMaterial",
        ),
        ({"density": 1000.0}, "Physics on /World/RedCube: density=1000.0; applied MassAPI"),
        ({"density": 0}, "Physics on /World/RedCube: density=0.0 (unset); applied MassAPI"),
        (
            {"mass": 2, "density": 500, "friction": 0, "restitution": 1},
            "Physics on /World/RedCube: mass=2.0, density=500.0, friction=0.0 (static and dynamic), restitution=1.0; "
            "material /World/RedCube/PhysMat; applied MassAPI, PhysicsMaterial",
        ),
    ],
)
def test_set_physics_properties_says_each_value_it_set(
    args: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    text = _check(
        Case(
            "set_physics_properties",
            {"prim_path": "/World/RedCube", **args},
            "/physics/properties",
            _physics_answer(**args),
            {"prim_path": "/World/RedCube", **args},
            (),
        ),
        bridge,
        tmp_path,
    )
    assert text == says


def test_set_physics_properties_says_when_it_became_a_rigid_body(bridge: MockIsaacServer, tmp_path: Path):
    # The extension names RigidBodyAPI and CollisionAPI only when this call added them.
    applied = ["RigidBodyAPI", "MassAPI", "CollisionAPI", "PhysicsMaterial"]
    answer = {**_physics_answer(mass=5.0, friction=0.5), "applied": applied}
    text = _check(
        Case(
            "set_physics_properties",
            {"prim_path": "/World/RedCube", "mass": 5.0, "friction": 0.5},
            "/physics/properties",
            answer,
            {"prim_path": "/World/RedCube", "mass": 5.0, "friction": 0.5},
            (),
        ),
        bridge,
        tmp_path,
    )
    assert text.endswith("; applied RigidBodyAPI, MassAPI, CollisionAPI, PhysicsMaterial")


def _physics_text(answer: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path) -> str:
    """The tool's text for friction 0.5 on /World/RedCube, given the extension's answer."""
    sent = {"prim_path": "/World/RedCube", "friction": 0.5}
    return _check(Case("set_physics_properties", sent, "/physics/properties", answer, sent, ()), bridge, tmp_path)


def test_set_physics_properties_with_an_older_extension_names_no_material(bridge: MockIsaacServer, tmp_path: Path):
    # An extension of 0.3.0 or older binds /World/PhysicsMaterials/<name>_PhysMat and sends no material.
    answer = {k: v for k, v in _physics_answer(friction=0.5).items() if k != "material"}

    text = _physics_text(answer, bridge, tmp_path)

    assert text == "Physics on /World/RedCube: friction=0.5 (static and dynamic); applied PhysicsMaterial"


@pytest.mark.parametrize(
    ("shared", "says"),
    [
        ({"count": 1, "prims": ["/World/envs/env_1/Cube"]}, "; also changes 1 prim: /World/envs/env_1/Cube"),
        (
            {"count": 7, "prims": [f"/World/envs/env_{e}/Cube" for e in range(1, 6)]},
            "; also changes 7 prims: /World/envs/env_1/Cube, /World/envs/env_2/Cube, /World/envs/env_3/Cube, "
            "/World/envs/env_4/Cube, /World/envs/env_5/Cube and 2 more",
        ),
    ],
    ids=["one", "five named and the rest counted"],
)
def test_set_physics_properties_names_the_other_prims_it_changes(
    shared: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    text = _physics_text({**_physics_answer(friction=0.5), "also_changes": shared}, bridge, tmp_path)

    assert text.endswith(f"; applied PhysicsMaterial{says}")


OLD_PHYSMAT = "/World/PhysicsMaterials/RedCube_PhysMat"


@pytest.mark.parametrize(
    ("old", "says"),
    [
        (
            {"path": OLD_PHYSMAT, "deleted": [OLD_PHYSMAT]},
            f"; deleted its old material, {OLD_PHYSMAT}, which no prim binds now",
        ),
        (
            {"path": OLD_PHYSMAT, "deleted": [OLD_PHYSMAT, "/World/PhysicsMaterials"]},
            f"; deleted its old material, {OLD_PHYSMAT}, which no prim binds now, and /World/PhysicsMaterials, left "
            "empty",
        ),
        (
            {"path": OLD_PHYSMAT, "kept": "1 prim still binds it: /World/Shelf/RedCube"},
            f"; kept its old material, {OLD_PHYSMAT}: 1 prim still binds it: /World/Shelf/RedCube",
        ),
    ],
    ids=["deleted", "deleted with its folder", "kept"],
)
def test_set_physics_properties_says_what_became_of_the_old_material(
    old: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    text = _physics_text({**_physics_answer(friction=0.5), "old_material": old}, bridge, tmp_path)

    assert text == (
        "Physics on /World/RedCube: friction=0.5 (static and dynamic); material /World/RedCube/PhysMat; "
        f"applied PhysicsMaterial{says}"
    )


def test_set_physics_properties_with_no_value_says_nothing_was_set(bridge: MockIsaacServer, tmp_path: Path):
    text = _check(
        Case(
            "set_physics_properties",
            {"prim_path": "/World/RedCube"},
            "/physics/properties",
            _physics_answer(),
            {"prim_path": "/World/RedCube"},
            (),
        ),
        bridge,
        tmp_path,
    )
    assert text == "Nothing set on /World/RedCube: give mass, density, friction or restitution"


def test_get_logs_passes_on_the_bridges_note(bridge: MockIsaacServer, tmp_path: Path):
    # Kit wrote lines and none started an entry: the note says so, where an empty answer alone reads as a quiet Kit.
    _check(
        Case(
            "get_logs",
            {},
            "/logs",
            {"entries": [], "count": 0, "total_captured": 0, "buffer_size": 2000, "note": "an invented note"},
            {"count": 50},
            ("No log entries found (buffer has 0 total entries)\nan invented note",),
        ),
        bridge,
        tmp_path,
    )


def test_apply_force_reads_a_0_2_0_extension_s_answer(bridge: MockIsaacServer, tmp_path: Path):
    # 0.2.0's extension answers no `at`, echoes the position asked for (None when none was), and nudged the velocity.
    _check(
        Case(
            "apply_force",
            {"prim_path": "/World/Cube", "force": [100, 0, 0]},
            "/physics/apply_force",
            {
                "prim_path": "/World/Cube",
                "force": [100, 0, 0],
                "position": None,
                "impulse": False,
                "method": "velocity",
            },
            {"prim_path": "/World/Cube", "force": [100, 0, 0], "impulse": False},
            ("Applied force [100, 0, 0] to /World/Cube (method: velocity)",),
        ),
        bridge,
        tmp_path,
    )


def test_get_sim_state_says_nothing_more_when_the_extension_is_this_release(bridge: MockIsaacServer, tmp_path: Path):
    # The extension this checkout carries, which is what a server started from it installs.
    release = kit_extension.carried_version()
    bridge.set_response("/bridge", {"status": "success", "result": {"protocol": 1, "extension_version": release}})
    bridge.set_response("/sim/state", {"status": "success", "result": {"state": "stopped"}})
    client = BridgeClient(port=bridge.port, token="invented-test-token")
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool("get_sim_state", {})

        result = asyncio.run(call())
    finally:
        client.close()
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    assert f"extension_version = {release}\nserver_version = {version('omniverse-mcp')}" in text
    assert "note = " not in text


# What the bridge answers open_scene for a stage the model should be told more about (#79): a .usdz from a URL that
# sets no axis or units, opened while the simulation and a recording ran.
OPENED_WITH_NOTES = {
    "file_path": "https://example.invalid/Scenes/room.usdz",
    "replaced": "C:/Scenes/before.usda",
    "up_axis": "Y",
    "up_axis_authored": False,
    "meters_per_unit": 0.01,
    "meters_per_unit_authored": False,
    "default_prim": None,
    "prim_count": 3,
    "package": True,
    "writable": False,
    "stopped": True,
    "recording_note": "frames stopped after 28, at 0.00 s of simulation: the stage began to close",
}


def _open_scene(answer: dict[str, Any], says: tuple[str, ...]) -> Case:
    file_path = str(answer["file_path"])
    return Case("open_scene", {"file_path": file_path}, "/scene/open", answer, {"file_path": file_path}, says)


def test_open_scene_says_what_the_model_should_know_of_the_stage(bridge: MockIsaacServer, tmp_path: Path):
    says = (
        "Opened https://example.invalid/Scenes/room.usdz\nreplaced = C:/Scenes/before.usda\n",
        "default_prim = none",
        "note = the file sets no upAxis: USD reads it as Y",
        "note = the file sets no metersPerUnit: USD reads it as 0.01 (centimetres)",
        "note = a .usdz package can't be saved back: flatten_usd, or save_scene with a file_path ending .usd or .usda",
        "note = the simulation was playing or paused: it is stopped now",
        "recording_note = frames stopped after 28, at 0.00 s of simulation: the stage began to close",
    )
    text = _check(_open_scene(OPENED_WITH_NOTES, says), bridge, tmp_path)
    # A package can't be saved back at all; the read-only note would say less.
    assert "read-only" not in text


def test_open_scene_notes_a_read_only_stage_alone(bridge: MockIsaacServer, tmp_path: Path):
    answer = {
        **OPENED_WITH_NOTES,
        "up_axis_authored": True,
        "meters_per_unit_authored": True,
        "package": False,
        "stopped": False,
        "recording_note": None,
    }
    text = _check(
        _open_scene(answer, ("note = the stage is read-only here: save_scene needs a file_path to keep changes",)),
        bridge,
        tmp_path,
    )
    assert text.count("note = ") == 1


# What an extension of 0.2.2 or older answers a recording's start with: it records the viewport, and names no render
# product (#25).
OLDER_RECORDING = {"session_id": "rec_1", "fps": 5, "output_dir": "rec_1", "resolution": [640, 480]}


def _recording(camera: str, width: int, height: int) -> dict[str, Any]:
    """What this release's extension answers: the frames' camera and size, and the render product they come from."""
    return {
        "session_id": "rec_1",
        "fps": 5,
        "output_dir": "rec_1",
        "resolution": [width, height],
        "camera_path": camera,
        "render_product": "/Render/OmniverseKit/HydraTextures/ovmcp_recording_0",
    }


@pytest.mark.parametrize(
    ("args", "answer", "says"),
    [
        (
            {"camera_path": "/World/RecCam", "width": 320, "height": 240},
            _recording("/World/RecCam", 320, 240),
            "Recording rec_1 at 5fps, 320x240 from /World/RecCam -> ",
        ),
        ({}, _recording("/OmniverseKit_Persp", 640, 480), "Recording rec_1 at 5fps, 640x480 from /OmniverseKit_Persp"),
    ],
)
def test_start_recording_says_the_camera_and_size_it_records(
    args: dict[str, Any], answer: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    text = _check(Case("start_recording", args, "/recording/start", answer, args, (says,)), bridge, tmp_path)
    assert "WARNING" not in text
    assert "\nRenders into /Render/OmniverseKit/HydraTextures/ovmcp_recording_0, deleted at stop\n" in text


def test_start_recording_warns_an_older_extension_ignores_the_camera_and_size(bridge: MockIsaacServer, tmp_path: Path):
    _check(
        Case(
            "start_recording",
            {"camera_path": "/World/RecCam", "width": 320, "height": 240},
            "/recording/start",
            OLDER_RECORDING,
            {"camera_path": "/World/RecCam", "width": 320, "height": 240},
            (
                "WARNING: this Kit extension records the active viewport, from its camera at its own size: "
                "camera_path /World/RecCam, width 320 and height 240 are ignored.",
                "To record from a camera at a size, install the extension of this server's release, "
                f"{kit_extension.install_advice()}.",
            ),
        ),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize(
    ("args", "says"),
    [
        ({"camera_path": "/World/RecCam"}, "camera_path /World/RecCam is ignored."),
        ({"width": 1920}, ": width 1920 is ignored."),
        ({"width": 640, "height": 720}, ": height 720 is ignored."),
        ({"camera_path": "/World/RecCam", "height": 240}, "camera_path /World/RecCam and height 240 are ignored."),
    ],
)
def test_start_recording_on_an_older_extension_names_each_ignored_parameter_it_was_given(
    args: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    _check(Case("start_recording", args, "/recording/start", OLDER_RECORDING, args, (says,)), bridge, tmp_path)


def test_stop_recording_says_why_frames_stopped_early(bridge: MockIsaacServer, tmp_path: Path):
    note = "frames stopped after 12, at 0.40 s of simulation: the stage changed"
    _check(
        Case(
            "stop_recording",
            {},
            "/recording/stop",
            {"frame_count": 12, "duration_seconds": 1.2, "output_dir": "rec_1", "state_file": None, "note": note},
            {},
            ("Stopped. 12 frames, 1.2s", f"Note: {note}"),
        ),
        bridge,
        tmp_path,
    )


def test_stop_recording_on_an_older_extension_says_what_it_did_before(bridge: MockIsaacServer, tmp_path: Path):
    # 0.3.0's extension answers no simulation_seconds or idle_seconds.
    text = _check(
        Case(
            "stop_recording",
            {},
            "/recording/stop",
            {"frame_count": 3, "duration_seconds": 0.6, "output_dir": "rec_1", "state_file": None},
            {},
            ("Stopped. 3 frames, 0.6s -> ",),
        ),
        bridge,
        tmp_path,
    )
    assert "simulation" not in text


def _logs(msg: str, search: str, bridge: MockIsaacServer, tmp_path: Path, channel: str = "carb") -> str:
    """get_logs' text for one entry of `msg`, found by `search`."""
    args = {"search": search} if search else {}
    entry = {"level": "info", "channel": channel, "msg": msg}
    answer = {"entries": [entry], "count": 1, "total_captured": 9, "buffer_size": 2000}
    return _check(Case("get_logs", args, "/logs", answer, args, ()), bridge, tmp_path)


def test_get_logs_shows_a_match_past_the_cut_with_its_context(bridge: MockIsaacServer, tmp_path: Path):
    # The bridge matches the whole message; the answer showed its first 200 characters, so a hit could show no match
    # at all (#111).
    msg = "x" * 2000 + "OvMcp" + "y" * 540
    text = _logs(msg, "ovmcp", bridge, tmp_path)
    assert f"  [INFO ] carb: {'x' * 200} ... (+2,345 characters)\n" in text
    assert text.endswith(f"\n    matched: ...{'x' * 80}OvMcp{'y' * 80}...")


def test_get_logs_shows_the_whole_line_of_a_callstack_that_holds_the_match(bridge: MockIsaacServer, tmp_path: Path):
    # #111's entry: Kit's deprecation callstack, the match in the bridge's own frame of it, at an invented path here.
    msg = (
        "`get_update_event_stream` is deprecated. Use Events 2.0. Callstack:"
        '   File "C:\\Python312\\Lib\\asyncio\\events.py", line 88, in _run\n'
        "    self._context.run(self._callback, *self._args)\n"
        '  File "c:/users/ada/kit/exts/omniverse-mcp/extension/ovmcp.bridge/ovmcp/bridge/handlers/camera_feed.py", '
        "line 161, in add\n"
        "    stream = omni.kit.app.get_app().get_update_event_stream()\n" + "    more of the callstack\n" * 20
    )
    text = _logs(msg, "MCP", bridge, tmp_path)
    assert f"{msg[:200]} ... (+{len(msg) - 200:,} characters)\n    matched: " in text
    assert text.endswith(
        '\n    matched: File "c:/users/ada/kit/exts/omniverse-mcp/extension/ovmcp.bridge/ovmcp/bridge/handlers/'
        'camera_feed.py", line 161, in add'
    )


@pytest.mark.parametrize(("at", "shown"), [(199, False), (197, True)], ids=["ending past the cut", "ending at it"])
def test_get_logs_counts_a_match_as_shown_only_when_it_ends_within_the_first_200(
    at: int, shown: bool, bridge: MockIsaacServer, tmp_path: Path
):
    # A match from character 199 shows only its first letter (#111's review P3).
    text = _logs("z" * at + "MCP" + "w" * 100, "mcp", bridge, tmp_path)
    assert ("matched:" not in text) == shown
    if not shown:
        assert text.endswith(f"\n    matched: ...{'z' * 80}MCP{'w' * 80}...")


def test_get_logs_marks_a_cut_without_a_search_and_adds_no_match(bridge: MockIsaacServer, tmp_path: Path):
    text = _logs("v" * 201, "", bridge, tmp_path)
    assert text.endswith(f": {'v' * 200} ... (+1 characters)")
    assert "matched:" not in text


def test_get_logs_marks_no_cut_on_a_message_of_200_characters(bridge: MockIsaacServer, tmp_path: Path):
    assert _logs("q" * 200, "q", bridge, tmp_path).endswith(f"  [INFO ] carb: {'q' * 200}")


def test_get_logs_shows_a_channel_whole(bridge: MockIsaacServer, tmp_path: Path):
    # Cut at 40, a channel lost the part that tells modules apart, which the channel filter matches too.
    channel = "isaacsim.core.experimental.utils.impl.transform"
    assert len(channel) > 40
    assert f"  [INFO ] {channel}: a short message" in _logs("a short message", "", bridge, tmp_path, channel)


def test_get_sim_state_says_why_a_recording_s_frames_stopped(bridge: MockIsaacServer, tmp_path: Path):
    note = "frames stopped after 3, at 0.10 s of simulation: the camera is gone: /World/RecCam was deleted"
    _check(
        Case(
            "get_sim_state",
            {},
            "/sim/state",
            {"state": "playing", "recording_active": True, "recording_note": note},
            {},
            (f"recording_note = {note}",),
        ),
        bridge,
        tmp_path,
    )


def test_get_sim_state_reads_an_older_extension_s_missing_kit_app_as_unknown(bridge: MockIsaacServer, tmp_path: Path):
    # An extension from before #105 sends no Kit app: each line says unknown, and a bug report asks the user.
    case = Case(
        "get_sim_state",
        {},
        "/sim/state",
        {"state": "stopped", "up_axis": "Y"},
        {},
        ("kit_app = unknown\nkit_version = unknown\nkit_os = unknown\nextension_version = ",),
    )
    _check(case, bridge, tmp_path)


def _compared(faces_a: int, delta: dict[str, Any]) -> dict[str, Any]:
    """/scene/compare's answer for an A of faces_a faces, with delta as B minus A."""
    side = {
        "label": "/World/A",
        "mesh_count": 1,
        "total_faces": faces_a,
        "total_vertices": 9,
        "total_triangles": 2,
        "bounds_center": [0, 0, 0],
        "bounds_dimensions": [1, 1, 1],
        "materials": [],
    }
    return {"a": side, "b": {**side, "label": "/World/B"}, "delta": delta}


@pytest.mark.parametrize(
    ("faces_a", "delta", "says", "never"),
    [
        # 20.6: a Cube, which has no mesh, to a mesh. The extension's percentage from 0 faces is 0 (#105).
        (
            0,
            {"faces": 4, "face_reduction_pct": 0, "vertices": 9, "triangles": 8, "meshes": 1},
            ("faces: +4 (A has 0 faces)", "vertices: +9  triangles: +8  meshes: +1"),
            "%",
        ),
        # Faces up, vertices down: one sign, the faces', read "+-5" (#105).
        (
            1,
            {"faces": 1, "face_reduction_pct": 100.0, "vertices": -5, "triangles": 0, "meshes": 0},
            ("faces: +1 (+100.0%)", "vertices: -5  triangles: +0  meshes: +0"),
            "+-",
        ),
        # Faces down, vertices up: the rise read without its "+".
        (
            4,
            {"faces": -2, "face_reduction_pct": -50.0, "vertices": 3, "triangles": -4, "meshes": 0},
            ("faces: -2 (-50.0%)", "vertices: +3  triangles: -4  meshes: +0"),
            "+-",
        ),
    ],
    ids=["from-0-faces", "faces-up-vertices-down", "faces-down-vertices-up"],
)
def test_compare_prims_gives_each_delta_its_own_sign_and_no_percentage_from_0_faces(
    faces_a: int, delta: dict[str, Any], says: tuple[str, ...], never: str, bridge: MockIsaacServer, tmp_path: Path
):
    args = {"prim_path_a": "/World/A", "prim_path_b": "/World/B"}
    case = Case("compare_prims", args, "/scene/compare", _compared(faces_a, delta), args, says)
    text = _check(case, bridge, tmp_path)
    assert never not in text.split("=== Delta (B - A) ===")[1]


ROBOT = {"robot_type": "g1", "prim_path": "/World/G1", "usd_path": "g1.usd", "joints": []}
OP = "xformOp:rotateX:unitsResolve"


@pytest.mark.parametrize(
    ("turn", "says"),
    [
        (
            {"file": "Z", "stage": "Y", "degrees": -90.0, "op": -90.0, "op_name": OP},
            f"Turned upright: the file is Z-up and the stage Y-up, so -90° about X went into {OP}, which now reads -90",
        ),
        # A file whose root held Kit's turn: the op reads 0, not the +90 added, and the answer says both (#105, P7).
        (
            {"file": "Y", "stage": "Z", "degrees": 90.0, "op": 0.0, "op_name": OP},
            f"Turned upright: the file is Y-up and the stage Z-up, so +90° about X added to {OP}, which now reads 0",
        ),
    ],
    ids=["new-op", "added-to-the-file-s-op"],
)
def test_create_robot_says_it_stood_the_robot_upright(
    turn: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    case = Case("create_robot", {"robot_type": "g1"}, "/robot/create", {**ROBOT, "up_axis_turn": turn}, {}, (says,))
    _check(case, bridge, tmp_path)


@pytest.mark.parametrize("answer", [ROBOT, {**ROBOT, "up_axis_turn": None}], ids=["older-extension", "no-turn"])
def test_create_robot_says_nothing_of_a_turn_it_didn_t_make(
    answer: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    text = _check(Case("create_robot", {"robot_type": "g1"}, "/robot/create", answer, {}, ()), bridge, tmp_path)
    assert "Turned upright" not in text


SCALE = "xformOp:scale:unitsResolve"
_SCALED = {
    "meters_per_unit": {"file": 1.0, "stage": 0.01},
    "kilograms_per_unit": None,
    "factor": 100.0,
    "op": [100.0, 100.0, 100.0],
    "op_name": SCALE,
    "converted": 12,
    "left": [],
    "left_count": 0,
    "table": True,
}
_CONVERTED = (
    "12 values (masses, inertia, drives, limits, camera distances) were converted to the stage's units, as Kit's "
    "metrics assembler converts them with its physics rules"
)


@pytest.mark.parametrize(
    ("units", "says"),
    [
        (
            _SCALED,
            (
                "Scaled to the stage's units: the file's metersPerUnit is 1 and the stage's 0.01, so a factor of 100 "
                f"went into {SCALE}, which now reads 100; {_CONVERTED}",
            ),
        ),
        # A file whose root held Kit's scale: the op reads 1, not the 0.01 multiplied in, and the answer says both.
        (
            {**_SCALED, "meters_per_unit": {"file": 0.01, "stage": 1.0}, "factor": 0.01, "op": [1.0, 1.0, 1.0]},
            (f"the stage's 1, so a factor of 0.01 was multiplied into {SCALE}, which now reads 1;",),
        ),
        (
            {**_SCALED, "kilograms_per_unit": {"file": 1.0, "stage": 0.001}},
            (
                "the file's metersPerUnit is 1 and the stage's 0.01, and its kilogramsPerUnit is 1 and the stage's "
                "0.001,",
            ),
        ),
        (
            {
                **_SCALED,
                "meters_per_unit": None,
                "kilograms_per_unit": {"file": 0.001, "stage": 1.0},
                "factor": None,
                "op": None,
                "op_name": None,
            },
            (f"Converted to the stage's units: the file's kilogramsPerUnit is 0.001 and the stage's 1; {_CONVERTED}",),
        ),
        (
            {
                **_SCALED,
                "left": [f"/World/Bot/Pad{i}/Shape.physxCollision:contactOffset" for i in range(10)],
                "left_count": 12,
            },
            (
                "12 values stay in the file's units: inside instances, which USD lets no one override, animated by "
                "value clips or splines, or of a type that doesn't multiply: "
                "/World/Bot/Pad0/Shape.physxCollision:contactOffset, ",
                "/World/Bot/Pad9/Shape.physxCollision:contactOffset, and 2 more",
            ),
        ),
        (
            {**_SCALED, "converted": 2, "table": False},
            (
                "; 2 values (camera distances) were converted to the stage's units, as Kit's metrics assembler "
                "converts them with its camera rules",
                "This Kit app has no PhysX schema to read units from, so the robot's physics values stay in the file's "
                "units",
            ),
        ),
        # A held op that isn't uniform, as no Kit writes it: its three values (improvement 5).
        (
            {**_SCALED, "factor": 0.01, "op": [1.0, 2.0, 3.0]},
            (f"so a factor of 0.01 was multiplied into {SCALE}, which now reads (1, 2, 3);",),
        ),
    ],
    ids=["new-op", "held-op", "both-units", "mass-only", "left", "no-table", "held-op-not-uniform"],
)
def test_create_robot_says_it_brought_the_robot_to_the_stage_s_units(
    units: dict[str, Any], says: tuple[str, ...], bridge: MockIsaacServer, tmp_path: Path
):
    case = Case("create_robot", {"robot_type": "g1"}, "/robot/create", {**ROBOT, "units_scale": units}, {}, says)
    _check(case, bridge, tmp_path)


@pytest.mark.parametrize("answer", [ROBOT, {**ROBOT, "units_scale": None}], ids=["older-extension", "same-units"])
def test_create_robot_says_nothing_of_units_it_didn_t_change(
    answer: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    text = _check(Case("create_robot", {"robot_type": "g1"}, "/robot/create", answer, {}, ()), bridge, tmp_path)
    assert "stage's units" not in text
    assert "PhysX schema" not in text


PRIM = {"prim_path": "/World/Box", "type": "Xform"}
_PRIM_ARGS = {"prim_path": "/World/Box", "usd_path": "/props/box.usda"}
_FRAME = {"up_axis": "Z", "meters_per_unit": 1.0, "prims": ["/World/Robot"]}


def test_create_prim_says_it_brought_a_file_to_the_stage_as_create_robot_does(bridge: MockIsaacServer, tmp_path: Path):
    # The same lines as create_robot's, for the same file (#119).
    turn = {"file": "Z", "stage": "Y", "degrees": -90.0, "op": -90.0, "op_name": OP}
    answer = {**PRIM, "up_axis_turn": turn, "units_scale": _SCALED, "frame": None, "not_brought": None}
    says = (
        "Created Xform at /World/Box\n"
        f"Turned upright: the file is Z-up and the stage Y-up, so -90° about X went into {OP}, which now reads -90",
        "Scaled to the stage's units: the file's metersPerUnit is 1 and the stage's 0.01, so a factor of 100 went "
        f"into {SCALE}, which now reads 100; {_CONVERTED}",
    )
    sent = {**_PRIM_ARGS, "prim_type": "Xform"}
    _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, sent, says), bridge, tmp_path)


def test_create_prim_names_the_frame_a_file_lands_in(bridge: MockIsaacServer, tmp_path: Path):
    # A millimetre file under a robot scaled to metres, on a centimetre stage: the scale against the frame, the
    # values against the stage (the plan's P3).
    turn = {"file": "Y", "stage": "Y", "degrees": 90.0, "op": 90.0, "op_name": OP, "frame": "Z"}
    units = {
        **_SCALED,
        "meters_per_unit": {"file": 0.001, "stage": 0.01, "frame": 1.0},
        "factor": 0.001,
        "op": [0.001, 0.001, 0.001],
        "converted": 3,
    }
    answer = {**PRIM, "up_axis_turn": turn, "units_scale": units, "frame": _FRAME, "not_brought": None}
    says = (
        f"Turned upright: the file is Y-up and the frame it lands in Z-up, so +90° about X went into {OP}",
        "Measured against the frame it lands in, not the stage's: /World/Robot's :unitsResolve ops make it Z-up, "
        "in metersPerUnit 1",
        "Scaled to the frame it lands in: the file's metersPerUnit is 0.001 and the frame's 1, so a factor of 0.001 "
        f"went into {SCALE}, which now reads 0.001; 3 values (masses, inertia, drives, limits, camera distances) were "
        "converted to the stage's units, metersPerUnit 0.01, as Kit's metrics assembler converts them",
    )
    _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, {}, says), bridge, tmp_path)


@pytest.mark.parametrize(
    ("units", "says"),
    [
        # The file's units are the frame's, which differ from the stage's: no scale, its values converted.
        (
            {**_SCALED, "meters_per_unit": {"file": 1.0, "stage": 0.01, "frame": 1.0}, "factor": None, "op": None},
            "Converted to the stage's units: the file's metersPerUnit is 1, as the frame it lands in, and the stage's "
            "0.01; 12 values",
        ),
        # The file's units are the stage's, which differ from the frame's: a scale, nothing converted.
        (
            {
                **_SCALED,
                "meters_per_unit": {"file": 1.0, "stage": 1.0, "frame": 0.01},
                "converted": None,
                "table": False,
            },
            f"the file's metersPerUnit is 1 and the frame's 0.01, so a factor of 100 went into {SCALE}, which now "
            "reads 100; its values are in the stage's units already",
        ),
    ],
    ids=["no-scale", "nothing-converted"],
)
def test_create_prim_under_a_frame_says_which_units_differ(
    units: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    answer = {**PRIM, "up_axis_turn": None, "units_scale": units, "frame": _FRAME, "not_brought": None}
    text = _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, {}, (says,)), bridge, tmp_path)
    assert "PhysX schema" not in text


def test_create_prim_on_a_prim_already_there_says_what_the_file_didn_t_get(bridge: MockIsaacServer, tmp_path: Path):
    # The reference stays on the prim: the answer says so and how to take it off before bringing the file elsewhere,
    # or the file would be on the stage twice (review R4).
    missed = {
        "prim_path": "/World/Shelf",
        "file": {"up_axis": "Y", "meters_per_unit": 1.0},
        "frame": {"up_axis": "Z", "meters_per_unit": 0.01},
        "values": {"meters_per_unit": {"file": 1.0, "stage": 0.01}, "kilograms_per_unit": None},
        "reference": "/props/box.usda",
    }
    answer = {**PRIM, "up_axis_turn": None, "units_scale": None, "frame": None, "not_brought": missed}
    says = (
        "Left as the file is: /World/Shelf was there before this call, so the file's reference on it isn't turned or "
        "scaled to the stage (the file Y-up in metersPerUnit 1, the frame inside /World/Shelf Z-up in metersPerUnit "
        "0.01), and leaves its physics values in the file's units (metersPerUnit 1 where the stage's is 0.01). The "
        "reference stays on /World/Shelf: to have the file brought instead, take it off with execute_script, "
        "stage.GetPrimAtPath('/World/Shelf').GetReferences().RemoveReference(Sdf.Reference('/props/box.usda')), then "
        "create_prim at a new path, such as /World/Shelf/Item",
    )
    text = _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, {}, says), bridge, tmp_path)
    assert "delete_prim" not in text


@pytest.mark.parametrize(
    ("missed", "says"),
    [
        # Placed right, its masses left in the file's kilograms (review R2).
        (
            {
                "prim_path": "/World/Crate",
                "file": None,
                "frame": None,
                "values": {"meters_per_unit": None, "kilograms_per_unit": {"file": 0.001, "stage": 1.0}},
                "reference": "/props/crate.usda",
            },
            "so the file's reference on it leaves its physics values in the file's units (kilogramsPerUnit 0.001 "
            "where the stage's is 1). The reference stays on /World/Crate",
        ),
        # A frame turned so that neither axis is up, as a Kit-saved file's own turn leaves it before it is brought.
        (
            {
                "prim_path": "/World/Saved",
                "file": {"up_axis": "Z", "meters_per_unit": 1.0},
                "frame": {"up_axis": None, "meters_per_unit": 100.0},
                "values": None,
                "reference": "/props/saved.usda",
            },
            "the frame inside /World/Saved turned so that neither Y nor Z is up in metersPerUnit 100)",
        ),
    ],
    ids=["values-only", "neither-axis-up"],
)
def test_create_prim_names_what_a_prim_already_there_lacks(
    missed: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    answer = {**PRIM, "up_axis_turn": None, "units_scale": None, "frame": None, "not_brought": missed}
    _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, {}, (says,)), bridge, tmp_path)


@pytest.mark.parametrize(
    "answer",
    [PRIM, {**PRIM, "up_axis_turn": None, "units_scale": None, "frame": None, "not_brought": None}],
    ids=["older-extension", "nothing-to-do"],
)
def test_create_prim_says_nothing_of_a_file_it_left_as_it_is(
    answer: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    text = _check(Case("create_prim", _PRIM_ARGS, "/scene/create", answer, {}, ()), bridge, tmp_path)
    assert text == "Created Xform at /World/Box"


def test_create_robot_names_the_frame_a_robot_lands_in(bridge: MockIsaacServer, tmp_path: Path):
    units = {**_SCALED, "meters_per_unit": {"file": 1.0, "stage": 0.01, "frame": 1.0}, "factor": None, "op": None}
    answer = {**ROBOT, "up_axis_turn": None, "units_scale": units, "frame": _FRAME}
    says = ("Measured against the frame it lands in, not the stage's: /World/Robot's :unitsResolve ops make it Z-up",)
    _check(Case("create_robot", {"robot_type": "g1"}, "/robot/create", answer, {}, says), bridge, tmp_path)


@pytest.mark.parametrize("args", [{}, {"fps": 10}, {"width": 640, "height": 480, "camera_path": ""}])
def test_start_recording_on_an_older_extension_warns_of_nothing_without_a_camera_or_a_size(
    args: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    # The defaults are what every call sends; a warning on each would be noise the model learns to skip.
    bridge.set_response("/recording/start", {"status": "success", "result": OLDER_RECORDING})
    client = BridgeClient(port=bridge.port, token="invented-test-token")
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool("start_recording", args)

        result = asyncio.run(call())
    finally:
        client.close()
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    assert not result.is_error, text
    assert text.startswith("Recording rec_1 at 5fps -> ")
    assert "WARNING" not in text
    assert "Renders into" not in text  # an older extension renders into nothing of its own


def _call(bridge: MockIsaacServer, tmp_path: Path, tool: str, args: dict[str, Any]) -> tuple[bool, str, list]:
    """Calls a tool: whether it erred, its text, and the requests it made beside the handshake."""
    bridge.requests.clear()
    client = BridgeClient(port=bridge.port, token="invented-test-token")
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool(tool, args)

        result = asyncio.run(call())
    finally:
        client.close()
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    return bool(result.is_error), text, [(path, body) for _, path, body in bridge.requests if path != "/bridge"]


@pytest.mark.parametrize(
    ("args", "says"),
    [
        ({"position": [1, 2, 3], "target": [1.0, 2.0, 3.0]}, "is the target"),
        ({"position": [0, 0, 0]}, "is the world origin, which it looks at without a target"),
    ],
)
def test_set_camera_refuses_a_position_on_the_point_it_looks_at(
    args: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    # Isaac Sim's call turns the camera all the same, with nothing to aim at, and answered success (#82).
    erred, text, calls = _call(bridge, tmp_path, "set_camera", args)
    assert erred
    assert says in text
    assert calls == []


def test_set_camera_without_a_target_says_it_looks_at_the_world_origin(bridge: MockIsaacServer, tmp_path: Path):
    # The extension aims at the origin and answers no target, so the answer said nothing of where it looked (#82).
    _check(
        Case(
            "set_camera",
            {"position": [5, 3, 5]},
            "/camera/set",
            {"position": [5, 3, 5], "target": None},
            {"position": [5, 3, 5], "target": None},
            ("Camera at [5, 3, 5] looking at [0, 0, 0], the world origin: no target was given",),
        ),
        bridge,
        tmp_path,
    )


def test_set_camera_frames_a_prim_from_the_angles_left_out(bridge: MockIsaacServer, tmp_path: Path):
    # The prim form (#77): the route that frames a prim, with 45 and 30 degrees for the angles left out.
    _check(
        Case(
            "set_camera",
            {"prim_path": "/World/Cube", "distance": 5.0},
            "/camera/look_at",
            {
                "camera_position": [3.0619, 3.0619, 3.0],
                "target": [0.0, 0.0, 0.5],
                "distance": 5.0,
                "azimuth": 45.0,
                "elevation": 30.0,
            },
            {"prim_path": "/World/Cube", "distance": 5.0, "azimuth": 45.0, "elevation": 30.0},
            (
                "Camera at [3.0619, 3.0619, 3.0] looking at the centre of /World/Cube, [0.0, 0.0, 0.5]\n"
                "Distance: 5.0 stage units, Azimuth: 45.0deg, Elevation: 30.0deg",
            ),
        ),
        bridge,
        tmp_path,
    )


def test_set_camera_sends_the_angles_given_for_a_prim(bridge: MockIsaacServer, tmp_path: Path):
    # 0 is an angle given, not one left out; without a distance, the extension works it out from the prim's size.
    answer = {"camera_position": [0, 4, 0], "target": [0, 0, 0], "distance": 4.0, "azimuth": 0.0, "elevation": 0.0}
    _check(
        Case(
            "set_camera",
            {"prim_path": "/World/Cube", "azimuth": 0, "elevation": 0},
            "/camera/look_at",
            answer,
            {"prim_path": "/World/Cube", "distance": None, "azimuth": 0, "elevation": 0},
            ("Azimuth: 0.0deg, Elevation: 0.0deg",),
        ),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize(
    ("args", "says"),
    [
        ({"prim_path": "/World/Cube", "position": [5, 3, 5]}, "leave position and target out"),
        ({"prim_path": "/World/Cube", "target": [0, 0, 0]}, "get_prim_bounds gives a prim's centre"),
        ({"position": [5, 3, 5], "azimuth": 90}, "distance, azimuth and elevation place the camera around prim_path"),
        ({"position": [5, 3, 5], "elevation": 0}, "give prim_path to frame a prim, or leave them out"),
        ({"distance": 3.0}, "distance, azimuth and elevation place the camera around prim_path"),
        ({}, "give position, where the camera stands, with target, the point it looks at; or prim_path"),
        ({"target": [0, 0, 0]}, "give position, where the camera stands"),
    ],
)
def test_set_camera_refuses_a_mix_of_its_forms_before_any_request(
    args: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    # Each form is chosen by its own parameters (#77): a mix, or neither, says what to drop or give, and moves nothing.
    erred, text, calls = _call(bridge, tmp_path, "set_camera", args)
    assert erred
    assert says in text
    assert calls == []


# A Franka as /robot/info answers it, in invented values of its sizes: 12 joints, 3 of them fixed, so 9 DOF.
FRANKA_JOINTS = [
    *(
        {"name": f"panda_joint{n}", "type": "PhysicsRevoluteJoint", "lower_limit": -166.0, "upper_limit": 166.0}
        | {"drive_angular": {"stiffness": 1000.0, "damping": 100.0}}
        for n in range(1, 8)
    ),
    *(
        {"name": f"panda_finger_joint{n}", "type": "PhysicsPrismaticJoint", "lower_limit": 0.0, "upper_limit": 0.04}
        | {"drive_linear": {"stiffness": 1000.0, "damping": 100.0}}
        for n in (1, 2)
    ),
    *({"name": name, "type": "PhysicsFixedJoint"} for name in ("root_joint", "panda_hand_joint", "panda_tcp_joint")),
]
FRANKA = {
    "prim_path": "/World/Franka",
    "is_articulation": True,
    "dof_count": 9,
    "link_count": 11,
    "joints": FRANKA_JOINTS,
}
HEADER = "Robot: /World/Franka\nArticulation: True\nDOF: 9\nLinks: 11"
STOPPED = (
    "No physics view of /World/Franka: play or step the simulation first; joint states are read while it plays or is "
    "paused. If it already plays, get_logs(min_level='warn') says why Isaac Sim made none."
)


def _states(count: int) -> dict[str, Any]:
    """/robot/joint_states' answer for count degrees of freedom."""
    names = [f"invented_joint{n}" for n in range(count)]
    return {"prim_path": "/World/Franka", "dof_count": count, "names": names, "positions": [0.5] * count}


def _robot(bridge: MockIsaacServer, info: dict[str, Any], states: dict[str, Any]) -> None:
    bridge.set_response("/robot/info", {"status": "success", "result": info})
    bridge.set_response("/robot/joint_states", states)


def _written(text: str, tmp_path: Path) -> str:
    """The one robot_info file the answer names, read."""
    (path,) = (tmp_path / "responses").glob("robot_info_*.txt")
    assert path.name in text
    return path.read_text(encoding="utf-8")


def test_get_robot_info_gives_the_structure_and_why_there_are_no_joint_states(bridge: MockIsaacServer, tmp_path: Path):
    # Stopped, or without Isaac Sim: the joint states' route errs, and the structure still answers (#77).
    info = {**FRANKA, "dof_count": 1, "joints": FRANKA_JOINTS[:1]}
    _robot(bridge, info, {"status": "error", "error": STOPPED})
    erred, text, calls = _call(bridge, tmp_path, "get_robot_info", {"prim_path": "/World/Franka"})
    assert not erred, text
    assert calls == [
        ("/robot/info", {"prim_path": "/World/Franka"}),
        ("/robot/joint_states", {"prim_path": "/World/Franka"}),
    ]
    assert text == (
        "Robot: /World/Franka\nArticulation: True\nDOF: 1\nLinks: 11\nJoints (1):\n"
        f"  panda_joint1 (PhysicsRevoluteJoint [-166.0, 166.0] drive=angular)\nJoint states: not read: {STOPPED}"
    )


def test_get_robot_info_fails_on_its_structure_without_asking_the_joint_states(bridge: MockIsaacServer, tmp_path: Path):
    bridge.set_response("/robot/info", {"status": "error", "error": "Prim not found: /World/Nothing"})
    erred, text, calls = _call(bridge, tmp_path, "get_robot_info", {"prim_path": "/World/Nothing"})
    assert erred
    assert "Prim not found: /World/Nothing" in text
    assert [path for path, _ in calls] == ["/robot/info"]


class _GoneAfterTheStructure(BridgeClient):
    """Kit stops answering between get_robot_info's two requests."""

    def get_joint_states(self, prim_path: str) -> dict[str, Any]:
        raise ConnectionError("Connection closed by the ovmcp.bridge extension")


def test_get_robot_info_fails_when_kit_goes_before_the_joint_states(bridge: MockIsaacServer, tmp_path: Path):
    # A route's error is a line of the answer; a Kit that can't be reached fails the call, as for every tool.
    bridge.set_response("/robot/info", {"status": "success", "result": FRANKA})
    client = _GoneAfterTheStructure(port=bridge.port, token="invented-test-token")
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool("get_robot_info", {"prim_path": "/World/Franka"})

        result = asyncio.run(call())
    finally:
        client.close()
    text = "\n".join(getattr(c, "text", "") for c in result.content)
    assert result.is_error
    assert "Kit app connection failed: Connection closed by the ovmcp.bridge extension" in text


@pytest.mark.parametrize(
    ("states", "inline"),
    [
        ({"status": "error", "error": STOPPED}, f"Joint states: not read: {STOPPED}"),
        (
            {"status": "success", "result": _states(9)},
            "Joint states (9 DOF, from physics: radians for revolute joints, stage units for prismatic ones, "
            "velocities per second; set_joint_targets takes degrees):\n  invented_joint0: pos=0.5000 vel=0.0000",
        ),
    ],
    ids=["stopped", "playing"],
)
def test_a_franka_s_joints_go_to_a_file_and_its_joint_states_stay_inline(
    states: dict[str, Any], inline: str, bridge: MockIsaacServer, tmp_path: Path
):
    # Each old tool answered a Franka inline; together they pass 1,000 characters (#77, P3): the header and the joint
    # states, what a caller came for, stay inline, and the Joints list goes to a file.
    _robot(bridge, FRANKA, states)
    erred, text, _calls = _call(bridge, tmp_path, "get_robot_info", {"prim_path": "/World/Franka"})
    assert not erred, text
    lines = text.splitlines()
    assert "\n".join(lines[:4]) == HEADER
    assert lines[4].startswith("Wrote the 12 joints (")
    assert "\n".join(lines[5:]).startswith(inline)
    assert "panda_joint1" not in text
    joints = _written(text, tmp_path)
    assert joints.startswith("Joints (12):\n  panda_joint1 (PhysicsRevoluteJoint [-166.0, 166.0] drive=angular)\n")
    assert joints.endswith("\n  panda_tcp_joint (PhysicsFixedJoint)")


def test_joint_states_too_long_to_answer_inline_go_to_the_file_after_the_joints(
    bridge: MockIsaacServer, tmp_path: Path
):
    # A G1's 43 degrees of freedom pass 1,000 characters with the header alone.
    _robot(bridge, FRANKA, {"status": "success", "result": _states(43)})
    erred, text, _calls = _call(bridge, tmp_path, "get_robot_info", {"prim_path": "/World/Franka"})
    assert not erred, text
    lines = text.splitlines()
    assert "\n".join(lines[:4]) == HEADER
    assert lines[4].startswith("Wrote the 12 joints, then the joint states (")
    assert len(lines) == 5
    written = _written(text, tmp_path)
    assert written.startswith("Joints (12):\n")
    assert "\n  panda_tcp_joint (PhysicsFixedJoint)\nJoint states (43 DOF, " in written
    assert written.endswith("\n  invented_joint42: pos=0.5000 vel=0.0000")


DUMPED = {"prim_count": 12, "file_size_bytes": 4096, "file_path": "scene_dump.txt", "root": "/World"}


def test_get_scene_tree_with_properties_has_kit_write_them_to_a_file(bridge: MockIsaacServer, tmp_path: Path):
    # The dump's job, merged into get_scene_tree (#77): 15 levels when max_depth is left out, as the dump took.
    _check(
        Case(
            "get_scene_tree",
            {"root": "/World", "include_properties": True},
            "/scene/dump",
            DUMPED,
            {"output_dir": OUTPUT, "root": "/World", "max_depth": 15, "include_properties": True},
            ("Dumped 12 prims under /World, to depth 15 (4,096 bytes) -> ",),
        ),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize(
    ("args", "sent"),
    [
        # A filter alone writes the file too; only values asked for bring the attributes.
        ({"filter_types": ["Mesh"]}, {"filter_types": ["Mesh"], "include_properties": False}),
        ({"property_filter": ["joint"]}, {"property_filter": ["joint"], "include_properties": True}),
        (
            {"filter_types": ["Mesh"], "property_filter": ["joint"], "max_depth": 3},
            {"filter_types": ["Mesh"], "property_filter": ["joint"], "include_properties": True, "max_depth": 3},
        ),
    ],
)
def test_get_scene_tree_with_a_filter_has_kit_write_the_file(
    args: dict[str, Any], sent: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    _check(
        Case("get_scene_tree", args, "/scene/dump", DUMPED, sent, ("Dumped 12 prims under /, to depth ",)),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize(
    "args",
    [{"filter_types": []}, {"property_filter": []}, {"include_properties": False, "filter_types": [], "max_depth": 5}],
)
def test_get_scene_tree_with_an_empty_filter_lists(args: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path):
    # An empty list asks for nothing, so the answer is the list, not a file.
    _check(
        Case("get_scene_tree", args, "/scene/tree", {"text": "[/]\n"}, {"max_depth": 5, "format": "text"}, ("[/]",)),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize("route", ["/scene/tree", "/scene/dump"])
def test_get_scene_tree_takes_any_depth(route: str, bridge: MockIsaacServer, tmp_path: Path):
    # The list refused a max_depth over 15, the old server's quiet cap made a bound; the dump took any (#77).
    args: dict[str, Any] = {"max_depth": 20, **({"include_properties": True} if route == "/scene/dump" else {})}
    answer = DUMPED if route == "/scene/dump" else {"text": "[/]\n"}
    _check(Case("get_scene_tree", args, route, answer, {"max_depth": 20}, ()), bridge, tmp_path)


MESH_TOTALS = {
    "prim_path": "/World/Robot",
    "mesh_count": 1,
    "total_faces": 6,
    "total_vertices": 8,
    "total_triangles": 12,
}


def _mesh_stats(bridge: MockIsaacServer, tmp_path: Path, tree: str, args: dict[str, Any]) -> tuple[str, list]:
    bridge.set_response("/scene/mesh_stats", {"status": "success", "result": MESH_TOTALS})
    bridge.set_response("/scene/face_count_tree", {"status": "success", "result": {"text": tree}})
    erred, text, calls = _call(bridge, tmp_path, "get_mesh_stats", {"prim_path": "/World/Robot", **args})
    assert not erred, text
    return text, calls


@pytest.mark.parametrize(("args", "depth"), [({}, 2), ({"max_depth": 0}, 0), ({"max_depth": 20}, 20)])
def test_get_mesh_stats_asks_the_totals_then_the_tree_from_its_prim(
    args: dict[str, Any], depth: int, bridge: MockIsaacServer, tmp_path: Path
):
    # The tree's route takes the prim as its root, 2 levels when max_depth is left out, where the tree's tool took 10.
    text, calls = _mesh_stats(bridge, tmp_path, TREE, args)
    assert calls == [
        ("/scene/mesh_stats", {"prim_path": "/World/Robot"}),
        ("/scene/face_count_tree", {"root": "/World/Robot", "max_depth": depth}),
    ]
    # The tree's total counts only the meshes within max_depth, and would contradict the totals above it.
    assert "# total:" not in text
    assert text.endswith("\ntriangles = 12")


@pytest.mark.parametrize(
    "tree",
    [
        "[/World/Robot]\ntype = Xform\nsubtree_faces = 6",
        "[/World/Robot]\ntype = Xform\n# total: 6 faces, a line that isn't the last\nsubtree_faces = 6\n",
    ],
)
def test_get_mesh_stats_keeps_a_tree_that_doesnt_end_with_its_total(tree: str, bridge: MockIsaacServer, tmp_path: Path):
    text, _calls = _mesh_stats(bridge, tmp_path, tree, {})
    assert text.endswith(f"\n\n{tree.rstrip()}")


def test_get_mesh_stats_writes_a_tree_too_long_to_give_with_the_totals(bridge: MockIsaacServer, tmp_path: Path):
    # Under 1,000 characters alone, over them with the totals: the tree goes to a file, the totals stay inline.
    tree = "\n\n".join(f"[/World/Robot/Part{n:02d}]\ntype = Mesh\nfaces = 6" for n in range(21))
    assert 900 < len(tree) <= 1000
    text, _calls = _mesh_stats(bridge, tmp_path, f"{tree}\n\n# total: 126 faces in 21 meshes", {})
    totals, wrote = text.split("\n\n")
    assert totals == "[/World/Robot]\nmeshes = 1\ntotal_faces = 6\ntotal_vertices = 8\ntotal_triangles = 12"
    assert wrote.startswith("Wrote the face count tree to depth 2 (")
    (path,) = (tmp_path / "responses").glob("mesh_stats_*.txt")
    assert wrote.endswith(path.name)
    assert path.read_text(encoding="utf-8") == tree


@pytest.mark.parametrize(
    "session_dir",
    [r"C:\Users\me\rec_1", r"\\host\share\rec_1", "/home/me/rec_1", "C:/Users/me/rec_1"],
)
def test_get_recording_frame_sends_an_absolute_session_dir_as_given(
    session_dir: str, bridge: MockIsaacServer, tmp_path: Path
):
    # Rooted in either OS's form: a Kit app on another OS keeps its own paths.
    bridge.set_response("/recording/frame", {"status": "success", "result": {"frame_index": 0, "image_base64": PNG}})
    erred, text, calls = _call(bridge, tmp_path, "get_recording_frame", {"session_dir": session_dir})
    assert not erred, text
    assert calls[0][1]["session_dir"] == session_dir


def test_get_recording_frame_reads_a_relative_session_dir_from_the_servers_folder(
    bridge: MockIsaacServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # start_recording and stop_recording print the folder relative to the server's working folder; Kit read it
    # from its own and answered "Frame not found" (#82).
    monkeypatch.chdir(tmp_path)
    bridge.set_response("/recording/frame", {"status": "success", "result": {"frame_index": 0, "image_base64": PNG}})
    erred, text, calls = _call(bridge, tmp_path, "get_recording_frame", {"session_dir": "mcp_output/recordings/rec_1"})
    assert not erred, text
    assert Path(calls[0][1]["session_dir"]) == tmp_path / "mcp_output" / "recordings" / "rec_1"


def test_raycast_sends_its_direction_as_a_unit_vector(bridge: MockIsaacServer, tmp_path: Path):
    bridge.set_response("/physics/raycast", {"status": "success", "result": {"hit": False}})
    erred, text, calls = _call(bridge, tmp_path, "raycast", {"origin": [0, 0, 5], "direction": [0, 3, -4]})
    assert not erred, text
    assert calls[0][1]["direction"] == pytest.approx([0, 0.6, -0.8])


@pytest.mark.parametrize("direction", [[0, 0, 0], [0, 0, -1, 0]])
def test_raycast_refuses_a_direction_it_cant_cast_along(
    direction: list[float], bridge: MockIsaacServer, tmp_path: Path
):
    erred, text, calls = _call(bridge, tmp_path, "raycast", {"origin": [0, 0, 5], "direction": direction})
    assert erred
    assert "direction" in text
    assert calls == []


@pytest.mark.parametrize(("answer", "warns"), [({"checked": True}, False), ({"message": "Prim deleted"}, True)])
def test_delete_prim_warns_when_the_extension_made_no_check(
    answer: dict[str, Any], warns: bool, bridge: MockIsaacServer, tmp_path: Path
):
    # A 0.2.3 extension answers "deleted" for a prim another layer keeps, and the plugin updates the server first.
    bridge.set_response("/scene/delete", {"status": "success", "result": {"prim_path": "/World/Cube", **answer}})
    erred, text, _calls = _call(bridge, tmp_path, "delete_prim", {"prim_path": "/World/Cube"})
    assert not erred, text
    assert text.startswith("Deleted /World/Cube")
    assert ("check with get_scene_tree" in text) is warns


def test_set_material_says_its_opacity_when_it_is_1(bridge: MockIsaacServer, tmp_path: Path):
    # A recolour now makes a see-through material opaque (#82), and the answer says so.
    answer = {
        "prim_path": "/World/Cube",
        "material_path": "/World/Looks/Cube_Mat",
        "color": [0, 1, 0],
        "opacity": 1.0,
        "roughness": 0.5,
        "metallic": 0.0,
    }
    bridge.set_response("/scene/material", {"status": "success", "result": answer})
    erred, text, _calls = _call(bridge, tmp_path, "set_material", {"prim_path": "/World/Cube", "color": [0, 1, 0]})
    assert not erred, text
    assert "opacity=1.0" in text


@pytest.mark.parametrize("scale", [1e-200, 1e200, 1.0])
def test_a_tiny_or_huge_direction_is_still_scaled_to_length_1(scale: float):
    # Squaring underflowed [1e-200, 0, 0] to a length of 0 and overflowed [1e200, 0, 0] to inf.
    assert _unit([3 * scale, 0, -4 * scale]) == pytest.approx([0.6, 0, -0.8])


@pytest.mark.parametrize("direction", [[math.nan, 0, 1], [math.inf, 0, 0], [1.7e308, 1.7e308, 1.7e308]])
def test_a_direction_with_no_finite_length_is_refused(direction: list[float]):
    with pytest.raises(ToolError, match="direction"):
        _unit(direction)
