"""
Full scenario tests against live Isaac Sim.
Covers phases 1-17, 22-23, and 24-26 from test_project/scenarios.md.

Usage, with Kit running: OMNIVERSE_MCP_SIM=1 uv run pytest -m scenario
"""

import base64
import itertools
import json
import math
import os
import re
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

import pytest

from omniverse_mcp.client import BridgeClient

from .conftest import CAMERA_AIM, VIEWPORT_SEGMENTATION_ON, call_tool, live_bridge
from .physics_checks import PhysicsChecks, _along_up, _turn_degrees

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


# 15.2b's bodies (#105): a floor and two slopes whose physics material has friction and restitution 0, combined by max,
# so each contact takes the body's own values; on each, a body the tool gives one value beside a control the tool
# never touches, with the same material or none. UP is the stage's up axis, 1 or 2; positions are (along X, along the
# up axis, along the third). Far from the scene's other prims, at x = -200.
FRICTION_SCENE = """
import math
from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics, UsdShade
stage = omni.usd.get_context().get_stage()
ROOT = "/World/IntTestFriction"
X = Gf.Vec3d(1, 0, 0)
U = Gf.Vec3d(0, 1, 0) if UP == 1 else Gf.Vec3d(0, 0, 1)
B = Gf.Cross(X, U)


def point(x, h, b):
    return X * x + U * h + B * b


def frame(right, up, at):
    third = Gf.Cross(right, up)
    return Gf.Matrix4d(
        right[0], right[1], right[2], 0, up[0], up[1], up[2], 0, third[0], third[1], third[2], 0, at[0], at[1], at[2], 1
    )


def material(name, friction, restitution, combine=None):
    path = f"{ROOT}/Mats/{name}"
    UsdShade.Material.Define(stage, path)
    prim = stage.GetPrimAtPath(path)
    api = UsdPhysics.MaterialAPI.Apply(prim)
    api.CreateStaticFrictionAttr().Set(friction)
    api.CreateDynamicFrictionAttr().Set(friction)
    api.CreateRestitutionAttr().Set(restitution)
    if combine:
        physx = PhysxSchema.PhysxMaterialAPI.Apply(prim)
        physx.CreateFrictionCombineModeAttr().Set(combine)
        physx.CreateRestitutionCombineModeAttr().Set(combine)
    return UsdShade.Material(prim)


def cube(name, matrix, size, mat=None, velocity=None, body=True):
    c = UsdGeom.Cube.Define(stage, f"{ROOT}/{name}")
    c.CreateSizeAttr().Set(1.0)
    UsdGeom.Xformable(c).AddTransformOp().Set(Gf.Matrix4d().SetScale(Gf.Vec3d(*size)) * matrix)
    prim = c.GetPrim()
    UsdPhysics.CollisionAPI.Apply(prim)
    if body:
        rigid = UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdPhysics.MassAPI.Apply(prim).CreateMassAttr().Set(1.0)
        if velocity:
            rigid.CreateVelocityAttr().Set(Gf.Vec3f(*(X * velocity)))
    if mat:
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(mat, UsdShade.Tokens.weakerThanDescendants, "physics")


ground = material("Ground", 0.0, 0.0, "max")
rubber = material("Rubber", 0.9, 0.0)
bouncy = material("Bouncy", 0.5, 0.8)
cube("Floor", frame(X, U, point(-200, -0.5, 0)), (40, 1, 40), ground, body=False)
box = (0.5, 0.5, 0.5)
for name, b, mat in (("RubberControl", -6, rubber), ("RubberGiven", -3, rubber), ("BareControl", 0, None), ("BareGiven", 3, None)):
    cube(f"Slide{name}", frame(X, U, point(-210, 0.25, b)), box, mat, velocity=4.0)
for name, b in (("Control", 6), ("Given", 9)):
    cube(f"Drop{name}", frame(X, U, point(-195, 1.5, b)), box, bouncy)
for degrees, b in ((24, 30), (29, 40)):
    a = math.radians(degrees)
    down, normal = X * math.cos(a) - U * math.sin(a), U * math.cos(a) + X * math.sin(a)
    centre = point(-200, 0, b)
    cube(f"Slope{degrees}", frame(down, normal, centre), (6, 1, 6), ground, body=False)
    for name, offset in (("Control", -1.0), ("Given", 1.0)):
        at = centre + normal * 0.751 + B * offset
        cube(f"Slope{degrees}{name}", frame(down, normal, at), box)
result = sorted(str(p.GetPath()) for p in stage.GetPrimAtPath(ROOT).GetChildren() if p.HasAPI(UsdPhysics.RigidBodyAPI))
"""

# Plays FRAMES updates from a stop and samples each of PATHS' PhysX poses, then pauses: per body its first and last
# position, and how high it rose above rest (0.25 along UP) after first touching the floor.
FRICTION_RUN = """
import omni.kit.app
import omni.timeline
from omni.physx import get_physx_interface

timeline = omni.timeline.get_timeline_interface()
physx = get_physx_interface()
track = {p: [] for p in PATHS}
timeline.play()
for _ in range(FRAMES):
    await omni.kit.app.get_app().next_update_async()
    for p in PATHS:
        pose = physx.get_rigidbody_transformation(p)
        if pose["ret_val"]:
            track[p].append([float(v) for v in pose["position"]])
timeline.pause()
await omni.kit.app.get_app().next_update_async()
result = {}
for p, points in track.items():
    heights = [q[UP] for q in points]
    touch = next((i for i, h in enumerate(heights) if h <= 0.3), None)
    result[p] = {
        "first": points[0] if points else None,
        "last": points[-1] if points else None,
        "rebound": max(heights[touch:]) - 0.25 if touch is not None else None,
    }
"""

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
# How long each drawing of DRAWN_THEN_CAPTURED lasts: a capture that ends after it may have missed it for that alone.
DRAWN_SECONDS = 1.0
# In one execute_script, `times` times: draw_debug's handler draws the zigzag with the backend in use, then
# capture_viewport captures at once, with no HTTP round trip between them to hide a stale frame (#57). Each draw starts
# from an empty view: the last drawing gone from the book, then 10 frames rendered, so none of its lines is in a frame
# still on its way. First, from such an empty view, one capture says whether the view is black: a black capture is
# taken again after a renderer reset, so then nothing is drawn. The result: whether it was black, and each capture's
# strongly red pixels (as RED_PIXELS counts them) and the seconds from the draw to the capture's end.
DRAWN_THEN_CAPTURED = """
import base64, io, time
import numpy as np
import omni.kit.app
from PIL import Image
from omni.kit.viewport.utility import get_active_viewport, next_viewport_frame_async
from ovmcp.bridge.handlers.debug_draw import _drawings, handle_draw_debug
app = omni.kit.app.get_app()
out = []
while not _drawings.book.idle:
    await app.next_update_async()
await next_viewport_frame_async(get_active_viewport(), 10)
view = await mcp.capture_viewport(width=320, height=240)
if view["status"] != "success":
    raise RuntimeError(view["error"])
black = view["result"]["is_black"]
for _ in range(0 if black else {times}):
    while not _drawings.book.idle:
        await app.next_update_async()
    await next_viewport_frame_async(get_active_viewport(), 10)
    started = time.monotonic()
    drawn = await handle_draw_debug(
        {{"type": "lines", "points": {zigzag!r}, "color": [1, 0, 0], "duration": {duration!r}}}
    )
    if drawn["status"] != "success":
        raise RuntimeError(drawn["error"])
    cap = await mcp.capture_viewport(width=320, height=240)
    took = time.monotonic() - started
    if cap["status"] != "success":
        raise RuntimeError(cap["error"])
    png = base64.b64decode(cap["result"]["image_base64"])
    rgb = np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).astype(np.int32)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    out.append([int(((red - green > 80) & (red - blue > 80)).sum()), took])
result = {{"black": black, "captures": out}}
"""


