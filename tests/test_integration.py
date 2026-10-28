"""
Integration test for the Omniverse MCP Bridge (ovmcp.bridge).

Requires Isaac Sim to be running with the ovmcp.bridge extension enabled.

Usage, with Kit running: OMNIVERSE_MCP_SIM=1 uv run pytest -m sim
"""

import json
import unittest

import pytest

from omniverse_mcp.client import BridgeClient

from .conftest import live_bridge

pytestmark = pytest.mark.sim


class TestIsaacSimIntegration(unittest.TestCase):
    """Integration tests that run against a live Isaac Sim instance."""

    @classmethod
    def setUpClass(cls):
        # It runs only with OMNIVERSE_MCP_SIM=1 (conftest.py), so a bridge that doesn't answer is a failure.
        host, port = live_bridge()
        cls.client = BridgeClient(host=host, port=port, timeout=30.0)
        result = cls.client.health()
        if result.get("status") != "success":
            raise ConnectionError(f"Health check failed at {host}:{port}: {result}")
        print(f"\nConnected to Isaac Sim: {json.dumps(result['result'], indent=2)}")
        # Ensure sim is stopped and create a clean scene
        cls.client.sim_control("stop")
        cls.client.capture_viewport(320, 240)  # Warmup capture pipeline

    @classmethod
    def tearDownClass(cls):
        # Clean up test prims
        for path in ["/World/IntTestCube", "/World/IntTestLight", "/World/IntTestClone", "/World/IntTestRobot"]:
            try:
                cls.client.delete_prim(path)
            except Exception:
                pass
        cls.client.close()

    # ===== Basic connectivity =====

    def test_01_health(self):
        result = self.client.health()
        self.assertEqual(result["status"], "success")
        self.assertIn("up_axis", result["result"])
        print(f"  Stage: {result['result']}")

    def test_02_sim_state(self):
        result = self.client.sim_state()
        self.assertEqual(result["status"], "success")
        print(f"  State: {result['result']['state']}, Prims: {result['result']['prim_count']}")

    def test_03_scene_tree(self):
        result = self.client.scene_tree("/", 3)
        self.assertEqual(result["status"], "success")
        print(f"  Root type: {result['result']['type']}")
        if "children" in result["result"]:
            for child in result["result"]["children"][:5]:
                print(f"    {child['path']} ({child['type']})")

    # ===== Script execution =====

    def test_04_execute_script_stdout(self):
        result = self.client.execute("print('Hello from Isaac Sim!')")
        self.assertEqual(result["status"], "success")
        self.assertIn("Hello from Isaac Sim!", result["result"]["stdout"])
        print(f"  stdout: {result['result']['stdout'].strip()}")

    def test_05_execute_script_return_value(self):
        result = self.client.execute("""
import omni.usd
stage = omni.usd.get_context().get_stage()
result = {"root_prims": [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]}
""")
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["result"]["return_value"])
        print(f"  Return: {result['result']['return_value']}")

    def test_06_execute_script_error(self):
        result = self.client.execute("raise ValueError('test error')")
        self.assertEqual(result["status"], "error")
        self.assertIn("test error", result["error"])
        print(f"  Error caught correctly: {result['error']}")

    # ===== Scene manipulation =====

    def test_07_create_and_delete_prim(self):
        # Create
        result = self.client.create_prim("/World/MCPTestCube", "Cube", position=[2, 0, 0.5], scale=0.3)
        self.assertEqual(result["status"], "success")
        print(f"  Created: {result['result']['prim_path']}")

        # Verify it exists
        result = self.client.prim_properties("/World/MCPTestCube")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["type"], "Cube")

        # Delete
        result = self.client.delete_prim("/World/MCPTestCube")
        self.assertEqual(result["status"], "success")
        print("  Deleted: /World/MCPTestCube")

    def test_08_set_transform(self):
        # Create a test prim
        self.client.create_prim("/World/MCPTestXform", "Xform")

        # Set transform
        result = self.client.set_transform(
            "/World/MCPTestXform",
            position=[1, 2, 3],
            rotation=[0, 45, 0],
            scale=2.0,
        )
        self.assertEqual(result["status"], "success")
        print("  Transform set for /World/MCPTestXform")

        # Clean up
        self.client.delete_prim("/World/MCPTestXform")

    # ===== Simulation =====

    def test_09_sim_control(self):
        # Play
        result = self.client.sim_control("play")
        self.assertEqual(result["status"], "success")
        print(f"  After play: {result['result']['current_state']}")

        # Pause
        result = self.client.sim_control("pause")
        self.assertEqual(result["status"], "success")
        print(f"  After pause: {result['result']['current_state']}")

        # Stop
        result = self.client.sim_control("stop")
        self.assertEqual(result["status"], "success")
        print(f"  After stop: {result['result']['current_state']}")

    # ===== Capture & Camera =====

    def test_10_capture_viewport(self):
        result = self.client.capture_viewport(640, 480)
        if result["status"] == "error" and "replicator" in result.get("error", "").lower():
            self.skipTest("Replicator not available")
        self.assertEqual(result["status"], "success")
        self.assertIn("image_base64", result["result"])
        self.assertIn("lighting_mode", result["result"])
        img_size = len(result["result"]["image_base64"])
        print(
            f"  Captured {result['result']['width']}x{result['result']['height']}, "
            f"lighting: {result['result']['lighting_mode']}, base64 size: {img_size}"
        )

    def test_11_camera_set(self):
        result = self.client.camera_set([5, 3, 5], [0, 0, 0])
        self.assertEqual(result["status"], "success")
        self.assertIn("position", result["result"])
        print(f"  Camera at {result['result']['position']}")

    def test_12_camera_look_at(self):
        # Create something to look at
        self.client.create_prim("/World/IntTestCube", "Cube", position=[0, 0.5, 0], scale=[0.3, 0.3, 0.3])
        result = self.client.camera_look_at("/World/IntTestCube", azimuth=45, elevation=30)
        self.assertEqual(result["status"], "success")
        self.assertGreater(result["result"]["distance"], 0)
        print(f"  Looking at IntTestCube, dist={result['result']['distance']:.2f}m")

    def test_13_camera_inspect_auto_fit(self):
        """Inspect with auto-fit distance (no zoom_offset)."""
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["result"]["captures"]), 2)
        self.assertGreater(result["result"]["distance"], 0)
        for cap in result["result"]["captures"]:
            self.assertIn("image_base64", cap)
        print(f"  Inspect auto-fit: dist={result['result']['distance']:.2f}m, 2 angles")

    def test_14_camera_inspect_zoom_offset(self):
        """Inspect with zoom_offset should change distance."""
        r_default = self.client.camera_inspect("/World/IntTestCube", angles=["front"])
        r_closer = self.client.camera_inspect("/World/IntTestCube", angles=["front"], zoom_offset=-0.3)
        self.assertEqual(r_default["status"], "success")
        self.assertEqual(r_closer["status"], "success")
        self.assertLess(r_closer["result"]["distance"], r_default["result"]["distance"])
        print(
            f"  Default dist={r_default['result']['distance']:.2f}m, "
            f"zoom_offset=-0.3 dist={r_closer['result']['distance']:.2f}m"
        )

    def test_15_camera_inspect_isolate(self):
        """Inspect with isolate=True."""
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front"], isolate=True)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["result"].get("isolate", False))
        self.assertEqual(len(result["result"]["captures"]), 1)
        print(f"  Isolated inspect OK, dist={result['result']['distance']:.2f}m")

    # ===== Viewport lighting =====

    def test_16_viewport_light_get(self):
        result = self.client.viewport_light("get")
        self.assertEqual(result["status"], "success")
        self.assertIn("lighting_mode", result["result"])
        self.assertIn("available_modes", result["result"])
        modes = result["result"]["available_modes"]
        self.assertIn("camera", modes)
        self.assertIn("stage", modes)
        print(f"  Lighting mode: {result['result']['lighting_mode']}, modes: {', '.join(modes)}")

    def test_17_viewport_light_set(self):
        # Set to camera light
        result = self.client.viewport_light("set", mode="camera")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["lighting_mode"], "camera")
        print("  Set to camera mode")

        # Set to Default rig
        result = self.client.viewport_light("set", mode="Default")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["lighting_mode"], "Default")
        print("  Set to Default rig")

    def test_18_viewport_light_legacy(self):
        """Legacy set_camera_light action still works."""
        result = self.client.viewport_light("set_camera_light", enabled=True)
        self.assertEqual(result["status"], "success")
        print("  Legacy set_camera_light OK")

    # ===== Materials & Visibility =====

    def test_19_set_material(self):
        result = self.client.set_material("/World/IntTestCube", color=[1, 0, 0], roughness=0.3)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["color"], [1, 0, 0])
        # Named by its MDL source, which Kit resolves; an id alone rendered Kit's red error material (#30).
        path = f"{result['result']['material_path']}/Shader"
        shader = self.client.execute(
            "from pxr import UsdShade\n"
            f"s = UsdShade.Shader(omni.usd.get_context().get_stage().GetPrimAtPath('{path}'))\n"
            "result = [str(s.GetImplementationSource()), s.GetSourceAsset('mdl').path]"
        )
        self.assertEqual(shader["result"]["return_value"], ["sourceAsset", "OmniPBR.mdl"])
        print(f"  Material set: color={result['result']['color']}, roughness={result['result']['roughness']}")

    def test_20_visibility(self):
        # Hide
        result = self.client.set_visibility("/World/IntTestCube", visible=False)
        self.assertEqual(result["status"], "success")
        # Show
        result = self.client.set_visibility("/World/IntTestCube", visible=True)
        self.assertEqual(result["status"], "success")
        print("  Visibility toggle OK")

    def test_21_clone_and_create_refuse_to_overwrite(self):
        guard, clone, row = "/World/IntTestGuard", "/World/IntTestGuardClone", "/World/IntTestGuardRow"
        try:
            self.assertEqual(self.client.create_prim(guard, "Cube")["status"], "success")
            # The same type again is a no-op; another type would retype it.
            self.assertEqual(self.client.create_prim(guard, "Cube", position=[0, 0, 1])["status"], "success")
            result = self.client.create_prim(guard, "Sphere")
            self.assertEqual(result["status"], "error")
            self.assertIn("already a Cube", result["error"])
            self.assertEqual(self.client.prim_properties(guard)["result"]["type"], "Cube")

            self.assertEqual(self.client.clone_prim(guard, clone)["status"], "success")
            result = self.client.clone_prim(guard, clone)
            self.assertEqual(result["status"], "error")
            self.assertIn(clone, result["error"])

            # One taken path in a batch refuses the whole batch, before any copy.
            self.assertEqual(self.client.create_prim(f"{row}_002", "Xform")["status"], "success")
            result = self.client.clone_prim(guard, row, count=3)
            self.assertEqual(result["status"], "error")
            self.assertEqual(self.client.prim_properties(f"{row}_001")["status"], "error")
            self.assertEqual(self.client.prim_properties(f"{row}_002")["result"]["type"], "Xform")
        finally:
            for path in (guard, clone, f"{row}_002"):
                self.client.delete_prim(path)

    def test_21_clone_prim(self):
        result = self.client.clone_prim("/World/IntTestCube", "/World/IntTestClone")
        self.assertEqual(result["status"], "success")
        print(f"  Cloned to {result['result'].get('clones', ['?'])[0]}")
        # Clean up
        self.client.delete_prim("/World/IntTestClone")

    # ===== Bounds & Mesh =====

    def test_22_prim_bounds(self):
        result = self.client.prim_bounds("/World/IntTestCube")
        self.assertEqual(result["status"], "success")
        self.assertIn("center", result["result"])
        self.assertIn("dimensions", result["result"])
        print(f"  Bounds: center={result['result']['center']}, dims={result['result']['dimensions']}")

    def test_23_mesh_stats(self):
        """Procedural prims return 0 faces (expected)."""
        result = self.client.mesh_stats("/World/IntTestCube")
        self.assertEqual(result["status"], "success")
        # Procedural Cube has no UsdGeom.Mesh, so 0 faces expected
        self.assertEqual(result["result"]["total_faces"], 0)
        print(f"  Procedural cube: {result['result']['total_faces']} faces (expected 0)")

    # ===== Logs =====

    def test_24_get_logs(self):
        result = self.client.get_logs(count=10)
        self.assertEqual(result["status"], "success")
        self.assertIn("entries", result["result"])
        self.assertIn("total_captured", result["result"])
        print(f"  Logs: {result['result']['count']} entries, total captured: {result['result']['total_captured']}")

    # ===== Error handling =====

    def test_25_invalid_prim(self):
        result = self.client.prim_properties("/World/Nonexistent_IntTest")
        self.assertEqual(result["status"], "error")
        print("  Error on invalid prim: OK")

    def test_26_invalid_sim_action(self):
        result = self.client.sim_control("invalid_action_xyz")
        self.assertEqual(result["status"], "error")
        print("  Error on invalid action: OK")

    # ===== Cleanup =====

    def test_99_cleanup(self):
        """Clean up test prims."""
        for path in [
            "/World/IntTestCube",
            "/World/IntTestLight",
            "/World/IntTestClone",
            "/World/IntTestRobot",
            "/World/Looks",
        ]:
            self.client.delete_prim(path)
        print("  Cleanup done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
