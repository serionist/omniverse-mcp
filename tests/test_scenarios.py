"""
Full scenario tests against live Isaac Sim.
Covers phases 1-17, 22-23, and 24-26 from test_project/scenarios.md.

Usage, with Kit running: OMNIVERSE_MCP_SIM=1 uv run pytest -m scenario
"""

import json
import os
import time
import unittest

import pytest

from omniverse_mcp.client import BridgeClient

from .conftest import live_bridge

pytestmark = pytest.mark.scenario


def _check_bridge(host: str, port: int) -> None:
    """Fail unless the bridge answers: the suite runs only with OMNIVERSE_MCP_SIM=1 (conftest.py)."""
    c = BridgeClient(host=host, port=port, timeout=2.0)
    try:
        r = c.health()
    finally:
        c.close()
    if r["status"] != "success":
        raise ConnectionError(f"Health check failed at {host}:{port}: {r}")


def _along_up(up: int, value: float, x: float = 0.0) -> list[float]:
    """`value` along the up axis (index `up`), `x` along X, 0 on the third: a point at that height, or a turn about
    the up axis."""
    vector = [x, 0.0, 0.0]
    vector[up] = value
    return vector


# draw_debug's backend on Isaac Sim, and the lines it holds, ours and any other code's: 0 while it is off.
DRAW_BACKEND = "isaacsim.util.debug_draw"
LINE_COUNT = (
    "import omni.kit.app\n"
    f"if omni.kit.app.get_app().get_extension_manager().is_extension_enabled('{DRAW_BACKEND}'):\n"
    "    from isaacsim.util.debug_draw import _debug_draw\n"
    "    result = _debug_draw.acquire_debug_draw_interface().get_num_lines()\n"
    "else:\n"
    "    result = 0\n"
)
# Strongly red pixels in a capture, red above green and blue by 80, counted in Kit with the numpy and Pillow Isaac Sim
# ships. A drawing is the only red in a view aimed away from /World/RedCube.
RED_PIXELS = (
    "import base64, io\n"
    "import numpy as np\n"
    "from PIL import Image\n"
    "cap = await mcp.capture_viewport(width=320, height=240)\n"
    "png = base64.b64decode(cap['result']['image_base64'])\n"
    "rgb = np.asarray(Image.open(io.BytesIO(png)).convert('RGB')).astype(np.int32)\n"
    "red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]\n"
    "result = int(((red - green > 80) & (red - blue > 80)).sum())\n"
)


