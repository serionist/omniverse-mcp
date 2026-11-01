"""The camera handlers against a fake Kit.

capture_viewport and inspect_prim each make one camera feed of the camera at the size asked for, and let it go
whatever happens, after a capture that succeeds, one that raises, and a restore of isolate that raises (#51).
The handlers of /camera/set, /camera/look_at and /camera/inspect aim the camera without Isaac Sim, and after an Isaac
Sim call that left it unaimed (#82).

handlers/camera.py is loaded from its file with Kit's modules, its _utils and its camera feed faked in sys.modules, as
tests/test_recording_handler.py loads its handler. The stage is a real usd-core one, and the Kit-free core is the real
one. No isaacsim is loaded, so the handlers take the USD fallback unless a test fakes Isaac Sim's call.
"""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

from ovmcp.core.png import encode_png
from ovmcp.core.xform import aim, aim_error

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "camera.py"
CAMERA, BOX = "/World/Cam", "/World/Box"


class FakeFeed:
    """A camera feed as the handlers use it."""

    def __init__(self, camera_path: str, width: int, height: int, prefix: str = "ovmcp_recording") -> None:
        self.camera_path, self.width, self.height, self.prefix = camera_path, width, height, prefix
        self.resolution = (width, height)
        self.render_product_path = f"/Render/OmniverseKit/HydraTextures/{prefix}_0"
        self.segmented = False

    async def first_frame(self, seconds: float) -> None:
        pass

    async def wait_frames(self, count: int, budget: Any = None) -> None:
        pass


class FakeKit:
    """What the handlers read of Kit, and what they did: the feeds made and released, and what a capture gives."""

    def __init__(self) -> None:
        self.stage = Usd.Stage.CreateInMemory()
        UsdGeom.Xform.Define(self.stage, "/World")
        UsdGeom.Camera.Define(self.stage, CAMERA)
        UsdGeom.Cube.Define(self.stage, BOX)
        UsdGeom.Sphere.Define(self.stage, "/World/Other")  # something for isolate to hide
        self.active = CAMERA  # the viewport's camera
        self.feeds: list[FakeFeed] = []
        self.released: list[FakeFeed] = []
        self.capture_error: Exception | None = None

    def make_feed(self, *args: Any, **kwargs: Any) -> FakeFeed:
        self.feeds.append(FakeFeed(*args, **kwargs))
        return self.feeds[-1]

    async def capture_feed_png(self, feed: FakeFeed, budget: Any = None) -> bytes:
        if self.capture_error is not None:
            raise self.capture_error
        return encode_png(np.full((feed.height, feed.width, 3), 128, dtype=np.uint8))

    async def release(self, feed: FakeFeed) -> None:
        self.released.append(feed)


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


