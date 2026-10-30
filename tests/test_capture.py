"""The capture path's waits, each bounded by time, and a call's bookkeeping: core/capture.py, with plain asyncio, a fake
Kit capture and a fake clock."""

import ast
import asyncio
import gc
import inspect
import re
import time
import weakref

import numpy as np
import pytest

from omniverse_mcp.client import BridgeClient
from ovmcp.core import capture
from ovmcp.core.capture import (
    Budget,
    Call,
    CaptureError,
    NoFrameError,
    OutOfTimeError,
    SegmentationWaits,
    bounded,
    capture_png,
    frames,
    poll,
)

from .conftest import EXTENSION_ROOT

_WHOLE = b"\x89PNG\r\n\x1a\n" + b"pixels" + b"\x00\x00\x00\x00IEND\xaeB`\x82"
_PARTIAL = _WHOLE[:12]


def _run(coro):
    return asyncio.run(coro)


class _Clock:
    """Time that moves only when a test moves it."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class _KitCapture:
    """Kit's capture delegate, as omni.kit.widget.viewport's Capture has it: a future the viewport sets, only if not
    done, when it delivers a frame; wait_for_result awaits it, then two app updates."""

    def __init__(self, result=None, *, done=True):
        self.future = asyncio.get_running_loop().create_future()
        if done:
            self.set_completed(result)

    async def wait_for_result(self, completion_frames=2):
        await self.future
        for _ in range(completion_frames):
            await asyncio.sleep(0)
        return self.future.result()

    def set_completed(self, value):
        if not self.future.done():
            self.future.set_result(value)


class _Kit:
    """The bridge's side of capture_png: Kit's capture, the file Kit writes, the viewport's frames and the app's
    updates on a fake clock, and the order the capture asked for frames and scheduled in."""

    def __init__(
        self,
        files=(),
        *,
        result=("LdrColor",),
        done=True,
        schedules=True,
        update_seconds=1.0,
    ):
        self.files = list(files)  # what each read gives, the last one again once they run out
        self.result = list(result) if isinstance(result, tuple) else result
        self.done = done
        self.schedules = schedules
        self.update_seconds = update_seconds
        self.clock = _Clock()
        self.capture: _KitCapture | None = None
        self.events: list[str] = []
        self.reads = 0
        self.updates = 0

    def schedule(self):
        self.events.append("schedule")
        if not self.schedules:
            return None
        self.capture = _KitCapture(self.result, done=self.done)
        return self.capture

    def read_file(self) -> bytes:
        self.reads += 1
        data = self.files[min(self.reads, len(self.files)) - 1] if self.files else None
        if data is None:
            raise FileNotFoundError("not written yet")
        return data

    async def next_update(self):
        self.updates += 1
        self.clock.now += self.update_seconds
        await asyncio.sleep(0)

    async def png(self, budget=None):
        return await capture_png(self.schedule, self.read_file, self.next_update, budget, self.clock)


def test_a_capture_returns_the_png_once_the_file_is_whole():
    kit = _Kit([None, _PARTIAL, _WHOLE], update_seconds=0.5)

    png = _run(kit.png())

    assert png.data == _WHOLE
    assert (kit.reads, kit.updates) == (3, 2)  # missing, then partial: neither is taken
    assert png.file_seconds == 1.0


@pytest.mark.parametrize("result", [[], None], ids=["empty", "none"])
def test_an_empty_result_fails_at_once(result):
    # Kit captured no AOV, so no file will come; the loop before #35 read for FILE_SECONDS first.
    kit = _Kit([_WHOLE], result=result)

    with pytest.raises(CaptureError, match=re.escape(f"wait_for_result gave {result!r}")):
        _run(kit.png())

    assert (kit.reads, kit.updates) == (0, 0)


def test_no_render_texture_is_an_error():
    kit = _Kit([_WHOLE], schedules=False)

    with pytest.raises(CaptureError, match="no render texture"):
        _run(kit.png())


def test_a_frame_that_never_comes_is_no_frame(monkeypatch):
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.05)
    kit = _Kit([_WHOLE], done=False)

    async def main():
        with pytest.raises(NoFrameError, match=r"no frame in 0\.05 s"):
            await kit.png()
        assert kit.capture is not None
        # The viewport delivers its frame after all: Kit sets the future only if not done, and ours was cancelled.
        assert kit.capture.future.cancelled()
        kit.capture.set_completed(["LdrColor"])

    _run(main())
    assert kit.reads == 0


def test_every_capture_takes_its_frame_from_a_feed():
    # A capture of the viewport took the next frame the viewport delivered, rendered about 3 updates before (#57), and
    # at the viewport's size (#51). Recording, capture_viewport and inspect_prim each render through a feed of their
    # own, whose next frame is within one update of the request (#25's E17), and no viewport capture is left to call.
    # The handlers import Kit, so the guard reads the source.
    handlers = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers"

    def called(module: str) -> set[str]:
        tree = ast.parse((handlers / module).read_text(encoding="utf-8"))
        return {
            node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

    for module in ("recording.py", "camera.py"):
        assert "capture_feed_png" in called(module), f"{module} no longer captures from a feed: guard what it calls"
    for module in sorted(p.name for p in handlers.glob("*.py")):
        assert "capture_viewport_to_file" not in called(module), module


def test_a_file_that_never_comes_fails_after_file_seconds():
    kit = _Kit([None])

    with pytest.raises(CaptureError, match=re.escape("no whole image in 10 s after capturing ['LdrColor']")) as raised:
        _run(kit.png())

    assert not isinstance(raised.value, OutOfTimeError)
    assert kit.clock.now == 10.0


def test_capture_errors_are_runtime_errors(monkeypatch):
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.01)
    for error in (CaptureError, NoFrameError, OutOfTimeError):
        assert issubclass(error, RuntimeError)
        assert not issubclass(error, TimeoutError)

    async def frame_that_never_comes():
        await asyncio.get_running_loop().create_future()

    async def main():
        try:
            await bounded(frame_that_never_comes(), capture.FRAME_SECONDS, None)
        except RuntimeError as error:  # recording's except
            return error
        return None

    error = _run(main())
    assert isinstance(error, NoFrameError)
    # Raised outside the except: nothing chains back to the cancelled wait.
    assert error.__context__ is None
    assert error.__cause__ is None


def test_the_budget_caps_each_wait_and_says_out_of_time():
    # The frame's own bound is 30 s; the budget's 0.02 s ends first.
    async def frame_cut_short():
        kit = _Kit([_WHOLE], done=False)
        with pytest.raises(OutOfTimeError, match="this call may take ran out"):
            await capture_png(kit.schedule, kit.read_file, kit.next_update, Budget(0.02))

    _run(frame_cut_short())

    # The file's own bound is 10 s; the budget's 3 s end first.
    kit = _Kit([None])
    with pytest.raises(OutOfTimeError):
        _run(kit.png(Budget(3, kit.clock)))
    assert kit.clock.now == 3.0

    # A spent budget starts no capture.
    kit = _Kit([_WHOLE])
    spent = Budget(1, kit.clock)
    kit.clock.now = 2.0
    with pytest.raises(OutOfTimeError):
        _run(kit.png(spent))
    assert kit.capture is None

    # Nor any other wait: the awaitable it was handed is closed, never started.
    async def frame():
        await asyncio.sleep(0)

    pending = frame()
    with pytest.raises(OutOfTimeError):
        _run(bounded(pending, 30, spent))
    assert pending.cr_frame is None


def test_frames_bounds_each_frame(monkeypatch):
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.05)
    asked = []

    def next_frame():
        asked.append(len(asked) + 1)
        future = asyncio.get_running_loop().create_future()
        if len(asked) < 3:
            future.set_result(None)  # the first two frames come; the third never does
        return future

    with pytest.raises(NoFrameError):
        _run(frames(next_frame, 20, Budget(80)))
    assert asked == [1, 2, 3]

    # Without a call's budget, a viewport that renders nothing is no frame, not out of time.
    asked.clear()
    with pytest.raises(NoFrameError):
        _run(frames(lambda: asyncio.get_running_loop().create_future(), 20))


def test_frames_without_a_budget_share_one_of_frame_seconds(monkeypatch):
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.5)
    clock = _Clock()
    count = 0

    async def slow_frame():
        # 0.2 s on the fake clock each, at once in real time, so a busy machine can't tip the result.
        nonlocal count
        count += 1
        if count == 3:
            await asyncio.get_running_loop().create_future()  # longer than the 0.1 s left of the shared 0.5 s
        clock.now += 0.2

    # Each frame is well inside 0.5 s, but three of them are not.
    with pytest.raises(OutOfTimeError):
        _run(frames(slow_frame, 20, clock=clock))
    assert count == 3
    assert clock.now == pytest.approx(0.4)


def test_poll_returns_the_first_ready_value_or_none():
    clock = _Clock()
    values = iter([0, 0, 3, 4])
    updates = 0

    async def next_update():
        nonlocal updates
        updates += 1
        clock.now += 1

    found = _run(poll(lambda: next(values), lambda v: v > 0, next_update, 5, None, clock))
    assert (found, updates) == (3, 2)

    reads = 0

    def read():
        nonlocal reads
        reads += 1
        return 0

    clock.now, updates = 0.0, 0
    assert _run(poll(read, lambda v: v > 0, next_update, 2.5, None, clock)) is None
    assert (reads, updates) == (4, 3)  # at 0, 1, 2 and 3 s

    # A budget with less left than the poll's own time ends it sooner.
    clock.now, updates = 0.0, 0
    assert _run(poll(read, lambda v: v > 0, next_update, 10, Budget(1.5, clock), clock)) is None
    assert updates == 2


def test_a_call_stops_on_no_frame_and_out_of_time():
    call = Call(80, _Clock())
    assert call.skipped("front") is None

    # Other capture errors are that angle's alone: the next angle may well work.
    call.failed(CaptureError("Kit captured nothing (wait_for_result gave [])"))
    call.failed(ValueError("not a capture error"))
    assert call.skipped("front") is None
    assert call.settle_after_restore()

    error = NoFrameError("The viewport rendered no frame in 30 s: its updates may be off")
    call.failed(error)
    call.failed(OutOfTimeError("The 80 s this call may take ran out"))  # the first stop is the one kept
    assert call.skipped("right") == {
        "angle": "right",
        "error": "Not captured: the viewport rendered no frame in 30 s: its updates may be off",
    }
    assert not call.settle_after_restore()

    # The message is kept, not the exception, whose traceback would hold the cancelled frame wait.
    kept = weakref.ref(error)
    del error
    gc.collect()
    assert kept() is None

    call = Call(80, _Clock())
    call.failed(OutOfTimeError("The 80 s this call may take ran out"))
    assert call.skipped("top") == {"angle": "top", "error": "Not captured: the 80 s this call may take ran out"}
    assert call.settle_after_restore()


def test_segmentation_waits_briefly_after_a_wait_that_got_nothing_until_data():
    waits = SegmentationWaits()
    # A capture's feed is new each time, so its waits are kept by stage, camera and size.
    here = (1, "/World/Cam", (320, 240))
    elsewhere = [(1, "/World/Cam", (640, 480)), (1, "/World/Other", (320, 240)), (2, "/World/Cam", (320, 240))]

    assert waits.seconds(here) == 5
    assert not waits.failed_before(here)
    waits.failed(here)
    assert waits.failed_before(here)
    # Not none: the next feed's sensor needs a frame or two for its first data.
    assert waits.seconds(here) == capture.SEGMENTATION_RETRY_SECONDS == 1
    for key in elsewhere:
        assert waits.seconds(key) == 5  # another size, camera or stage waits afresh
    waits.got_data(here)
    assert waits.seconds(here) == 5
    waits.got_data(elsewhere[2])  # nothing on record there: no error
    assert waits.seconds(elsewhere[2]) == 5


def test_the_waits_read_their_seconds_when_called(monkeypatch):
    # A live test shortens them through execute_script, after the module was imported.
    monkeypatch.setattr(capture, "FRAME_SECONDS", 0.02)
    monkeypatch.setattr(capture, "FILE_SECONDS", 3.0)
    monkeypatch.setattr(capture, "SEGMENTATION_SECONDS", 2.0)

    with pytest.raises(NoFrameError, match=r"0\.02 s"):
        _run(frames(lambda: asyncio.get_running_loop().create_future(), 1))

    kit = _Kit([None])
    with pytest.raises(CaptureError, match="in 3 s"):
        _run(kit.png())
    assert kit.clock.now == 3.0

    assert SegmentationWaits().seconds("stage") == 2.0


@pytest.mark.parametrize(("width", "height"), [(1, 1), (640, 480), (capture.MAX_SIDE, capture.MAX_SIDE)])
def test_a_frame_size_from_1_to_the_limit_is_taken(width, height):
    assert capture.frame_size(width, height) == (width, height)


@pytest.mark.parametrize(
    ("width", "height", "named"),
    [
        (0, 480, "width"),
        (640, -1, "height"),
        (capture.MAX_SIDE + 1, 480, "width"),
        (640, capture.MAX_SIDE + 1, "height"),
        (True, 480, "width"),  # an int to Python, and 1 pixel wide
        (640.0, 480, "width"),
        ("640", 480, "width"),
        (640, None, "height"),
    ],
)
def test_a_frame_size_out_of_range_or_not_whole_is_refused_naming_the_value(width, height, named):
    with pytest.raises(ValueError, match=rf"^{named} must be a whole number of pixels from 1 to 4096, got "):
        capture.frame_size(width, height)


@pytest.mark.parametrize(
    ("body", "size"),
    [
        ({}, None),
        ({"width": None, "height": None}, None),
        ({"width": 320, "height": 240}, (320, 240)),
        ({"width": capture.MAX_SIDE, "height": capture.MAX_SIDE}, (4096, 4096)),
    ],
)
def test_a_capture_size_is_both_sides_or_neither(body, size):
    assert capture.capture_size(body) == size


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"width": 320}, "only width was given"),
        ({"height": 240}, "only height was given"),
        ({"width": capture.MAX_SIDE + 1, "height": 240}, "width must be a whole number of pixels from 1 to 4096"),
        ({"width": 320, "height": 0}, "height must be"),
        ({"width": -1, "height": 240}, "width must be"),
        ({"width": True, "height": 240}, "width must be"),
        ({"width": 320.5, "height": 240}, "width must be"),
        ({"width": "1280", "height": 720}, "width must be"),
    ],
)
def test_a_capture_size_out_of_range_or_half_given_is_refused(body, message):
    with pytest.raises(ValueError, match=message):
        capture.capture_size(body)


@pytest.mark.parametrize(
    ("mode", "spp", "total", "frames"),
    [
        ("PathTracing", 64, 64, 0),  # Isaac Sim's: its first frame has every sample
        ("PathTracing", 1, 64, 63),
        ("PathTracing", 4, 10, 2),
        ("PathTracing", 8, 0, 0),  # no total set: nothing to wait for
        ("PathTracing", 1, 100_000, capture.MAX_SETTLE_FRAMES),
        ("PathTracing", None, 3, 2),  # no samples a frame read: one each
        ("RealTimePathTracing", 1, 64, 0),
        ("RaytracedLighting", 1, 64, 0),
        (None, 1, 64, 0),
    ],
)
def test_a_feed_settles_until_path_tracing_has_its_samples(mode, spp, total, frames):
    assert capture.settle_frames(mode, spp, total) == frames


def _colour_loop(ids, name_of):
    """The bridge's colouring before #51, one mask per id, for the one-pass version to match."""
    unique = np.unique(ids)
    image = np.zeros((*ids.shape[:2], 3), dtype=np.uint8)
    legend = {}
    for index, uid in enumerate(unique):
        if int(uid) == 0:
            continue
        hue = (index * 0.618033988749895) % 1.0
        sector = int(hue * 6)
        fraction = hue * 6 - sector
        falling, rising = int(255 * (1 - fraction)), int(255 * fraction)
        colours = [
            [255, rising, 0],
            [falling, 255, 0],
            [0, 255, rising],
            [0, falling, 255],
            [rising, 0, 255],
            [255, 0, falling],
        ]
        image[ids == uid] = colours[sector]
        legend.setdefault(name_of(int(uid)), colours[sector])
    return image, legend


