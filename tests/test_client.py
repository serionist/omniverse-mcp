"""
Unit tests for the BridgeClient HTTP client.

Uses a mock HTTP server to test all endpoints without needing Isaac Sim.
Run: python -m pytest tests/test_client.py -v
"""

import json
import socket
import threading
import time
import unittest
from collections.abc import Iterator

import pytest

import omniverse_mcp.client as client_module
from omniverse_mcp.client import BridgeClient, BridgeError, KitSilentError

from .mock_bridge import MockIsaacServer


class TestBridgeClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MockIsaacServer()
        # Register mock responses for all endpoints
        cls.mock.set_response("/bridge", {"status": "success", "result": {"protocol": 1, "extension_version": "1.0.0"}})
        cls.mock.set_response(
            "/health",
            {
                "status": "success",
                "result": {
                    "stage_path": "/test.usd",
                    "up_axis": "Y",
                    "meters_per_unit": 1.0,
                    "recording_active": False,
                    "protocol": 1,
                    "extension_version": "1.0.0",
                },
            },
        )
        cls.mock.set_response(
            "/execute", {"status": "success", "result": {"stdout": "hello\n", "stderr": "", "return_value": 42}}
        )
        cls.mock.set_response(
            "/scene/tree",
            {
                "status": "success",
                "result": {
                    "path": "/",
                    "type": "Xform",
                    "children": [{"path": "/World", "type": "Xform", "world_position": [0, 0, 0]}],
                },
            },
        )
        cls.mock.set_response(
            "/scene/dump",
            {
                "status": "success",
                "result": {"file_path": "/tmp/scene_dump.json", "file_size_bytes": 1234, "prim_count": 10, "root": "/"},
            },
        )
        cls.mock.set_response(
            "/scene/prim",
            {
                "status": "success",
                "result": {"prim_path": "/World", "type": "Xform", "is_active": True, "properties": {}},
            },
        )
        cls.mock.set_response(
            "/scene/bounds",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Cube",
                    "center": [0, 0.5, 0],
                    "dimensions": [1, 1, 1],
                    "min": [-0.5, 0, -0.5],
                    "max": [0.5, 1, 0.5],
                    "max_dimension": 1.0,
                    "diagonal": 1.732,
                },
            },
        )
        cls.mock.set_response(
            "/scene/transform",
            {"status": "success", "result": {"prim_path": "/World/Box", "message": "Transform updated"}},
        )
        cls.mock.set_response(
            "/scene/create", {"status": "success", "result": {"prim_path": "/World/NewCube", "type": "Cube"}}
        )
        cls.mock.set_response(
            "/scene/delete", {"status": "success", "result": {"prim_path": "/World/Old", "message": "Prim deleted"}}
        )
        cls.mock.set_response(
            "/scene/material",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Cube",
                    "material_path": "/World/Looks/Cube_Mat",
                    "color": [1, 0, 0],
                    "roughness": 0.5,
                    "metallic": 0.0,
                    "opacity": 1.0,
                },
            },
        )
        cls.mock.set_response(
            "/scene/clone",
            {"status": "success", "result": {"source": "/World/Cube", "clones": ["/World/Cube_Clone"], "count": 1}},
        )
        cls.mock.set_response(
            "/scene/visibility", {"status": "success", "result": {"prim_path": "/World/Cube", "visible": False}}
        )
        cls.mock.set_response("/sim/performance", {"status": "success", "result": {"measured_frames": 240}})
        cls.mock.set_response(
            "/scene/attribute",
            {"status": "success", "result": {"prim_path": "/World/Sun", "name": "inputs:intensity", "after": "3000"}},
        )
        cls.mock.set_response(
            "/scene/save", {"status": "success", "result": {"file_path": "/tmp/scene.usd", "action": "saved"}}
        )
        cls.mock.set_response("/scene/new", {"status": "success", "result": {"message": "New scene created"}})
        cls.mock.set_response(
            "/scene/open", {"status": "success", "result": {"file_path": "C:/Scenes/room.usda", "up_axis": "Z"}}
        )
        cls.mock.set_response(
            "/robot/create",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/G1",
                    "robot_type": "g1",
                    "usd_path": "/Isaac/Robots/Unitree/G1/g1.usd",
                    "joints": [],
                },
            },
        )
        cls.mock.set_response(
            "/robot/info",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/G1",
                    "dof_count": 43,
                    "link_count": 20,
                    "joints": [{"name": "left_hip_pitch_joint", "type": "PhysicsRevoluteJoint"}],
                },
            },
        )
        cls.mock.set_response(
            "/robot/joint_states",
            {"status": "success", "result": {"prim_path": "/World/G1", "dof_count": 43, "positions": [0.0] * 43}},
        )
        cls.mock.set_response(
            "/robot/joint_targets", {"status": "success", "result": {"prim_path": "/World/G1", "targets_set": 1}}
        )
        cls.mock.set_response(
            "/sim/control", {"status": "success", "result": {"action": "play", "current_state": "playing"}}
        )
        cls.mock.set_response(
            "/sim/state",
            {
                "status": "success",
                "result": {
                    "state": "stopped",
                    "current_time": 0.0,
                    "fps": 60.0,
                    "prim_count": 5,
                    "up_axis": "Y",
                    "meters_per_unit": 1.0,
                    "recording_active": False,
                },
            },
        )
        cls.mock.set_response(
            "/sim/capture",
            {
                "status": "success",
                "result": {
                    "image_base64": "iVBORw0KGgo=",
                    "width": 1280,
                    "height": 720,
                    "camera_path": "/OmniverseKit_Persp",
                    "format": "png",
                    "screen_bboxes": [
                        {
                            "prim_path": "/World/Cube",
                            "type": "Cube",
                            "screen_bbox": [120.0, 200.0, 480.0, 600.0],
                            "world_center": [0.0, 0.5, 0.0],
                            "world_dimensions": [1.0, 1.0, 1.0],
                        }
                    ],
                    "segmentation_base64": "iVBORw0KGgo=",
                    "segmentation_legend": {"/World/Cube": [255, 159, 0]},
                },
            },
        )
        cls.mock.set_response(
            "/camera/set",
            {
                "status": "success",
                "result": {"camera_path": "/OmniverseKit_Persp", "position": [5, 3, 5], "target": [0, 0, 0]},
            },
        )
        cls.mock.set_response(
            "/camera/look_at",
            {
                "status": "success",
                "result": {
                    "camera_path": "/OmniverseKit_Persp",
                    "camera_position": [2, 1.5, 2],
                    "target": [0, 0.5, 0],
                    "distance": 3.0,
                    "azimuth": 45.0,
                    "elevation": 30.0,
                },
            },
        )
        cls.mock.set_response(
            "/camera/inspect",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Cube",
                    "center": [0, 0.5, 0],
                    "distance": 2.5,
                    "zoom_offset": 0.0,
                    "isolate": False,
                    "captures": [
                        {
                            "angle": "front",
                            "azimuth": 0,
                            "elevation": 20,
                            "camera_position": [0, 1, 2.3],
                            "image_base64": "iVBORw0KGgo=",
                        }
                    ],
                },
            },
        )
        cls.mock.set_response(
            "/recording/start",
            {
                "status": "success",
                "result": {
                    "session_id": "rec_123",
                    "output_dir": "/tmp/rec_123",
                    "fps": 5,
                    "resolution": [640, 480],
                    "camera_path": "/OmniverseKit_Persp",
                },
            },
        )
        cls.mock.set_response(
            "/recording/stop",
            {
                "status": "success",
                "result": {
                    "session_id": "rec_123",
                    "output_dir": "/tmp/rec_123",
                    "frame_count": 15,
                    "duration_seconds": 3.0,
                    "metadata_file": "/tmp/rec_123/metadata.json",
                },
            },
        )
        cls.mock.set_response(
            "/recording/frame",
            {
                "status": "success",
                "result": {
                    "frame_index": 0,
                    "image_base64": "iVBORw0KGgo=",
                    "format": "png",
                    "sim_time": 0.0,
                    "wall_time": 0.0,
                },
            },
        )
        cls.mock.set_response(
            "/extensions/list",
            {
                "status": "success",
                "result": {
                    "count": 2,
                    "extensions": [
                        {"id": "omni.replicator.core", "name": "Replicator Core", "enabled": True, "version": "1.0.0"},
                        {"id": "omni.physx", "name": "PhysX", "enabled": True, "version": "1.0.0"},
                    ],
                },
            },
        )
        cls.mock.set_response(
            "/extensions/manage",
            {"status": "success", "result": {"extension_id": "omni.test.ext", "action": "enable", "enabled": True}},
        )
        cls.mock.set_response(
            "/physics/properties",
            {"status": "success", "result": {"prim_path": "/World/Cube", "applied": ["MassAPI", "PhysicsMaterial"]}},
        )
        cls.mock.set_response(
            "/physics/apply_force",
            {"status": "success", "result": {"prim_path": "/World/Cube", "method": "velocity", "force": [100, 0, 0]}},
        )
        cls.mock.set_response(
            "/physics/raycast",
            {
                "status": "success",
                "result": {
                    "hit": True,
                    "prim_path": "/World/Ground",
                    "position": [0, 0, 0],
                    "normal": [0, 1, 0],
                    "distance": 10.0,
                },
            },
        )
        cls.mock.set_response(
            "/debug/draw",
            {"status": "success", "result": {"drawn": [{"type": "line", "start": [0, 0, 0], "end": [1, 1, 0]}]}},
        )
        # New tool responses
        cls.mock.set_response(
            "/scene/mesh_stats",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Mesh",
                    "total_faces": 1200,
                    "total_vertices": 800,
                    "total_triangles": 2400,
                    "mesh_count": 3,
                    "meshes": [
                        {"path": "/World/Mesh/Body", "faces": 1000, "vertices": 600, "triangles": 2000},
                        {"path": "/World/Mesh/Arm_L", "faces": 100, "vertices": 100, "triangles": 200},
                        {"path": "/World/Mesh/Arm_R", "faces": 100, "vertices": 100, "triangles": 200},
                    ],
                },
            },
        )
        cls.mock.set_response(
            "/scene/face_count_tree",
            {
                "status": "success",
                "result": {
                    "text": "[/World]\ntype = Xform\nsubtree_faces = 1200\n",
                    "total_faces": 1200,
                    "mesh_count": 3,
                },
            },
        )
        cls.mock.set_response(
            "/scene/flatten",
            {
                "status": "success",
                "result": {"input_path": "/tmp/scene.usda", "output_path": "/tmp/flat.usdc", "layer_count": 5},
            },
        )
        cls.mock.set_response(
            "/scene/export",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Component",
                    "output_path": "/tmp/component.usdc",
                    "target_root": "/Component",
                    "materials_included": 2,
                    "up_axis": "Z",
                },
            },
        )
        cls.mock.set_response(
            "/scene/variant_selection",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Server",
                    "variant_set": "model",
                    "old_selection": "focused",
                    "new_selection": "shell",
                    "available_variants": ["focused", "shell"],
                },
            },
        )
        cls.mock.set_response(
            "/scene/create_variant_structure",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World/Server",
                    "variant_set_name": "model",
                    "variants_created": ["focused", "shell"],
                    "default_selection": "focused",
                },
            },
        )
        cls.mock.set_response(
            "/scene/compare",
            {
                "status": "success",
                "result": {
                    "a": {
                        "label": "/World/A",
                        "total_faces": 10000,
                        "total_vertices": 8000,
                        "total_triangles": 20000,
                        "mesh_count": 5,
                        "bounds_center": [0, 0, 0],
                        "bounds_dimensions": [1, 1, 1],
                        "materials": ["/World/Looks/Mat1"],
                    },
                    "b": {
                        "label": "/World/B",
                        "total_faces": 2000,
                        "total_vertices": 1500,
                        "total_triangles": 4000,
                        "mesh_count": 3,
                        "bounds_center": [0, 0, 0],
                        "bounds_dimensions": [1, 1, 1],
                        "materials": ["/World/Looks/Mat1"],
                    },
                    "delta": {
                        "faces": -8000,
                        "vertices": -6500,
                        "triangles": -16000,
                        "meshes": -2,
                        "face_reduction_pct": -80.0,
                    },
                },
            },
        )
        cls.mock.set_response(
            "/scene/update_material_paths",
            {
                "status": "success",
                "result": {
                    "prim_path": "/World",
                    "old_prefix": "/Old/Looks",
                    "new_prefix": "/World/Looks",
                    "updated_count": 5,
                    "updated_prims": ["/World/Server/Body", "/World/Server/Door"],
                },
            },
        )
        cls.mock.set_response(
            "/viewport/light",
            {
                "status": "success",
                "result": {
                    "lighting_mode": "stage",
                    "available_modes": ["off", "camera", "stage", "Default", "Colored Lights", "Grey Studio"],
                    "has_scene_lights": True,
                    "scene_lights": [{"path": "/World/DistantLight", "type": "DistantLight", "intensity": 1000}],
                },
            },
        )
        cls.mock.set_response(
            "/logs",
            {
                "status": "success",
                "result": {
                    "entries": [
                        {
                            "index": 0,
                            "level": "warn",
                            "channel": "omni.physx",
                            "module": "PhysX",
                            "source": "physx.cpp:42",
                            "func": "init",
                            "msg": "Test warning",
                            "timestamp": 1709912345.0,
                        }
                    ],
                    "count": 1,
                    "total_captured": 100,
                    "buffer_size": 2000,
                },
            },
        )
        cls.mock.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.client = BridgeClient(host="127.0.0.1", port=self.mock.port, timeout=5.0)
        self.mock.requests.clear()

    def tearDown(self):
        self.client.close()

    def test_health(self):
        r = self.client.health()
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["up_axis"], "Y")

    def test_execute(self):
        r = self.client.execute("print('hello')")
        self.assertEqual(r["result"]["stdout"], "hello\n")
        self.assertEqual(r["result"]["return_value"], 42)

    def test_scene_tree(self):
        r = self.client.scene_tree("/", 5)
        self.assertIn("children", r["result"])

    def test_scene_dump(self):
        r = self.client.scene_dump("/tmp", "/", 15, True)
        self.assertEqual(r["result"]["prim_count"], 10)

    def test_prim_properties(self):
        r = self.client.prim_properties("/World")
        self.assertEqual(r["result"]["type"], "Xform")

    def test_prim_bounds(self):
        r = self.client.prim_bounds("/World/Cube")
        self.assertEqual(r["result"]["max_dimension"], 1.0)

    def test_set_transform(self):
        r = self.client.set_transform("/World/Box", position=[1, 2, 3])
        self.assertEqual(r["status"], "success")

    def test_create_prim(self):
        r = self.client.create_prim("/World/NewCube", "Cube", position=[0, 0, 1])
        self.assertEqual(r["result"]["type"], "Cube")

    def test_delete_prim(self):
        r = self.client.delete_prim("/World/Old")
        self.assertEqual(r["status"], "success")

    def test_create_robot(self):
        r = self.client.create_robot("g1", position=[0, 0, 0])
        self.assertEqual(r["result"]["robot_type"], "g1")

    def test_sim_control(self):
        r = self.client.sim_control("play")
        self.assertEqual(r["result"]["current_state"], "playing")

    def test_sim_state(self):
        r = self.client.sim_state()
        self.assertEqual(r["result"]["state"], "stopped")

    def test_performance_sends_its_frames_and_warm_up(self):
        r = self.client.performance(240, 60)
        self.assertEqual(r["result"]["measured_frames"], 240)
        self.assertEqual(self.mock.requests[-1], ("POST", "/sim/performance", {"frames": 240, "warmup": 60}))
        # The measurement's defaults, as the tool's.
        self.client.performance()
        self.assertEqual(self.mock.requests[-1], ("POST", "/sim/performance", {"frames": 120, "warmup": 30}))

    def test_capture_viewport(self):
        r = self.client.capture_viewport(1280, 720)
        self.assertIn("image_base64", r["result"])
        self.assertIn("screen_bboxes", r["result"])
        self.assertEqual(len(r["result"]["screen_bboxes"]), 1)
        self.assertEqual(r["result"]["screen_bboxes"][0]["prim_path"], "/World/Cube")
        self.assertIn("segmentation_base64", r["result"])
        self.assertIn("segmentation_legend", r["result"])
        self.assertIn("/World/Cube", r["result"]["segmentation_legend"])

    def test_camera_set(self):
        r = self.client.camera_set([5, 3, 5], [0, 0, 0])
        self.assertEqual(r["result"]["position"], [5, 3, 5])

    def test_camera_look_at(self):
        r = self.client.camera_look_at("/World/Cube", distance=3.0, azimuth=45.0)
        self.assertEqual(r["result"]["distance"], 3.0)

    def test_camera_inspect(self):
        r = self.client.camera_inspect("/World/Cube", angles=["front"])
        self.assertEqual(len(r["result"]["captures"]), 1)

    def test_recording_start(self):
        r = self.client.recording_start("/tmp", fps=5)
        self.assertEqual(r["result"]["session_id"], "rec_123")

    def test_recording_start_with_tracking(self):
        r = self.client.recording_start(
            "/tmp",
            fps=5,
            track_prims=["/World/G1"],
            property_filter=["joint", "pos"],
        )
        self.assertEqual(r["result"]["session_id"], "rec_123")
        # Verify the request included tracking params
        path, method, body = self.mock.requests[-1]
        self.assertEqual(body["track_prims"], ["/World/G1"])
        self.assertEqual(body["property_filter"], ["joint", "pos"])

    def test_recording_stop(self):
        r = self.client.recording_stop()
        self.assertEqual(r["result"]["frame_count"], 15)

    def test_recording_frame(self):
        r = self.client.recording_frame("/tmp/rec_123", 0)
        self.assertIn("image_base64", r["result"])

    def test_extensions_list(self):
        r = self.client.extensions_list(search="replicator")
        self.assertEqual(r["result"]["count"], 2)

    def test_extensions_manage(self):
        r = self.client.extensions_manage("omni.test.ext", "enable")
        self.assertTrue(r["result"]["enabled"])

    def test_set_material(self):
        r = self.client.set_material("/World/Cube", color=[1, 0, 0], roughness=0.5)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["color"], [1, 0, 0])

    def test_set_material_with_custom_path(self):
        r = self.client.set_material("/World/Cube", color=[0, 1, 0], material_path="/World/Looks/Green")
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["material_path"], "/World/Looks/Green")

    def test_clone_prim(self):
        r = self.client.clone_prim("/World/Cube", "/World/Cube_Clone")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["clones"], ["/World/Cube_Clone"])

    def test_clone_prim_batch(self):
        r = self.client.clone_prim("/World/Cube", "/World/Batch", count=3, offset=[2, 0, 0])
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["offset"], [2, 0, 0])

    def test_set_visibility(self):
        r = self.client.set_visibility("/World/Cube", visible=False)
        self.assertEqual(r["status"], "success")
        self.assertFalse(r["result"]["visible"])

    def test_set_attribute_sends_the_name_and_the_value_as_given(self):
        r = self.client.set_attribute("/World/Sun", "inputs:intensity", 3000)
        self.assertEqual(r["result"]["after"], "3000")
        self.assertEqual(
            self.mock.requests[-1],
            ("POST", "/scene/attribute", {"prim_path": "/World/Sun", "name": "inputs:intensity", "value": 3000}),
        )

    def test_save_scene(self):
        r = self.client.save_scene("/tmp/scene.usd")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["file_path"], "/tmp/scene.usd")

    def test_new_scene(self):
        r = self.client.new_scene()
        self.assertEqual(r["status"], "success")
        # Both, always: an extension given neither makes the Y-up stage a server older than #159 asked for.
        self.assertEqual(self.mock.requests[-1], ("POST", "/scene/new", {"up_axis": "Z", "meters_per_unit": 1.0}))
        self.client.new_scene("Y", 0.01)
        self.assertEqual(self.mock.requests[-1], ("POST", "/scene/new", {"up_axis": "Y", "meters_per_unit": 0.01}))

    def test_open_scene(self):
        r = self.client.open_scene("C:/Scenes/room.usda")
        self.assertEqual(r["status"], "success")
        _, path, body = self.mock.requests[-1]
        self.assertEqual(path, "/scene/open")
        self.assertEqual(body, {"file_path": "C:/Scenes/room.usda"})

    def test_get_robot_info(self):
        r = self.client.get_robot_info("/World/G1")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["dof_count"], 43)

    def test_get_joint_states(self):
        r = self.client.get_joint_states("/World/G1")
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(r["result"]["positions"]), 43)

    def test_set_joint_targets(self):
        r = self.client.set_joint_targets("/World/G1", targets={"left_hip": 0.5})
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["targets_set"], 1)

    def test_set_physics_properties(self):
        r = self.client.set_physics_properties("/World/Cube", mass=5.0, friction=0.8)
        self.assertEqual(r["status"], "success")
        self.assertIn("MassAPI", r["result"]["applied"])

    def test_set_physics_properties_sends_collision_only_when_given(self):
        # An unknown key reaches an older handler unread; one not given isn't sent at all (#150).
        sent = []
        for collision in (True, False, None):
            self.mock.requests.clear()
            self.client.set_physics_properties("/World/Cube", collision=collision)
            sent.append(next(body for _, path, body in self.mock.requests if path == "/physics/properties"))
        self.assertEqual(sent[0], {"prim_path": "/World/Cube", "collision": True})
        self.assertEqual(sent[1], {"prim_path": "/World/Cube", "collision": False})
        self.assertEqual(sent[2], {"prim_path": "/World/Cube"})

    def test_apply_force(self):
        r = self.client.apply_force("/World/Cube", force=[100, 0, 0])
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["method"], "velocity")

    def test_raycast(self):
        r = self.client.raycast(origin=[0, 10, 0], direction=[0, -1, 0])
        self.assertEqual(r["status"], "success")
        self.assertTrue(r["result"]["hit"])
        self.assertEqual(r["result"]["prim_path"], "/World/Ground")

    def test_draw_debug(self):
        r = self.client.draw_debug("line", start=[0, 0, 0], end=[1, 1, 0], color=[1, 0, 0])
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(r["result"]["drawn"]), 1)

    def test_keepalive_multiple_requests(self):
        self.client.health()
        self.client.sim_state()
        self.client.scene_tree()
        # One connection: one handshake, then the three requests.
        self.assertEqual(
            [path for _, path, _ in self.mock.requests], ["/bridge", "/health", "/sim/state", "/scene/tree"]
        )

    def test_handshake_on_every_new_connection(self):
        self.client.health()
        self.client._disconnect()
        self.client.health()
        self.assertEqual([path for _, path, _ in self.mock.requests], ["/bridge", "/health", "/bridge", "/health"])

    def test_extension_from_before_the_handshake_is_refused(self):
        old = MockIsaacServer()
        old.set_response("/bridge", {"status": "error", "error": "Unknown endpoint: /bridge"}, status=404)
        old.start()
        client = BridgeClient(host="127.0.0.1", port=old.port, timeout=5.0)
        try:
            with self.assertRaisesRegex(
                BridgeError,
                "older than this MCP server.* extension install, then restart Kit; with the extension from Kit's "
                "community registry",
            ):
                client.health()
            self.assertEqual([path for _, path, _ in old.requests], ["/bridge"])
        finally:
            client.close()
            old.stop()

    def test_reconnect_after_disconnect(self):
        self.client.health()
        self.client._disconnect()
        r = self.client.health()
        self.assertEqual(r["status"], "success")

    # --- New tool tests ---

    def test_mesh_stats(self):
        r = self.client.mesh_stats("/World/Mesh")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["total_faces"], 1200)
        self.assertEqual(r["result"]["mesh_count"], 3)
        self.assertEqual(len(r["result"]["meshes"]), 3)

    def test_face_count_tree(self):
        r = self.client.face_count_tree("/World", max_depth=5)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["total_faces"], 1200)
        self.assertIn("subtree_faces", r["result"]["text"])

    def test_flatten_usd(self):
        r = self.client.flatten_usd("/tmp/flat.usdc", "/tmp/scene.usda")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["layer_count"], 5)

    def test_flatten_usd_current_stage(self):
        r = self.client.flatten_usd("/tmp/flat.usdc")
        self.assertEqual(r["status"], "success")
        # Verify no input_path was sent in body
        _, _, body = self.mock.requests[-1]
        self.assertNotIn("input_path", body)

    def test_export_prim(self):
        r = self.client.export_prim("/World/Component", "/tmp/component.usdc")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["materials_included"], 2)
        self.assertEqual(r["result"]["up_axis"], "Z")

    def test_set_variant_selection(self):
        r = self.client.set_variant_selection("/World/Server", "model", "shell")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["new_selection"], "shell")
        self.assertEqual(r["result"]["old_selection"], "focused")

    def test_create_variant_structure(self):
        r = self.client.create_variant_structure("/World/Server", "model", ["focused", "shell"])
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["variants_created"], ["focused", "shell"])
        self.assertEqual(r["result"]["default_selection"], "focused")

    def test_create_variant_structure_with_default(self):
        r = self.client.create_variant_structure(
            "/World/Server", "model", ["focused", "shell"], default_variant="shell"
        )
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["default_variant"], "shell")

    def test_compare_prims_direct(self):
        r = self.client.compare_prims(prim_path_a="/World/A", prim_path_b="/World/B")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["delta"]["face_reduction_pct"], -80.0)
        self.assertEqual(r["result"]["a"]["total_faces"], 10000)
        self.assertEqual(r["result"]["b"]["total_faces"], 2000)

    def test_compare_prims_variant(self):
        r = self.client.compare_prims(
            prim_path="/World/Server",
            variant_set="model",
            variant_a="focused",
            variant_b="shell",
        )
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["variant_set"], "model")
        self.assertEqual(body["variant_a"], "focused")
        self.assertEqual(body["variant_b"], "shell")

    def test_update_material_paths(self):
        r = self.client.update_material_paths("/Old/Looks", "/World/Looks", "/World")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["updated_count"], 5)
        self.assertEqual(len(r["result"]["updated_prims"]), 2)

    def test_camera_inspect_default_angles(self):
        """Default angles=None should not send angles in the request body (server defaults to all 14)."""
        r = self.client.camera_inspect("/World/Cube")
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertNotIn("angles", body)
        self.assertNotIn("zoom_offset", body)  # 0.0 default not sent
        self.assertNotIn("isolate", body)  # False default not sent

    def test_camera_inspect_with_zoom_offset(self):
        r = self.client.camera_inspect("/World/Cube", angles=["front"], zoom_offset=-0.3)
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertAlmostEqual(body["zoom_offset"], -0.3)

    def test_camera_inspect_with_isolate(self):
        r = self.client.camera_inspect("/World/Cube", angles=["front"], isolate=True)
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertTrue(body["isolate"])

    def test_camera_inspect_with_segmentation(self):
        r = self.client.camera_inspect("/World/Cube", angles=["front"], include_segmentation=True)
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertTrue(body.get("include_segmentation"))

    def test_camera_inspect_refuses_an_old_positional_distance(self):
        # The 5th positional used to be distance; it must not be read as a zoom_offset.
        with self.assertRaises(TypeError):
            self.client.camera_inspect("/World/Cube", None, 640, 480, 5.0)

    def test_viewport_light_get(self):
        r = self.client.viewport_light("get")
        self.assertEqual(r["status"], "success")
        self.assertIn("lighting_mode", r["result"])
        self.assertIn("available_modes", r["result"])
        self.assertIn("scene_lights", r["result"])
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["action"], "get")

    def test_viewport_light_set_mode(self):
        r = self.client.viewport_light("set", mode="Default")
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["action"], "set")
        self.assertEqual(body["mode"], "Default")

    def test_viewport_light_set_camera_light_legacy(self):
        r = self.client.viewport_light("set_camera_light", enabled=True)
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["action"], "set_camera_light")
        self.assertTrue(body["enabled"])

    def test_viewport_light_legacy_positional_enabled(self):
        # The old signature was viewport_light(action, enabled); mode must not take enabled's slot.
        self.client.viewport_light("set_camera_light", False)
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body, {"action": "set_camera_light", "enabled": False})

    def test_get_logs(self):
        r = self.client.get_logs(count=10, min_level="warn")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["count"], 1)
        self.assertEqual(r["result"]["entries"][0]["level"], "warn")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["count"], 10)
        self.assertEqual(body["min_level"], "warn")

    def test_get_logs_with_filters(self):
        r = self.client.get_logs(count=20, channel="omni.physx", search="warning")
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["channel"], "omni.physx")
        self.assertEqual(body["search"], "warning")

    def test_get_logs_default(self):
        r = self.client.get_logs()
        self.assertEqual(r["status"], "success")
        _, _, body = self.mock.requests[-1]
        self.assertEqual(body["count"], 50)
        self.assertNotIn("min_level", body)
        self.assertNotIn("channel", body)


