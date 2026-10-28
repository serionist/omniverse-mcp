"""World bounds on usd-core, and the screen outline of a projected box: what get_prim_bounds and capture report."""

import pytest
from pxr import Gf, Usd, UsdGeom

from ovmcp.core.bounds import box_corners, center_and_size, screen_box, world_bbox


@pytest.fixture
def stage():
    return Usd.Stage.CreateInMemory()


def test_a_cube_has_its_world_box(stage):
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.CreateSizeAttr(2.0)
    UsdGeom.Xformable(cube).AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
    UsdGeom.Xformable(cube).AddScaleOp().Set(Gf.Vec3f(1, 2, 0.5))

    center, dims, corners = world_bbox(cube.GetPrim())

    assert center == pytest.approx([1, 2, 3])
    assert dims == pytest.approx([2, 4, 1])
    assert corners == [pytest.approx([0, 0, 2.5]), pytest.approx([2, 4, 3.5])]


def test_a_prim_with_no_extent_gets_its_position_and_a_small_box(stage):
    xform = UsdGeom.Xform.Define(stage, "/World/Empty")
    xform.AddTranslateOp().Set(Gf.Vec3d(-4, 0.5, 9))

    assert world_bbox(xform.GetPrim()) == ([-4, 0.5, 9], [0.1, 0.1, 0.1], [[-4, 0.5, 9], [-4, 0.5, 9]])


def test_a_prim_with_no_transform_gets_the_origin(stage):
    prim = stage.DefinePrim("/World/Typeless")

    assert world_bbox(prim) == ([0.0, 0.0, 0.0], [0.1, 0.1, 0.1], [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])


def test_center_and_size_take_gf_vectors_and_lists():
    assert center_and_size(Gf.Vec3d(-1, 0, 2), [3, 4, 2]) == ([1.0, 2.0, 2.0], [4.0, 4.0, 0.0])


def test_the_corners_follow_the_index_bits():
    corners = box_corners([0, 10, 100], [1, 11, 101])

    assert len(corners) == 8
    for i, (x, y, z) in enumerate(corners):
        assert (x, y, z) == (1 if i & 1 else 0, 11 if i & 2 else 10, 101 if i & 4 else 100)


# A 1000 x 500 viewport, captured as a 500 x 250 image: every pixel halves.
VIEWPORT, IMAGE = (1000, 500), (500, 250)


def test_an_outline_on_screen_is_scaled_to_the_image():
    points = [[0.1, 0.2, 0.5], [0.3, 0.6, 0.5], [0.2, 0.4, 0.9]]

    assert screen_box(points, VIEWPORT, IMAGE) == [50.0, 50.0, 150.0, 150.0]


def test_an_outline_partly_off_screen_is_clamped_to_the_viewport():
    points = [[-0.5, -0.1, 1], [0.5, 1.4, 1]]

    assert screen_box(points, VIEWPORT, IMAGE) == [0.0, 0.0, 250.0, 250.0]


@pytest.mark.parametrize(
    "points",
    [
        [[-0.4, 0.5, 1], [-0.1, 0.6, 1]],  # left
        [[1.1, 0.5, 1], [1.4, 0.6, 1]],  # right
        [[0.5, -0.4, 1], [0.6, -0.1, 1]],  # above
        [[0.5, 1.1, 1], [0.6, 1.4, 1]],  # below
    ],
    ids=["left", "right", "above", "below"],
)
def test_an_outline_wholly_off_screen_is_none(points):
    assert screen_box(points, VIEWPORT, IMAGE) is None


def test_the_outline_is_rounded_to_a_tenth_of_a_pixel():
    assert screen_box([[0.12345, 0.0, 1], [0.98765, 1.0, 1]], (1000, 1000), (1000, 1000)) == [123.5, 0.0, 987.6, 1000.0]
