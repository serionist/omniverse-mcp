"""The prim create_robot names for a robot or its USD file (#40); where /robot/joint_states finds a robot's articulation
(#50). Without Kit. Where a file loads from is tests/test_usd_files.py's."""

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.robot import (
    UP_AXIS_OP,
    articulation_root,
    file_up_axis,
    is_usd_file,
    robot_prim_path,
    stand_upright,
    up_axis_turn,
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


# ---- standing a file of another up axis on the stage (#105) ----


def _layer(up_axis: str | None) -> Sdf.Layer:
    layer = Sdf.Layer.CreateAnonymous("bot.usda")
    if up_axis is not None:
        layer.pseudoRoot.SetInfo("upAxis", up_axis)
    return layer


@pytest.mark.parametrize(
    ("file_axis", "stage_axis", "degrees"),
    [("Z", "Y", -90.0), ("Y", "Z", 90.0), ("Z", "Z", None), ("Y", "Y", None), (None, "Y", None), (None, "Z", None)],
)
def test_the_turn_that_stands_a_file_on_the_stage(file_axis: str | None, stage_axis: str, degrees: float | None):
    # Kit's metrics assembler turns a Z-up file on a Y-up stage by -90 about X; a file that doesn't say is left alone.
    assert file_up_axis(_layer(file_axis)) == file_axis
    assert up_axis_turn(file_up_axis(_layer(file_axis)), stage_axis) == degrees


@pytest.fixture
def stage() -> Usd.Stage:
    return Usd.Stage.CreateInMemory()


def _prim(stage: Usd.Stage, ops: list[str]) -> Usd.Prim:
    xformable = UsdGeom.Xform.Define(stage, "/Bot")
    for name in ops:
        if name == "translate":
            xformable.AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
        elif name == "pivot":
            xformable.AddTranslateOp(opSuffix="pivot").Set(Gf.Vec3d(0.2, 0, 0.3))
        elif name == "rotateXYZ":
            xformable.AddRotateXYZOp().Set(Gf.Vec3f(0, 30, 0))
        elif name == "invert pivot":
            xformable.AddTranslateOp(opSuffix="pivot", isInverseOp=True)
        elif name == "units":
            xformable.AddRotateXOp(opSuffix="unitsResolve").Set(-90.0)
    return xformable.GetPrim()


def _names(prim: Usd.Prim) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()]


def test_a_turn_goes_last_on_a_root_without_an_inverse_op(stage: Usd.Stage):
    prim = _prim(stage, ["translate", "rotateXYZ"])

    assert stand_upright(prim, -90.0) == -90.0
    assert _names(prim) == ["xformOp:translate", "xformOp:rotateXYZ", UP_AXIS_OP]
    assert prim.GetAttribute(UP_AXIS_OP).Get() == -90.0


def test_a_turn_goes_before_an_inverse_op_as_kit_puts_it(stage: Usd.Stage):
    # Appended after the inverse pivot, the robot would land off by Rx·p - p from where Kit puts it.
    prim = _prim(stage, ["translate", "pivot", "rotateXYZ", "invert pivot"])

    stand_upright(prim, -90.0)

    assert _names(prim) == [
        "xformOp:translate",
        "xformOp:translate:pivot",
        "xformOp:rotateXYZ",
        UP_AXIS_OP,
        "!invert!xformOp:translate:pivot",
    ]
    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    pivot = Gf.Matrix4d().SetTranslate(Gf.Vec3d(0.2, 0, 0.3))
    turn = Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), -90)) * Gf.Matrix4d().SetRotate(
        Gf.Rotation(Gf.Vec3d(0, 1, 0), 30)
    )
    want = pivot.GetInverse() * turn * pivot * Gf.Matrix4d().SetTranslate(Gf.Vec3d(1, 2, 3))
    assert Gf.IsClose(matrix, want, 1e-6)


def test_a_root_that_holds_the_op_gets_the_sum_in_place(stage: Usd.Stage):
    # A Z-up robot Kit saved into a Y-up file (-90), given to a Z-up stage (+90): its content was Z-up all along.
    prim = _prim(stage, ["translate", "units"])

    assert stand_upright(prim, 90.0) == 0.0
    assert _names(prim) == ["xformOp:translate", UP_AXIS_OP]
    # The sum is in the op, not only in the answer: "now reads 0" must hold when it is read back (review F5).
    assert prim.GetAttribute(UP_AXIS_OP).Get() == 0.0


def test_a_turn_reuses_an_attribute_of_its_name_out_of_the_order_in_its_precision(stage: Usd.Stage):
    # A double attribute of the op's name, not in the order: a float op raised Tf.ErrorException, a 500 (review F3).
    prim = _prim(stage, ["translate"])
    prim.CreateAttribute(UP_AXIS_OP, Sdf.ValueTypeNames.Double).Set(12.0)

    assert stand_upright(prim, -90.0) == -90.0
    assert _names(prim) == ["xformOp:translate", UP_AXIS_OP]
    assert prim.GetAttribute(UP_AXIS_OP).GetTypeName() == Sdf.ValueTypeNames.Double
    assert prim.GetAttribute(UP_AXIS_OP).Get() == -90.0


def test_an_animated_op_is_refused(stage: Usd.Stage):
    prim = _prim(stage, ["units"])
    prim.GetAttribute(UP_AXIS_OP).Set(-90.0, 1.0)

    with pytest.raises(ValueError, match="animated"):
        stand_upright(prim, 90.0)
