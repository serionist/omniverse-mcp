"""The recording handler against a fake Kit (#25, #69): the feed it makes, when it takes frames and how it numbers
them, how frames stop when the stage changes or the camera goes, and how start, stop and shutdown clean up.

handlers/recording.py is loaded from its file with Kit's modules, its _utils and its camera feed faked in sys.modules,
as tests/test_debug_draw_handler.py loads its handler. The stage is a real usd-core one, and the Kit-free core is
the real one.
"""

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd, UsdGeom

from ovmcp.core import capture
from ovmcp.core.recording import MAX_IN_FLIGHT

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "recording.py"
OPENED, CLOSING = "OPENED", "CLOSING"
PNG = b"\x89PNG\r\n\x1a\nframe"


class FakeFeed:
    """A camera feed as the handler uses it."""

    def __init__(self, kit: "FakeKit", camera_path: str, width: int, height: int) -> None:
        self.kit = kit
        self.camera_path, self.width, self.height = camera_path, width, height
        self.render_product_path = f"/Render/OmniverseKit/HydraTextures/ovmcp_recording_{len(kit.feeds)}"
        self.waiting = False
        self.dropped = False

    async def first_frame(self, seconds: float) -> None:
        assert seconds == capture.FRAME_SECONDS
        await self.kit.first_frame_wait()

    def drop(self) -> None:
        self.dropped = True


