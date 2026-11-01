"""The robot handlers against a fake Kit, on a usd-core stage, loaded as tests/test_scene_handler.py loads the scene
handlers. create_robot's (#82): the robot is placed through the Kit-free transform writer, and a refusal leaves nothing
behind for the retry to trip on; a file of another up axis stands on the stage (#105); a file of other units is scaled
to the stage's and its values converted (#112). /robot/joint_states' without Isaac Sim (#77): an error that names no
tool."""

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any

import golden
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.usd import floats, is_a

from .test_scene_handler import FakeKit, load_handler


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def robot(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler("robot", kit, monkeypatch)


def _bot_file(
    folder: Path,
    animated: bool = False,
    up_axis: str | None = None,
    units_op: float | None = None,
    size: tuple[float, float, float] | None = None,
    meters: float | None = None,
    kilograms: float | None = None,
    scale_op: float | None = None,
) -> str:
    """A robot's USD file: a root Xform with its own [translate, orient] ops, the translate animated if asked, and a
    body 2 tall along the file's up axis, under an upAxis, a metersPerUnit and a kilogramsPerUnit it authors if asked;
    its root ends with Kit's turn and Kit's scale if asked, as a file Kit resolved and saved has. The body has a mass
    of 2 and an inertia of (1, 2, 3)."""
    layer = Sdf.Layer.CreateNew(str(folder / "bot.usda"))
    held = Usd.Stage.Open(layer)
    if up_axis is not None:
        UsdGeom.SetStageUpAxis(held, up_axis)
    if meters is not None:
        UsdGeom.SetStageMetersPerUnit(held, meters)
    if kilograms is not None:
        UsdPhysics.SetStageKilogramsPerUnit(held, kilograms)
    root = UsdGeom.Xform.Define(held, "/Bot")
    translate = root.AddTranslateOp()
    if animated:
        translate.Set(Gf.Vec3d(0, 0, 1), 1.0)
    else:
        translate.Set(Gf.Vec3d(0, 0, 0))
    root.AddOrientOp().Set(Gf.Quatf(1, 0, 0, 0))
    if units_op is not None:
        root.AddRotateXOp(opSuffix="unitsResolve").Set(units_op)
    if scale_op is not None:
        root.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(scale_op, scale_op, scale_op))
    body = UsdGeom.Cube.Define(held, "/Bot/Body")
    tall = size or ((1.0, 1.0, 2.0) if up_axis == "Z" else (1.0, 2.0, 1.0))
    body.AddScaleOp().Set(Gf.Vec3f(*(0.5 * v for v in tall)))
    mass = UsdPhysics.MassAPI.Apply(body.GetPrim())
    mass.CreateMassAttr(2.0)
    mass.CreateDiagonalInertiaAttr(Gf.Vec3f(1, 2, 3))
    held.SetDefaultPrim(root.GetPrim())
    layer.Save()
    return layer.realPath


def _create(robot: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(robot.handle_create_robot(body))


def test_a_robot_from_a_file_is_placed_through_its_own_ops(robot, kit, tmp_path):
    r = _create(robot, robot_type=_bot_file(tmp_path), prim_path="/World/Bot", position=[1, 2, 3], rotation=[0, 0, 90])

    assert r["status"] == "success", r
    prim = kit.stage.GetPrimAtPath("/World/Bot")
    assert [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()] == [
        "xformOp:translate",
        "xformOp:orient",
    ]
    assert prim.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(1, 2, 3)


def test_a_malformed_rotation_makes_no_robot(robot, kit, tmp_path):
    # 0.2.3 made the robot, then failed, and the retry was refused as taken.
    r = _create(robot, robot_type=_bot_file(tmp_path), prim_path="/World/Bot", rotation=[0, 90])

    assert r["status"] == "error"
    assert "rotation must be" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Bot").IsValid()


def test_a_refusal_found_once_the_robot_is_there_takes_it_away(robot, kit, tmp_path):
    r = _create(robot, robot_type=_bot_file(tmp_path, animated=True), prim_path="/World/Robots/Bot", position=[1, 2, 3])

    assert r["status"] == "error"
    assert "The robot was not added" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()


def test_joint_states_without_isaac_sim_say_so_and_name_no_tool(robot, kit, monkeypatch):
    # get_robot_info gives this error as its joint states' line; it named get_joint_states, a tool that is gone (#77).
    # The module made unimportable, as in a Kit app without Isaac Sim, wherever this runs.
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.prims", None)
    bot = UsdGeom.Xform.Define(kit.stage, "/World/Bot").GetPrim()
    UsdPhysics.ArticulationRootAPI.Apply(bot)

    r = asyncio.run(robot.handle_get_joint_states({"prim_path": "/World/Bot"}))

    assert r["status"] == "error"
    assert r["error"].startswith("Joint states need Isaac Sim's isaacsim.core.experimental.prims extension: ")
    tools = {*json.loads(golden.GOLDEN.read_text(encoding="utf-8"))["tools"], "get_joint_states"}
    assert sorted(name for name in tools if name in r["error"]) == []


# ---- a file of another up axis stands on the stage (#105) ----


def _size(kit: FakeKit, path: str) -> list[float]:
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(kit.stage.GetPrimAtPath(path))
    return [round(v, 6) for v in floats(box.ComputeAlignedRange().GetSize())]


def _ops(kit: FakeKit, path: str) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(kit.stage.GetPrimAtPath(path)).GetOrderedXformOps()]


