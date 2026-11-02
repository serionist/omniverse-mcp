"""A camera rendered at a size into a texture of its own, read as the viewport reads its own (#25, #51).

The texture is Kit's public `omni.kit.hydra_texture.create_hydra_texture`; a frame is announced by its
drawable-changed event, and a capture delegate (`omni.kit.widget.viewport.capture.FileCapture`) queued on the feed is
handed that frame's outputs, as the viewport's own texture hands them to `capture_viewport_to_file`'s. The user's
viewport, its camera and its size never change, and no Replicator setting or timeline state is touched.

Kit writes the texture's render product into the stage's root and session layers and keeps it after the texture goes,
so `discard` deletes it, once the stage it is on is open (a new stage carries it over, #25's E13). A capture's feed
may carry instance segmentation too, which `release` lets go of before the render product goes (#51's E16).

inspect_prim and capture_viewport share one feed, kept between calls (`kept_feed`, `put_back`): Kit 110 can hang for
good during a new RTX view's first frames, and a feed made for each call made a view each call (#114).
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import carb
import omni.kit.app
import omni.usd

from ovmcp.core import capture
from ovmcp.core.recording import delete_render_product
from ovmcp.core.serial import LazyLock

from ._updates import on_update

# What one step of a feed's release may raise, from Kit's bindings or omni.syntheticdata's Python, so that step fails
# alone and the next ones still run.
_RELEASE_ERRORS = (RuntimeError, ValueError, AttributeError, KeyError, TypeError)

# How long a capture's feed is kept after its call with no other capture, before it is released (#114, Q2). Read as
# each call ends, so the unit tests can shorten it.
IDLE_SECONDS = 30.0

# How often a capture waiting for its frame looks whether its feed was let go meanwhile.
_LET_GO_SECONDS = 0.05

# Held for the whole of every handler that moves the viewport camera, hides prims or captures, so one request never
# sees another's half-done viewport, and by all that lets the kept feed go but the stage's events: its timer,
# release_kept, and the routes that write the stage to a file. Not re-entrant (ovmcp.core.serial): what runs holding
# it calls release, never these.
_viewport = LazyLock()


def _subscribe(texture: Any, on_frame: Callable[[int], None]) -> Any:
    """The texture's drawable-changed subscription, in the form this Kit has: Events 2.0 since Kit 108.2, an event
    stream before, as NVIDIA's own material preview tells them apart."""
    import omni.hydratexture

    if hasattr(omni.hydratexture, "GLOBAL_EVENT_DRAWABLE_CHANGED"):
        import carb.eventdispatcher

        return carb.eventdispatcher.get_eventdispatcher().observe_event(
            observer_name="ovmcp camera feed",
            event_name=omni.hydratexture.GLOBAL_EVENT_DRAWABLE_CHANGED,
            filter=texture.get_event_key(),
            on_event=lambda event: on_frame(event["result_handle"]),
        )
    return texture.get_event_stream().create_subscription_to_push_by_type(
        omni.hydratexture.EVENT_TYPE_DRAWABLE_CHANGED,
        lambda event: on_frame(event.payload["result_handle"]),
        name="ovmcp camera feed",
    )


