"""
Integration test for the Omniverse MCP Bridge (ovmcp.bridge).

Requires Isaac Sim to be running with the ovmcp.bridge extension enabled.

Usage, with Kit running: OMNIVERSE_MCP_SIM=1 uv run pytest -m sim
"""

import base64
import json
import re
import secrets
import shutil
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import Any

import pytest
from pxr import Sdf

from omniverse_mcp.client import BridgeClient
from ovmcp.core import capture

from .conftest import CAMERA_AIM, RESTORE_LIMIT, SET_LIMIT, VIEWPORT_SEGMENTATION_ON, call_tool, live_bridge

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

# The Kit app /health and /sim/state name, for get_sim_state and a bug report (#105).
_KIT_FACTS = ("kit_app_name", "kit_app_version", "kit_version", "kit_os")

# A robot file of an up axis of its own (UP), its body tallest along it (TALL), for test_27b (#105).
_UPRIGHT_USDA = """#usda 1.0
(
    defaultPrim = "Bot"
    upAxis = "UP"
)

def Xform "Bot"
{
    def Cube "Body"
    {
        float3 xformOp:scale = TALL
        uniform token[] xformOpOrder = ["xformOp:scale"]
    }
}
"""

# Kit's metrics assembler resolving PATH, as its "resolve" does: the ops after, and the turn's value. None without it.
_RESOLVE = """
try:
    from omni.metrics.assembler.core import get_metrics_assembler_interface
except ImportError:
    result = None
else:
    context = omni.usd.get_context()
    get_metrics_assembler_interface().resolve_hierarchy(context.get_stage_id(), PATH)
    prim = context.get_stage().GetPrimAtPath(PATH)
    result = {
        "ops": [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()],
        "value": prim.GetAttribute("xformOp:rotateX:unitsResolve").Get(),
    }
"""

# test_27c's robot, in metres and kilograms, Z-up (#112): a base held to the world at its origin, and two arms 1 long
# along X on hinges about Y, which gravity pulls down against their drives. Force hangs on an angular force drive, its
# 1 kg from a density over its collider; Acceleration on an angular acceleration drive, its mass and inertia authored.
# Sleep and stabilisation are off: their thresholds are in stage units, so one stage's arm would stop short of where
# the other's settles.
_UNITS_BOT_USDA = """#usda 1.0
(
    defaultPrim = "Bot"
    kilogramsPerUnit = 1
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "Bot" (
    prepend apiSchemas = ["PhysicsArticulationRootAPI", "PhysxArticulationAPI"]
)
{
    bool physxArticulation:enabledSelfCollisions = 0
    float physxArticulation:sleepThreshold = 0
    float physxArticulation:stabilizationThreshold = 0

    def Xform "Base" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:mass = 5
        float3 physics:diagonalInertia = (0.1, 0.1, 0.1)
    }

    def PhysicsFixedJoint "Bolt"
    {
        rel physics:body1 = </Bot/Base>
    }

    def Xform "Force" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:density = 100
        double3 xformOp:translate = (0.5, -0.5, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Cube "Shape" (
            prepend apiSchemas = ["PhysicsCollisionAPI"]
        )
        {
            double size = 1
            float3 xformOp:scale = (1, 0.1, 0.1)
            uniform token[] xformOpOrder = ["xformOp:scale"]
        }
    }

    def PhysicsRevoluteJoint "ForceHinge" (
        prepend apiSchemas = ["PhysicsDriveAPI:angular"]
    )
    {
        uniform token physics:axis = "Y"
        rel physics:body0 = </Bot/Base>
        rel physics:body1 = </Bot/Force>
        point3f physics:localPos0 = (0, -0.5, 0)
        point3f physics:localPos1 = (-0.5, 0, 0)
        uniform token drive:angular:physics:type = "force"
        float drive:angular:physics:stiffness = 0.5
        float drive:angular:physics:damping = 0.1
    }

    def Xform "Acceleration" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:mass = 1
        float3 physics:diagonalInertia = (0.0017, 0.0842, 0.0842)
        double3 xformOp:translate = (0.5, 0.5, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }

    def PhysicsRevoluteJoint "AccelerationHinge" (
        prepend apiSchemas = ["PhysicsDriveAPI:angular"]
    )
    {
        uniform token physics:axis = "Y"
        rel physics:body0 = </Bot/Base>
        rel physics:body1 = </Bot/Acceleration>
        point3f physics:localPos0 = (0, 0.5, 0)
        point3f physics:localPos1 = (-0.5, 0, 0)
        uniform token drive:angular:physics:type = "acceleration"
        float drive:angular:physics:stiffness = 1.5
        float drive:angular:physics:damping = 0.3
    }
}
"""

# test_27c's stages: Z-up, in metres or centimetres (MPU), with earth's gravity in their units (GRAVITY), and a
# timeline long enough to play past 4 s.
_UNITS_STAGE_USDA = """#usda 1.0
(
    defaultPrim = "World"
    endTimeCode = 1000
    kilogramsPerUnit = 1
    metersPerUnit = MPU
    startTimeCode = 0
    timeCodesPerSecond = 60
    upAxis = "Z"
)

def Xform "World"
{
    def PhysicsScene "PhysicsScene"
    {
        vector3f physics:gravityDirection = (0, 0, -1)
        float physics:gravityMagnitude = GRAVITY
    }
}
"""

# Plays to UNTIL seconds of simulation, then pauses: the timeline's time, whatever an update's length, bounded by a
# count of updates so a timeline that doesn't move can't hold the call. The time reached.
_PLAY_TO = """
import omni.kit.app
import omni.timeline

timeline = omni.timeline.get_timeline_interface()
timeline.play()
updates = 0
while timeline.get_current_time() < UNTIL and updates < 2000:
    await omni.kit.app.get_app().next_update_async()
    updates += 1
timeline.pause()
await omni.kit.app.get_app().next_update_async()
result = timeline.get_current_time()
"""

# Kit's metrics assembler resolving PATH into an anonymous layer of its own, as #112's probe did, so neither the robot's
# file nor the stage's layer is written: PATH's ops and scale, and the values NAMES lists, before and after, and which
# of them Kit wrote into its layer. That layer is weaker than the stage's, which holds create_robot's converted values,
# so only its specs show whether Kit converted one again. None without the assembler.
_RESOLVE_UNITS = """
try:
    from omni.metrics.assembler.core import get_metrics_assembler_interface
except ImportError:
    result = None
else:
    context = omni.usd.get_context()
    stage = context.get_stage()

    def read():
        prim = stage.GetPrimAtPath(PATH)
        values = {}
        for path, name in NAMES:
            value = stage.GetPrimAtPath(path).GetAttribute(name).Get()
            values[path + "." + name] = [float(v) for v in value] if hasattr(value, "__len__") else float(value)
        return {
            "ops": [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()],
            "scale": [float(v) for v in prim.GetAttribute("xformOp:scale:unitsResolve").Get()],
            "values": values,
        }

    before = read()
    layer = Sdf.Layer.CreateAnonymous("ovmcp-IntTest-resolve")
    stage.GetRootLayer().subLayerPaths.insert(0, layer.identifier)
    assembler = get_metrics_assembler_interface()
    assembler.set_resolve_layer(layer.identifier)
    try:
        assembler.resolve_hierarchy(context.get_stage_id(), PATH)
    finally:
        assembler.set_resolve_layer(None)
    written = [path + "." + name for path, name in NAMES if layer.GetAttributeAtPath(path + "." + name) is not None]
    result = {"before": before, "after": read(), "written": written}
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
# What a capture's feed captures with and renders through (handlers/camera_feed.py), each looked up when it is used.
_FILE_CAPTURE = "import omni.kit.widget.viewport.capture as target"
_HYDRA_TEXTURE = "import omni.kit.hydra_texture as target"

# Kit's capture delegate as the feed is handed it, done at once with the result it names, and no file written. A frame
# handed to it is ignored.
_FINISHED_CAPTURE = """
class wrapper:
    def __init__(self, *args, **kwargs):
        pass

    def capture(self, *args, **kwargs):
        pass

    async def wait_for_result(self, completion_frames=2):
        return {result!r}
"""

# Textures made with their updates off, so a capture's feed renders no frame, as a viewport with its updates off.
_NO_FRAMES = """
def wrapper(*args, **kwargs):
    texture = original(*args, **kwargs)
    if texture is not None:
        texture.set_updates_enabled(False)
    return texture
"""

# What a capture could leave behind or change, to compare before and after: every path under /Render, composed or
# held by a layer, but /Render/Vars, where Kit keeps the outputs render products share; whether the root layer's text
# names a capture's feed (Kit lists render products in /Render/OmniverseGlobalRenderSettings.products there); the
# capture graphs omni.syntheticdata still keeps; and the viewport's camera, size, render scale and fill mode.
_CAPTURE_TRACES = """
from omni.kit.viewport.utility import get_active_viewport
from omni.syntheticdata import SyntheticData
from pxr import Usd

stage = omni.usd.get_context().get_stage()
paths = set()
render = stage.GetPrimAtPath("/Render")
if render:
    paths.update(str(prim.GetPath()) for prim in Usd.PrimRange(render))
for layer in stage.GetLayerStack(includeSessionLayers=True):
    if layer.GetPrimAtPath("/Render"):
        layer.Traverse("/Render", lambda path: paths.add(str(path)) if path.IsPrimPath() else None)
viewport = get_active_viewport()
result = {
    "render": sorted(path for path in paths if not path.startswith("/Render/Vars")),
    "root_names_a_feed": "ovmcp_capture_" in stage.GetRootLayer().ExportToString(),
    "graphs": sorted(path for path in SyntheticData.Get()._nodeGraphs if "ovmcp_capture_" in path),
    "viewport": [
        str(viewport.camera_path), list(viewport.full_resolution), viewport.resolution_scale, viewport.fill_frame
    ],
}
"""

# The pixels of one colour in a segmentation PNG, as their extent [x0, y0, x1, y1], counted in Kit with the numpy and
# Pillow Isaac Sim ships; None when there are none.
_COLOUR_EXTENT = """
import base64, io
import numpy as np
from PIL import Image

