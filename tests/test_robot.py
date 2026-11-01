"""The prim create_robot names for a robot or its USD file (#40); where /robot/joint_states finds a robot's articulation
(#50); the turn that stands a file of another up axis on the stage (#105), and the scale and the converted values that
bring a file of other units to the stage's (#112). Without Kit. Where a file loads from is tests/test_usd_files.py's."""

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.robot import (
    UNITS_OP,
    UP_AXIS_OP,
    Converted,
    Exponents,
    Factors,
    Units,
    articulation_root,
    convert_units,
    file_up_axis,
    is_usd_file,
    layer_units,
    robot_prim_path,
    scale_to_stage,
    stand_upright,
    unit_exponents,
    units_factors,
    up_axis_turn,
)
from ovmcp.core.xform import add_local_op


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


# ---- bringing a file of other units to the stage's (#112) ----


def _units_layer(meters: float | None = None, kilograms: float | None = None, text: str = "") -> Sdf.Layer:
    """An anonymous layer of the units asked for, its prims from text."""
    layer = Sdf.Layer.CreateAnonymous("bot.usda")
    if text:
        layer.ImportFromString("#usda 1.0\n" + text)
    if meters is not None:
        layer.pseudoRoot.SetInfo("metersPerUnit", meters)
    if kilograms is not None:
        layer.pseudoRoot.SetInfo("kilogramsPerUnit", kilograms)
    return layer


@pytest.mark.parametrize(
    ("meters", "kilograms", "units"),
    [(1.0, 0.001, Units(1.0, 0.001)), (None, None, Units(None, None)), (0.0, -1.0, Units(None, None))],
    ids=["both", "neither", "nonsense"],
)
def test_a_layer_s_units_are_what_it_authors(meters: float | None, kilograms: float | None, units: Units):
    # A unit of 0 or below would scale the robot to nothing: taken as not said, as one the file leaves out (Q2).
    assert layer_units(_units_layer(meters, kilograms)) == units


@pytest.mark.parametrize(
    ("file", "stage", "factors"),
    [
        (Units(1.0, None), Units(0.01, 1.0), Factors(100.0, 1.0)),
        (Units(0.01, None), Units(1.0, 1.0), Factors(0.01, 1.0)),
        (Units(0.01, 1.0), Units(0.01, 1.0), None),
        (Units(None, None), Units(0.01, 1.0), None),
        (Units(None, 0.001), Units(1.0, 1.0), Factors(1.0, 0.001)),
        (Units(1.0, 1.0), Units(0.01, 0.001), Factors(100.0, 1000.0)),
        (Units(0.30000000000000004, None), Units(0.3, 1.0), None),
    ],
    ids=["metres-on-cm", "cm-on-metres", "same", "unsaid", "mass-only", "both", "rounding"],
)
def test_the_factors_from_a_file_s_units_to_the_stage_s(file: Units, stage: Units, factors: Factors | None):
    assert units_factors(file, stage) == factors


def test_the_scale_is_a_double_op_after_the_turn_as_kit_writes_them(stage: Usd.Stage):
    # Kit's assembler on a Z-up metre file and a Y-up centimetre stage: the turn, then the scale, both double (P3).
    prim = _prim(stage, ["translate", "rotateXYZ"])
    stand_upright(prim, -90.0)

    assert scale_to_stage(prim, 100.0) == [100.0, 100.0, 100.0]
    assert _names(prim) == ["xformOp:translate", "xformOp:rotateXYZ", UP_AXIS_OP, UNITS_OP]
    assert prim.GetAttribute(UNITS_OP).GetTypeName() == Sdf.ValueTypeNames.Double3
    assert prim.GetAttribute(UNITS_OP).Get() == Gf.Vec3d(100, 100, 100)


def test_the_scale_goes_before_an_inverse_op(stage: Usd.Stage):
    prim = _prim(stage, ["translate", "pivot", "rotateXYZ", "invert pivot"])

    scale_to_stage(prim, 0.01)

    assert _names(prim) == [
        "xformOp:translate",
        "xformOp:translate:pivot",
        "xformOp:rotateXYZ",
        UNITS_OP,
        "!invert!xformOp:translate:pivot",
    ]


def test_a_held_scale_is_multiplied_in_its_place_and_precision(stage: Usd.Stage):
    # A metre robot Kit dropped on a centimetre stage and saved (op 100), given to a metre stage: 1, where it was.
    prim = _prim(stage, ["translate"])
    xformable = UsdGeom.Xformable(prim)
    xformable.AddScaleOp(UsdGeom.XformOp.PrecisionFloat, "unitsResolve").Set(Gf.Vec3f(100, 100, 100))
    xformable.AddRotateXOp(opSuffix="unitsResolve").Set(-90.0)

    assert scale_to_stage(prim, 0.01) == pytest.approx([1.0, 1.0, 1.0])
    assert _names(prim) == ["xformOp:translate", UNITS_OP, UP_AXIS_OP]
    assert prim.GetAttribute(UNITS_OP).GetTypeName() == Sdf.ValueTypeNames.Float3
    assert prim.GetAttribute(UNITS_OP).Get() == Gf.Vec3f(1, 1, 1)