def _reply(path: str) -> bytes:
    result = {"protocol": 1, "extension_version": "1.0.0"} if path == "/bridge" else {}
    data = json.dumps({"status": "success", "result": result}).encode()
    return b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\nConnection: keep-alive\r\n\r\n" % len(data) + data


def _read_request(conn: socket.socket) -> str:
    """The path of the next request on the connection, its body read and dropped; a ConnectionError once the client
    closes it."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("the client closed the connection")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    length = next((int(line.split(":", 1)[1]) for line in lines if line.lower().startswith("content-length:")), 0)
    while len(rest) < length:
        rest += conn.recv(4096)
    return lines[0].split(" ")[1]


class _ScriptedBridge(threading.Thread):
    """A bridge that takes connections one after another, each answering requests as its script says: "ok" answers in
    full, "cut" sends half the answer; then it closes the connection, as a bridge that drops a kept-alive one. A
    connection the client never makes ends the script after a second."""

    def __init__(self, *connections: list[str]):
        super().__init__(daemon=True)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.connections = connections
        self.paths: list[str] = []
        self.accepted = 0

    def run(self) -> None:
        with self.listener:
            self.listener.settimeout(1.0)
            for steps in self.connections:
                try:
                    conn, _ = self.listener.accept()
                except TimeoutError:
                    return
                self.accepted += 1
                with conn:
                    for step in steps:
                        path = _read_request(conn)
                        self.paths.append(path)
                        reply = _reply(path)
                        conn.sendall(reply if step == "ok" else reply[: len(reply) // 2])


def test_a_dropped_kept_alive_connection_is_retried_once_with_a_new_handshake():
    bridge = _ScriptedBridge(["ok", "ok"], ["ok", "ok"])
    bridge.start()
    client = BridgeClient(port=bridge.port, token="invented-test-token", timeout=5.0)
    try:
        client.health()
        # The bridge has closed the connection; the client finds out on the next request, before any reply.
        assert client.health()["status"] == "success"
    finally:
        client.close()
        bridge.join(5)
    assert bridge.accepted == 2
    assert bridge.paths == ["/bridge", "/health", "/bridge", "/health"]


def test_a_reply_cut_short_is_not_sent_again():
    # A second connection stands ready, so a retry would succeed and show.
    bridge = _ScriptedBridge(["ok", "ok", "cut"], ["ok", "ok"])
    bridge.start()
    client = BridgeClient(port=bridge.port, token="invented-test-token", timeout=5.0)
    try:
        client.health()
        # The request may have run: sending it again could run a script twice.
        with pytest.raises(ConnectionError):
            client.health()
    finally:
        client.close()
        bridge.join(5)
    assert bridge.accepted == 1
    assert bridge.paths == ["/bridge", "/health", "/health"]


def test_the_extension_version_follows_each_handshake():
    # A Kit restart with another release on the same protocol isn't refused; get_sim_state reports what this keeps.
    bridge = MockIsaacServer()
    bridge.start()
    client = BridgeClient(port=bridge.port, token="invented-test-token", timeout=5.0)
    try:
        for release in ("0.1.0", "0.2.0"):
            bridge.set_response(
                "/bridge", {"status": "success", "result": {"protocol": 1, "extension_version": release}}
            )
            client._disconnect()
            client.health()
            assert client.extension_version == release
    finally:
        client.close()
        bridge.stop()


class _SilentBridge(threading.Thread):
    """A bridge whose port takes every connection, as a hung Kit's still does, and answers each request only while
    `answering` is set; otherwise it reads the request and says nothing. The paths it read, in order."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.answering = False
        self.paths: list[str] = []
        self.connections = 0
        self._stopped = threading.Event()

    def run(self) -> None:
        self.listener.settimeout(0.05)
        while not self._stopped.is_set():
            try:
                conn, _ = self.listener.accept()
            except TimeoutError:
                continue
            self.connections += 1
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            try:
                while not self._stopped.is_set():
                    path = _read_request(conn)  # raises once the client gives up and closes the connection
                    self.paths.append(path)
                    while not self.answering and not self._stopped.is_set():
                        self._stopped.wait(0.02)
                    conn.sendall(_reply(path))
            except OSError:
                return

    def stop(self) -> None:
        self._stopped.set()
        self.join(5)
        self.listener.close()


