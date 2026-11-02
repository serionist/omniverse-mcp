"""The camera feed against a fake Kit: the drawable-changed subscription in Kit 110's form and Kit 107's, a frame
handed to the captures waiting for it and to no other, a capture given up taken back, and a dropped feed's render
product deleted from the stage open now or the next one (#25). The capture feed kept between calls: its camera and
size set in place, its timer, the stage's closing and Kit's save, and shutdown (#114); lent to a recording at its
size and handed back at the stop (#141).

handlers/camera_feed.py and handlers/_utils.py are loaded from their files with Kit's modules faked in sys.modules, as
tests/test_debug_draw_handler.py loads its handler, camera_feed.py into a fake package beside the real _updates.py; the
Kit-free core and pxr (usd-core) are the real ones.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd, UsdGeom

from ovmcp.core import capture
from ovmcp.core.exposure import SCHEMAS

from .conftest import HANDLERS, FakeUpdates, load_updates

OPENED, CLOSING = "OPENED", "CLOSING"
PRODUCT_PREFIX = "/Render/OmniverseKit/HydraTextures/"
DRAWABLE_CHANGED = "omni.kit.hydra_texture:drawable_changed"
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels" + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class FakeTexture:
    """What the feed reads of a hydra texture, and its camera and size as a kept feed sets them."""

    def __init__(self, name: str, log: list[Any] | None = None) -> None:
        self.name = name
        self.updates: list[bool] = []
        self.stream_subscriptions: list[tuple[Any, ...]] = []
        self._log = log if log is not None else []
        self.refuses_camera = False

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "camera_path" and getattr(self, "refuses_camera", False):
            raise RuntimeError("Kit refused the camera")
        if name in ("camera_path", "width", "height"):
            self._log.append((name, value))
        super().__setattr__(name, value)

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
        self._log.append(("updates", enabled))


class FakeSyntheticDataError(Exception):
    """omni.syntheticdata's own error, which derives from Exception alone."""


class FakeRegistry:
    """omni.syntheticdata's registry of graphs, as a feed's release reads it: graphs by path, and their reset."""

    def __init__(self, kit: "FakeKit") -> None:
        self._kit = kit
        self._nodeGraphs: dict[str, str] = {}

    def _reset_node_graph(self, graph: str) -> None:
        stage = self._kit.stage
        on_session = stage.GetEditTarget().GetLayer() == stage.GetSessionLayer()
        self._kit.log.append(("reset", graph, "session layer" if on_session else "another layer"))


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
    """Kit as the feed sees it: the texture factory, the drawable events in either form, the update event (#122), the
    stage's state and the stage."""

    def __init__(self, events_2: bool = True) -> None:
        self.events_2 = events_2
        self.textures: list[FakeTexture] = []
        self.created: list[tuple[Any, ...]] = []
        self.give_none = False
        self.observers: list[dict[str, Any]] = []
        self.updates = FakeUpdates()
        self.stage_state = OPENED
        self.stage = Usd.Stage.CreateInMemory()
        # What Kit does at the start of each update, before the update event's observers: a test's frame, say, as Kit
        # announces a frame before them (#122's P1).
        self.on_update: Any = None
        # What happened, in order, across the texture, omni.syntheticdata and the app's updates.
        self.log: list[Any] = []
        self.registry: Any = FakeRegistry(self)
        self.sensor_error: Exception | None = None
        self.stage_id = 1

    def create_hydra_texture(self, name: str, *args: Any, **kwargs: Any) -> FakeTexture | None:
        self.created.append((name, *args, kwargs))
        if self.give_none:
            return None
        self.textures.append(FakeTexture(name, self.log))
        return self.textures[-1]

    def enable_sensors(self, view: Any, sensor_types: list[str]) -> None:
        self.log.append(("enable", view.render_product_path, sensor_types))

    def disable_sensors(self, view: Any, sensor_types: list[str]) -> None:
        if self.sensor_error is not None:
            raise self.sensor_error
        self.log.append(("disable", view.render_product_path, sensor_types))

    def observe_event(self, **kwargs: Any) -> Any:
        if kwargs["event_name"] == FakeUpdates.APP["GLOBAL_EVENT_UPDATE"]:
            return self.updates.observe_event(**kwargs)
        self.observers.append(kwargs)
        return ("observer", kwargs["observer_name"])

    def frame(self, result_handle: int) -> None:
        """Kit delivers a frame of the newest texture, in the form this Kit has."""
        if self.events_2:
            drawable = [o for o in self.observers if o["event_name"] == DRAWABLE_CHANGED]
            drawable[-1]["on_event"]({"result_handle": result_handle})
        else:
            _type, fn, _name = self.textures[-1].stream_subscriptions[-1]
            fn(SimpleNamespace(payload={"result_handle": result_handle}))

    def stage_event(self, event: str) -> None:
        """Kit sends a stage event, on Events 2.0 in Kit 107 and Kit 110 alike, to whoever observes it."""
        for observer in list(self.observers):
            if observer["event_name"] == f"stage event {event}":
                observer["on_event"](SimpleNamespace(event_name=observer["event_name"]))


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
        kit.log.append("update")
        if kit.on_update is not None:
            kit.on_update(None)
        kit.updates.update()

    app = SimpleNamespace(next_update_async=next_update_async)
    context = SimpleNamespace(
        get_stage_state=lambda: kit.stage_state,
        get_stage=lambda: kit.stage,
        get_stage_id=lambda: kit.stage_id,
        stage_event_name=lambda event: f"stage event {event}",
    )
    kit_app = _module("omni.kit.app", get_app=lambda: app, **FakeUpdates.APP)
    texture_module = _module("omni.kit.hydra_texture", create_hydra_texture=kit.create_hydra_texture)
    viewport_capture = _module("omni.kit.widget.viewport.capture", FileCapture=FakeDelegate)
    events: dict[str, object] = {"EVENT_TYPE_DRAWABLE_CHANGED": 11183105052706112355}
    if kit.events_2:
        events["GLOBAL_EVENT_DRAWABLE_CHANGED"] = DRAWABLE_CHANGED
    hydratexture = _module("omni.hydratexture", **events)
    dispatcher = _module(
        "carb.eventdispatcher", get_eventdispatcher=lambda: SimpleNamespace(observe_event=kit.observe_event)
    )
    usd = _module(
        "omni.usd",
        get_context=lambda: context,
        StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING),
        StageEventType=SimpleNamespace(CLOSING="closing", SAVING="saving"),
    )
    omni_kit = _module("omni.kit", app=kit_app, hydra_texture=texture_module)
    syntheticdata = _module(
        "omni.syntheticdata",
        sensors=SimpleNamespace(enable_sensors=kit.enable_sensors, disable_sensors=kit.disable_sensors),
        _syntheticdata=SimpleNamespace(SensorType=SimpleNamespace(InstanceSegmentation="InstanceSegmentation")),
        SyntheticData=SimpleNamespace(Get=lambda: kit.registry),
        SyntheticDataException=FakeSyntheticDataError,
    )
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
        "omni.syntheticdata": syntheticdata,
        "omni.usd": usd,
        # The feed's package, holding the real helper it observes Kit's update event through.
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "handlers_under_test._updates", load_updates())


