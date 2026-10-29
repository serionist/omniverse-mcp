"""
Integration test for the Omniverse MCP Bridge (ovmcp.bridge).

Requires Isaac Sim to be running with the ovmcp.bridge extension enabled.

Usage, with Kit running: OMNIVERSE_MCP_SIM=1 uv run pytest -m sim
"""

import json
import secrets
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

import pytest

from omniverse_mcp.client import BridgeClient
from ovmcp.core import capture

from .conftest import live_bridge

pytestmark = pytest.mark.sim


# A robot's USD file in its smallest form: a default prim, with a child the test reads back after the reference loads.
_ROBOT_USDA = """#usda 1.0
(
    defaultPrim = "Bot"
)

def Xform "Bot"
{
    def Cube "Body"
    {
    }
}
"""

# The live tests of the bounded capture waits (#27, #35) change Kit through execute_script, which is not behind the
# viewport lock, and undo it in their cleanup. Each change also undoes itself on Kit's loop after 60 s, in case the
# test process dies first, and only while it is still that test's own, so a late undo never removes a later test's.

# Puts `wrapper` in place of `target.<name>`. A wrapper an earlier run left behind is unwrapped first, so the
# original is always Kit's own function.
_WRAP = """
import asyncio
{target}
original = target.{name}
while hasattr(original, "_ovmcp_test_original"):
    original = original._ovmcp_test_original
{wrapper}
wrapper._ovmcp_test_original = original


def undo():
    if target.{name} is wrapper:
        target.{name} = original


wrapper._ovmcp_test_undo = undo
target.{name} = wrapper
asyncio.get_running_loop().call_later(60, undo)
result = "wrapped"
"""

_UNWRAP = """
{target}
undo = getattr(target.{name}, "_ovmcp_test_undo", None)
if undo is not None:
    undo()
result = "unwrapped"
"""

_SENSORS = "import omni.syntheticdata as syn\ntarget = syn.sensors"
_VIEWPORT_UTILITY = "import omni.kit.viewport.utility as target"

# Kit's capture delegate, done at once with the result it names, and no file written.
_FINISHED_CAPTURE = """
class _Finished:
    async def wait_for_result(self, completion_frames=2):
        return {result!r}


def wrapper(viewport_api, file_path=None, *args, **kwargs):
    return _Finished()
"""

# Sets one of ovmcp.core.capture's limits; an extension from before the bounded waits has none to set. The token says
# whose change it is: by value alone, an earlier run's late undo would put back a later run's limit mid-test.
_SHORTEN = """
import asyncio
try:
    from ovmcp.core import capture
except ImportError:
    capture = None
if capture is not None:
    token = object()
    capture._ovmcp_test_{name} = token
    capture.{name} = {seconds!r}

    def undo():
        if getattr(capture, "_ovmcp_test_{name}", None) is token:
            capture.{name} = {default!r}
            capture._ovmcp_test_{name} = None

    asyncio.get_running_loop().call_later(60, undo)
result = capture is not None
"""

_RESTORE = """
from ovmcp.core import capture
capture.{name} = {default!r}
capture._ovmcp_test_{name} = None
result = capture.{name}
"""

# Turns the active viewport's updates off, then waits up to 3 s for a frame through Kit's own frame wait.
_UPDATES_OFF = """
import asyncio
import omni.kit.viewport.utility as utility

viewport = utility.get_active_viewport()
token = object()
utility._ovmcp_test_updates_off = token
viewport.updates_enabled = False


def undo():
    if getattr(utility, "_ovmcp_test_updates_off", None) is token:
        viewport.updates_enabled = True
        utility._ovmcp_test_updates_off = None


asyncio.get_running_loop().call_later(60, undo)
try:
    await asyncio.wait_for(utility.next_viewport_frame_async(viewport, 1), 3)
    result = "a frame"
except asyncio.TimeoutError:
    result = "no frame"
"""

