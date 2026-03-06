"""
Integration test for the Isaac Sim MCP Bridge.

Requires Isaac Sim to be running with the isaacsim.mcp.bridge extension enabled.

Usage:
    python -m pytest tests/test_integration.py -v
    python tests/test_integration.py
"""

import json
import sys
import unittest

from isaac_sim_mcp.client import IsaacSimClient


class TestIsaacSimIntegration(unittest.TestCase):
    """Integration tests that run against a live Isaac Sim instance."""

    @classmethod
    def setUpClass(cls):
        cls.client = IsaacSimClient(host="127.0.0.1", port=8211, timeout=30.0)
        try:
            result = cls.client.health()
            if result.get("status") != "success":
                raise ConnectionError(f"Health check failed: {result}")
            print(f"\nConnected to Isaac Sim: {json.dumps(result['result'], indent=2)}")
        except Exception as e:
            raise unittest.SkipTest(
                f"Cannot connect to Isaac Sim at 127.0.0.1:8211. "
                f"Start Isaac Sim with isaacsim.mcp.bridge extension. Error: {e}"
            )

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

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

    def test_07_create_and_delete_prim(self):
        # Create
        result = self.client.create_prim(
            "/World/MCPTestCube", "Cube",
            position=[2, 0, 0.5], scale=0.3
        )
        self.assertEqual(result["status"], "success")
        print(f"  Created: {result['result']['prim_path']}")

        # Verify it exists
        result = self.client.prim_properties("/World/MCPTestCube")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["type"], "Cube")

        # Delete
        result = self.client.delete_prim("/World/MCPTestCube")
        self.assertEqual(result["status"], "success")
        print(f"  Deleted: /World/MCPTestCube")

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
        print(f"  Transform set for /World/MCPTestXform")

        # Clean up
        self.client.delete_prim("/World/MCPTestXform")

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

    def test_10_capture_viewport(self):
        result = self.client.capture_viewport(640, 480)
        if result["status"] == "error" and "replicator" in result.get("error", "").lower():
            self.skipTest("Replicator not available")
        self.assertEqual(result["status"], "success")
        self.assertIn("image_base64", result["result"])
        img_size = len(result["result"]["image_base64"])
        print(f"  Captured {result['result']['width']}x{result['result']['height']}, base64 size: {img_size}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
