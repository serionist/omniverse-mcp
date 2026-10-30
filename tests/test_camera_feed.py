"""The camera feed against a fake Kit: the drawable-changed subscription in Kit 110's form and Kit 107's, a frame
handed to the captures waiting for it and to no other, a capture given up taken back, and a dropped feed's render
product deleted from the stage open now or the next one (#25).

handlers/camera_feed.py and handlers/_utils.py are loaded from their files with Kit's modules faked in sys.modules, as
tests/test_debug_draw_handler.py loads its handler; the Kit-free core and pxr (usd-core) are the real ones.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd

from ovmcp.core import capture

from .conftest import EXTENSION_ROOT

HANDLERS = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers"
OPENED, CLOSING = "OPENED", "CLOSING"
PRODUCT_PREFIX = "/Render/OmniverseKit/HydraTextures/"
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class FakeTexture:
    """What the feed reads of a hydra texture."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.updates: list[bool] = []
        self.stream_subscriptions: list[tuple[Any, ...]] = []

    def get_render_product_path(self) -> str:
        return PRODUCT_PREFIX + self.name

    def get_event_key(self) -> dict[str, str]:
        return {"texture": self.name}

    def get_event_stream(self) -> SimpleNamespace:
        def subscribe(event_type: Any, fn: Any, name: str = "") -> tuple[Any, ...]:
            self.stream_subscriptions.append((event_type, fn, name))
            return ("stream subscription", name)

        return SimpleNamespace(create_subscription_to_push_by_type=subscribe)

    def get_aov_info(self, result_handle: int, include_texture: bool = False) -> list[dict[str, Any]]:
        assert include_texture
        return [{"name": "LdrColor", "frame": result_handle}, {"name": "HdrColor", "frame": result_handle}]

    def get_frame_info(self, result_handle: int) -> dict[str, int]:
        return {"frame_number": result_handle}

    def set_updates_enabled(self, enabled: bool) -> None:
        self.updates.append(enabled)


class FakeDelegate:
    """A capture delegate: records the frame it is handed, as FileCapture would write it."""

    def __init__(self, path: str = "") -> None:
        self.path = path
        self.handed: list[tuple[Any, ...]] = []
        self._done = asyncio.Event()

    def capture(self, outputs: dict[str, Any], info: dict[str, Any], texture: Any, result_handle: int) -> None:
        self.handed.append((outputs, info, texture, result_handle))
        if self.path:
            Path(self.path).write_bytes(PNG)
        self._done.set()

    async def wait_for_result(self) -> list[str]:
        await self._done.wait()
        return ["LdrColor"]