async def _nothing(*_args: Any, **_kwargs: Any) -> None:
    pass


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def handler(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    settings = SimpleNamespace(get=lambda _key: None, set=lambda *_a: None, set_bool=lambda *_a: None)
    context = SimpleNamespace(get_stage=lambda: kit.stage, get_stage_id=lambda: 1)
    kit_app = _module("omni.kit.app", get_app=lambda: SimpleNamespace(next_update_async=_nothing))
    omni_kit = _module("omni.kit", app=kit_app)
    usd = _module("omni.usd", get_context=lambda: context)
    fakes = {
        "carb": _module(
            "carb",
            log_warn=lambda _m: None,
            log_info=lambda _m: None,
            settings=SimpleNamespace(get_settings=lambda: settings),
        ),
        "omni": _module("omni", kit=omni_kit, usd=usd),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": usd,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            CAMERA_SETTLE_FRAMES=20,
            _get_active_camera_path=lambda: kit.active,
            _get_stage=lambda: kit.stage,
            _next_update=_nothing,
            _reset_renderer=_nothing,
            _settle_viewport=_nothing,
            capture_feed_png=kit.capture_feed_png,
        ),
        "handlers_under_test.camera_feed": _module(
            "handlers_under_test.camera_feed",
            CameraFeed=kit.make_feed,
            enable_segmentation=lambda _feed: "no segmentation in this test",
            release=kit.release,
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.camera", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(handler: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(handler.handle_capture(body))


def _inspect(handler: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(handler.handle_camera_inspect({"prim_path": BOX, "angles": ["front"], **body}))


def test_a_capture_renders_its_camera_at_its_size_in_one_feed_and_lets_it_go(handler, kit):
    r = _capture(handler, width=320, height=240, camera_path=CAMERA)
    assert r["status"] == "success", r
    assert (r["result"]["width"], r["result"]["height"], r["result"]["camera_path"]) == (320, 240, CAMERA)
    (feed,) = kit.feeds
    assert (feed.camera_path, feed.resolution, feed.prefix) == (CAMERA, (320, 240), "ovmcp_capture")
    assert kit.released == [feed]


def test_a_capture_that_raises_still_lets_its_feed_go(handler, kit):
    kit.capture_error = RuntimeError("Kit wrote no whole image")
    r = _capture(handler, width=320, height=240)
    assert r["status"] == "error"
    assert "no whole image" in r["error"]
    assert kit.released == kit.feeds
    assert len(kit.feeds) == 1


def test_a_camera_path_that_isn_t_a_camera_makes_no_feed(handler, kit):
    r = _capture(handler, width=320, height=240, camera_path=BOX)
    assert r["status"] == "error"
    assert "not a Camera" in r["error"]
    assert kit.feeds == []


def test_an_inspection_renders_one_feed_at_its_size_and_lets_it_go(handler, kit):
    r = _inspect(handler, width=320, height=240)
    assert r["status"] == "success", r
    (cap,) = r["result"]["captures"]
    assert "image_base64" in cap
    assert (r["result"]["width"], r["result"]["height"]) == (320, 240)
    (feed,) = kit.feeds
    assert (feed.camera_path, feed.resolution) == (CAMERA, (320, 240))
    assert kit.released == [feed]


def test_an_inspection_whose_capture_raises_still_lets_its_feed_go(handler, kit):
    kit.capture_error = RuntimeError("Kit wrote no whole image")
    r = _inspect(handler, width=320, height=240)
    assert r["status"] == "success", r
    (cap,) = r["result"]["captures"]
    assert "no whole image" in cap["error"]
    assert kit.released == kit.feeds


def test_an_inspection_whose_isolate_restore_raises_still_lets_its_feed_go(handler, kit, monkeypatch):
    class FailingRestore:
        """Hides as isolate does, then fails to show the prims again."""

        def __init__(self, _layer: Any) -> None:
            self.warnings: list[str] = []
            self.paths: list[str] = []

        def hide(self, paths: list[str]) -> None:
            self.paths = list(paths)

        def __len__(self) -> int:
            return len(self.paths)

        def restore(self) -> None:
            raise RuntimeError("the session layer went away")

    monkeypatch.setattr(handler, "Hidden", FailingRestore)
    with pytest.raises(RuntimeError, match="the session layer went away"):
        _inspect(handler, width=320, height=240, isolate=True)
    (feed,) = kit.feeds
    assert kit.released == [feed]  # before ad47884 an error in the restore skipped the release


# ---- whether the stage has lights, for the unlit warning (#105) ----


@pytest.mark.parametrize("lights", [False, True], ids=["no-lights", "a-light"])
def test_a_capture_in_mode_stage_says_whether_the_stage_has_lights(handler, kit, monkeypatch, lights):
    # The image isn't black (the fake's is grey), as Kit 110's grid keeps an unlit one from being.
    monkeypatch.setattr(handler, "_get_current_lighting_mode", lambda: "stage")
    if lights:
        UsdLux.DistantLight.Define(kit.stage, "/World/Sun")

    r = _capture(handler, width=32, height=24)

    assert r["result"]["is_black"] is False
    assert r["result"]["has_scene_lights"] is lights


def test_a_light_inside_an_instance_counts(handler, kit, monkeypatch):
    # A lamp asset referenced as an instance: its light is reached only through the instance's proxies, and a walk
    # without them warned of no lights in a lit scene (review I7).
    monkeypatch.setattr(handler, "_get_current_lighting_mode", lambda: "stage")
    source = kit.stage.CreateClassPrim("/_Lamps/Lamp")
    UsdLux.DistantLight.Define(kit.stage, "/_Lamps/Lamp/Bulb")
    lamp = kit.stage.DefinePrim("/World/Lamp")
    lamp.GetReferences().AddInternalReference(source.GetPath())
    lamp.SetInstanceable(True)

    assert _capture(handler, width=32, height=24)["result"]["has_scene_lights"] is True


def test_an_inspection_in_mode_stage_says_whether_the_stage_has_lights(handler, kit, monkeypatch):
    monkeypatch.setattr(handler, "_get_current_lighting_mode", lambda: "stage")

    r = _inspect(handler, width=32, height=24)

    assert r["result"]["captures"][0]["is_black"] is False
    assert r["result"]["has_scene_lights"] is False


@pytest.mark.parametrize("mode", ["camera", "off", "Default"])
def test_a_lit_capture_in_another_mode_leaves_the_stage_unwalked(handler, kit, monkeypatch, mode):
    # The walk covers the whole stage on Kit's main thread; only stage mode's warning reads it.
    monkeypatch.setattr(handler, "_get_current_lighting_mode", lambda: mode)
    monkeypatch.setattr(handler, "_has_scene_lights", lambda: pytest.fail("the stage was walked"))

    assert "has_scene_lights" not in _capture(handler, width=32, height=24)["result"]
    assert "has_scene_lights" not in _inspect(handler, width=32, height=24)["result"]


# ---- aiming the camera (#82) ----

KIT_CAMERA = "/OmniverseKit_Persp"
EYE_AT, TARGET_AT = [6.0, 3.0, 5.0], [2.0, 0.5, -1.0]
EYE, TARGET = Gf.Vec3d(*EYE_AT), Gf.Vec3d(*TARGET_AT)
UNIT = (1.0, 1.0, 1.0)


def _kit_camera(kit: FakeKit) -> Usd.Prim:
    """Kit's own viewport camera as the live run showed it: defined in the session layer, which holds its ops and its
    centre of interest; the viewport looks through it."""
    stage = kit.stage
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        cam = UsdGeom.Camera.Define(stage, KIT_CAMERA)
        cam.AddTranslateOp().Set(Gf.Vec3d(0, 0, 10))
        cam.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, 0))
        cam.AddScaleOp().Set(Gf.Vec3f(1, 1, 1))
        coi = cam.GetPrim().CreateAttribute("omni:kit:centerOfInterest", Sdf.ValueTypeNames.Vector3d)
        coi.Set(Gf.Vec3d(0, 0, -10))
    kit.active = KIT_CAMERA
    return cam.GetPrim()


def _ops(prim: Usd.Prim) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()]


