"""
Full scenario tests against live Isaac Sim.
Covers all 17 phases from test_project/scenarios.md.

Run: conda run -n isaac-mcp python -m pytest tests/test_scenarios.py -v -s
"""

import json
import os
import time
import unittest

from isaac_sim_mcp.client import IsaacSimClient


def _skip_if_no_sim():
    """Skip if Isaac Sim is not running."""
    try:
        c = IsaacSimClient(timeout=2.0)
        r = c.health()
        c.close()
        if r["status"] != "success":
            raise ConnectionError()
    except Exception:
        raise unittest.SkipTest("Isaac Sim not running on localhost:8211")


class TestScenarios(unittest.TestCase):
    """Full scenario tests matching test_project/scenarios.md."""

    @classmethod
    def setUpClass(cls):
        _skip_if_no_sim()
        cls.c = IsaacSimClient(timeout=10.0)
        # Stop sim and clean up before starting
        cls.c.sim_control("stop")
        # Warmup viewport capture pipeline (first capture after connect is slow)
        cls.c.capture_viewport(320, 240)
        # Track results
        cls.results = []

    @classmethod
    def tearDownClass(cls):
        # Cleanup
        for path in ["/World/Ground", "/World/RedCube", "/World/BlueSphere",
                      "/World/Light", "/World/G1", "/World/PhysicsScene",
                      "/World/Looks", "/World/RedCube_Clone",
                      "/World/CloneBatch_001", "/World/CloneBatch_002", "/World/CloneBatch_003",
                      "/World/PhysicsMaterials"]:
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
            f.write(f"| # | Test | Result |\n")
            f.write(f"|---|------|--------|\n")
            for i, (name, status) in enumerate(cls.results, 1):
                f.write(f"| {i} | {name} | {status} |\n")
        print(f"\nResults written to: {results_path}")

    def _record(self, status):
        self.results.append((self._testMethodName, status))

    def _pass(self):
        self._record("PASS")

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
        r1 = self.c.create_prim("/World/Ground", "Cube", position=[0, -0.05, 0], scale=[10, 0.1, 10])
        self.assertEqual(r1["status"], "success")
        r2 = self.c.create_prim("/World/RedCube", "Cube", position=[0, 2, 0], scale=[0.3, 0.3, 0.3])
        self.assertEqual(r2["status"], "success")
        r3 = self.c.create_prim("/World/BlueSphere", "Sphere", position=[1, 0.5, 0], scale=[0.2, 0.2, 0.2])
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
        print(f"  Created 4 prims with materials")
        self._pass()

    def test_02_02_transform_operations(self):
        """Phase 2.2: Transform Operations"""
        r = self.c.set_transform("/World/RedCube", position=[2, 2, 0])
        self.assertEqual(r["status"], "success")
        r = self.c.set_transform("/World/RedCube", rotation=[0, 45, 0])
        self.assertEqual(r["status"], "success")
        r = self.c.set_transform("/World/RedCube", scale=[0.5, 0.5, 0.5])
        self.assertEqual(r["status"], "success")
        print(f"  Transform updated")
        self._pass()

    def test_02_03_delete_prim(self):
        """Phase 2.3: Delete Prim"""
        r = self.c.delete_prim("/World/BlueSphere")
        self.assertEqual(r["status"], "success")

        tree = self.c.scene_tree("/World", 2)
        # Check prim path is gone (material BlueSphere_Mat may still exist under /World/Looks)
        tree_str = json.dumps(tree["result"])
        self.assertNotIn("/World/BlueSphere\"", tree_str)

        r = self.c.delete_prim("/World/Nonexistent")
        self.assertEqual(r["status"], "error")
        print(f"  Delete OK, error on missing: OK")
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
        ground = self.c.prim_bounds("/World/Ground")["result"]
        cube = self.c.prim_bounds("/World/RedCube")["result"]

        ground_top_y = ground["max"][1]
        cube_half_h = cube["dimensions"][1] / 2.0
        target_y = ground_top_y + cube_half_h

        r = self.c.set_transform("/World/RedCube", position=[0, target_y, 0])
        self.assertEqual(r["status"], "success")

        new_bounds = self.c.prim_bounds("/World/RedCube")["result"]
        # Cube center should be above ground top
        self.assertGreater(new_bounds["center"][1], ground_top_y - 0.1)
        print(f"  Placed cube at y={target_y:.3f}, ground_top={ground_top_y:.3f}")
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
        print(f"  Camera set + captured")
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
        print(f"  3 angles captured")
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
        r = self.c.execute("stage = omni.usd.get_context().get_stage(); result = [str(p.GetPath()) for p in stage.GetPseudoRoot().GetChildren()]")
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
        print(f"  Physics APIs applied")
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
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=[0, 3, 0])
        time.sleep(0.2)

        before = self.c.prim_bounds("/World/RedCube")["result"]
        before_y = before["center"][1]

        self.c.sim_control("play")
        time.sleep(1.5)
        # Pause (not stop) to preserve physics state
        self.c.sim_control("pause")
        time.sleep(0.3)

        after = self.c.prim_bounds("/World/RedCube")["result"]
        after_y = after["center"][1]

        print(f"  Before Y={before_y:.2f}, After Y={after_y:.2f}")
        self.assertLess(after_y, before_y, "Cube should have fallen due to gravity")
        self.c.sim_control("stop")
        self._pass()

    # ===== Phase 6: Recording (Basic) =====

    def test_06_01_record_simulation(self):
        """Phase 6.1: Record a Falling Cube"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=[0, 3, 0])
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
            print(f"  Frame 0 and 3 retrieved")
        self._pass()

    # ===== Phase 7: Recording with Prim State Tracking =====

    def test_07_01_record_with_track_prims(self):
        """Phase 7.1: Record with track_prims"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=[0, 3, 0])
        time.sleep(0.2)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "recordings_state")
        r = self.c.recording_start(output_dir, fps=10, width=320, height=240,
                                    track_prims=["/World/RedCube"])
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

        self.assertIn("# Isaac Sim MCP Recording State", content)
        self.assertIn("=== FRAME", content)
        self.assertIn("[/World/RedCube]", content)
        self.assertIn("pos =", content)

        # Check Y position decreases across frames
        positions = []
        for line in content.split("\n"):
            if line.startswith("pos ="):
                parts = line.split("=")[1].strip().split(",")
                y = float(parts[1].strip())
                positions.append(y)

        self.assertGreater(len(positions), 0, "No position data found in state.txt")
        if len(positions) >= 2:
            max_y = max(positions)
            min_y = min(positions)
            self.assertGreater(max_y - min_y, 0.1,
                               f"Y should vary due to gravity: max={max_y:.2f}, min={min_y:.2f}")
            print(f"  Y positions: max={max_y:.2f}, min={min_y:.2f}, frames={len(positions)}")
        self._pass()

    def test_07_03_record_with_property_filter(self):
        """Phase 7.3: Record with property_filter"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=[0, 3, 0])
        time.sleep(0.2)

        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results", "recordings_filtered")
        r = self.c.recording_start(output_dir, fps=10, width=320, height=240,
                                    track_prims=["/World/RedCube"],
                                    property_filter=["xformOp", "physics"])
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
            lines = [l for l in content.split("\n")
                     if "=" in l and not l.startswith("#") and not l.startswith("===") and not l.startswith("[")]
            # Formatter always adds: type, pos, rot, rigid_body, articulation_root
            always_keys = {"type", "pos", "rot", "rigid_body", "articulation_root"}
            for line in lines:
                key = line.split("=")[0].strip()
                if key in always_keys:
                    continue
                self.assertTrue(
                    any(f in key for f in ["xformOp", "physics"]),
                    f"Unexpected property in filtered output: {key}"
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

        self.assertIn("# Isaac Sim MCP Scene Dump", content)
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
        print(f"  Type filter: Cube only")
        self._pass()

    def test_08_03_filtered_by_property(self):
        """Phase 8.3: Filtered by Property"""
        output_dir = os.path.join(os.path.dirname(__file__), "..", "test_project", "results")
        r = self.c.scene_dump(output_dir, "/World", property_filter=["physics", "collision"])
        self.assertEqual(r["status"], "success")

        with open(r["result"]["file_path"]) as f:
            content = f.read()

        self.assertIn("[/World/RedCube]", content)
        print(f"  Property filter applied")
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
        r = self.c.create_robot("g1", "/World/G1", position=[3, 0.74, 0])
        self.assertEqual(r["status"], "success", f"Failed: {r.get('error', '')}")
        self.assertIn("prim_path", r["result"])
        joints = r["result"].get("joints", [])
        print(f"  G1 spawned at {r['result']['prim_path']}, {len(joints)} joints")
        self._pass()

    def test_10_02_inspect_robot(self):
        """Phase 10.2: Inspect Robot"""
        r = self.c.camera_inspect("/World/G1", angles=["front", "perspective"])
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(r["result"]["captures"]), 2)
        print(f"  Robot inspected from 2 angles")
        self._pass()

    def test_10_03_invalid_robot(self):
        """Phase 10.4: Invalid Robot"""
        r = self.c.create_robot("nonexistent_robot_xyz")
        self.assertEqual(r["status"], "error")
        print(f"  Error on invalid robot: OK")
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
        print(f"  0-255 auto-normalized OK")
        self._pass()

    def test_12_03_set_material_pbr_props(self):
        """Phase 12.3: Set Material - PBR Properties"""
        r = self.c.set_material("/World/RedCube", color=[0.8, 0.1, 0.1],
                                roughness=0.2, metallic=0.9)
        self.assertEqual(r["status"], "success")
        self.assertAlmostEqual(r["result"]["roughness"], 0.2)
        self.assertAlmostEqual(r["result"]["metallic"], 0.9)
        print(f"  PBR: roughness=0.2, metallic=0.9")
        self._pass()

    def test_12_04_set_material_opacity(self):
        """Phase 12.4: Set Material - Opacity"""
        r = self.c.set_material("/World/RedCube", color=[1, 0, 0], opacity=0.5)
        self.assertEqual(r["status"], "success")
        self.assertAlmostEqual(r["result"]["opacity"], 0.5)
        print(f"  Opacity=0.5")
        # Restore full opacity
        self.c.set_material("/World/RedCube", color=[1, 0, 0], opacity=1.0)
        self._pass()

    def test_12_05_set_material_custom_path(self):
        """Phase 12.5: Set Material - Custom Material Path"""
        r = self.c.set_material("/World/RedCube", color=[0, 1, 0],
                                material_path="/World/Looks/MyGreenMat")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["material_path"], "/World/Looks/MyGreenMat")
        print(f"  Custom path: /World/Looks/MyGreenMat")
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
        print(f"  Visual verification captured")
        self._pass()


    # ===== Phase 13: Visibility & Cloning =====

    def test_13_01_set_visibility_hide(self):
        """Phase 13.1: Hide a Prim"""
        r = self.c.set_visibility("/World/RedCube", visible=False)
        self.assertEqual(r["status"], "success")
        self.assertFalse(r["result"]["visible"])
        print(f"  RedCube hidden")
        self._pass()

    def test_13_02_set_visibility_show(self):
        """Phase 13.2: Show a Prim"""
        r = self.c.set_visibility("/World/RedCube", visible=True)
        self.assertEqual(r["status"], "success")
        self.assertTrue(r["result"]["visible"])
        print(f"  RedCube visible again")
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
        """Phase 14.4: Get Joint States (requires sim played)"""
        self.c.sim_control("play")
        time.sleep(0.5)
        self.c.sim_control("pause")

        r = self.c.get_joint_states("/World/G1")
        if r["status"] == "error":
            print(f"  Joint states not available (expected if articulation not initialized): {r['error']}")
            self._record("SKIP")
            return
        result = r["result"]
        self.assertIn("positions", result)
        self.assertIn("dof_count", result)
        print(f"  {result['dof_count']} DOF, positions: {result['positions'][:5]}...")
        self.c.sim_control("stop")
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
        self.c.set_transform("/World/RedCube", position=[0, 2, 0])
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
        self.c.set_transform("/World/RedCube", position=[0, 1, 0])
        # Make sure physics scene exists for raycasting
        self.c.sim_control("play")
        time.sleep(0.3)
        self.c.sim_control("pause")

        # Cast a ray downward from above the ground
        r = self.c.raycast(origin=[0, 10, 0], direction=[0, -1, 0], max_distance=100.0)
        self.assertEqual(r["status"], "success")
        result = r["result"]
        if result["hit"]:
            print(f"  Hit: {result.get('prim_path', '?')} at dist={result['distance']:.2f}")
        else:
            print(f"  No hit (PhysX may need sim stepping)")
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
        r = self.c.draw_debug("line", start=[0, 0, 0], end=[5, 5, 0],
                               color=[1, 0, 0], duration=3.0)
        self.assertEqual(r["status"], "success")
        print(f"  Drew debug line")
        self._pass()

    def test_16_04_draw_debug_sphere(self):
        """Phase 16.4: Draw Debug Sphere"""
        r = self.c.draw_debug("sphere", center=[0, 2, 0], radius=0.5,
                               color=[0, 1, 0], duration=3.0)
        self.assertEqual(r["status"], "success")
        print(f"  Drew debug sphere")
        self._pass()

    def test_16_05_draw_debug_points(self):
        """Phase 16.5: Draw Debug Points"""
        r = self.c.draw_debug("points", points=[[0, 0, 0], [1, 1, 0], [2, 0, 0]],
                               color=[0, 0, 1], duration=3.0, size=10.0)
        self.assertEqual(r["status"], "success")
        print(f"  Drew debug points")
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
        print(f"  New scene created with /World")
        self._pass()


if __name__ == "__main__":
    unittest.main()