def _shown(captures: list[tuple[int, float]]) -> str:
    """Captures as `red (seconds)`, for a test's printout."""
    return ", ".join(f"{red} ({took:.2f} s)" for red, took in captures)


# A recording's camera beside the cube's column, 8 units along X, looking at the column 1.5 up, with a wide lens: the
# red cube is in its view from the ground to above 3, where the viewport aimed away (_aim_away) sees none of it (#25).
RECORDING_CAMERA = (
    "from pxr import Gf, UsdGeom\n"
    "stage = omni.usd.get_context().get_stage()\n"
    "up = 2 if UsdGeom.GetStageUpAxis(stage) == 'Z' else 1\n"
    "def at(height, x=0.0):\n"
    "    v = [x, 0.0, 0.0]\n"
    "    v[up] = height\n"
    "    return Gf.Vec3d(*v)\n"
    "camera = UsdGeom.Camera.Define(stage, PATH)\n"
    "camera.ClearXformOpOrder()\n"
    "look = Gf.Matrix4d().SetLookAt(at(1.5, 8.0), at(1.5), at(1.0) - at(0.0))\n"
    "camera.AddTransformOp().Set(look.GetInverse())\n"
    "camera.CreateFocalLengthAttr(18.0)\n"
    "result = str(camera.GetPath())\n"
)
# Each frame file's size, strongly red pixels and their mean image row, read in Kit with its numpy and Pillow; None for
# an empty file, a frame that didn't come.
FRAME_STATS = (
    "import io\n"
    "import numpy as np\n"
    "from PIL import Image\n"
    "def stats(path):\n"
    "    data = open(path, 'rb').read()\n"
    "    if not data:\n"
    "        return None\n"
    "    rgb = np.asarray(Image.open(io.BytesIO(data)).convert('RGB')).astype(np.int32)\n"
    "    red = (rgb[..., 0] - rgb[..., 1] > 80) & (rgb[..., 0] - rgb[..., 2] > 80)\n"
    "    rows = np.nonzero(red)[0]\n"
    "    return [int(rgb.shape[1]), int(rgb.shape[0]), int(red.sum()), float(rows.mean()) if len(rows) else None]\n"
    "result = [stats(p) for p in PATHS]\n"
)
# The viewport as a recording must leave it: its camera, that camera's transform, its resolution; and whether the
# timeline plays every frame, which Replicator's capture would have turned on.
VIEWPORT_STATE = (
    "from omni.kit.viewport.utility import get_active_viewport\n"
    "from pxr import Usd, UsdGeom\n"
    "import omni.timeline\n"
    "vp = get_active_viewport()\n"
    "stage = omni.usd.get_context().get_stage()\n"
    "xf = UsdGeom.Xformable(stage.GetPrimAtPath(str(vp.camera_path))).GetLocalTransformation(Usd.TimeCode.Default())\n"
    "result = [str(vp.camera_path), [round(float(xf[i][j]), 4) for i in range(4) for j in range(4)],\n"
    "          list(vp.resolution),\n"
    "          omni.timeline.get_timeline_interface().get_play_every_frame()]\n"
)
# What of a render product stays on the stage: whether its prim composes, the layers holding a spec of it, and
# whether the root layer's text names it.
RENDER_PRODUCT = (
    "stage = omni.usd.get_context().get_stage()\n"
    "name = PATH.rsplit('/', 1)[-1]\n"
    "layers = [l.identifier for l in stage.GetLayerStack(includeSessionLayers=True) if l.GetPrimAtPath(PATH)]\n"
    "result = [bool(stage.GetPrimAtPath(PATH)), layers, name in stage.GetRootLayer().ExportToString()]\n"
)
# The render products under Kit's textures: one more while a recording runs.
HYDRA_TEXTURES = (
    "prim = omni.usd.get_context().get_stage().GetPrimAtPath('/Render/OmniverseKit/HydraTextures')\n"
    "result = sorted(str(p.GetPath()) for p in prim.GetChildren()) if prim else []\n"
)


def _png_size(path: str) -> tuple[int, int] | None:
    """A PNG file's width and height from its header; None for an empty file."""
    with open(path, "rb") as f:
        head = f.read(24)
    if len(head) < 24:
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