def test_a_z_up_file_stands_on_a_y_up_stage(robot, kit, tmp_path):
    # The G1 on scenario 10.1's Y-up stage lay on its side: tallest along Z (#105).
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis="Z"), prim_path="/World/Bot", position=[3, 0.74, 0])

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", "xformOp:rotateX:unitsResolve"]
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:rotateX:unitsResolve").Get() == -90.0
    assert _size(kit, "/World/Bot") == [1.0, 2.0, 1.0]
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:translate").Get() == Gf.Vec3d(3, 0.74, 0)
    assert r["result"]["up_axis_turn"] == {
        "file": "Z",
        "stage": "Y",
        "degrees": -90.0,
        "op": -90.0,
        "op_name": "xformOp:rotateX:unitsResolve",
    }


def test_a_rotation_turns_the_standing_robot_about_the_stage_s_axis(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    # 1 by 1.5 by 2 in its Z-up file: upright, 1 by 2 by 1.5; turned 90° about Y, 1.5 by 2 by 1. With X and Z alike, a
    # rotation dropped would look the same as one made (review I10).
    bot = _bot_file(tmp_path, up_axis="Z", size=(1.0, 1.5, 2.0))

    r = _create(robot, robot_type=bot, prim_path="/World/Bot", rotation=[0, 90, 0])

    assert r["status"] == "success", r
    # Turned about Y, the stage's up, it still stands: the turn upright is inside the rotation.
    assert _size(kit, "/World/Bot") == [1.5, 2.0, 1.0]


def test_a_y_up_file_stands_on_a_z_up_stage(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.z)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis="Y"), prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"]["degrees"] == 90.0
    assert _size(kit, "/World/Bot") == [1.0, 1.0, 2.0]


@pytest.mark.parametrize(("file_axis", "stage_axis"), [("Z", "Z"), ("Y", "Y"), (None, "Z")], ids=["Z", "Y", "unsaid"])
def test_a_file_of_the_stage_s_axis_or_none_is_left_as_it_is(robot, kit, tmp_path, file_axis, stage_axis):
    UsdGeom.SetStageUpAxis(kit.stage, stage_axis)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis=file_axis), prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"] is None
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient"]


