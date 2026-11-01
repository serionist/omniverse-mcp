"""The turn that stands a referenced file of another up axis on the stage (#105), and the scale and the converted
values that bring a file of other units to the stage's (#112), which create_robot and create_prim share. Without Kit."""

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.metrics import (
    UNITS_OP,
    UP_AXIS_OP,
    Brought,
    Converted,
    Exponents,
    Factors,
    Frame,
    StepError,
    Table,
    Units,
    bring_to_stage,
    convert_units,
    file_up_axis,
    frame_of,
    layer_units,
    not_brought,
    scale_to_stage,
    stand_upright,
    unit_exponents,
    units_factors,
    up_axis_turn,
)
from ovmcp.core.usd import floats
from ovmcp.core.xform import add_local_op

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


# ---- the frame a prim lands in, and a file brought to it (#119) ----


def _box(
    up_axis: str | None = None,
    meters: float | None = None,
    turn: float | None = None,
    scale: float | None = None,
) -> Sdf.Layer:
    """A file whose default prim, /Box, holds a box 0.5 by 0.5 by 1, tall along the file's up axis, its base at the
    origin, with a contact offset of 0.02; its root holds Kit's turn and Kit's scale if asked, as a file Kit resolved
    and saved has."""
    layer = Sdf.Layer.CreateAnonymous("box.usda")
    held = Usd.Stage.Open(layer)
    if up_axis is not None:
        UsdGeom.SetStageUpAxis(held, up_axis)
    if meters is not None:
        UsdGeom.SetStageMetersPerUnit(held, meters)
    root = UsdGeom.Xform.Define(held, "/Box")
    if turn is not None:
        root.AddRotateXOp(opSuffix="unitsResolve").Set(turn)
    if scale is not None:
        root.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(scale, scale, scale))
    shape = UsdGeom.Cube.Define(held, "/Box/Shape")
    z = up_axis == "Z"
    shape.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0.5) if z else Gf.Vec3d(0, 0.5, 0))
    shape.AddScaleOp().Set(Gf.Vec3f(0.25, 0.25, 0.5) if z else Gf.Vec3f(0.25, 0.5, 0.25))
    shape.GetPrim().CreateAttribute("physxCollision:contactOffset", Sdf.ValueTypeNames.Float).Set(0.02)
    held.SetDefaultPrim(root.GetPrim())
    return layer


def _scene(up_axis: str, meters: float) -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, up_axis)
    UsdGeom.SetStageMetersPerUnit(stage, meters)
    UsdPhysics.SetStageKilogramsPerUnit(stage, 1.0)
    UsdGeom.Xform.Define(stage, "/World")
    return stage


def _placed(stage: Usd.Stage, path: str, layer: Sdf.Layer) -> Usd.Prim:
    prim = stage.DefinePrim(path)
    prim.GetReferences().AddReference(layer.identifier)
    return prim


def _bring(
    _stage: Usd.Stage, prim: Usd.Prim, layer: Sdf.Layer, table: Table | None = _small_table, noun: str = "file"
) -> Brought:
    return bring_to_stage(prim, layer, table, noun)


def _size(prim: Usd.Prim) -> list[float]:
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(prim)
    return [round(v, 6) for v in floats(box.ComputeAlignedRange().GetSize())]


def _brought_outer(stage: Usd.Stage, layer: Sdf.Layer) -> Usd.Prim:
    """layer's file at /World/Outer, brought to the stage as create_prim brings it."""
    outer = _placed(stage, "/World/Outer", layer)
    _bring(stage, outer, layer)
    return outer


def test_a_frame_without_units_ops_is_the_stage_s():
    # A prim's own scale is the user's: it scales what is under it as asked, and doesn't change the frame (N3).
    stage = _scene("Y", 0.01)
    parent = UsdGeom.Xform.Define(stage, "/World/Scaled")
    parent.AddScaleOp().Set(Gf.Vec3f(100, 100, 100))
    # An op's attribute out of the order does nothing, so it doesn't count either.
    parent.GetPrim().CreateAttribute(UNITS_OP, Sdf.ValueTypeNames.Double3).Set(Gf.Vec3d(100, 100, 100))

    assert frame_of(parent.GetPrim(), "Y", 0.01) == Frame("Y", 0.01, [])