class FakeKit:
    """Kit as the handler sees it: the stage and its state, the timeline, the update stream, the feeds made and
    discarded, and each capture's frame, which a test hands over when it chooses."""

    def __init__(self) -> None:
        self.stage = Usd.Stage.CreateInMemory()
        for path in ("/World/RecCam", "/OmniverseKit_Persp"):
            UsdGeom.Camera.Define(self.stage, path)
        UsdGeom.Cube.Define(self.stage, "/World/RedCube")
        UsdGeom.Xform.Define(self.stage, "/World/G1")
        UsdGeom.Xform.Define(self.stage, "/World/G1/base")
        self.stage_id = 1
        self.stage_state = OPENED
        self.sim_time = 0.0
        self.feeds: list[FakeFeed] = []
        self.discarded: list[FakeFeed] = []
        self.discard_raises = False
        self.forgotten = 0
        self.captures: list[asyncio.Future[bytes]] = []
        self.subscriptions: list[Any] = []
        self.first_frame_fails = False
        self.first_frame_gate: asyncio.Future[None] | None = None

    async def first_frame_wait(self) -> None:
        if self.first_frame_gate is not None:
            await self.first_frame_gate
        if self.first_frame_fails:
            raise capture.NoFrameError("The camera /World/RecCam rendered no frame in 30 s")

    def make_feed(self, camera_path: str, width: int, height: int) -> FakeFeed:
        self.feeds.append(FakeFeed(self, camera_path, width, height))
        return self.feeds[-1]

    def discard(self, feed: FakeFeed) -> None:
        feed.drop()
        self.discarded.append(feed)
        if self.discard_raises:
            raise RuntimeError("the layer is locked")

    async def capture_feed_png(self, _feed: FakeFeed, _budget: Any = None) -> bytes:
        future: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
        self.captures.append(future)
        return await future

    def subscribe(self, fn: Any, name: str = "") -> SimpleNamespace:
        self.subscriptions.append(fn)
        return SimpleNamespace(name=name)

    def update(self) -> None:
        """One Kit update: the newest subscription's callback, as Kit calls it."""
        self.subscriptions[-1](None)


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def recording(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    timeline = SimpleNamespace(get_time_codes_per_seconds=lambda: 60.0, get_current_time=lambda: kit.sim_time)
    context = SimpleNamespace(
        get_stage_id=lambda: kit.stage_id, get_stage_state=lambda: kit.stage_state, get_stage=lambda: kit.stage
    )
    stream = SimpleNamespace(create_subscription_to_pop=kit.subscribe)
    kit_app = _module("omni.kit.app", get_app=lambda: SimpleNamespace(get_update_event_stream=lambda: stream))
    usd = _module("omni.usd", get_context=lambda: context, StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING))
    omni_timeline = _module("omni.timeline", get_timeline_interface=lambda: timeline)
    omni_kit = _module("omni.kit", app=kit_app)
    fakes = {
        "carb": _module("carb", log_warn=lambda _m: None, log_info=lambda _m: None),
        "omni": _module("omni", kit=omni_kit, usd=usd, timeline=omni_timeline),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.timeline": omni_timeline,
        "omni.usd": usd,
        # What start checks the app has, before it makes a feed; the feed itself is faked below.
        "omni.kit.hydra_texture": _module("omni.kit.hydra_texture"),
        "omni.kit.widget.viewport.capture": _module("omni.kit.widget.viewport.capture"),
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            _get_active_camera_path=lambda: "/OmniverseKit_Persp",
            _get_stage=lambda: kit.stage,
            capture_feed_png=kit.capture_feed_png,
        ),
        "handlers_under_test.camera_feed": _module(
            "handlers_under_test.camera_feed",
            CameraFeed=kit.make_feed,
            discard=kit.discard,
            forget=lambda: setattr(kit, "forgotten", kit.forgotten + 1),
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.recording", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _settle() -> None:
    """Lets every task that can run, run."""
    for _ in range(5):
        await asyncio.sleep(0)


def _body(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    return {"output_dir": str(tmp_path), "fps": 30, "width": 320, "height": 240, **extra}


async def _start(recording: Any, tmp_path: Path, **extra: Any) -> dict[str, Any]:
    return await recording.handle_recording_start(_body(tmp_path, **extra))


def _metadata(stop: dict[str, Any]) -> dict[str, Any]:
    return json.loads(Path(stop["result"]["metadata_file"]).read_text())


def test_start_makes_one_feed_of_the_camera_at_the_size_asked(recording, kit, tmp_path):
    r = asyncio.run(_start(recording, tmp_path, camera_path="/World/RecCam"))
    assert r["status"] == "success", r
    (feed,) = kit.feeds
    assert (feed.camera_path, feed.width, feed.height) == ("/World/RecCam", 320, 240)
    result = r["result"]
    assert result["resolution"] == [320, 240]
    assert result["camera_path"] == "/World/RecCam"
    assert result["render_product"] == feed.render_product_path
    assert recording.recording_active()


def test_without_a_camera_it_records_the_active_viewport_s(recording, kit, tmp_path):
    r = asyncio.run(_start(recording, tmp_path))
    assert r["result"]["camera_path"] == "/OmniverseKit_Persp"
    assert kit.feeds[0].camera_path == "/OmniverseKit_Persp"


@pytest.mark.parametrize(
    ("extra", "says"),
    [
        ({"camera_path": "/World/Nothing"}, "No prim at /World/Nothing"),
        ({"camera_path": "/World/RedCube"}, "not a Camera"),
        ({"width": 4097}, "width must be a whole number of pixels from 1 to 4096"),
        ({"fps": 0}, "fps must be a whole number of at least 1"),
    ],
)
def test_a_bad_camera_or_size_is_refused_and_makes_nothing(recording, kit, tmp_path, extra, says):
    r = asyncio.run(_start(recording, tmp_path, **extra))
    assert r["status"] == "error"
    assert says in r["error"]
    assert kit.feeds == []
    assert not recording.recording_active()
    assert list(tmp_path.iterdir()) == []


def test_a_second_start_while_the_first_waits_for_its_first_frame_is_refused(recording, kit, tmp_path):
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        kit.first_frame_gate = asyncio.get_running_loop().create_future()
        first = asyncio.ensure_future(_start(recording, tmp_path))
        await _settle()
        second = await _start(recording, tmp_path, force=True)
        kit.first_frame_gate.set_result(None)
        return await first, second

    first, second = asyncio.run(scenario())
    assert first["status"] == "success"
    assert second == {"status": "error", "error": recording.STARTING}
    assert len(kit.feeds) == 1


def test_the_refusals_of_a_second_start_name_stop_recording_and_no_force(recording, kit, tmp_path):
    # start_recording has no force: 0.2.3's "use force=True to override" was a hint no agent could follow (#82).
    async def scenario() -> dict[str, Any]:
        first = await _start(recording, tmp_path)
        assert first["status"] == "success"
        return await _start(recording, tmp_path)

    second = asyncio.run(scenario())
    assert second == {"status": "error", "error": recording.ALREADY_ACTIVE}
    for refusal in (recording.ALREADY_ACTIVE, recording.STARTING):
        assert "stop_recording" in refusal
        assert "force" not in refusal


def test_a_feed_that_renders_no_first_frame_is_an_error_that_leaves_nothing(recording, kit, tmp_path):
    kit.first_frame_fails = True
    r = asyncio.run(_start(recording, tmp_path))
    assert r["status"] == "error"
    assert "rendered no frame in 30 s" in r["error"]
    assert kit.discarded == kit.feeds
    assert not recording.recording_active()


def test_a_stage_change_during_the_first_frame_is_an_error_that_leaves_nothing(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        kit.first_frame_gate = asyncio.get_running_loop().create_future()
        start = asyncio.ensure_future(_start(recording, tmp_path))
        await _settle()
        kit.stage_id = 2  # a new_scene while the feed waited
        kit.first_frame_gate.set_result(None)
        return await start

    r = asyncio.run(scenario())
    assert r["status"] == "error"
    assert "The stage changed while the recording started" in r["error"]
    assert kit.discarded == kit.feeds
    assert not recording.recording_active()


def test_frames_are_taken_every_few_updates_and_none_while_one_awaits_its_render(recording, kit, tmp_path):
    async def scenario() -> None:
        await _start(recording, tmp_path)  # fps 30 at 60 time codes: a frame every 2 updates
        feed = kit.feeds[0]
        kit.update()
        kit.update()
        await _settle()
        assert len(kit.captures) == 1
        feed.waiting = True  # its render hasn't come: a frame now would share it
        kit.update()
        kit.update()
        await _settle()
        assert len(kit.captures) == 1
        feed.waiting = False
        kit.update()
        kit.update()
        await _settle()
        assert len(kit.captures) == 2

    asyncio.run(scenario())


def test_no_more_than_four_frames_are_in_flight(recording, kit, tmp_path):
    async def scenario() -> None:
        await _start(recording, tmp_path)
        for _ in range(2 * (MAX_IN_FLIGHT + 3)):
            kit.update()
        await _settle()
        assert len(kit.captures) == MAX_IN_FLIGHT
        kit.captures[0].set_result(PNG)
        await _settle()
        kit.update()
        kit.update()
        await _settle()
        assert len(kit.captures) == MAX_IN_FLIGHT + 1

    asyncio.run(scenario())


def test_frames_keep_the_numbers_of_their_ticks_whatever_order_they_end_in(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path, track_prims=["/World/G1"])
        for t in range(6):
            kit.sim_time = t / 60
            kit.update()
        await _settle()
        assert len(kit.captures) == 3
        for future, data in zip(reversed(kit.captures), (b"third", b"second", b"first"), strict=True):
            future.set_result(data)
            await _settle()
        return await recording.handle_recording_stop({})

    stop = asyncio.run(scenario())
    folder = Path(stop["result"]["output_dir"])
    assert [(folder / f"frame_{n:05d}.png").read_bytes() for n in range(3)] == [b"first", b"second", b"third"]
    meta = _metadata(stop)
    assert [f["frame"] for f in meta["frames"]] == [0, 1, 2]
    # Each frame's sim_time is its tick's (updates 2, 4, 6), and so is its state, written in number order.
    assert [round(f["sim_time"] * 60) for f in meta["frames"]] == [1, 3, 5]
    state = (folder / "state.txt").read_text()
    assert state.startswith("# Omniverse MCP Recording State")
    headers = [line for line in state.splitlines() if line.startswith("=== FRAME")]
    assert len(headers) == 3
    assert meta["track_prims"] == ["/World/G1", "/World/G1/base"]


def test_stop_awaits_the_frames_in_flight_then_cleans_up_and_writes_the_metadata(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path, camera_path="/World/RecCam")
        kit.update()
        kit.update()
        await _settle()
        stop = asyncio.ensure_future(recording.handle_recording_stop({}))
        await _settle()
        assert not stop.done()  # its frame is still being taken
        kit.captures[0].set_result(PNG)
        return await stop

    stop = asyncio.run(scenario())
    assert stop["status"] == "success"
    assert stop["result"]["frame_count"] == 1
    assert "note" not in stop["result"]
    assert kit.discarded == kit.feeds
    meta = _metadata(stop)
    assert (meta["resolution"], meta["camera_path"], meta["frame_count"]) == ([320, 240], "/World/RecCam", 1)
    assert "ended" not in meta
    assert (Path(stop["result"]["output_dir"]) / "frame_00000.png").read_bytes() == PNG
    assert not recording.recording_active()
    assert asyncio.run(recording.handle_recording_stop({})) == {"status": "error", "error": "No active recording"}


def test_a_removal_that_fails_still_ends_the_recording_and_writes_its_metadata(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path)
        kit.discard_raises = True
        return await recording.handle_recording_stop({})

    stop = asyncio.run(scenario())
    assert stop["status"] == "success"
    assert "was not deleted: the layer is locked" in stop["result"]["note"]
    assert _metadata(stop)["frame_count"] == 0
    assert not recording.recording_active()


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda kit: setattr(kit, "stage_state", CLOSING), "the stage began to close"),
        (lambda kit: setattr(kit, "stage_id", 2), "the stage changed"),
        (lambda kit: kit.stage.RemovePrim("/World/RecCam"), "the camera is gone: /World/RecCam was deleted"),
        (
            lambda kit: UsdGeom.Xform.Define(kit.stage, "/World/RecCam"),
            "the camera is gone: /World/RecCam is no longer a Camera",
        ),
    ],
)
def test_frames_stop_when_the_stage_changes_or_the_camera_goes(recording, kit, tmp_path, change, says):
    async def scenario() -> tuple[str | None, dict[str, Any]]:
        await _start(recording, tmp_path, camera_path="/World/RecCam")
        kit.update()
        kit.update()
        await _settle()
        assert len(kit.captures) == 1
        change(kit)
        kit.update()
        await _settle()
        note = recording.recording_note()
        for _ in range(6):
            kit.update()  # no more frames after
        await _settle()
        assert len(kit.captures) == 1
        return note, await recording.handle_recording_stop({})

    note, stop = asyncio.run(scenario())
    assert note is not None
    assert says in note
    assert kit.discarded == kit.feeds  # the feed went at once, its render product with it
    assert says in stop["result"]["note"]
    meta = _metadata(stop)
    assert says in meta["ended"]
    # The frame in flight was cancelled at once: an empty marker, not a 30 s wait.
    assert (Path(stop["result"]["output_dir"]) / "frame_00000.png").read_bytes() == b""
    assert [f["frame"] for f in meta["frames"]] == [0]


