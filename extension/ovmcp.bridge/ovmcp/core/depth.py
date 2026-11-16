"""A capture's depth (#203): omni.syntheticdata's distance to the camera, in metres, made the stage's units, a grey
image an agent reads and the raw distances a script reads. No Kit.

omni.syntheticdata's own tests read a cube n centimetre units away as (n - 1) / 100, so metres, and a pinhole's sky
as more than 1000, a fisheye's as inf (0.6.17's tests/sensors/test_distance_to_camera.py).
"""

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .png import encode_png

if TYPE_CHECKING:
    from numpy.typing import NDArray

# The farthest hit's grey, so it stays visible against nothing hit, which is black; the nearest is white.
GREY_FAR = 40
GREY_NEAR = 255


@dataclass(frozen=True)
class Depth:
    """A frame's depth: the grey PNG, the distances in stage units with inf where nothing is hit, the nearest and
    farthest hit (None when nothing is), and the share of the frame that hits nothing."""

    png: bytes
    distances: "NDArray[Any]"
    near: float | None
    far: float | None
    nothing_hit: float


def stage_distances(
    metres: "NDArray[Any]",
    meters_per_unit: float,
    ids: "NDArray[Any] | None" = None,
    far_clip: float | None = None,
) -> "NDArray[Any]":
    """The sensor's metres as stage units, inf where nothing is hit: where the same frame's segmentation id is 0 when
    there is one, as every capture takes segmentation; else where the value isn't finite, isn't positive, or is at or
    past `far_clip` (stage units), in case the sky reads large and finite."""
    import numpy as np

    if meters_per_unit <= 0:
        raise ValueError(f"metersPerUnit must be positive (got {meters_per_unit!r})")
    distances = np.asarray(metres, dtype=np.float32).reshape(np.shape(metres)[:2]) / np.float32(meters_per_unit)
    if ids is not None and np.shape(ids)[:2] == distances.shape:
        missed = np.asarray(ids).reshape(distances.shape) == 0
    else:
        missed = ~np.isfinite(distances) | (distances <= 0)
        if far_clip is not None:
            missed |= distances >= far_clip
    return np.where(missed, np.float32(np.inf), distances)


def depth_image(distances: "NDArray[Any]") -> Depth:
    """The grey image of stage_distances' result: linear in inverse distance from grey GREY_FAR at the farthest hit to
    white at the nearest, so a far floor doesn't squeeze what stands in front into a few greys; nothing hit black."""
    import numpy as np

    hit = np.isfinite(distances)
    total = distances.size
    nothing_hit = float(1 - np.count_nonzero(hit) / total) if total else 1.0
    grey = np.zeros(distances.shape, dtype=np.uint8)
    if not hit.any():
        return Depth(encode_png(grey), distances, None, None, nothing_hit)
    near = float(distances[hit].min())
    far = float(distances[hit].max())
    if far > near:
        inverse = 1.0 / distances[hit].astype(np.float64)
        scale = (inverse - 1.0 / far) / (1.0 / near - 1.0 / far)
        grey[hit] = np.round(GREY_FAR + scale * (GREY_NEAR - GREY_FAR)).astype(np.uint8)
    else:
        grey[hit] = GREY_NEAR
    return Depth(encode_png(grey), distances, near, far, nothing_hit)


def npy_bytes(distances: "NDArray[Any]") -> bytes:
    """The distances as a .npy file, float32, for a script's numpy.load."""
    import numpy as np

    buffer = io.BytesIO()
    np.save(buffer, np.asarray(distances, dtype=np.float32))
    return buffer.getvalue()