def test_a_file_kit_resolved_and_saved_gets_the_turn_it_still_owes(robot, kit, tmp_path):
    # A Z-up robot Kit dropped on a Y-up stage (-90) and saved as a Y-up file, given to a Z-up stage (+90).
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.z)
    bot = _bot_file(tmp_path, up_axis="Y", units_op=-90.0)

    r = _create(robot, robot_type=bot, prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"]["degrees"] == 90.0
    assert r["result"]["up_axis_turn"]["op"] == 0.0
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", "xformOp:rotateX:unitsResolve"]
    # What the answer says is what the op holds (review F5).
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:rotateX:unitsResolve").Get() == 0.0


def test_a_usd_error_writing_the_turn_leaves_no_robot(robot, kit, tmp_path):
    # A float3 attribute of the turn's name on the file's root, out of its order: USD refuses the op with a
    # Tf.ErrorException, which answered 500 and left the robot, so a retry was refused as taken (review F3).
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    bot = _bot_file(tmp_path, up_axis="Z")
    layer = Sdf.Layer.FindOrOpen(bot)
    held = Usd.Stage.Open(layer)
    held.GetPrimAtPath("/Bot").CreateAttribute("xformOp:rotateX:unitsResolve", Sdf.ValueTypeNames.Float3)
    layer.Save()

    r = _create(robot, robot_type=bot, prim_path="/World/Robots/Bot")

    assert r["status"] == "error", r
    assert "The robot was not added" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()


def test_a_refusal_after_the_turn_leaves_no_robot(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    bot = _bot_file(tmp_path, animated=True, up_axis="Z")

    r = _create(robot, robot_type=bot, prim_path="/World/Robots/Bot", position=[1, 2, 3])

    assert r["status"] == "error"
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()


def test_a_later_set_transform_keeps_the_turn_where_it_is(robot, kit, tmp_path, monkeypatch):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    _create(robot, robot_type=_bot_file(tmp_path, up_axis="Z"), prim_path="/World/Bot")
    scene = load_handler("scene", kit, monkeypatch)

    r = asyncio.run(scene.handle_transform({"prim_path": "/World/Bot", "position": [0, 1, 0], "rotation": [0, 45, 0]}))

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot")[-1] == "xformOp:rotateX:unitsResolve"
    assert _size(kit, "/World/Bot")[1] == 2.0


# ---- a file of other units is scaled to the stage's and its values converted (#112) ----

SCALE = "xformOp:scale:unitsResolve"

# omni.usd.schema.physx-110.4.4's units_db.py, the entries these tests' robots author: (mass, distance, degrees,
# seconds, radians), or a dict where the prim decides, which its units.py settles as the fake below does.
_UNITS_DB: dict[str, Any] = {
    "physxArticulation:sleepThreshold": (0, 2, 0, -2, 0),
    "physics:mass": (1, 0, 0, 0, 0),
    "physics:diagonalInertia": (1, 2, 0, 0, 0),
    "physics:centerOfMass": (0, 0, 0, 0, 0),
    "physxCollision:contactOffset": (0, 1, 0, 0, 0),
    "physics:density": (1, -3, 0, 0, 0),
    "physics:lowerLimit": {"RevoluteJoint": (0, 0, 1, 0, 0), "PrismaticJoint": (0, 1, 0, 0, 0)},
    "physics:upperLimit": {"RevoluteJoint": (0, 0, 1, 0, 0), "PrismaticJoint": (0, 1, 0, 0, 0)},
    "drive:angular:physics:stiffness": {"Force": (1, 2, -1, -2, 0), "Acceleration": (0, 2, -1, -2, 0)},
    "drive:angular:physics:damping": {"Force": (1, 2, -1, -1, 0), "Acceleration": (0, 2, -1, -1, 0)},
    "drive:angular:physics:maxForce": (1, 2, 0, -2, 0),
    "drive:angular:physics:targetPosition": (0, 0, 1, 0, 0),
    "physxJoint:maxJointVelocity": {"Linear joint": (0, 1, 0, -1, 0), "Angular joint": (0, 0, 1, -1, 0)},
    "drive:linear:physics:stiffness": {"Force": (1, 0, 0, -2, 0), "Acceleration": (0, 0, 0, -2, 0)},
    "drive:linear:physics:damping": {"Force": (1, 0, 0, -1, 0), "Acceleration": (0, 0, 0, -1, 0)},
    "drive:linear:physics:maxForce": (1, 1, 0, -2, 0),
    "drive:linear:physics:targetPosition": (0, 1, 0, 0, 0),
    "drive:linear:physics:targetVelocity": (0, 1, 0, -1, 0),
}


def _exponents(name: str, prim: Usd.Prim | None = None) -> Any:
    found = _UNITS_DB.get(name)
    if not isinstance(found, dict) or prim is None:
        return found
    revolute = is_a(prim, UsdPhysics.RevoluteJoint)
    if "RevoluteJoint" in found:
        return found["RevoluteJoint" if revolute else "PrismaticJoint"]
    if "Angular joint" in found:
        return found["Angular joint" if revolute else "Linear joint"]
    kind = prim.GetAttribute(f"drive:{name.split(':')[1]}:physics:type")
    return found["Force" if kind.IsValid() and kind.Get() == "force" else "Acceleration"]


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch) -> None:
    """pxr.PhysicsSchemaTools.units, which only Kit's PhysX schema ships, faked with its own entries."""
    units = types.ModuleType("pxr.PhysicsSchemaTools.units")
    units.get_attribute_unit_exponents = _exponents  # type: ignore[attr-defined]
    tools = types.ModuleType("pxr.PhysicsSchemaTools")
    tools.units = units  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools", tools)
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools.units", units)


def _stage_units(kit: FakeKit, meters: float, kilograms: float = 1.0, up_axis: str = "Y") -> None:
    UsdGeom.SetStageUpAxis(kit.stage, up_axis)
    UsdGeom.SetStageMetersPerUnit(kit.stage, meters)
    UsdPhysics.SetStageKilogramsPerUnit(kit.stage, kilograms)


# 112-probe.py's robot in metres, Y-up: a fixed base, an arm with a density and an instanced pad, a hinge on an angular
# force drive, a slide on a linear one with a sampled target velocity.
_PROBE_BOT = """#usda 1.0
(
    defaultPrim = "Bot"
    metersPerUnit = 1
    kilogramsPerUnit = 1
    upAxis = "Y"
)

def Xform "Bot" (
    prepend apiSchemas = ["PhysicsArticulationRootAPI"]
)
{
    float physxArticulation:sleepThreshold = 0.005

    def Xform "Base" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:mass = 2
        float3 physics:diagonalInertia = (0.1, 0.2, 0.3)
        point3f physics:centerOfMass = (0, 0.1, 0)

        def Cube "Shape" (
            prepend apiSchemas = ["PhysicsCollisionAPI"]
        )
        {
            double size = 0.2
            float physxCollision:contactOffset = 0.02
        }
    }

    def Xform "Arm" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:density = 1000
        double3 xformOp:translate = (0, 0.5, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]

        def Xform "Pad" (
            instanceable = true
            prepend references = </Proto>
        )
        {
        }
    }

    def Xform "Finger" (
        prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"]
    )
    {
        float physics:mass = 0.1
    }

    def PhysicsRevoluteJoint "Hinge" (
        prepend apiSchemas = ["PhysicsDriveAPI:angular"]
    )
    {
        rel physics:body0 = </Bot/Base>
        rel physics:body1 = </Bot/Arm>
        point3f physics:localPos0 = (0, 0.25, 0)
        float physics:lowerLimit = -90
        float physics:upperLimit = 90
        uniform token drive:angular:physics:type = "force"
        float drive:angular:physics:stiffness = 1000
        float drive:angular:physics:damping = 100
        float drive:angular:physics:maxForce = 50
        float drive:angular:physics:targetPosition = 30
        float physxJoint:maxJointVelocity = 180
    }

    def PhysicsPrismaticJoint "Slide" (
        prepend apiSchemas = ["PhysicsDriveAPI:linear"]
    )
    {
        rel physics:body0 = </Bot/Arm>
        rel physics:body1 = </Bot/Finger>
        point3f physics:localPos0 = (0, 0.1, 0)
        float physics:lowerLimit = 0
        float physics:upperLimit = 0.04
        uniform token drive:linear:physics:type = "force"
        float drive:linear:physics:stiffness = 500
        float drive:linear:physics:damping = 10
        float drive:linear:physics:maxForce = 20
        float drive:linear:physics:targetPosition = 0.02
        float drive:linear:physics:targetVelocity.timeSamples = {
            0: 0,
            10: 0.1,
        }
        float physxJoint:maxJointVelocity = 0.2
    }
}

def Xform "Proto"
{
    def Cube "Shape"
    {
        double size = 0.05
        float physxCollision:contactOffset = 0.03
    }
}
"""

# What Kit's assembler made of each of the probe robot's values on a centimetre stage (112-probe.out.txt, K2's after).
_KITS: dict[tuple[str, str], Any] = {
    ("", "physxArticulation:sleepThreshold"): 50.0,
    ("Base", "physics:mass"): 2.0,
    ("Base", "physics:diagonalInertia"): (1000.0, 2000.0, 3000.0),
    ("Base", "physics:centerOfMass"): (0.0, 0.1, 0.0),
    ("Base/Shape", "physxCollision:contactOffset"): 2.0,
    ("Arm", "physics:density"): 0.001,
    ("Arm/Pad/Shape", "physxCollision:contactOffset"): 0.03,
    ("Hinge", "physics:localPos0"): (0.0, 0.25, 0.0),
    ("Hinge", "physics:upperLimit"): 90.0,
    ("Hinge", "drive:angular:physics:stiffness"): 1e7,
    ("Hinge", "drive:angular:physics:damping"): 1e6,
    ("Hinge", "drive:angular:physics:maxForce"): 5e5,
    ("Hinge", "drive:angular:physics:targetPosition"): 30.0,
    ("Hinge", "physxJoint:maxJointVelocity"): 180.0,
    ("Slide", "physics:localPos0"): (0.0, 0.1, 0.0),
    ("Slide", "physics:upperLimit"): 4.0,
    ("Slide", "drive:linear:physics:stiffness"): 500.0,
    ("Slide", "drive:linear:physics:damping"): 10.0,
    ("Slide", "drive:linear:physics:maxForce"): 2000.0,
    ("Slide", "drive:linear:physics:targetPosition"): 2.0,
    ("Slide", "drive:linear:physics:targetVelocity"): 0.0,
    ("Slide", "physxJoint:maxJointVelocity"): 20.0,
}


def _value(kit: FakeKit, path: str, name: str, time: float | None = None) -> Any:
    value = kit.stage.GetPrimAtPath(path).GetAttribute(name).Get(Usd.TimeCode.Default() if time is None else time)
    return tuple(float(v) for v in value) if hasattr(value, "__len__") else value


def test_a_metre_robot_on_a_centimetre_stage_gets_kit_s_scale_and_kit_s_values(robot, kit, tmp_path, table):
    _stage_units(kit, 0.01)
    bot = tmp_path / "bot.usda"
    bot.write_text(_PROBE_BOT, encoding="utf-8")

    r = _create(robot, robot_type=str(bot), prim_path="/World/Bot")

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", SCALE]
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute(SCALE).Get() == Gf.Vec3d(100, 100, 100)
    # The base's 0.2 cube is 20 centimetres: shapes and joint frames ride the scale (K8, K9).
    assert _size(kit, "/World/Bot/Base/Shape") == [20.0, 20.0, 20.0]
    for (rel, name), want in _KITS.items():
        got = _value(kit, "/World/Bot" + (f"/{rel}" if rel else ""), name)
        assert got == pytest.approx(want, rel=1e-6), (rel, name)
    # Every sample, not only the first (U2).
    assert _value(kit, "/World/Bot/Slide", "drive:linear:physics:targetVelocity", 10) == pytest.approx(10.0)
    assert r["result"]["units_scale"] == {
        "meters_per_unit": {"file": 1.0, "stage": 0.01},
        "kilograms_per_unit": None,
        "factor": 100.0,
        "op": [100.0, 100.0, 100.0],
        "op_name": SCALE,
        # Kit's 13 but the slide's lower limit, 0, which converts to itself and gets no override.
        "converted": 12,
        "left": ["/World/Bot/Arm/Pad/Shape.physxCollision:contactOffset"],
        "left_count": 1,
        "table": True,
    }


def test_a_z_up_metre_file_on_a_y_up_centimetre_stage_is_turned_then_scaled(robot, kit, tmp_path, table):
    # Kit's order (P3): the turn, then the scale, after the file's own ops.
    _stage_units(kit, 0.01)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis="Z", meters=1.0), prim_path="/World/Bot")

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", "xformOp:rotateX:unitsResolve", SCALE]
    assert _size(kit, "/World/Bot") == [100.0, 200.0, 100.0]
    assert r["result"]["up_axis_turn"]["degrees"] == -90.0
    assert r["result"]["units_scale"]["op"] == [100.0, 100.0, 100.0]