def test_a_forced_start_ends_the_running_recording_first(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path)
        return await _start(recording, tmp_path, force=True)

    r = asyncio.run(scenario())
    assert r["status"] == "success"
    first, second = kit.feeds
    assert kit.discarded == [first]
    assert not second.dropped


def test_a_forced_start_with_a_bad_camera_keeps_the_running_recording(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path)
        return await _start(recording, tmp_path, force=True, camera_path="/World/RedCube")

    r = asyncio.run(scenario())
    assert r["status"] == "error"
    assert "not a Camera" in r["error"]
    assert recording.recording_active()
    assert kit.discarded == []


def test_no_start_slips_in_while_a_forced_start_ends_the_running_recording(recording, kit, tmp_path):
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        await _start(recording, tmp_path)
        kit.update()
        kit.update()
        await _settle()
        forced = asyncio.ensure_future(_start(recording, tmp_path, force=True))
        await _settle()  # the forced start waits for the running recording's frame in flight
        ordinary = await _start(recording, tmp_path)
        kit.captures[0].set_result(PNG)
        return await forced, ordinary

    forced, ordinary = asyncio.run(scenario())
    assert forced["status"] == "success"
    assert ordinary == {"status": "error", "error": recording.STARTING}  # the forced start is still under way
    assert len(kit.feeds) == 2