class CameraFeed:
    """`camera_path` rendered at `width` x `height`, every update, until `drop`.

    It renders every update rather than only for a frame: a texture's first render after its updates come back on is
    about four times as far from a settled one as two settled ones are, under real-time path tracing (#25's E23).
    """

    def __init__(self, camera_path: str, width: int, height: int, prefix: str = "ovmcp_recording"):
        from omni.kit.hydra_texture import create_hydra_texture

        self.camera_path = camera_path
        self.width = width
        self.height = height
        # A name of its own: a session's id is the second it started in, which a forced restart can share.
        self.name = f"{prefix}_{uuid.uuid4().hex}"
        self.frames = 0
        # Whether instance segmentation was ever turned on for this feed, so its release frees its graphs; and whether
        # it is on now, so the call that turned it on, or the release, turns it off.
        self.segmented = False
        self.sensor_on = False
        self._pending: list[Any] = []
        # As Replicator makes its render products: rendered with the update, so a frame shows the update before the
        # one it was asked on, not three before as the viewport's does (#25's E17).
        self._texture: Any = create_hydra_texture(self.name, width, height, "", camera_path, "rtx", is_async=False)
        if self._texture is None:
            raise RuntimeError(f"Kit gave no texture to render {camera_path} with: is the RTX renderer loaded?")
        self.render_product_path: str = self._texture.get_render_product_path()
        self._subscription: Any = _subscribe(self._texture, self._on_frame)

    def _on_frame(self, result_handle: int) -> None:
        # Kit 110 calls this on its main thread (#25's E16); Kit 107's thread was never measured, so it does no USD
        # work and logs nothing (#5), only hands the frame to what waits for it.
        self.frames += 1
        texture = self._texture
        if not self._pending or texture is None:
            return
        delegates, self._pending = self._pending, []
        outputs = {aov["name"]: aov for aov in texture.get_aov_info(result_handle, include_texture=True)}
        info = texture.get_frame_info(result_handle)
        for delegate in delegates:
            delegate.capture(outputs, info, texture, result_handle)

    @property
    def resolution(self) -> tuple[int, int]:
        """The feed's size, read as omni.syntheticdata reads a viewport's (with `camera_path` and
        `render_product_path`), so its view parameters, projections and sensors take a feed as they take a viewport."""
        return self.width, self.height

    @property
    def waiting(self) -> bool:
        """Whether a capture still waits for its frame: one asked for now would get the same render (#25's E18)."""
        return bool(self._pending)

    def schedule(self, delegate: Any) -> Any:
        """Hands `delegate` the next frame; returns it, as the viewport's `schedule_capture` does."""
        self._check_rendering()
        self._pending.append(delegate)
        return delegate

    def _check_rendering(self) -> None:
        """A NoFrameError at once for a feed let go during a call, as a stage event or shutdown does with the kept one,
        rather than a wait of FRAME_SECONDS for a frame that can't come."""
        if self._texture is None:
            raise capture.NoFrameError(
                f"The feed rendering {self.camera_path} was let go during the call, as Kit closed or saved the stage: "
                "capture again"
            )

    def aim(self, camera_path: str, width: int, height: int) -> None:
        """Points the feed at `camera_path` at `width` x `height`, on the texture and on the feed, whose camera and size
        the boxes and segmentation read. A changed camera makes no new RTX view, a changed size one, on the same render
        product (#114's K5, K15); each is set only when it changed. Both sides in one go, as K5 measured."""
        texture = self._texture
        if camera_path != self.camera_path:
            texture.camera_path = camera_path
            self.camera_path = camera_path
        if (width, height) != (self.width, self.height):
            texture.width = width
            texture.height = height
            self.width, self.height = width, height

    def withdraw(self, delegate: Any) -> None:
        """Takes back a capture given up at its time bound, so it never writes into a file already deleted."""
        if delegate in self._pending:
            self._pending.remove(delegate)

    async def first_frame(self, seconds: float) -> None:
        """Waits for the feed's first frame; a NoFrameError when none comes in `seconds`, or at once when the feed is
        let go meanwhile."""
        app = omni.kit.app.get_app()

        def frames() -> int:
            self._check_rendering()
            return self.frames

        rendered = await capture.poll(frames, lambda n: n > 0, app.next_update_async, seconds)
        if rendered is None:
            raise capture.NoFrameError(f"The camera {self.camera_path} rendered no frame in {seconds:g} s")

    async def result_of(self, delegate: Any) -> Any:
        """`delegate.wait_for_result()`, for a capture this feed was handed: a NoFrameError at once when the feed is let
        go first, since `drop` takes back the captures still waiting, which then get no frame."""
        result = asyncio.ensure_future(delegate.wait_for_result())
        try:
            while not result.done():
                self._check_rendering()
                await asyncio.wait({result}, timeout=_LET_GO_SECONDS)
            return result.result()
        finally:
            if not result.done():
                result.cancel()

    async def next_frame(self) -> None:
        """Waits until the feed renders another frame, with no bound of its own: `wait_frames` bounds each."""
        app = omni.kit.app.get_app()
        start = self.frames
        while self.frames == start:
            self._check_rendering()
            await app.next_update_async()

    async def wait_frames(self, count: int, budget: capture.Budget | None = None) -> None:
        """`count` more of the feed's frames, each bounded as a viewport frame is (`capture.frames`): a NoFrameError
        naming the camera when one doesn't come, an OutOfTimeError when `budget` runs out first."""
        await capture.frames(self.next_frame, count, budget, source=f"The camera {self.camera_path}")

    def drop(self) -> None:
        """Stops the rendering and lets the texture go; its render product stays (`discard` deletes it). Safe twice."""
        self._subscription = None
        self._pending = []
        texture, self._texture = self._texture, None
        if texture is not None:
            texture.set_updates_enabled(False)

    def remove_render_product(self, stage: Any) -> bool:
        """Deletes the render product from every layer of `stage`, with Kit's entry for it in its render settings
        (core/recording.py), and says so; does nothing and says False while the stage isn't open, since a stage
        closing or opening is no place to edit."""
        if omni.usd.get_context().get_stage_state() != omni.usd.StageState.OPENED:
            return False
        delete_render_product(stage, self.render_product_path)
        carb.log_info(f"[MCP Bridge] Deleted the camera feed's render product {self.render_product_path}")
        return True