@pytest.mark.parametrize(
    ("meters", "stage_meters"),
    [(0.01, 0.01), (1.0, 1.0), (None, 0.01), (None, 1.0)],
    ids=["cm", "m", "unsaid-cm", "unsaid-m"],
)
def test_a_file_of_the_stage_s_units_or_none_is_left_as_it_is(robot, kit, tmp_path, table, meters, stage_meters):
    _stage_units(kit, stage_meters)

    r = _create(robot, robot_type=_bot_file(tmp_path, meters=meters), prim_path="/World/Bot")

    assert r["result"]["units_scale"] is None
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient"]
    assert _value(kit, "/World/Bot/Body", "physics:diagonalInertia") == (1.0, 2.0, 3.0)


def test_a_camera_s_distances_convert_and_without_the_physx_schema_the_answer_says_so(
    robot, kit, tmp_path, monkeypatch
):
    # A Kit app without the PhysX schema: the scale and the camera's two distances, not the physics values (K12).
    monkeypatch.setitem(sys.modules, "pxr.PhysicsSchemaTools", None)
    _stage_units(kit, 0.01)
    bot = _bot_file(tmp_path, meters=1.0)
    layer = Sdf.Layer.FindOrOpen(bot)
    held = Usd.Stage.Open(layer)
    camera = UsdGeom.Camera.Define(held, "/Bot/Eye")
    camera.CreateFocusDistanceAttr(10.0)
    camera.CreateClippingRangeAttr(Gf.Vec2f(1, 1000))
    layer.Save()

    r = _create(robot, robot_type=bot, prim_path="/World/Bot")

    assert r["status"] == "success", r
    assert _value(kit, "/World/Bot/Eye", "focusDistance") == pytest.approx(1000.0)
    assert _value(kit, "/World/Bot/Eye", "clippingRange") == pytest.approx((100.0, 100000.0))
    assert _value(kit, "/World/Bot/Body", "physics:diagonalInertia") == (1.0, 2.0, 3.0)
    scaled = r["result"]["units_scale"]
    assert (scaled["op"], scaled["converted"], scaled["table"]) == ([100.0, 100.0, 100.0], 2, False)