@pytest.fixture
def silent(monkeypatch: pytest.MonkeyPatch) -> Iterator[_SilentBridge]:
    monkeypatch.setattr(client_module, "HEALTH_SECONDS", 0.3)
    bridge = _SilentBridge()
    bridge.start()
    yield bridge
    bridge.stop()


def test_a_call_kit_never_answers_is_named_once_health_is_silent_too(silent: _SilentBridge):
    client = BridgeClient(port=silent.port, token="invented-test-token", timeout=0.3)
    try:
        with pytest.raises(KitSilentError, match=r"stopped answering: a call got no answer in 0\.3 s") as first:
            client.health()
        assert f"127.0.0.1:{silent.port}" in str(first.value)
        assert "/health none in 0.3 s" in str(first.value)
        # The handshake went unanswered, then /health on a connection of its own.
        assert silent.paths == ["/bridge", "/health"]

        # Each later call asks /health first, and fails as fast while it stays silent: the call never goes.
        started = time.monotonic()
        with pytest.raises(KitSilentError, match="still silent"):
            client.scene_tree()
        assert time.monotonic() - started < 2
        assert silent.paths == ["/bridge", "/health", "/health"]

        # Kit answers again: the mark clears and the call goes, on a new connection with its handshake.
        silent.answering = True
        assert client.scene_tree()["status"] == "success"
        assert silent.paths[3:] == ["/health", "/bridge", "/scene/tree"]
        assert client.health()["status"] == "success"  # no /health asked first any more
        assert silent.paths[6:] == ["/health"]
    finally:
        client.close()