def test_an_ancestor_that_brought_a_file_makes_the_frame_under_it():
    # A Z-up metre file brought to a Y-up centimetre stage: -90 and x100, so under it the frame is Z-up in metres.
    stage = _scene("Y", 0.01)
    _brought_outer(stage, _box("Z", 1.0))
    child = stage.DefinePrim("/World/Outer/Part")

    assert frame_of(child, "Y", 0.01) == Frame("Z", 1.0, ["/World/Outer"])


def test_two_ancestors_multiply_their_scales_and_add_their_turns():
    stage = _scene("Y", 0.01)
    outer = UsdGeom.Xform.Define(stage, "/World/A")
    outer.AddRotateXOp(opSuffix="unitsResolve").Set(-90.0)
    outer.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(100, 100, 100))
    inner = UsdGeom.Xform.Define(stage, "/World/A/B")
    inner.AddRotateXOp(opSuffix="unitsResolve").Set(90.0)
    inner.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(0.1, 0.1, 0.1))

    frame = frame_of(inner.GetPrim(), "Y", 0.01)

    assert frame.up_axis == "Y"
    assert frame.meters == pytest.approx(0.1)
    assert frame.prims == ["/World/A", "/World/A/B"]


@pytest.mark.parametrize(
    ("turn", "stage_axis", "up_axis"),
    [(-90.0, "Y", "Z"), (90.0, "Z", "Y"), (180.0, "Y", None), (-90.0, "Z", None)],
    ids=["z-in-y", "y-in-z", "upside-down", "sideways"],
)
def test_a_frame_s_up_axis_is_what_its_turn_stands_up(turn: float, stage_axis: str, up_axis: str | None):
    stage = _scene(stage_axis, 1.0)
    prim = UsdGeom.Xform.Define(stage, "/World/Turned")
    prim.AddRotateXOp(opSuffix="unitsResolve").Set(turn)

    assert frame_of(prim.GetPrim(), stage_axis, 1.0).up_axis == up_axis


def test_a_prim_that_resets_the_transform_stack_stops_the_walk():
    # The ops above it don't reach what is under it.
    stage = _scene("Y", 1.0)
    _brought_outer(stage, _box("Z", 1.0))
    reset = UsdGeom.Xform.Define(stage, "/World/Outer/Reset")
    reset.SetResetXformStack(True)

    assert frame_of(reset.GetPrim(), "Y", 1.0) == Frame("Y", 1.0, [])


def test_a_file_of_another_up_axis_and_units_is_turned_then_scaled_and_its_values_converted():
    stage = _scene("Y", 1.0)
    layer = _box("Z", 0.01)
    prim = _placed(stage, "/World/Box", layer)

    brought = _bring(stage, prim, layer)

    assert _names(prim) == [UP_AXIS_OP, UNITS_OP]
    assert brought.up_axis_turn == {"file": "Z", "stage": "Y", "degrees": -90.0, "op": -90.0, "op_name": UP_AXIS_OP}
    assert brought.units_scale == {
        "meters_per_unit": {"file": 0.01, "stage": 1.0},
        "kilograms_per_unit": None,
        "factor": 0.01,
        "op": [0.01, 0.01, 0.01],
        "op_name": UNITS_OP,
        "converted": 1,
        "left": [],
        "left_count": 0,
        "table": True,
    }
    assert brought.frame is None
    assert _size(stage.GetPrimAtPath("/World/Box/Shape")) == [0.005, 0.01, 0.005]
    assert _get(stage.GetPrimAtPath("/World/Box/Shape"), "physxCollision:contactOffset") == pytest.approx(0.0002)


