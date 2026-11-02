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
from omniverse_mcp.client import BridgeClient, KitSilentError
from omniverse_mcp.server import create_server
from omniverse_mcp.tools.misc import duration
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


# /sim/performance's answer for a playing stage with two robots' sensors on, as the extension sends it: 240 frames of
# 44.6 ms take 10.70 s, and fixed time steps of 1/60 s at the scene's 120 steps a second carry 2 steps each, 480 steps
# that simulate 4.00 s.
PERFORMANCE: dict[str, Any] = {
    "frames": 240,
    "warmup": 60,
    "measured_frames": 240,
    "app": {"fps": 22.42, "mean_ms": 44.6, "p50_ms": 43.9, "p95_ms": 51.2, "worst_ms": 63.0},
    "halves": {"first_ms": 44.9, "second_ms": 44.3, "settled": True},
    "gpu_render": {"mean_ms": 31.2, "p95_ms": 36.0},
    "physics": {
        "steps_per_second": 120.0,
        "steps": 480,
        "steps_per_frame": 2.0,
        "step_ms": 6.1,
        "frame_ms": 12.2,
        "simulated_seconds": 4.0,
        "wall_seconds": 10.704,
        "ratio": 0.3737,
    },
    "gpu_memory": {
        "device": "NVIDIA RTX 6000 Pro",
        "used_bytes": int(14.2 * 2**30),
        "total_bytes": 48 * 2**30,
        "total_kind": "dedicated",
    },
    "stage": {
        "prims": 18342,
        "meshes": 2210,
        "instances": 9120,
        "prototypes": 41,
        "point_instancers": 2,
        "point_instances": 50000,
    },
    "render_products": [
        *({"path": f"/Render/Lidar{i}", "kind": "lidar", "resolution": [1024, 1024]} for i in range(2)),
        *({"path": f"/Render/Cam{i}", "kind": "camera", "resolution": [1280, 720]} for i in range(4)),
    ],
    "conditions": {
        "gpu": "NVIDIA RTX 6000 Pro",
        "kit_app_name": "Isaac-Sim Python",
        "kit_app_version": "6.2.0",
        "kit_version": "110.4.0",
        "kit_os": "Linux-6.8.0-x86_64-with-glibc2.39",
        "renderer": "rtx",
        "render_mode": "RaytracedLighting",
        "timeline": "playing",
        "headless": True,
        "fixed_time_stepping": True,
        "time_codes_per_second": 60.0,
        "rate_limit": True,
        "rate_limit_frequency": 60,
        "rate_limit_lifted": True,
        "async_rendering": False,
        "eco_mode": False,
        "sleep_ms_on_focus": 0,
        "sleep_ms_out_of_focus": 0,
    },
    "notes": [],
}


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
        {"text": "[/World/Cube]\ntype = Cube\napi_schemas = []\nvariant_sets = []\n"},
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
        "set_prim_attribute",
        {"prim_path": "/World/Sun", "name": "inputs:intensity", "value": 3000},
        "/scene/attribute",
        {
            "prim_path": "/World/Sun",
            "name": "inputs:intensity",
            "type": "float",
            "before": "50000",
            "after": "3000",
            "layer": "the stage's root layer",
        },
        {"prim_path": "/World/Sun", "name": "inputs:intensity", "value": 3000, "layer": "auto"},
        ("[/World/Sun]\ninputs:intensity = 3000 (float; was 50000)\nwritten to the stage's root layer",),
    ),
    Case(
        "save_scene",
        {"file_path": "scene.usd"},
        "/scene/save",
        {"action": "save_as", "file_path": "scene.usd", "session_selections": []},
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
    Case(
        "new_scene",
        {},
        "/scene/new",
        {"message": "New scene created", "default_prim": "/World", "up_axis": "Z", "meters_per_unit": 1.0},
        {"up_axis": "Z", "meters_per_unit": 1.0},
        ("New scene created with /World root prim\nup_axis = Z\nmeters_per_unit = 1.0",),
    ),
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
            "layer": "session",
            "written_to": "Kit's session layer",
            "files_select": "full",
        },
        {"prim_path": "/World/Asset", "variant_set": "model", "variant_name": "shell", "layer": "session"},
        (
            "Variant switched in the session layer: /World/Asset model=shell (the files select full; save_scene "
            "leaves it out of the file)\nWas: full. Available: full, shell",
        ),
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
        "get_performance",
        {"frames": 240, "warmup": 60},
        "/sim/performance",
        PERFORMANCE,
        {"frames": 240, "warmup": 60},
        (
            "app = 22.4 FPS (frame time mean 44.6 ms, p50 43.9, p95 51.2, worst 63.0) over 240 frames after 60\n"
            "settled = first half 44.9 ms, second half 44.3 ms\n"
            "gpu_render = mean 31.2 ms, p95 36.0\n"
            "physics = 120 steps a simulated second, 2.0 steps a frame, 6.1 ms a step (12.2 ms a frame); simulated "
            "4.00 s in 10.70 s (0.37 of real time)\n"
            "gpu_memory = 14.2 GiB used of 48.0 GiB of dedicated video memory (Hydra's figures for device 0, NVIDIA "
            "RTX 6000 Pro)\n"
            "stage = 18342 prims, 2210 meshes, 9120 instances of 41 prototypes, 50000 point instances in 2 point "
            "instancers\n"
            "render_products = 6: 2 lidars at 1024x1024, 4 cameras at 1280x720\n"
            "conditions = NVIDIA RTX 6000 Pro, Isaac-Sim Python 6.2.0 (Kit 110.4.0), renderer rtx (RaytracedLighting), "
            "playing, headless, fixed time steps of 1/60 s; rate limit lifted for the measurement (it was on at 60 "
            "Hz); async rendering off, eco mode off",
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
            "render_product": "/Render/OmniverseKit/HydraTextures/ovmcp_feed_0",
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
    # Jobs (#158)
    Case(
        "run_script_job",
        {"code": "await bake()"},
        "/jobs/script",
        {"id": "j3", "kind": "script", "label": "await bake()"},
        {"code": "await bake()"},
        ('Job j3 started (script); read it with get_job("j3")',),
    ),
    Case(
        "get_job",
        {"job_id": "j3", "wait": 60},
        "/jobs/get",
        {
            "id": "j3",
            "kind": "script",
            "label": "D:/bakes/bake.py",
            "state": "working",
            "message": "",
            "elapsed": 252.4,
            "lines": ["36 of 150 stacks settled", "37 of 150 stacks settled"],
            "lines_new": 2,
            "lines_total": 37,
            "last": "37 of 150 stacks settled",
        },
        {"job_id": "j3", "wait": 60},
        (
            "job = j3 (script)\nlabel = D:/bakes/bake.py\nstate = working\nelapsed = 4m 12s\n"
            "last = 37 of 150 stacks settled\n"
            "lines = 37 printed, 2 since the last read:\n  36 of 150 stacks settled\n  37 of 150 stacks settled",
        ),
    ),
    Case(
        "cancel_job",
        {"job_id": "j3"},
        "/jobs/cancel",
        {"id": "j3", "kind": "script", "state": "cancelling", "was": "working", "message": "cancel_job was called"},
        {"job_id": "j3"},
        (
            "Job j3 cancelled at its next await: it reads cancelling until its cleanup has run; read it with "
            'get_job("j3", wait=10)',
        ),
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


def test_set_prim_attribute_gives_the_extent_it_moved(bridge: MockIsaacServer, tmp_path: Path):
    text = _check(
        Case(
            "set_prim_attribute",
            {"prim_path": "/World/Ball", "name": "radius", "value": 5},
            "/scene/attribute",
            {
                "prim_path": "/World/Ball",
                "name": "radius",
                "type": "double",
                "before": "1",
                "after": "5",
                "layer": "the stage's root layer",
                "extent": "(-5.0000, -5.0000, -5.0000), (5.0000, 5.0000, 5.0000)",
            },
            {"prim_path": "/World/Ball", "name": "radius", "value": 5},
            (
                "extent updated to (-5.0000, -5.0000, -5.0000), (5.0000, 5.0000, 5.0000), so get_prim_bounds gives "
                "the new size",
            ),
        ),
        bridge,
        tmp_path,
    )
    assert text.splitlines()[1] == "radius = 5 (double; was 1)"


def test_set_prim_attribute_sends_a_colour_list_and_gives_a_token_s_note(bridge: MockIsaacServer, tmp_path: Path):
    _check(
        Case(
            "set_prim_attribute",
            {"prim_path": "/World/Cube", "name": "primvars:displayColor", "value": [[1, 0, 0]]},
            "/scene/attribute",
            {
                "prim_path": "/World/Cube",
                "name": "primvars:displayColor",
                "type": "color3f[]",
                "before": "null",
                "after": "(1.0000, 0.0000, 0.0000)",
                "layer": "the stage's root layer",
            },
            {"prim_path": "/World/Cube", "name": "primvars:displayColor", "value": [[1.0, 0.0, 0.0]]},
            ("primvars:displayColor = (1.0000, 0.0000, 0.0000) (color3f[]; was null)",),
        ),
        bridge,
        tmp_path,
    )
    _check(
        Case(
            "set_prim_attribute",
            {"prim_path": "/World/Rock", "name": "physics:approximation", "value": "sdf"},
            "/scene/attribute",
            {
                "prim_path": "/World/Rock",
                "name": "physics:approximation",
                "type": "token",
                "before": "none",
                "after": "sdf",
                "layer": "the stage's root layer",
                "note": "sdf isn't among physics:approximation's allowed tokens (none, convexHull); written as given",
            },
            {"prim_path": "/World/Rock", "name": "physics:approximation", "value": "sdf"},
            ("note: sdf isn't among",),
        ),
        bridge,
        tmp_path,
    )


@pytest.mark.parametrize(("value", "kind"), [(3000, int), (True, bool), (1.5, float), ("sdf", str)])
def test_set_prim_attribute_keeps_the_value_s_json_type(bridge: MockIsaacServer, tmp_path: Path, value, kind):
    # The extension refuses 1 for a bool and true for an int, so each type must survive the schema's union.
    answer = {"prim_path": "/World/A", "name": "my:v", "type": "x", "before": "0", "after": "1", "layer": "root"}
    bridge.set_response("/scene/attribute", {"status": "success", "result": answer})

    erred, text, calls = _call(
        bridge, tmp_path, "set_prim_attribute", {"prim_path": "/World/A", "name": "my:v", "value": value}
    )

    assert not erred, text
    (body,) = [b for path, b in calls if path == "/scene/attribute"]
    assert type(body["value"]) is kind
    assert body["value"] == value


def test_set_prim_attribute_keeps_whole_numbers_whole_inside_a_list(bridge: MockIsaacServer, tmp_path: Path):
    # An int64[] value past 2**53 would lose its last digits as a float; a bool inside a list stays a bool.
    answer = {"prim_path": "/World/A", "name": "my:ids", "type": "int64[]", "before": "[]", "after": "1", "layer": "x"}
    bridge.set_response("/scene/attribute", {"status": "success", "result": answer})
    value = [9007199254740993, 2, True, [1, 0]]

    erred, text, calls = _call(
        bridge, tmp_path, "set_prim_attribute", {"prim_path": "/World/A", "name": "my:ids", "value": value}
    )

    assert not erred, text
    (body,) = [b for path, b in calls if path == "/scene/attribute"]
    assert body["value"] == value
    assert [type(v) for v in body["value"][:3]] == [int, int, bool]


def _variant_answer(**changed: Any) -> dict[str, Any]:
    return {
        "prim_path": "/World/Area",
        "variant_set": "state",
        "old_selection": "closed",
        "new_selection": "open",
        "available_variants": ["closed", "open"],
        "layer": "session",
        "written_to": "Kit's session layer",
        "files_select": "closed",
        **changed,
    }


_INSTANCE_NOTE = "/World/Area is an instance: a selection of its own gives it a prototype of its own"


@pytest.mark.parametrize(
    ("args", "answer", "says"),
    [
        (
            {"layer": "edit_target"},
            _variant_answer(layer="edit_target", written_to="the stage's root layer (C:/site.usda)"),
            "Variant switched at the edit target, the stage's root layer (C:/site.usda): /World/Area state=open (the "
            "files beneath select closed; save_scene writes it into the file)",
        ),
        (
            # A sublayer made the edit target in Kit's Layer window, which save_scene, writing the root layer, never
            # saves.
            {"layer": "edit_target"},
            _variant_answer(layer="edit_target", written_to="C:/scene/props.usda"),
            "Variant switched at the edit target, C:/scene/props.usda: /World/Area state=open (the files beneath "
            "select closed; save_scene writes only the root layer, not C:/scene/props.usda)",
        ),
        (
            {"variant_name": ""},
            _variant_answer(old_selection="open", new_selection="closed"),
            "Variant selection cleared in the session layer: /World/Area state=closed (the files select closed)",
        ),
        (
            {},
            _variant_answer(files_select=None, note=_INSTANCE_NOTE),
            "(the files select none; save_scene leaves it out of the file)\nWas: closed. Available: closed, open\n"
            "Note: /World/Area is an instance",
        ),
    ],
    ids=["edit-target", "edit-target-a-sublayer", "clear", "instance"],
)
def test_set_variant_selection_says_where_the_switch_went(
    args: dict[str, Any], answer: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    bridge.set_response("/scene/variant_selection", {"status": "success", "result": answer})
    sent = {"prim_path": "/World/Area", "variant_set": "state", "variant_name": "open", **args}

    erred, text, calls = _call(bridge, tmp_path, "set_variant_selection", sent)

    assert not erred, text
    assert says in text
    (body,) = [b for path, b in calls if path == "/scene/variant_selection"]
    assert body["layer"] == args.get("layer", "session")
    assert "WARNING" not in text


def test_set_variant_selection_warns_when_the_extension_wrote_at_the_edit_target(
    bridge: MockIsaacServer, tmp_path: Path
):
    # An extension from before #155 takes no layer and writes at the edit target, into the stage's file.
    answer = {
        "prim_path": "/World/Area",
        "variant_set": "state",
        "old_selection": "closed",
        "new_selection": "open",
        "available_variants": ["closed", "open"],
    }
    bridge.set_response("/scene/variant_selection", {"status": "success", "result": answer})

    erred, text, _calls = _call(
        bridge,
        tmp_path,
        "set_variant_selection",
        {"prim_path": "/World/Area", "variant_set": "state", "variant_name": "open"},
    )

    assert not erred, text
    assert "Variant switched: /World/Area state=open (was: closed)" in text
    assert "WARNING: This Kit extension, older than the server, wrote the selection at the edit target" in text
    assert "extension install" in text


@pytest.mark.parametrize("name", ["", "open"])
def test_set_variant_selection_says_an_older_extension_cant_clear(name: str, bridge: MockIsaacServer, tmp_path: Path):
    # An extension from before #155 refuses an empty variant_name with this alone, which reads as the caller's mistake.
    bridge.set_response("/scene/variant_selection", {"status": "error", "error": "variant_name is required"})

    erred, text, _calls = _call(
        bridge,
        tmp_path,
        "set_variant_selection",
        {"prim_path": "/World/Area", "variant_set": "state", "variant_name": name},
    )

    assert erred
    assert "variant_name is required" in text
    warns = "WARNING: This Kit extension, older than the server, can't clear a selection" in text
    assert warns is (name == "")
    assert ("extension install" in text) is (name == "")


def test_set_prim_attribute_sends_the_layer_asked_for(bridge: MockIsaacServer, tmp_path: Path):
    answer = {"prim_path": "/World/A", "name": "my:v", "type": "x", "before": "0", "after": "1"}
    bridge.set_response("/scene/attribute", {"status": "success", "result": answer | {"layer": "Kit's session layer"}})
    args = {"prim_path": "/World/A", "name": "my:v", "value": 1, "layer": "session"}

    erred, text, calls = _call(bridge, tmp_path, "set_prim_attribute", args)

    assert not erred, text
    assert "written to Kit's session layer" in text
    (body,) = [b for path, b in calls if path == "/scene/attribute"]
    assert body["layer"] == "session"


def test_save_scene_names_the_session_layers_selections_it_leaves_out(bridge: MockIsaacServer, tmp_path: Path):
    left = ["/World/Area lod=low", "/World/Area state=open"]
    answer = {"action": "save", "file_path": "C:/site.usda", "session_selections": left}
    bridge.set_response("/scene/save", {"status": "success", "result": answer})

    erred, text, _calls = _call(bridge, tmp_path, "save_scene", {})

    assert not erred, text
    assert text.splitlines()[1] == (
        "Not in the file: the variant selections in Kit's session layer, /World/Area lod=low, /World/Area state=open; "
        'to keep one, clear it with set_variant_selection(variant_name="") and select it again with '
        'layer="edit_target"'
    )


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
    assert text == "Nothing set on /World/RedCube: give mass, density, friction, restitution or collision"


def _collision_text(args: dict[str, Any], echo: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path) -> str:
    """The tool's text for args on /World/Floor, given what the extension echoed beside the unset values."""
    sent = {"prim_path": "/World/Floor", **args}
    unset = dict.fromkeys(("mass", "density", "friction", "restitution"))
    answer = {"prim_path": "/World/Floor", "applied": [], **unset, **echo}
    return _check(Case("set_physics_properties", sent, "/physics/properties", answer, sent, ()), bridge, tmp_path)


@pytest.mark.parametrize(
    ("args", "echo", "says"),
    [
        (
            {"collision": True},
            {"applied": ["CollisionAPI"], "collision": True},
            "Physics on /World/Floor: collision=on; applied CollisionAPI",
        ),
        ({"collision": False}, {"collision": False}, "Physics on /World/Floor: collision=off"),
        (
            {"collision": False},
            {"collision": False, "collider": False},
            "Physics on /World/Floor: collision=off (it had no collider)",
        ),
        (
            {"collision": True},
            {
                "applied": ["CollisionAPI", "MeshCollisionAPI"],
                "collision": True,
                "approximation": "convexHull",
                "body": "/World/Cart",
            },
            "Physics on /World/Floor: collision=on; applied CollisionAPI, MeshCollisionAPI; approximation convexHull; "
            "part of the rigid body /World/Cart",
        ),
        # A stronger layer's false, read back after the write.
        ({"collision": True}, {"collision": False}, "Physics on /World/Floor: collision=off"),
    ],
    ids=["on", "off", "off without a collider", "a moving mesh", "held off by a stronger layer"],
)
def test_set_physics_properties_says_what_collision_became(
    args: dict[str, Any], echo: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    assert _collision_text(args, echo, bridge, tmp_path) == says


def test_set_physics_properties_warns_when_an_older_extension_drops_collision(bridge: MockIsaacServer, tmp_path: Path):
    # The 0.4.1 handler builds its echo from fixed keys: collision comes back missing, and the call succeeds.
    text = _collision_text({"collision": True}, {}, bridge, tmp_path)

    first, warning = text.split("\n")
    assert first == "Physics on /World/Floor: nothing set"
    assert warning.startswith("WARNING: collision not set: the Kit extension is 1.0.0, this server's is ")
    assert "Install this server's, " in warning
    assert "did apply the Collision API" not in warning


def test_the_older_extension_s_warning_says_friction_did_apply_the_api(bridge: MockIsaacServer, tmp_path: Path):
    text = _collision_text(
        {"collision": True, "friction": 0.5}, {"friction": 0.5, "applied": ["CollisionAPI"]}, bridge, tmp_path
    )

    assert text.startswith("Physics on /World/Floor: friction=0.5 (static and dynamic); applied CollisionAPI\n")
    assert text.endswith("Its friction or restitution did apply the Collision API, so the prim collides.")


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
        "render_product": "/Render/OmniverseKit/HydraTextures/ovmcp_feed_0",
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
    kept = "kept up to 30 s after the stop for the next capture or recording"
    assert f"\nRenders into /Render/OmniverseKit/HydraTextures/ovmcp_feed_0, {kept}\n" in text


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


def test_get_performance_says_what_kit_couldnt_give_and_each_note(bridge: MockIsaacServer, tmp_path: Path):
    # A stopped stage in a Kit app without Hydra's stats, whose time ran out while it loaded: each missing number on
    # its line, the conditions it had, and the notes as the extension wrote them.
    answer = {
        **PERFORMANCE,
        "measured_frames": 0,
        "app": None,
        "app_missing": "the 90 s this call may take ran out while the stage was still loading",
        "gpu_render": {"missing": "not available in this app: it has no omni.hydra.engine.stats"},
        "physics": {"missing": "not measured: the timeline is stopped, so physics doesn't step; play it"},
        "gpu_memory": {"missing": "not available in this app: it has no omni.hydra.engine.stats"},
        "stage": {**PERFORMANCE["stage"], "instances": 0, "prototypes": 0, "point_instancers": 0},
        "render_products": [],
        "conditions": {
            **PERFORMANCE["conditions"],
            "gpu": None,
            "timeline": "stopped",
            "headless": False,
            "fixed_time_stepping": False,
            "rate_limit": None,
            "rate_limit_lifted": False,
            "eco_mode": True,
            "async_rendering": True,
            "sleep_ms_on_focus": 10,
        },
        "notes": ["eco mode is on and the timeline isn't playing: measure while it plays"],
    }
    del answer["halves"]
    text = _check(
        Case(
            "get_performance",
            {},
            "/sim/performance",
            answer,
            {"frames": 120, "warmup": 30},
            (
                "app = not measured: the 90 s this call may take ran out while the stage was still loading\n"
                "gpu_render = not available in this app: it has no omni.hydra.engine.stats\n"
                "physics = not measured: the timeline is stopped, so physics doesn't step; play it\n"
                "gpu_memory = not available in this app: it has no omni.hydra.engine.stats\n"
                "stage = 18342 prims, 2210 meshes\n"
                "render_products = none\n"
                "conditions = Isaac-Sim Python 6.2.0 (Kit 110.4.0), renderer rtx (RaytracedLighting), stopped, with a "
                "window, time steps by the wall clock; rate limit not set, so left as it was; async rendering on, eco "
                "mode on, sleepMsOnFocus 10 ms\n"
                "note = eco mode is on and the timeline isn't playing: measure while it plays",
            ),
        ),
        bridge,
        tmp_path,
    )
    assert "settled" not in text


@pytest.mark.parametrize(
    ("memory", "says"),
    [
        (
            {"device": "Invented GPU", "used_bytes": 2**30, "total_bytes": None, "total_kind": None},
            "gpu_memory = 1.0 GiB used (Hydra's figures for device 0, Invented GPU)\n",
        ),
        (
            {"device": "Invented GPU", "used_bytes": 2**30, "total_bytes": 16 * 2**30, "total_kind": "budget"},
            "gpu_memory = 1.0 GiB used of a 16.0 GiB budget (Hydra's figures for device 0, Invented GPU)\n",
        ),
        (
            {"device": "Invented GPU", "used_bytes": None, "total_bytes": 16 * 2**30, "total_kind": "dedicated"},
            "gpu_memory = not given by Hydra for Invented GPU\n",
        ),
    ],
    ids=["no-total", "budget", "no-use"],
)
def test_get_performance_reads_a_limiter_off_steps_without_a_rate_and_part_of_the_memory(
    memory: dict[str, Any], says: str, bridge: MockIsaacServer, tmp_path: Path
):
    # A limiter already off before the call is left off, and said so; fixed steps whose rate Kit didn't give are still
    # fixed; Hydra's figures as far as it gives them.
    conditions = {
        **PERFORMANCE["conditions"],
        "rate_limit": False,
        "rate_limit_lifted": False,
        "time_codes_per_second": None,
    }
    answer = {**PERFORMANCE, "gpu_memory": memory, "conditions": conditions}
    case = Case(
        "get_performance",
        {},
        "/sim/performance",
        answer,
        {},
        (says, "playing, headless, fixed time steps; rate limit off; async rendering off, eco mode off"),
    )
    _check(case, bridge, tmp_path)


def test_get_performance_says_how_many_of_the_frames_asked_it_measured(bridge: MockIsaacServer, tmp_path: Path):
    answer = {**PERFORMANCE, "measured_frames": 40, "notes": ["the 90 s this call may take ran out after 40 of 240"]}
    case = Case(
        "get_performance",
        {"frames": 240, "warmup": 60},
        "/sim/performance",
        answer,
        {"frames": 240, "warmup": 60},
        ("over 40 of 240 frames after 60\n", "note = the 90 s this call may take ran out after 40 of 240"),
    )
    _check(case, bridge, tmp_path)


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


class _Silent(BridgeClient):
    """A Kit whose scene tree call meets the client's error for a Kit that stopped answering, or its plain timeout."""

    error: OSError = KitSilentError("Kit at 127.0.0.1:8211 stopped answering: a call got no answer in 120 s")

    def scene_tree(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise self.error


def _scene_tree_through(client: BridgeClient, bridge: MockIsaacServer, tmp_path: Path) -> tuple[bool, str]:
    try:

        async def call():
            async with Client(create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)) as c:
                return await c.call_tool("get_scene_tree", {})

        result = asyncio.run(call())
    finally:
        client.close()
    return bool(result.is_error), "\n".join(getattr(c, "text", "") for c in result.content)


def test_a_kit_that_stopped_answering_is_named_with_what_it_may_be_doing(bridge: MockIsaacServer, tmp_path: Path):
    # Kit 110 can hang for good in NVIDIA's renderer (#114): the agent learns what happened and when to restart Kit.
    erred, text = _scene_tree_through(_Silent(port=bridge.port, token="invented-test-token"), bridge, tmp_path)
    assert erred
    assert "Kit at 127.0.0.1:8211 stopped answering: a call got no answer in 120 s. It may be busy" in text
    assert "most likely in NVIDIA's RTX renderer" in text
    assert "#114" in text
    assert "If it stays silent for minutes, restart the Kit app." in text
    assert "connection failed" not in text


def test_a_plain_timeout_is_still_a_connection_failure(bridge: MockIsaacServer, tmp_path: Path):
    client = _Silent(port=bridge.port, token="invented-test-token")
    client.error = TimeoutError("timed out")
    erred, text = _scene_tree_through(client, bridge, tmp_path)
    assert erred
    assert "Kit app connection failed: timed out" in text
    assert "restart" not in text


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


@pytest.mark.parametrize(
    ("block", "warns"),
    [
        ("[/World/Cube]\ntype = Cube\napi_schemas = PhysicsCollisionAPI\nvariant_sets = []\nsize = 1", False),
        # An extension built between #149 and #155: schemas, but no variant sets.
        ("[/World/Cube]\ntype = Cube\napi_schemas = PhysicsCollisionAPI\nsize = 1", True),
        ("[/World/Cube]\ntype = Cube\nmaterial:binding = <unreadable>\nsize = 1", True),
    ],
)
def test_get_prim_properties_warns_when_the_extension_lists_no_schemas(
    block: str, warns: bool, bridge: MockIsaacServer, tmp_path: Path
):
    # An extension from before #149 lists no schemas and no relationship's targets, and one from before #155 no
    # variant sets, and the plugin updates the server first: without the warning, the description would promise lines
    # the answer doesn't give.
    bridge.set_response("/scene/prim", {"status": "success", "result": {"text": block, "prim_path": "/World/Cube"}})
    erred, text, _calls = _call(bridge, tmp_path, "get_prim_properties", {"prim_path": "/World/Cube"})
    assert not erred, text
    assert text.startswith("[/World/Cube]")
    warning = "WARNING: This Kit extension, older than the server, lists no applied API schemas, no variant sets"
    assert (warning in text) is warns
    assert ("extension install" in text) is warns


def test_new_scene_sends_the_frame_asked_and_gives_the_one_read_back(bridge: MockIsaacServer, tmp_path: Path):
    answer = {"message": "New scene created", "default_prim": "/World", "up_axis": "Y", "meters_per_unit": 0.01}
    bridge.set_response("/scene/new", {"status": "success", "result": answer})

    erred, text, calls = _call(bridge, tmp_path, "new_scene", {"up_axis": "Y", "meters_per_unit": 0.01})

    assert not erred, text
    assert calls == [("/scene/new", {"up_axis": "Y", "meters_per_unit": 0.01})]
    assert text == "New scene created with /World root prim\nup_axis = Y\nmeters_per_unit = 0.01"


def test_new_scene_warns_when_an_older_extension_made_its_own_y_up_stage(bridge: MockIsaacServer, tmp_path: Path):
    # An extension from before #159 ignores both keys and answers no frame, and the plugin updates the server first:
    # without the warning, an agent would place things along Z on a Y-up stage.
    bridge.set_response("/scene/new", {"status": "success", "result": {"message": "New scene created"}})

    erred, text, _calls = _call(bridge, tmp_path, "new_scene", {})

    assert not erred, text
    assert text.startswith("New scene created with /World root prim\nWARNING: This Kit extension, older than the")
    assert "server, made a Y-up stage in Kit's units" in text
    assert "up_axis = " not in text
    assert f"Install this server's, {kit_extension.install_advice()}." in text


@pytest.mark.parametrize("args", [{"up_axis": "X"}, {"meters_per_unit": 0}, {"meters_per_unit": -0.01}])
def test_new_scene_refuses_a_frame_it_can_t_make_before_the_bridge(
    args: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    erred, _text, calls = _call(bridge, tmp_path, "new_scene", args)

    assert erred
    assert calls == []


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


# ----- jobs (#158) -----


def _job(state: str, **fields: Any) -> dict[str, Any]:
    """/jobs/get's answer for a script job of 37 lines, all read."""
    return {
        "id": "j3",
        "kind": "script",
        "label": "bake.py",
        "state": state,
        "message": "",
        "elapsed": 612.0,
        "lines": [],
        "lines_new": 0,
        "lines_total": 37,
        "last": "37 of 150 stacks settled",
        **fields,
    }


def _no_output() -> dict[str, Any]:
    return {"stdout": "", "stdout_lines": 0, "stderr": "", "stderr_lines": 0}


def _job_text(bridge: MockIsaacServer, tmp_path: Path, answer: dict[str, Any]) -> str:
    bridge.set_response("/jobs/get", {"status": "success", "result": answer})
    erred, text, _calls = _call(bridge, tmp_path, "get_job", {})
    assert not erred, text
    return text


def test_get_job_says_when_there_is_nothing_new_and_when_lines_were_cut(bridge: MockIsaacServer, tmp_path: Path):
    assert "lines = 37 printed, none since the last read" in _job_text(bridge, tmp_path, _job("working"))
    cut = _job("working", lines=["x"] * 200, lines_new=312, lines_total=512)
    assert "lines = 512 printed, 312 since the last read, the last 200 shown:" in _job_text(bridge, tmp_path, cut)


def test_get_job_gives_a_finished_script_s_return_value_and_its_kept_output(bridge: MockIsaacServer, tmp_path: Path):
    stdout = "".join(f"stack {i}\n" for i in range(312, 512))
    answer = _job(
        "completed",
        result={"return_value": {"settled": 150}},
        output={"stdout": stdout, "stdout_lines": 512, "stderr": "a warning\n", "stderr_lines": 1},
    )
    text = _job_text(bridge, tmp_path, answer)
    # Over 1,000 characters: written to a file, which holds the whole answer.
    assert text.startswith("Wrote job (")
    written = Path(text.rsplit("-> ", 1)[1])
    whole = (written if written.is_absolute() else Path.cwd() / written).read_text(encoding="utf-8")
    assert 'Return value:\n{\n  "settled": 150\n}' in whole
    assert "Stdout (the last 200 of 512 lines):\nstack 312\n" in whole
    assert whole.endswith("stack 511\nStderr:\na warning")
    assert "lines = " not in whole


def test_get_job_gives_a_failed_job_s_error_and_the_last_lines_of_its_traceback(
    bridge: MockIsaacServer, tmp_path: Path
):
    traceback = "Traceback (most recent call last):\n" + "".join(f'  File "x", line {i}\n' for i in range(9))
    answer = _job(
        "failed",
        error="stack 3 fell over",
        traceback=traceback + "ValueError: stack 3 fell over\n",
        output={**_no_output(), "stdout": "1 of 150\n", "stdout_lines": 1},
    )
    text = _job_text(bridge, tmp_path, answer)
    assert "state = failed" in text
    assert "error = stack 3 fell over\nTraceback (its last lines):\n" in text
    assert '  File "x", line 4\n' not in text
    assert '  File "x", line 8\nValueError: stack 3 fell over\nStdout:\n1 of 150' in text


def test_get_job_says_why_a_job_was_cancelled_and_how_long_one_has_been_cancelling(
    bridge: MockIsaacServer, tmp_path: Path
):
    cancelled = _job("cancelled", message="the stage changed", output=_no_output())
    text = _job_text(bridge, tmp_path, cancelled)
    assert "state = cancelled\nelapsed = 10m 12s\nmessage = the stage changed" in text
    cancelling = _job("cancelling", message="cancel_job was called", cancelling=75.0)
    text = _job_text(bridge, tmp_path, cancelling)
    assert "cancelling = for 1m 15s, its cleanup running" in text
    assert "until cancel_job cancels it again" in text
    assert "message =" not in text


def test_get_job_gives_another_kind_s_result_whole(bridge: MockIsaacServer, tmp_path: Path):
    sweep = _job("completed", kind="sweep", result={"manifest": "shots/manifest.json"}, output=_no_output())
    assert 'Result:\n{\n  "manifest": "shots/manifest.json"\n}' in _job_text(bridge, tmp_path, sweep)


def test_get_job_names_no_return_value_a_script_didn_t_set(bridge: MockIsaacServer, tmp_path: Path):
    done = _job("completed", result={"return_value": None}, output=_no_output())
    assert "Return value: none" in _job_text(bridge, tmp_path, done)


@pytest.mark.parametrize("args", [{}, {"code": "  "}, {"code": "await x", "file": "bake.py"}])
def test_run_script_job_needs_one_of_code_and_file_before_any_request(
    args: dict[str, Any], bridge: MockIsaacServer, tmp_path: Path
):
    erred, text, calls = _call(bridge, tmp_path, "run_script_job", args)
    assert erred
    assert "Give the script as code or as file, one of them" in text
    assert calls == []


def test_run_script_job_sends_a_file_alone(bridge: MockIsaacServer, tmp_path: Path):
    bridge.set_response("/jobs/script", {"status": "success", "result": {"id": "j1", "kind": "script"}})
    erred, _text, calls = _call(bridge, tmp_path, "run_script_job", {"file": " D:/bakes/bake.py "})
    assert not erred
    assert calls == [("/jobs/script", {"file": "D:/bakes/bake.py"})]


def test_run_script_job_passes_on_the_refusal_of_a_script_that_never_awaits(bridge: MockIsaacServer, tmp_path: Path):
    refusal = "This script never awaits, so it would hold Kit's main thread from its start to its end"
    bridge.set_response("/jobs/script", {"status": "error", "error": refusal})
    erred, text, _calls = _call(bridge, tmp_path, "run_script_job", {"code": "for i in range(9): pass"})
    assert erred
    assert refusal in text


@pytest.mark.parametrize(
    ("was", "says"),
    [
        ("cancelling", "Job j3 cancelled again at its next await"),
        ("completed", "Job j3 had already ended (completed): nothing to cancel"),
    ],
)
def test_cancel_job_says_a_second_cancel_and_an_ended_job(was: str, says: str, bridge: MockIsaacServer, tmp_path: Path):
    answer = {"id": "j3", "kind": "script", "state": was, "was": was, "message": ""}
    bridge.set_response("/jobs/cancel", {"status": "success", "result": answer})
    erred, text, _calls = _call(bridge, tmp_path, "cancel_job", {"job_id": "j3"})
    assert not erred
    assert text.startswith(says)


@pytest.mark.parametrize(
    ("tool", "args", "field"),
    [("get_job", {"wait": 101}, "wait"), ("get_job", {"wait": -1}, "wait"), ("cancel_job", {}, "job_id")],
)
def test_a_wait_past_100_s_or_a_cancel_without_an_id_is_refused_before_any_request(
    tool: str, args: dict[str, Any], field: str, bridge: MockIsaacServer, tmp_path: Path
):
    erred, text, calls = _call(bridge, tmp_path, tool, args)
    assert erred
    assert field in text
    assert calls == []


def test_get_sim_state_names_a_running_job(bridge: MockIsaacServer, tmp_path: Path):
    job = {"id": "j3", "kind": "script", "state": "working", "elapsed": 252.4}
    case = Case(
        "get_sim_state", {}, "/sim/state", {"state": "playing", "job": job}, {}, ("job = j3 (script, working, 4m 12s)",)
    )
    _check(case, bridge, tmp_path)


@pytest.mark.parametrize(
    ("seconds", "said"), [(0.04, "0.0s"), (12.34, "12.3s"), (59.99, "60.0s"), (252.4, "4m 12s"), (3723, "1h 2m 3s")]
)
def test_a_job_s_time_reads_in_seconds_minutes_and_hours(seconds: float, said: str):
    assert duration(seconds) == said
