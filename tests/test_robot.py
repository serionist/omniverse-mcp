"""The prim create_robot names for a robot or its USD file (#40); where /robot/joint_states finds a robot's articulation
(#50). Without Kit. Where a file loads from is tests/test_usd_files.py's."""

import pytest
from pxr import Usd, UsdGeom, UsdPhysics

from ovmcp.core.robot import articulation_root, is_usd_file, robot_prim_path


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