class _Leftovers:
    """Dropped feeds whose render products wait for an open stage to be deleted from, and the guard of the update
    observer that looks for one while any wait."""

    def __init__(self) -> None:
        self.feeds: list[CameraFeed] = []
        self.subscription: Any = None

    def add(self, feed: CameraFeed) -> None:
        self.feeds.append(feed)
        self.delete()
        if self.feeds and self.subscription is None:
            self.subscription = on_update("camera feed leftovers", self.delete)

    def delete(self) -> None:
        stage = omni.usd.get_context().get_stage()
        while self.feeds:
            # Off the list first: a deletion that fails is reported once by Kit, not retried on every update.
            feed = self.feeds.pop()
            if not feed.remove_render_product(stage):
                self.feeds.append(feed)
                break
        if not self.feeds:
            self.subscription = None

    def forget(self) -> None:
        self.feeds.clear()
        self.subscription = None


_leftovers = _Leftovers()


def discard(feed: CameraFeed) -> None:
    """Drops `feed` and deletes its render product from the stage open now, or from the next stage once it is open:
    after a new stage, Kit has carried the render product over to it (#25's E13)."""
    feed.drop()
    _leftovers.add(feed)


def enable_segmentation(feed: CameraFeed) -> str | None:
    """Turns instance segmentation on for `feed`; why it can't be, or None.

    Only where its graphs can be freed again: omni.syntheticdata keeps the graph it makes under the feed's render
    product in a registry, and one left there when the render product goes makes Kit log hundreds of errors a second
    until the next stage (#51's E16). The registry is private, so a Kit whose omni.syntheticdata has no such registry
    gets no segmentation rather than a leak.
    """
    try:
        import omni.syntheticdata as syn
        from omni.syntheticdata import SyntheticData
    except ImportError:
        return "omni.syntheticdata is not loaded: enable it with manage_extensions"
    registry = SyntheticData.Get()
    if registry is None or not hasattr(registry, "_nodeGraphs") or not hasattr(registry, "_reset_node_graph"):
        return "This Kit app's omni.syntheticdata can't free a capture's segmentation graphs, so none was taken"
    # Marked first: a sensor half made when this raises is still turned off and its graphs freed.
    feed.segmented = True
    feed.sensor_on = True
    syn.sensors.enable_sensors(feed, [syn._syntheticdata.SensorType.InstanceSegmentation])
    return None


def _release_errors() -> tuple[type[Exception], ...]:
    """_RELEASE_ERRORS, and omni.syntheticdata's own exception, which derives from Exception alone, where it loads."""
    try:
        from omni.syntheticdata import SyntheticDataException
    except ImportError:
        return _RELEASE_ERRORS
    return (*_RELEASE_ERRORS, SyntheticDataException)


def _release_step(what: str, step: Callable[[], object]) -> None:
    try:
        step()
    except _release_errors() as e:
        carb.log_warn(f"[MCP Bridge] Releasing a camera feed: {what} failed: {e}")


def _turn_segmentation_off(feed: CameraFeed) -> None:
    """Disables the feed's sensor, but not without a stage: omni.syntheticdata then raises rather than deactivates, and
    it has already reset its graphs as the stage closed. Its graphs stay, for the next call or the release."""
    import omni.syntheticdata as syn

    if omni.usd.get_context().get_stage() is not None:
        syn.sensors.disable_sensors(feed, [syn._syntheticdata.SensorType.InstanceSegmentation])
    feed.sensor_on = False


def _free_segmentation_graphs(feed: CameraFeed) -> None:
    """Pops each of omni.syntheticdata's graphs under the feed's render product from its registry and resets it, as
    Replicator's own render product teardown does, under the session layer, as omni.syntheticdata's own reset does."""
    from omni.syntheticdata import SyntheticData
    from pxr import Usd

    registry = SyntheticData.Get()
    graphs = registry._nodeGraphs
    prefix = feed.render_product_path.rstrip("/") + "/"
    stage = omni.usd.get_context().get_stage()
    for path in [path for path in graphs if path.startswith(prefix)]:
        graph = graphs.pop(path)
        if stage is not None:
            with Usd.EditContext(stage, stage.GetSessionLayer()):
                registry._reset_node_graph(graph)