class FakeKit:
    """Kit as the feed sees it: the texture factory, the drawable events in either form, the update stream, the
    stage's state and the stage."""

    def __init__(self, events_2: bool = True) -> None:
        self.events_2 = events_2
        self.textures: list[FakeTexture] = []
        self.created: list[tuple[Any, ...]] = []
        self.give_none = False
        self.observers: list[dict[str, Any]] = []
        self.update_subscriptions: list[Any] = []
        self.stage_state = OPENED
        self.stage = Usd.Stage.CreateInMemory()
        self.on_update: Any = None

    def create_hydra_texture(self, name: str, *args: Any, **kwargs: Any) -> FakeTexture | None:
        self.created.append((name, *args, kwargs))
        if self.give_none:
            return None
        self.textures.append(FakeTexture(name))
        return self.textures[-1]

    def observe_event(self, **kwargs: Any) -> tuple[str, str]:
        self.observers.append(kwargs)
        return ("observer", kwargs["observer_name"])

    def subscribe_update(self, fn: Any, name: str = "") -> tuple[str, str]:
        self.update_subscriptions.append((fn, name))
        self.on_update = fn
        return ("update subscription", name)

    def frame(self, result_handle: int) -> None:
        """Kit delivers a frame of the newest texture, in the form this Kit has."""
        if self.events_2:
            self.observers[-1]["on_event"]({"result_handle": result_handle})
        else:
            _type, fn, _name = self.textures[-1].stream_subscriptions[-1]
            fn(SimpleNamespace(payload={"result_handle": result_handle}))


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_kit(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> None:
    async def next_update_async() -> None:
        await asyncio.sleep(0)
        if kit.on_update is not None:
            kit.on_update(None)

    stream = SimpleNamespace(create_subscription_to_pop=kit.subscribe_update)
    app = SimpleNamespace(next_update_async=next_update_async, get_update_event_stream=lambda: stream)
    context = SimpleNamespace(get_stage_state=lambda: kit.stage_state, get_stage=lambda: kit.stage)
    kit_app = _module("omni.kit.app", get_app=lambda: app)
    texture_module = _module("omni.kit.hydra_texture", create_hydra_texture=kit.create_hydra_texture)
    viewport_capture = _module("omni.kit.widget.viewport.capture", FileCapture=FakeDelegate)
    events: dict[str, object] = {"EVENT_TYPE_DRAWABLE_CHANGED": 11183105052706112355}
    if kit.events_2:
        events["GLOBAL_EVENT_DRAWABLE_CHANGED"] = "omni.kit.hydra_texture:drawable_changed"
    hydratexture = _module("omni.hydratexture", **events)
    dispatcher = _module(
        "carb.eventdispatcher", get_eventdispatcher=lambda: SimpleNamespace(observe_event=kit.observe_event)
    )
    usd = _module("omni.usd", get_context=lambda: context, StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING))
    omni_kit = _module("omni.kit", app=kit_app, hydra_texture=texture_module)
    fakes = {
        "carb": _module("carb", log_info=lambda _m: None, log_warn=lambda _m: None, eventdispatcher=dispatcher),
        "carb.eventdispatcher": dispatcher,
        "omni": _module("omni", kit=omni_kit, usd=usd, hydratexture=hydratexture),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.kit.hydra_texture": texture_module,
        "omni.kit.widget": _module("omni.kit.widget"),
        "omni.kit.widget.viewport": _module("omni.kit.widget.viewport"),
        "omni.kit.widget.viewport.capture": viewport_capture,
        "omni.hydratexture": hydratexture,
        "omni.usd": usd,
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture(params=[True, False], ids=["kit110", "kit107"])
def kit(request: pytest.FixtureRequest) -> FakeKit:
    return FakeKit(events_2=request.param)


@pytest.fixture
def feeds(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    _fake_kit(kit, monkeypatch)
    return _load("camera_feed_under_test", HANDLERS / "camera_feed.py")


def test_a_feed_renders_its_camera_at_its_size_in_a_texture_of_its_own(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    feeds.CameraFeed("/World/RecCam", 320, 240)
    (name, *args, options), (other_name, *_rest) = kit.created
    assert name.startswith("ovmcp_recording_")
    assert name != other_name  # two feeds in one second never share a texture
    assert args == [320, 240, "", "/World/RecCam", "rtx"]
    assert options == {"is_async": False}
    assert feed.render_product_path == PRODUCT_PREFIX + name
    assert feeds.CameraFeed("/World/RecCam", 8, 8, prefix="ovmcp_capture").name.startswith("ovmcp_capture_")


def test_the_subscription_takes_the_form_this_kit_has(feeds, kit):
    feeds.CameraFeed("/World/RecCam", 320, 240)
    texture = kit.textures[-1]
    if kit.events_2:
        (observer,) = kit.observers
        assert observer["event_name"] == "omni.kit.hydra_texture:drawable_changed"
        assert observer["filter"] == texture.get_event_key()  # this texture's frames only
        assert texture.stream_subscriptions == []
    else:
        assert kit.observers == []
        ((event_type, _fn, _name),) = texture.stream_subscriptions
        assert event_type == 11183105052706112355


def test_a_frame_is_handed_to_the_captures_waiting_for_it_once_by_output_name(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    first, second = FakeDelegate(), FakeDelegate()
    assert feed.schedule(first) is first
    feed.schedule(second)
    assert feed.waiting
    kit.frame(7)
    assert not feed.waiting
    for delegate in (first, second):
        ((outputs, info, texture, handle),) = delegate.handed
        assert sorted(outputs) == ["HdrColor", "LdrColor"]
        assert outputs["LdrColor"]["frame"] == 7
        assert (info, texture, handle) == ({"frame_number": 7}, kit.textures[-1], 7)
    kit.frame(8)
    assert len(first.handed) == 1  # a capture gets one frame, not every later one
    assert feed.frames == 2


def test_a_capture_taken_back_gets_no_frame(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    kept, withdrawn = FakeDelegate(), FakeDelegate()
    feed.schedule(kept)
    feed.schedule(withdrawn)
    feed.withdraw(withdrawn)
    feed.withdraw(withdrawn)  # twice, or one already handed its frame: nothing happens
    kit.frame(1)
    feed.withdraw(kept)
    assert len(kept.handed) == 1
    assert withdrawn.handed == []


def test_a_kit_that_gives_no_texture_is_an_error(feeds, kit):
    kit.give_none = True
    with pytest.raises(RuntimeError, match="no texture to render /World/RecCam"):
        feeds.CameraFeed("/World/RecCam", 320, 240)


def test_the_first_frame_is_waited_for_and_its_absence_is_no_frame_error(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    with pytest.raises(capture.NoFrameError, match=r"/World/RecCam rendered no frame in 0\.05 s"):
        asyncio.run(feed.first_frame(0.05))

    kit.on_update = lambda _event: kit.frame(1)  # the next update brings a frame
    asyncio.run(feed.first_frame(5.0))
    assert feed.frames == 1


def test_a_dropped_feed_stops_rendering_and_hands_out_nothing_more(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    waiting = FakeDelegate()
    feed.schedule(waiting)
    feed.drop()
    feed.drop()
    assert kit.textures[-1].updates == [False]
    assert not feed.waiting
    if kit.events_2:
        kit.frame(1)  # an event already on its way when the subscription went
    assert waiting.handed == []


def _with_product(kit: FakeKit, path: str) -> None:
    kit.stage.DefinePrim(path, "RenderProduct")


def test_a_discarded_feed_s_render_product_goes_from_the_open_stage_at_once(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    _with_product(kit, feed.render_product_path)
    feeds.discard(feed)
    assert kit.textures[-1].updates == [False]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert kit.update_subscriptions == []


def test_a_render_product_waits_for_an_open_stage_then_goes_from_that_one(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    kit.stage_state = CLOSING
    feeds.discard(feed)
    assert len(kit.update_subscriptions) == 1
    kit.on_update(None)  # still closing: nothing is touched
    # A new stage opens; Kit has carried the render product over to it (#25's E13).
    kit.stage = Usd.Stage.CreateInMemory()
    _with_product(kit, feed.render_product_path)
    kit.stage_state = OPENED
    kit.on_update(None)
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert feeds._leftovers.subscription is None


def test_forget_deletes_nothing_and_stops_looking(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    kit.stage_state = CLOSING
    feeds.discard(feed)
    feeds.forget()
    assert feeds._leftovers.paths == []
    assert feeds._leftovers.subscription is None


@pytest.fixture
def utils(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    _fake_kit(kit, monkeypatch)
    return _load("utils_under_test", HANDLERS / "_utils.py")


def test_a_feed_s_frame_comes_back_as_png_bytes(feeds, utils, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    schedule = feed.schedule

    def schedule_then_render(delegate: Any) -> Any:
        # Kit renders the next frame soon after the capture is asked for.
        asyncio.get_running_loop().call_soon(kit.frame, 3)
        return schedule(delegate)

    feed.schedule = schedule_then_render
    assert asyncio.run(utils.capture_feed_png(feed)) == PNG
    assert not feed.waiting


def test_a_frame_that_never_comes_fails_in_its_time_and_is_taken_back(feeds, utils, kit, monkeypatch):
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.05)
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    with pytest.raises(capture.NoFrameError):
        asyncio.run(utils.capture_feed_png(feed))
    assert not feed.waiting  # a frame arriving now finds no capture to write into a deleted file