def test_an_animated_scale_is_refused(stage: Usd.Stage):
    prim = _prim(stage, [])
    UsdGeom.Xformable(prim).AddScaleOp(opSuffix="unitsResolve").Set(Gf.Vec3f(1, 1, 1), 1.0)

    with pytest.raises(ValueError, match="animated"):
        scale_to_stage(prim, 100.0)


def test_a_local_op_given_no_precision_is_float(stage: Usd.Stage):
    # #105's turn kept its float op when the scale's double came in.
    op = add_local_op(_prim(stage, []), UsdGeom.XformOp.TypeRotateY, "mine")

    assert op.GetPrecision() == UsdGeom.XformOp.PrecisionFloat


def _nine(_name: str, _prim: Usd.Prim) -> Exponents:
    return Exponents(mass=9, distance=9)


def test_a_camera_s_distances_and_an_acceleration_drive_s_gains_have_exponents_of_their_own(stage: Usd.Stage):
    camera = UsdGeom.Camera.Define(stage, "/Camera").GetPrim()
    joint = UsdPhysics.RevoluteJoint.Define(stage, "/Hinge").GetPrim()
    angular = UsdPhysics.DriveAPI.Apply(joint, "angular")
    linear = UsdPhysics.DriveAPI.Apply(joint, "linear")

    assert unit_exponents("focusDistance", camera, _nine) == (0, 1)
    assert unit_exponents("clippingRange", camera, _nine) == (0, 1)
    assert unit_exponents("focalLength", camera, _nine) == (9, 9)
    # A drive of no type authored is a force drive, the schema's fallback: the table's.
    assert unit_exponents("drive:angular:physics:stiffness", joint, _nine) == (9, 9)
    angular.CreateTypeAttr(UsdPhysics.Tokens.acceleration)
    linear.CreateTypeAttr(UsdPhysics.Tokens.acceleration)
    # (deg/s²)/deg holds no mass and no distance, where the table keeps the force drive's m² (P2, K11).
    assert unit_exponents("drive:angular:physics:stiffness", joint, _nine) == (0, 0)
    assert unit_exponents("drive:angular:physics:damping", joint, _nine) == (0, 0)
    assert unit_exponents("drive:angular:physics:maxForce", joint, _nine) == (9, 9)
    assert unit_exponents("drive:linear:physics:stiffness", joint, _nine) == (9, 9)


_SMALL_TABLE = {
    "physics:mass": Exponents(mass=1, distance=0),
    "physics:density": Exponents(mass=1, distance=-3),
    "physics:diagonalInertia": Exponents(mass=1, distance=2),
    "physics:centerOfMass": Exponents(mass=0, distance=0),
    "physics:upperLimit": Exponents(mass=0, distance=1),
    "physxCollision:contactOffset": Exponents(mass=0, distance=1),
    "drive:linear:physics:targetVelocity": Exponents(mass=0, distance=1),
    "ovmcp:label": Exponents(mass=0, distance=1),
}


def _small_table(name: str, _prim: Usd.Prim) -> Exponents | None:
    return _SMALL_TABLE.get(name)


_BOT = """
def Xform "Bot"
{
    float physics:mass = 2
    float physics:density = 1000
    float3 physics:diagonalInertia = (0.1, 0.2, 0.3)
    point3f physics:centerOfMass = (0, 0.1, 0)
    float physics:upperLimit = 0
    float physxCollision:contactOffset = inf
    float drive:linear:physics:targetVelocity = 0.5
    float drive:linear:physics:targetVelocity.timeSamples = {
        0: 0,
        10: 0.1,
    }
    string ovmcp:label = "a"
    float unlisted = 3

    def Camera "Eye"
    {
        float2 clippingRange = (1, 1000)
    }

    def Xform "Pad" (
        instanceable = true
        prepend references = </Proto>
    )
    {
    }
}

def Xform "Proto"
{
    def Cube "Shape"
    {
        float physxCollision:contactOffset = 0.03
    }
}
"""


def _stage_of(meters: float, kilograms: float = 1.0) -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, meters)
    UsdPhysics.SetStageKilogramsPerUnit(stage, kilograms)
    return stage


def _robot(stage: Usd.Stage, layer: Sdf.Layer, path: str = "/Bot") -> Usd.Prim:
    prim = stage.DefinePrim("/World/Bot")
    prim.GetReferences().AddReference(layer.identifier, path)
    return prim