async def release(feed: CameraFeed) -> None:
    """Lets a capture's feed go, in the order measured to leave nothing behind (#51's E16), each step on its own so one
    that fails doesn't keep the rest from running: its segmentation turned off, the feed dropped, the segmentation's
    graphs freed, two updates, then its render product deleted, now or once a stage is open (`discard`).

    Replicator also turns USD notice handling off around a deletion, for a render product made again at once; E16's
    teardown, without that, logged nothing and the next capture made its feed as usual, so it isn't copied here.

    Until its render product goes the feed is in `_releasing`, so Kit's Save during the two updates deletes it first
    (`_on_saving`).
    """
    _releasing.add(feed)
    try:
        try:
            _stop(feed)
        finally:
            app = omni.kit.app.get_app()
            for _ in range(2):
                await app.next_update_async()
    finally:
        # Even when the call is cancelled during the updates: its render product must not stay.
        _releasing.discard(feed)
        _leftovers.add(feed)


def _stop(feed: CameraFeed) -> None:
    """The steps of a feed's release before its render product goes: segmentation off, the feed dropped, its graphs
    freed. Even after an error no step expected, the next ones run, and the error rises after: a feed left rendering
    would carry its render product onto the next stage."""
    try:
        if feed.sensor_on:
            _release_step("turning segmentation off", lambda: _turn_segmentation_off(feed))
    finally:
        try:
            _release_step("dropping the feed", feed.drop)
        finally:
            if feed.segmented:
                _release_step("freeing the segmentation graphs", lambda: _free_segmentation_graphs(feed))


def _tear_down_at_once(feed: CameraFeed) -> None:
    """`release`'s steps with no update between them, for what can't wait for one: Kit's SAVING event and shutdown.
    Segmentation off, the feed dropped, its graphs freed, its render product deleted while a stage is open (else from
    the next open one, unless shutdown forgets it), whatever an earlier step raised. Measured quiet in #51's E16
    windows, a segmented feed's too: no error as it ran, 2 s after, at a save, a new stage, or a segmented viewport
    capture after (#114's step 1)."""
    try:
        _stop(feed)
    finally:
        _release_step("deleting its render product", lambda: _leftovers.add(feed))


# Feeds part way through `release`: stopped, their graphs freed, their render products not yet deleted.
_releasing: set[CameraFeed] = set()


class _Kept:
    """The capture feed kept between calls, the stage it was made on, and what lets it go (#114).

    Kit 110 can hang for good during a new RTX view's first frames, and a feed made for each call made a view each
    call; a kept feed whose camera changes makes none (#114's K4, K15). It goes after IDLE_SECONDS with no capture, when
    the stage closes, when Kit saves it, when a call leaves it in doubt, and at shutdown.
    """

    def __init__(self) -> None:
        self.feed: CameraFeed | None = None
        self.stage_id: object = None
        # Counts each time the feed was taken or let go, so an idle release that waited for the lock while a call took
        # the feed does nothing.
        self.generation = 0
        self.timer: asyncio.TimerHandle | None = None
        # The idle release's task, held so asyncio, which keeps only a weak reference, doesn't lose it.
        self.idle_release: asyncio.Future[None] | None = None
        self.stage_events: list[Any] = []

    def take(self) -> CameraFeed | None:
        """The kept feed, off the clock, for a call."""
        self._stop_timer()
        return self.feed

    def keep(self, feed: CameraFeed, stage_id: object) -> None:
        self.feed, self.stage_id = feed, stage_id

    def let_go(self) -> CameraFeed | None:
        """The kept feed, no longer kept or timed, for its caller to release."""
        self._stop_timer()
        feed, self.feed = self.feed, None
        return feed

    def start_timer(self) -> None:
        self.timer = asyncio.get_running_loop().call_later(IDLE_SECONDS, self._idle, self.generation)

    def _idle(self, generation: int) -> None:
        self.timer = None
        # A task of its own, as each handler is: the release waits for the lock and for Kit's updates.
        self.idle_release = asyncio.ensure_future(_release_idle(generation))

    def _stop_timer(self) -> None:
        self.generation += 1
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None


_kept = _Kept()


async def _release_idle(generation: int) -> None:
    async with _viewport.get():
        # Not when a call took the feed after the timer fired, or something else let it go.
        if _kept.generation == generation:
            await _release_kept()


def _on_closing(_event: Any) -> None:
    """The stage closing: the kept feed dropped at once, its render product deleted from the next stage once that is
    open, since Kit carries it over (discard). omni.syntheticdata resets its own graphs as the stage closes."""
    feed = _kept.let_go()
    if feed is not None:
        discard(feed)