# Each prim under /World, and whether it renders: what isolate hides, and must give back.
_VISIBILITY = """
from pxr import UsdGeom
stage = omni.usd.get_context().get_stage()
result = {
    str(prim.GetPath()): str(UsdGeom.Imageable(prim).ComputeVisibility())
    for prim in stage.GetPrimAtPath("/World").GetChildren()
    if prim.IsA(UsdGeom.Imageable)
}
"""

_UPDATES_ON = """
import omni.kit.viewport.utility as utility
viewport = utility.get_active_viewport()
viewport.updates_enabled = True
utility._ovmcp_test_updates_off = None
result = viewport.updates_enabled
"""


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
        for path in [
            "/World/IntTestCube",
            "/World/IntTestLight",
            "/World/IntTestClone",
            "/World/IntTestRobot",
            "/World/IntTestPair",
        ]:
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

    def _red_and_blue(self, angles: list[str]) -> list[list[float]]:
        """Each inspect_prim frame's mean red and blue, of /World/IntTestPair isolated, as Kit (PIL, numpy) measures."""
        result = self.client.camera_inspect("/World/IntTestPair", angles=angles, width=160, height=120, isolate=True)
        self.assertEqual(result["status"], "success", result)
        images = [cap["image_base64"] for cap in result["result"]["captures"]]
        means = self.client.execute(
            "import base64, io\nimport numpy as np\nfrom PIL import Image\n"
            f"images = {json.dumps(images)}\n"
            "result = [[float(np.asarray(Image.open(io.BytesIO(base64.b64decode(b))).convert('RGB'), dtype=float)"
            "[..., i].mean()) for i in (0, 2)] for b in images]"
        )
        self.assertEqual(means["status"], "success", means)
        return means["result"]["return_value"]

    def test_15b_inspect_frames_show_their_own_angle(self):
        """A red plate above a blue one: seen from the top, red; from the bottom, blue. Captures used to read the
        previous capture's file, so each frame showed the angle before it (#32)."""
        up = self.client.sim_state()["result"]["up_axis"]
        axis = 2 if up == "Z" else 1
        flat = [0.5, 0.5, 0.5]
        flat[axis] = 0.03
        self.client.create_prim("/World/IntTestPair", "Xform")
        for name, height, colour in (("Top", 0.3, [1.0, 0.0, 0.0]), ("Bottom", -0.3, [0.0, 0.0, 1.0])):
            position = [0.0, 0.0, 0.0]
            position[axis] = height
            self.client.create_prim(f"/World/IntTestPair/{name}", "Cube", position=position, scale=flat)
            # Under the pair, so deleting it takes them too.
            material = f"/World/IntTestPair/Looks/{name}_Mat"
            made = self.client.set_material(f"/World/IntTestPair/{name}", color=colour, material_path=material)
            self.assertEqual(made["status"], "success", made)
        self.client.create_prim("/World/IntTestPair/Dome", "DomeLight")
        # A light's intensity defaults to 1, too dim to tell red from blue; the viewport's own light isn't the test's.
        lit = self.client.execute(
            "from pxr import UsdLux\n"
            "stage = omni.usd.get_context().get_stage()\n"
            "UsdLux.DomeLight(stage.GetPrimAtPath('/World/IntTestPair/Dome')).CreateIntensityAttr(1000.0)\n"
            "result = 'lit'"
        )
        self.assertEqual(lit["status"], "success", lit)
        # A frame from below first: with #32's bug the next call's first frame would be this one, blue where red is
        # asked for.
        (below,) = self._red_and_blue(["bottom"])
        self.assertGreater(below[1], below[0] + 5)

        (top_red, top_blue), (bottom_red, bottom_blue), (again_red, again_blue) = self._red_and_blue(
            ["top", "bottom", "top"]
        )
        self.assertGreater(top_red, top_blue + 5)
        self.assertGreater(bottom_blue, bottom_red + 5)
        self.assertGreater(again_red, again_blue + 5)
        print(f"  top red-blue {top_red - top_blue:.0f}, bottom blue-red {bottom_blue - bottom_red:.0f}")

    # ===== Bounded capture waits (#27, #35) =====

    def _kit(self, code: str):
        """Run code inside Kit through execute_script; the `result` it sets."""
        done = self.client.execute(code)
        self.assertEqual(done["status"], "success", done)
        return done["result"]["return_value"]

    def _wrap(self, target: str, name: str, wrapper: str) -> None:
        """Put the function `wrapper` defines, which may call `original`, in place of `target.<name>` in Kit, until
        the test ends."""
        self._kit(_WRAP.format(target=target, name=name, wrapper=textwrap.dedent(wrapper)))
        self.addCleanup(self._kit, _UNWRAP.format(target=target, name=name))

    def _shorten(self, name: str, seconds: float) -> bool:
        """Set one of ovmcp.core.capture's limits in Kit until the test ends; False for an extension without them."""
        values = {"name": name, "seconds": seconds, "default": getattr(capture, name)}
        shortened = self._kit(_SHORTEN.format(**values))
        if shortened:
            self.addCleanup(self._kit, _RESTORE.format(**values))
        return shortened

    def test_15c_segmentation_that_comes_late_is_waited_for(self):
        """Segmentation empty for its first 15 reads, then Kit's own: waited for by time, where the bridge used to read
        it four times and drop it (#27)."""
        self._wrap(
            _SENSORS,
            "get_instance_segmentation",
            """
            import numpy as np

            reads = []


            def wrapper(viewport, *args, **kwargs):
                reads.append(1)
                if len(reads) <= 15:
                    return np.zeros((0, 0), dtype=np.uint32)
                return original(viewport, *args, **kwargs)


            wrapper.reads = reads
            """,
        )
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front"], include_segmentation=True)
        reads = self._kit(f"{_SENSORS}\nresult = len(target.get_instance_segmentation.reads)")
        self.assertEqual(result["status"], "success", result)
        (cap,) = result["result"]["captures"]
        self.assertIn("image_base64", cap)
        self.assertNotIn("segmentation_error", cap)
        self.assertIn("segmentation_base64", cap)
        self.assertGreaterEqual(reads, 16)  # the 15 empty ones, then Kit's
        print(f"  segmentation after {reads} reads")

    def test_15d_inspect_says_why_segmentation_is_missing(self):
        """Segmentation that never comes: each angle's answer says why, the first after one wait, the second without
        waiting again on the same stage (#27)."""
        self._wrap(
            _SENSORS,
            "get_instance_segmentation",
            """
            import numpy as np


            def wrapper(viewport, *args, **kwargs):
                return np.zeros((0, 0), dtype=np.uint32)
            """,
        )
        started = time.monotonic()
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right"], include_segmentation=True)
        took = time.monotonic() - started
        self.assertEqual(result["status"], "success", result)
        first, second = result["result"]["captures"]
        for cap in (first, second):
            self.assertIn("image_base64", cap)
            self.assertNotIn("segmentation_base64", cap)
        self.assertIn(f"within {capture.SEGMENTATION_SECONDS:g} s of enabling it", first.get("segmentation_error", ""))
        self.assertIn("as before, so this capture did not wait", second.get("segmentation_error", ""))
        self.assertLess(took, 15)  # a guard against a hang; the messages tell one wait from two
        print(f"  2 angles, each saying why, in {took:.1f} s")

    def test_15e_an_empty_capture_fails_at_once(self):
        """A capture whose wait_for_result names nothing captured fails at once, where it waited 10 s for a file that
        could not come (#35). One that names LdrColor but writes no file, as Kit 110 does without a valid resource,
        fails after the file wait."""
        self._wrap(_VIEWPORT_UTILITY, "capture_viewport_to_file", _FINISHED_CAPTURE.format(result=[]))
        started = time.monotonic()
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right", "top", "back"])
        took = time.monotonic() - started
        self.assertEqual(result["status"], "success", result)
        captures = result["result"]["captures"]
        self.assertEqual(len(captures), 4)
        for cap in captures:
            self.assertIn("wait_for_result gave []", cap.get("error", ""), cap)
        self.assertLess(took, 15)

        self._shorten("FILE_SECONDS", 2)
        self._wrap(_VIEWPORT_UTILITY, "capture_viewport_to_file", _FINISHED_CAPTURE.format(result=["LdrColor"]))
        started = time.monotonic()
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right", "top"])
        no_file = time.monotonic() - started
        self.assertEqual(result["status"], "success", result)
        captures = result["result"]["captures"]
        self.assertEqual(len(captures), 3)
        for cap in captures:
            self.assertIn("no whole image in 2 s", cap.get("error", ""), cap)
        self.assertLess(no_file, 15)
        print(f"  4 empty captures in {took:.1f} s, 3 without a file in {no_file:.1f} s")

    def test_15f_a_viewport_that_renders_nothing_fails_in_time(self):
        """With the viewport's updates off no frame comes: set_camera answers after one frame wait, and inspect_prim
        stops after its first angle, naming the angles it did not capture; both hung before (#35)."""
        frame_seconds = 3 if self._shorten("FRAME_SECONDS", 3) else capture.FRAME_SECONDS
        try:
            self.assertEqual(
                self._kit(_UPDATES_OFF), "no frame", "updates_enabled = False did not stop this Kit app's frames"
            )
            started = time.monotonic()
            moved = self.client.camera_set([5, 3, 5], [0, 0, 0])
            moved_in = time.monotonic() - started
            self.assertEqual(moved["status"], "success", moved)
            self.assertLess(moved_in, frame_seconds + 5)

            started = time.monotonic()
            result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right", "top"])
            inspected_in = time.monotonic() - started
            self.assertEqual(result["status"], "success", result)
            first, *rest = result["result"]["captures"]
            self.assertIn("no frame", first.get("error", ""), first)
            for cap in rest:
                self.assertTrue(cap.get("error", "").startswith("Not captured"), cap)
            self.assertLess(inspected_in, 15)

            # Isolated: no frame after hiding, so no angle is tried, and the prims come back without a wait for frames.
            shown = self._kit(_VISIBILITY)
            self.assertGreater(len(shown), 1, "nothing beside the cube for isolate to hide")
            started = time.monotonic()
            result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right"], isolate=True)
            isolated_in = time.monotonic() - started
            self.assertEqual(result["status"], "success", result)
            for cap in result["result"]["captures"]:
                self.assertTrue(cap.get("error", "").startswith("Not captured"), cap)
            self.assertLess(isolated_in, frame_seconds + 5)
            self.assertEqual(self._kit(_VISIBILITY), shown)
        finally:
            self.assertTrue(self._kit(_UPDATES_ON))
        self.assertEqual(self.client.capture_viewport(320, 240)["status"], "success")
        print(
            f"  set_camera in {moved_in:.1f} s, inspect_prim in {inspected_in:.1f} s, isolated in {isolated_in:.1f} s, "
            "then a capture"
        )

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

    def _shader_source(self, material_path: str) -> list[str]:
        done = self.client.execute(
            "from pxr import UsdShade\n"
            f"s = UsdShade.Shader(omni.usd.get_context().get_stage().GetPrimAtPath('{material_path}/Shader'))\n"
            "result = [str(s.GetImplementationSource()), s.GetSourceAsset('mdl').path]"
        )
        self.assertEqual(done["status"], "success", done)
        return done["result"]["return_value"]

    def test_19_set_material(self):
        # A material from before #30 named only its id, which some Kit apps don't resolve: Kit then rendered its red
        # error material and logged "Unable to find SdrShaderNode". Both kinds must resolve after set_material.
        old = "/World/Looks/IntTestOld_Mat"
        made = self.client.execute(
            "from pxr import UsdShade, Sdf\n"
            "stage = omni.usd.get_context().get_stage()\n"
            f"mat = UsdShade.Material.Define(stage, '{old}')\n"
            f"shader = UsdShade.Shader.Define(stage, '{old}/Shader')\n"
            "shader.CreateIdAttr('OmniPBR')\n"
            "shader.CreateOutput('out', Sdf.ValueTypeNames.Token)\n"
            "mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'out')\n"
            "result = 'made'"
        )
        self.assertEqual(made["status"], "success", made)
        since = self.client.get_logs(count=1)["result"]["total_captured"]
        result = self.client.set_material("/World/IntTestCube", color=[1, 0, 0], roughness=0.3)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["result"]["color"], [1, 0, 0])
        upgraded = self.client.set_material("/World/IntTestCube", color=[0, 1, 0], material_path=old)
        self.assertEqual(upgraded["status"], "success")
        for path in (result["result"]["material_path"], old):
            self.assertEqual(self._shader_source(path), ["sourceAsset", "OmniPBR.mdl"])
        # A frame renders the bound material; the renderer logs a shader it can't resolve.
        self.assertEqual(self.client.capture_viewport(320, 240)["status"], "success")
        unresolved = self.client.get_logs(count=50, since_index=since, search="SdrShaderNode")["result"]["entries"]
        self.assertEqual(unresolved, [])
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

    # ===== A robot from its own USD file (#40) =====

    def test_27_create_robot_from_a_usd_file(self):
        # Kit runs on this machine, so it reads the file this test writes. The folder's case is kept, and the prim is
        # named after the file; before #40 the path was lowercased and put under Isaac Sim's asset root.
        usd = Path(tempfile.mkdtemp(prefix="ovmcp-Robots-")) / "IntTestRobot.usda"
        self.addCleanup(shutil.rmtree, usd.parent, True)
        usd.write_text(_ROBOT_USDA, encoding="utf-8")
        result = self.client.create_robot(str(usd))
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(result["result"]["prim_path"], "/World/IntTestRobot")
        self.assertEqual(result["result"]["usd_path"], str(usd))
        body = self.client.prim_properties("/World/IntTestRobot/Body")
        self.assertEqual(body["status"], "success", body.get("error"))
        print(f"  Robot from {usd.name}: /World/IntTestRobot/Body loaded")

    def test_28_create_robot_from_a_missing_file(self):
        missing = Path(tempfile.gettempdir()) / "ovmcp-No-Such-Robot.usd"
        result = self.client.create_robot(str(missing))
        self.assertEqual(result["status"], "error")
        self.assertIn(str(missing), result["error"])
        print("  Error on a missing USD file: OK")

    def test_29_create_robot_from_a_url_that_wont_open(self):
        # A URL isn't checked on disk, so the layer is opened before the reference: no empty prim reported created.
        url = (Path(tempfile.gettempdir()) / "ovmcp-no-such" / "Robot.usd").as_uri()
        result = self.client.create_robot(url)
        self.assertEqual(result["status"], "error")
        self.assertIn("Could not open", result["error"])
        self.assertEqual(self.client.prim_properties("/World/Robot")["status"], "error")

    def test_30_create_robot_on_a_taken_prim(self):
        # test_27 left /World/IntTestRobot; a second robot there would compose into it.
        result = self.client.create_robot("franka", "/World/IntTestRobot")
        self.assertEqual(result["status"], "error")
        self.assertIn("already exists", result["error"])

    # ===== Cleanup =====

    def test_99_cleanup(self):
        """Clean up test prims."""
        for path in [
            "/World/IntTestCube",
            "/World/IntTestLight",
            "/World/IntTestClone",
            "/World/IntTestRobot",
            "/World/IntTestPair",
            "/World/Looks",
        ]:
            self.client.delete_prim(path)
        print("  Cleanup done")


