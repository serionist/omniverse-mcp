"""A camera rendered at a size into a texture of its own, read as the viewport reads its own (#25, #51).

The texture is Kit's public `omni.kit.hydra_texture.create_hydra_texture`; a frame is announced by its
drawable-changed event, and a capture delegate (`omni.kit.widget.viewport.capture.FileCapture`) queued on the feed is
handed that frame's outputs, as the viewport's own texture hands them to `capture_viewport_to_file`'s. The user's
viewport, its camera and its size never change, and no Replicator setting or timeline state is touched.

Kit writes the texture's render product into the stage's root and session layers and keeps it after the texture goes,
so `discard` deletes it, once the stage it is on is open (a new stage carries it over, #25's E13). A capture's feed
may carry instance segmentation too, which `release` lets go of before the render product goes (#51's E16).
"""

import uuid
from collections.abc import Callable
from typing import Any

import carb
import omni.kit.app
import omni.usd

from ovmcp.core import capture
from ovmcp.core.recording import delete_render_product

# What one step of a feed's release may raise, from Kit's bindings or omni.syntheticdata's Python, so that step fails
# alone and the next ones still run.
_RELEASE_ERRORS = (RuntimeError, ValueError, AttributeError, KeyError, TypeError)


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
        # Whether instance segmentation was turned on for this feed, so its release turns it off and frees its graphs.
        self.segmented = False
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
        self._pending.append(delegate)
        return delegate

    def withdraw(self, delegate: Any) -> None:
        """Takes back a capture given up at its time bound, so it never writes into a file already deleted."""
        if delegate in self._pending:
            self._pending.remove(delegate)

    async def first_frame(self, seconds: float) -> None:
        """Waits for the feed's first frame; a NoFrameError when none comes in `seconds`."""
        app = omni.kit.app.get_app()
        rendered = await capture.poll(lambda: self.frames, lambda n: n > 0, app.next_update_async, seconds)
        if rendered is None:
            raise capture.NoFrameError(f"The camera {self.camera_path} rendered no frame in {seconds:g} s")

    async def next_frame(self) -> None:
        """Waits until the feed renders another frame, with no bound of its own: `wait_frames` bounds each."""
        app = omni.kit.app.get_app()
        start = self.frames
        while self.frames == start:
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
    """Dropped feeds whose render products wait for an open stage to be deleted from, and the update subscription that
    looks for one while any wait."""

    def __init__(self) -> None:
        self.feeds: list[CameraFeed] = []
        self.subscription: Any = None

    def add(self, feed: CameraFeed) -> None:
        self.feeds.append(feed)
        self.delete()
        if self.feeds and self.subscription is None:
            stream = omni.kit.app.get_app().get_update_event_stream()
            self.subscription = stream.create_subscription_to_pop(
                lambda _event: self.delete(), name="ovmcp camera feed leftovers"
            )

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


def forget() -> None:
    """At the extension's shutdown: deletes nothing, since the stage may be tearing down."""
    _leftovers.forget()


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
    # Marked first: a sensor half made when this raises is still released.
    feed.segmented = True
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
    it has already reset its graphs as the stage closed."""
    import omni.syntheticdata as syn

    if omni.usd.get_context().get_stage() is None:
        return
    syn.sensors.disable_sensors(feed, [syn._syntheticdata.SensorType.InstanceSegmentation])


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
    """
    try:
        if feed.segmented:
            _release_step("turning segmentation off", lambda: _turn_segmentation_off(feed))
    finally:
        # Even after an error no step expected: a feed left rendering would carry its render product onto the next
        # stage, and the call would answer with its error once the rest has run.
        try:
            _release_step("dropping the feed", feed.drop)
            if feed.segmented:
                _release_step("freeing the segmentation graphs", lambda: _free_segmentation_graphs(feed))
            app = omni.kit.app.get_app()
            for _ in range(2):
                await app.next_update_async()
        finally:
            # Even when the call is cancelled during the updates: its render product must not stay.
            _leftovers.add(feed)