def _isaac(monkeypatch: pytest.MonkeyPatch, kit: FakeKit, leave: Any) -> list[tuple]:
    """Isaac Sim's set_camera_view, faked: `leave(camera, eye, target)` writes what it leaves. The calls it took."""
    calls: list[tuple] = []

    def set_camera_view(eye: Any, target: Any, camera_prim_path: str) -> None:
        calls.append((list(eye), list(target), camera_prim_path))
        leave(kit.stage.GetPrimAtPath(camera_prim_path), Gf.Vec3d(*eye), Gf.Vec3d(*target))

    for name in ("isaacsim", "isaacsim.core", "isaacsim.core.utils"):
        monkeypatch.setitem(sys.modules, name, _module(name, __path__=[]))
    monkeypatch.setitem(
        sys.modules,
        "isaacsim.core.utils.viewports",
        _module("isaacsim.core.utils.viewports", set_camera_view=set_camera_view),
    )
    return calls


def _in_session(camera: Usd.Prim, **values: Any) -> None:
    with Usd.EditContext(camera.GetStage(), camera.GetStage().GetSessionLayer()):
        for name, value in values.items():
            camera.GetAttribute(name).Set(value)


def _set_camera(handler: Any, position: list[float], target: list[float] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"position": position}
    if target is not None:
        body["target"] = target
    return asyncio.run(handler.handle_camera_set(body))