rgb = np.asarray(Image.open(io.BytesIO(base64.b64decode(SEGMENTATION))).convert("RGB"))
ys, xs = np.nonzero(np.all(rgb == np.array(COLOUR, dtype=np.uint8), axis=-1))
result = None if xs.size == 0 else [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
"""

# A camera prim aimed at a point from another side than the viewport's, on the stage's up axis. A wide lens, as the
# viewport's own: with USD's default 50 mm the cube filled the frame, and a box that is the whole frame shows little.
_AIMED_CAMERA = """
from pxr import Gf, UsdGeom

stage = omni.usd.get_context().get_stage()
up = Gf.Vec3d(0, 0, 1) if UsdGeom.GetStageUpAxis(stage) == "Z" else Gf.Vec3d(0, 1, 0)
target = Gf.Vec3d(*TARGET)
eye = target + Gf.Vec3d(-1.5, 0, 0) + up * 0.8 + (Gf.Vec3d(0, 1.2, 0) if up[2] else Gf.Vec3d(0, 0, 1.2))
camera = UsdGeom.Camera.Define(stage, PATH)
camera.CreateFocalLengthAttr(18.0)
UsdGeom.Xformable(camera).ClearXformOpOrder()
UsdGeom.Xformable(camera).AddTransformOp().Set(Gf.Matrix4d().SetLookAt(eye, target, up).GetInverse())
result = PATH
"""


# The centre of the red pixels in the viewport's own frame, as fractions of its size off the middle; None when there
# are none. What the user sees, where a capture renders a feed of its own.
_VIEWPORT_RED = """
import io
import numpy as np
from PIL import Image
from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
from ovmcp.bridge.handlers._utils import _settle_viewport, capture_file_png
viewport = get_active_viewport()
await _settle_viewport(frames=30)
png = await capture_file_png(lambda path: capture_viewport_to_file(viewport, file_path=path))
rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
ys, xs = np.nonzero((rgb[..., 0] > 120) & (rgb[..., 1] < 80) & (rgb[..., 2] < 80))
height, width = rgb.shape[:2]
result = None if xs.size == 0 else [float(xs.mean()) / width - 0.5, float(ys.mean()) / height - 0.5]
"""

# isaacsim.core.utils.viewports made unimportable, as in a Kit app without Isaac Sim, until the cleanup's
# _ISAAC_BACK, or Kit's loop after 60 s, and only while it is still this run's own.
_NO_ISAAC = """
import asyncio
import sys
NAME = "isaacsim.core.utils.viewports"
token = object()
sys._ovmcp_test_isaac = (sys.modules.get(NAME), token)
sys.modules[NAME] = None


def undo():
    held = getattr(sys, "_ovmcp_test_isaac", None)
    if held is not None and held[1] is token:
        if held[0] is None:
            sys.modules.pop(NAME, None)
        else:
            sys.modules[NAME] = held[0]
        sys._ovmcp_test_isaac = None


sys._ovmcp_test_isaac_undo = undo
asyncio.get_running_loop().call_later(60, undo)
result = "forced"
"""

_ISAAC_BACK = """
import sys
undo = getattr(sys, "_ovmcp_test_isaac_undo", None)
if undo is not None:
    undo()
result = sys.modules.get("isaacsim.core.utils.viewports") is not None
"""

# How many times set_camera_view's recorder (test_12f) was called; COUNT = 0 starts the count afresh. The count is
# kept on sys, since the module the recorder wraps is unimportable once the test hides it.
_ISAAC_CALLS = """
import sys
if COUNT == 0:
    sys._ovmcp_test_isaac_calls = 0
result = getattr(sys, "_ovmcp_test_isaac_calls", 0)
"""

# The ops and their values of the prims under ROOT, by path, and each one's world position, read in Kit.
_XFORMS = """
from pxr import Usd, UsdGeom
stage = omni.usd.get_context().get_stage()
result = {}
for prim in Usd.PrimRange(stage.GetPrimAtPath(ROOT)):
    xformable = UsdGeom.Xformable(prim)
    if not xformable:
        continue
    ops = {op.GetOpName(): repr(op.Get()) for op in xformable.GetOrderedXformOps()}
    where = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
    result[str(prim.GetPath())] = {"ops": list(ops), "values": ops, "world": [where[0], where[1], where[2]]}
"""

# A prim placed about a pivot and one placed by a matrix, under /World/IntTestXforms: imported assets carry both.
_PLACED = """
from pxr import Gf, UsdGeom
stage = omni.usd.get_context().get_stage()
UsdGeom.Xform.Define(stage, "/World/IntTestXforms")
pivoted = UsdGeom.XformCommonAPI(UsdGeom.Xform.Define(stage, "/World/IntTestXforms/Pivoted"))
pivoted.SetTranslate(Gf.Vec3d(1, 0, 0))
pivoted.SetPivot(Gf.Vec3f(0, 0.5, 0))
pivoted.SetRotate(Gf.Vec3f(0, 0, 90))
placed = UsdGeom.Xform.Define(stage, "/World/IntTestXforms/Matrix")
turned = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d.ZAxis(), 30))
placed.AddTransformOp().Set(turned * Gf.Matrix4d().SetTranslate(Gf.Vec3d(1, 2, 3)))
box = UsdGeom.Cube.Define(stage, "/World/IntTestXforms/Matrix/Box")
box.CreateSizeAttr(0.2)
box.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
result = "placed"
"""


def _png_size(image_base64: str) -> tuple[int, int]:
    """A base64 PNG's width and height, from its header."""
    head = base64.b64decode(image_base64[:32])
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


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
        # open_scene's calls get the server's own 120 s: an open over the network takes seconds (#79).
        cls.slow = BridgeClient(host=host, port=port, timeout=120.0)
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
            "/World/IntTestOpen",
        ]:
            try:
                cls.client.delete_prim(path)
            except Exception:
                pass
        cls.client.close()
        cls.slow.close()

    # ===== Basic connectivity =====

    def test_01_health(self):
        result = self.client.health()
        self.assertEqual(result["status"], "success")
        self.assertIn("up_axis", result["result"])
        # The Kit app, for people, as /sim/state gives get_sim_state (#105).
        for key in _KIT_FACTS:
            self.assertNotIn(result["result"].get(key, "unknown"), ("", "unknown"), key)
        print(f"  Stage: {result['result']}")

    def test_02_sim_state(self):
        result = self.client.sim_state()
        self.assertEqual(result["status"], "success")
        facts = {key: result["result"].get(key, "unknown") for key in _KIT_FACTS}
        for key, value in facts.items():
            self.assertNotIn(value, ("", "unknown"), key)
        erred, text = call_tool("get_sim_state", {}, self._output_folder())
        self.assertFalse(erred, text)
        app = f"kit_app = {facts['kit_app_name']} {facts['kit_app_version']}"
        self.assertIn(f"{app}\nkit_version = {facts['kit_version']}\nkit_os = {facts['kit_os']}\n", text)
        print(f"  State: {result['result']['state']}, Prims: {result['result']['prim_count']}, {app}")

    def test_03_scene_tree(self):
        result = self.client.scene_tree("/", 3)
        self.assertEqual(result["status"], "success")
        print(f"  Root type: {result['result']['type']}")
        if "children" in result["result"]:
            for child in result["result"]["children"][:5]:
                print(f"    {child['path']} ({child['type']})")

    def test_03b_scene_tree_text_stops_at_max_depth(self):
        """The text listed the next level's prims that had children and left out the rest, so a childless prim there
        looked absent; it stops at max_depth now, with the prim's count of children (#82)."""
        # Its own prims: a fresh stage has no /World until an earlier test makes one.
        root = "/World/IntTestDepth"
        self.addCleanup(self.client.delete_prim, root)
        for path in (root, f"{root}/A", f"{root}/B", f"{root}/A/Deep"):
            made = self.client.create_prim(path, "Xform")
            self.assertEqual(made["status"], "success", made)
        result = self.client.scene_tree(root, 0, fmt="text")
        self.assertEqual(result["status"], "success", result)
        lines = result["result"]["text"].splitlines()
        self.assertEqual([line for line in lines if line.startswith("[")], [f"[{root}]"])
        self.assertIn("children = 2 (truncated)", lines)
        result = self.client.scene_tree(root, 1, fmt="text")
        self.assertEqual(result["status"], "success", result)
        lines = result["result"]["text"].splitlines()
        self.assertEqual([line for line in lines if line.startswith("[")], [f"[{root}]", f"[{root}/A]", f"[{root}/B]"])
        self.assertIn("children = 1 (truncated)", lines)
        print("  A tree at depth 0 and 1: the next level's children counted, not listed")

    def _output_folder(self) -> str:
        """A folder of the test's own for the server's files and Kit's, gone when the test ends."""
        folder = tempfile.mkdtemp(prefix="ovmcp-IntTest-")
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def test_03c_scene_tree_lists_or_dumps_through_the_server(self):
        """get_scene_tree through the MCP server (#77): the list without values, Kit's file with include_properties,
        whose prim count is the file's blocks, and a max_depth over the list's old cap of 15."""
        root, out = "/World/IntTestServerTree", self._output_folder()
        self.addCleanup(self.client.delete_prim, root)
        paths = (root, f"{root}/A", f"{root}/B", f"{root}/A/Deep")
        for path in paths:
            made = self.client.create_prim(path, "Xform")
            self.assertEqual(made["status"], "success", made)

        erred, text = call_tool("get_scene_tree", {"root": root, "max_depth": 1}, out)
        self.assertFalse(erred, text)
        lines = text.splitlines()
        self.assertEqual([line for line in lines if line.startswith("[")], [f"[{p}]" for p in paths[:3]])
        self.assertIn("children = 1 (truncated)", lines)

        erred, text = call_tool("get_scene_tree", {"root": root, "include_properties": True}, out)
        self.assertFalse(erred, text)
        dumped = re.fullmatch(
            rf"Dumped (\d+) prims under {re.escape(root)}, to depth 15 \([\d,]+ bytes\) -> (.+)", text
        )
        self.assertIsNotNone(dumped, text)
        assert dumped is not None
        dump = Path(out) / "scene_dump.txt"
        self.assertEqual(Path(dumped[2]).resolve(), dump.resolve())
        written = dump.read_text(encoding="utf-8")
        blocks = [line for line in written.splitlines() if line.startswith("[/")]
        self.assertEqual(sorted(blocks), sorted(f"[{p}]" for p in paths))
        self.assertEqual(int(dumped[1]), len(blocks))
        self.assertIn("\nvisibility = ", written)  # the attribute values include_properties asks for

        erred, text = call_tool("get_scene_tree", {"root": root, "max_depth": 20}, out)
        self.assertFalse(erred, text)
        self.assertEqual(
            sorted(line for line in text.splitlines() if line.startswith("[")), sorted(f"[{p}]" for p in paths)
        )
        self.assertNotIn("truncated", text)
        print(f"  Listed to depth 1, dumped {len(blocks)} prims to {dump.name}, listed to depth 20")

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

    def test_07b_a_part_of_a_referenced_file_is_not_deleted(self):
        """delete_prim answered "Deleted" for a part of a referenced file and left it there, its root-layer override
        gone; it is refused now, naming the reference, and the override stays (#82)."""
        usd = Path(tempfile.mkdtemp(prefix="ovmcp-ref-")) / "IntTestBot.usda"
        self.addCleanup(shutil.rmtree, usd.parent, True)
        usd.write_text(_ROBOT_USDA, encoding="utf-8")
        self.addCleanup(self.client.delete_prim, "/World/IntTestRef")
        made = self.client.create_prim("/World/IntTestRef", usd_path=str(usd))
        self.assertEqual(made["status"], "success", made)
        moved = self.client.set_transform("/World/IntTestRef/Body", position=[0, 1, 0])
        self.assertEqual(moved["status"], "success", moved)

        result = self.client.delete_prim("/World/IntTestRef/Body")

        self.assertEqual(result["status"], "error", result)
        self.assertIn("comes through a reference on /World/IntTestRef", result["error"])
        body = self._kit(_XFORMS.replace("ROOT", repr("/World/IntTestRef/Body")))["/World/IntTestRef/Body"]
        self.assertEqual(body["world"], [0.0, 1.0, 0.0])  # the root layer's override, kept
        deleted = self.client.delete_prim("/World/IntTestRef")  # the referencing prim goes, with its reference
        self.assertEqual(deleted["status"], "success", deleted)
        self.assertTrue(deleted["result"]["checked"])
        print(f"  Refused: {result['error']}")

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

    def test_08b_set_transform_keeps_a_pivot_and_a_matrix(self):
        """set_prim_transform rewrote a prim's ops as translate, rotate and scale: a pivot went, could be read as the
        position, and a matrix-placed prim lost its placement (#82)."""
        self.addCleanup(self.client.delete_prim, "/World/IntTestXforms")
        self._kit(_PLACED)
        read = _XFORMS.replace("ROOT", repr("/World/IntTestXforms"))
        before = self._kit(read)

        for result in (
            self.client.set_transform("/World/IntTestXforms/Pivoted", position=[4.0, 0.0, 0.0]),
            self.client.set_transform(
                "/World/IntTestXforms/Matrix", position=[5.0, 6.0, 7.0], rotation=[0.0, 0.0, 90.0]
            ),
        ):
            self.assertEqual(result["status"], "success", result)
        after = self._kit(read)

        pivoted, was = after["/World/IntTestXforms/Pivoted"], before["/World/IntTestXforms/Pivoted"]
        self.assertEqual(pivoted["ops"], was["ops"])
        self.assertEqual(pivoted["values"]["xformOp:translate"], "Gf.Vec3d(4.0, 0.0, 0.0)")
        self.assertEqual(pivoted["values"]["xformOp:translate:pivot"], was["values"]["xformOp:translate:pivot"])
        self.assertEqual(after["/World/IntTestXforms/Matrix"]["ops"], ["xformOp:transform"])
        # The box sits one unit along the matrix's own X, which now points along world Y.
        for got, want in zip(after["/World/IntTestXforms/Matrix/Box"]["world"], [5, 7, 7], strict=True):
            self.assertAlmostEqual(got, want, places=4)
        print(f"  Pivot kept: {pivoted['ops']}; the matrix moved and turned in place")

    def test_08c_get_prim_properties_reads_a_scaled_prim_s_rotation(self):
        """Scenario 2.2: rotateXYZ (0, 45, 0) at scale 0.5 read as 0.7428, 0, 0.6695, 0, an 84° turn, with the scale
        left in the matrix the rotation was read from (#105)."""
        path = "/World/IntTestScaled"
        self.addCleanup(self.client.delete_prim, path)
        self.assertEqual(self.client.create_prim(path, "Cube")["status"], "success")
        done = self.client.set_transform(path, rotation=[0.0, 45.0, 0.0], scale=[0.5, 0.5, 0.5])
        self.assertEqual(done["status"], "success", done)

        erred, text = call_tool("get_prim_properties", {"prim_path": path}, self._output_folder())

        self.assertFalse(erred, text)
        self.assertIn("rot = 0.9239, 0.0000, 0.3827, 0.0000", text)

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

    def test_10b_the_viewports_own_segmentation_stays_off(self):
        """After a capture with its segmentation, the viewport's own sensor is off: captures segment through feeds of
        their own, and the bridge no longer turns the viewport's on at startup, which copied its instance ids to the
        host every frame (#76). On a fresh Kit this runs on the stage it started with, where 0.2.3 had turned it on."""
        result = self.client.capture_viewport(320, 240)
        self.assertEqual(result["status"], "success", result)
        self.assertIsNotNone(result["result"]["segmentation_base64"], result["result"].get("segmentation_error"))
        self.assertFalse(self._kit(VIEWPORT_SEGMENTATION_ON))
        print("  The capture had its segmentation; the viewport's own sensor is off")

    def test_11_camera_set(self):
        result = self.client.camera_set([5, 3, 5], [0, 0, 0])
        self.assertEqual(result["status"], "success")
        self.assertIn("position", result["result"])
        aim = self._camera_aim([0, 0, 0])
        self.assertLess(aim["degrees"], 0.5, aim)
        print(f"  Camera at {result['result']['position']}, {aim['degrees']:.3f} degrees off the origin")
        self._straight_down_a_y_up_stage()

    def _straight_down_a_y_up_stage(self):
        """Straight down a Y-up stage's up axis, where Isaac Sim's call alone left the camera at the origin with a
        scale of about 3.4e38: the check after it puts the camera's ops back and aims it through USD."""
        up = self.client.sim_state()["result"]["up_axis"]
        if up != "Y":
            set_axis = (
                "from pxr import UsdGeom\nUsdGeom.SetStageUpAxis(omni.usd.get_context().get_stage(), {!r})\nresult = 1"
            )
            self._kit(set_axis.format("Y"))
            self.addCleanup(self._kit, set_axis.format(up))
        target, eye = [0.0, 0.5, 0.0], [0.0, 8.0, 0.0]
        self.addCleanup(self.client.delete_prim, "/World/IntTestDown")
        self.client.create_prim("/World/IntTestDown", "Cube", position=target, scale=0.2)

        result = self.client.camera_set(eye, target)

        self.assertEqual(result["status"], "success", result)
        aim = self._camera_aim(target)
        self.assertLess(aim["degrees"], 0.5, aim)
        for got, want in zip(aim["eye"], eye, strict=True):
            self.assertAlmostEqual(got, want, places=3)
        for scale in aim["scale"]:
            self.assertAlmostEqual(scale, 1.0, places=3)
        self._assert_centred_in_a_capture("/World/IntTestDown")
        print(f"  Straight down a Y-up stage: {aim['degrees']:.3f} degrees off, scale {aim['scale']}")

    def _camera_aim(self, target: list[float]) -> dict:
        """CAMERA_AIM for target, read in Kit."""
        return self._kit(f"TARGET = {list(target)!r}\n{CAMERA_AIM}")

    def _assert_centred_in_a_capture(self, prim: str) -> None:
        """The prim's box sits within 5% of a 320x240 capture's middle."""
        capture = self.client.capture_viewport(320, 240)
        self.assertEqual(capture["status"], "success", capture)
        (box,) = [b["screen_bbox"] for b in capture["result"]["screen_bboxes"] if b["prim_path"] == prim]
        self.assertLess(abs((box[0] + box[2]) / 2 - 160), 16, box)
        self.assertLess(abs((box[1] + box[3]) / 2 - 120), 12, box)

    def test_12_camera_look_at(self):
        # Create something to look at
        self.client.create_prim("/World/IntTestCube", "Cube", position=[0, 0.5, 0], scale=[0.3, 0.3, 0.3])
        result = self.client.camera_look_at("/World/IntTestCube", azimuth=45, elevation=30)
        self.assertEqual(result["status"], "success")
        self.assertGreater(result["result"]["distance"], 0)
        aim = self._camera_aim(result["result"]["target"])
        self.assertLess(aim["degrees"], 0.5, aim)
        print(f"  Looking at IntTestCube, dist={result['result']['distance']:.2f}, {aim['degrees']:.3f} degrees off")

    # ===== Captures at the size asked for, through a feed of their own (#51) =====

    def _traces(self) -> dict:
        """_CAPTURE_TRACES, read in Kit."""
        return self._kit(_CAPTURE_TRACES)

    def _cube_box_and_pixels(self, result: dict, prim: str = "/World/IntTestCube") -> tuple[list, list]:
        """The prim's screen box in a capture, and the extent of its colour in the capture's segmentation."""
        (box,) = [b["screen_bbox"] for b in result["screen_bboxes"] if b["prim_path"] == prim]
        colour = result["segmentation_legend"][prim]
        code = _COLOUR_EXTENT.replace("SEGMENTATION", repr(result["segmentation_base64"])).replace(
            "COLOUR", repr(colour)
        )
        pixels = self._kit(code)
        self.assertIsNotNone(pixels, f"{prim}'s colour isn't in its segmentation")
        return box, pixels

    def _assert_box_on_pixels(self, box: list, pixels: list) -> None:
        for edge, (b, p) in enumerate(zip(box, pixels, strict=True)):
            self.assertLessEqual(abs(b - p), 2, f"edge {edge}: box {box} against the pixels {pixels}")

    def test_12b_capture_is_the_size_asked_for(self):
        """The image, its segmentation and its boxes at the size asked for, the boxes on the cube's pixels, whatever the
        viewport's size; on 0.2.2 the image was the viewport's 1280x720 while the boxes were scaled to the size asked
        for (#51)."""
        for width, height in ((320, 240), (640, 360), (360, 640)):
            result = self.client.capture_viewport(width, height)
            self.assertEqual(result["status"], "success", result)
            r = result["result"]
            self.assertEqual((r["width"], r["height"]), (width, height))
            self.assertEqual(_png_size(r["image_base64"]), (width, height))
            self.assertIsNotNone(r["segmentation_base64"], r.get("segmentation_error"))
            self.assertEqual(_png_size(r["segmentation_base64"]), (width, height))
            box, pixels = self._cube_box_and_pixels(r)
            self._assert_box_on_pixels(box, pixels)
            print(f"  {width}x{height}: box {box}, pixels {pixels}")

    def test_12c_capture_from_a_camera_path_boxes_that_camera(self):
        """With camera_path, the boxes are that camera's, where 0.2.2 projected them from the viewport's own camera
        (#70); the viewport's camera doesn't move; a path that isn't a camera is refused."""
        camera = "/World/IntTestCam"
        self.addCleanup(self.client.delete_prim, camera)
        center = self.client.prim_bounds("/World/IntTestCube")["result"]["center"]
        self._kit(_AIMED_CAMERA.replace("TARGET", repr(center)).replace("PATH", repr(camera)))
        before = self._traces()["viewport"]

        result = self.client.capture_viewport(640, 480, camera_path=camera)
        self.assertEqual(result["status"], "success", result)
        box, pixels = self._cube_box_and_pixels(result["result"])
        self.assertTrue(
            0 < box[0] < box[2] < 640 and 0 < box[1] < box[3] < 480, f"the cube isn't inside the frame: {box}"
        )
        self._assert_box_on_pixels(box, pixels)
        self.assertEqual(self._traces()["viewport"], before)

        for path, why in (("/World/NoSuchCamera", "No prim at /World/NoSuchCamera"), ("/World/IntTestCube", "not a")):
            refused = self.client.capture_viewport(320, 240, camera_path=path)
            self.assertEqual(refused["status"], "error", refused)
            self.assertIn(why, refused["error"])
        print(f"  {camera}: box {box}, pixels {pixels}")

    def _assert_nothing_left(self, before: dict, since: int) -> None:
        """Nothing of a capture's left once it answered: the stage's /Render, the root layer, omni.syntheticdata's
        graphs and the viewport as before, and, 2 s on, no error from a graph left behind in Kit's log (#51's E16)."""
        after = self._traces()
        self.assertEqual(after, before)
        self.assertFalse(after["root_names_a_feed"])
        self.assertEqual(after["graphs"], [])
        time.sleep(2.0)
        logged = self.client.get_logs(count=50, since_index=since, search="Py_Graph")["result"]["entries"]
        self.assertEqual(logged, [], "omni.syntheticdata tripped on a capture's graph")

    def _log_index(self) -> int:
        entries = self.client.get_logs(count=1)["result"]["entries"]
        return entries[-1]["index"] if entries else -1

    def test_12d_a_capture_leaves_nothing(self):
        """A capture, and one that fails after its segmentation is turned on, leave the stage, its root layer,
        omni.syntheticdata and the viewport as they found them."""
        camera = "/World/IntTestCam"
        self.addCleanup(self.client.delete_prim, camera)
        center = self.client.prim_bounds("/World/IntTestCube")["result"]["center"]
        self._kit(_AIMED_CAMERA.replace("TARGET", repr(center)).replace("PATH", repr(camera)))
        self.assertEqual(self.client.capture_viewport(320, 240, camera_path=camera)["status"], "success")
        before, since = self._traces(), self._log_index()

        result = self.client.capture_viewport(320, 240, camera_path=camera)
        self.assertEqual(result["status"], "success", result)
        self.assertIsNotNone(result["result"]["segmentation_base64"], result["result"].get("segmentation_error"))
        self._assert_nothing_left(before, since)

        self._wrap(_FILE_CAPTURE, "FileCapture", _FINISHED_CAPTURE.format(result=[]))
        since = self._log_index()
        failed = self.client.capture_viewport(320, 240, camera_path=camera)
        self.assertEqual(failed["status"], "error", failed)
        self.assertIn("wait_for_result gave []", failed["error"])
        self._assert_nothing_left(before, since)
        print(f"  {len(before['render'])} paths under /Render before and after, a capture and a failed one")

    def test_12e_an_oversized_capture_is_refused(self):
        """A side above 4096 is refused before anything is made."""
        before = self._traces()
        for result in (
            self.client.capture_viewport(capture.MAX_SIDE + 1, 240),
            self.client.camera_inspect("/World/IntTestCube", angles=["front"], width=5000, height=240),
        ):
            self.assertEqual(result["status"], "error", result)
            self.assertIn("from 1 to 4096", result["error"])
        self.assertEqual(self._traces(), before)

    # ===== The camera aimed through USD, in the session layer (#82) =====

    def test_12f_the_camera_aims_without_isaac_sim(self):
        """/camera/set, /camera/look_at and /camera/inspect aim the viewport's camera through USD, in the session layer
        that holds Kit's camera: once with Isaac Sim's call recorded but left undone, so the check after it must find
        the camera unaimed, and once without Isaac Sim at all. 0.2.3's fallback answered a USD error or moved
        nothing."""
        up = self.client.sim_state()["result"]["up_axis"]

        def at(a: float, h: float, b: float) -> list[float]:
            return [float(a), float(h), float(b)] if up == "Y" else [float(a), float(b), float(h)]

        target, prim = at(2, 0.5, -1), "/World/IntTestAim/Target"
        self.addCleanup(self.client.delete_prim, "/World/IntTestAim")
        self.client.create_prim("/World/IntTestAim", "Xform")
        made = self.client.create_prim(prim, "Cube", position=target, scale=0.5)
        self.assertEqual(made["status"], "success", made)
        red = self.client.set_material(prim, color=[1, 0, 0], material_path="/World/IntTestAim/Looks/Red_Mat")
        self.assertEqual(red["status"], "success", red)
        lighting = self.client.viewport_light("get")["result"]["lighting_mode"]
        self.addCleanup(self.client.viewport_light, "set", mode=lighting)
        self.client.viewport_light("set", mode="camera")

        # Isaac's call, recorded and left undone: the check after it must aim the camera.
        self._wrap(
            "import isaacsim.core.utils.viewports as target",
            "set_camera_view",
            """
            def wrapper(*args, **kwargs):
                import sys

                sys._ovmcp_test_isaac_calls = getattr(sys, "_ovmcp_test_isaac_calls", 0) + 1
            """,
        )
        self._isaac_calls(reset=True)
        self._aims(at(6, 3, 5), target, prim)
        self.assertEqual(self._isaac_calls(), 1)

        # Without Isaac Sim: its module unimportable, as in USD Composer. Undone first, before the wrap is.
        self._kit(_NO_ISAAC)
        self.addCleanup(self._kit, _ISAAC_BACK)
        self._aims(at(-5, 2, 4), target, prim)
        looked = self.client.camera_look_at(prim, azimuth=200, elevation=25)
        self.assertEqual(looked["status"], "success", looked)
        self.assertLess(self._camera_aim(looked["result"]["target"])["degrees"], 0.5)
        inspected = self.client.camera_inspect(prim, angles=["front"], width=64, height=48)
        self.assertEqual(inspected["status"], "success", inspected)
        (front,) = inspected["result"]["captures"]
        self.assertIn("image_base64", front, front)
        self.assertLess(self._camera_aim(inspected["result"]["center"])["degrees"], 0.5)
        self.assertEqual(self._isaac_calls(), 1)  # none without Isaac Sim
        print("  Aimed through USD with Isaac's call left undone, and without Isaac Sim")

    def _aims(self, eye: list[float], target: list[float], prim: str) -> None:
        """set_camera from eye: the camera looks at target, Kit's camera keeps its ops in the session layer, and the
        prim is in the middle of a capture and of the viewport's own frame."""
        result = self.client.camera_set(eye, target)
        self.assertEqual(result["status"], "success", result)
        aim = self._camera_aim(target)
        self.assertLess(aim["degrees"], 0.5, aim)
        self.assertEqual(aim["root_xform"], [], aim)
        self._assert_centred_in_a_capture(prim)
        centre = self._kit(_VIEWPORT_RED)
        self.assertIsNotNone(centre, "no red in the viewport's own frame")
        self.assertLess(max(abs(centre[0]), abs(centre[1])), 0.05, centre)

    def _isaac_calls(self, reset: bool = False) -> int:
        return self._kit(f"COUNT = {0 if reset else 1}\n{_ISAAC_CALLS}")

    def test_12g_a_prim_behind_the_camera_gets_no_screen_box(self):
        """A prim behind the camera has no screen box, and one across the camera's plane is boxed by its part in front.
        0.2.3 divided the corners behind the camera by their depth, which mirrored them onto the screen: a box near the
        image's middle for a prim it couldn't show (#90)."""
        up = self.client.sim_state()["result"]["up_axis"]

        def at(a: float, h: float, b: float) -> list[float]:
            return [float(a), float(h), float(b)] if up == "Y" else [float(a), float(b), float(h)]

        # Swapping y and z mirrors the scene, so the camera's right is +x on a Y-up stage and -x on a Z-up one.
        right = 1.5 if up == "Y" else -1.5
        root = "/World/IntTestBehind"
        ahead, behind, across = f"{root}/Ahead", f"{root}/Behind", f"{root}/Across"
        self.addCleanup(self.client.delete_prim, root)
        for path, position, scale in (
            (ahead, at(0, 0.5, 0), at(0.5, 0.5, 0.5)),
            (behind, at(0, 0.5, 8), at(0.5, 0.5, 0.5)),
            # 0.2 by 8 along the view, to the right: it reaches from 4 in front of the camera to 4 behind it.
            (across, at(right, 0.5, 5), at(0.1, 0.1, 4)),
        ):
            made = self.client.create_prim(path, "Cube", position=position, scale=scale)
            self.assertEqual(made["status"], "success", made)
        aimed = self.client.camera_set(at(0, 0.5, 5), at(0, 0.5, 0))
        self.assertEqual(aimed["status"], "success", aimed)

        result = self.client.capture_viewport(320, 240)

        self.assertEqual(result["status"], "success", result)
        boxes = {b["prim_path"]: b["screen_bbox"] for b in result["result"]["screen_bboxes"]}
        self.assertNotIn(behind, boxes)
        self.assertLess(abs((boxes[ahead][0] + boxes[ahead][2]) / 2 - 160), 16, boxes[ahead])
        # Its part in front is all right of the middle, running off the right edge where the near plane cuts it; its
        # mirrored corners reached into the left half.
        self.assertGreater(boxes[across][0], 160, boxes[across])
        self.assertEqual(boxes[across][2], 320.0, boxes[across])
        print(f"  ahead {boxes[ahead]}, across {boxes[across]}, behind none")

    def test_12h_set_camera_aims_at_a_point_or_a_prim_through_the_server(self):
        """set_camera through the MCP server (#77): a point without a target, which the answer now says is the world
        origin; a prim, framed by the route the prim form picks; and the two forms mixed, refused before the camera
        moves."""
        out = self._output_folder()
        prim = "/World/IntTestServerAim"
        self.addCleanup(self.client.delete_prim, prim)
        made = self.client.create_prim(prim, "Cube", position=[1.0, 2.0, 0.5], scale=0.5)
        self.assertEqual(made["status"], "success", made)

        erred, text = call_tool("set_camera", {"position": [5, 3, 5]}, out)
        self.assertFalse(erred, text)
        self.assertTrue(text.endswith(" looking at [0, 0, 0], the world origin: no target was given"), text)
        aim = self._camera_aim([0, 0, 0])
        self.assertLess(aim["degrees"], 0.5, aim)

        erred, text = call_tool("set_camera", {"prim_path": prim, "azimuth": 30, "elevation": 20}, out)
        self.assertFalse(erred, text)
        framed = re.search(rf"looking at the centre of {re.escape(prim)}, \[([^\]]+)\]\nDistance: ", text)
        self.assertIsNotNone(framed, text)
        assert framed is not None
        centre = [float(v) for v in framed[1].split(",")]
        bounds = self.client.prim_bounds(prim)
        self.assertEqual(bounds["status"], "success", bounds)
        for got, want in zip(centre, bounds["result"]["center"], strict=True):
            self.assertAlmostEqual(got, want, places=4)
        self.assertIn("Azimuth: 30.0deg, Elevation: 20.0deg", text)
        aim = self._camera_aim(centre)
        self.assertLess(aim["degrees"], 0.5, aim)

        erred, text = call_tool("set_camera", {"prim_path": prim, "position": [5, 3, 5]}, out)
        self.assertTrue(erred, text)
        self.assertIn("leave position and target out", text)
        unmoved = self._camera_aim(centre)
        for got, want in zip(unmoved["eye"], aim["eye"], strict=True):
            self.assertAlmostEqual(got, want, places=4)
        self.assertLess(unmoved["degrees"], 0.5, unmoved)
        print(f"  At a point, around {prim} at {centre}, and the mix refused with the camera where it was")

    def test_12i_a_prim_beside_the_view_gets_no_screen_box(self):
        """Scenario 26.2: a 2 m cube beside the view of a 1 m one got a box at the frame's corner, as the rectangle of
        its projected corners reached it while its outline didn't, and no pixel of it showed (#105)."""
        up = self.client.sim_state()["result"]["up_axis"]

        def at(a: float, h: float, b: float) -> list[float]:
            return [float(a), float(h), float(b)] if up == "Y" else [float(a), float(b), float(h)]

        root = "/World/IntTestBeside"
        near, side = f"{root}/Near", f"{root}/Side"
        self.addCleanup(self.client.delete_prim, root)
        for path, position, scale in ((near, at(0, 1, 0), 0.5), (side, at(3, 0.5, 0), 1.0)):
            made = self.client.create_prim(path, "Cube", position=position, scale=scale)
            self.assertEqual(made["status"], "success", made)
        aimed = self.client.camera_set(at(1.53, 2.25, 1.53), at(0, 1, 0))
        self.assertEqual(aimed["status"], "success", aimed)

        result = self.client.capture_viewport(640, 480)

        self.assertEqual(result["status"], "success", result)
        boxes = {b["prim_path"]: b["screen_bbox"] for b in result["result"]["screen_bboxes"]}
        self.assertNotIn(side, boxes)
        # An empty legend from a segmentation that failed would pass for one without the side cube (I13).
        self.assertIsNone(result["result"].get("segmentation_error"), result["result"].get("segmentation_error"))
        self.assertNotIn(side, result["result"]["segmentation_legend"])
        # The probe measured the near cube at [145.7, 87.6, 494.3, 444.1]; mirrored on a Z-up stage, it is centred.
        self.assertLess(abs((boxes[near][0] + boxes[near][2]) / 2 - 320), 16, boxes[near])
        print(f"  near {boxes[near]}, beside the view none")

    def test_12j_an_unlit_capture_warns_though_the_grid_shows(self):
        """Scenario 23.6: with lighting off the prims render black and the grid doesn't, so the image isn't all black
        and no warning came. Lighting off, and stage on a stage without lights, now warn (#105). The stage's lights
        read the same in every mode, a light rig's never among them (#117)."""
        found = self.client.viewport_light("get")
        self.assertEqual(found["status"], "success", found)
        self.addCleanup(self.client.viewport_light, "set", mode=found["result"]["lighting_mode"])
        prim = "/World/IntTestUnlit"
        self.addCleanup(self.client.delete_prim, prim)
        self.assertEqual(self.client.create_prim(prim, "Cube", scale=0.5)["status"], "success")
        out = self._output_folder()

        def light_paths() -> list[str]:
            got = self.client.viewport_light("get")
            self.assertEqual(got["status"], "success", got)
            paths = [light["path"] for light in got["result"]["scene_lights"]]
            self.assertEqual(got["result"]["has_scene_lights"], bool(paths), got)
            return paths

        # Read first in a light rig, whose lights Kit puts on the stage under /OmniKit_Viewport_LightRig, and which
        # mode stage takes away: the get counted them, and said a stage without lights was lit (#117). The lists of
        # paths are compared, not yes or no: on a stage with lights of its own, a rig counted again still reads yes.
        if "Default" in found["result"]["available_modes"]:
            self.assertEqual(self.client.viewport_light("set", mode="Default")["status"], "success")
        stage_lights = light_paths()
        self.assertFalse([p for p in stage_lights if p.startswith("/OmniKit_Viewport_LightRig")], stage_lights)
        lit = bool(stage_lights)

        for mode in ("off", "stage", "camera"):
            with self.subTest(mode=mode):
                self.assertEqual(self.client.viewport_light("set", mode=mode)["status"], "success")
                self.assertEqual(light_paths(), stage_lights)
                warns = {"off": True, "stage": not lit, "camera": False}[mode]
                erred, text = call_tool("capture_viewport", {"width": 160, "height": 120}, out)
                self.assertFalse(erred, text)
                # Kit 110's grid keeps an unlit image from being all black, so the lighting's warning comes; where a
                # Kit renders it all black, the black image's warning names the lighting instead (review F6). Only
                # the texts that name the lighting count: a lit stage's capture can be all black for a renderer not
                # yet warm, which names neither (review round 2).
                said = any(
                    named in text
                    for named in (
                        "surfaces render black",
                        "Lighting mode is 'off'",
                        "No scene lights and mode is 'stage'",
                    )
                )
                self.assertEqual(said, warns, text)
                if mode == "off":
                    erred, text = call_tool(
                        "inspect_prim", {"prim_path": prim, "angles": ["front"], "width": 160, "height": 120}, out
                    )
                    self.assertFalse(erred, text)
                    # Once a call: the lighting's warning, or the black one's where the angle is all black.
                    self.assertEqual(
                        text.count("Lighting mode is 'off'") + text.count("captures are all-black"), 1, text
                    )

    def test_13_camera_inspect_auto_fit(self):
        """Inspect with auto-fit distance (no zoom_offset)."""
        result = self.client.camera_inspect("/World/IntTestCube", angles=["front", "right"])
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["result"]["captures"]), 2)
        self.assertGreater(result["result"]["distance"], 0)
        for cap in result["result"]["captures"]:
            self.assertIn("image_base64", cap)
        print(f"  Inspect auto-fit: dist={result['result']['distance']:.2f}m, 2 angles")

    def test_13b_inspect_is_the_size_asked_for(self):
        """Each angle and its segmentation at the size asked for, where 0.2.2 gave the viewport's (#51), and nothing of
        the call's feed left after it."""
        # Warm: the first segmentation on a stage may make omni.syntheticdata's shared graphs, which stay.
        self.client.camera_inspect(
            "/World/IntTestCube", angles=["front"], width=320, height=240, include_segmentation=True
        )
        before, since = self._traces(), self._log_index()
        result = self.client.camera_inspect(
            "/World/IntTestCube", angles=["front", "top"], width=320, height=240, include_segmentation=True
        )
        self.assertEqual(result["status"], "success", result)
        self.assertEqual((result["result"]["width"], result["result"]["height"]), (320, 240))
        for cap in result["result"]["captures"]:
            self.assertIn("image_base64", cap, cap.get("error"))
            self.assertEqual(_png_size(cap["image_base64"]), (320, 240))
            self.assertIn("segmentation_base64", cap, cap.get("segmentation_error"))
            self.assertEqual(_png_size(cap["segmentation_base64"]), (320, 240))
        self._assert_nothing_left(before, since)
        print("  2 angles at 320x240, with segmentation")

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
        values = {"name": name, "value": seconds, "default": getattr(capture, name)}
        shortened = self._kit(SET_LIMIT.format(**values))
        if shortened:
            self.addCleanup(self._kit, RESTORE_LIMIT.format(**values))
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
        """Segmentation that never comes: each angle's answer says why, the first after one wait, the second after a
        brief one, since it got nothing with this camera and size on this stage before (#27, #51)."""
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
        self.assertIn(
            f"on this stage before, and none in the {capture.SEGMENTATION_RETRY_SECONDS:g} s this capture waited",
            second.get("segmentation_error", ""),
        )
        self.assertLess(took, 15)  # a guard against a hang; the messages tell one wait from two
        print(f"  2 angles, each saying why, in {took:.1f} s")

    def test_15e_an_empty_capture_fails_at_once(self):
        """A capture whose wait_for_result names nothing captured fails at once, where it waited 10 s for a file that
        could not come (#35). One that names LdrColor but writes no file, as Kit 110 does without a valid resource,
        fails after the file wait."""
        self._wrap(_FILE_CAPTURE, "FileCapture", _FINISHED_CAPTURE.format(result=[]))
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
        self._wrap(_FILE_CAPTURE, "FileCapture", _FINISHED_CAPTURE.format(result=["LdrColor"]))
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
        """With the viewport's updates off no frame comes: set_camera answers after one frame wait. With a capture's
        feed rendering nothing too (its texture's updates off), inspect_prim stops after its first angle, naming the
        angles it did not capture; both hung before (#35)."""
        frame_seconds = 3 if self._shorten("FRAME_SECONDS", 3) else capture.FRAME_SECONDS
        try:
            self.assertEqual(
                self._kit(_UPDATES_OFF), "no frame", "updates_enabled = False did not stop this Kit app's frames"
            )
            # inspect_prim renders through a feed of its own (#51), whose frames the viewport's updates don't stop.
            self._wrap(_HYDRA_TEXTURE, "create_hydra_texture", _NO_FRAMES)
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
            self._kit(_UNWRAP.format(target=_HYDRA_TEXTURE, name="create_hydra_texture"))
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
        since = self.client.get_logs(count=1)["result"]["total_captured"] - 1  # the newest entry's index
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

    def test_21b_clone_offset_keeps_each_copy_s_placement(self):
        """clone_prim's offset rewrote each copy's ops, so a matrix-placed source's copies lost their placement; copy n
        now moves n offsets from the source through its own matrix (#82)."""
        self.addCleanup(self.client.delete_prim, "/World/IntTestXforms")
        self._kit(_PLACED)

        result = self.client.clone_prim(
            "/World/IntTestXforms/Matrix", "/World/IntTestXforms/Row", count=3, offset=[2, 0, 0]
        )

        self.assertEqual(result["status"], "success", result)
        after = self._kit(_XFORMS.replace("ROOT", repr("/World/IntTestXforms")))
        source = after["/World/IntTestXforms/Matrix/Box"]["world"]
        for n, path in enumerate(result["result"]["clones"]):
            self.assertEqual(after[path]["ops"], ["xformOp:transform"])
            for got, want in zip(after[f"{path}/Box"]["world"], [source[0] + 2 * n, source[1], source[2]], strict=True):
                self.assertAlmostEqual(got, want, places=4)
        print(f"  {len(result['result']['clones'])} copies, each its matrix kept and moved by its offsets")

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

    def test_23b_mesh_stats_gives_totals_and_the_tree_through_the_server(self):
        """get_mesh_stats through the MCP server (#77): a mesh under an Xform, its totals inline, then the face count
        tree from the prim, with the mesh's counts and its parent's subtree_faces, and no `# total:` line."""
        root = "/World/IntTestServerMesh"
        self.addCleanup(self.client.delete_prim, root)
        # Two quads side by side: 2 faces, 6 points, 4 triangles.
        made = self._kit(
            "from pxr import Gf\n"
            "stage = omni.usd.get_context().get_stage()\n"
            f"UsdGeom.Xform.Define(stage, {root!r})\n"
            f"mesh = UsdGeom.Mesh.Define(stage, {root + '/Quads'!r})\n"
            "mesh.CreatePointsAttr([Gf.Vec3f(x, y, 0) for y in (0, 1) for x in (0, 1, 2)])\n"
            "mesh.CreateFaceVertexCountsAttr([4, 4])\n"
            "mesh.CreateFaceVertexIndicesAttr([0, 1, 4, 3, 1, 2, 5, 4])\n"
            "result = str(mesh.GetPath())"
        )
        self.assertEqual(made, f"{root}/Quads")

        erred, text = call_tool("get_mesh_stats", {"prim_path": root}, self._output_folder())

        self.assertFalse(erred, text)
        totals, tree = text.split("\n\n", 1)
        self.assertEqual(totals, f"[{root}]\nmeshes = 1\ntotal_faces = 2\ntotal_vertices = 6\ntotal_triangles = 4")
        self.assertTrue(tree.startswith(f"# face_count_tree root={root}\n"), tree)
        self.assertIn(f"[{root}]\ntype = Xform\nsubtree_faces = 2", tree)
        self.assertIn(f"[{root}/Quads]\ntype = Mesh\nfaces = 2\nvertices = 6\ntriangles = 4", tree)
        self.assertNotIn("# total:", tree)
        print(f"  {root}: the totals, then its tree of {tree.count('[/')} prims")

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

    def test_27b_a_robot_file_of_the_other_up_axis_stands(self):
        """A robot file that authors the up axis the stage hasn't stands upright on it, turned about X in Kit's own
        op, as Kit's metrics assembler turns a dropped file; the assembler, run on it after, adds no second turn
        (#105)."""
        up = self.client.sim_state()["result"]["up_axis"]
        other = "Z" if up == "Y" else "Y"
        tall = "(0.5, 0.5, 1)" if other == "Z" else "(0.5, 1, 0.5)"
        usd = Path(tempfile.mkdtemp(prefix="ovmcp-Robots-")) / "IntTestUpright.usda"
        self.addCleanup(shutil.rmtree, usd.parent, True)
        usd.write_text(_UPRIGHT_USDA.replace("UP", other).replace("TALL", tall), encoding="utf-8")
        path = "/World/IntTestUpright"
        self.addCleanup(self.client.delete_prim, path)

        result = self.client.create_robot(str(usd))

        self.assertEqual(result["status"], "success", result.get("error"))
        turn = result["result"]["up_axis_turn"]
        self.assertEqual((turn["file"], turn["stage"], turn["degrees"]), (other, up, -90.0 if up == "Y" else 90.0))
        axis = 1 if up == "Y" else 2
        dims = self.client.prim_bounds(path)["result"]["dimensions"]
        self.assertEqual(max(range(3), key=lambda i: dims[i]), axis, dims)
        resolved = self._kit(_RESOLVE.replace("PATH", repr(path)))
        if resolved is None:
            print(f"  stood upright on a {up}-up stage; no metrics assembler here")
            return
        self.assertEqual(resolved["ops"].count("xformOp:rotateX:unitsResolve"), 1, resolved)
        self.assertEqual(resolved["value"], turn["op"], resolved)
        dims = self.client.prim_bounds(path)["result"]["dimensions"]
        self.assertEqual(max(range(3), key=lambda i: dims[i]), axis, dims)
        print(f"  stood upright on a {up}-up stage, and Kit's assembler left it so: {resolved}")

    def test_27c_a_robot_file_of_other_units_behaves_as_in_the_stage_s(self):
        """A metre robot file on a metre stage and on a centimetre stage the test writes and opens: on the centimetre
        one it is scaled 100 times and its values converted, so each arm sags as far as on the metre one, the force
        drive's and the acceleration drive's. With the scale alone the force drive would be 10^4 times too weak; with
        the PhysX schema's table, the acceleration drive 10^4 times too stiff. Kit's assembler, run on it after,
        changes none of the force arm's values (#112)."""
        copy = self._saved_copy("IntTestUnitsBack.usda")
        self.addCleanup(self._reopen, copy)
        self.addCleanup(self.client.sim_control, "stop")
        folder = Path(tempfile.mkdtemp(prefix="ovmcp-Robots-"))
        self.addCleanup(shutil.rmtree, folder, True)
        robot = folder / "IntTestUnitsBot.usda"
        robot.write_text(_UNITS_BOT_USDA, encoding="utf-8")
        path = "/World/IntTestUnitsBot"
        sags: dict[str, dict[str, float]] = {}
        boxes: dict[str, list[float]] = {}
        for name, meters in (("metres", 1.0), ("centimetres", 0.01)):
            stage = folder / f"IntTestUnits_{name}.usda"
            text = _UNITS_STAGE_USDA.replace("MPU", f"{meters:g}").replace("GRAVITY", f"{9.81 / meters:g}")
            stage.write_text(text, encoding="utf-8")
            self._reopen(stage)

            result = self.client.create_robot(str(robot))

            self.assertEqual(result["status"], "success", result.get("error"))
            self.assertEqual(result["result"]["prim_path"], path)
            scaled = result["result"].get("units_scale")
            if meters == 1.0:
                self.assertIsNone(scaled)
            else:
                self.assertIsNotNone(scaled, "an extension older than #112's scales nothing")
                got = (scaled["factor"], scaled["op"], scaled["table"], scaled["left_count"])
                self.assertEqual(got, (100.0, [100.0, 100.0, 100.0], True, 0), scaled)
            boxes[name] = self.client.prim_bounds(f"{path}/Force")["result"]["dimensions"]
            sags[name] = self._settled_sags(path)
            self.assertEqual(self.client.sim_control("stop")["status"], "success")
        self._kit_leaves_the_force_arm(path)

        ratios = [round(c / m, 3) for c, m in zip(boxes["centimetres"], boxes["metres"], strict=True)]
        self.assertEqual(ratios, [100.0, 100.0, 100.0], boxes)
        for joint in ("ForceHinge", "AccelerationHinge"):
            metre, centimetre = sags["metres"][joint], sags["centimetres"][joint]
            self.assertGreater(abs(metre), 0.02, f"{joint} didn't sag on the metre stage: {sags}")
            self.assertAlmostEqual(centimetre, metre, delta=0.02 * abs(metre), msg=f"{joint}: {sags}")
        print(f"  sags in radians, metres and centimetres: {sags}")

    def _settled_sags(self, path: str) -> dict[str, float]:
        """Each hinge's angle in radians, by its name, once the arms have settled: played to 3 s and to 4 s of
        simulation, the two readings agreeing within 0.2%."""
        readings = []
        for until in (3.0, 4.0):
            done = self.slow.execute(_PLAY_TO.replace("UNTIL", repr(until)))
            self.assertEqual(done["status"], "success", done)
            self.assertGreaterEqual(done["result"]["return_value"], until, "the simulation didn't reach its time")
            states = self.client.get_joint_states(path)
            self.assertEqual(states["status"], "success", states)
            readings.append(dict(zip(states["result"]["names"], states["result"]["positions"], strict=True)))
        first, last = readings
        for joint, angle in last.items():
            self.assertAlmostEqual(first[joint], angle, delta=0.002 * abs(angle) + 1e-5, msg=f"unsettled: {readings}")
        return last

    def _kit_leaves_the_force_arm(self, path: str) -> None:
        """Kit's metrics assembler, resolving the robot on the centimetre stage, adds no op and writes none of the
        values create_robot converted into its layer (P5). It does convert the acceleration drive's gains, by its
        table, which create_robot leaves: printed, not checked."""
        names = [
            (f"{path}/Base", "physics:diagonalInertia"),
            (f"{path}/Force", "physics:density"),
            (f"{path}/ForceHinge", "drive:angular:physics:stiffness"),
            (f"{path}/ForceHinge", "drive:angular:physics:damping"),
            (f"{path}/Acceleration", "physics:diagonalInertia"),
        ]
        acceleration = (f"{path}/AccelerationHinge", "drive:angular:physics:stiffness")
        script = _RESOLVE_UNITS.replace("PATH", repr(path)).replace("NAMES", repr([*names, acceleration]))
        resolved = self._kit(script)
        if resolved is None:
            print("  no metrics assembler here")
            return
        before, after = resolved["before"], resolved["after"]
        self.assertEqual(after["ops"], before["ops"], resolved)
        self.assertEqual(after["ops"].count("xformOp:scale:unitsResolve"), 1, resolved)
        self.assertEqual(after["scale"], [100.0, 100.0, 100.0], resolved)
        for prim, name in names:
            key = f"{prim}.{name}"
            self.assertNotIn(key, resolved["written"], resolved)
            self.assertEqual(after["values"][key], before["values"][key], key)
        key = ".".join(acceleration)
        print(
            f"  Kit's assembler: the acceleration drive's stiffness {before['values'][key]} -> {after['values'][key]}"
        )

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

    # ===== Opening a scene (#79) =====
    # test_31 saves the stage the suite found and opens that copy again, so its content stays; the stage stays tied to
    # the copy, which the cleanup deletes.

    OPENED_CUBE = "/World/IntTestOpen"
    MISSING = "ovmcp-no-such-scene/Missing.usda"

    def _saved_copy(self, name: str) -> Path:
        """The open stage saved to a .usda of the test's own (one Windows doesn't hold locked), deleted after it."""
        folder = Path(tempfile.mkdtemp(prefix="ovmcp-open-"))
        self.addCleanup(shutil.rmtree, folder, True)
        path = folder / name
        r = self.client.save_scene(str(path))
        self.assertEqual(r["status"], "success", r)
        return path

    def _open(self, file_path: str) -> dict:
        return self.slow.open_scene(file_path)

    def _reopen(self, path: Path) -> None:
        r = self._open(str(path))
        self.assertEqual(r["status"], "success", r)

    def _cube_is_there(self) -> None:
        """test_31's cube: there before a refused open, as test_31 left it, and after, since the open stage stays."""
        r = self.client.prim_properties(self.OPENED_CUBE)
        self.assertEqual(r["status"], "success", "test_31's cube isn't on the open stage")

    def test_31_open_scene_opens_a_saved_scene_again(self):
        r = self.client.create_prim(self.OPENED_CUBE, "Cube")
        self.assertEqual(r["status"], "success", r)
        before = self.client.sim_state()["result"]
        path = self._saved_copy("IntTestOpen.usda")
        self.assertEqual(self.client.new_scene()["status"], "success")
        self.assertEqual(self.client.prim_properties(self.OPENED_CUBE)["status"], "error")
        self.assertEqual(self.client.sim_control("play")["status"], "success")
        r = self._open(str(path))
        self.assertEqual(r["status"], "success", r)
        result = r["result"]
        self.assertEqual(Path(result["file_path"]), path)
        self.assertEqual(result["replaced"], "an unsaved stage")
        self.assertEqual((result["up_axis"], result["meters_per_unit"]), (before["up_axis"], before["meters_per_unit"]))
        # Stopped before the open, as Kit's File > Open does.
        self.assertTrue(result["stopped"])
        self.assertEqual(self.client.sim_state()["result"]["state"], "stopped")
        self._cube_is_there()
        print(f"  {path.name}: {result['prim_count']} prims, {result['up_axis']} up, the cube back")

    def test_32_open_scene_refuses_a_missing_file_before_kit_closes_the_stage(self):
        # Kit closes the open stage before it reads the file (#79's E7): the path rule refuses first.
        self._cube_is_there()
        missing = Path(tempfile.gettempdir()) / self.MISSING
        r = self._open(str(missing))
        self.assertEqual(r["status"], "error", r)
        self.assertIn(str(missing), r["error"])
        self._cube_is_there()

    def test_33_open_scene_refuses_a_file_usd_cant_open(self):
        self._cube_is_there()
        folder = Path(tempfile.mkdtemp(prefix="ovmcp-open-"))
        self.addCleanup(shutil.rmtree, folder, True)
        notes = folder / "notes.txt"
        notes.write_text("plain text\n", encoding="utf-8")
        r = self._open(str(notes))
        self.assertEqual(r["status"], "error", r)
        self.assertIn("USD can't open", r["error"])
        self._cube_is_there()

    def test_34_open_scene_refuses_a_url_with_no_file(self):
        # A URL isn't looked for on disk: omni.client's stat refuses it.
        self._cube_is_there()
        url = (Path(tempfile.gettempdir()) / self.MISSING).as_uri()
        r = self._open(url)
        self.assertEqual(r["status"], "error", r)
        self.assertIn(f"No file at {url}", r["error"])
        self._cube_is_there()

    def test_35_open_scene_reads_a_relative_path_from_kit_s_folder(self):
        self._cube_is_there()
        r = self.client.execute(f"import os\nresult = os.path.join(os.getcwd(), *{self.MISSING.split('/')!r})")
        self.assertEqual(r["status"], "success", r)
        whole = r["result"]["return_value"]
        r = self._open(self.MISSING)
        self.assertEqual(r["status"], "error", r)
        self.assertIn(f"No USD file at {whole}", r["error"])
        self._cube_is_there()

    def test_36_open_scene_opens_a_scene_of_isaac_sim_s_asset_library(self):
        # Over the network, as the scenarios' robots load; the suite's stage comes back from its own copy after.
        copy = self._saved_copy("IntTestBack.usda")
        self.addCleanup(self._reopen, copy)
        r = self._open("/Isaac/Environments/Simple_Room/simple_room.usd")
        self.assertEqual(r["status"], "success", r)
        result = r["result"]
        self.assertTrue(result["file_path"].endswith("/Isaac/Environments/Simple_Room/simple_room.usd"), result)
        self.assertEqual((result["default_prim"], result["up_axis"], result["meters_per_unit"]), ("/Root", "Z", 1.0))
        self.assertFalse(result["writable"])
        print(f"  {result['file_path']}: {result['prim_count']} prims")

    # ===== Cleanup =====

    def test_99_cleanup(self):
        """Clean up test prims."""
        for path in [
            "/World/IntTestCube",
            "/World/IntTestLight",
            "/World/IntTestClone",
            "/World/IntTestRobot",
            "/World/IntTestPair",
            "/World/IntTestOpen",
            "/World/Looks",
        ]:
            self.client.delete_prim(path)
        print("  Cleanup done")


