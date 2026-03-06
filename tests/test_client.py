"""
Unit tests for the IsaacSimClient HTTP client.

Uses a mock HTTP server to test all endpoints without needing Isaac Sim.
Run: python -m pytest tests/test_client.py -v
"""

import asyncio
import json
import threading
import time
import unittest

from isaac_sim_mcp.client import IsaacSimClient


class MockIsaacServer:
    """Minimal async HTTP server that mimics the Isaac Sim extension."""

    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.port = port
        self.server = None
        self.requests: list[tuple[str, str, dict]] = []
        self._responses: dict[str, dict] = {}

    def set_response(self, path: str, response: dict):
        self._responses[path] = response

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                request_line = await reader.readline()
                if not request_line:
                    break
                request_line = request_line.decode().strip()
                if not request_line:
                    continue
                parts = request_line.split(" ")
                method, path = parts[0], parts[1]
                content_length = 0
                while True:
                    header = await reader.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                    h = header.decode().strip()
                    if h.lower().startswith("content-length:"):
                        content_length = int(h.split(":", 1)[1].strip())
                body = {}
                if content_length > 0:
                    raw = await reader.readexactly(content_length)
                    body = json.loads(raw.decode())
                self.requests.append((method, path, body))
                response = self._responses.get(path, {"status": "success", "result": {}})
                body_bytes = json.dumps(response).encode()
                header_str = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    f"Connection: keep-alive\r\n\r\n"
                )
                writer.write(header_str.encode() + body_bytes)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    async def _start(self):
        self.server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self.server.sockets[0].getsockname()[1]

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        time.sleep(0.3)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start())
        self._loop.run_forever()

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


class TestIsaacSimClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock = MockIsaacServer()
        # Register mock responses for all endpoints
        cls.mock.set_response("/health", {"status": "success", "result": {"stage_path": "/test.usd", "up_axis": "Y", "meters_per_unit": 1.0, "recording_active": False}})
        cls.mock.set_response("/execute", {"status": "success", "result": {"stdout": "hello\n", "stderr": "", "return_value": 42}})
        cls.mock.set_response("/scene/tree", {"status": "success", "result": {"path": "/", "type": "Xform", "children": [{"path": "/World", "type": "Xform", "world_position": [0, 0, 0]}]}})
        cls.mock.set_response("/scene/dump", {"status": "success", "result": {"file_path": "/tmp/scene_dump.json", "file_size_bytes": 1234, "prim_count": 10, "root": "/"}})
        cls.mock.set_response("/scene/prim", {"status": "success", "result": {"prim_path": "/World", "type": "Xform", "is_active": True, "properties": {}}})
        cls.mock.set_response("/scene/bounds", {"status": "success", "result": {"prim_path": "/World/Cube", "center": [0, 0.5, 0], "dimensions": [1, 1, 1], "min": [-0.5, 0, -0.5], "max": [0.5, 1, 0.5], "max_dimension": 1.0, "diagonal": 1.732}})
        cls.mock.set_response("/scene/transform", {"status": "success", "result": {"prim_path": "/World/Box", "message": "Transform updated"}})
        cls.mock.set_response("/scene/create", {"status": "success", "result": {"prim_path": "/World/NewCube", "type": "Cube"}})
        cls.mock.set_response("/scene/delete", {"status": "success", "result": {"prim_path": "/World/Old", "message": "Prim deleted"}})
        cls.mock.set_response("/scene/material", {"status": "success", "result": {"prim_path": "/World/Cube", "material_path": "/World/Looks/Cube_Mat", "color": [1, 0, 0], "roughness": 0.5, "metallic": 0.0, "opacity": 1.0}})
        cls.mock.set_response("/scene/clone", {"status": "success", "result": {"source": "/World/Cube", "clones": ["/World/Cube_Clone"], "count": 1}})
        cls.mock.set_response("/scene/visibility", {"status": "success", "result": {"prim_path": "/World/Cube", "visible": False}})
        cls.mock.set_response("/scene/save", {"status": "success", "result": {"file_path": "/tmp/scene.usd", "action": "saved"}})
        cls.mock.set_response("/scene/new", {"status": "success", "result": {"message": "New scene created"}})
        cls.mock.set_response("/robot/create", {"status": "success", "result": {"prim_path": "/World/G1", "robot_type": "g1", "usd_path": "/Isaac/Robots/Unitree/G1/g1.usd", "joints": []}})
        cls.mock.set_response("/robot/info", {"status": "success", "result": {"prim_path": "/World/G1", "dof_count": 43, "link_count": 20, "joints": [{"name": "left_hip_pitch_joint", "type": "PhysicsRevoluteJoint"}]}})
        cls.mock.set_response("/robot/joint_states", {"status": "success", "result": {"prim_path": "/World/G1", "dof_count": 43, "positions": [0.0] * 43}})
        cls.mock.set_response("/robot/joint_targets", {"status": "success", "result": {"prim_path": "/World/G1", "targets_set": 1}})
        cls.mock.set_response("/sim/control", {"status": "success", "result": {"action": "play", "current_state": "playing"}})
        cls.mock.set_response("/sim/state", {"status": "success", "result": {"state": "stopped", "current_time": 0.0, "fps": 60.0, "prim_count": 5, "up_axis": "Y", "meters_per_unit": 1.0, "recording_active": False}})
        cls.mock.set_response("/sim/capture", {"status": "success", "result": {"image_base64": "iVBORw0KGgo=", "width": 1280, "height": 720, "camera_path": "/OmniverseKit_Persp", "format": "png"}})
        cls.mock.set_response("/camera/set", {"status": "success", "result": {"camera_path": "/OmniverseKit_Persp", "position": [5, 3, 5], "target": [0, 0, 0]}})
        cls.mock.set_response("/camera/look_at", {"status": "success", "result": {"camera_path": "/OmniverseKit_Persp", "camera_position": [2, 1.5, 2], "target": [0, 0.5, 0], "distance": 3.0, "azimuth": 45.0, "elevation": 30.0}})
        cls.mock.set_response("/camera/inspect", {"status": "success", "result": {"prim_path": "/World/Cube", "center": [0, 0.5, 0], "distance": 2.5, "captures": [{"angle": "front", "azimuth": 0, "elevation": 20, "camera_position": [0, 1, 2.3], "image_base64": "iVBORw0KGgo="}]}})
        cls.mock.set_response("/recording/start", {"status": "success", "result": {"session_id": "rec_123", "output_dir": "/tmp/rec_123", "fps": 5, "resolution": [640, 480], "camera_path": "/OmniverseKit_Persp"}})
        cls.mock.set_response("/recording/stop", {"status": "success", "result": {"session_id": "rec_123", "output_dir": "/tmp/rec_123", "frame_count": 15, "duration_seconds": 3.0, "metadata_file": "/tmp/rec_123/metadata.json"}})
        cls.mock.set_response("/recording/frame", {"status": "success", "result": {"frame_index": 0, "image_base64": "iVBORw0KGgo=", "format": "png", "sim_time": 0.0, "wall_time": 0.0}})
        cls.mock.set_response("/extensions/list", {"status": "success", "result": {"count": 2, "extensions": [{"id": "omni.replicator.core", "name": "Replicator Core", "enabled": True, "version": "1.0.0"}, {"id": "omni.physx", "name": "PhysX", "enabled": True, "version": "1.0.0"}]}})
        cls.mock.set_response("/extensions/manage", {"status": "success", "result": {"extension_id": "omni.test.ext", "action": "enable", "enabled": True}})
        cls.mock.set_response("/physics/properties", {"status": "success", "result": {"prim_path": "/World/Cube", "applied": ["MassAPI", "PhysicsMaterial"]}})
        cls.mock.set_response("/physics/apply_force", {"status": "success", "result": {"prim_path": "/World/Cube", "method": "velocity", "force": [100, 0, 0]}})
        cls.mock.set_response("/physics/raycast", {"status": "success", "result": {"hit": True, "prim_path": "/World/Ground", "position": [0, 0, 0], "normal": [0, 1, 0], "distance": 10.0}})
        cls.mock.set_response("/debug/draw", {"status": "success", "result": {"drawn": [{"type": "line", "start": [0, 0, 0], "end": [1, 1, 0]}]}})
        cls.mock.start()

    @classmethod
    def tearDownClass(cls):
        cls.mock.stop()

    def setUp(self):
        self.client = IsaacSimClient(host="127.0.0.1", port=self.mock.port, timeout=5.0)
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

    def test_capture_viewport(self):
        r = self.client.capture_viewport(1280, 720)
        self.assertIn("image_base64", r["result"])

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
            "/tmp", fps=5, track_prims=["/World/G1"],
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

    def test_save_scene(self):
        r = self.client.save_scene("/tmp/scene.usd")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["file_path"], "/tmp/scene.usd")

    def test_new_scene(self):
        r = self.client.new_scene()
        self.assertEqual(r["status"], "success")

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
        self.assertEqual(len(self.mock.requests), 3)

    def test_reconnect_after_disconnect(self):
        self.client.health()
        self.client._disconnect()
        r = self.client.health()
        self.assertEqual(r["status"], "success")


if __name__ == "__main__":
    unittest.main()