class TestScenarios(PhysicsChecks):
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

    def _drawn_then_captured(self, zigzag: list[list[float]], times: int = 5) -> list[tuple[int, float]]:
        """DRAWN_THEN_CAPTURED's captures, each its red pixels and seconds; the view must not be black without the
        drawing (test_02_01 lights the stage), and each capture must end inside its drawing's DRAWN_SECONDS. Its own
        client: the five drawings come close to the scenario client's 10 s."""
        code = DRAWN_THEN_CAPTURED.format(times=times, zigzag=zigzag, duration=DRAWN_SECONDS)
        host, port = live_bridge()
        client = BridgeClient(host=host, port=port, timeout=60.0)
        try:
            r = client.execute(code)
        finally:
            client.close()
        self.assertEqual(r["status"], "success", r)
        done = r["result"]["return_value"]
        self.assertFalse(done["black"], "the view is black: light the stage first, as test_02_01 does")
        captures = [(red, took) for red, took in done["captures"]]
        for _, took in captures:
            self.assertLess(took, DRAWN_SECONDS, f"a capture ended {took:.2f} s after its draw: Kit was slow")
        return captures

    def _a_capture_at_once_holds_the_drawing(self, zigzag: list[list[float]]) -> None:
        """Every capture made at once after a drawing holds it: through the viewport it missed every time before #57,
        and since #51 a capture renders through a feed of its own, whose first frame comes after the drawing (#51's
        E19). Each feed's render product goes with its capture."""
        textures = self._run_in_kit(HYDRA_TEXTURES)
        captured = self._drawn_then_captured(zigzag)
        print(f"  Captured at once: red pixels and seconds {_shown(captured)}")
        for red, _ in captured:
            self.assertGreater(red, 100, "a capture made just after the drawing doesn't hold it")
        self.assertEqual(self._run_in_kit(HYDRA_TEXTURES), textures, "a capture's render product stayed")

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

    def _run_in_kit(self, code: str, **values: object) -> Any:
        """`code` through execute, with each of `values` bound to its name first."""
        bound = "".join(f"{name} = {value!r}\n" for name, value in values.items())
        r = self.c.execute(bound + code)
        self.assertEqual(r["status"], "success", r)
        return r["result"]["return_value"]

    def _recording_camera(self, path: str = "/World/RecCam") -> str:
        """A camera of the test's own aimed at the red cube's column (RECORDING_CAMERA), deleted after."""
        self.addCleanup(self.c.delete_prim, path)
        return str(self._run_in_kit(RECORDING_CAMERA, PATH=path))

    def _recordings(self, name: str) -> str:
        return os.path.join(os.path.dirname(__file__), "..", "test_project", "results", name)

    def _frames(self, folder: str) -> list[str]:
        return sorted(str(p) for p in Path(folder).iterdir() if p.name.startswith("frame_"))

    def _frame_stats(self, paths: list[str]) -> list[Any]:
        return self._run_in_kit(FRAME_STATS, PATHS=[str(Path(p).resolve()) for p in paths])

    def _metadata(self, stop: dict) -> dict:
        with open(stop["result"]["metadata_file"]) as f:
            return json.load(f)

    def _stop_recording_after(self) -> None:
        """A cleanup that ends a recording the test left running, so the next test can start one."""

        def stop() -> None:
            if self.c.sim_state()["result"].get("recording_active"):
                self.c.recording_stop()

        self.addCleanup(stop)

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
        # A distant light shines along its own -Z: this turns it down onto the scene on a Y-up stage and a Z-up one
        # alike, where [45, 0, 0] shone up on a Y-up one. At the default 50000 the scene washes out white; 3000 is Kit's
        # own sun's (#103).
        r4 = self.c.create_prim("/World/Light", "DistantLight", rotation=[-50, 30, 0])
        self.assertEqual(r4["status"], "success")
        lit = self.c.execute(
            "UsdLux.DistantLight(omni.usd.get_context().get_stage().GetPrimAtPath('/World/Light'))"
            ".CreateIntensityAttr(3000.0)"
        )
        self.assertEqual(lit["status"], "success", lit)

        # Apply materials so objects are visually distinct
        r_red = self.c.set_material("/World/RedCube", color=[1, 0, 0])
        self.assertEqual(r_red["status"], "success")
        r_blue = self.c.set_material("/World/BlueSphere", color=[0.2, 0.4, 1.0])
        self.assertEqual(r_blue["status"], "success")
        r_gray = self.c.set_material("/World/Ground", color=[0.4, 0.4, 0.4], roughness=0.8)
        self.assertEqual(r_gray["status"], "success")

        tree = self.c.scene_tree("/World", 2)
        tree_str = json.dumps(tree["result"])
        cube_material = r_red["result"]["material_path"]
        self.assertTrue(cube_material.startswith("/World/Looks/"), cube_material)
        for name in ["Ground", "RedCube", "BlueSphere", "Light", cube_material]:
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
        # 45° about the up axis at scale 0.5: before #105 the scale left in the matrix read as an 84° turn.
        text = self.c.prim_properties("/World/RedCube", fmt="text")["result"]["text"]
        turned = "rot = 0.9239, 0.0000, 0.3827, 0.0000" if up == 1 else "rot = 0.9239, 0.0000, 0.0000, 0.3827"
        self.assertIn(turned, text)
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
        # The size asked for, not the viewport's (#51).
        head = base64.b64decode(r["result"]["image_base64"][:32])
        self.assertEqual((int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")), (640, 480))
        print(f"  Captured {r['result']['width']}x{r['result']['height']}")
        self._pass()

    def test_03_02_camera_positioning(self):
        """Phase 3.2: Camera Positioning"""
        r = self.c.camera_set([5, 3, 5], [0, 0, 0])
        self.assertEqual(r["status"], "success")
        aim = self._run_in_kit(CAMERA_AIM, TARGET=[0, 0, 0])
        self.assertLess(aim["degrees"], 0.5, aim)  # aimed, not only moved (#82)
        cap = self.c.capture_viewport(640, 480)
        self.assertEqual(cap["status"], "success")
        print("  Camera set + captured")
        self._pass()

    def test_03_03_look_at_prim(self):
        """Phase 3.3: Look At Prim"""
        r = self.c.camera_look_at("/World/RedCube", azimuth=0, elevation=20)
        self.assertEqual(r["status"], "success")
        aim = self._run_in_kit(CAMERA_AIM, TARGET=r["result"]["target"])
        self.assertLess(aim["degrees"], 0.5, aim)  # aimed at the cube's centre, its rotation not wiped (#82)
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
        """Phase 5.2: Step: two app updates of play, then paused"""
        before = self.c.sim_state()["result"]
        r = self.c.sim_control("step")
        self.assertEqual(r["status"], "success")
        self.assertEqual(r["result"]["current_state"], "paused")
        after = self.c.sim_state()["result"]
        moved, frame = after["sim_time"] - before["sim_time"], 1.0 / after["fps"]
        print(f"  The step moved the timeline {moved:.4f} s, {moved / frame:.2f} frames")
        # About two frames: Isaac Sim 6.2 moves 2/60 s; one either side, for when the play starts or ends.
        self.assertAlmostEqual(moved, 2 * frame, delta=frame + 1e-6)
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

        viewport_camera = self._run_in_kit(VIEWPORT_STATE)[0]
        r = self.c.recording_start(self._recordings("recordings"), fps=5, width=320, height=240)
        self.assertEqual(r["status"], "success", r)
        self.__class__._rec_dir = r["result"]["output_dir"]
        self.assertEqual(r["result"]["camera_path"], viewport_camera)

        self.c.sim_control("play")
        time.sleep(2.0)
        self.c.sim_control("stop")
        time.sleep(0.3)

        r = self.c.recording_stop()
        self.assertEqual(r["status"], "success", r)
        self.assertGreater(r["result"]["frame_count"], 0)
        # Every frame a whole PNG of the size asked for, whatever the viewport's own (#25).
        frames = self._frames(r["result"]["output_dir"])
        self.assertEqual(len(frames), r["result"]["frame_count"])
        self.assertEqual({_png_size(p) for p in frames}, {(320, 240)})
        meta = self._metadata(r)
        self.assertEqual((meta["resolution"], meta["camera_path"]), ([320, 240], viewport_camera))
        print(f"  Recorded {r['result']['frame_count']} frames at 320x240 from {viewport_camera}")
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

    def test_06_03_record_from_a_camera(self):
        """Phase 6.3: Frames come from the camera asked for, at its size, and the viewport doesn't move (#25)"""
        self.c.sim_control("stop")
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 1.5))
        camera = self._recording_camera()
        self._aim_away()
        self._stop_recording_after()
        before = self._run_in_kit(VIEWPORT_STATE)

        r = self.c.recording_start(
            self._recordings("recordings_camera"), fps=10, width=160, height=120, camera_path=camera
        )
        self.assertEqual(r["status"], "success", r)
        self.assertEqual((r["result"]["camera_path"], r["result"]["resolution"]), (camera, [160, 120]))
        during = self._run_in_kit(VIEWPORT_STATE)
        time.sleep(1.0)
        stop = self.c.recording_stop()
        self.assertEqual(stop["status"], "success", stop)

        frames = self._frames(stop["result"]["output_dir"])
        stats = [s for s in self._frame_stats(frames) if s is not None]
        self.assertGreater(len(stats), 2, "the recording kept no frames")
        self.assertEqual({(w, h) for w, h, _red, _row in stats}, {(160, 120)})
        self.assertTrue(all(red > 20 for _w, _h, red, _row in stats), f"a frame without the red cube: {stats}")
        self.assertEqual(during, before, "the recording moved the viewport")
        self.assertEqual(self._run_in_kit(VIEWPORT_STATE), before, "the viewport isn't as it was")
        self.assertLess(self._red_pixels(), 20, "the viewport, aimed away, shows the red cube")
        print(f"  {len(stats)} frames at 160x120 from {camera}, red pixels {min(s[2] for s in stats)} at least")
        self._pass()

    def test_06_04_frames_follow_the_simulation(self):
        """Phase 6.4: Frames of a falling cube show it falling, lower in the last than in the first (#25)"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 3))
        camera = self._recording_camera()
        self._stop_recording_after()
        r = self.c.recording_start(
            self._recordings("recordings_fall"), fps=10, width=320, height=240, camera_path=camera
        )
        self.assertEqual(r["status"], "success", r)
        self.c.sim_control("play")
        time.sleep(1.5)
        # Paused, not stopped: a stop puts the cube back at the top, and a frame taken after it would show that.
        self.c.sim_control("pause")
        stop = self.c.recording_stop()
        self.c.sim_control("stop")
        self.assertEqual(stop["status"], "success", stop)

        stats = [s for s in self._frame_stats(self._frames(stop["result"]["output_dir"])) if s and s[3] is not None]
        self.assertGreater(len(stats), 3, f"too few frames with the cube: {stats}")
        first_row, last_row = stats[0][3], stats[-1][3]
        self.assertGreater(
            last_row - first_row, 10, f"the cube didn't fall in the frames: rows {first_row}, {last_row}"
        )
        print(f"  The cube from image row {first_row:.0f} to {last_row:.0f} over {len(stats)} frames")
        self._pass()

    def test_06_05_record_from_a_prim_that_isnt_a_camera(self):
        """Phase 6.5: A prim that isn't a camera, or none, is refused, and leaves nothing (#25)"""
        self._stop_recording_after()  # one that started after all mustn't block the next test
        before = self._run_in_kit(HYDRA_TEXTURES)
        for path, says in (("/World/RedCube", "not a Camera"), ("/World/NoSuchCamera", "No prim at")):
            r = self.c.recording_start(self._recordings("recordings_refused"), camera_path=path)
            self.assertEqual(r["status"], "error", r)
            self.assertIn(says, r["error"])
        self.assertEqual(self._run_in_kit(HYDRA_TEXTURES), before)
        self.assertFalse(self.c.sim_state()["result"]["recording_active"])
        self._pass()

    def test_06_06_recording_makes_and_removes_its_render_product(self):
        """Phase 6.6: The recording's render product exists while it runs, and is gone from every layer after (#25)"""
        camera = self._recording_camera()
        self._stop_recording_after()
        play_every_frame = self._run_in_kit(VIEWPORT_STATE)[3]
        r = self.c.recording_start(self._recordings("recordings_product"), camera_path=camera)
        self.assertEqual(r["status"], "success", r)
        product = r["result"]["render_product"]
        exists, layers, _named = self._run_in_kit(RENDER_PRODUCT, PATH=product)
        self.assertTrue(exists, product)
        self.assertTrue(layers)
        stop = self.c.recording_stop()
        self.assertEqual(stop["status"], "success", stop)
        self.assertNotIn("note", stop["result"])
        # Kit lists the render product in its render settings too, which outlive the prim unless deleted (#25's E22).
        self.assertEqual(self._run_in_kit(RENDER_PRODUCT, PATH=product), [False, [], False])
        self.assertEqual(self._run_in_kit(VIEWPORT_STATE)[3], play_every_frame)
        print(f"  {product} in {len(layers)} layers while recording, in none after")
        self._pass()

    def test_06_07_refuses_a_frame_too_large(self):
        """Phase 6.7: A side over 4096 is refused, and nothing starts (#25)"""
        self._stop_recording_after()  # one that started after all mustn't block the next test
        for width, height in ((4097, 240), (240, 4097)):
            r = self.c.recording_start(self._recordings("recordings_refused"), width=width, height=height)
            self.assertEqual(r["status"], "error", r)
            self.assertIn("4096", r["error"])
        self.assertFalse(self.c.sim_state()["result"]["recording_active"])
        self._pass()

    def test_06_08_each_frame_its_own_number(self):
        """Phase 6.8: Frames faster than a capture keep a number each, none overwritten (#69)"""
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.set_transform("/World/RedCube", position=_along_up(self._up_axis(), 3))
        camera = self._recording_camera()
        self._stop_recording_after()
        r = self.c.recording_start(
            self._recordings("recordings_fast"), fps=30, width=320, height=240, camera_path=camera
        )
        self.assertEqual(r["status"], "success", r)
        self.c.sim_control("play")
        time.sleep(1.0)
        self.c.sim_control("pause")
        stop = self.c.recording_stop()
        self.c.sim_control("stop")
        self.assertEqual(stop["status"], "success", stop)

        meta = self._metadata(stop)
        numbers = [f["frame"] for f in meta["frames"]]
        self.assertGreater(len(numbers), 5)
        self.assertEqual(numbers, list(range(len(numbers))), "a frame number repeats or is missing")
        frames = self._frames(stop["result"]["output_dir"])
        self.assertEqual(len(frames), len(numbers))
        contents = []
        for path in frames:
            with open(path, "rb") as f:
                contents.append(f.read())
        same = sum(1 for a, b in itertools.pairwise(contents) if a and a == b)
        print(f"  {len(numbers)} frames in 1 s at fps=30, {same} the same as the one before")
        self._pass()

    def test_06_09_recording_stops_when_its_camera_goes(self):
        """Phase 6.9: Deleting the camera stops the frames, and stop says why (#25)"""
        camera = self._recording_camera("/World/RecCamGone")
        self._stop_recording_after()
        r = self.c.recording_start(self._recordings("recordings_gone"), fps=10, camera_path=camera)
        self.assertEqual(r["status"], "success", r)
        product = r["result"]["render_product"]
        time.sleep(0.5)
        self.assertEqual(self.c.delete_prim(camera)["status"], "success")
        time.sleep(0.3)
        state = self.c.sim_state()["result"]
        self.assertIn("the camera is gone", state.get("recording_note", ""))
        taken = len(self._frames(r["result"]["output_dir"]))
        time.sleep(0.5)
        self.assertEqual(len(self._frames(r["result"]["output_dir"])), taken, "frames went on after the camera went")
        stop = self.c.recording_stop()
        self.assertEqual(stop["status"], "success", stop)
        self.assertIn("the camera is gone", stop["result"].get("note", ""))
        self.assertEqual(self._run_in_kit(RENDER_PRODUCT, PATH=product), [False, [], False])
        print(f"  {stop['result']['frame_count']} frames, then: {stop['result']['note']}")
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
        # Down from the first frame to the lowest, not the last: each frame's state is read at its tick, while 7.1
        # plays or once it paused, and a cube that landed may bounce, so the last need not be the lowest.
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
        # The prims written, where it counted the whole stage (#82).
        blocks = sum(line.startswith("[") for line in content.splitlines())
        self.assertEqual(r["result"]["prim_count"], blocks)
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
        up = self._up_axis()
        r = self.c.create_robot("g1", "/World/G1", position=_along_up(up, 0.74, x=3))
        self.assertEqual(r["status"], "success", f"Failed: {r.get('error', '')}")
        self.assertIn("prim_path", r["result"])
        # The G1's file is Z-up: on a Y-up stage it lay on its side, tallest along Z (#105).
        dims = self.c.prim_bounds("/World/G1")["result"]["dimensions"]
        self.assertEqual(max(range(3), key=lambda i: dims[i]), up, dims)
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
        # What the tool can follow: it takes no force (#82).
        self.assertIn("stop_recording", r2["error"])
        self.assertNotIn("force", r2["error"])

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
        # Restore full opacity: 0.2.3 wrote only an opacity below 1, so the cube stayed see-through.
        restored = self.c.set_material("/World/RedCube", color=[1, 0, 0], opacity=1.0)
        self.assertEqual(restored["status"], "success", restored)
        shader = self._run_in_kit(
            "from pxr import UsdShade\n"
            "shader = UsdShade.Shader(omni.usd.get_context().get_stage().GetPrimAtPath(PATH))\n"
            "result = [shader.GetInput('enable_opacity').Get(), shader.GetInput('opacity_constant').Get()]",
            PATH=restored["result"]["material_path"] + "/Shader",
        )
        self.assertEqual(shader, [False, 1.0])
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
        # Copy n sits n offsets from the cube, in the parent's space (#82).
        where = self._run_in_kit(
            "from pxr import Usd, UsdGeom\n"
            "stage = omni.usd.get_context().get_stage()\n"
            "def at(path):\n"
            "    t = UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(Usd.TimeCode.Default())\n"
            "    return list(t.ExtractTranslation())\n"
            "result = [at(p) for p in PATHS]",
            PATHS=["/World/RedCube", *clones],
        )
        cube = where[0]
        for n, copy in enumerate(where[1:]):
            for got, want in zip(copy, [cube[0] + 2 * n, cube[1], cube[2]], strict=True):
                self.assertAlmostEqual(got, want, places=4)
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

    def _robot_info(self, out: str) -> str:
        """get_robot_info on the G1 through the MCP server, with the file its answer names, if any, after it."""
        erred, text = call_tool("get_robot_info", {"prim_path": "/World/G1"}, out)
        self.assertFalse(erred, text)
        self.assertTrue(text.startswith("Robot: /World/G1\nArticulation: True\nDOF: "), text)
        wrote = re.search(r"^Wrote .+ -> (.+)$", text, re.MULTILINE)
        if wrote is None:
            return text
        # The answer gives the file relative to the working folder when it is under it, else absolute.
        return f"{text}\n{Path(wrote[1]).read_text(encoding='utf-8')}"

    def test_14_05_get_robot_info_reads_the_joint_states_through_the_server(self):
        """Phase 14.4 through the MCP server (#77): get_robot_info answers the G1's structure with its joint states
        while paused, and with a line saying why there are none once stopped, where get_joint_states failed. 14_04
        leaves the G1 stopped, so this plays and pauses it itself."""
        out = tempfile.mkdtemp(prefix="ovmcp-scenario-")
        self.addCleanup(shutil.rmtree, out, True)
        try:
            r = self.c.sim_control("play")
            self.assertEqual(r["status"], "success", f"Play failed: {r.get('error', '')}")
            time.sleep(0.5)
            self.assertEqual(self.c.sim_control("pause")["status"], "success")

            paused = self._robot_info(out)
        finally:
            self.c.sim_control("stop")

        self.assertRegex(paused, r"(?m)^Joints \(\d+\):$")
        header = re.search(r"(?m)^Joint states \((\d+) DOF, from physics: .+\):$", paused)
        self.assertIsNotNone(header, paused)
        assert header is not None
        dof = int(header[1])
        self.assertGreater(dof, 0)
        states = paused[header.end() :].lstrip("\n").splitlines()[:dof]
        for line in states:
            self.assertRegex(line, r"^  \S+: pos=-?\d+\.\d{4} vel=-?\d+\.\d{4}$")
        self.assertEqual(len(states), dof)

        stopped = self._robot_info(out)
        self.assertRegex(stopped, r"(?m)^Joints \(\d+\):$")
        self.assertRegex(stopped, r"(?m)^Joint states: not read: .*play or step the simulation first")
        self.assertNotIn("pos=", stopped)
        print(f"  Paused: {dof} DOF read through the server; stopped: the structure, and why there are no states")
        self._pass()

    # ===== Phase 15: Physics Properties & Forces =====

    def test_15_01_set_physics_mass(self):
        """Phase 15.1: Set Mass"""
        r = self.c.set_physics_properties("/World/RedCube", mass=5.0)
        self.assertEqual(r["status"], "success")
        self.assertIn("MassAPI", r["result"]["applied"])
        # The tool's answer gives each value from this echo, so a value the extension didn't echo would go unsaid
        # (#104).
        self.assertEqual(r["result"]["mass"], 5.0)
        print(f"  Applied: {r['result']['applied']}")
        self._pass()

    def test_15_02_set_physics_friction(self):
        """Phase 15.2: Set Friction and Restitution"""
        r = self.c.set_physics_properties("/World/RedCube", friction=0.8, restitution=0.3)
        self.assertEqual(r["status"], "success")
        applied = r["result"]["applied"]
        self.assertIn("PhysicsMaterial", applied)
        self.assertEqual((r["result"]["friction"], r["result"]["restitution"]), (0.8, 0.3))
        print(f"  Applied: {applied}")
        self._pass()

    def test_15_02b_restitution_alone_keeps_the_friction(self):
        """#105: given restitution alone, a body's friction went from PhysX's 0.5 to USD's 0, and a material bound
        before lost all it held. Each body the tool gave one value behaves as its untouched control on the same floor:
        no constant is asserted, so a PhysX whose defaults differ from the core's fails it."""
        root = "/World/IntTestFriction"
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.addCleanup(self.c.delete_prim, root)
        self.addCleanup(self.c.sim_control, "stop")
        up = self._up_axis()
        r = self.c.execute(f"UP = {up}\n" + FRICTION_SCENE)
        self.assertEqual(r["status"], "success", r)
        paths = r["result"]["return_value"]
        for name, values in (
            ("SlideRubberGiven", {"restitution": 0.2}),
            ("SlideBareGiven", {"restitution": 0.0}),
            ("DropGiven", {"friction": 0.5}),
            ("Slope24Given", {"restitution": 0.0}),
            ("Slope29Given", {"restitution": 0.0}),
        ):
            done = self.c.set_physics_properties(f"{root}/{name}", **values)
            self.assertEqual(done["status"], "success", done)
            self.addCleanup(self.c.delete_prim, f"/World/PhysicsMaterials/{name}_PhysMat")
        r = self.c.execute(f"UP, PATHS, FRAMES = {up}, {paths!r}, 60\n" + FRICTION_RUN)
        self.assertEqual(r["status"], "success", r)
        seen = {path.rsplit("/", 1)[1]: v for path, v in r["result"]["return_value"].items()}

        def moved(name: str) -> float:
            first, last = seen[name]["first"], seen[name]["last"]
            return math.dist(first, last)

        for pair in ("SlideRubber", "SlideBare"):
            travel = [seen[f"{pair}{k}"]["last"][0] - seen[f"{pair}{k}"]["first"][0] for k in ("Control", "Given")]
            self.assertAlmostEqual(travel[0], travel[1], delta=0.05, msg=f"{pair}: {travel}")
        rebound = [seen[f"Drop{k}"]["rebound"] for k in ("Control", "Given")]
        self.assertGreater(rebound[0], 0.3, rebound)
        self.assertAlmostEqual(rebound[0], rebound[1], delta=0.05, msg=f"rebound: {rebound}")
        for slope in ("Slope24", "Slope29"):
            control, given = moved(f"{slope}Control"), moved(f"{slope}Given")
            self.assertAlmostEqual(control, given, delta=0.05, msg=f"{slope}: {control}, {given}")
        print(f"  slides, rebound {rebound}, slopes as their controls")
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
        # 0.2.0 fell back to nudging physics:velocity on every call, since the PhysX call it made doesn't exist (#25).
        self.assertEqual(r["result"]["method"], "physx")
        self.assertEqual(r["result"]["at"], "centre of mass")
        print(f"  Force applied: method={r['result']['method']} at {r['result']['position']}")

        time.sleep(0.5)
        self.c.sim_control("stop")
        self._pass()

    def test_15_05_apply_force_invalid(self):
        """Phase 15.5: Apply Force to Invalid Prim"""
        r = self.c.apply_force("/World/Nonexistent", force=[1, 0, 0])
        self.assertEqual(r["status"], "error")
        self._pass()

    def test_15_06_impulse_and_force_by_mass(self):
        """Phase 15.6: An impulse changes the speed by impulse / mass; a force acts for one physics step"""
        body = self._force_body("ForceByMassCube")
        dt = self._physics_step()

        self.c.sim_control("play")
        time.sleep(0.3)
        r = self.c.apply_force(body, force=[10, 0, 0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        speed = self._speed_along_x(body)
        print(f"  10 N s on 5 kg: {speed:.3f} units/s along X (2 expected)")
        self.assertAlmostEqual(speed, 2.0, delta=2.0 * 0.25)

        # Stopping puts the body back at rest where it started.
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.sim_control("play")
        time.sleep(0.3)
        r = self.c.apply_force(body, force=[10, 0, 0])
        self.assertEqual(r["status"], "success", r)
        speed = self._speed_along_x(body)
        expected = 10 * dt / 5
        # apply_force's description says a force lasts one physics step; a force PhysX held would keep speeding it up.
        print(f"  10 N on 5 kg: {speed:.4f} units/s along X ({expected:.4f} expected for one step of {dt:.4f} s)")
        self.assertAlmostEqual(speed, expected, delta=expected * 0.5)
        self._pass()

    def test_15_07_force_at_a_point_spins(self):
        """Phase 15.7: A push at the centre of mass moves the body without turning it; one above it turns it"""
        body = self._force_body("ForceSpinCube")
        up = self._up_axis()

        self.c.sim_control("play")
        time.sleep(0.3)
        before = self._physx_pose(body)
        r = self.c.apply_force(body, force=[1, 0, 0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["at"], "centre of mass")
        time.sleep(0.5)
        turned = _turn_degrees(before["rotation"], self._physx_pose(body)["rotation"])
        print(f"  At the centre of mass: turned {turned:.2f} degrees")
        self.assertLess(turned, 2.0)

        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.sim_control("play")
        time.sleep(0.3)
        before = self._physx_pose(body)
        above = list(before["position"])
        above[up] += 0.2
        r = self.c.apply_force(body, force=[1, 0, 0], position=above, impulse=True)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["at"], "given")
        time.sleep(0.5)
        turned = _turn_degrees(before["rotation"], self._physx_pose(body)["rotation"])
        print(f"  0.2 above the centre: turned {turned:.2f} degrees")
        self.assertGreater(turned, 5.0)
        self._pass()

    def test_15_08_centre_of_mass_off_origin(self):
        """Phase 15.8: Without a position, the push is at the centre of mass PhysX holds, not at the body's origin"""
        up = self._up_axis()
        side = 3 - up  # the axis neither X nor up: the centre of mass sits off the origin along it
        offset = [0.0, 0.0, 0.0]
        offset[side] = 0.5  # in the cube's own units, so 0.15 once its 0.3 scale applies
        body = self._force_body("ForceOffCentreCube", centre_of_mass=offset)

        self.c.sim_control("play")
        time.sleep(0.3)
        before = self._physx_pose(body)
        r = self.c.apply_force(body, force=[2, 0, 0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["at"], "centre of mass")
        off = r["result"]["position"][side] - before["position"][side]
        print(f"  The point pushed at is {off:.3f} off the origin along {'XYZ'[side]} (0.15 authored)")
        self.assertAlmostEqual(off, 0.15, delta=0.02)
        time.sleep(0.5)
        turned = _turn_degrees(before["rotation"], self._physx_pose(body)["rotation"])
        print(f"  At the centre of mass: turned {turned:.2f} degrees")
        self.assertLess(turned, 2.0)

        self.c.sim_control("stop")
        time.sleep(0.3)
        self.c.sim_control("play")
        time.sleep(0.3)
        before = self._physx_pose(body)
        r = self.c.apply_force(body, force=[2, 0, 0], position=before["position"], impulse=True)
        self.assertEqual(r["status"], "success", r)
        time.sleep(0.5)
        turned = _turn_degrees(before["rotation"], self._physx_pose(body)["rotation"])
        print(f"  At the origin: turned {turned:.2f} degrees")
        self.assertGreater(turned, 5.0)
        self._pass()

    def test_15_09_apply_force_while_stopped(self):
        """Phase 15.9: Stopped, PhysX holds no bodies, so a push is refused"""
        body = self._force_body("ForceStoppedCube")
        r = self.c.apply_force(body, force=[1, 0, 0])
        self.assertEqual(r["status"], "error", r)
        self.assertIn("stopped", r["error"])
        self._pass()

    def test_15_10_apply_force_to_a_kinematic_body(self):
        """Phase 15.10: A kinematic body takes a force and doesn't move, so a push is refused"""
        body = self._force_body("ForceKinematicCube", kinematic=True)
        self.c.sim_control("play")
        time.sleep(0.3)
        r = self.c.apply_force(body, force=[1, 0, 0])
        self.assertEqual(r["status"], "error", r)
        self.assertIn("kinematic", r["error"])
        self._pass()

    def test_15_11_apply_force_to_a_robot_link(self):
        """Phase 15.11: A push on the G1's pelvis moves the robot by the push: its speed along X changes by the
        impulse over its mass (#58)"""
        links = self._rigid_bodies_under("/World/G1")
        pelvis = next((p for p in links if p.endswith("/pelvis")), "")
        self.assertTrue(pelvis, "No pelvis under /World/G1: test_10_01 loads the G1")
        up = self._up_axis()
        lift = 20.0
        self.c.sim_control("stop")
        time.sleep(0.3)
        # In the air nothing but the push moves the robot along X, its joints included, until it lands. The cleanups
        # run last first: stop, then the G1 back where test_10_01 put it.
        self.addCleanup(self.c.set_transform, "/World/G1", position=_along_up(up, 0.74, x=3))
        self.addCleanup(self.c.sim_control, "stop")
        r = self.c.set_transform("/World/G1", position=_along_up(up, 0.74 + lift, x=3))
        self.assertEqual(r["status"], "success", r)
        self._start_physics()

        before = self._speed_along_x_in_kit(links, 12)
        r = self.c.apply_force(pelvis, force=[100, 0, 0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        self.assertEqual(r["result"]["at"], "centre of mass")
        after = self._speed_along_x_in_kit(links, 12)

        # #59 read drift against a threshold, and refused a push PhysX made: this compares the change with the push.
        change, expected = after["speed"] - before["speed"], 100 / after["mass"]
        print(f"  100 N s on the pelvis of {after['mass']:.2f} kg: {change:.4f} units/s along X ({expected:.4f})")
        self.assertAlmostEqual(change, expected, delta=expected * 0.02)
        self.assertLess(after["time"], math.sqrt(2 * lift / 9.81), "the G1 landed before the speed was measured")
        self._pass()

    def test_15_12_apply_force_to_a_disabled_body(self):
        """Phase 15.12: PhysX holds a disabled rigid body as a static one, which no force moves, so a push is
        refused"""
        body = self._force_body("ForceDisabledCube", enabled=False)
        self.c.sim_control("play")
        time.sleep(0.3)
        r = self.c.apply_force(body, force=[1, 0, 0])
        self.assertEqual(r["status"], "error", r)
        self.assertIn("physics:rigidBodyEnabled is false", r["error"])
        self._pass()

    def test_15_14_apply_force_to_a_link_of_a_free_articulation(self):
        """Phase 15.14: A push on a link that isn't the root moves its articulation exactly as far as the push"""
        first, second = self._force_pair("ForcePair")
        self._start_physics()
        before = self._speed_along_x_in_kit([first, second], 12)
        r = self.c.apply_force(second, force=[10, 0, 0], impulse=True)
        self.assertEqual(r["status"], "success", r)
        after = self._speed_along_x_in_kit([first, second], 12)
        change, expected = after["speed"] - before["speed"], 10 / after["mass"]
        print(f"  10 N s on one cube of {after['mass']:.1f} kg: {change:.4f} units/s along X ({expected:.4f})")
        self.assertAlmostEqual(change, expected, delta=expected * 0.02)
        self._pass()

    def test_15_15_apply_force_to_a_body_fixed_to_the_world(self):
        """Phase 15.15: A body a fixed joint holds to the world is refused, a robot's base or a lone cube; the link its
        joint lets turn is pushed"""
        up = self._up_axis()
        cube = self._force_body("ForceBoltedCube")
        r = self.c.execute(
            "stage = omni.usd.get_context().get_stage()\n"
            f"bolt = UsdPhysics.FixedJoint.Define(stage, {cube + '/Bolt'!r})\n"
            f"bolt.CreateBody1Rel().SetTargets([Sdf.Path({cube!r})])\n"
            # The world's end sits where _force_body put the cube, so the joint holds it there.
            f"bolt.CreateLocalPos0Attr(Gf.Vec3f(*{_along_up(up, 5, x=-30)!r}))\n"
            "result = 'ok'"
        )
        self.assertEqual(r["status"], "success", r)
        first, second = self._force_pair("ForcePairFixed", fixed=True)
        root = first.rsplit("/", 1)[0]
        self._start_physics()

        r = self.c.apply_force(cube, force=[10, 0, 0], impulse=True)
        self.assertEqual(r["status"], "error", r)
        self.assertEqual(r["error"], f"{cube} is held to the world by a fixed joint: no force moves it")
        r = self.c.apply_force(first, force=[10, 0, 0], impulse=True)
        self.assertEqual(r["status"], "error", r)
        held = f"{first} is held to the world by a fixed joint, as the base of the articulation at {root}"
        self.assertIn(held, r["error"])

        before = {p: self._physx_pose(p)["position"] for p in (first, second)}
        sideways = [0.0, 0.0, 0.0]
        sideways[3 - up] = 1.0  # neither X nor up: about the hinge
        r = self.c.apply_force(second, force=sideways, impulse=True)
        self.assertEqual(r["status"], "success", r)
        self._run_frames(30)
        moved = {p: math.dist(before[p], self._physx_pose(p)["position"]) for p in (first, second)}
        print(f"  In 30 steps the fixed base moved {moved[first]:.2e}, the link it holds {moved[second]:.3f}")
        self.assertLess(moved[first], 1e-4)
        self.assertGreater(moved[second], 0.01)
        self._pass()

    def test_15_16_apply_force_to_a_franka(self):
        """Phase 15.16: Isaac Sim's own Franka: its base, which a fixed joint holds to the world, is refused; its hand
        is pushed"""
        path = "/World/ForceFranka"
        self.c.sim_control("stop")
        time.sleep(0.3)
        self.addCleanup(self.c.delete_prim, path)
        self.addCleanup(self.c.sim_control, "stop")
        up = self._up_axis()
        r = self.c.create_robot("franka", path, position=_along_up(up, 0, x=-50))
        self.assertEqual(r["status"], "success", r)
        # On a Y-up stage it is turned upright (#105): tallest along the up axis, and its world-anchored root joint
        # doesn't pull the base back to the file's orientation once physics runs.
        dims = self.c.prim_bounds(path)["result"]["dimensions"]
        self.assertEqual(max(range(3), key=lambda i: dims[i]), up, dims)
        self._start_physics()
        base, hand = f"{path}/panda_link0", f"{path}/panda_hand"
        before = self._physx_pose(base)["rotation"]
        self._run_frames(30)
        self.assertLess(_turn_degrees(before, self._physx_pose(base)["rotation"]), 1.0)
        r = self.c.apply_force(base, force=[100, 0, 0], impulse=True)
        self.assertEqual(r["status"], "error", r)
        held = f"{base} is held to the world by a fixed joint, as the base of the articulation at {path}"
        self.assertIn(held, r["error"])
        r = self.c.apply_force(hand, force=[0, 0, 5], impulse=True)
        self.assertEqual(r["status"], "success", r)
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
        """Phase 16.8: A drawing shows in a capture, however soon after it is made"""
        self._lines_go_after_the_test()
        zigzag = self._aim_away()
        before = self._red_pixels()
        r = self.c.draw_debug("lines", points=zigzag, color=[1, 0, 0], duration=5.0)
        self.assertEqual(r["status"], "success", r)
        drawn = self._red_pixels()
        print(f"  Strongly red pixels: {before} before the zigzag, {drawn} with it")
        self.assertLess(before, 20, "the view aimed away from the red cube holds red already")
        self.assertGreater(drawn, 100, "the zigzag isn't in the capture")
        self._a_capture_at_once_holds_the_drawing(zigzag)
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
        # The fallback draws a frame later than isaacsim.util.debug_draw, so it missed a capture first (#57).
        self._a_capture_at_once_holds_the_drawing(zigzag)
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
        """Phase 17.4: Segmentation on the new stage. omni.syntheticdata drops its graphs on every stage open; each
        capture turns segmentation on for its own feed and waits for its first data (#27, #51), and nothing turns the
        viewport's own sensor on again (#76): the suite's first segmentation on a new stage, and on a cold start the
        one whose timing Kit's log records."""
        off = self.c.execute(VIEWPORT_SEGMENTATION_ON)
        self.assertEqual(off["status"], "success", off)
        self.assertFalse(off["result"]["return_value"], "the viewport's own segmentation is on on the new stage")

        cube = self.SEGMENTATION_TARGET
        self.addCleanup(self.c.delete_prim, cube)
        # A Cube is 2 across, so a scale of 0.25 makes it 0.5: the bridge takes no size.
        r = self.c.create_prim(cube, "Cube", position=_along_up(self._up_axis(), 0.5), scale=0.25)
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

    def test_17_05_recording_stops_at_a_new_stage(self):
        """Phase 17.5: A new stage stops a recording's frames, and its render product doesn't follow (#25)"""
        self._stop_recording_after()
        r = self.c.recording_start(self._recordings("recordings_new_stage"), fps=10, width=320, height=240)
        self.assertEqual(r["status"], "success", r)
        product = r["result"]["render_product"]
        time.sleep(0.3)
        self.assertEqual(self.c.new_scene()["status"], "success")
        time.sleep(0.5)
        taken = len(self._frames(r["result"]["output_dir"]))
        time.sleep(0.5)
        self.assertEqual(len(self._frames(r["result"]["output_dir"])), taken, "frames went on on the new stage")
        stop = self.c.recording_stop()
        self.assertEqual(stop["status"], "success", stop)
        self.assertIn("stage", stop["result"].get("note", ""))
        # Kit carries a texture's render product over to a new stage (#25's E13): it must not stay there.
        self.assertEqual(self._run_in_kit(RENDER_PRODUCT, PATH=product), [False, [], False])
        print(f"  {stop['result']['frame_count']} frames, then: {stop['result']['note']}")
        self._pass()

    SEGMENTED_CUBE = "/World/SegmentedCaptureCube"

    def _segmented_capture(self) -> dict:
        """A cube in front of the viewport's camera and a capture of it, with its segmentation."""
        cube = self.SEGMENTED_CUBE
        if self.c.prim_bounds(cube).get("status") != "success":
            r = self.c.create_prim(cube, "Cube", position=_along_up(self._up_axis(), 0.5), size=0.5)
            self.assertEqual(r["status"], "success", r)
        self.assertEqual(self.c.camera_look_at(cube)["status"], "success")
        r = self.c.capture_viewport(320, 240)
        self.assertEqual(r["status"], "success", r)
        self.assertTrue(r["result"]["segmentation_base64"], r["result"].get("segmentation_error"))
        self.assertIn(cube, r["result"]["segmentation_legend"])
        return r

    def test_17_06_segmentation_after_captures_and_a_new_stage(self):
        """Phase 17.6: Captures with segmentation, then a new stage, then another: each capture's segmentation graphs
        went with it, so omni.syntheticdata's reset at the new stage trips on none, and the next capture has its
        segmentation (#51's E16)."""
        self.addCleanup(self.c.delete_prim, self.SEGMENTED_CUBE)
        entries = self.c.get_logs(count=1)["result"]["entries"]
        since = entries[-1]["index"] if entries else -1
        self._segmented_capture()
        self._segmented_capture()
        self.assertEqual(self.c.new_scene()["status"], "success")
        time.sleep(0.5)
        self._segmented_capture()
        time.sleep(2.0)
        logged = self.c.get_logs(count=50, since_index=since, search="Py_Graph")["result"]["entries"]
        self.assertEqual(logged, [], "omni.syntheticdata tripped on a capture's graph")
        print("  2 captures, a new stage, a third: segmentation each time, nothing in Kit's log")
        self._pass()

    def _open_scene(self, file_path: str) -> dict:
        """open_scene through a client with the server's 120 s: the scenario client's 10 s is short for an open."""
        host, port = live_bridge()
        client = BridgeClient(host=host, port=port, timeout=120.0)
        try:
            return client.open_scene(file_path)
        finally:
            client.close()

    def test_17_07_an_opened_file_stops_a_recording_and_drops_the_drawings(self):
        """Phase 17.7: open_scene stops a recording's frames and drops the drawings, as a new stage does, and the
        opened stage captures with its segmentation (#79's E11). The stage saved first is the one opened, so the
        phases after find its content; it stays tied to the copy, which the cleanup deletes."""
        self._stop_recording_after()
        self.addCleanup(self.c.delete_prim, self.SEGMENTED_CUBE)
        folder = Path(tempfile.mkdtemp(prefix="ovmcp-open-"))
        self.addCleanup(shutil.rmtree, folder, True)
        scene = folder / "Phase17_7.usda"
        self.assertEqual(self.c.save_scene(str(scene))["status"], "success")
        start = self._lines_go_after_the_test()
        r = self.c.recording_start(self._recordings("recordings_opened_file"), fps=10, width=320, height=240)
        self.assertEqual(r["status"], "success", r)
        product = r["result"]["render_product"]
        drawn = self.c.draw_debug("line", start=[0, 0, 0], end=[1, 0, 0], duration=30.0)
        self.assertEqual(drawn["status"], "success", drawn)
        time.sleep(0.3)
        opened = self._open_scene(str(scene))
        self.assertEqual(opened["status"], "success", opened)
        time.sleep(0.5)
        taken = len(self._frames(r["result"]["output_dir"]))
        time.sleep(0.5)
        self.assertEqual(len(self._frames(r["result"]["output_dir"])), taken, "frames went on on the opened stage")
        stop = self.c.recording_stop()
        self.assertEqual(stop["status"], "success", stop)
        self.assertIn("stage", stop["result"].get("note", ""))
        self.assertEqual(self._run_in_kit(RENDER_PRODUCT, PATH=product), [False, [], False])
        # The 30 s line went with its stage.
        self._wait_for_line_count(start, timeout=5.0)
        self._segmented_capture()
        print(f"  {stop['result']['frame_count']} frames, then: {stop['result']['note']}; the line gone")
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

    def test_24_05_get_logs_by_count(self):
        """Phase 24.5: Get Logs by Count: the newest entries, oldest first"""
        marker = f"log_count_marker {time.time_ns()}"
        r = self.c.execute(f"carb.log_warn('{marker}')")
        self.assertEqual(r["status"], "success", r)
        five = self.c.get_logs(count=5)
        self.assertEqual(five["status"], "success", five)
        entries = five["result"]["entries"]
        self.assertEqual((len(entries), five["result"]["count"]), (5, 5))
        # The newest come last: the marker is the last of the five, or near the end when Kit logged after it.
        self.assertIn(marker, [e["msg"] for e in entries])
        one = self.c.get_logs(count=1)
        self.assertEqual(one["status"], "success", one)
        self.assertEqual((len(one["result"]["entries"]), one["result"]["count"]), (1, 1))
        print(f"  5 entries, the marker at {[e['msg'] for e in entries].index(marker) + 1}; then 1")
        self._pass()

    def test_24_06_get_logs_after_error(self):
        """Phase 24.6: Get Logs After Error: a line written to Kit's log is found; a script's exception is in the
        answer, not the log"""
        marker = f"{time.time_ns()}"
        r = self.c.execute(f"carb.log_error('log_test_error {marker}')\nraise RuntimeError('log_test_raise {marker}')")
        self.assertEqual(r["status"], "error", r)
        self.assertIn(f"log_test_raise {marker}", r["error"])
        self.assertIn("RuntimeError", r["traceback"])

        logged = self.c.get_logs(count=10, search=f"log_test_error {marker}")
        self.assertEqual(logged["status"], "success", logged)
        self.assertEqual([e["level"] for e in logged["result"]["entries"]], ["error"])
        # The bridge answers a script's exception rather than logging it, so the answer is where an agent reads it.
        raised = self.c.get_logs(count=10, search=f"log_test_raise {marker}")
        self.assertEqual(raised["status"], "success", raised)
        self.assertEqual(raised["result"]["entries"], [])
        print("  The logged error found at level error; the raised one only in the answer")
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
        self.assertEqual(lighting_mode, "off")
        # Kit's grid keeps the image from being all black: the warning is the lighting's, through the server (#105).
        erred, text = call_tool("capture_viewport", {"width": 160, "height": 120}, tempfile.mkdtemp(prefix="ovmcp-"))
        self.assertFalse(erred, text)
        self.assertIn("Lighting mode is 'off'", text)
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

        if self._up_axis() == 1:
            # Scenario 26.2's TestCube, 2 m at (3, 0.5, 0): beside this view on its Y-up stage, it had a box at the
            # frame's corner (#105). test_integration's test_12i checks either axis.
            self.c.create_prim("/World/SettleSide", "Cube", position=[3, 0.5, 0], scale=[1, 1, 1])
            self.addCleanup(self.c.delete_prim, "/World/SettleSide")
        r = self.c.camera_look_at("/World/SettleTest", azimuth=45, elevation=30)
        self.assertEqual(r["status"], "success")
        # Immediately capture
        cap = self.c.capture_viewport(640, 480)
        self.assertEqual(cap["status"], "success")
        self.assertGreater(len(cap["result"]["image_base64"]), 100)
        boxes = {b["prim_path"] for b in cap["result"]["screen_bboxes"]}
        self.assertNotIn("/World/SettleSide", boxes)

        # Clean up
        self.c.delete_prim("/World/SettleTest")
        self.c.delete_prim("/World/SettleLight2")
        print("  Look-at + immediate capture OK")
        self._pass()


if __name__ == "__main__":
    unittest.main()
