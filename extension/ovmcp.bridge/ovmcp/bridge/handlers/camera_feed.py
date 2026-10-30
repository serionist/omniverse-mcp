"""A camera rendered at a size into a texture of its own, read as the viewport reads its own (#25).

The texture is Kit's public `omni.kit.hydra_texture.create_hydra_texture`; a frame is announced by its
drawable-changed event, and a capture delegate (`omni.kit.widget.viewport.capture.FileCapture`) queued on the feed is
handed that frame's outputs, as the viewport's own texture hands them to `capture_viewport_to_file`'s. The user's
viewport, its camera and its size never change, and no Replicator setting or timeline state is touched.

Kit writes the texture's render product into the stage's root and session layers and keeps it after the texture goes,
so `discard` deletes it, once the stage it is on is open (a new stage carries it over, #25's E13).
"""

import uuid
from collections.abc import Callable
from typing import Any

import carb
import omni.kit.app
import omni.usd

from ovmcp.core import capture
from ovmcp.core.recording import delete_render_product


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

    def drop(self) -> None:
        """Stops the rendering and lets the texture go; its render product stays (`discard` deletes it). Safe twice."""
        self._subscription = None
        self._pending = []
        texture, self._texture = self._texture, None
        if texture is not None:
            texture.set_updates_enabled(False)


class _Leftovers:
    """Render products of dropped feeds waiting for an open stage to be deleted from, and the update subscription that
    looks for one while any wait."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.subscription: Any = None

    def add(self, path: str) -> None:
        self.paths.append(path)
        self.delete()
        if self.paths and self.subscription is None:
            stream = omni.kit.app.get_app().get_update_event_stream()
            self.subscription = stream.create_subscription_to_pop(
                lambda _event: self.delete(), name="ovmcp camera feed leftovers"
            )

    def delete(self) -> None:
        context = omni.usd.get_context()
        if context.get_stage_state() == omni.usd.StageState.OPENED:
            stage = context.get_stage()
            while self.paths:
                # Off the list first: a deletion that fails is reported once by Kit, not retried on every update.
                path = self.paths.pop()
                delete_render_product(stage, path)
                carb.log_info(f"[MCP Bridge] Deleted the camera feed's render product {path}")
        if not self.paths:
            self.subscription = None

    def forget(self) -> None:
        self.paths.clear()
        self.subscription = None


_leftovers = _Leftovers()


def discard(feed: CameraFeed) -> None:
    """Drops `feed` and deletes its render product from the stage open now, or from the next stage once it is open."""
    feed.drop()
    _leftovers.add(feed.render_product_path)


def forget() -> None:
    """At the extension's shutdown: deletes nothing, since the stage may be tearing down."""
    _leftovers.forget()
