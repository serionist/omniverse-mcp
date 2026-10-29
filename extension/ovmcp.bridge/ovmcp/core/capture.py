"""The capture path's waits, each bounded by time, and the bookkeeping of one inspect or capture call.

A fixed count of app updates is too few on a cold start (#27), and a wait with no bound hangs the call and the viewport
lock when the viewport renders nothing (#35). Every wait here has a time limit instead. No Kit imports: the bridge
passes Kit's calls in, so the tests run these with plain asyncio.

The limits are read when a function runs, never bound as defaults, so a live test can shorten one through
execute_script.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine, Hashable
from typing import NamedTuple, Protocol, TypeVar

from .png import is_complete_png

T = TypeVar("T")

FRAME_SECONDS = 30.0  # one frame of the viewport: a settle's, a reset's, or the capture's own
FILE_SECONDS = 10.0  # the captured file, which Kit 110 writes after it says the capture is done (#32)
SEGMENTATION_SECONDS = 5.0  # instance segmentation's first data after the sensor is enabled
CALL_SECONDS = 80.0  # one inspect_prim or capture_viewport call
CLEANUP_SECONDS = 10.0  # the settle after isolate's prims are shown again
# The server's client gives up after 120 s. A call's 80 s and its cleanup's 10 s leave 30 s for encoding the images
# and sending them; a unit test holds the sum under the client's timeout.

Clock = Callable[[], float]


class CaptureError(RuntimeError):
    """A capture that gave no image; the message says which step, and for how long.

    A RuntimeError, so recording's `except RuntimeError` still turns a failed frame into its empty marker.
    """


class NoFrameError(CaptureError):
    """The viewport delivered no frame within FRAME_SECONDS."""


class OutOfTimeError(CaptureError):
    """The call's time ran out."""