def test_a_file_inside_an_asset_brought_to_the_stage_is_measured_against_its_frame():
    # U2, and Kit's own recursive test (K1, N1): the metre file under the metre asset needs no op of its own, and its
    # values are converted against the stage, as Kit converts them.
    stage = _scene("Y", 0.01)
    layer = _box("Z", 1.0)
    _brought_outer(stage, layer)
    inner = _placed(stage, "/World/Outer/Inner", layer)

    brought = _bring(stage, inner, layer)

    assert _names(inner) == []
    assert _size(stage.GetPrimAtPath("/World/Outer/Inner/Shape")) == _size(stage.GetPrimAtPath("/World/Outer/Shape"))
    assert _size(stage.GetPrimAtPath("/World/Outer/Inner/Shape")) == [50.0, 100.0, 50.0]
    assert _get(stage.GetPrimAtPath("/World/Outer/Inner/Shape"), "physxCollision:contactOffset") == pytest.approx(2.0)
    assert brought.up_axis_turn is None
    assert brought.frame == {"up_axis": "Z", "meters_per_unit": 1.0, "prims": ["/World/Outer"]}
    scaled = brought.units_scale
    assert scaled is not None
    assert scaled["meters_per_unit"] == {"file": 1.0, "stage": 0.01, "frame": 1.0}
    assert (scaled["factor"], scaled["op"], scaled["converted"]) == (None, None, 1)


def test_a_file_of_the_stage_s_axis_inside_a_turned_asset_is_stood_upright():
    # N2: Kit leaves this one lying along -Z; the plan's rule turns it back (Q2).
    stage = _scene("Y", 1.0)
    _brought_outer(stage, _box("Z", 1.0))
    layer = _box("Y", 1.0)
    inner = _placed(stage, "/World/Outer/Native", layer)

    brought = _bring(stage, inner, layer)

    assert brought.up_axis_turn == {
        "file": "Y",
        "stage": "Y",
        "degrees": 90.0,
        "op": 90.0,
        "op_name": UP_AXIS_OP,
        "frame": "Z",
    }
    size = _size(stage.GetPrimAtPath("/World/Outer/Native/Shape"))
    assert max(range(3), key=lambda i: size[i]) == 1, size
    assert brought.units_scale is None


def test_a_millimetre_file_in_a_metre_frame_on_a_centimetre_stage_names_the_frame_and_the_stage():
    # P3: the factor against the frame, the values against the stage.
    stage = _scene("Y", 0.01)
    _brought_outer(stage, _box("Y", 1.0))
    layer = _box("Y", 0.001)
    inner = _placed(stage, "/World/Outer/Part", layer)

    brought = _bring(stage, inner, layer)

    scaled = brought.units_scale
    assert scaled is not None
    assert scaled["meters_per_unit"] == {"file": 0.001, "stage": 0.01, "frame": 1.0}
    assert scaled["factor"] == pytest.approx(0.001)
    assert _get(stage.GetPrimAtPath("/World/Outer/Part/Shape"), "physxCollision:contactOffset") == pytest.approx(0.002)
    assert _size(stage.GetPrimAtPath("/World/Outer/Part/Shape")) == [0.05, 0.1, 0.05]


def test_a_file_of_the_stage_s_units_in_a_frame_of_others_is_scaled_and_nothing_converted():
    stage = _scene("Y", 1.0)
    _brought_outer(stage, _box("Y", 0.01))
    layer = _box("Y", 1.0)
    inner = _placed(stage, "/World/Outer/Part", layer)

    brought = _bring(stage, inner, layer)

    scaled = brought.units_scale
    assert scaled is not None
    assert (scaled["factor"], scaled["op"], scaled["converted"]) == (100.0, [100.0, 100.0, 100.0], None)
    assert _get(stage.GetPrimAtPath("/World/Outer/Part/Shape"), "physxCollision:contactOffset") == pytest.approx(0.02)
    assert _size(stage.GetPrimAtPath("/World/Outer/Part/Shape")) == [0.5, 1.0, 0.5]


def test_a_file_that_authors_neither_is_left_as_it_is_wherever_it_lands():
    stage = _scene("Y", 0.01)
    _brought_outer(stage, _box("Z", 1.0))
    layer = _box()
    inner = _placed(stage, "/World/Outer/Part", layer)

    assert _bring(stage, inner, layer) == Brought(None, None, None)
    assert _names(inner) == []
    assert stage.GetRootLayer().GetPrimAtPath("/World/Outer/Part/Shape") is None