def _convert(stage: Usd.Stage, prim: Usd.Prim, file: Units, table=_small_table) -> Converted:
    units = Units(UsdGeom.GetStageMetersPerUnit(stage), UsdPhysics.GetStageKilogramsPerUnit(stage))
    return convert_units(prim, file, units, table)


def _get(prim: Usd.Prim, name: str, time: float | None = None) -> object:
    return prim.GetAttribute(name).Get(Usd.TimeCode.Default() if time is None else time)


def test_each_value_is_converted_by_its_exponents_and_written_only_when_it_changes():
    # A metre and kilogram file on a stage of centimetres and grams: lengths times 100, masses times 1000.
    stage = _stage_of(0.01, 0.001)
    prim = _robot(stage, _units_layer(1.0, 1.0, _BOT))

    done = _convert(stage, prim, Units(1.0, 1.0))

    assert _get(prim, "physics:mass") == pytest.approx(2000)
    # Both factors off 1 and a negative exponent: 1000 kg/m³ is 1000 * 1000 / 100³ g/cm³ (improvement 5).
    assert _get(prim, "physics:density") == pytest.approx(1.0)
    assert _get(prim, "physics:diagonalInertia") == pytest.approx((1e6, 2e6, 3e6))
    assert _get(prim.GetChild("Eye"), "clippingRange") == pytest.approx((100, 100000))
    # The default and every sample: written one at a time, the first sample would hide the file's others (U2).
    assert _get(prim, "drive:linear:physics:targetVelocity") == pytest.approx(50)
    assert _get(prim, "drive:linear:physics:targetVelocity", 10) == pytest.approx(10)
    assert _get(prim, "drive:linear:physics:targetVelocity", 0) == 0
    root = stage.GetRootLayer()
    # A value the factor leaves as it is gets no override: it would hide a later change to the file.
    for name in ("physics:centerOfMass", "physics:upperLimit", "physxCollision:contactOffset", "unlisted"):
        assert root.GetAttributeAtPath(f"/World/Bot.{name}") is None, name
    assert done == Converted(
        values=5,
        left=["/World/Bot.ovmcp:label", "/World/Bot/Pad/Shape.physxCollision:contactOffset"],
    )
    # Inside the instance, which no layer of the stage can override (Q5).
    assert _get(prim.GetChild("Pad").GetChild("Shape"), "physxCollision:contactOffset") == pytest.approx(0.03)


def test_a_default_and_samples_from_two_layers_are_each_converted_by_their_own_layer_s_units():
    # The file's samples, in metres, beat the default in millimetres of the file it references; Get() still reads
    # the millimetre default, so each is converted by its own layer's units (P1).
    millimetres = _units_layer(0.001, text='def Xform "Arm"\n{\n    float physics:upperLimit = 40\n}\n')
    metres = _units_layer(
        1.0,
        text=f'def Xform "Bot"\n{{\n    def "Arm" (prepend references = @{millimetres.identifier}@</Arm>)\n    {{\n'
        "        float physics:upperLimit.timeSamples = {\n            0: 0.04,\n        }\n    }\n}\n",
    )
    stage = _stage_of(0.01)
    prim = _robot(stage, metres)
    arm = prim.GetChild("Arm")

    _convert(stage, prim, Units(1.0, None))

    assert _get(arm, "physics:upperLimit", 0) == pytest.approx(4)
    assert _get(arm, "physics:upperLimit") == pytest.approx(4)


def test_a_robot_kit_dropped_and_saved_keeps_the_values_of_the_metre_file_it_references():
    # A Composer centimetre file whose robot references a metre file, Kit's converted values never saved (K3), put on
    # a metre stage: the metre file's values are in the stage's units already, and the centimetre file's own aren't
    # (the plan's P1).
    bot = _units_layer(1.0, text='def Xform "Bot"\n{\n    float3 physics:diagonalInertia = (0.1, 0.2, 0.3)\n}\n')
    cell = _units_layer(
        0.01,
        text=f'def Xform "Robot" (prepend references = @{bot.identifier}@</Bot>)\n{{\n'
        "    float physics:upperLimit = 4\n}\n",
    )
    stage = _stage_of(1.0)
    prim = _robot(stage, cell, "/Robot")

    _convert(stage, prim, Units(0.01, None))

    assert _get(prim, "physics:diagonalInertia") == pytest.approx((0.1, 0.2, 0.3))
    assert _get(prim, "physics:upperLimit") == pytest.approx(0.04)