class Budget:
    """The time a call may spend, from when it is made. Each wait is capped at what is left."""

    def __init__(self, seconds: float, clock: Clock = time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._end = clock() + seconds

    def left(self) -> float:
        return max(0.0, self._end - self._clock())

    def out_of_time(self) -> OutOfTimeError:
        return OutOfTimeError(f"The {self.seconds:g} s this call may take ran out")


async def bounded(awaitable: Awaitable[T], seconds: float, budget: Budget | None) -> T:
    """`awaitable` within the shorter of `seconds` and what is left of `budget`.

    Its timeout is NoFrameError when `seconds` was the shorter bound, OutOfTimeError when the budget was. Either is
    raised outside the `except`, so it carries no chain back to the cancelled wait, whose frame holds Kit's
    subscription.
    """
    left = budget.left() if budget is not None else seconds
    if budget is not None and left <= 0:
        if isinstance(awaitable, Coroutine):
            awaitable.close()  # never started; closed, so Python doesn't warn that it was never awaited
        raise budget.out_of_time()
    cut_short = left < seconds
    try:
        return await asyncio.wait_for(awaitable, min(seconds, left))
    except TimeoutError:  # asyncio's, since 3.11
        pass
    if cut_short and budget is not None:
        raise budget.out_of_time()
    raise NoFrameError(
        f"The viewport rendered no frame in {seconds:g} s: its updates may be off, its window hidden, or Eco Mode "
        "paused a static scene"
    )


async def frames(
    next_frame: Callable[[], Awaitable[object]],
    count: int,
    budget: Budget | None = None,
    clock: Clock = time.monotonic,
) -> None:
    """`count` frames from `next_frame`, each within FRAME_SECONDS and what is left of `budget`.

    Without a budget they share one of FRAME_SECONDS, on `clock`, and the first frame is bounded by FRAME_SECONDS
    alone: the shared budget, made a moment before, would cut that wait short by the moment, and a viewport that
    renders nothing would be OutOfTimeError, not NoFrameError.
    """
    own = budget is None
    shared = Budget(FRAME_SECONDS, clock) if budget is None else budget
    for i in range(count):
        await bounded(next_frame(), FRAME_SECONDS, None if own and i == 0 else shared)


async def poll(
    read: Callable[[], T],
    ready: Callable[[T], bool],
    next_update: Callable[[], Awaitable[object]],
    seconds: float,
    budget: Budget | None = None,
    clock: Clock = time.monotonic,
) -> T | None:
    """The first `read()` that is `ready`, read now and after each update, for `seconds` or what is left of `budget`.

    None once the time is up.
    """
    limit = seconds if budget is None else min(seconds, budget.left())
    deadline = clock() + limit
    while True:
        value = read()
        if ready(value):
            return value
        if clock() >= deadline:
            return None
        await next_update()


class KitCapture(Protocol):
    """What capture_viewport_to_file returns: Kit's capture delegate."""

    def wait_for_result(self) -> Awaitable[object]: ...


class Png(NamedTuple):
    """A captured image, with how long its frame and its file took."""

    data: bytes
    frame_seconds: float
    file_seconds: float


async def capture_png(
    schedule: Callable[[], KitCapture | None],
    read_file: Callable[[], bytes],
    next_update: Callable[[], Awaitable[object]],
    budget: Budget | None = None,
    clock: Clock = time.monotonic,
) -> Png:
    """Schedule a capture, wait for its frame, then for its file to be a whole PNG.

    `schedule` starts Kit's capture into the file that `read_file` reads. A spent budget starts no capture. Kit
    gives None for a viewport without a render texture, and a result that names nothing captured when the frame had
    no colour output: no file will come for either, so each fails at once (#35) instead of after FILE_SECONDS.
    """
    if budget is not None and budget.left() <= 0:
        raise budget.out_of_time()
    started = clock()
    kit_capture = schedule()
    if kit_capture is None:
        raise CaptureError("The viewport has no render texture yet, so Kit can't capture it: capture again shortly")
    completed = await bounded(kit_capture.wait_for_result(), FRAME_SECONDS, budget)
    framed = clock()
    if not completed:
        raise CaptureError(f"Kit captured nothing (wait_for_result gave {completed!r})")

    def read() -> bytes:
        try:
            return read_file()
        except OSError:  # not there yet, or still open for writing on Windows
            return b""

    seconds = FILE_SECONDS
    cut_short = budget is not None and budget.left() < seconds
    data = await poll(read, is_complete_png, next_update, seconds, budget, clock)
    if data is None:
        if cut_short and budget is not None:
            raise budget.out_of_time()
        raise CaptureError(f"Kit wrote no whole image in {seconds:g} s after capturing {completed!r}")
    return Png(data, framed - started, clock() - framed)


class Call:
    """One inspect or capture call: its budget, and what stopped it.

    A NoFrameError or an OutOfTimeError stops the call, since the next angle would wait the same. Only its kind and
    message are kept, never the exception: its traceback would hold the cancelled frame wait, and Kit's subscription
    with it.
    """

    def __init__(self, seconds: float, clock: Clock = time.monotonic):
        self.budget = Budget(seconds, clock)
        self._stopped_by: str | None = None
        self._no_frame = False

    def failed(self, error: BaseException) -> None:
        """Note an error of an angle; the first NoFrameError or OutOfTimeError stops the call."""
        if self._stopped_by is None and isinstance(error, NoFrameError | OutOfTimeError):
            message = str(error)
            self._stopped_by = message[:1].lower() + message[1:]  # it follows "Not captured: "
            self._no_frame = isinstance(error, NoFrameError)

    def skipped(self, angle: str) -> dict[str, str] | None:
        """The entry of an angle not captured because the call stopped, or None while it runs."""
        if self._stopped_by is None:
            return None
        return {"angle": angle, "error": f"Not captured: {self._stopped_by}"}

    def settle_after_restore(self) -> bool:
        """Whether to wait for frames after isolate's prims are shown again: not after the viewport gave none."""
        return not self._no_frame


class SegmentationWaits:
    """Where a wait for instance segmentation ended with no data, so a capture there doesn't wait again.

    Kept per (stage id, render product path): Kit resets the sensor on every stage open, and a new or opened stage has
    a new id, so it waits afresh. A read with data clears the record.
    """

    def __init__(self) -> None:
        self._failed: set[Hashable] = set()

    def seconds(self, key: Hashable) -> float:
        return 0.0 if key in self._failed else SEGMENTATION_SECONDS

    def failed(self, key: Hashable) -> None:
        self._failed.add(key)

    def got_data(self, key: Hashable) -> None:
        self._failed.discard(key)