def test_a_file_of_other_kilograms_per_unit_has_its_masses_converted_and_nothing_scaled(robot, kit, tmp_path, table):
    _stage_units(kit, 0.01)

    r = _create(robot, robot_type=_bot_file(tmp_path, kilograms=0.001), prim_path="/World/Bot")

    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient"]
    assert _value(kit, "/World/Bot/Body", "physics:mass") == pytest.approx(0.002)
    assert _value(kit, "/World/Bot/Body", "physics:diagonalInertia") == pytest.approx((0.001, 0.002, 0.003))
    scaled = r["result"]["units_scale"]
    assert scaled["meters_per_unit"] is None
    assert scaled["kilograms_per_unit"] == {"file": 0.001, "stage": 1.0}
    assert (scaled["factor"], scaled["op"], scaled["op_name"], scaled["converted"]) == (None, None, None, 2)


def test_a_file_whose_root_holds_the_scale_gets_it_multiplied_and_the_answer_names_both(robot, kit, tmp_path, table):
    # A metre robot Kit dropped on a centimetre stage and saved (op 100), given to a metre stage (improvement 3).
    _stage_units(kit, 1.0)

    r = _create(robot, robot_type=_bot_file(tmp_path, meters=0.01, scale_op=100.0), prim_path="/World/Bot")

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", SCALE]
    assert _size(kit, "/World/Bot") == [1.0, 2.0, 1.0]
    scaled = r["result"]["units_scale"]
    assert (scaled["factor"], scaled["op"]) == (0.01, [1.0, 1.0, 1.0])