def _on_saving(_event: Any) -> None:
    """Kit's own Save (File > Save, save_stage): the kept feed torn down before Kit writes the root layer, which holds
    its render product (#114's K11, Q7). The event is synchronous, so the teardown can't wait for release's updates.
    A feed part way through `release` has only its updates left, so its render product is deleted now too."""
    feed = _kept.let_go()
    if feed is not None:
        _tear_down_at_once(feed)
    stage = omni.usd.get_context().get_stage()
    for releasing in list(_releasing):
        _release_step("deleting its render product", lambda releasing=releasing: releasing.remove_render_product(stage))


def _observe_stage() -> None:
    """Observes the stage's CLOSING and SAVING, once, through Events 2.0, which Kit 107's omni.usd has too."""
    if _kept.stage_events:
        return
    import carb.eventdispatcher

    context = omni.usd.get_context()
    dispatcher = carb.eventdispatcher.get_eventdispatcher()
    _kept.stage_events = [
        dispatcher.observe_event(
            observer_name=f"ovmcp kept capture feed: {name}",
            event_name=context.stage_event_name(event),
            on_event=on_event,
        )
        for name, event, on_event in (
            ("closing", omni.usd.StageEventType.CLOSING, _on_closing),
            ("saving", omni.usd.StageEventType.SAVING, _on_saving),
        )
    ]


def kept_feed(camera_path: str, width: int, height: int) -> CameraFeed:
    """The feed a capture renders `camera_path` through at `width` x `height`, called holding _viewport: the kept one,
    pointed at the call's camera and size, or a new one, kept from now on; `put_back` hands it back. Any size is kept
    (#114's Q2). The caller waits for the frames it needs, a new feed's first among them."""
    _observe_stage()
    feed = _kept.take()
    stage_id = omni.usd.get_context().get_stage_id()
    if feed is not None and _kept.stage_id != stage_id:
        # Another stage, whose closing never reached us: Kit carried the render product over (#25's E13), so it goes
        # as on a closing stage.
        _kept.let_go()
        discard(feed)
        feed = None
    if feed is None:
        feed = CameraFeed(camera_path, width, height, prefix="ovmcp_capture")
        _kept.keep(feed, stage_id)
        return feed
    try:
        feed.aim(camera_path, width, height)
    except BaseException:
        # Half aimed, it would render one camera while the boxes say another: not kept.
        _kept.let_go()
        discard(feed)
        raise
    return feed


async def put_back(feed: CameraFeed, healthy: bool) -> None:
    """Hands back the feed of a call ending, holding _viewport, its segmentation off: kept for IDLE_SECONDS when
    `healthy`, released at once when not, so a stalled feed or a half-made sensor is never kept. A feed a stage event
    or shutdown let go during the call is left alone: it is torn down already."""
    if _kept.feed is not feed:
        return
    keep = False
    try:
        if healthy:
            if feed.sensor_on:
                # Off between calls: left on, a kept 640x480 feed's segmentation cut Kit's updates a second while idle
                # from 157 to 110 (#114's step 1, S1). Turning it off and on again makes no new view (K5).
                _turn_segmentation_off(feed)
            keep = True
    except _release_errors() as e:
        carb.log_warn(f"[MCP Bridge] A capture's feed is released: turning its segmentation off failed: {e}")
    finally:
        if keep:
            _kept.start_timer()
        else:
            _kept.let_go()
            await release(feed)


async def _release_kept() -> None:
    feed = _kept.let_go()
    if feed is not None:
        await release(feed)


async def release_kept() -> None:
    """Releases the kept feed now, if there is one, taking _viewport: for a live test, through execute_script, that
    compares the stage with no feed kept."""
    async with _viewport.get():
        await _release_kept()


@contextlib.asynccontextmanager
async def without_kept_feed() -> AsyncIterator[None]:
    """Holds _viewport with the kept feed released, for a route that writes the stage to a file: Kit keeps a feed's
    render product in the root layer (#114's K11), so it goes before the write, and no capture makes another before the
    write is done."""
    async with _viewport.get():
        await _release_kept()
        yield


def forget() -> None:
    """At the extension's shutdown: the kept feed torn down at once, its render product deleted while a stage is open,
    and the stage's events no longer observed. Render products waiting for an open stage are forgotten, since the stage
    may be tearing down."""
    feed = _kept.let_go()
    _kept.stage_events = []
    if feed is not None:
        _tear_down_at_once(feed)
    _leftovers.forget()
