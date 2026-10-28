"""inspect_prim's camera: its arguments, its angles, and how far it stands so a prim fills the frame. No Kit."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

MARGIN_PX = 10

CORNER_ELEVATION = 35.26  # atan(1/sqrt(2)): from the horizontal up to a cube's corner

# The named angles, (azimuth, elevation) in degrees: the 6 face centres and the 8 corners of a cube around the prim.
ANGLES = {
    "front": (0, 0),
    "back": (180, 0),
    "right": (90, 0),
    "left": (270, 0),
    "top": (0, 90),
    "bottom": (0, -90),
    "top_front_right": (45, CORNER_ELEVATION),
    "top_front_left": (315, CORNER_ELEVATION),
    "top_back_right": (135, CORNER_ELEVATION),
    "top_back_left": (225, CORNER_ELEVATION),
    "bottom_front_right": (45, -CORNER_ELEVATION),
    "bottom_front_left": (315, -CORNER_ELEVATION),
    "bottom_back_right": (135, -CORNER_ELEVATION),
    "bottom_back_left": (225, -CORNER_ELEVATION),
}


@dataclass(frozen=True)
class InspectArgs:
    angles: list[tuple[str, float, float]]  # (name, azimuth, elevation)
    width: int
    height: int
    zoom_offset: float
    isolate: bool
    include_segmentation: bool


def inspect_args(body: dict[str, Any]) -> InspectArgs:
    """inspect_prim's request body, checked; the ValueError says what is wrong with it."""
    try:
        width = int(body.get("width", 800))
        height = int(body.get("height", 600))
        zoom_offset = float(body.get("zoom_offset", 0.0))
    except (TypeError, ValueError):
        raise ValueError("width and height must be whole numbers, and zoom_offset a number") from None
    if not math.isfinite(zoom_offset):
        raise ValueError(f"zoom_offset must be a finite number (got {zoom_offset})")
    return InspectArgs(
        angles=_angles(body.get("angles")),
        width=width,
        height=height,
        zoom_offset=zoom_offset,
        isolate=bool(body.get("isolate", False)),
        include_segmentation=bool(body.get("include_segmentation", False)),
    )


def _angles(angles: object) -> list[tuple[str, float, float]]:
    if angles is None or angles == ["all"]:
        return [(name, az, el) for name, (az, el) in ANGLES.items()]
    if not isinstance(angles, list):
        raise ValueError("angles must be a list of angle names or [azimuth, elevation] pairs")
    resolved: list[tuple[str, float, float]] = []
    for angle in cast("list[object]", angles):
        if isinstance(angle, str):
            if angle not in ANGLES:
                raise ValueError(f"Unknown angle {angle!r}; the named angles are: {', '.join(ANGLES)}")
            az, el = ANGLES[angle]
            resolved.append((angle, az, el))
        elif (pair := _pair(angle)) is not None:
            resolved.append((f"az{pair[0]}_el{pair[1]}", pair[0], pair[1]))
        else:
            raise ValueError(f"Each angle is a name or an [azimuth, elevation] pair of numbers (got {angle!r})")
    return resolved


def _pair(angle: object) -> tuple[float, float] | None:
    """An [azimuth, elevation] pair of finite numbers, as given (an int stays an int, for the angle's name)."""
    if not isinstance(angle, (list, tuple)):
        return None
    pair = cast("Sequence[object]", angle)
    if len(pair) != 2 or not all(_is_number(v) for v in pair):
        return None
    return cast("float", pair[0]), cast("float", pair[1])


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def require_perspective(projection: str, camera_path: str) -> None:
    """Moving an orthographic camera closer or further frames nothing; refuse it, saying what to do instead."""
    if projection == "orthographic":
        raise ValueError(
            f"The viewport camera {camera_path} is orthographic, so its distance frames nothing. Switch the viewport "
            "to a perspective camera such as /OmniverseKit_Persp and inspect again."
        )


def bounding_radius(dims: tuple[float, float, float] | list[float]) -> float:
    """Radius of the sphere around a bounding box of these dimensions; 0.5 for a box with no size."""
    radius = math.sqrt(sum(d * d for d in dims)) / 2
    return radius if radius >= 0.001 else 0.5


def fit_distance(
    radius: float,
    focal_length: float,
    horizontal_aperture: float,
    vertical_aperture: float,
    width: int,
    height: int,
    margin_px: int = MARGIN_PX,
) -> float:
    """Distance from a sphere's centre at which it fits the frame, `margin_px` inside every edge.

    `width` and `height` are the pixels actually captured. The renderer frames vertically either by the vertical
    aperture or by the horizontal aperture at the frame's aspect ratio; the narrower of the two is used, so the
    sphere fits whichever it is.
    """
    if width <= 2 * margin_px or height <= 2 * margin_px:
        raise ValueError(f"A {width}x{height} frame leaves no room inside a {margin_px}px margin")
    if focal_length <= 0 or horizontal_aperture <= 0:
        raise ValueError("The camera needs a positive focal length and horizontal aperture")

    tan_h = horizontal_aperture / (2 * focal_length)
    tan_v = tan_h * height / width
    if vertical_aperture > 0:
        tan_v = min(tan_v, vertical_aperture / (2 * focal_length))
    # The margin shrinks the usable image plane, not the angle.
    tan_h *= (width - 2 * margin_px) / width
    tan_v *= (height - 2 * margin_px) / height

    # A sphere of radius r at distance d subtends asin(r / d); it fits when that is at most the half-angle.
    return radius / math.sin(math.atan(min(tan_h, tan_v)))


def apply_zoom(distance: float, zoom_offset: float) -> float:
    """0 keeps the fit, -0.3 stands 30% closer, 0.5 stands 50% further."""
    if zoom_offset <= -1:
        raise ValueError(
            f"zoom_offset must be greater than -1 (got {zoom_offset}); -1 would put the camera at the prim's centre"
        )
    return distance * (1.0 + zoom_offset)