def test_a_start_waiting_for_its_first_frame_fails_once_the_extension_shuts_down(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        kit.first_frame_gate = asyncio.get_running_loop().create_future()
        start = asyncio.ensure_future(_start(recording, tmp_path))
        await _settle()
        recording.shut_down()  # a hot reload, say, while the feed waits
        kit.first_frame_gate.set_result(None)
        return await start

    r = asyncio.run(scenario())
    assert r["status"] == "error"
    assert "shut down" in r["error"]
    assert kit.discarded == kit.feeds
    assert not recording.recording_active()


def test_an_app_that_cannot_capture_a_camera_is_refused_before_anything_is_made(recording, kit, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "omni.kit.widget.viewport.capture", None)
    r = asyncio.run(_start(recording, tmp_path))
    assert r == {
        "status": "error",
        "error": "This Kit app can't record from a camera: it has no omni.kit.widget.viewport.capture",
    }
    assert kit.feeds == []


def test_shutdown_ends_the_frames_and_the_feed_but_deletes_nothing(recording, kit, tmp_path):
    async def scenario() -> None:
        await _start(recording, tmp_path)
        kit.update()
        kit.update()
        await _settle()
        recording.shut_down()
        await _settle()

    asyncio.run(scenario())
    (feed,) = kit.feeds
    assert feed.dropped
    assert kit.discarded == []  # deleting prims while Kit shuts down risks a crash
    assert kit.forgotten == 1
    assert kit.captures[0].cancelled()
    assert not recording.recording_active()


def test_a_frame_comes_back_from_the_last_recording(recording, kit, tmp_path):
    async def scenario() -> dict[str, Any]:
        await _start(recording, tmp_path)
        kit.update()
        kit.update()
        await _settle()
        kit.captures[0].set_result(PNG)
        await recording.handle_recording_stop({})
        return await recording.handle_recording_frame({"frame_index": 0})

    r = asyncio.run(scenario())
    assert r["status"] == "success"
    assert r["result"]["frame"] == 0
    assert r["result"]["image_base64"]
