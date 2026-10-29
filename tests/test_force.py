"""apply_force's request, its refusals and the point it pushes at (#25), without Kit."""

import math
import re

import pytest

from ovmcp.core.force import (
    ForceArgs,
    centre_of_mass,
    force_args,
    refusal,
    world_point,
)

IDENTITY = (0.0, 0.0, 0.0, 1.0)  # x, y, z, w, as PhysX gives a rotation
HALF = math.sqrt(0.5)


class Float3:
    """Stands for carb.Float3: indexable and sized, not a list or a tuple."""

    def __init__(self, *values: float):
        self._values = values

    def __getitem__(self, i: int) -> float:
        return self._values[i]

    def __len__(self) -> int:
        return len(self._values)


def test_force_args_take_a_force_and_default_the_rest():
    args = force_args({"prim_path": "/World/Box", "force": [10, 0, -2.5]})
    assert args == ForceArgs("/World/Box", (10.0, 0.0, -2.5), None, False)
    assert args.mode == "Force"


def test_force_args_take_a_position_and_an_impulse():
    args = force_args({"prim_path": "/World/Box", "force": [0, 0, 1], "position": (1, 2, 3), "impulse": True})
    assert args.position == (1.0, 2.0, 3.0)
    assert args.impulse
    assert args.mode == "Impulse"


def test_a_null_position_is_the_centre_of_mass():
    assert force_args({"prim_path": "/World/Box", "force": [1, 0, 0], "position": None}).position is None


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": "", "force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": 7, "force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": "/World/Box"}, "force [fx, fy, fz] is required"),
        ({"prim_path": "/World/Box", "force": [1, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": "100"}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": {"x": 1, "y": 0, "z": 0}}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": 100}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, "0", 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [True, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [math.nan, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [0, math.inf, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "position": [0, 0]}, "position must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "impulse": "yes"}, "impulse must be true or false"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "impulse": 1}, "impulse must be true or false"),
    ],
)
def test_force_args_refuse_what_physx_cant_take(body, says):
    with pytest.raises(ValueError, match="^" + re.escape(says)):
        force_args(body)


def test_a_stopped_timeline_is_refused_first():
    # Stopped, PhysX holds no bodies, so whether it holds this one says nothing.
    why = refusal("/World/Box", stopped=True, enabled=False, kinematic=True, held=False)
    assert why is not None
    assert why.startswith("The simulation is stopped")
    assert "paused works too" in why


def test_a_disabled_rigid_body_is_refused_before_a_kinematic_one():
    why = refusal("/World/Box", stopped=False, enabled=False, kinematic=True, held=True)
    assert why is not None
    assert why.startswith("/World/Box's rigid body is disabled (physics:rigidBodyEnabled is false)")
    assert "static body" in why


def test_a_kinematic_body_is_refused():
    why = refusal("/World/Box", stopped=False, enabled=True, kinematic=True, held=True)
    assert why is not None
    assert why.startswith("/World/Box is kinematic (physics:kinematicEnabled is true)")


def test_a_body_physx_doesnt_hold_is_refused():
    why = refusal("/World/Box", stopped=False, enabled=True, kinematic=False, held=False)
    assert why is not None
    assert why.startswith("PhysX holds no rigid body at /World/Box")


def test_a_body_physx_holds_while_it_plays_or_pauses_is_pushed():
    assert refusal("/World/Box", stopped=False, enabled=True, kinematic=False, held=True) is None


def test_the_centre_of_mass_comes_from_physx_s_mass_information():
    assert centre_of_mass({"mass": 5.0, "inertia": Float3(1, 1, 1), "com": Float3(0, 0, 0.25)}, "/B") == (0, 0, 0.25)


@pytest.mark.parametrize(
    "info",
    [
        {"mass": 0.0, "com": (0.0, 0.0, 0.0)},  # what PhysX gives for a body it hasn't parsed
        {"mass": -1.0, "com": (0.0, 0.0, 0.0)},
        {"com": (0.0, 0.0, 0.0)},
        {"mass": "5", "com": (0.0, 0.0, 0.0)},
        {"mass": 5.0},
        {"mass": 5.0, "com": None},
        {},
    ],
)
def test_no_mass_is_no_centre_of_mass(info):
    with pytest.raises(ValueError, match=r"^PhysX has no mass for /World/Box, so no centre of mass"):
        centre_of_mass(info, "/World/Box")


def test_a_centre_of_mass_that_isnt_three_numbers_is_an_error():
    with pytest.raises(ValueError, match="com must be 3 finite numbers"):
        centre_of_mass({"mass": 5.0, "com": (0.0, math.nan, 0.0)}, "/World/Box")


def test_no_rotation_and_no_translation_keeps_the_point():
    assert world_point((0, 0, 0), IDENTITY, (0.1, 0.2, 0.3)) == pytest.approx((0.1, 0.2, 0.3))


def test_the_body_s_position_moves_the_point():
    assert world_point(Float3(1, 2, 3), Float3(*IDENTITY), Float3(0, 0, 0.5)) == pytest.approx((1, 2, 3.5))


def test_a_quarter_turn_about_z_takes_x_to_y():
    # PhysX's order: x, y, z, then w.
    assert world_point((0, 0, 0), (0, 0, HALF, HALF), (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-12)


def test_a_quarter_turn_about_y_takes_x_to_minus_z():
    assert world_point((10, 0, 0), (0, HALF, 0, HALF), (1, 0, 0)) == pytest.approx((10, 0, -1), abs=1e-12)


def test_a_half_turn_about_x_takes_y_to_minus_y():
    assert world_point((0, 0, 0), (1, 0, 0, 0), (0, 2, 0)) == pytest.approx((0, -2, 0), abs=1e-12)


def test_a_rotation_that_isnt_a_unit_quaternion_is_normalised():
    assert world_point((0, 0, 0), (0, 0, 3, 3), (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-12)


@pytest.mark.parametrize(
    ("position", "rotation", "local", "says"),
    [
        ((0, 0, 0), (0, 0, 0, 0), (1, 0, 0), "rotation must be a quaternion"),
        ((0, 0, 0), (0, 0, 1), (1, 0, 0), "rotation must be 4 finite numbers"),
        ((0, 0), IDENTITY, (1, 0, 0), "position must be 3 finite numbers"),
        ((0, 0, 0), IDENTITY, None, "local must be 3 finite numbers"),
    ],
)
def test_a_pose_that_isnt_one_is_an_error(position, rotation, local, says):
    with pytest.raises(ValueError, match=says):
        world_point(position, rotation, local)