def test_set_camera_aims_kits_camera_without_isaac_sim_in_the_session_layer(handler, kit):
    # 0.2.3 wrote the root layer, under the session layer's ops: a USD error, and nothing moved.
    camera = _kit_camera(kit)

    r = _set_camera(handler, EYE_AT, TARGET_AT)

    assert r["status"] == "success", r
    assert aim_error(camera, EYE, TARGET, UNIT) is None
    assert _ops(camera) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
    assert not kit.stage.GetRootLayer().GetPrimAtPath(KIT_CAMERA)


def test_set_camera_aims_at_the_world_origin_without_a_target(handler, kit):
    camera = _kit_camera(kit)
    r = _set_camera(handler, [4, 4, 4])
    assert r["status"] == "success", r
    assert aim_error(camera, Gf.Vec3d(4, 4, 4), Gf.Vec3d(0, 0, 0)) is None


def test_look_at_prim_aims_kits_camera_and_keeps_its_ops(handler, kit):
    # 0.2.3 cleared the camera's ops and wrote a translate: the rotation wiped, or a USD error on Kit's own camera.
    camera = _kit_camera(kit)

    r = asyncio.run(handler.handle_camera_look_at({"prim_path": BOX, "azimuth": 45, "elevation": 30}))

    assert r["status"] == "success", r
    eye, target = Gf.Vec3d(*r["result"]["camera_position"]), Gf.Vec3d(*r["result"]["target"])
    assert aim_error(camera, eye, target) is None
    assert _ops(camera) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]


def test_inspect_prim_aims_kits_camera_at_its_angle(handler, kit):
    # 0.2.3's fallback wrote the root layer, so every angle was taken from where the camera stood.
    camera = _kit_camera(kit)

    r = _inspect(handler, width=64, height=48)

    assert r["status"] == "success", r
    (cap,) = r["result"]["captures"]
    assert "image_base64" in cap
    assert aim_error(camera, Gf.Vec3d(*cap["camera_position"]), Gf.Vec3d(*r["result"]["center"])) is None


def test_set_camera_aims_a_scene_camera_under_a_moved_parent(handler, kit):
    # 0.2.3's fallback moved a scene camera without turning it.
    rig = UsdGeom.Xform.Define(kit.stage, "/World/Rig")
    rig.AddTranslateOp().Set(Gf.Vec3d(10, 0, 0))
    rig.AddRotateYOp().Set(90.0)
    camera = UsdGeom.Camera.Define(kit.stage, "/World/Rig/Cam").GetPrim()
    kit.active = "/World/Rig/Cam"

    r = _set_camera(handler, [1, 2, 3], [0, 0, 0])

    assert r["status"] == "success", r
    assert aim_error(camera, Gf.Vec3d(1, 2, 3), Gf.Vec3d(0, 0, 0)) is None


def test_what_isaac_sims_call_leaves_straight_down_is_put_back_and_aimed(handler, kit, monkeypatch):
    # Straight down a Y-up stage's up axis Kit's look-at is singular: the camera at the origin, scaled by FLT_MAX.
    camera = _kit_camera(kit)

    def at_the_origin(cam: Usd.Prim, _eye: Gf.Vec3d, _target: Gf.Vec3d) -> None:
        _in_session(cam, **{"xformOp:translate": Gf.Vec3d(0, 0, 0), "xformOp:scale": Gf.Vec3f(3.4e38, 3.4e38, 3.4e38)})

    calls = _isaac(monkeypatch, kit, at_the_origin)

    r = _set_camera(handler, [2, 8, -1], [2, 0.5, -1])

    assert r["status"] == "success", r
    assert len(calls) == 1
    assert aim_error(camera, Gf.Vec3d(2, 8, -1), Gf.Vec3d(2, 0.5, -1), UNIT) is None
    assert camera.GetAttribute("xformOp:scale").Get() == Gf.Vec3f(1, 1, 1)


def test_an_aim_isaac_sims_call_leaves_scaled_is_caught_by_its_scale(handler, kit, monkeypatch):
    # inspect_prim's top and bottom may leave the direction right and a near-singular scale.
    camera = _kit_camera(kit)

    def aimed_but_scaled(cam: Usd.Prim, eye: Gf.Vec3d, target: Gf.Vec3d) -> None:
        aim(cam, eye, target, cam.GetStage().GetSessionLayer())
        _in_session(cam, **{"xformOp:scale": Gf.Vec3f(1.7e6, 1.7e6, 1.7e6)})

    _isaac(monkeypatch, kit, aimed_but_scaled)

    r = _set_camera(handler, EYE_AT, TARGET_AT)

    assert r["status"] == "success", r
    assert aim_error(camera, EYE, TARGET, UNIT) is None