def test_a_layer_that_says_no_units_takes_its_file_s_and_then_the_robot_file_s():
    # A sublayer, such as an Isaac Sim robot's configuration/ file, takes its own file's units; a file the robot
    # references that says none takes the robot file's, here centimetres, not the stage's.
    configuration = _units_layer(text='over "Bot"\n{\n    float physics:upperLimit = 4\n}\n')
    prop = _units_layer(text='def Xform "Prop"\n{\n    float physics:upperLimit = 2\n}\n')
    robot = _units_layer(
        0.01,
        text=f'def Xform "Bot"\n{{\n    def "Prop" (prepend references = @{prop.identifier}@</Prop>)\n'
        "    {\n    }\n}\n",
    )
    robot.subLayerPaths.append(configuration.identifier)
    stage = _stage_of(1.0)
    prim = _robot(stage, robot)

    _convert(stage, prim, Units(0.01, None))

    assert _get(prim, "physics:upperLimit") == pytest.approx(0.04)
    assert _get(prim.GetChild("Prop"), "physics:upperLimit") == pytest.approx(0.02)


def test_a_value_of_the_stage_s_own_layers_is_in_the_stage_s_units():
    stage = _stage_of(0.01)
    prim = _robot(stage, _units_layer(1.0, text='def Xform "Bot"\n{\n}\n'))
    prim.CreateAttribute("physics:upperLimit", Sdf.ValueTypeNames.Float).Set(5.0)

    assert _convert(stage, prim, Units(1.0, None)) == Converted(values=0, left=[])
    assert _get(prim, "physics:upperLimit") == 5.0


_SAMPLED_BESIDE_A_DEFAULT = """
def Xform "Bot"
{
    float physics:upperLimit = 0.02
    float physics:upperLimit.timeSamples = {
        0: 0,
        10: 0,
    }
}
"""


def test_a_default_written_takes_the_samples_beside_it_changed_or_not():
    # The samples are 0 and stay 0, but a default written into the stage's layer would beat them at every time,
    # where the file's samples beat its own default before (review E1).
    stage = _stage_of(0.01)
    prim = _robot(stage, _units_layer(1.0, text=_SAMPLED_BESIDE_A_DEFAULT))

    _convert(stage, prim, Units(1.0, None))

    assert [_get(prim, "physics:upperLimit", t) for t in (0, 5, 10)] == [0, 0, 0]
    assert _get(prim, "physics:upperLimit") == pytest.approx(2)


_SPECIALIZED = """
def Xform "Bot"
{
    def Xform "Base"
    {
        float physics:upperLimit = 0.5
    }

    def Xform "Arm" (
        specializes = </Bot/Base>
    )
    {
    }
}
"""


def test_a_value_reached_through_a_specializes_arc_is_converted_once():
    # A stage whose root layer says no metersPerUnit, which USD reads as centimetres. Base's converted value, once
    # written in the stage's layer, came to Arm through the arc USD implies there, and Arm read it as the file's and
    # converted it again, to 5000 (review E2).
    stage = Usd.Stage.CreateInMemory()
    prim = _robot(stage, _units_layer(1.0, text=_SPECIALIZED))

    _convert(stage, prim, Units(1.0, None))

    assert _get(prim.GetChild("Base"), "physics:upperLimit") == pytest.approx(50)
    assert _get(prim.GetChild("Arm"), "physics:upperLimit") == pytest.approx(50)


_BLOCKED_SAMPLE = """
def Xform "Bot"
{
    float physics:upperLimit.timeSamples = {
        0: None,
        10: 0.1,
    }
}
"""


def test_a_blocked_sample_stays_blocked():
    stage = _stage_of(0.01)
    prim = _robot(stage, _units_layer(1.0, text=_BLOCKED_SAMPLE))

    _convert(stage, prim, Units(1.0, None))

    assert _get(prim, "physics:upperLimit", 0) is None
    assert _get(prim, "physics:upperLimit", 10) == pytest.approx(10)


def test_a_value_from_value_clips_is_left_and_named():
    # A clip's samples come from a layer the stage doesn't hold, which no layer of the stage overrides sample by
    # sample.
    clip = _units_layer(
        text='over "Bot"\n{\n    float physics:upperLimit.timeSamples = {\n        0: 0.04,\n    }\n}\n'
    )
    bot = _units_layer(1.0, text='def Xform "Bot"\n{\n    float physics:upperLimit\n}\n')
    held = Usd.Stage.Open(bot)
    clips = Usd.ClipsAPI(held.GetPrimAtPath("/Bot"))
    clips.SetClipAssetPaths([Sdf.AssetPath(clip.identifier)])
    clips.SetClipPrimPath("/Bot")
    clips.SetClipActive([(0.0, 0)])
    clips.SetClipTimes([(0.0, 0.0)])
    stage = _stage_of(0.01)
    prim = _robot(stage, bot)

    assert _convert(stage, prim, Units(1.0, None)) == Converted(values=0, left=["/World/Bot.physics:upperLimit"])
    assert _get(prim, "physics:upperLimit", 0) == pytest.approx(0.04)