def test_without_the_physx_schema_only_the_cameras_convert_and_the_answer_says_so():
    stage = _scene("Y", 0.01)
    layer = _units_layer(1.0, None, _BOT)
    prim = stage.DefinePrim("/World/Bot")
    prim.GetReferences().AddReference(layer.identifier, "/Bot")

    brought = _bring(stage, prim, layer, table=None)

    scaled = brought.units_scale
    assert scaled is not None
    assert (scaled["op"], scaled["converted"], scaled["table"]) == ([100.0, 100.0, 100.0], 1, False)
    assert _get(stage.GetPrimAtPath("/World/Bot/Eye"), "clippingRange") == Gf.Vec2f(100, 100000)
    assert _get(stage.GetPrimAtPath("/World/Bot"), "physics:density") == pytest.approx(1000.0)


@pytest.mark.parametrize("noun", ["file", "robot"])
def test_a_failure_while_converting_names_its_step(noun: str):
    # P2: bring_to_stage does every step, so the handler can't tell which failed; the error says.
    def broken(name: str, _prim: Usd.Prim) -> Exponents | None:
        raise KeyError(name)

    stage = _scene("Y", 0.01)
    layer = _box("Y", 1.0)
    prim = _placed(stage, "/World/Box", layer)

    with pytest.raises(StepError) as raised:
        _bring(stage, prim, layer, table=broken, noun=noun)

    assert raised.value.step == f"Converting the {noun}'s values to the stage's units"
    assert str(raised.value).startswith(f"Converting the {noun}'s values to the stage's units failed: KeyError: '")
    assert isinstance(raised.value.cause, KeyError)


def test_an_animated_held_op_is_refused_as_it_is():
    stage = _scene("Z", 1.0)
    layer = _box("Y", 1.0)
    held = Usd.Stage.Open(layer)
    UsdGeom.Xformable(held.GetPrimAtPath("/Box")).AddRotateXOp(opSuffix="unitsResolve").Set(-90.0, 1.0)
    prim = _placed(stage, "/World/Box", layer)

    with pytest.raises(ValueError, match="is animated"):
        _bring(stage, prim, layer)


def test_a_prim_brought_for_another_file_reports_the_file_added_to_it():
    # P1: the shelf brought in (-90, x0.01); a Y-up metre file on it would lie along -Z at 1/100.
    stage = _scene("Y", 1.0)
    shelf = _brought_outer(stage, _box("Z", 0.01))
    added = _box("Y", 1.0)
    shelf.GetReferences().AddReference(added.identifier)

    assert not_brought(shelf, added, added=True) == {
        "prim_path": "/World/Outer",
        "file": {"up_axis": "Y", "meters_per_unit": 1.0},
        "frame": {"up_axis": "Z", "meters_per_unit": 0.01},
        "values": None,
    }


def test_a_prim_brought_for_its_own_file_is_not_reported():
    stage = _scene("Y", 1.0)
    layer = _box("Z", 0.01)
    shelf = _brought_outer(stage, layer)

    assert not_brought(shelf, layer, added=False) is None


def test_a_file_kit_saved_is_reported_until_it_is_brought():
    # A Z-up metre box Kit dropped on a Y-up centimetre stage and saved: its root holds -90 and x100, in a Y-up
    # centimetre file. On a Z-up metre stage its content is upright and its size right only once brought.
    stage = _scene("Z", 1.0)
    layer = _box("Z", 1.0)
    saved = Sdf.Layer.CreateAnonymous("saved.usda")
    held = Usd.Stage.Open(saved)
    UsdGeom.SetStageUpAxis(held, "Y")
    UsdGeom.SetStageMetersPerUnit(held, 0.01)
    root = UsdGeom.Xform.Define(held, "/Box")
    root.AddRotateXOp(opSuffix="unitsResolve").Set(-90.0)
    root.AddScaleOp(UsdGeom.XformOp.PrecisionDouble, "unitsResolve").Set(Gf.Vec3d(100, 100, 100))
    root.GetPrim().GetReferences().AddReference(layer.identifier)
    held.SetDefaultPrim(root.GetPrim())
    prim = _placed(stage, "/World/Saved", saved)

    assert not_brought(prim, saved, added=False) == {
        "prim_path": "/World/Saved",
        "file": {"up_axis": "Z", "meters_per_unit": 1.0},
        "frame": {"up_axis": None, "meters_per_unit": 100.0},
        "values": None,
    }
    _bring(stage, prim, saved)
    assert not_brought(prim, saved, added=False) is None
    size = _size(stage.GetPrimAtPath("/World/Saved/Shape"))
    assert size == [0.5, 0.5, 1.0]