def test_instances_are_coloured_as_before_in_one_pass():
    ids = np.array([[0, 7, 7, 3], [3, 0, 9, 12], [12, 12, 0, 7]], dtype=np.uint32)
    names = {3: "/World/A", 7: "/World/B", 9: "/World/B", 12: "/World/C"}  # two ids, one prim

    image, legend = capture.colour_instances(ids, names.__getitem__)
    expected_image, expected_legend = _colour_loop(ids, names.__getitem__)
    assert image.dtype == np.uint8
    assert image.shape == (3, 4, 3)
    assert np.array_equal(image, expected_image)
    assert legend == expected_legend
    assert list(legend) == ["/World/A", "/World/B", "/World/C"]
    assert not image[ids == 0].any()  # the background stays black


def test_an_instance_without_a_name_is_named_by_its_id():
    _image, legend = capture.colour_instances(np.array([[0, 5]], dtype=np.uint32), lambda _instance: None)
    assert list(legend) == ["instance_5"]


def test_colouring_a_4096_a_side_capture_is_one_pass():
    ids = (np.arange(4096 * 4096, dtype=np.uint32) % 2000).reshape(4096, 4096)
    started = time.monotonic()
    image, legend = capture.colour_instances(ids, lambda instance: f"/World/P{instance}")
    took = time.monotonic() - started
    assert image.shape == (4096, 4096, 3)
    assert len(legend) == 1999
    # A mask per id would be 2,000 passes over the 16.8 million pixels, minutes on any runner; one lookup takes a few
    # seconds at most.
    assert took < 10, f"{took:.1f} s"


def test_a_feed_that_renders_nothing_is_named_in_its_error():
    async def never():
        await asyncio.sleep(1)

    with pytest.raises(NoFrameError, match=r"^The camera /World/Cam rendered no frame in 0\.05 s$"):
        _run(bounded(never(), 0.05, None, "The camera /World/Cam"))
    with pytest.raises(NoFrameError, match=r"^The viewport rendered no frame in 0\.05 s: its updates may be off"):
        _run(bounded(never(), 0.05, None))


def test_a_call_ends_before_the_server_gives_up():
    # The bridge sends nothing until a handler returns, so the server's socket timeout bounds the whole call; 20 s are
    # left for encoding the images and sending them.
    client_timeout = inspect.signature(BridgeClient.__init__).parameters["timeout"].default
    assert client_timeout >= capture.CALL_SECONDS + capture.CLEANUP_SECONDS + 20