# Spheres of a few thousand vertices under ROOT, each vertex pushed in or out by a jitter drawn from the sphere's own
# seed in SEEDS: meshes no cook cache holds, so every one is cooked, and no cache is cleared to get there. Each is a
# rigid body with a convex hull: PhysX cooks a dynamic body's shape while physics loads, with Kit's main thread waiting
# on the cooking workers. Static colliders cook without that wait, and 8 of them played on main's bridge without a
# hang; 32 rigid bodies hung it (2026-10-29). A PhysicsScene under ROOT when the stage has none.
_COLD_COOK_SCENE = """
import math
import random

from pxr import Gf, UsdGeom, UsdPhysics

RINGS, SEGMENTS = 48, 64
stage = omni.usd.get_context().get_stage()
UsdGeom.Xform.Define(stage, ROOT)
if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse()):
    UsdPhysics.Scene.Define(stage, ROOT + "/PhysicsScene")
for i, seed in enumerate(SEEDS):
    rng = random.Random(seed)
    points = []
    for ring in range(RINGS + 1):
        theta = math.pi * ring / RINGS
        for segment in range(SEGMENTS):
            phi = 2 * math.pi * segment / SEGMENTS
            r = 1.0 + rng.uniform(-0.05, 0.05)
            points.append(Gf.Vec3f(r * math.sin(theta) * math.cos(phi), r * math.sin(theta) * math.sin(phi),
                                   r * math.cos(theta)))
    indices = []
    for ring in range(RINGS):
        for segment in range(SEGMENTS):
            a, b = ring * SEGMENTS + segment, ring * SEGMENTS + (segment + 1) % SEGMENTS
            indices += [a, b, b + SEGMENTS, a + SEGMENTS]
    mesh = UsdGeom.Mesh.Define(stage, f"{ROOT}/Sphere_{i}")
    mesh.CreatePointsAttr(points)
    mesh.CreateFaceVertexCountsAttr([4] * (RINGS * SEGMENTS))
    mesh.CreateFaceVertexIndicesAttr(indices)
    UsdGeom.XformCommonAPI(mesh).SetTranslate(Gf.Vec3d(3.0 * i, 0.0, 2.0))
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    UsdPhysics.RigidBodyAPI.Apply(mesh.GetPrim())
    UsdPhysics.MeshCollisionAPI.Apply(mesh.GetPrim()).CreateApproximationAttr("convexHull")
result = len(points)
"""
_SPHERES = 32


