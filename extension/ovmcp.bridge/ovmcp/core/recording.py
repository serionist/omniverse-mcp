"""What start_recording accepts, when a recording takes its frames, and how the render product of a recording's camera
feed leaves the stage.

A recording renders its camera at its size into a texture of its own (handlers/camera_feed.py), so the user's viewport
never moves (#25). No Kit imports: the handler passes in the stage and Kit's answers, so the tests run all of this on
usd-core.
"""

from collections.abc import Mapping
from typing import NamedTuple, cast

from pxr import Sdf, Usd, UsdGeom

from .capture import frame_size
from .usd import is_a, prim_spec, relationship_spec, remove_child_spec

DEFAULT_FPS = 5
DEFAULT_SIZE = (640, 480)

# Frames whose files are still being written. A frame takes about four app updates, most of them after its render, so
# one at a time halved fps=30 (#25's E15); four leave room for that, and still bound the waits a stalled feed starts.
MAX_IN_FLIGHT = 4

# Kit lists every texture's render product in its render settings, in the root layer, and leaves the entry there when
# the prim goes (#25's E22).
RENDER_SETTINGS_PRODUCTS = Sdf.Path("/Render/OmniverseGlobalRenderSettings.products")


class RecordingArgs(NamedTuple):
    output_dir: str
    fps: int
    width: int
    height: int
    camera_path: str
    track_prims: list[str]
    property_filter: list[str] | None


def _strings(name: str, value: object) -> list[str] | None:
    if value is None:
        return None
    items = list(cast("list[object]", value)) if isinstance(value, list) else None
    if items is None or not all(isinstance(v, str) for v in items):
        raise ValueError(f"{name} must be a list of strings, got {value!r}")
    return [v for v in items if isinstance(v, str)]


def recording_args(body: Mapping[str, object]) -> RecordingArgs:
    """A start request's values, checked. A ValueError says what is wrong; nothing has been made then."""
    output_dir = body.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir:
        raise ValueError("output_dir is required")
    fps = body.get("fps", DEFAULT_FPS)
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1:
        raise ValueError(f"fps must be a whole number of at least 1, got {fps!r}")
    width, height = frame_size(body.get("width", DEFAULT_SIZE[0]), body.get("height", DEFAULT_SIZE[1]))
    camera_path = body.get("camera_path", "")
    if not isinstance(camera_path, str):
        raise ValueError(f"camera_path must be a prim path, got {camera_path!r}")
    return RecordingArgs(
        output_dir,
        fps,
        width,
        height,
        camera_path,
        _strings("track_prims", body.get("track_prims")) or [],
        _strings("property_filter", body.get("property_filter")),
    )


def steps_per_frame(time_codes_per_second: float, fps: int) -> int:
    """App updates between frames: a stage of 60 time codes a second, recorded at 5 frames a second, takes one in 12."""
    return max(1, int(time_codes_per_second / fps))


def camera_error(stage: Usd.Stage, path: str) -> str | None:
    """Why `path` can't be recorded from, or None when it is a camera on `stage`."""
    if not Sdf.Path.IsValidPathString(path) or not Sdf.Path(path).IsAbsolutePath():
        return f"camera_path must be an absolute prim path, such as /World/Camera, got {path!r}"
    prim = stage.GetPrimAtPath(path)
    if not prim.IsValid():
        return f"No prim at {path}: camera_path must name a camera. Use get_scene_tree() to see available prims."
    if not is_a(prim, UsdGeom.Camera):
        return f"{path} is a {prim.GetTypeName() or 'typeless'} prim, not a Camera: camera_path must name a camera"
    return None


class FrameClock:
    """Which app updates take a frame, and the frame's number.

    Every `steps`-th update takes one, unless the feed still awaits the last one's render, which would give two frames
    the same render (#25's E18), or MAX_IN_FLIGHT frames are still being written. Numbers are given when a frame is
    taken, so frames whose captures end out of order keep theirs, and none is used twice (#69).
    """

    def __init__(self, steps: int, max_in_flight: int = MAX_IN_FLIGHT):
        self._steps = steps
        self._max_in_flight = max_in_flight
        self._updates = 0
        self._next = 0
        self.in_flight = 0

    def tick(self, render_pending: bool = False) -> int | None:
        """This update's frame number, or None when it takes none."""
        self._updates += 1
        if self._updates % self._steps or render_pending or self.in_flight >= self._max_in_flight:
            return None
        number = self._next
        self._next += 1
        self.in_flight += 1
        return number

    def done(self) -> None:
        """A frame's file is written, or given up."""
        self.in_flight = max(0, self.in_flight - 1)

    @property
    def taken(self) -> int:
        return self._next


def delete_render_product(stage: Usd.Stage, path: str) -> None:
    """Deletes a texture's render product from every layer of `stage` that holds a spec of it, and its entry in Kit's
    render settings: Kit writes the prim into the root layer and the session layer, whatever the edit target (#25's
    E12), and the prim outlives the texture."""
    product = Sdf.Path(path)
    for layer in stage.GetLayerStack(includeSessionLayers=True):
        products = relationship_spec(layer, RENDER_SETTINGS_PRODUCTS)
        if products is not None and products.targetPathList.ContainsItemEdit(product):
            products.targetPathList.RemoveItemEdits(product)
        parent = prim_spec(layer, product.GetParentPath())
        if parent is not None and prim_spec(layer, product) is not None:
            remove_child_spec(parent, product.name)
