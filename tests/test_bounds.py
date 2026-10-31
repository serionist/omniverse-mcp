"""World bounds on usd-core, and the screen outline of a projected box: what get_prim_bounds and capture report."""

import pytest
from pxr import Gf, Usd, UsdGeom

from ovmcp.core.bounds import box_corners, center_and_size, project_in_front, screen_box, world_bbox


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


# Kit's pinhole projection as omni.syntheticdata's get_projection_matrix builds it, for a camera at the origin looking
# down -z with a 90 degree field of view, a square image and a near plane at 1: [x, y, z, 1] times it gives
# [-x, y, ..., z], so w is the view-space z and a point in front has w < 0.
NEAR, FAR = 1.0, 100.0
PROJECTION = [
    [-1.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, FAR / (FAR - NEAR), 1.0],
    [0.0, 0.0, NEAR * FAR / (FAR - NEAR), 0.0],
]
SQUARE = (1000, 1000)


def _clip(min_pt: list[float], max_pt: list[float]) -> list[list[float]]:
    return [
        [sum([*corner, 1.0][r] * PROJECTION[r][k] for r in range(4)) for k in range(4)]
        for corner in box_corners(min_pt, max_pt)
    ]


def test_a_box_in_front_projects_as_kits_projection_does():
    points = project_in_front(_clip([1, -1, -10], [3, 1, -5]), NEAR)

    # Kit's project_pinhole: x / w and y / w, mapped from -1..1 to 0..1, so right is a larger x and down a larger y.
    assert len(points) == 8
    assert points[0] == pytest.approx([0.5 * (-1 / -10 + 1), 0.5 * (-1 / -10 + 1)])
    assert screen_box(points, SQUARE, SQUARE) == [550.0, 400.0, 800.0, 600.0]


def test_a_box_behind_the_camera_has_no_points():
    # Divided by its positive w, it lands mirrored near the middle of the screen, as #90 saw live.
    assert project_in_front(_clip([1, -1, 2], [3, 1, 4]), NEAR) == []


def test_a_box_across_the_camera_plane_is_bounded_by_its_part_in_front():
    # The corners behind would put the box's left edge at 200, mirrored; the part in front starts at 550 and runs off
    # the right edge, where the near plane cuts it.
    points = project_in_front(_clip([1, -1, -10], [3, 1, 5]), NEAR)

    assert len(points) == 4 + 4  # the corners in front and the 4 edges along z, cut at the near plane
    assert screen_box(points, SQUARE, SQUARE) == [550.0, 0.0, 1000.0, 1000.0]


def test_a_near_plane_at_the_eye_divides_no_corner_by_zero():
    # A camera's clippingRange can start at 0; a box reaching the eye then has corners at w = 0.
    points = project_in_front(_clip([-1, -1, -10], [1, 1, 0]), 0.0)

    assert screen_box(points, SQUARE, SQUARE) == [0.0, 0.0, 1000.0, 1000.0]
