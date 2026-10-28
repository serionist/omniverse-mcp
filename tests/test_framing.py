"""inspect_prim's framing maths: the fitted sphere stays inside the frame, margins included."""

import math

import pytest
from ovmcp.core.framing import (
    ANGLES,
    MARGIN_PX,
    apply_zoom,
    bounding_radius,
    fit_distance,
    inspect_args,
    require_perspective,
)

# Kit's default perspective camera.
FOCAL, H_AP, V_AP = 18.14756, 20.955, 15.2908


def _projected_half_extent_px(radius, distance, tan_half_fov, pixels):
    """Half the size, in pixels, of the sphere's outline on the image plane, for a frame `pixels` wide."""
    half_angle = math.asin(radius / distance)
    return math.tan(half_angle) / tan_half_fov * pixels / 2


@pytest.mark.parametrize(("width", "height"), [(1280, 720), (640, 480), (800, 600), (720, 1280), (512, 512)])
def test_the_sphere_fits_inside_the_margins_both_ways(width, height):
    radius = 1.0
    d = fit_distance(radius, FOCAL, H_AP, V_AP, width, height)
    tan_h = H_AP / (2 * FOCAL)
    tan_v = min(tan_h * height / width, V_AP / (2 * FOCAL))
    assert _projected_half_extent_px(radius, d, tan_h, width) <= width / 2 - MARGIN_PX + 1e-6
    assert _projected_half_extent_px(radius, d, tan_v, height) <= height / 2 - MARGIN_PX + 1e-6


def test_the_tighter_side_touches_its_margin():
    radius, width, height = 1.0, 1280, 720
    d = fit_distance(radius, FOCAL, H_AP, V_AP, width, height)
    tan_v = min(H_AP / (2 * FOCAL) * height / width, V_AP / (2 * FOCAL))
    assert _projected_half_extent_px(radius, d, tan_v, height) == pytest.approx(height / 2 - MARGIN_PX)


def test_a_wide_frame_frames_by_its_aspect_not_the_vertical_aperture():
    # 1280x720 is wider than the default apertures' 1.37:1, so the vertical aperture would overstate the height.
    wide = fit_distance(1.0, FOCAL, H_AP, V_AP, 1280, 720)
    by_aperture_only = 1.0 / math.sin(math.atan(V_AP / (2 * FOCAL) * (720 - 2 * MARGIN_PX) / 720))
    assert wide > by_aperture_only


def test_sine_not_tangent():
    d = fit_distance(1.0, FOCAL, H_AP, 0.0, 1000, 1000, margin_px=0)
    half = math.atan(H_AP / (2 * FOCAL))
    assert d == pytest.approx(1.0 / math.sin(half))
    assert d > 1.0 / math.tan(half)


def test_distance_scales_with_the_radius():
    assert fit_distance(2.0, FOCAL, H_AP, V_AP, 800, 600) == pytest.approx(
        2 * fit_distance(1.0, FOCAL, H_AP, V_AP, 800, 600)
    )


@pytest.mark.parametrize(("width", "height"), [(20, 600), (800, 20), (16, 16), (0, 0)])
def test_a_frame_with_no_room_inside_the_margins_is_refused(width, height):
    with pytest.raises(ValueError, match="no room"):
        fit_distance(1.0, FOCAL, H_AP, V_AP, width, height)


def test_a_camera_without_a_focal_length_is_refused():
    with pytest.raises(ValueError, match="focal length"):
        fit_distance(1.0, 0.0, H_AP, V_AP, 800, 600)


@pytest.mark.parametrize(("zoom", "factor"), [(0.0, 1.0), (-0.3, 0.7), (0.5, 1.5)])
def test_zoom(zoom, factor):
    assert apply_zoom(10.0, zoom) == pytest.approx(10.0 * factor)


@pytest.mark.parametrize("zoom", [-1.0, -1.5])
def test_zoom_into_the_prim_is_refused(zoom):
    with pytest.raises(ValueError, match="greater than -1"):
        apply_zoom(10.0, zoom)


def test_bounding_radius():
    assert bounding_radius((2.0, 2.0, 1.0)) == pytest.approx(1.5)
    assert bounding_radius((0.0, 0.0, 0.0)) == 0.5


def test_inspect_args_defaults():
    args = inspect_args({"prim_path": "/World/Box"})
    assert (args.width, args.height, args.zoom_offset, args.isolate, args.include_segmentation) == (
        800,
        600,
        0.0,
        False,
        False,
    )
    assert [name for name, _, _ in args.angles] == list(ANGLES)


def test_inspect_args_take_names_pairs_and_numeric_strings():
    args = inspect_args({"angles": ["front", [30, 15]], "width": "1280", "height": 720.0, "zoom_offset": "-0.25"})
    assert args.angles == [("front", 0, 0), ("az30_el15", 30, 15)]
    assert (args.width, args.height, args.zoom_offset) == (1280, 720, -0.25)


@pytest.mark.parametrize(
    "body",
    [
        {"zoom_offset": "closer"},
        {"zoom_offset": None},
        {"zoom_offset": [1]},
        {"width": "wide"},
        {"height": {"px": 600}},
        {"zoom_offset": float("nan")},
        {"zoom_offset": float("inf")},
        {"angles": "front"},
        {"angles": ["frnot"]},
        {"angles": [[30]]},
        {"angles": [[30, "up"]]},
        {"angles": [[True, 0]]},
        {"angles": [7]},
    ],
)
def test_bad_inspect_args_are_a_value_error_not_a_type_error(body):
    with pytest.raises(ValueError):
        inspect_args(body)


def test_an_orthographic_camera_is_refused_with_what_to_do():
    with pytest.raises(ValueError, match="/OmniverseKit_Top is orthographic.*/OmniverseKit_Persp"):
        require_perspective("orthographic", "/OmniverseKit_Top")
    require_perspective("perspective", "/OmniverseKit_Persp")