def test_a_call_that_times_out_on_a_kept_alive_connection_is_named_too(silent: _SilentBridge):
    client = BridgeClient(port=silent.port, token="invented-test-token", timeout=0.3)
    silent.answering = True
    try:
        assert client.health()["status"] == "success"
        silent.answering = False  # Kit hangs between two calls on one connection
        with pytest.raises(KitSilentError, match="stopped answering"):
            client.scene_tree()
        assert silent.paths == ["/bridge", "/health", "/scene/tree", "/health"]
    finally:
        client.close()


def test_a_port_nothing_listens_on_lets_the_connection_error_stand(silent: _SilentBridge, monkeypatch):
    # While the user restarts a hung Kit nothing listens on its port: each call says so, as before, not "still
    # silent ... restart the Kit app".
    client = BridgeClient(port=silent.port, token="invented-test-token", timeout=0.3)
    try:
        with pytest.raises(KitSilentError):
            client.health()
        silent.stop()
        monkeypatch.setattr(client_module, "HEALTH_SECONDS", 3.0)  # Windows refuses a closed port after about 2 s
        with pytest.raises(ConnectionRefusedError):
            client.health()
    finally:
        client.close()


def test_a_call_that_times_out_while_health_answers_keeps_its_timeout(silent: _SilentBridge, monkeypatch):
    client = BridgeClient(port=silent.port, token="invented-test-token", timeout=0.3)
    probes: list[bool] = []

    def answers(_client: BridgeClient) -> bool:
        probes.append(True)
        return True  # a slow call, not a stuck Kit

    monkeypatch.setattr(BridgeClient, "_answers", answers)
    try:
        with pytest.raises(TimeoutError) as timed_out:
            client.health()
        assert not isinstance(timed_out.value, KitSilentError)
        silent.answering = True
        assert client.health()["status"] == "success"
        assert probes == [True]  # the later call asked no /health first
    finally:
        client.close()


def test_a_connect_that_times_out_is_a_host_that_is_down(monkeypatch):
    # Not a stuck Kit: nothing connected, so no /health is asked and the error stays as it is.
    tried: list[object] = []

    def times_out(address: object, timeout: float | None = None) -> socket.socket:
        tried.append(address)
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", times_out)  # the module the client calls it through
    client = BridgeClient(port=8212, token="invented-test-token", timeout=0.3)
    with pytest.raises(TimeoutError) as timed_out:
        client.health()
    assert not isinstance(timed_out.value, KitSilentError)
    assert tried == [("127.0.0.1", 8212)]


if __name__ == "__main__":
    unittest.main()