def test_a_reference_an_older_extension_left_is_reported_and_a_file_that_says_nothing_is_not():
    stage = _scene("Y", 1.0)
    layer = _box("Z", 1.0)
    prim = _placed(stage, "/World/Old", layer)
    plain = _box()
    other = _placed(stage, "/World/Plain", plain)

    assert not_brought(prim, layer, added=False) == {
        "prim_path": "/World/Old",
        "file": {"up_axis": "Z", "meters_per_unit": 1.0},
        "frame": {"up_axis": "Y", "meters_per_unit": 1.0},
        "values": None,
    }
    assert not_brought(other, plain, added=True) is None


def test_a_reference_added_to_a_prim_already_there_reports_the_values_it_leaves_in_the_file_s_units():
    # Review R2: a metre file under a robot scaled to metres on a centimetre stage sits right, but its contact offset
    # stays 0.02 where the stage reads 2; a file of other kilogramsPerUnit keeps its masses in its own.
    stage = _scene("Y", 0.01)
    _brought_outer(stage, _box("Y", 1.0))
    link = stage.DefinePrim("/World/Outer/Link", "Xform")
    metres = _box("Y", 1.0)
    link.GetReferences().AddReference(metres.identifier)
    grams = Sdf.Layer.CreateAnonymous("grams.usda")
    grams.pseudoRoot.SetInfo("kilogramsPerUnit", 0.001)
    plain = stage.DefinePrim("/World/Plain", "Xform")

    assert not_brought(link, metres, added=True) == {
        "prim_path": "/World/Outer/Link",
        "file": None,
        "frame": None,
        "values": {"meters_per_unit": {"file": 1.0, "stage": 0.01}, "kilograms_per_unit": None},
    }
    # Held from before, its values were converted when it was brought, or by no one this call can tell.
    assert not_brought(link, metres, added=False) is None
    assert not_brought(plain, grams, added=True) == {
        "prim_path": "/World/Plain",
        "file": None,
        "frame": None,
        "values": {"meters_per_unit": None, "kilograms_per_unit": {"file": 0.001, "stage": 1.0}},
    }


def _rooted(type_name: str) -> Sdf.Layer:
    """A Z-up centimetre file whose default prim is of type_name, "" for typeless, holding _box's box."""
    text = _box("Z", 0.01).ExportToString()
    layer = Sdf.Layer.CreateAnonymous("rooted.usda")
    layer.ImportFromString(text.replace('def Xform "Box"', " ".join(filter(None, ["def", type_name, '"Box"']))))
    return layer


@pytest.mark.parametrize("type_name", ["", "Scope"], ids=["typeless", "scope"])
def test_a_file_whose_root_has_no_transform_is_made_an_xform_and_brought(type_name: str):
    # Review R1: the ops landed on a prim that isn't Xformable, the answer said turned and scaled, and nothing moved.
    stage = _scene("Y", 1.0)
    layer = _rooted(type_name)
    prim = _placed(stage, "/World/Box", layer)

    brought = _bring(stage, prim, layer)

    assert prim.GetTypeName() == "Xform"
    assert _names(prim) == [UP_AXIS_OP, UNITS_OP]
    assert brought.up_axis_turn is not None
    assert _size(stage.GetPrimAtPath("/World/Box/Shape")) == [0.005, 0.01, 0.005]


def test_a_file_whose_root_is_a_material_gets_no_turn_or_scale():
    # A Material holds nothing a turn or a scale would move, and stays a Material.
    stage = _scene("Y", 1.0)
    layer = _rooted("Material")
    prim = _placed(stage, "/World/Look", layer)

    brought = _bring(stage, prim, layer)

    assert prim.GetTypeName() == "Material"
    assert _names(prim) == []
    assert brought.up_axis_turn is None
    scaled = brought.units_scale
    assert scaled is not None
    assert (scaled["op"], scaled["converted"]) == (None, 1)