class TestScenarios(unittest.TestCase):
    """Full scenario tests matching test_project/scenarios.md."""

    @classmethod
    def setUpClass(cls):
        host, port = live_bridge()
        _check_bridge(host, port)
        cls.c = BridgeClient(host=host, port=port, timeout=10.0)
        # Stop sim and clean up before starting
        cls.c.sim_control("stop")
        # Warmup viewport capture pipeline (first capture after connect is slow)
        cls.c.capture_viewport(320, 240)
        # Track results
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        # Cleanup
        for path in [
            "/World/Ground",
            "/World/InspectTarget",
            "/World/SegmentationCube",
            "/World/RedCube",
            "/World/BlueSphere",
            "/World/Light",
            "/World/G1",
            "/World/PhysicsScene",
            "/World/Looks",
            "/World/RedCube_Clone",
            "/World/CloneBatch_001",
            "/World/CloneBatch_002",
            "/World/CloneBatch_003",
            "/World/PhysicsMaterials",
        ]:
            try:
                cls.c.delete_prim(path)
            except Exception:
                pass
        cls.c.sim_control("stop")
        cls.c.close()

        # Write results
        results_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results")
        os.makedirs(results_dir, exist_ok=True)
        results_path = os.path.join(results_dir, "test_results.md")
        with open(results_path, "w") as f:
            f.write("# Test Results\n\n")
            f.write("| # | Test | Result |\n")
            f.write("|---|------|--------|\n")
            for i, (name, status) in enumerate(cls.results, 1):
                f.write(f"| {i} | {name} | {status} |\n")
        print(f"\nResults written to: {results_path}")

    def _record(self, status):
        self.results.append((self._testMethodName, status))

    def _pass(self):
        self._record("PASS")

    def _up_axis(self) -> int:
        """The stage's up axis as the bridge reads it now: 1 for Y, 2 for Z. Never assumed: Isaac Sim opens a Z-up
        stage, and 17.2's new_scene leaves a Y-up one to the next run, so a first run and a later one differ (#6)."""
        r = self.c.sim_state()
        self.assertEqual(r["status"], "success", r)
        up = r["result"]["up_axis"]
        self.assertIn(up, ("Y", "Z"))
        return 2 if up == "Z" else 1

    def _line_count(self) -> int:
        r = self.c.execute(LINE_COUNT)
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _wait_for_line_count(self, count: int, timeout: float = 10.0) -> None:
        """Waits until isaacsim.util.debug_draw holds `count` lines; fails after `timeout` seconds."""
        deadline = time.monotonic() + timeout
        while (now := self._line_count()) != count:
            if time.monotonic() > deadline:
                self.fail(f"debug_draw holds {now} lines, not {count}, after {timeout} s")
            time.sleep(0.1)

    def _lines_go_after_the_test(self) -> int:
        """The line count now, and a cleanup that waits for it again: a test's drawings expire before the next test
        counts or captures."""
        start = self._line_count()
        self.addCleanup(self._wait_for_line_count, start)
        return start

    def _red_pixels(self) -> int:
        r = self.c.execute(RED_PIXELS)
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _choose_backend(self, *names: str) -> str:
        """The bridge's choose_backend, through execute: the first of `names` it can draw with, or the default."""
        r = self.c.execute(
            f"from ovmcp.bridge.handlers.debug_draw import choose_backend\nresult = choose_backend({names or ''})"
        )
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _aim_away(self) -> list[list[float]]:
        """Aims the camera along +X from x=20, away from all the suite puts near the origin (the red cube, the ground,
        the robot), and returns a zigzag five units ahead that crosses the view."""
        up = self._up_axis()
        r = self.c.camera_set(_along_up(up, 1, x=20), _along_up(up, 1, x=30))
        self.assertEqual(r["status"], "success", r)
        side = 3 - up  # the axis that is neither X nor up
        zigzag = []
        for i, across in enumerate([-2, -1, 0, 1, 2]):
            point = _along_up(up, 0.2 if i % 2 == 0 else 1.8, x=25)
            point[side] = across
            zigzag.append(point)
        return zigzag

    # ===== Phase 1: Connectivity =====

    def test_01_01_health_check(self):
        """Phase 1.1: Health Check"""
        r = self.c.sim_state()
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertIn("up_axis", result)
        self.assertIn("prim_count", result)
        print(f"  up_axis={result['up_axis']}, prims={result['prim_count']}")
        self._pass()

    def test_01_02_scene_tree_empty(self):
        """Phase 1.2: Scene Tree"""
        r = self.c.scene_tree("/", 3)
        self.assertEqual(r["status"], "success")
        self.assertIn("path", r["result"])
        print(f"  Root: {r['result']['path']}")
        self._pass()

    # ===== Phase 2: Scene Manipulation =====

    def test_02_01_create_primitives(self):
        """Phase 2.1: Create Primitives"""
        # Heights go along the stage's up axis, so the ground is a floor the cube falls onto (5.3, 7.1) on either.
        up = self._up_axis()
        flat = [10.0, 10.0, 10.0]
        flat[up] = 0.1
        r1 = self.c.create_prim("/World/Ground", "Cube", position=_along_up(up, -0.05), scale=flat)
        self.assertEqual(r1["status"], "success")
        r2 = self.c.create_prim("/World/RedCube", "Cube", position=_along_up(up, 2), scale=[0.3, 0.3, 0.3])
        self.assertEqual(r2["status"], "success")
        r3 = self.c.create_prim("/World/BlueSphere", "Sphere", position=_along_up(up, 0.5, x=1), scale=[0.2, 0.2, 0.2])
        self.assertEqual(r3["status"], "success")
        r4 = self.c.create_prim("/World/Light", "DistantLight", rotation=[45, 0, 0])
        self.assertEqual(r4["status"], "success")

        # Apply materials so objects are visually distinct
        r_red = self.c.set_material("/World/RedCube", color=[1, 0, 0])
        self.assertEqual(r_red["status"], "success")
        r_blue = self.c.set_material("/World/BlueSphere", color=[0.2, 0.4, 1.0])
        self.assertEqual(r_blue["status"], "success")
        r_gray = self.c.set_material("/World/Ground", color=[0.4, 0.4, 0.4], roughness=0.8)
        self.assertEqual(r_gray["status"], "success")

        tree = self.c.scene_tree("/World", 2)
        tree_str = json.dumps(tree["result"])
        for name in ["Ground", "RedCube", "BlueSphere", "Light"]:
            self.assertIn(name, tree_str)
        print("  Created 4 prims with materials")
        self._pass()

    def test_02_02_transform_operations(self):
        """Phase 2.2: Transform Operations"""
        up = self._up_axis()
        r = self.c.set_transform("/World/RedCube", position=_along_up(up, 2, x=2))
        self.assertEqual(r["status"], "success")
        r = self.c.set_transform("/World/RedCube", rotation=_along_up(up, 45))
        self.assertEqual(r["status"], "success")
        r = self.c.set_transform("/World/RedCube", scale=[0.5, 0.5, 0.5])
        self.assertEqual(r["status"], "success")
        print("  Transform updated")
        self._pass()

    def test_02_03_delete_prim(self):
        """Phase 2.3: Delete Prim"""
        r = self.c.delete_prim("/World/BlueSphere")
        self.assertEqual(r["status"], "success")

        tree = self.c.scene_tree("/World", 2)
        # Check prim path is gone (material BlueSphere_Mat may still exist under /World/Looks)
        tree_str = json.dumps(tree["result"])
        self.assertNotIn('/World/BlueSphere"', tree_str)

        r = self.c.delete_prim("/World/Nonexistent")
        self.assertEqual(r["status"], "error")
        print("  Delete OK, error on missing: OK")
        self._pass()

    def test_02_04_bounding_box(self):
        """Phase 2.4: Bounding Box"""
        r = self.c.prim_bounds("/World/RedCube")
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertIn("center", result)
        self.assertIn("dimensions", result)
        self.assertIn("diagonal", result)
        print(f"  center={result['center']}, dims={result['dimensions']}")
        self._pass()

    def test_02_05_spatial_reasoning(self):
        """Phase 2.5: Spatial Reasoning"""
        up = self._up_axis()
        ground = self.c.prim_bounds("/World/Ground")["result"]
        cube = self.c.prim_bounds("/World/RedCube")["result"]

        ground_top = ground["max"][up]
        cube_half_h = cube["dimensions"][up] / 2.0
        target = ground_top + cube_half_h

        r = self.c.set_transform("/World/RedCube", position=_along_up(up, target))
        self.assertEqual(r["status"], "success")

        new_bounds = self.c.prim_bounds("/World/RedCube")["result"]
        # Cube center should be above ground top
        self.assertGreater(new_bounds["center"][up], ground_top - 0.1)
        print(f"  Placed cube at {'XYZ'[up]}={target:.3f}, ground_top={ground_top:.3f}")
        self._pass()

    # ===== Phase 3: Camera & Visual =====

    def test_03_01_viewport_capture(self):
        """Phase 3.1: Basic Viewport Capture"""
        time.sleep(0.5)  # Let renderer settle
        r = self.c.capture_viewport(640, 480)
        self.assertEqual(r["status"], "success", f"Capture failed: {r.get('error', '')}")
        self.assertIn("image_base64", r["result"])
        self.assertGreater(len(r["result"]["image_base64"]), 100)
        print(f"  Captured {r['result']['width']}x{r['result']['height']}")
        self._pass()

    def test_03_02_camera_positioning(self):
        """Phase 3.2: Camera Positioning"""
        r = self.c.camera_set([5, 3, 5], [0, 0, 0])
        self.assertEqual(r["status"], "success")
        cap = self.c.capture_viewport(640, 480)
        self.assertEqual(cap["status"], "success")
        print("  Camera set + captured")
        self._pass()

    def test_03_03_look_at_prim(self):
        """Phase 3.3: Look At Prim"""
        r = self.c.camera_look_at("/World/RedCube", azimuth=0, elevation=20)
        self.assertEqual(r["status"], "success")
        time.sleep(0.3)  # Let viewport settle after camera move
        cap = self.c.capture_viewport(640, 480)
        self.assertEqual(cap["status"], "success")
        print(f"  Looking at RedCube, distance={r['result']['distance']}")
        self._pass()

    def test_03_04_look_at_auto_distance(self):
        """Phase 3.4: Look At with Auto-Distance"""
        r = self.c.camera_look_at("/World/Ground")
        self.assertEqual(r["status"], "success")
        self.assertGreater(r["result"]["distance"], 0)
        print(f"  Auto distance={r['result']['distance']:.2f}m")
        self._pass()

    def test_03_05_multi_angle_inspect(self):
        """Phase 3.5: Multi-Angle Inspect"""
        r = self.c.camera_inspect("/World/RedCube", angles=["front", "right", "top"])
        self.assertEqual(r["status"], "success")
        captures = r["result"]["captures"]
        self.assertEqual(len(captures), 3)
        for cap in captures:
            self.assertIn("image_base64", cap)
        # Auto-fit distance should be computed
        self.assertGreater(r["result"]["distance"], 0)
        print(f"  3 angles captured, auto-fit dist={r['result']['distance']:.2f}m")
        self._pass()

    # ===== Phase 4: Script Execution =====

    def test_04_01_basic_print(self):
        """Phase 4.1: Basic Print"""
        r = self.c.execute("print('Hello MCP!')")
        self.assertEqual(r["status"], "success")
        self.assertIn("Hello MCP!", r["result"]["stdout"])
        self._pass()

    def test_04_02_return_value(self):
        """Phase 4.2: Return Value"""
        r = self.c.execute("result = {'version': 1, 'test': True}")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["return_value"], {"version": 1, "test": True})
        self._pass()

    def test_04_03_usd_api_access(self):
        """Phase 4.3: USD API Access"""
        r = self.c.execute(
            "stage = omni.usd.get_context().get_stage(); result = [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]"
        )
        self.assertEqual(r["status"], "success")
        paths = r["result"]["return_value"]
        self.assertIsInstance(paths, list)
        self.assertTrue(any("World" in p for p in paths))
        print(f"  Root prims: {paths}")
        self._pass()

    def test_04_04_error_handling(self):
        """Phase 4.4: Error Handling"""
        r = self.c.execute("raise ValueError('test error')")
        self.assertEqual(r["status"], "error")
        self.assertIn("test error", r.get("error", ""))
        self._pass()

    def test_04_05_add_physics(self):
        """Phase 4.5: Add Physics via Script"""
        script = (
            "stage = omni.usd.get_context().get_stage()\n"
            "if not stage.GetPrimAtPath('/World/PhysicsScene').IsValid():\n"
            "    UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')\n"
            "ground = stage.GetPrimAtPath('/World/Ground')\n"
            "if not ground.HasAPI(UsdPhysics.CollisionAPI):\n"
            "    UsdPhysics.CollisionAPI.Apply(ground)\n"
            "cube = stage.GetPrimAtPath('/World/RedCube')\n"
            "if not cube.HasAPI(UsdPhysics.RigidBodyAPI):\n"
            "    UsdPhysics.RigidBodyAPI.Apply(cube)\n"
            "if not cube.HasAPI(UsdPhysics.CollisionAPI):\n"
            "    UsdPhysics.CollisionAPI.Apply(cube)\n"
            "result = 'physics added'"
        )
        r = self.c.execute(script)
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["return_value"], "physics added")

        props = self.c.prim_properties("/World/RedCube")
        props_str = json.dumps(props["result"])
        self.assertTrue("rigidBody" in props_str.lower() or "physics" in props_str.lower())
        print("  Physics APIs applied")
        self._pass()

    # ===== Phase 5: Simulation & Physics =====

    def test_05_01_play_pause_stop(self):
        """Phase 5.1: Play/Pause/Stop"""
        r = self.c.sim_control("play")
        self.assertEqual(r["status"], "success")

        r = self.c.sim_control("pause")
        self.assertEqual(r["status"], "success")

        r = self.c.sim_control("stop")
        self.assertEqual(r["status"], "success")
        self._pass()

    def test_05_02_step(self):
        """Phase 5.2: Step"""
        r = self.c.sim_control("step")
        self.assertEqual(r["status"], "success")
        self.c.sim_control("stop")
        self._pass()

    def test_05_03_gravity_test(self):
        """Phase 5.3: Gravity Test"""
        # Gravity pulls along the stage's up axis: the physics scene of 4.5 gives no direction of its own.
        up = self._up_axis()
        axis = "XYZ"[up]
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(up, 3))
        time.sleep(0.2)

        before = self.c.prim_bounds("/World/RedCube")["result"]
        before_h = before["center"][up]

        self.c.sim_control("play")
        time.sleep(1.5)
        # Pause (not stop) to preserve physics state
        self.c.sim_control("pause")
        time.sleep(0.3)

        after = self.c.prim_bounds("/World/RedCube")["result"]
        after_h = after["center"][up]

        print(f"  Before {axis}={before_h:.2f}, After {axis}={after_h:.2f}")
        self.assertLess(after_h, before_h, f"Cube should have fallen along {axis} due to gravity")
        self.c.sim_control("stop")
        self._pass()

    # ===== Phase 6: Recording (Basic) =====

    def test_06_01_record_simulation(self):
        """Phase 6.1: Record a Falling Cube"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 3))
        time.sleep(0.2)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "recordings")
        r = self.c.recording_start(output_dir, fps=5, width=320, height=240)
        self.assertEqual(r["status"], "success")
        self.__class__._rec_dir = r["result"]["output_dir"]

        self.c.sim_control("play")
        time.sleep(2.0)
        self.c.sim_control("stop")
        time.sleep(0.3)

        r = self.c.recording_stop()
        self.assertEqual(r["status"], "success")
        self.assertGreater(r["result"]["frame_count"], 0)
        print(f"  Recorded {r['result']['frame_count']} frames")
        self._pass()

    def test_06_02_review_frames(self):
        """Phase 6.2: Review Frames"""
        rec_dir = getattr(self.__class__, "_rec_dir", "")
        if not rec_dir:
            self.skipTest("No recording to review")

        r0 = self.c.recording_frame(rec_dir, 0)
        self.assertEqual(r0["status"], "success")
        self.assertIn("image_base64", r0["result"])

        r5 = self.c.recording_frame(rec_dir, 3)
        if r5["status"] == "success":
            print("  Frame 0 and 3 retrieved")
        self._pass()

    # ===== Phase 7: Recording with Prim State Tracking =====

    def test_07_01_record_with_track_prims(self):
        """Phase 7.1: Record with track_prims"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 3))
        time.sleep(0.2)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "recordings_state")
        r = self.c.recording_start(output_dir, fps=10, width=320, height=240, track_prims=["/World/RedCube"])
        self.assertEqual(r["status"], "success")
        self.__class__._state_rec_dir = r["result"]["output_dir"]

        self.c.sim_control("play")
        time.sleep(2.0)
        self.c.sim_control("pause")
        time.sleep(0.3)

        r = self.c.recording_stop()
        self.assertEqual(r["status"], "success")
        self.assertIsNotNone(r["result"].get("state_file"))
        self.__class__._state_file = r["result"]["state_file"]
        self.c.sim_control("stop")
        print(f"  State file: {r['result']['state_file']}")
        self._pass()

    def test_07_02_validate_state_txt(self):
        """Phase 7.2: Validate state.txt Format"""
        state_file = getattr(self.__class__, "_state_file", "")
        if not state_file or not os.path.exists(state_file):
            self.skipTest("No state file to validate")

        with open(state_file) as f:
            content = f.read()

        self.assertIn("# Omniverse MCP Recording State", content)
        self.assertIn("=== FRAME", content)
        self.assertIn("[/World/RedCube]", content)
        self.assertIn("pos =", content)

        # The cube's height in each frame, along the up axis 7.1 recorded on: nothing between the two changes it.
        up = self._up_axis()
        axis = "XYZ"[up]
        heights = []
        for line in content.split("\n"):
            if line.startswith("pos ="):
                parts = line.split("=")[1].strip().split(",")
                heights.append(float(parts[up].strip()))

        self.assertGreater(len(heights), 1, "state.txt should hold the cube in more than one frame")
        # Down from the first frame to the lowest, not the last: a frame still being captured when 7.1 stops the
        # recording can be written after 7.1 stops the timeline, which puts the cube back at 3.
        first, lowest = heights[0], min(heights)
        self.assertGreater(
            first - lowest, 0.1, f"{axis} should fall due to gravity: first={first:.2f}, lowest={lowest:.2f}"
        )
        print(f"  {axis} positions: first={first:.2f}, lowest={lowest:.2f}, frames={len(heights)}")
        self._pass()

    def test_07_03_record_with_property_filter(self):
        """Phase 7.3: Record with property_filter"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 3))
        time.sleep(0.2)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "recordings_filtered")
        r = self.c.recording_start(
            output_dir,
            fps=10,
            width=320,
            height=240,
            track_prims=["/World/RedCube"],
            property_filter=["xformOp", "physics"],
        )
        self.assertEqual(r["status"], "success")

        self.c.sim_control("play")
        time.sleep(1.0)
        self.c.sim_control("stop")
        time.sleep(0.3)

        r = self.c.recording_stop()
        self.assertEqual(r["status"], "success")

        state_file = r["result"].get("state_file")
        if state_file and os.path.exists(state_file):
            with open(state_file) as f:
                content = f.read()
            # Should have filtered properties
            self.assertIn("[/World/RedCube]", content)
            # Should NOT have unrelated properties like "extent" or "purpose"
            lines = [
                l
                for l in content.split("\n")
                if "=" in l and not l.startswith("#") and not l.startswith("===") and not l.startswith("[")
            ]
            # Formatter always adds: type, pos, rot, rigid_body, articulation_root
            always_keys = {"type", "pos", "rot", "rigid_body", "articulation_root"}
            for line in lines:
                key = line.split("=")[0].strip()
                if key in always_keys:
                    continue
                self.assertTrue(
                    any(f in key for f in ["xformOp", "physics"]), f"Unexpected property in filtered output: {key}"
                )
            print(f"  Property filter working, {len(lines)} filtered lines")
        self._pass()

    # ===== Phase 8: Scene Dump =====

    def test_08_01_full_scene_dump(self):
        """Phase 8.1: Full Scene Dump"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results")
        r = self.c.scene_dump(output_dir, "/World", include_properties=True)
        self.assertEqual(r["status"], "success")
        file_path = r["result"]["file_path"]
        self.assertTrue(file_path.endswith(".txt"))
        self.assertTrue(os.path.exists(file_path))

        with open(file_path) as f:
            content = f.read()

        self.assertIn("# Omniverse MCP Scene Dump", content)
        self.assertIn("=== SCENE", content)
        self.assertIn("[/World/RedCube]", content)
        self.assertIn("type = Cube", content)
        print(f"  Dump: {r['result']['file_size_bytes']} bytes, {r['result']['prim_count']} prims")
        self._pass()

    def test_08_02_filtered_by_type(self):
        """Phase 8.2: Filtered by Type"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results")
        r = self.c.scene_dump(output_dir, "/World", filter_types=["Cube"])
        self.assertEqual(r["status"], "success")

        with open(r["result"]["file_path"]) as f:
            content = f.read()

        self.assertIn("[/World/RedCube]", content)
        self.assertIn("[/World/Ground]", content)
        # Should NOT have non-Cube prims as blocks (Light is DistantLight)
        self.assertNotIn("[/World/Light]", content)
        print("  Type filter: Cube only")
        self._pass()

    def test_08_03_filtered_by_property(self):
        """Phase 8.3: Filtered by Property"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results")
        r = self.c.scene_dump(output_dir, "/World", property_filter=["physics", "collision"])
        self.assertEqual(r["status"], "success")

        with open(r["result"]["file_path"]) as f:
            content = f.read()

        self.assertIn("[/World/RedCube]", content)
        print("  Property filter applied")
        self._pass()

    # ===== Phase 9: Extension Management =====

    def test_09_01_list_extensions(self):
        """Phase 9.1: List Extensions"""
        r = self.c.extensions_list(search="replicator")
        self.assertEqual(r["status"], "success")
        self.assertGreater(r["result"]["count"], 0)
        print(f"  Found {r['result']['count']} replicator extensions")
        self._pass()

    # ===== Phase 10: Robot Spawning =====

    def test_10_01_spawn_g1(self):
        """Phase 10.1: Spawn G1 Robot"""
        r = self.c.create_robot("g1", "/World/G1", position=_along_up(self._up_axis(), 0.74, x=3))
        self.assertEqual(r["status"], "success", f"Failed: {r.get('error', '')}")
        self.assertIn("prim_path", r["result"])
        joints = r["result"].get("joints", [])
        print(f"  G1 spawned at {r['result']['prim_path']}, {len(joints)} joints")
        self._pass()

    def test_10_02_inspect_robot(self):
        """Phase 10.2: Inspect Robot"""
        r = self.c.camera_inspect("/World/G1", angles=["front", "top_front_right"])
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(r["result"]["captures"]), 2)
        self.assertGreater(r["result"]["distance"], 0)
        print(f"  Robot inspected from 2 angles, auto-fit dist={r['result']['distance']:.2f}m")
        self._pass()

    def test_10_03_invalid_robot(self):
        """Phase 10.4: Invalid Robot"""
        r = self.c.create_robot("nonexistent_robot_xyz")
        self.assertEqual(r["status"], "error")
        print("  Error on invalid robot: OK")
        self._pass()

    # ===== Phase 11: Error Cases =====

    def test_11_01_invalid_prim_path(self):
        """Phase 11.1: Invalid Prim Path"""
        r = self.c.prim_properties("/Nonexistent/Path")
        self.assertEqual(r["status"], "error")

        r = self.c.set_transform("/Nonexistent/Path", position=[0, 0, 0])
        self.assertEqual(r["status"], "error")

        r = self.c.delete_prim("/Nonexistent/Path")
        self.assertEqual(r["status"], "error")

        r = self.c.prim_bounds("/Nonexistent/Path")
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_11_02_invalid_sim_control(self):
        """Phase 11.2: Invalid Sim Control"""
        r = self.c.sim_control("invalid_action")
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_11_03_script_syntax_error(self):
        """Phase 11.3: Script Syntax Error"""
        r = self.c.execute("def broken(")
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_11_04_double_recording(self):
        """Phase 11.4: Double Recording"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "rec_double")
        r = self.c.recording_start(output_dir, fps=5)
        self.assertEqual(r["status"], "success")

        r2 = self.c.recording_start(output_dir, fps=5)
        self.assertEqual(r2["status"], "error")

        self.c.recording_stop()
        self._pass()

    def test_11_05_stop_without_recording(self):
        """Phase 11.5: Stop Without Recording"""
        r = self.c.recording_stop()
        self.assertEqual(r["status"], "error")
        self._pass()

    # ===== Phase 12: Materials =====

    def test_12_01_set_material_basic(self):
        """Phase 12.1: Set Material - Basic Color"""
        r = self.c.set_material("/World/RedCube", color=[1, 0, 0])
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertEqual(result["prim_path"], "/World/RedCube")
        self.assertIn("material_path", result)
        self.assertAlmostEqual(result["color"][0], 1.0)
        self.assertAlmostEqual(result["color"][1], 0.0)
        self.assertAlmostEqual(result["color"][2], 0.0)
        print(f"  Material: {result['material_path']}")
        self._pass()

    def test_12_02_set_material_255_range(self):
        """Phase 12.2: Set Material - 0-255 Color Range"""
        r = self.c.set_material("/World/Ground", color=[128, 128, 128])
        self.assertEqual(r["status"], "success")
        result = r["result"]
        # Should be normalized to ~0.5
        for c in result["color"]:
            self.assertAlmostEqual(c, 128.0 / 255.0, places=2)
        print("  0-255 auto-normalized OK")
        self._pass()

    def test_12_03_set_material_pbr_props(self):
        """Phase 12.3: Set Material - PBR Properties"""
        r = self.c.set_material("/World/RedCube", color=[0.8, 0.1, 0.1], roughness=0.2, metallic=0.9)
        self.assertEqual(r["status"], "success")
        self.assertAlmostEqual(r["result"]["roughness"], 0.2)
        self.assertAlmostEqual(r["result"]["metallic"], 0.9)
        print("  PBR: roughness=0.2, metallic=0.9")
        self._pass()

    def test_12_04_set_material_opacity(self):
        """Phase 12.4: Set Material - Opacity"""
        r = self.c.set_material("/World/RedCube", color=[1, 0, 0], opacity=0.5)
        self.assertEqual(r["status"], "success")
        self.assertAlmostEqual(r["result"]["opacity"], 0.5)
        print("  Opacity=0.5")
        # Restore full opacity
        self.c.set_material("/World/RedCube", color=[1, 0, 0], opacity=1.0)
        self._pass()

    def test_12_05_set_material_custom_path(self):
        """Phase 12.5: Set Material - Custom Material Path"""
        r = self.c.set_material("/World/RedCube", color=[0, 1, 0], material_path="/World/Looks/MyGreenMat")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["material_path"], "/World/Looks/MyGreenMat")
        print("  Custom path: /World/Looks/MyGreenMat")
        # Restore red
        self.c.set_material("/World/RedCube", color=[1, 0, 0])
        self._pass()

    def test_12_06_set_material_invalid_prim(self):
        """Phase 12.6: Set Material - Invalid Prim"""
        r = self.c.set_material("/World/Nonexistent", color=[1, 0, 0])
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_12_07_set_material_invalid_color(self):
        """Phase 12.7: Set Material - Invalid Color"""
        r = self.c.set_material("/World/RedCube", color=[1, 0])
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_12_08_verify_material_visual(self):
        """Phase 12.8: Verify Material Visually"""
        # Apply a bright red material and capture to verify it's not white
        self.c.set_material("/World/RedCube", color=[1, 0, 0], roughness=0.5)
        self.c.camera_look_at("/World/RedCube", azimuth=30, elevation=20)
        time.sleep(0.3)
        r = self.c.capture_viewport(640, 480)
        self.assertEqual(r["status"], "success")
        self.assertGreater(len(r["result"]["image_base64"]), 100)
        print("  Visual verification captured")
        self._pass()

    # ===== Phase 13: Visibility & Cloning =====

    def test_13_01_set_visibility_hide(self):
        """Phase 13.1: Hide a Prim"""
        r = self.c.set_visibility("/World/RedCube", visible=False)
        self.assertEqual(r["status"], "success")
        self.assertFalse(r["result"]["visible"])
        print("  RedCube hidden")
        self._pass()

    def test_13_02_set_visibility_show(self):
        """Phase 13.2: Show a Prim"""
        r = self.c.set_visibility("/World/RedCube", visible=True)
        self.assertEqual(r["status"], "success")
        self.assertTrue(r["result"]["visible"])
        print("  RedCube visible again")
        self._pass()

    def test_13_03_set_visibility_invalid_prim(self):
        """Phase 13.3: Visibility on Invalid Prim"""
        r = self.c.set_visibility("/World/Nonexistent", visible=False)
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_13_04_clone_prim_single(self):
        """Phase 13.4: Clone a Single Prim"""
        r = self.c.clone_prim("/World/RedCube", "/World/RedCube_Clone")
        self.assertEqual(r["status"], "success", f"Clone failed: {r.get('error', '')}")
        clones = r["result"]["clones"]
        self.assertEqual(len(clones), 1)
        self.assertEqual(clones[0], "/World/RedCube_Clone")

        # Verify clone exists
        props = self.c.prim_properties("/World/RedCube_Clone")
        self.assertEqual(props["status"], "success")
        print(f"  Cloned to {clones[0]}")
        self._pass()

    def test_13_05_clone_prim_batch(self):
        """Phase 13.5: Clone Multiple Copies with Offset"""
        r = self.c.clone_prim("/World/RedCube", "/World/CloneBatch", count=3, offset=[2, 0, 0])
        self.assertEqual(r["status"], "success", f"Clone batch failed: {r.get('error', '')}")
        clones = r["result"]["clones"]
        self.assertEqual(len(clones), 3)
        # Verify 3-digit suffix format
        self.assertIn("/World/CloneBatch_001", clones)
        print(f"  Batch cloned: {clones}")
        self._pass()

    def test_13_06_clone_prim_invalid_source(self):
        """Phase 13.6: Clone Invalid Source"""
        r = self.c.clone_prim("/World/Nonexistent", "/World/Clone")
        self.assertEqual(r["status"], "error")
        self._pass()

    # ===== Phase 14: Robot Control =====

    def test_14_01_get_robot_info(self):
        """Phase 14.1: Get Robot Info"""
        r = self.c.get_robot_info("/World/G1")
        self.assertEqual(r["status"], "success", f"Robot info failed: {r.get('error', '')}")
        result = r["result"]
        self.assertIn("joints", result)
        self.assertIn("dof_count", result)
        self.assertGreater(result["dof_count"], 0)
        print(f"  G1: {result['dof_count']} DOF, {len(result['joints'])} joints, {result['link_count']} links")
        self._pass()

    def test_14_02_get_robot_info_invalid(self):
        """Phase 14.2: Robot Info on Non-Robot"""
        r = self.c.get_robot_info("/World/RedCube")
        self.assertEqual(r["status"], "success")
        # Should return 0 joints for a non-articulated prim
        self.assertEqual(r["result"]["dof_count"], 0)
        self._pass()

    def test_14_03_set_joint_targets(self):
        """Phase 14.3: Set Joint Targets"""
        # First get robot info to know joint names
        info = self.c.get_robot_info("/World/G1")
        self.assertEqual(info["status"], "success")
        joints = info["result"]["joints"]
        if len(joints) == 0:
            self.skipTest("No joints found")

        # Set a target for the first non-fixed joint (fixed joints have no drive)
        non_fixed = [j for j in joints if j["type"] != "PhysicsFixedJoint"]
        if not non_fixed:
            self.skipTest("No non-fixed joints found")
        first_joint = non_fixed[0]["name"]
        r = self.c.set_joint_targets("/World/G1", targets={first_joint: 0.0})
        self.assertEqual(r["status"], "success")
        self.assertGreater(r["result"]["targets_set"], 0)
        print(f"  Set target for {first_joint}")
        self._pass()

    def test_14_04_get_joint_states(self):
        """Phase 14.4: Get Joint States while paused, and the error once stopped (#50). The G1's first play: before
        #5, Kit stopped answering here."""
        try:
            r = self.c.sim_control("play")
            self.assertEqual(r["status"], "success", f"Play failed: {r.get('error', '')}")
            time.sleep(0.5)
            self.assertEqual(self.c.sim_control("pause")["status"], "success")

            r = self.c.get_joint_states("/World/G1")
            self.assertEqual(r["status"], "success", f"Joint states failed: {r.get('error', '')}")
            result = r["result"]
            self.assertGreater(result["dof_count"], 0)
            for key in ("names", "positions", "velocities"):
                self.assertEqual(len(result[key]), result["dof_count"], key)
            print(f"  {result['dof_count']} DOF, positions: {result['positions'][:5]}...")
        finally:
            self.c.sim_control("stop")

        # Stopped, there's no physics to read, and the handler loads none: the error says to play first.
        r = self.c.get_joint_states("/World/G1")
        self.assertEqual(r["status"], "error")
        self.assertIn("play or step the simulation first", r["error"])
        self._pass()

    # ===== Phase 15: Physics Properties & Forces =====

    def test_15_01_set_physics_mass(self):
        """Phase 15.1: Set Mass"""
        r = self.c.set_physics_properties("/World/RedCube", mass=5.0)
        self.assertEqual(r["status"], "success")
        self.assertIn("MassAPI", r["result"]["applied"])
        print(f"  Applied: {r['result']['applied']}")
        self._pass()

    def test_15_02_set_physics_friction(self):
        """Phase 15.2: Set Friction and Restitution"""
        r = self.c.set_physics_properties("/World/RedCube", friction=0.8, restitution=0.3)
        self.assertEqual(r["status"], "success")
        applied = r["result"]["applied"]
        self.assertIn("PhysicsMaterial", applied)
        print(f"  Applied: {applied}")
        self._pass()

    def test_15_03_set_physics_invalid_prim(self):
        """Phase 15.3: Physics on Invalid Prim"""
        r = self.c.set_physics_properties("/World/Nonexistent", mass=1.0)
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_15_04_apply_force(self):
        """Phase 15.4: Apply Force"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 2))
        self.c.sim_control("play")
        time.sleep(0.3)

        r = self.c.apply_force("/World/RedCube", force=[100, 0, 0])
        self.assertEqual(r["status"], "success", f"Apply force failed: {r.get('error', '')}")
        print(f"  Force applied: method={r['result']['method']}")

        time.sleep(0.5)
        self.c.sim_control("stop")
        self._pass()

    def test_15_05_apply_force_invalid(self):
        """Phase 15.5: Apply Force to Invalid Prim"""
        r = self.c.apply_force("/World/Nonexistent", force=[1, 0, 0])
        self.assertEqual(r["status"], "error")
        self._pass()

    # ===== Phase 16: Raycasting & Debug Draw =====

    def test_16_01_raycast_hit(self):
        """Phase 16.1: Raycast Hit"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        up = self._up_axis()
        self.c.set_transform("/World/RedCube", position=_along_up(up, 1))
        # Make sure physics scene exists for raycasting
        self.c.sim_control("play")
        time.sleep(0.3)
        self.c.sim_control("pause")

        # Cast a ray downward from above the ground
        r = self.c.raycast(origin=_along_up(up, 10), direction=_along_up(up, -1), max_distance=100.0)
        self.assertEqual(r["status"], "success")
        result = r["result"]
        if result["hit"]:
            print(f"  Hit: {result.get('prim_path', '?')} at dist={result['distance']:.2f}")
        else:
            print("  No hit (PhysX may need sim stepping)")
        self.c.sim_control("stop")
        self._pass()

    def test_16_02_raycast_miss(self):
        """Phase 16.2: Raycast Miss"""
        self.c.sim_control("play")
        time.sleep(0.3)
        self.c.sim_control("pause")

        # Cast ray into empty space
        r = self.c.raycast(origin=[0, 0, 0], direction=[0, 0, 1], max_distance=0.001)
        self.assertEqual(r["status"], "success")
        # With very short distance, likely no hit
        self.c.sim_control("stop")
        self._pass()

    def test_16_03_draw_debug_line(self):
        """Phase 16.3: Draw Debug Line"""
        self._lines_go_after_the_test()
        r = self.c.draw_debug("line", start=[0, 0, 0], end=[5, 5, 0], color=[1, 0, 0], duration=3.0)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["backend"], DRAW_BACKEND)
        print("  Drew debug line")
        self._pass()

    def test_16_04_draw_debug_sphere(self):
        """Phase 16.4: Draw Debug Sphere"""
        self._lines_go_after_the_test()
        r = self.c.draw_debug("sphere", center=[0, 2, 0], radius=0.5, color=[0, 1, 0], duration=3.0)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["backend"], DRAW_BACKEND)
        print("  Drew debug sphere")
        self._pass()

    def test_16_05_draw_debug_points(self):
        """Phase 16.5: Draw Debug Points"""
        self._lines_go_after_the_test()
        r = self.c.draw_debug(
            "points", points=[[0, 0, 0], [1, 1, 0], [2, 0, 0]], color=[0, 0, 1], duration=3.0, size=10.0
        )
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["backend"], DRAW_BACKEND)
        print("  Drew debug points")
        self._pass()

    def test_16_06_draw_debug_expires(self):
        """Phase 16.6: A drawing shows for its duration, then goes"""
        start = self._lines_go_after_the_test()
        up = self._up_axis()
        r = self.c.draw_debug("line", start=_along_up(up, 0), end=_along_up(up, 1), duration=1.0)
        drawn_at = time.monotonic()
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["duration"], 1.0)
        self.assertEqual(self._line_count(), start + 1)
        time.sleep(0.4)
        self.assertEqual(self._line_count(), start + 1, "the line went before its second was up")
        self._wait_for_line_count(start, timeout=5.0)
        print(f"  The line went {time.monotonic() - drawn_at:.1f} s after it was drawn")
        self._pass()

    def test_16_07_draw_debug_twice(self):
        """Phase 16.7: A drawing that expires leaves a longer one showing"""
        start = self._lines_go_after_the_test()
        up = self._up_axis()
        r = self.c.draw_debug("line", start=_along_up(up, 0), end=_along_up(up, 1), duration=3.0)
        self.assertEqual(r["status"], "success", r)
        r = self.c.draw_debug("sphere", center=_along_up(up, 1), radius=0.5, duration=1.0)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(self._line_count(), start + 4)
        # When the sphere goes, the clear takes all four lines and the line is drawn again in the same update: without
        # the redraw the count would fall to the start.
        self._wait_for_line_count(start + 1, timeout=5.0)
        print("  The 1 s sphere went, the 3 s line stayed")
        self._pass()

    def test_16_08_draw_debug_reaches_a_capture(self):
        """Phase 16.8: A drawing shows in a capture"""
        self._lines_go_after_the_test()
        zigzag = self._aim_away()
        before = self._red_pixels()
        r = self.c.draw_debug("lines", points=zigzag, color=[1, 0, 0], duration=5.0)
        self.assertEqual(r["status"], "success", r)
        drawn = self._red_pixels()
        print(f"  Strongly red pixels: {before} before the zigzag, {drawn} with it")
        self.assertLess(before, 20, "the view aimed away from the red cube holds red already")
        self.assertGreater(drawn, 100, "the zigzag isn't in the capture")
        self._pass()

    def test_16_09_draw_debug_with_omni_debugdraw(self):
        """Phase 16.9: omni.debugdraw, which forgets a line after a frame, shows a drawing for its duration"""
        r = self.c.execute(
            "import omni.kit.app\n"
            "result = omni.kit.app.get_app().get_extension_manager().is_extension_enabled('omni.debugdraw')"
        )
        self.assertEqual(r["status"], "success", r)
        if not r["result"]["return_value"]:
            # Cleanups run last first: the default backend is back before omni.debugdraw goes off again.
            self.addCleanup(
                self.c.execute,
                "import omni.kit.app\n"
                "manager = omni.kit.app.get_app().get_extension_manager()\n"
                "manager.set_extension_enabled_immediate('omni.debugdraw', False)",
            )
        self.addCleanup(self._choose_backend)
        self.assertEqual(self._choose_backend("omni.debugdraw"), "omni.debugdraw")

        zigzag = self._aim_away()
        r = self.c.draw_debug("lines", points=zigzag, color=[1, 0, 0], duration=4.0)
        drawn_at = time.monotonic()
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["backend"], "omni.debugdraw")
        during = self._red_pixels()
        self.assertLess(time.monotonic() - drawn_at, 4.0, "the capture ended after the drawing's 4 s: Kit was slow")
        time.sleep(max(0.0, drawn_at + 4.5 - time.monotonic()))
        after = self._red_pixels()
        print(f"  Strongly red pixels: {during} while it lasts, {after} after")
        self.assertGreater(during, 100, "omni.debugdraw's zigzag isn't in the capture")
        self.assertLess(after, 20, "omni.debugdraw's zigzag outlasted its duration")
        self._pass()

    # ===== Phase 17: Scene Lifecycle =====

    def test_17_01_save_scene(self):
        """Phase 17.1: Save Scene to File"""
        import tempfile

        save_path = os.path.join(tempfile.gettempdir(), "mcp_test_scene.usd")
        r = self.c.save_scene(save_path)
        self.assertEqual(r["status"], "success")
        self.assertIn("file_path", r["result"])
        print(f"  Saved to: {r['result']['file_path']}")
        # Clean up temp file
        if os.path.exists(save_path):
            os.remove(save_path)
        self._pass()

    def test_17_02_new_scene(self):
        """Phase 17.2: Create New Scene (destructive - runs last)"""
        r = self.c.new_scene()
        self.assertEqual(r["status"], "success")
        time.sleep(0.5)

        # Verify /World exists
        tree = self.c.scene_tree("/World", 1)
        self.assertEqual(tree["status"], "success")
        print("  New scene created with /World")
        self._pass()

    def test_17_03_draw_debug_forgets_the_old_stage(self):
        """Phase 17.3: A new stage doesn't get the old one's drawings back"""
        start = self._lines_go_after_the_test()
        r = self.c.draw_debug("line", start=[0, 0, 0], end=[1, 0, 0], duration=30.0)
        self.assertEqual(r["status"], "success", r)
        r = self.c.new_scene()
        self.assertEqual(r["status"], "success", r)
        time.sleep(0.5)
        r = self.c.draw_debug("sphere", center=_along_up(self._up_axis(), 1), radius=0.5, duration=1.0)
        self.assertEqual(r["status"], "success", r)
        # The sphere's three lines alone: the 30 s line went with its stage.
        self._wait_for_line_count(start + 3, timeout=2.0)
        # When the sphere goes, what is left is drawn again: nothing, not the old stage's line.
        self._wait_for_line_count(start, timeout=5.0)
        time.sleep(0.5)
        self.assertEqual(self._line_count(), start, "the old stage's line came back")
        print("  The old stage's line stayed gone")

    SEGMENTATION_TARGET = "/World/SegmentationCube"

    def test_17_04_segmentation_after_a_new_stage(self):
        """Phase 17.4: Segmentation on the new stage. omni.syntheticdata drops its sensors on every stage open, so the
        bridge enables instance segmentation again and waits for its first data (#27): the suite's first segmentation
        on a new stage, and on a cold start the one whose timing Kit's log records."""
        empty = self.c.execute(
            "import omni.syntheticdata as syn\n"
            "from omni.kit.viewport.utility import get_active_viewport\n"
            "result = int(syn.sensors.get_instance_segmentation(get_active_viewport()).size)"
        )
        self.assertEqual(empty["status"], "success", empty)
        self.assertEqual(empty["result"]["return_value"], 0, "17.3's new stage still had segmentation data")

        cube = self.SEGMENTATION_TARGET
        self.addCleanup(self.c.delete_prim, cube)
        r = self.c.create_prim(cube, "Cube", position=_along_up(self._up_axis(), 0.5), size=0.5)
        self.assertEqual(r["status"], "success", r)
        r = self.c.camera_inspect(cube, angles=["front"], include_segmentation=True)
        self.assertEqual(r["status"], "success", r)
        (cap,) = r["result"]["captures"]
        self.assertIn("image_base64", cap)
        self.assertIn("segmentation_base64", cap, cap.get("segmentation_error"))
        legend = cap.get("segmentation_legend", {})
        self.assertTrue(any(path == cube or path.startswith(cube + "/") for path in legend), legend)
        print(f"  Segmentation on the new stage: {len(legend)} prims in the legend")
        self._pass()

    # ===== Phase 24: Logging =====

    def test_24_01_get_logs_default(self):
        """Phase 24.1: Get Logs (Default)"""
        r = self.c.get_logs()
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertIn("entries", result)
        self.assertIn("total_captured", result)
        self.assertIn("buffer_size", result)
        self.assertGreater(result["total_captured"], 0)
        print(f"  {result['count']} entries, {result['total_captured']} total captured")
        self._pass()

    def test_24_02_get_logs_level_filter(self):
        """Phase 24.2: Get Logs with Level Filter"""
        # A warning and an info message of its own, so the filter is seen to keep one and drop the other: with no
        # warnings in the buffer, or levels named wrongly (#21), checking only what came back proves nothing.
        marker = f"scenario 24.2 {time.time_ns()}"
        r = self.c.execute(f'import carb\ncarb.log_warn("{marker} warning")\ncarb.log_info("{marker} info")')
        self.assertEqual(r["status"], "success")
        r = self.c.get_logs(count=2000, min_level="warn", search=marker)
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertEqual([(e["level"], e["msg"]) for e in result["entries"]], [("warn", f"{marker} warning")])
        r = self.c.get_logs(count=2000, min_level="info", search=marker)
        self.assertEqual([e["level"] for e in r["result"]["entries"]], ["warn", "info"])
        print(f"  {result['count']} warn+ entries")
        self._pass()

    def test_24_03_get_logs_search_filter(self):
        """Phase 24.3: Get Logs with Search Filter"""
        r = self.c.get_logs(search="MCP")
        self.assertEqual(r["status"], "success")
        result = r["result"]
        for entry in result["entries"]:
            self.assertIn("mcp", entry["msg"].lower(), f"Entry should contain 'MCP': {entry['msg'][:80]}")
        print(f"  {result['count']} entries matching 'MCP'")
        self._pass()

    def test_24_04_get_logs_channel_filter(self):
        """Phase 24.4: Get Logs with Channel Filter"""
        r = self.c.get_logs(channel="omni")
        self.assertEqual(r["status"], "success")
        result = r["result"]
        for entry in result["entries"]:
            self.assertIn("omni", entry["channel"].lower(), f"Channel should contain 'omni': {entry['channel']}")
        print(f"  {result['count']} entries with channel matching 'omni'")
        self._pass()

    def test_24_05_get_logs_since_index(self):
        """Phase 24.5: Get Logs with since_index"""
        # Get last 5 entries to find a reference index
        r1 = self.c.get_logs(count=5)
        self.assertEqual(r1["status"], "success")
        entries = r1["result"]["entries"]
        if not entries:
            self.skipTest("No log entries available")

        last_index = entries[-1]["index"]

        # Now get entries after that index
        r2 = self.c.get_logs(since_index=last_index)
        self.assertEqual(r2["status"], "success")
        for entry in r2["result"]["entries"]:
            self.assertGreater(entry["index"], last_index, f"Entry index {entry['index']} should be > {last_index}")
        print(f"  {r2['result']['count']} entries after index {last_index}")
        self._pass()

    def test_24_06_get_logs_after_error(self):
        """Phase 24.6: Get Logs After Error"""
        # Generate a known error
        self.c.execute("raise RuntimeError('log_test_error_sentinel')")

        # Check if it appears in logs
        r = self.c.get_logs(count=20, search="log_test_error_sentinel")
        self.assertEqual(r["status"], "success")
        # The error may appear in Omniverse logs or may only be in the script response
        # Either way, get_logs should not error
        print(f"  {r['result']['count']} entries matching error sentinel")
        self._pass()

    # ===== Phase 25: Async Script Execution (MCP Bridge) =====

    def test_25_01_async_scene_tree(self):
        """Phase 25.1: Async Scene Tree via MCP Bridge"""
        r = self.c.execute("tree = await mcp.scene_tree()\nresult = tree['status']")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["return_value"], "success")
        print("  Async scene_tree returned success")
        self._pass()

    def test_25_02_async_sim_state(self):
        """Phase 25.2: Async Sim State via MCP Bridge"""
        r = self.c.execute(
            "state = await mcp.sim_state()\n"
            "result = {\n"
            "    'up_axis': state['result']['up_axis'],\n"
            "    'status': state['status']\n"
            "}"
        )
        self.assertEqual(r["status"], "success")
        rv = r["result"]["return_value"]
        self.assertEqual(rv["status"], "success")
        self.assertIn(rv["up_axis"], ["Y", "Z"])
        print(f"  Async sim_state: up_axis={rv['up_axis']}")
        self._pass()

    def test_25_03_async_create_and_query(self):
        """Phase 25.3: Async Create and Query"""
        r = self.c.execute(
            "await mcp.create_prim('/World/McpTestCube', 'Cube', position=[0, 1, 0])\n"
            "bounds = await mcp.prim_bounds('/World/McpTestCube')\n"
            "result = bounds['result']['center']"
        )
        self.assertEqual(r["status"], "success")
        center = r["result"]["return_value"]
        self.assertIsInstance(center, list)
        self.assertEqual(len(center), 3)
        # Y should be approximately 1.0
        self.assertAlmostEqual(center[1], 1.0, places=0)
        print(f"  Created + queried: center={center}")

        # Clean up
        self.c.delete_prim("/World/McpTestCube")
        self._pass()

    def test_25_04_async_camera_and_capture(self):
        """Phase 25.4: Async Camera and Capture"""
        r = self.c.execute(
            "await mcp.set_camera([5, 3, 5], target=[0, 0, 0])\n"
            "cap = await mcp.capture_viewport(width=320, height=240)\n"
            "result = {\n"
            "    'status': cap['status'],\n"
            "    'has_image': 'image_base64' in cap.get('result', {})\n"
            "}"
        )
        self.assertEqual(r["status"], "success")
        rv = r["result"]["return_value"]
        self.assertEqual(rv["status"], "success")
        self.assertTrue(rv["has_image"])
        print("  Async camera+capture: success")
        self._pass()

    def test_25_05_async_logs(self):
        """Phase 25.5: Async Logs via MCP Bridge"""
        r = self.c.execute(
            "logs = await mcp.get_logs(count=5)\n"
            "result = {\n"
            "    'count': logs['result']['count'],\n"
            "    'status': logs['status']\n"
            "}"
        )
        self.assertEqual(r["status"], "success")
        rv = r["result"]["return_value"]
        self.assertEqual(rv["status"], "success")
        print(f"  Async get_logs: {rv['count']} entries")
        self._pass()

    def test_25_06_sync_still_works(self):
        """Phase 25.6: Sync Script Still Works"""
        r = self.c.execute("result = 42")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["return_value"], 42)
        print("  Sync script: 42")
        self._pass()

    def test_25_07_mixed_sync_async(self):
        """Phase 25.7: Mixed Sync and Async in Same Script"""
        r = self.c.execute(
            "import math\n"
            "x = math.sqrt(144)\n"
            "state = await mcp.sim_state()\n"
            "result = {'sqrt': x, 'up_axis': state['result']['up_axis']}"
        )
        self.assertEqual(r["status"], "success")
        rv = r["result"]["return_value"]
        self.assertAlmostEqual(rv["sqrt"], 12.0)
        self.assertIn(rv["up_axis"], ["Y", "Z"])
        print(f"  Mixed: sqrt=12.0, up_axis={rv['up_axis']}")
        self._pass()

    def test_25_08_async_error_handling(self):
        """Phase 25.8: Async Script Error Handling"""
        r = self.c.execute("bounds = await mcp.prim_bounds('/World/Nonexistent_MCP_Test')\nresult = bounds['status']")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["return_value"], "error")
        print("  Async error handled gracefully")
        self._pass()

    # ===== Phase 22: Enhanced Inspect Prim =====
    # Phases 22 to 26 run after 17.2's new_scene, which makes the stage Y-up, so their heights are on Y; run alone on
    # a Z-up stage they would place things sideways.

    INSPECT_TARGET = "/World/InspectTarget"

    def test_22_00_create_inspect_target(self):
        """Phase 22.0: Create the prim this phase inspects (no earlier phase leaves one)"""
        r = self.c.create_prim(self.INSPECT_TARGET, "Cube", position=[0, 0, 1.0], size=0.8, color=[0.8, 0.4, 0.1])
        self.assertEqual(r["status"], "success")
        self._pass()

    def test_22_01_inspect_with_segmentation(self):
        """Phase 22.1: Inspect with Segmentation"""
        r = self.c.camera_inspect(self.INSPECT_TARGET, angles=["front", "right"], include_segmentation=True)
        self.assertEqual(r["status"], "success")
        captures = r["result"]["captures"]
        self.assertEqual(len(captures), 2)
        for cap in captures:
            self.assertIn("image_base64", cap)
            self.assertIn("segmentation_base64", cap)
        print("  2 angles with segmentation captured")
        self._pass()

    def test_22_02_inspect_cube_corner_angles(self):
        """Phase 22.2: Inspect with Cube Corner Angles"""
        r = self.c.camera_inspect(
            self.INSPECT_TARGET, angles=["top_front_right", "top_back_left", "bottom_front_right", "bottom"]
        )
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(r["result"]["captures"]), 4)
        self.assertGreater(r["result"]["distance"], 0)
        print(f"  4 cube-based angles captured, dist={r['result']['distance']:.2f}m")
        self._pass()

    def test_22_03_inspect_nonexistent_prim(self):
        """Phase 22.3: Inspect Non-Existent Prim"""
        r = self.c.camera_inspect("/World/Nonexistent_22")
        self.assertEqual(r["status"], "error")
        print("  Error on nonexistent prim: OK")
        self._pass()

    def test_22_04_inspect_with_zoom_offset(self):
        """Phase 22.4: Inspect with Zoom Offset"""
        # Zoom closer
        r1 = self.c.camera_inspect(self.INSPECT_TARGET, angles=["front"], zoom_offset=-0.3)
        self.assertEqual(r1["status"], "success")
        d1 = r1["result"]["distance"]
        # Default distance
        r2 = self.c.camera_inspect(self.INSPECT_TARGET, angles=["front"])
        self.assertEqual(r2["status"], "success")
        d2 = r2["result"]["distance"]
        # Zoom closer should produce smaller distance
        self.assertLess(d1, d2)
        print(f"  zoom_offset=-0.3: dist={d1:.2f}m vs default: dist={d2:.2f}m")
        self._pass()

    def test_22_05_inspect_with_isolate(self):
        """Phase 22.5: Inspect with Isolate"""
        r = self.c.camera_inspect(self.INSPECT_TARGET, angles=["front"], isolate=True)
        self.assertEqual(r["status"], "success")
        self.assertTrue(r["result"].get("isolate", False))
        captures = r["result"]["captures"]
        self.assertEqual(len(captures), 1)
        self.assertIn("image_base64", captures[0])
        print(f"  Isolated inspect captured, dist={r['result']['distance']:.2f}m")
        self._pass()

    # ===== Phase 23: Viewport Lighting =====

    def test_23_01_get_lighting_state(self):
        """Phase 23.1: Get Lighting State"""
        r = self.c.viewport_light("get")
        self.assertEqual(r["status"], "success")
        result = r["result"]
        self.assertIn("lighting_mode", result)
        self.assertIn("available_modes", result)
        self.assertIn("has_scene_lights", result)
        modes = result["available_modes"]
        self.assertIn("camera", modes)
        self.assertIn("stage", modes)
        print(f"  Lighting mode: {result['lighting_mode']}, modes: {modes}")
        self._pass()

    def test_23_02_set_lighting_mode_default(self):
        """Phase 23.2: Set Lighting Mode to Default Rig"""
        r = self.c.viewport_light("set", mode="Default")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["lighting_mode"], "Default")
        print("  Set to Default rig")
        self._pass()

    def test_23_03_set_lighting_mode_camera(self):
        """Phase 23.3: Set Lighting Mode to Camera"""
        r = self.c.viewport_light("set", mode="camera")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["lighting_mode"], "camera")
        print("  Set to camera light")
        self._pass()

    def test_23_04_set_lighting_mode_stage(self):
        """Phase 23.4: Set Lighting Mode to Stage"""
        r = self.c.viewport_light("set", mode="stage")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["lighting_mode"], "stage")
        print("  Set to stage mode")
        self._pass()

    def test_23_05_set_camera_light_legacy(self):
        """Phase 23.5: Legacy set_camera_light Action"""
        r = self.c.viewport_light("set_camera_light", enabled=True)
        self.assertEqual(r["status"], "success")
        print("  Legacy set_camera_light: OK")
        self._pass()

    def test_23_06_black_image_warning(self):
        """Phase 23.6: Black Image Detection (no auto-fix)"""
        # Set lighting to off
        self.c.viewport_light("set", mode="off")
        time.sleep(0.5)
        cap = self.c.capture_viewport(320, 240)
        self.assertEqual(cap["status"], "success")
        # Should detect black but NOT auto-fix
        is_black = cap["result"].get("is_black", False)
        lighting_mode = cap["result"].get("lighting_mode", "")
        print(f"  Lighting off: is_black={is_black}, mode={lighting_mode}")
        # Restore lighting
        self.c.viewport_light("set", mode="Default")
        self._pass()

    # ===== Phase 26: Camera Frame Settling =====

    def test_26_01_camera_set_immediate_capture(self):
        """Phase 26.1: Camera Set + Immediate Capture (no delay)"""
        # Create something visible
        self.c.create_prim("/World/SettleCube", "Cube", position=[0, 0.5, 0], scale=[0.5, 0.5, 0.5])
        self.c.create_prim("/World/SettleLight", "DistantLight", rotation=[45, 0, 0])
        self.c.set_material("/World/SettleCube", color=[1, 0, 0])
        time.sleep(0.5)

        positions = [
            [5, 3, 5],
            [-3, 2, 4],
            [0, 5, -3],
        ]
        for pos in positions:
            r = self.c.camera_set(pos, [0, 0, 0])
            self.assertEqual(r["status"], "success")
            # Immediately capture — NO sleep/delay
            cap = self.c.capture_viewport(640, 480)
            self.assertEqual(cap["status"], "success")
            self.assertGreater(len(cap["result"]["image_base64"]), 100)

        # Clean up
        self.c.delete_prim("/World/SettleCube")
        self.c.delete_prim("/World/SettleLight")
        print("  3 camera positions captured immediately without delay")
        self._pass()

    def test_26_02_look_at_immediate_capture(self):
        """Phase 26.2: Look At + Immediate Capture"""
        self.c.create_prim("/World/SettleTest", "Cube", position=[0, 1, 0], scale=[0.5, 0.5, 0.5])
        self.c.create_prim("/World/SettleLight2", "DistantLight", rotation=[45, 0, 0])
        self.c.set_material("/World/SettleTest", color=[0, 1, 0])
        time.sleep(0.5)

        r = self.c.camera_look_at("/World/SettleTest", azimuth=45, elevation=30)
        self.assertEqual(r["status"], "success")
        # Immediately capture
        cap = self.c.capture_viewport(640, 480)
        self.assertEqual(cap["status"], "success")
        self.assertGreater(len(cap["result"]["image_base64"]), 100)

        # Clean up
        self.c.delete_prim("/World/SettleTest")
        self.c.delete_prim("/World/SettleLight2")
        print("  Look-at + immediate capture OK")
        self._pass()


if __name__ == "__main__":
    unittest.main()