# Opens the USD file PATH as the open stage: whether it opened, and Kit's error if not.
_OPEN_STAGE = """
import omni.usd
result = list(await omni.usd.get_context().open_stage_async(PATH))
"""

# The open stage as Kit holds it: its root layer's file, which of PRIMS it has, and whether it has unsaved edits.
_OPEN_STAGE_STATE = """
import omni.usd
stage = omni.usd.get_context().get_stage()
root = stage.GetRootLayer()
result = {"file": root.realPath, "prims": [p for p in PRIMS if stage.GetPrimAtPath(p)], "dirty": root.dirty}
"""

# Holds PATH's layer in Kit, as a stage other than the open one would, and gives its root prims; with EDIT, first gives
# it an edit it doesn't save. _RELEASE_LAYER lets it go.
_HOLD_LAYER = """
import omni.usd
from pxr import Sdf
layer = Sdf.Layer.FindOrOpen(PATH)
omni.usd._ovmcp_test_held = layer
if EDIT:
    Sdf.CreatePrimInLayer(layer, "/IntTestHeldEdit")
result = [str(prim.path) for prim in layer.rootPrims]
"""

_RELEASE_LAYER = """
import omni.usd
omni.usd.__dict__.pop("_ovmcp_test_held", None)
result = "released"
"""