def test_a_refusal_after_the_conversion_leaves_no_robot_and_no_override(robot, kit, tmp_path, table):
    _stage_units(kit, 0.01)
    bot = _bot_file(tmp_path, animated=True, meters=1.0)

    r = _create(robot, robot_type=bot, prim_path="/World/Robots/Bot", position=[1, 2, 3])

    assert r["status"] == "error"
    assert "The robot was not added" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Robots") is None


def test_any_other_failure_while_converting_leaves_no_robot_and_names_the_step(
    robot, kit, tmp_path, monkeypatch, table
):
    # Such as the PhysX schema's table changed in a later Kit (improvement 2).
    def broken(*_args: Any) -> Any:
        raise KeyError("Acceleration")

    monkeypatch.setattr(robot, "convert_units", broken)
    _stage_units(kit, 0.01)

    r = _create(robot, robot_type=_bot_file(tmp_path, meters=1.0), prim_path="/World/Robots/Bot")

    assert r["status"] == "error"
    assert r["error"] == (
        "Converting the robot's values to the stage's units failed: KeyError: 'Acceleration'. The robot was not added"
    )
    assert kit.stage.GetRootLayer().GetPrimAtPath("/World/Robots") is None


def test_the_physx_schema_s_table_is_imported_once(robot, table):
    assert robot._physics_exponents() is robot._physics_exponents()
    assert robot._physics_exponents()("physics:density", None) == (1, -3)