class TestColdCook(unittest.TestCase):
    """Last in the suite: a play that cooks collision meshes from scratch (#5). With a Python consumer on Kit's log, a
    cooking worker that logged waited for the GIL that Kit's main thread held while it waited for the worker, and Kit
    stopped answering. If Kit hangs, the run stops here, before test_scenarios.py runs into it."""

    @classmethod
    def setUpClass(cls):
        host, port = live_bridge()
        cls.client = BridgeClient(host=host, port=port, timeout=60.0)  # a cold cook takes about a second

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_a_play_that_cooks_new_collision_meshes_returns(self):
        root = f"/World/IntTestCook_{secrets.token_hex(4)}"  # this run's own, so older cooking lines don't count
        seeds = [secrets.randbits(32) for _ in range(_SPHERES)]
        made = self.client.execute(f"ROOT = {root!r}\nSEEDS = {seeds!r}\n{_COLD_COOK_SCENE}")
        self.assertEqual(made["status"], "success", made.get("error"))
        self.assertGreater(made["result"]["return_value"], 2000)

        try:
            played = self.client.sim_control("play")
        except TimeoutError:
            pytest.exit(
                f"Kit didn't answer sim_control('play') within {self.client.timeout:g} s while physics cooked new "
                "collision meshes: the hang of #5 (https://github.com/serionist/omniverse-mcp/issues/5). Kit is "
                "hung: kill it before running anything else against it.",
                returncode=1,
            )
        try:
            self.assertEqual(played["status"], "success", played.get("error"))
            # A cache hit starts no cooking task, so each sphere a cooking line names was cooked in this play.
            cooked = self.client.get_logs(count=2000, channel="omni.physx.cooking", search="ConvexMeshCookingTask")
            self.assertEqual(cooked["status"], "success", cooked.get("error"))
            named = {
                i for i in range(_SPHERES) for e in cooked["result"]["entries"] if f"{root}/Sphere_{i}" in e["msg"]
            }
            self.assertEqual(named, set(range(_SPHERES)), "every sphere is named in a ConvexMeshCookingTask line")
            print(f"  play answered; {len(named)} spheres cooked")
        finally:
            self.client.sim_control("stop")
            self.client.delete_prim(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