# What Kit's session layer makes of the open stage, with SUN bound before it: the light rig's lights, SUN's visibility,
# and whether the session layer holds an opinion on it, as a light mode such as Default authors them (#118).
_SESSION_STATE = """
import omni.usd
from pxr import UsdGeom
stage = omni.usd.get_context().get_stage()
result = {
    "rig": bool(stage.GetPrimAtPath("/OmniKit_Viewport_LightRig/Lights/DomeLight")),
    "sun": str(UsdGeom.Imageable(stage.GetPrimAtPath(SUN)).ComputeVisibility()),
    "sun_in_session": bool(stage.GetSessionLayer().GetAttributeAtPath(SUN + ".visibility")),
}
"""


class TestFlattenAndExportKeepTheOpenStage(unittest.TestCase):
    """flatten_usd and export_prim_as_file against the open stage's own file (#81): both cleared the layer Kit held
    for their paths, so a flatten of the open stage's file emptied the open scene. And against Kit's session layer,
    which both wrote into their files (#118). Each test opens a stage of its own, a copy of the one before saved to a
    file: the class runs after TestIsaacSimIntegration, and its last copy stays open, so later tests find the stage
    much as it was."""

    CUBE = "/World/IntTestFlatCube"
    UNSAVED = "/World/IntTestUnsaved"

    @classmethod
    def setUpClass(cls):
        host, port = live_bridge()
        cls.client = BridgeClient(host=host, port=port, timeout=60.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def _run(self, code: str, **names: Any) -> Any:
        script = "".join(f"{name} = {value!r}\n" for name, value in names.items()) + code
        result = self.client.execute(script)
        self.assertEqual(result["status"], "success", result.get("error"))
        return result["result"]["return_value"]

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="ovmcp-flatten-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        # The stage as it was, with a cube, saved to a file and opened from it: the open stage's own file. Then an
        # edit that isn't saved.
        self.scene = self.folder / "IntTestScene.usda"
        self.assertEqual(self.client.create_prim(self.CUBE, "Cube")["status"], "success")
        saved = self.client.save_scene(str(self.scene))
        self.client.delete_prim(self.CUBE)
        self.assertEqual(saved["status"], "success", saved.get("error"))
        opened = self._run(_OPEN_STAGE, PATH=str(self.scene))
        self.assertTrue(opened[0], opened)
        self.addCleanup(self.client.delete_prim, self.CUBE)
        self.addCleanup(self.client.delete_prim, self.UNSAVED)
        self.assertEqual(self.client.create_prim(self.UNSAVED, "Xform")["status"], "success")
        self._assert_stage_intact(self.scene.read_bytes())

    def _assert_stage_intact(self, file_bytes: bytes) -> None:
        """The open stage is still the scene's file, with the cube and the unsaved edit, and the file is as it was."""
        state = self._run(_OPEN_STAGE_STATE, PRIMS=[self.CUBE, self.UNSAVED])
        self.assertTrue(Path(state["file"]).samefile(self.scene), state)
        self.assertEqual(state["prims"], [self.CUBE, self.UNSAVED], "the open stage lost its prims")
        self.assertTrue(state["dirty"], "the open stage lost its unsaved edit")
        self.assertEqual(self.scene.read_bytes(), file_bytes, "the open stage's file was written")

    def test_a_flatten_of_the_open_stages_own_file_leaves_the_stage_and_holds_its_edits(self):
        before = self.scene.read_bytes()
        flat = self.folder / "flat.usda"
        result = self.client.flatten_usd(str(flat), str(self.scene))
        self.assertEqual(result["status"], "success", result.get("error"))
        self._assert_stage_intact(before)
        text = flat.read_text(encoding="utf-8")
        self.assertIn("IntTestFlatCube", text)
        self.assertIn("IntTestUnsaved", text, "the flatten left out the open stage's unsaved edit")
        print(f"  Flattened {self.scene.name}: the open stage kept {self.CUBE} and its unsaved {self.UNSAVED}")

    def test_a_flatten_and_an_export_in_mode_default_leave_out_kits_session_layer(self):
        # Mode Default puts Kit's light rig in the session layer and hides the stage's own lights there: a flatten
        # wrote both into its file, lit by the rig with its own lights off, and an export the hiding (#118).
        lamp = "/World/IntTestFlatLamp"
        sun = f"{lamp}/Sun"
        self.addCleanup(self.client.delete_prim, lamp)
        for path, kind in ((lamp, "Xform"), (sun, "DistantLight")):
            self.assertEqual(self.client.create_prim(path, kind)["status"], "success")
        found = self.client.viewport_light("get")["result"]["lighting_mode"]
        self.addCleanup(self.client.viewport_light, "set", mode=found)
        # Through stage, so Kit hides the new light even when it found Default.
        for mode in ("stage", "Default"):
            self.assertEqual(self.client.viewport_light("set", mode=mode)["status"], "success")
        session = self._run(_SESSION_STATE, SUN=sun)
        self.assertEqual(session, {"rig": True, "sun": "invisible", "sun_in_session": True}, "Kit's Default moved")

        before = self.scene.read_bytes()
        flat, exported = self.folder / "flat.usda", self.folder / "lamp.usda"
        for name, result, out, light in (
            ("flatten_usd", self.client.flatten_usd(str(flat)), flat, sun),
            ("export_prim_as_file", self.client.export_prim(lamp, str(exported)), exported, "/IntTestFlatLamp/Sun"),
        ):
            with self.subTest(name):
                self.assertEqual(result["status"], "success", result.get("error"))
                layer = Sdf.Layer.OpenAsAnonymous(str(out))
                text = layer.ExportToString()
                self.assertNotIn("OmniKit_Viewport_LightRig", text, "the light rig was written")
                # Kit defines its camera in the session layer; a saved scene may hold an over of it and a rel to it,
                # which are the scene's and stay, as with Kit's own Save Flattened As.
                camera = layer.GetPrimAtPath("/OmniverseKit_Persp")
                self.assertFalse(camera and camera.specifier == Sdf.SpecifierDef, "Kit's own camera was written")
                self.assertTrue(layer.GetPrimAtPath(light), "the stage's own light is missing")
                self.assertFalse(layer.GetAttributeAtPath(f"{light}.visibility"), "Kit's hiding of it was written")
        rig = self.client.export_prim("/OmniKit_Viewport_LightRig", str(self.folder / "rig.usda"))
        self.assertEqual(rig["status"], "error", rig)
        self.assertIn("comes from Kit's session layer", rig["error"])
        self.assertEqual(self._run(_SESSION_STATE, SUN=sun), session, "Kit's session layer changed")
        self._assert_stage_intact(before)
        print(
            "  In mode Default, flatten_usd and export_prim_as_file wrote no rig and no hiding; the rig's export erred"
        )

    def test_the_open_stages_own_file_is_refused_as_an_output(self):
        # Kit resolves a path its own way, so the file is named as given, with forward slashes, and, where the file
        # system ignores case as Windows' does, in capitals, which Sdf's registry takes for another file.
        spellings = [str(self.scene), self.scene.as_posix()]
        shouted = self.scene.with_name(self.scene.name.upper())
        if shouted.exists():
            spellings.append(str(shouted))
        before = self.scene.read_bytes()
        for spelling in spellings:
            for name, call in (
                ("export_prim_as_file", lambda s=spelling: self.client.export_prim(self.CUBE, s)),
                ("flatten_usd", lambda s=spelling: self.client.flatten_usd(s)),
                ("flatten_usd of itself", lambda s=spelling: self.client.flatten_usd(s, s)),
            ):
                with self.subTest(f"{name}, {spelling}"):
                    result = call()
                    self.assertEqual(result["status"], "error", result)
                    self.assertIn("the open stage's root layer", result["error"])
                    self.assertIn("save_scene", result["error"])
                    self._assert_stage_intact(before)
        print(
            f"  export_prim_as_file and flatten_usd refused the open stage's own file, {len(spellings)} spellings; "
            "the stage is intact"
        )

    def test_an_input_usd_cant_open_is_an_error(self):
        missing = self.folder / "IntTestMissing.usda"
        result = self.client.flatten_usd(str(self.folder / "flat.usda"), str(missing))
        self.assertEqual(result["status"], "error", result)
        self.assertIn(f"Could not open {missing}", result["error"])
        self.assertNotIn("traceback", result)
        self._assert_stage_intact(self.scene.read_bytes())

    def test_a_file_kit_holds_outside_the_open_stage_is_written_and_read_again(self):
        # While Kit held a layer for the output path, export_prim_as_file cleared it and then failed: Usd's CreateNew
        # refuses a path the registry holds a layer for. Now the file is written and the held layer read again, unless
        # it has unsaved edits. A held .usdc, export_prim_as_file's default, has its file mapped on Windows, which the
        # old Clear() let go of before the write.
        for suffix in (".usda", ".usdc"):
            with self.subTest(suffix):
                self._write_a_held_file(self.folder / f"IntTestHeld{suffix}")
        self._assert_stage_intact(self.scene.read_bytes())
        print("  A .usda and a .usdc Kit held were written twice and read again each time; with unsaved edits, refused")

    def _write_a_held_file(self, out: Path) -> None:
        self.assertEqual(self.client.export_prim(self.CUBE, str(out))["status"], "success")
        self.addCleanup(self._run, _RELEASE_LAYER)
        self.assertEqual(self._run(_HOLD_LAYER, PATH=str(out), EDIT=False), ["/IntTestFlatCube"])

        result = self.client.export_prim(self.UNSAVED, str(out))
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(self._run(_HOLD_LAYER, PATH=str(out), EDIT=False), ["/IntTestUnsaved"])
        result = self.client.flatten_usd(str(out))
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertIn("/World", self._run(_HOLD_LAYER, PATH=str(out), EDIT=False), "the held layer wasn't read again")

        self._run(_HOLD_LAYER, PATH=str(out), EDIT=True)
        written = out.read_bytes()
        for name, call in (
            ("export_prim_as_file", lambda: self.client.export_prim(self.CUBE, str(out))),
            ("flatten_usd", lambda: self.client.flatten_usd(str(out))),
        ):
            result = call()
            self.assertEqual(result["status"], "error", f"{name}: {result}")
            self.assertIn("unsaved edits", result["error"])
            self.assertEqual(out.read_bytes(), written)
        self._run(_RELEASE_LAYER)


# A sublayer's file: a cube under /World, which an over leaves to the stage over it to define.
_PROPS_USDA = """#usda 1.0

over "World"
{
    def Cube "IntTestProp"
    {
    }
}
"""

# A file Kit is to hold outside the open stage, with a root prim the open stage doesn't have.
_HELD_USDA = """#usda 1.0

def Xform "IntTestHeldBefore"
{
}
"""

# Gives the USD file PATH the sublayer SUB, a path relative to it, and saves it.
_ADD_SUBLAYER = """
from pxr import Sdf
layer = Sdf.Layer.FindOrOpen(PATH)
layer.subLayerPaths.append(SUB)
result = layer.Save()
"""

# The open stage as Kit holds it: its root layer's file, its sublayers' files, which of PRIMS it has, and whether its
# root layer has unsaved edits.
_LAYERED_STAGE_STATE = """
import omni.usd
stage = omni.usd.get_context().get_stage()
root = stage.GetRootLayer()
result = {
    "file": root.realPath,
    "sublayers": [layer.realPath for layer in stage.GetLayerStack(includeSessionLayers=False)[1:]],
    "prims": [p for p in PRIMS if stage.GetPrimAtPath(p)],
    "dirty": root.dirty,
}
"""


class TestSaveSceneKeepsTheOpenStagesLayers(unittest.TestCase):
    """save_scene with a file_path against the open stage's other layers (#85): it exported the root layer over any
    file, so a sublayer's file became a copy of the root layer while Kit kept the sublayer as it was, and the stage and
    its files parted. Each test opens a copy of the stage over a sublayer of its own; a copy of the stage as it was is
    opened again after, so later tests find it much as it was."""

    PROP = "/World/IntTestProp"
    UNSAVED = "/World/IntTestSaveUnsaved"

    @classmethod
    def setUpClass(cls):
        host, port = live_bridge()
        # open_scene's calls get the server's own 120 s, as TestIsaacSimIntegration's do.
        cls.client = BridgeClient(host=host, port=port, timeout=120.0)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def _run(self, code: str, **names: Any) -> Any:
        script = "".join(f"{name} = {value!r}\n" for name, value in names.items()) + code
        result = self.client.execute(script)
        self.assertEqual(result["status"], "success", result.get("error"))
        return result["result"]["return_value"]

    def _save(self, path: Path) -> None:
        result = self.client.save_scene(str(path))
        self.assertEqual(result["status"], "success", result.get("error"))

    def _open(self, path: Path) -> None:
        result = self.client.open_scene(str(path))
        self.assertEqual(result["status"], "success", result.get("error"))

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix="ovmcp-save-"))
        self.addCleanup(shutil.rmtree, self.folder, True)
        # The stage as it was, opened again after the test, before the folder goes.
        before = self.folder / "IntTestBefore.usda"
        self._save(before)
        self.addCleanup(self._open, before)
        # A copy over the sublayer IntTestProps.usda, opened from its file, then an edit that isn't saved.
        self.props = self.folder / "IntTestProps.usda"
        self.props.write_text(_PROPS_USDA, encoding="utf-8", newline="\n")
        self.scene = self.folder / "IntTestScene.usda"
        self._save(self.scene)
        self.assertTrue(self._run(_ADD_SUBLAYER, PATH=str(self.scene), SUB=f"./{self.props.name}"))
        self._open(self.scene)
        self.assertEqual(self.client.create_prim(self.UNSAVED, "Xform")["status"], "success")
        self._assert_stage_intact()

    def _assert_stage_intact(self, *, unsaved: bool = True) -> None:
        """The open stage is still the scene's file over the sublayer, with the sublayer's cube and the edit; with
        unsaved, the edit is still unsaved. After a save, whether the root layer is clean is USD's to say: an Export
        to its own file leaves it with unsaved edits in usd-core."""
        state = self._run(_LAYERED_STAGE_STATE, PRIMS=[self.PROP, self.UNSAVED])
        self.assertTrue(Path(state["file"]).samefile(self.scene), state)
        self.assertEqual(len(state["sublayers"]), 1, state)
        self.assertTrue(Path(state["sublayers"][0]).samefile(self.props), state)
        self.assertEqual(state["prims"], [self.PROP, self.UNSAVED], "the open stage lost its prims")
        if unsaved:
            self.assertTrue(state["dirty"], "the open stage lost its unsaved edit")

    def test_a_save_over_the_sublayers_file_is_refused(self):
        # As in TestFlattenAndExportKeepTheOpenStage: as given, with forward slashes, and in capitals where the file
        # system ignores case.
        spellings = [str(self.props), self.props.as_posix()]
        shouted = self.props.with_name(self.props.name.upper())
        if shouted.exists():
            spellings.append(str(shouted))
        props, scene = self.props.read_bytes(), self.scene.read_bytes()
        for spelling in spellings:
            with self.subTest(spelling):
                result = self.client.save_scene(spelling)
                self.assertEqual(result["status"], "error", result)
                self.assertIn("a sublayer of the open stage", result["error"])
                self.assertIn("save_scene without a file_path", result["error"])
                self.assertEqual(self.props.read_bytes(), props, "the sublayer's file was written")
                self.assertEqual(self.scene.read_bytes(), scene, "the open stage's file was written")
                self._assert_stage_intact()
        print(f"  save_scene refused the sublayer's file, {len(spellings)} spellings; the stage and files are intact")

    def test_a_save_over_the_open_stages_own_file_writes_it(self):
        props = self.props.read_bytes()
        for i, spelling in enumerate((str(self.scene), self.scene.as_posix())):
            with self.subTest(spelling):
                saved = f"IntTestSaved{i}"
                self.assertEqual(self.client.create_prim(f"/World/{saved}", "Xform")["status"], "success")
                result = self.client.save_scene(spelling)
                self.assertEqual(result["status"], "success", result.get("error"))
                self.assertEqual(result["result"]["action"], "save_as")
                text = self.scene.read_text(encoding="utf-8")
                self.assertIn(f'"{saved}"', text, "the save didn't write the open stage's file")
                self.assertIn(self.props.name, text, "the saved file lost its sublayer")
                self.assertEqual(self.props.read_bytes(), props, "the sublayer's file was written")
                self._assert_stage_intact(unsaved=False)
        result = self.client.save_scene()
        self.assertEqual(result["status"], "success", result.get("error"))
        self.assertEqual(result["result"]["action"], "save")
        self.assertTrue(Path(result["result"]["file_path"]).samefile(self.scene), result)
        print("  save_scene wrote the open stage's own file by two spellings, and without a file_path")

    def test_a_file_kit_holds_outside_the_open_stage_is_read_again_or_refused_with_unsaved_edits(self):
        out = self.folder / "IntTestHeld.usda"
        out.write_text(_HELD_USDA, encoding="utf-8", newline="\n")
        self.addCleanup(self._run, _RELEASE_LAYER)
        self.assertEqual(self._run(_HOLD_LAYER, PATH=str(out), EDIT=False), ["/IntTestHeldBefore"])

        self._save(out)
        held = self._run(_HOLD_LAYER, PATH=str(out), EDIT=False)
        self.assertIn("/World", held, "the held layer wasn't read again")
        self.assertNotIn("/IntTestHeldBefore", held)

        self._run(_HOLD_LAYER, PATH=str(out), EDIT=True)
        written = out.read_bytes()
        result = self.client.save_scene(str(out))
        self.assertEqual(result["status"], "error", result)
        self.assertIn("unsaved edits", result["error"])
        self.assertEqual(out.read_bytes(), written)
        self._assert_stage_intact()
        print("  A file Kit held was saved over and read again; with an unsaved edit, refused")


