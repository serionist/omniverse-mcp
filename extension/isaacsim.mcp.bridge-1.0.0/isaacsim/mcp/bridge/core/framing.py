"""How far inspect_prim's camera stands so a prim fills the frame: plain maths, no Kit."""

import math

MARGIN_PX = 10


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
        raise ValueError(f"zoom_offset must be greater than -1 (got {zoom_offset}); -1 would put the camera at the "
                         "prim's centre")
    return distance * (1.0 + zoom_offset)