@pytest.fixture(params=[True, False], ids=["kit110", "kit107"])
def kit(request: pytest.FixtureRequest) -> FakeKit:
    return FakeKit(events_2=request.param)


@pytest.fixture
def feeds(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    _fake_kit(kit, monkeypatch)
    return _load("handlers_under_test.camera_feed", HANDLERS / "camera_feed.py")


def test_a_feed_renders_its_camera_at_its_size_in_a_texture_of_its_own(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    feeds.CameraFeed("/World/RecCam", 320, 240)
    (name, *args, options), (other_name, *_rest) = kit.created
    assert name.startswith("ovmcp_feed_")  # whichever call made it: captures and recordings share it (#141)
    assert name != other_name  # two feeds in one second never share a texture
    assert args == [320, 240, "", "/World/RecCam", "rtx"]
    assert options == {"is_async": False}
    assert feed.render_product_path == PRODUCT_PREFIX + name


def test_the_subscription_takes_the_form_this_kit_has(feeds, kit):
    feeds.CameraFeed("/World/RecCam", 320, 240)
    texture = kit.textures[-1]
    if kit.events_2:
        (observer,) = kit.observers
        assert observer["event_name"] == DRAWABLE_CHANGED
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


def _cameras(kit: FakeKit, *paths: str) -> None:
    for path in paths:
        UsdGeom.Camera.Define(kit.stage, path)


def _shielded(kit: FakeKit, path: str) -> bool:
    spec = kit.stage.GetSessionLayer().GetPrimAtPath(path)
    return (
        spec is not None
        and spec.HasInfo("apiSchemas")
        and set(SCHEMAS) <= set(spec.GetInfo("apiSchemas").prependedItems)
    )


def test_a_feed_shields_its_camera_in_the_session_layer_and_lifts_it_when_dropped(feeds, kit):
    # RTX wrote its exposure schemas into the root layer of a scene camera a capture rendered through (#177).
    _cameras(kit, "/World/ShotCam")
    root, session = kit.stage.GetRootLayer().ExportToString(), kit.stage.GetSessionLayer().ExportToString()

    feed = feeds.CameraFeed("/World/ShotCam", 320, 240)

    assert _shielded(kit, "/World/ShotCam")
    assert kit.stage.GetRootLayer().ExportToString() == root
    feed.drop()
    assert kit.stage.GetSessionLayer().ExportToString() == session


def test_a_feed_aimed_elsewhere_shields_the_new_camera_and_lifts_the_old(feeds, kit):
    _cameras(kit, "/World/A", "/World/B")
    session = kit.stage.GetSessionLayer().ExportToString()
    feed = feeds.CameraFeed("/World/A", 320, 240)

    feed.aim("/World/B", 320, 240)

    assert kit.textures[-1].camera_path == "/World/B"
    assert not _shielded(kit, "/World/A")
    assert _shielded(kit, "/World/B")
    feed.drop()
    assert kit.stage.GetSessionLayer().ExportToString() == session


def test_a_camera_kit_refuses_keeps_the_old_shield_and_leaves_none_on_the_new(feeds, kit):
    _cameras(kit, "/World/A", "/World/B")
    feed = feeds.CameraFeed("/World/A", 320, 240)
    kit.textures[-1].refuses_camera = True

    with pytest.raises(RuntimeError, match="refused the camera"):
        feed.aim("/World/B", 320, 240)

    assert _shielded(kit, "/World/A")
    assert not _shielded(kit, "/World/B")


def test_a_feed_made_while_the_stage_isn_t_open_writes_nothing(feeds, kit):
    _cameras(kit, "/World/ShotCam")
    session = kit.stage.GetSessionLayer().ExportToString()
    kit.stage_state = CLOSING

    feed = feeds.CameraFeed("/World/ShotCam", 320, 240)
    feed.drop()

    assert kit.stage.GetSessionLayer().ExportToString() == session


def test_a_shield_on_a_stage_since_replaced_is_left_to_go_with_it(feeds, kit):
    _cameras(kit, "/World/ShotCam")
    feed = feeds.CameraFeed("/World/ShotCam", 320, 240)
    old = kit.stage
    kit.stage = Usd.Stage.CreateInMemory()

    feed.drop()  # writes nothing into the new stage's session layer

    assert kit.stage.GetSessionLayer().GetPrimAtPath("/World/ShotCam") is None
    assert _shielded(kit, "/World/ShotCam") is False
    assert old.GetSessionLayer().GetPrimAtPath("/World/ShotCam") is not None


def test_a_kit_that_gives_no_texture_leaves_no_shield(feeds, kit):
    _cameras(kit, "/World/ShotCam")
    session = kit.stage.GetSessionLayer().ExportToString()
    kit.give_none = True

    with pytest.raises(RuntimeError):
        feeds.CameraFeed("/World/ShotCam", 320, 240)

    assert kit.stage.GetSessionLayer().ExportToString() == session


def _with_product(kit: FakeKit, path: str) -> None:
    kit.stage.DefinePrim(path, "RenderProduct")


def test_a_discarded_feed_s_render_product_goes_from_the_open_stage_at_once(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    _with_product(kit, feed.render_product_path)
    feeds.discard(feed)
    assert kit.textures[-1].updates == [False]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert kit.updates.observers == []


def test_a_render_product_waits_for_an_open_stage_then_goes_from_that_one(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    kit.stage_state = CLOSING
    feeds.discard(feed)
    assert kit.updates.names == ["ovmcp.bridge camera feed leftovers"]
    kit.updates.update()  # still closing: nothing is touched
    # A new stage opens; Kit has carried the render product over to it (#25's E13).
    kit.stage = Usd.Stage.CreateInMemory()
    _with_product(kit, feed.render_product_path)
    kit.stage_state = OPENED
    kit.updates.update()
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert feeds._leftovers.subscription is None
    assert kit.updates.observers == []  # dropped from inside its own call


def test_a_render_product_is_removed_from_a_stage_only_while_it_is_open(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    _with_product(kit, feed.render_product_path)
    kit.stage_state = CLOSING
    assert feed.remove_render_product(kit.stage) is False
    assert kit.stage.GetPrimAtPath(feed.render_product_path)
    kit.stage_state = OPENED
    assert feed.remove_render_product(kit.stage) is True
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_forget_deletes_nothing_and_stops_looking(feeds, kit):
    feed = feeds.CameraFeed("/World/RecCam", 320, 240)
    kit.stage_state = CLOSING
    feeds.discard(feed)
    feeds.forget()
    assert feeds._leftovers.feeds == []
    assert feeds._leftovers.subscription is None
    assert kit.updates.observers == []


def test_a_feed_reads_as_a_viewport_does_to_omni_syntheticdata(feeds, kit):
    feed = feeds.CameraFeed("/World/Cam", 320, 240)
    # What get_view_params, world_to_image and the sensors read of a viewport (#51's A9).
    assert (feed.camera_path, feed.resolution) == ("/World/Cam", (320, 240))
    assert feed.render_product_path == PRODUCT_PREFIX + kit.created[-1][0]
    assert kit.created[-1][0].startswith("ovmcp_feed_")


def test_a_feed_s_frames_are_waited_for_and_their_absence_names_the_camera(feeds, kit, monkeypatch):
    feed = feeds.CameraFeed("/World/Cam", 320, 240)
    kit.on_update = lambda _event: kit.frame(feed.frames + 1)  # a frame on every update
    asyncio.run(feed.wait_frames(3))
    assert feed.frames == 3

    kit.on_update = None
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.05)
    with pytest.raises(capture.NoFrameError, match=r"^The camera /World/Cam rendered no frame in 0\.05 s$"):
        asyncio.run(feed.wait_frames(1))


def test_segmentation_is_turned_on_only_where_its_graphs_can_be_freed(feeds, kit, monkeypatch):
    feed = feeds.CameraFeed("/World/Cam", 320, 240)
    assert feeds.enable_segmentation(feed) is None
    assert feed.segmented
    assert kit.log[-1] == ("enable", feed.render_product_path, ["InstanceSegmentation"])

    for registry in (SimpleNamespace(_nodeGraphs={}), SimpleNamespace(_reset_node_graph=print), None):
        kit.registry = registry
        other = feeds.CameraFeed("/World/Cam", 320, 240)
        assert "can't free a capture's segmentation graphs" in feeds.enable_segmentation(other)
        assert not other.segmented
    assert sum(entry[0] == "enable" for entry in kit.log if isinstance(entry, tuple)) == 1

    monkeypatch.setitem(sys.modules, "omni.syntheticdata", None)  # an app without it: the import fails
    assert "not loaded" in feeds.enable_segmentation(feeds.CameraFeed("/World/Cam", 8, 8))


def _segmented(feeds: Any, kit: FakeKit) -> Any:
    """A feed with segmentation on, its graph in the registry beside another render product's, its prim on the stage."""
    feed = feeds.CameraFeed("/World/Cam", 320, 240)
    feeds.enable_segmentation(feed)
    kit.registry._nodeGraphs = {
        feed.render_product_path + "/PostRender/SDGPipeline": "this feed's graph",
        PRODUCT_PREFIX + "another/PostRender/SDGPipeline": "another product's graph",
    }
    _with_product(kit, feed.render_product_path)
    kit.log.clear()
    return feed


def test_a_segmented_feed_is_released_in_the_order_measured(feeds, kit):
    feed = _segmented(feeds, kit)
    asyncio.run(feeds.release(feed))
    # Segmentation off, the texture dropped, the graph freed under the session layer, two updates, then the prim gone
    # (#51's E16): in any other order Kit logged errors on every update until the next stage.
    assert kit.log == [
        ("disable", feed.render_product_path, ["InstanceSegmentation"]),
        ("updates", False),
        ("reset", "this feed's graph", "session layer"),
        "update",
        "update",
    ]
    assert list(kit.registry._nodeGraphs.values()) == ["another product's graph"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_release_step_that_fails_leaves_the_rest_to_run(feeds, kit):
    feed = _segmented(feeds, kit)
    kit.sensor_error = RuntimeError("the sensor's node is gone")
    asyncio.run(feeds.release(feed))
    assert kit.log == [("updates", False), ("reset", "this feed's graph", "session layer"), "update", "update"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_omni_syntheticdata_s_own_error_leaves_the_rest_of_the_release_to_run(feeds, kit):
    feed = _segmented(feeds, kit)
    kit.sensor_error = FakeSyntheticDataError("invalid USD stage")
    asyncio.run(feeds.release(feed))  # no error out of it: the capture's answer stands
    assert kit.log == [("updates", False), ("reset", "this feed's graph", "session layer"), "update", "update"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_with_the_stage_closed_the_sensor_is_left_alone_and_the_feed_still_goes(feeds, kit):
    feed = _segmented(feeds, kit)
    # Closed during the capture: omni.syntheticdata would raise without a stage, and reset its graphs as it closed.
    kit.stage, kit.stage_state = None, "CLOSED"
    asyncio.run(feeds.release(feed))
    assert kit.log == [("updates", False), "update", "update"]  # no disable, and no reset without a stage
    assert kit.registry._nodeGraphs == {PRODUCT_PREFIX + "another/PostRender/SDGPipeline": "another product's graph"}
    # The next stage carries the render product over (#25's E13); it goes once that stage is open.
    kit.stage = Usd.Stage.CreateInMemory()
    _with_product(kit, feed.render_product_path)
    kit.stage_state = OPENED
    kit.updates.update()
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_an_error_no_step_expects_still_drops_the_feed_and_its_render_product(feeds, kit):
    feed = _segmented(feeds, kit)
    kit.sensor_error = OSError("an error none of the steps expect")
    with pytest.raises(OSError, match="none of the steps expect"):
        asyncio.run(feeds.release(feed))
    assert kit.log == [("updates", False), ("reset", "this feed's graph", "session layer"), "update", "update"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_feed_without_segmentation_is_released_without_touching_omni_syntheticdata(feeds, kit):
    feed = feeds.CameraFeed("/World/Cam", 320, 240)
    kit.registry._nodeGraphs = {feed.render_product_path + "/PostRender/SDGPipeline": "not ours to free"}
    _with_product(kit, feed.render_product_path)
    asyncio.run(feeds.release(feed))
    assert kit.log == [("updates", False), "update", "update"]
    assert kit.registry._nodeGraphs  # untouched
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_feed_released_while_the_stage_changes_goes_from_the_next_open_stage(feeds, kit):
    feed = _segmented(feeds, kit)
    kit.stage_state = CLOSING
    asyncio.run(feeds.release(feed))
    assert kit.stage.GetPrimAtPath(feed.render_product_path)  # not edited while the stage closes
    # The new stage carries the render product over (#25's E13); it goes once that stage is open.
    kit.stage = Usd.Stage.CreateInMemory()
    _with_product(kit, feed.render_product_path)
    kit.stage_state = OPENED
    kit.updates.update()
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


@pytest.fixture
def utils(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    _fake_kit(kit, monkeypatch)
    return _load("utils_under_test", HANDLERS / "_utils.py")


def test_a_feed_s_frame_comes_back_as_png_bytes(feeds, utils, kit, monkeypatch):
    async def no_viewport_frames(_viewport: Any) -> None:
        raise AssertionError("a feed's capture waited for the viewport's fresh frames (#57's, not the feed's)")

    monkeypatch.setattr(utils, "_next_frame", no_viewport_frames)
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


# ---- the capture feed kept between calls (#114) ----


def _kept_with_frames(feeds: Any, kit: FakeKit, camera: str = "/World/Cam", size: tuple[int, int] = (320, 240)) -> Any:
    """kept_feed's feed, its prim on the stage and a frame rendered, the log cleared."""
    feed = feeds.kept_feed(camera, *size)
    if not kit.stage.GetPrimAtPath(feed.render_product_path):
        _with_product(kit, feed.render_product_path)
    kit.frame(feed.frames + 1)
    kit.log.clear()
    return feed


def _put_back(feeds: Any, feed: Any, healthy: bool = True) -> None:
    async def put_back() -> None:
        await feeds.put_back(feed, healthy)
        feeds._kept._stop_timer()  # the loop ends with the test: its timer would never fire

    asyncio.run(put_back())


def test_a_call_at_the_size_of_the_last_reuses_its_feed_and_sets_a_new_camera_on_both(feeds, kit):
    first = _kept_with_frames(feeds, kit)
    _put_back(feeds, first)

    again = feeds.kept_feed("/World/Cam", 320, 240)
    assert again is first
    assert kit.log == []  # nothing set: Kit's view isn't touched

    other = feeds.kept_feed("/World/Other", 320, 240)
    assert other is first
    assert len(kit.created) == 1  # no new texture, so no new RTX view (#114's K15)
    assert kit.created[0][0].startswith("ovmcp_feed_")
    assert kit.log == [("camera_path", "/World/Other")]
    # The boxes and segmentation read the feed's camera: they follow the texture's.
    assert (first.camera_path, first.resolution) == ("/World/Other", (320, 240))


def test_a_call_at_another_size_resizes_the_kept_feed_in_place(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    product = feed.render_product_path
    _put_back(feeds, feed)

    assert feeds.kept_feed("/World/Cam", 640, 480) is feed
    assert len(kit.created) == 1
    assert kit.log == [("width", 640), ("height", 480)]
    assert (feed.resolution, feed.render_product_path) == ((640, 480), product)


def test_a_kept_feed_is_released_after_the_idle_seconds_with_no_call(feeds, kit, monkeypatch):
    monkeypatch.setattr(feeds, "IDLE_SECONDS", 0.01)
    feed = _kept_with_frames(feeds, kit)

    async def kept_then_idle() -> None:
        await feeds.put_back(feed, True)
        assert feeds._kept.feed is feed  # kept while the time runs
        await asyncio.sleep(0.05)
        await feeds._kept.idle_release

    asyncio.run(kept_then_idle())
    assert feeds._kept.feed is None
    assert kit.log == [("updates", False), "update", "update"]  # release's order
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_call_within_the_idle_seconds_stops_the_timer(feeds, kit, monkeypatch):
    monkeypatch.setattr(feeds, "IDLE_SECONDS", 0.02)
    feed = _kept_with_frames(feeds, kit)

    async def taken_again() -> None:
        await feeds.put_back(feed, True)
        assert feeds.kept_feed("/World/Cam", 320, 240) is feed
        await asyncio.sleep(0.05)

    asyncio.run(taken_again())
    assert feeds._kept.feed is feed
    assert feeds._kept.idle_release is None  # the timer never fired
    assert kit.log == []


def test_an_idle_release_that_waited_for_a_call_does_nothing(feeds, kit, monkeypatch):
    monkeypatch.setattr(feeds, "IDLE_SECONDS", 0.01)
    feed = _kept_with_frames(feeds, kit)

    async def fires_during_a_call() -> None:
        await feeds.put_back(feed, True)
        async with feeds._viewport.get():  # a call holds the lock as the timer fires
            await asyncio.sleep(0.05)
            assert feeds._kept.idle_release is not None
            assert feeds.kept_feed("/World/Cam", 320, 240) is feed
        await feeds._kept.idle_release

    asyncio.run(fires_during_a_call())
    assert feeds._kept.feed is feed
    assert kit.log == []
    assert kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_feed_in_doubt_is_released_at_once(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    _put_back(feeds, feed, healthy=False)
    assert feeds._kept.feed is None
    assert kit.log == [("updates", False), "update", "update"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert feeds.kept_feed("/World/Cam", 320, 240) is not feed


def test_a_calls_segmentation_is_turned_off_as_its_feed_is_kept_and_its_graphs_freed_at_release(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    feeds.enable_segmentation(feed)
    kit.registry._nodeGraphs = {feed.render_product_path + "/PostRender/SDGPipeline": "the feed's graph"}
    kit.log.clear()

    _put_back(feeds, feed)
    # Off between calls: left on, Kit's updates a second while idle fell from 157 to 110 (#114's step 1, S1). The
    # graph stays.
    assert kit.log == [("disable", feed.render_product_path, ["InstanceSegmentation"])]
    assert (feed.segmented, feed.sensor_on) == (True, False)
    assert kit.registry._nodeGraphs

    kit.log.clear()
    asyncio.run(feeds.release_kept())
    # Not turned off twice; the graph freed before the render product goes (#51's E16).
    assert kit.log == [("updates", False), ("reset", "the feed's graph", "session layer"), "update", "update"]
    assert kit.registry._nodeGraphs == {}


def test_a_feed_whose_segmentation_will_not_turn_off_is_released(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    feeds.enable_segmentation(feed)
    kit.sensor_error = RuntimeError("the sensor's node is gone")
    kit.log.clear()
    _put_back(feeds, feed)
    assert feeds._kept.feed is None
    assert ("updates", False) in kit.log
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_release_kept_with_no_feed_kept_does_nothing(feeds, kit):
    asyncio.run(feeds.release_kept())
    assert kit.log == []
    assert kit.created == []


def test_a_closing_stage_drops_the_kept_feed_and_deletes_it_from_the_next_stage(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    _put_back(feeds, feed)
    kit.stage_state = CLOSING
    kit.stage_event("closing")
    assert feeds._kept.feed is None
    assert kit.log == [("updates", False)]  # dropped at once, nothing edited on a closing stage
    # Its render product waits for the next stage under Kit's update event, not the deprecated stream (#122).
    assert kit.updates.names == ["ovmcp.bridge camera feed leftovers"]
    # The new stage carries the render product over (#25's E13); it goes once that stage is open.
    kit.stage, kit.stage_id = Usd.Stage.CreateInMemory(), 2
    _with_product(kit, feed.render_product_path)
    kit.stage_state = OPENED
    kit.updates.update()
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_feed_a_stage_event_let_go_during_its_call_is_left_alone(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    kit.stage_state = CLOSING
    kit.stage_event("closing")
    kit.log.clear()
    _put_back(feeds, feed)
    assert kit.log == []
    assert feeds._kept.feed is None


def test_a_feed_kept_on_another_stage_is_discarded_and_a_new_one_made(feeds, kit):
    old = _kept_with_frames(feeds, kit)
    _put_back(feeds, old)
    # A new stage whose closing never reached the bridge: Kit carried the render product over (#25's E13).
    kit.stage, kit.stage_id = Usd.Stage.CreateInMemory(), 2
    _with_product(kit, old.render_product_path)
    new = feeds.kept_feed("/World/Cam", 320, 240)
    assert new is not old
    assert kit.textures[0].updates == [False]
    assert not kit.stage.GetPrimAtPath(old.render_product_path)
    assert feeds._kept.feed is new


def test_kits_save_tears_the_kept_feed_down_at_once_before_it_writes(feeds, kit):
    feed = _segmented(feeds, kit)
    feeds._kept.keep(feed, kit.stage_id)
    feeds._observe_stage()
    kit.stage_event("saving")
    # release's order with no update between, which a synchronous event can't wait for (#114's step 1: quiet).
    assert kit.log == [
        ("disable", feed.render_product_path, ["InstanceSegmentation"]),
        ("updates", False),
        ("reset", "this feed's graph", "session layer"),
    ]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert feeds._kept.feed is None


def test_shutdown_tears_the_kept_feed_down_at_once_and_stops_observing_the_stage(feeds, kit, monkeypatch):
    monkeypatch.setattr(feeds, "IDLE_SECONDS", 0.01)
    feed = _segmented(feeds, kit)
    feeds._kept.keep(feed, kit.stage_id)
    feeds._observe_stage()

    async def kept_then_shut_down() -> None:
        await feeds.put_back(feed, True)
        feeds.enable_segmentation(feed)  # on again, as a call that shutdown meets would have it
        kit.log.clear()
        feeds.forget()
        await asyncio.sleep(0.05)  # the timer was stopped: no release follows

    asyncio.run(kept_then_shut_down())
    assert kit.log == [
        ("disable", feed.render_product_path, ["InstanceSegmentation"]),
        ("updates", False),
        ("reset", "this feed's graph", "session layer"),
    ]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert (feeds._kept.feed, feeds._kept.stage_events, feeds._kept.idle_release) == (None, [], None)


def test_the_stages_events_are_observed_once(feeds, kit):
    for _ in range(3):
        _put_back(feeds, feeds.kept_feed("/World/Cam", 320, 240))
    names = [o["event_name"] for o in kit.observers if o["event_name"].startswith("stage event")]
    assert names == ["stage event closing", "stage event saving"]


def test_a_feed_let_go_during_a_call_fails_its_waits_at_once(feeds, utils, kit):
    # Kit saves during the call: no wait runs its FRAME_SECONDS for a frame that can't come.
    fresh = feeds.kept_feed("/World/Cam", 320, 240)  # a new feed, waiting for its first frame
    kit.stage_event("saving")
    with pytest.raises(capture.NoFrameError, match="was let go during the call"):
        asyncio.run(asyncio.wait_for(fresh.first_frame(capture.FRAME_SECONDS), 1.0))

    feed = _kept_with_frames(feeds, kit)

    async def saved_while_a_capture_waits() -> bytes:
        scheduled = asyncio.Event()
        schedule = feed.schedule

        def schedule_and_say(delegate: Any) -> Any:
            scheduled.set()
            return schedule(delegate)

        feed.schedule = schedule_and_say
        taking = asyncio.ensure_future(utils.capture_feed_png(feed))
        await scheduled.wait()
        kit.stage_event("saving")  # drop takes the waiting capture back: it would never get its frame
        return await asyncio.wait_for(taking, 1.0)

    with pytest.raises(capture.NoFrameError, match="was let go during the call"):
        asyncio.run(saved_while_a_capture_waits())
    with pytest.raises(capture.NoFrameError, match="was let go during the call"):
        asyncio.run(feed.wait_frames(20))
    with pytest.raises(capture.NoFrameError, match="was let go during the call"):
        feed.schedule(FakeDelegate())


def test_kits_save_during_a_release_deletes_its_render_product_before_it_writes(feeds, kit):
    # The caller let the feed go before release's updates, so Kit's Save between them finds no kept feed.
    feed = _segmented(feeds, kit)
    feeds._observe_stage()
    at_the_save: list[Any] = []

    def save_during_the_updates(_event: Any) -> None:
        if not at_the_save:
            kit.stage_event("saving")
            at_the_save.extend([list(kit.log), bool(kit.stage.GetPrimAtPath(feed.render_product_path))])

    kit.on_update = save_during_the_updates
    asyncio.run(feeds.release(feed))
    done_by_then, product_left = at_the_save
    # Stopped and its graph freed before the save, as the measured teardown has it; its render product gone at it.
    assert done_by_then == [
        ("disable", feed.render_product_path, ["InstanceSegmentation"]),
        ("updates", False),
        ("reset", "this feed's graph", "session layer"),
        "update",
    ]
    assert product_left is False
    assert feeds._releasing == set()
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_kits_save_still_drops_and_deletes_after_an_error_no_step_expects(feeds, kit):
    feed = _segmented(feeds, kit)
    feeds._kept.keep(feed, kit.stage_id)
    feeds._observe_stage()
    kit.sensor_error = OSError("the graph went away")
    with pytest.raises(OSError, match="the graph went away"):
        kit.stage_event("saving")
    assert kit.log == [("updates", False), ("reset", "this feed's graph", "session layer")]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_kept_feed_that_will_not_take_the_calls_camera_is_discarded(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    _put_back(feeds, feed)
    kit.textures[-1].refuses_camera = True
    with pytest.raises(RuntimeError, match="refused the camera"):
        feeds.kept_feed("/World/Other", 320, 240)
    # Half aimed it would render one camera while the boxes said another.
    assert feeds._kept.feed is None
    assert kit.textures[0].updates == [False]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
    assert feeds.kept_feed("/World/Other", 320, 240) is not feed


def test_a_route_that_writes_the_stage_holds_the_lock_with_no_feed_kept(feeds, kit):
    feed = _kept_with_frames(feeds, kit)
    _put_back(feeds, feed)

    async def write() -> tuple[bool, Any]:
        async with feeds.without_kept_feed():
            # A capture asked for now waits for the lock, so the write never meets a feed.
            return feeds._viewport.get().locked(), feeds._kept.feed

    assert asyncio.run(write()) == (True, None)
    assert kit.log == [("updates", False), "update", "update"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


# ---- the kept feed lent to a recording (#141) ----


def _lent(feeds: Any, kit: FakeKit, camera: str = "/World/RecCam", size: tuple[int, int] = (320, 240)) -> Any:
    """lend's feed, its prim on the stage and a frame rendered, the log cleared."""
    feed = asyncio.run(feeds.lend(camera, *size))
    if not kit.stage.GetPrimAtPath(feed.render_product_path):
        _with_product(kit, feed.render_product_path)
    kit.frame(feed.frames + 1)
    kit.log.clear()
    return feed


def test_a_recording_at_the_kept_feeds_size_borrows_it_and_only_sets_its_camera(feeds, kit, monkeypatch):
    monkeypatch.setattr(feeds, "IDLE_SECONDS", 0.01)
    kept = _kept_with_frames(feeds, kit)

    async def lent_before_the_timer_fires() -> Any:
        await feeds.put_back(kept, True)
        feed = await feeds.lend("/World/RecCam", 320, 240)
        await asyncio.sleep(0.05)  # the idle release would have fired by now
        return feed

    assert asyncio.run(lent_before_the_timer_fires()) is kept
    assert len(kit.created) == 1  # no new texture, so no new RTX view (#114's K15)
    assert kit.log == [("camera_path", "/World/RecCam")]  # no size set, nothing released
    assert (kept.camera_path, kept.resolution) == ("/World/RecCam", (320, 240))
    # Off the slot while the recording holds it: no timer, and no stage event or save reaches it there.
    assert (feeds._kept.feed, feeds._kept.timer, feeds._kept.idle_release) == (None, None, None)
    assert kit.stage.GetPrimAtPath(kept.render_product_path)


def test_a_recording_at_another_size_gets_a_feed_of_its_own_and_leaves_the_kept_one(feeds, kit):
    kept = _kept_with_frames(feeds, kit)

    async def lent_at_another_size() -> tuple[Any, Any]:
        await feeds.put_back(kept, True)
        feed = await feeds.lend("/World/RecCam", 160, 120)
        timer = feeds._kept.timer
        feeds._kept._stop_timer()  # the loop ends with the test: its timer would never fire
        return feed, timer

    feed, timer = asyncio.run(lent_at_another_size())
    # A resize would set up a view, and the next capture at 320x240 another; a feed of its own sets up one (P1).
    assert feed is not kept
    assert (feed.camera_path, feed.resolution) == ("/World/RecCam", (160, 120))
    assert feed.name.startswith("ovmcp_feed_")
    assert kit.log == []  # the kept feed untouched: no size, no camera
    assert feeds._kept.feed is kept
    assert timer is not None  # still on its clock


def test_with_no_feed_kept_a_recording_gets_a_new_one_that_isnt_kept(feeds, kit):
    asyncio.run(feeds.lend("/World/RecCam", 320, 240))
    assert len(kit.created) == 1
    assert feeds._kept.feed is None


def test_a_kept_feed_of_another_stage_goes_before_a_recording_gets_a_new_one(feeds, kit):
    old = _kept_with_frames(feeds, kit)
    _put_back(feeds, old)
    kit.stage, kit.stage_id = Usd.Stage.CreateInMemory(), 2
    _with_product(kit, old.render_product_path)
    new = asyncio.run(feeds.lend("/World/RecCam", 320, 240))
    assert new is not old
    assert kit.textures[0].updates == [False]
    assert not kit.stage.GetPrimAtPath(old.render_product_path)
    assert feeds._kept.feed is None


def test_a_kept_feed_that_will_not_take_the_recordings_camera_is_torn_down_with_its_graphs(feeds, kit):
    kept = _kept_with_frames(feeds, kit)
    feeds.enable_segmentation(kept)
    kit.registry._nodeGraphs = {kept.render_product_path + "/PostRender/SDGPipeline": "a capture's graph"}
    _put_back(feeds, kept)  # its sensor turned off, its graph left
    kit.textures[-1].refuses_camera = True
    kit.log.clear()
    with pytest.raises(RuntimeError, match="refused the camera"):
        asyncio.run(feeds.lend("/World/RecCam", 320, 240))
    # The graph freed before the render product goes (#51's E16), which discard would have skipped.
    assert kit.log == [("updates", False), ("reset", "a capture's graph", "session layer")]
    assert kit.registry._nodeGraphs == {}
    assert not kit.stage.GetPrimAtPath(kept.render_product_path)
    assert feeds._kept.feed is None


def test_a_segmented_kept_feed_that_will_not_take_the_calls_camera_has_its_graphs_freed(feeds, kit):
    kept = _kept_with_frames(feeds, kit)
    feeds.enable_segmentation(kept)
    kit.registry._nodeGraphs = {kept.render_product_path + "/PostRender/SDGPipeline": "a capture's graph"}
    _put_back(feeds, kept)
    kit.textures[-1].refuses_camera = True
    kit.log.clear()
    with pytest.raises(RuntimeError, match="refused the camera"):
        feeds.kept_feed("/World/Other", 320, 240)
    assert kit.log == [("updates", False), ("reset", "a capture's graph", "session layer")]
    assert kit.registry._nodeGraphs == {}


def test_after_shutdown_a_recording_borrows_nothing(feeds, kit):
    feeds.forget()
    with pytest.raises(RuntimeError, match="shut down"):
        asyncio.run(feeds.lend("/World/RecCam", 320, 240))
    assert kit.created == []


def test_a_healthy_feed_handed_back_with_none_kept_is_kept_on_the_clock(feeds, kit):
    feed = _lent(feeds, kit)

    async def handed_back() -> Any:
        await feeds.hand_back(feed, kit.stage_id, True)
        timer = feeds._kept.timer
        feeds._kept._stop_timer()
        return timer

    assert asyncio.run(handed_back()) is not None
    assert feeds._kept.feed is feed
    assert feeds._kept.stage_id == kit.stage_id
    assert kit.log == []  # kept as it is, rendering
    # Its stage's closing and Kit's Save now reach it, as they reach a capture's.
    names = [o["event_name"] for o in kit.observers if o["event_name"].startswith("stage event")]
    assert names == ["stage event closing", "stage event saving"]
    assert feeds.kept_feed("/World/Cam", 320, 240) is feed  # the next capture renders through it


@pytest.mark.parametrize(
    "why",
    ["another feed kept", "the stage changed", "the stage is closing", "it was dropped", "in doubt"],
)
def test_a_feed_handed_back_otherwise_is_released(feeds, kit, why):
    feed = _lent(feeds, kit)
    healthy = True
    other = None
    if why == "another feed kept":
        other = _kept_with_frames(feeds, kit, size=(640, 480))
        _put_back(feeds, other)
    elif why == "the stage changed":
        kit.stage_id = 2
    elif why == "the stage is closing":
        kit.stage_state = CLOSING
    elif why == "it was dropped":
        feed.drop()
    else:
        healthy = False
    kit.log.clear()
    asyncio.run(feeds.hand_back(feed, 1, healthy))
    assert feed.dropped
    assert feeds._kept.feed is other
    assert kit.log[-2:] == ["update", "update"]  # release's order
    if why != "the stage is closing":
        assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_stop_while_a_capture_holds_the_lock_releases_without_waiting(feeds, kit):
    feed = _lent(feeds, kit)

    async def stop_during_a_capture() -> None:
        lock = feeds._viewport.get()
        await lock.acquire()  # a capture runs
        try:
            await asyncio.wait_for(feeds.hand_back(feed, kit.stage_id, True), 1.0)
        finally:
            lock.release()

    asyncio.run(stop_during_a_capture())
    assert feed.dropped
    assert feeds._kept.feed is None
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


@pytest.mark.parametrize("stage_open", [True, False], ids=["stage open", "stage closing"])
def test_a_stop_after_shutdown_tears_the_feed_down_and_keeps_nothing(feeds, kit, stage_open):
    # A stop still awaiting its frames as the extension shut down: kept now, the feed would render on a timer
    # nothing cancels, its stage observed again by an unloaded module (round 1's P2).
    feed = _lent(feeds, kit)
    feeds.forget()
    if not stage_open:
        kit.stage_state = CLOSING
    asyncio.run(feeds.hand_back(feed, kit.stage_id, True))
    assert feed.dropped
    assert (feeds._kept.feed, feeds._kept.timer, feeds._kept.stage_events) == (None, None, [])
    assert not [o for o in kit.observers if o["event_name"].startswith("stage event")]
    assert kit.updates.observers == []  # nothing waits for a stage
    assert bool(kit.stage.GetPrimAtPath(feed.render_product_path)) is not stage_open


def test_let_go_now_frees_a_segmented_feeds_graphs_before_its_render_product_goes(feeds, kit):
    feed = _segmented(feeds, kit)
    feeds.let_go_now(feed)
    assert kit.log == [
        ("disable", feed.render_product_path, ["InstanceSegmentation"]),
        ("updates", False),
        ("reset", "this feed's graph", "session layer"),
    ]
    assert list(kit.registry._nodeGraphs.values()) == ["another product's graph"]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)


def test_a_stop_queued_behind_a_capture_during_which_the_extension_shuts_down_keeps_nothing(feeds, kit):
    # The lock is free but a capture is queued for it, so the stop waits behind that capture; the extension shuts down
    # during it. Kept then, the feed would observe the stage again for an unloaded module (code review round 1's F3).
    feed = _lent(feeds, kit)

    async def queued_then_shut_down() -> None:
        lock = feeds._viewport.get()
        await lock.acquire()  # a capture runs

        async def queued_capture() -> None:
            async with lock:
                feeds.forget()  # the extension shuts down during this capture

        queued = asyncio.ensure_future(queued_capture())
        await asyncio.sleep(0)  # it queues for the lock
        lock.release()  # the first capture ends; the queued one is woken but not yet in
        assert not lock.locked()
        await asyncio.wait_for(feeds.hand_back(feed, kit.stage_id, True), 1.0)
        await queued

    asyncio.run(queued_then_shut_down())
    assert feed.dropped
    assert (feeds._kept.feed, feeds._kept.timer, feeds._kept.stage_events) == (None, None, [])
    assert not [o for o in kit.observers if o["event_name"].startswith("stage event")]
    assert not kit.stage.GetPrimAtPath(feed.render_product_path)
