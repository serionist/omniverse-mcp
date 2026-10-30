"""The capture handlers against a fake Kit (#51): capture_viewport and inspect_prim each make one camera feed of the
camera at the size asked for, and let it go whatever happens, after a capture that succeeds, one that raises, and a
restore of isolate that raises.

handlers/camera.py is loaded from its file with Kit's modules, its _utils and its camera feed faked in sys.modules, as
tests/test_recording_handler.py loads its handler. The stage is a real usd-core one, and the Kit-free core is the real
one.
"""

import asyncio
import importlib.util
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pytest
from pxr import Usd, UsdGeom

from ovmcp.core.png import encode_png

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
            _get_active_camera_path=lambda: CAMERA,
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