# Spheres of a few thousand vertices under ROOT, each vertex pushed in or out by a jitter drawn from the sphere's own
# seed in SEEDS: meshes no cook cache holds, so every one is cooked, and no cache is cleared to get there. Each is a
# rigid body with a convex hull. On main's bridge, 8 static colliders played without a hang and 32 rigid bodies hung
# it (2026-10-29); the count and the body type changed together, so keep both. A PhysicsScene under ROOT when the
# stage has none.
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
    mesh = UsdGeom.Mesh.Define(stage, f"{ROOT}/Sphere_{i:02d}")
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
        mark = self.client.get_logs(count=1)["result"]["total_captured"] - 1  # the newest entry's index
        made = self.client.execute(f"ROOT = {root!r}\nSEEDS = {seeds!r}\n{_COLD_COOK_SCENE}")
        self.assertEqual(made["status"], "success", made.get("error"))
        self.assertGreater(made["result"]["return_value"], 2000)

        started = time.perf_counter()
        try:
            played = self.client.sim_control("play")
        except TimeoutError:
            pytest.exit(
                f"Kit didn't answer sim_control('play') within {self.client.timeout:g} s while physics cooked new "
                "collision meshes: the hang of #5 (https://github.com/serionist/omniverse-mcp/issues/5). Kit is "
                "hung: kill it before running anything else against it.",
                returncode=1,
            )
        played_in = time.perf_counter() - started
        try:
            self.assertEqual(played["status"], "success", played.get("error"))
            # A cache hit starts no cooking task, so each cooking line logged since the scene was made is a sphere
            # cooked from scratch. Kit starts cooking as the prims are authored, and the play follows at once, with it
            # still running. Kit 110 names the prim in the line; Kit 107 (Isaac Sim 5.1) ends it at "Prim " with no
            # path, so there the lines are counted instead. Cooking may outlast the play's answer, so the last lines
            # may take a moment.
            deadline = time.monotonic() + 5.0
            while True:
                cooked = self.client.get_logs(
                    count=2000, channel="omni.physx.cooking", search="ConvexMeshCookingTask", since_index=mark
                )
                self.assertEqual(cooked["status"], "success", cooked.get("error"))
                lines = [e["msg"] for e in cooked["result"]["entries"]]
                if len(lines) >= _SPHERES or time.monotonic() > deadline:
                    break
                time.sleep(0.2)
            if any(root in line for line in lines):
                named = {i for i in range(_SPHERES) for line in lines if f"{root}/Sphere_{i:02d}" in line}
                self.assertEqual(named, set(range(_SPHERES)), "every sphere is named in a ConvexMeshCookingTask line")
            else:
                self.assertGreaterEqual(len(lines), _SPHERES, "a ConvexMeshCookingTask line for each sphere")
            print(f"  play answered in {played_in:.2f} s; {len(lines)} cooking lines for {_SPHERES} spheres")
        finally:
            self.client.sim_control("stop")
            self.client.delete_prim(root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
