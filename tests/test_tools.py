"""Every tool once, through SDK v2's in-memory MCP client against the mock bridge: the route it calls, what it sends,
and the text the model reads back from a canned answer. tests/test_contract.py pins what the tools accept; this pins
what they do with it."""

import asyncio
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import golden
import pytest
from mcp import Client

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.server import create_server

from .mock_bridge import MockIsaacServer

HANDSHAKE = {"status": "success", "result": {"protocol": 1, "extension_version": "1.0.0"}}
# The 8-byte PNG signature: enough for the server, which writes the bytes as they come.
PNG = "iVBORw0KGgo="
# Stands for the server's output folder in what a case expects sent: each test has its own.
OUTPUT = "<output>"


@dataclass(frozen=True)
class Case:
    tool: str
    args: dict[str, Any]
    route: str
    answer: dict[str, Any]
    sent: dict[str, Any]  # what the request body must hold, at least
    says: tuple[str, ...]  # what the tool's text must hold

    def __str__(self) -> str:
        return self.tool


CASES = [
    # Scene
    Case(
        "get_scene_tree",
        {"root": "/World", "max_depth": 2},
        "/scene/tree",
        {"text": "[/World]\ntype = Xform\n"},
        {"root": "/World", "max_depth": 2, "format": "text"},
        ("[/World]", "type = Xform"),
    ),
    Case(
        "dump_scene",
        {"filter_types": ["Mesh"], "property_filter": ["joint"]},
        "/scene/dump",
        {"prim_count": 12, "file_size_bytes": 4096, "file_path": "scene_dump.txt"},
        {"output_dir": OUTPUT, "filter_types": ["Mesh"], "property_filter": ["joint"], "include_properties": True},
        ("Dumped 12 prims (4,096 bytes)",),
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
        {},
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
    Case("new_scene", {}, "/scene/new", {}, {}, ("New scene created",)),
    # Geometry and USD
    Case(
        "get_mesh_stats",
        {"prim_path": "/World/Mesh"},
        "/scene/mesh_stats",
        {
            "prim_path": "/World/Mesh",
            "mesh_count": 1,
            "total_faces": 6,
            "total_vertices": 8,
            "total_triangles": 12,
            "meshes": [{"path": "/World/Mesh", "faces": 6, "vertices": 8, "triangles": 12}],
        },
        {"prim_path": "/World/Mesh"},
        ("total_faces = 6", "faces = 6, vertices = 8, triangles = 12"),
    ),
    Case(
        "get_prim_face_count_tree",
        {"root": "/World", "max_depth": 0},
        "/scene/face_count_tree",
        {"text": "[/World]\nsubtree_faces = 6\n"},
        {"root": "/World", "max_depth": 0},
        ("subtree_faces = 6",),
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
        ("DOF: 1", "joint1 (RevoluteJoint [-1.0, 1.0] drive=angular)"),
    ),
    Case(
        "get_joint_states",
        {"prim_path": "/World/Franka"},
        "/robot/joint_states",
        {"prim_path": "/World/Franka", "dof_count": 1, "names": ["joint1"], "positions": [0.5], "velocities": [0.25]},
        {"prim_path": "/World/Franka"},
        ("joint1: pos=0.5000 vel=0.2500",),
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
        "look_at_prim",
        {"prim_path": "/World/Cube", "distance": 5.0},
        "/camera/look_at",
        {"camera_position": [3, 2, 3], "target": [0, 0, 0], "distance": 5.0, "azimuth": 45.0, "elevation": 30.0},
        {"prim_path": "/World/Cube", "distance": 5.0},
        ("Distance: 5.0m, Azimuth: 45.0deg, Elevation: 30.0deg",),
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
        ("Inspect /World/Cube (dist=2.5m, zoom_offset=-0.3)", "top: ERROR invented failure"),
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
        {"state": "stopped", "up_axis": "Z", "sim_time": 0.0, "fps": 60.0, "prim_count": 3, "meters_per_unit": 1.0},
        {},
        # The mock bridge's handshake answers extension 1.0.0, another release than this server's.
        ("state = stopped", "up_axis = Z", "extension_version = 1.0.0", "note = the Kit extension is 1.0.0"),
    ),
    Case(
        "set_physics_properties",
        {"prim_path": "/World/Cube", "mass": 0, "friction": 0.4},
        "/physics/properties",
        {"prim_path": "/World/Cube", "applied": ["MassAPI", "PhysicsMaterialAPI"]},
        {"prim_path": "/World/Cube", "mass": 0, "friction": 0.4},
        ("Physics on /World/Cube: MassAPI, PhysicsMaterialAPI",),
    ),
    Case(
        "apply_force",
        {"prim_path": "/World/Cube", "force": [0, 0, 10], "impulse": True},
        "/physics/apply_force",
        {"prim_path": "/World/Cube", "force": [0, 0, 10], "impulse": True, "method": "physx"},
        {"prim_path": "/World/Cube", "force": [0, 0, 10], "impulse": True},
        ("Applied impulse [0, 0, 10] to /World/Cube (method: physx)",),
    ),
    Case(
        "raycast",
        {"origin": [0, 0, 5], "direction": [0, 0, -1]},
        "/physics/raycast",
        {"hit": True, "prim_path": "/World/Ground", "position": [0, 0, 0], "normal": [0, 0, 1], "distance": 5.0},
        {"origin": [0, 0, 5], "direction": [0, 0, -1], "max_distance": 1000.0},
        ("Hit: /World/Ground", "Distance: 5.0000m"),
    ),
    Case(
        "draw_debug",
        {"shape": "lines", "points": [[0, 0, 0], [0, 0, 1]], "size": 0.1},
        "/debug/draw",
        {"drawn": [{"type": "lines", "segments": 1}]},
        {"type": "lines", "points": [[0, 0, 0], [0, 0, 1]], "size": 0.1},
        ("Drew 1 debug element(s): lines",),
    ),
    # Recording
    Case(
        "start_recording",
        {"fps": 10, "track_prims": ["/World/G1"]},
        "/recording/start",
        {"session_id": "rec_1", "fps": 10, "output_dir": "rec_1", "track_prims": ["/World/G1", "/World/G1/base"]},
        {"output_dir": str(Path(OUTPUT) / "recordings"), "fps": 10, "track_prims": ["/World/G1"]},
        ("Recording rec_1 at 10fps", "Tracking 2 prims"),
    ),
    Case(
        "stop_recording",
        {},
        "/recording/stop",
        {"frame_count": 3, "duration_seconds": 0.6, "output_dir": "rec_1", "state_file": "rec_1/state.txt"},
        {},
        ("Stopped. 3 frames, 0.6s", "State: rec_1/state.txt"),
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


def _check(case: Case, bridge: MockIsaacServer, tmp_path: Path) -> None:
    bridge.set_response(case.route, {"status": "success", "result": case.answer})
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
    assert [path for path, _ in calls] == [case.route]
    body = calls[0][1]
    sent = {k: v.replace(OUTPUT, str(tmp_path)) if isinstance(v, str) else v for k, v in case.sent.items()}
    assert {k: body.get(k) for k in sent} == sent
    for part in case.says:
        assert part in text


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


def test_get_sim_state_says_nothing_more_when_the_extension_is_this_release(bridge: MockIsaacServer, tmp_path: Path):
    release = version("omniverse-mcp")
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
    assert f"extension_version = {release}\nserver_version = {release}" in text
    assert "note = " not in text