def test_the_centre_of_interest_is_set_after_isaac_sims_call_too(handler, kit, monkeypatch):
    # Isaac's own branch for a camera straight down a Z-up stage left it at 42.4 for a distance of 7.5.
    camera = _kit_camera(kit)

    def aimed_with_a_stale_centre(cam: Usd.Prim, eye: Gf.Vec3d, target: Gf.Vec3d) -> None:
        aim(cam, eye, target, cam.GetStage().GetSessionLayer())
        _in_session(cam, **{"omni:kit:centerOfInterest": Gf.Vec3d(0, 0, -42.4)})

    calls = _isaac(monkeypatch, kit, aimed_with_a_stale_centre)

    r = _set_camera(handler, EYE_AT, TARGET_AT)

    assert r["status"] == "success", r
    assert len(calls) == 1
    coi = camera.GetAttribute("omni:kit:centerOfInterest").Get()
    assert Gf.IsClose(coi, Gf.Vec3d(0, 0, -(TARGET - EYE).GetLength()), 1e-6)


def test_a_position_on_its_target_is_refused_before_anything_is_written(handler, kit, monkeypatch):
    # Isaac's same-x-and-y branch would turn the camera first.
    camera = _kit_camera(kit)
    calls = _isaac(monkeypatch, kit, lambda *_args: None)

    r = _set_camera(handler, [1, 2, 3], [1, 2, 3])

    assert r["status"] == "error"
    assert "nothing to look at" in r["error"]
    assert calls == []
    assert camera.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(0, 0, 10)


@pytest.mark.parametrize("body", [{"position": [1, 2]}, {"position": [1, 2, 3], "target": "origin"}])
def test_set_camera_refuses_a_point_that_isnt_one(handler, kit, body):
    _kit_camera(kit)
    r = asyncio.run(handler.handle_camera_set(body))
    assert r["status"] == "error"
    assert "must be [x, y, z]" in r["error"]


@pytest.mark.parametrize(("angle", "up_tips_to"), [("top", -1), ("bottom", 1)])
def test_inspect_prim_top_and_bottom_come_over_from_the_front_not_rolled(handler, kit, angle, up_tips_to):
    # The bottom view's up was minus front like the top's, a roll of 180 degrees. Y-up: front is +Z.
    camera = _kit_camera(kit)

    r = _inspect(handler, angles=[angle], width=64, height=48)

    assert r["status"] == "success", r
    (cap,) = r["result"]["captures"]
    assert "image_base64" in cap, cap
    matrix = UsdGeom.Xformable(camera).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    assert Gf.IsClose(matrix.TransformDir(Gf.Vec3d(0, 1, 0)).GetNormalized(), Gf.Vec3d(0, 0, up_tips_to), 1e-6)


def test_a_bare_scene_camera_isaac_sims_call_broke_is_put_back_without_ops_and_aimed(handler, kit, monkeypatch):
    # A camera with no authored order had nothing to restore, so Isaac's FLT_MAX scale stayed.
    camera = kit.stage.GetPrimAtPath(CAMERA)

    def at_the_origin(cam: Usd.Prim, _eye: Gf.Vec3d, _target: Gf.Vec3d) -> None:
        xformable = UsdGeom.Xformable(cam)
        xformable.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
        xformable.AddScaleOp().Set(Gf.Vec3f(3.4e38, 3.4e38, 3.4e38))

    calls = _isaac(monkeypatch, kit, at_the_origin)

    r = _set_camera(handler, [2, 8, -1], [2, 0.5, -1])

    assert r["status"] == "success", r
    assert len(calls) == 1
    assert aim_error(camera, Gf.Vec3d(2, 8, -1), Gf.Vec3d(2, 0.5, -1), UNIT) is None
    assert _ops(camera) == ["xformOp:translate", "xformOp:orient"]
