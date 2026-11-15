"""The prim create_robot names for a robot or its USD file (#40), and where /robot/joint_states finds a robot's
articulation (#50). Without Kit. Where a file loads from is tests/test_usd_files.py's; the turn and the scale that bring
a file to the stage are tests/test_metrics.py's."""

import pytest
from pxr import Usd, UsdGeom, UsdPhysics

from ovmcp.core.robot import (
    ARTICULATION,
    BODY,
    articulation_root,
    from_usd_gain,
    is_usd_file,
    observed_kinds,
    robot_prim_path,
    to_usd_gain,
    tracking_errors,
)


@pytest.mark.parametrize(
    ("robot_type", "prim"),
    [
        ("franka", "/World/Franka"),
        ("g1", "/World/G1"),
        ("/home/me/Robots/MyBot.usd", "/World/MyBot"),
        (r"C:\Robots\My Bot-2.usda", "/World/My_Bot_2"),
        ("omniverse://server/Robots/2Arm.USD", "/World/_Arm"),
    ],
)
def test_a_robot_s_prim_is_named_after_it(robot_type: str, prim: str):
    assert robot_prim_path(robot_type) == prim


def test_a_usd_file_is_told_from_a_robot_s_name():
    assert is_usd_file("/home/me/Bot.USDA")
    assert is_usd_file("scene.usdz")
    assert not is_usd_file("franka")


# ----- The articulation root -----


@pytest.fixture
def robots() -> Usd.Stage:
    """/World/Arm has its root on itself; /World/Biped on /World/Biped/pelvis, after a link without one; /World/Copy is
    an instance of /Prototypes/Biped, whose root is only an instance proxy on the stage; /World/Table has none."""
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Arm").GetPrim())
    for biped in ("/World/Biped", "/Prototypes/Biped"):
        UsdGeom.Xform.Define(stage, biped)
        UsdGeom.Xform.Define(stage, f"{biped}/base")
        UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, f"{biped}/pelvis").GetPrim())
        UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, f"{biped}/pelvis/hand").GetPrim())
    copy = UsdGeom.Xform.Define(stage, "/World/Copy").GetPrim()
    copy.GetReferences().AddInternalReference("/Prototypes/Biped")
    copy.SetInstanceable(True)
    assert stage.GetPrimAtPath("/World/Copy/pelvis").IsInstanceProxy()
    UsdGeom.Cube.Define(stage, "/World/Table")
    return stage


@pytest.mark.parametrize(
    ("prim", "root"),
    [
        ("/World/Arm", "/World/Arm"),
        ("/World/Biped", "/World/Biped/pelvis"),
        ("/World/Biped/pelvis/hand", "/World/Biped/pelvis/hand"),
        ("/World/Copy", "/World/Copy/pelvis"),
        ("/World/Table", None),
    ],
)
def test_the_articulation_root_at_or_under_a_prim(robots: Usd.Stage, prim: str, root: str | None):
    assert articulation_root(robots.GetPrimAtPath(prim)) == root


# ----- What a stepped read gives of a prim (#198) -----


def test_a_stepped_read_tells_a_body_a_robot_both_and_neither(robots: Usd.Stage):
    # The G1's pelvis is a rigid body and the articulation's root at once; the read gives it both.
    pelvis = robots.GetPrimAtPath("/World/Biped/pelvis")
    UsdPhysics.RigidBodyAPI.Apply(pelvis)
    UsdPhysics.RigidBodyAPI.Apply(robots.GetPrimAtPath("/World/Table"))
    UsdGeom.Xform.Define(robots, "/World/Light")
    assert observed_kinds(robots.GetPrimAtPath("/World/Table")) == {BODY}
    assert observed_kinds(robots.GetPrimAtPath("/World/Arm")) == {ARTICULATION}
    assert observed_kinds(robots.GetPrimAtPath("/World/Biped")) == {ARTICULATION}
    assert observed_kinds(pelvis) == {BODY, ARTICULATION}
    assert observed_kinds(robots.GetPrimAtPath("/World/Light")) == set()


# ----- drive gains (#199) -----


def test_an_angular_gain_is_per_radian_in_physics_and_per_degree_in_usd():
    # Isaac Sim's own reading of a Franka: USD 400 per degree is 22918.31 per radian.
    assert from_usd_gain(400.0, angular=True) == pytest.approx(22918.31, abs=0.01)
    assert to_usd_gain(22918.31, angular=True) == pytest.approx(400.0, abs=1e-3)


@pytest.mark.parametrize(("value", "angular"), [(1000.0, True), (5.5, True), (1000.0, False), (0.0, True)])
def test_a_gain_goes_to_usd_and_back_unchanged(value: float, angular: bool):
    assert from_usd_gain(to_usd_gain(value, angular), angular) == pytest.approx(value)


def test_a_linear_gain_is_the_same_in_both():
    assert to_usd_gain(250.0, angular=False) == from_usd_gain(250.0, angular=False) == 250.0


def test_the_tracking_error_is_the_target_s_less_the_position_where_a_position_drive_acts():
    # The second is a velocity-driven wheel (stiffness 0): no position target pulls it.
    assert tracking_errors([0.25, 312.4, -1.0], [0.5, 0.0, -0.5], [57295.8, 0.0, 10.0]) == [0.25, None, 0.5]
