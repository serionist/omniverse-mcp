"""The transform writer every tool that places a prim goes through (#82), on usd-core: each part into the prim's own
ops, every other op kept, and a write that couldn't show refused with nothing written; and a camera aimed at a point,
in the layer that holds its ops."""

import math

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from ovmcp.core import xform
from ovmcp.core.xform import Parts, check_transform, set_local_transform

ORIGIN = Gf.Vec3d(0, 0, 0)


@pytest.fixture
def stage() -> Usd.Stage:
    return Usd.Stage.CreateInMemory()


def _ops(prim: Usd.Prim) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()]


def _local(prim: Usd.Prim) -> Gf.Matrix4d:
    return UsdGeom.Xformable(prim).GetLocalTransformation(Usd.TimeCode.Default())


def _rotation_matrix(rotation: Gf.Rotation) -> Gf.Matrix4d:
    return Gf.Matrix4d().SetRotate(rotation)


def _close(a: Gf.Matrix4d, b: Gf.Matrix4d, eps: float = 1e-5) -> bool:
    return Gf.IsClose(a, b, eps)


def _value(prim: Usd.Prim, name: str):
    return prim.GetAttribute(name).Get()


def _root_spec(stage: Usd.Stage, path: str) -> bool:
    return bool(stage.GetRootLayer().GetPrimAtPath(path))


# ---- which ops a part goes into ----


def test_a_prim_with_no_ops_gets_the_ops_the_bridge_always_gave(stage):
    prim = UsdGeom.Xform.Define(stage, "/P").GetPrim()

    set_local_transform(prim, position=[1, 2, 3], rotation=[10, 20, 30], scale=2)

    assert _ops(prim) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
    ops = UsdGeom.Xformable(prim).GetOrderedXformOps()
    assert [op.GetPrecision() for op in ops] == [
        UsdGeom.XformOp.PrecisionDouble,
        UsdGeom.XformOp.PrecisionFloat,
        UsdGeom.XformOp.PrecisionFloat,
    ]
    assert _value(prim, "xformOp:rotateXYZ") == Gf.Vec3f(10, 20, 30)
    assert _value(prim, "xformOp:scale") == Gf.Vec3f(2, 2, 2)


def test_a_quaternion_on_a_prim_with_no_ops_adds_an_orient(stage):
    prim = UsdGeom.Xform.Define(stage, "/P").GetPrim()

    set_local_transform(prim, rotation=[0, 0, 0, 2])

    assert _ops(prim) == ["xformOp:orient"]
    assert _value(prim, "xformOp:orient") == Gf.Quatd(0, 0, 0, 1)  # normalised


def test_kits_translate_orient_scale_take_each_part_and_keep_their_kind(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp().Set(Gf.Vec3d(9, 9, 9))
    xf.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Quatd(1, 0, 0, 0))
    xf.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(1, 1, 1))
    prim = xf.GetPrim()

    set_local_transform(prim, position=[1, 2, 3], rotation=[0, 90, 0], scale=[1, 2, 3])

    assert _ops(prim) == ["xformOp:translate", "xformOp:orient", "xformOp:scale"]
    assert _value(prim, "xformOp:translate") == Gf.Vec3d(1, 2, 3)
    expected = Gf.Rotation(Gf.Vec3d.YAxis(), 90).GetQuat()
    assert Gf.IsClose(_value(prim, "xformOp:orient").GetImaginary(), expected.GetImaginary(), 1e-6)
    assert _value(prim, "xformOp:scale") == Gf.Vec3d(1, 2, 3)


def test_euler_angles_into_a_rotate_xyz_op_are_kept_as_given(stage):
    # A round trip through Gf.Rotation would store [0, 120, 0] as about [180, 60, 180].
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddRotateXYZOp()
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=[0, 120, 0])

    assert _value(prim, "xformOp:rotateXYZ") == Gf.Vec3f(0, 120, 0)


def test_a_quaternion_into_an_orient_op_is_kept_as_given(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddOrientOp()
    prim = xf.GetPrim()
    quat = Gf.Quatd(0.5, 0.5, 0.5, 0.5)

    set_local_transform(prim, rotation=[0.5, 0.5, 0.5, 0.5])

    assert _value(prim, "xformOp:orient") == quat


@pytest.mark.parametrize("order", ["XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"])
@pytest.mark.parametrize("given", [[10, 20, 30], [0.9, 0.1, 0.3, 0.2]], ids=["euler", "quaternion"])
def test_a_rotation_goes_into_any_euler_op_in_its_order(stage, order, given):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddXformOp(getattr(UsdGeom.XformOp, f"TypeRotate{order}"))
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=given)

    assert _ops(prim) == [f"xformOp:rotate{order}"]
    want = check_transform(rotation=given).rotation
    assert want is not None
    assert _close(_local(prim), _rotation_matrix(want), 1e-4)


@pytest.mark.parametrize("given", [[10, 20, 30], [0.9, 0.1, 0.3, 0.2]], ids=["euler", "quaternion"])
def test_kits_three_single_axis_ops_take_the_rotation_split_into_their_axes(stage, given):
    # Kit's TransformPrimCommand writes [rotateZ, rotateY, rotateX].
    xf = UsdGeom.Xform.Define(stage, "/P")
    for axis in "ZYX":
        xf.AddXformOp(getattr(UsdGeom.XformOp, f"TypeRotate{axis}"))
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=given)

    assert _ops(prim) == ["xformOp:rotateZ", "xformOp:rotateY", "xformOp:rotateX"]
    want = check_transform(rotation=given).rotation
    assert want is not None
    assert _close(_local(prim), _rotation_matrix(want), 1e-4)


def test_a_single_axis_op_alone_is_replaced_in_its_place(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
    xf.AddRotateYOp().Set(30.0)
    xf.AddScaleOp()
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=[10, 20, 30])

    assert _ops(prim) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
    assert _value(prim, "xformOp:rotateXYZ") == Gf.Vec3f(10, 20, 30)


def test_other_rotate_ops_together_are_replaced_by_one_in_the_first_ones_place(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp()
    xf.AddOrientOp()
    xf.AddRotateXOp().Set(45.0)
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=[0, 0, 0.6, 0.8])

    assert _ops(prim) == ["xformOp:translate", "xformOp:orient"]
    assert _close(_local(prim), _rotation_matrix(Gf.Rotation(Gf.Quatd(0, 0, 0.6, 0.8)).GetInverse().GetInverse()))


def test_a_pivot_stays_around_the_rotation_and_the_position_goes_in_the_translate_op(stage):
    # 0.2.3 read the inverse pivot, a translate op too, as the position, and dropped the pivot.
    xf = UsdGeom.Xform.Define(stage, "/P")
    prim = xf.GetPrim()
    common = UsdGeom.XformCommonAPI(xf)
    common.SetTranslate(Gf.Vec3d(1, 0, 0))
    common.SetPivot(Gf.Vec3f(0, 5, 0))
    common.SetRotate(Gf.Vec3f(0, 0, 90))
    before = _ops(prim)

    set_local_transform(prim, position=[4, 0, 0], scale=2)

    assert _ops(prim) == [*before[:-1], "xformOp:scale", before[-1]]
    assert before[-1] == "!invert!xformOp:translate:pivot"
    assert _value(prim, "xformOp:translate") == Gf.Vec3d(4, 0, 0)
    assert _value(prim, "xformOp:translate:pivot") == Gf.Vec3f(0, 5, 0)


@pytest.mark.parametrize(
    ("precision", "kind"),
    [
        (UsdGeom.XformOp.PrecisionHalf, Gf.Vec3h),
        (UsdGeom.XformOp.PrecisionFloat, Gf.Vec3f),
        (UsdGeom.XformOp.PrecisionDouble, Gf.Vec3d),
    ],
)
def test_a_value_is_written_in_its_ops_precision(stage, precision, kind):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp(precision)
    prim = xf.GetPrim()

    set_local_transform(prim, position=[1, 2, 3])

    value = _value(prim, "xformOp:translate")
    assert isinstance(value, kind)
    assert value == kind(1, 2, 3)


def test_an_op_added_over_an_attribute_out_of_the_order_takes_its_precision(stage):
    # AddXformOp raises for an attribute of its name in another precision.
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddOrientOp(UsdGeom.XformOp.PrecisionFloat).Set(Gf.Quatf(1, 0, 0, 0))
    xf.ClearXformOpOrder()
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=[0, 0, 0, 1])

    assert _ops(prim) == ["xformOp:orient"]
    assert _value(prim, "xformOp:orient") == Gf.Quatf(0, 0, 0, 1)


def test_a_prim_placed_by_one_matrix_has_its_matrix_changed(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    placed = (
        Gf.Matrix4d().SetScale(Gf.Vec3d(2, 2, 2))
        * Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d.ZAxis(), 30))
        * Gf.Matrix4d().SetTranslate(Gf.Vec3d(1, 2, 3))
    )
    xf.AddTransformOp().Set(placed)
    prim = xf.GetPrim()

    set_local_transform(prim, position=[5, 6, 7])
    assert _ops(prim) == ["xformOp:transform"]
    moved = _value(prim, "xformOp:transform")
    assert moved.ExtractTranslation() == Gf.Vec3d(5, 6, 7)
    assert _close(moved.ExtractRotationMatrix(), placed.ExtractRotationMatrix(), 1e-9)

    set_local_transform(prim, rotation=[0, 0, 90], scale=[1, 1, 3])
    turned = Gf.Transform()
    turned.SetMatrix(_value(prim, "xformOp:transform"))
    assert Gf.IsClose(turned.GetScale(), Gf.Vec3d(1, 1, 3), 1e-6)
    assert Gf.IsClose(
        turned.GetRotation().GetQuat().GetImaginary(), Gf.Rotation(Gf.Vec3d.ZAxis(), 90).GetQuat().GetImaginary(), 1e-6
    )
    assert turned.GetTranslation() == Gf.Vec3d(5, 6, 7)


def test_a_matrix_among_other_ops_takes_the_part_with_no_op_of_its_own(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
    xf.AddTransformOp().Set(Gf.Matrix4d(1))
    prim = xf.GetPrim()

    set_local_transform(prim, position=[2, 0, 0], rotation=[0, 0, 90])

    assert _ops(prim) == ["xformOp:translate", "xformOp:transform"]
    assert _value(prim, "xformOp:translate") == Gf.Vec3d(2, 0, 0)
    assert _close(_value(prim, "xformOp:transform"), _rotation_matrix(Gf.Rotation(Gf.Vec3d.ZAxis(), 90)))


def test_a_singular_matrix_takes_a_position_but_no_rotation_or_scale(stage):
    # Factor fails on it and clamps, so the rotation would be lost while the answer said success.
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTransformOp().Set(Gf.Matrix4d(1))
    prim = xf.GetPrim()
    set_local_transform(prim, scale=0)

    with pytest.raises(ValueError, match="singular"):
        set_local_transform(prim, scale=1)
    with pytest.raises(ValueError, match="singular"):
        set_local_transform(prim, rotation=[0, 0, 90])
    set_local_transform(prim, position=[1, 2, 3])
    assert _value(prim, "xformOp:transform").ExtractTranslation() == Gf.Vec3d(1, 2, 3)


def test_an_op_added_goes_before_kits_units_resolve_ops(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.AddTranslateOp()
    xf.AddScaleOp(opSuffix="unitsResolve").Set(Gf.Vec3f(100, 100, 100))
    prim = xf.GetPrim()

    set_local_transform(prim, rotation=[0, 0, 90], scale=2)

    assert _ops(prim) == [
        "xformOp:translate",
        "xformOp:rotateXYZ",
        "xformOp:scale",
        "xformOp:scale:unitsResolve",
    ]


def test_reset_xform_stack_stays(stage):
    xf = UsdGeom.Xform.Define(stage, "/P")
    xf.SetResetXformStack(True)
    prim = xf.GetPrim()

    set_local_transform(prim, position=[1, 2, 3])

    assert xf.GetResetXformStack()
    assert list(xf.GetXformOpOrderAttr().Get()) == ["!resetXformStack!", "xformOp:translate"]


# ---- refusals, with nothing written ----


@pytest.mark.parametrize(
    ("parts", "says"),
    [
        ({"position": [1, 2]}, "position must be"),
        ({"position": [1, "2", 3]}, "position must be"),
        ({"position": [1, 2, math.inf]}, "position must be"),
        ({"rotation": [1, 2]}, "rotation must be"),
        ({"rotation": [0, 0, 0, 0]}, "no quaternion"),
        ({"scale": [1, 2]}, "scale must be"),
        ({"scale": True}, "scale must be"),
    ],
)
def test_a_malformed_part_is_refused_before_any_prim_is_touched(parts, says):
    with pytest.raises(ValueError, match=says):
        check_transform(**parts)


def test_a_write_the_session_layer_outranks_is_refused(stage):
    # Kit's own camera lives in the session layer; 0.2.3's writes into the root layer moved nothing.
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        cam = UsdGeom.Camera.Define(stage, "/Cam")
        cam.AddTranslateOp().Set(Gf.Vec3d(0, 0, 5))

    with pytest.raises(ValueError, match="held by Kit's session layer, which outranks the stage's root layer"):
        set_local_transform(cam.GetPrim(), position=[1, 2, 3])
    assert not _root_spec(stage, "/Cam")


@pytest.mark.parametrize("where", ["root", "session"])
def test_samples_in_the_written_layer_or_a_stronger_one_hide_the_write(stage, where):
    xf = UsdGeom.Xform.Define(stage, "/P")
    op = xf.AddTranslateOp()
    layer = stage.GetRootLayer() if where == "root" else stage.GetSessionLayer()
    with Usd.EditContext(stage, layer):
        op.Set(Gf.Vec3d(1, 0, 0), 1.0)

    with pytest.raises(ValueError, match="hidden by its time samples"):
        set_local_transform(xf.GetPrim(), position=[5, 5, 5])
    assert op.GetAttr().Get() is None  # no default value written, which the samples would hide
    assert op.GetAttr().Get(1.0) == Gf.Vec3d(1, 0, 0)


def test_samples_only_in_a_weaker_layer_would_be_frozen(stage):
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    xf = UsdGeom.Xform.Define(held, "/Bot")
    xf.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)
    prim = stage.DefinePrim("/Bot")
    prim.GetReferences().AddReference(asset.identifier, "/Bot")

    with pytest.raises(ValueError, match="override the animation and freeze it"):
        set_local_transform(prim, position=[5, 5, 5])
    assert not stage.GetRootLayer().GetAttributeAtPath("/Bot.xformOp:translate")


def test_samples_in_a_weaker_layer_under_a_default_already_held_are_let_through(stage):
    # The root layer's default already froze the animation, so a new value freezes nothing more.
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Bot").AddTranslateOp().Set(Gf.Vec3d(1, 0, 0), 1.0)
    prim = stage.DefinePrim("/Bot")
    prim.GetReferences().AddReference(asset.identifier, "/Bot")
    prim.GetAttribute("xformOp:translate").Set(Gf.Vec3d(3, 0, 0))

    set_local_transform(prim, position=[5, 5, 5])

    assert prim.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(5, 5, 5)


def test_a_prim_inside_an_instance_is_refused_naming_the_instance(stage):
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Bot")
    UsdGeom.Cube.Define(held, "/Bot/Link")
    instance = stage.DefinePrim("/World/Bot")
    instance.GetReferences().AddReference(asset.identifier, "/Bot")
    instance.SetInstanceable(True)

    with pytest.raises(ValueError, match="inside the instance /World/Bot"):
        set_local_transform(stage.GetPrimAtPath("/World/Bot/Link"), position=[1, 2, 3])


def test_a_prim_with_no_transform_is_refused(stage):
    prim = stage.DefinePrim("/Looks/Mat", "Material")
    with pytest.raises(ValueError, match="no transform"):
        set_local_transform(prim, position=[1, 2, 3])


def test_layers_are_named_by_their_place_never_an_anonymous_identifier(stage, tmp_path):
    sub = Sdf.Layer.CreateNew(str(tmp_path / "props.usda"))
    stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    assert xform.layer_name(stage, stage.GetSessionLayer()) == "Kit's session layer"
    assert xform.layer_name(stage, stage.GetRootLayer()) == "the stage's root layer"
    assert xform.layer_name(stage, sub).endswith("props.usda")


# ---- what position means, for clone_prim ----


def test_position_of_reads_the_translate_op_then_the_matrix_then_the_origin(stage):
    a = UsdGeom.Xform.Define(stage, "/A")
    a.AddTranslateOp(opSuffix="pivot").Set(Gf.Vec3d(9, 9, 9))
    a.AddTranslateOp().Set(Gf.Vec3d(1, 2, 3))
    b = UsdGeom.Xform.Define(stage, "/B")
    b.AddTransformOp().Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(4, 5, 6)))
    c = UsdGeom.Xform.Define(stage, "/C")

    assert xform.position_of(a.GetPrim()) == Gf.Vec3d(1, 2, 3)
    assert xform.position_of(b.GetPrim()) == Gf.Vec3d(4, 5, 6)
    assert xform.position_of(c.GetPrim()) == ORIGIN


# ---- the camera ----


def _looks(matrix: Gf.Matrix4d, eye: Gf.Vec3d, target: Gf.Vec3d) -> float:
    forward = matrix.TransformDir(Gf.Vec3d(0, 0, -1)).GetNormalized()
    return math.degrees(math.acos(max(-1.0, min(1.0, Gf.Dot(forward, (target - eye).GetNormalized())))))


def _orthonormal(matrix: Gf.Matrix4d) -> bool:
    rotation = matrix.ExtractRotationMatrix()
    return Gf.IsClose(rotation * rotation.GetTranspose(), Gf.Matrix3d(1), 1e-9)


@pytest.mark.parametrize("up_axis", ["Y", "Z"])
@pytest.mark.parametrize(
    "eye",
    [Gf.Vec3d(6, 3, 5), Gf.Vec3d(2, 8, -1), Gf.Vec3d(2, -1, 8), Gf.Vec3d(2, 0.5, -9), Gf.Vec3d(2.0001, 8, -1)],
    ids=["oblique", "above-on-y", "above-on-z", "level", "nearly-above"],
)
def test_look_at_points_minus_z_at_the_target_from_any_side(up_axis, eye):
    target = Gf.Vec3d(2, 0.5, -1)
    matrix = xform.look_at(eye, target, up_axis)
    assert _looks(matrix, eye, target) < 1e-6
    assert matrix.ExtractTranslation() == eye
    assert _orthonormal(matrix)


def test_look_at_keeps_the_stages_up_upward(stage):
    matrix = xform.look_at(Gf.Vec3d(6, 3, 5), Gf.Vec3d(0, 0, 0), "Y")
    assert Gf.Dot(matrix.TransformDir(Gf.Vec3d(0, 1, 0)), Gf.Vec3d(0, 1, 0)) > 0.9


def test_look_at_refuses_a_target_on_the_camera():
    with pytest.raises(ValueError, match="nothing to look at"):
        xform.look_at(Gf.Vec3d(1, 2, 3), Gf.Vec3d(1, 2, 3), "Y")


def _kit_camera(stage: Usd.Stage) -> Usd.Prim:
    """A camera as Kit makes its own: defined in the session layer, which holds its ops and its centre of interest."""
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        cam = UsdGeom.Camera.Define(stage, "/OmniverseKit_Persp")
        cam.AddTranslateOp().Set(Gf.Vec3d(0, 0, 10))
        cam.AddRotateXYZOp().Set(Gf.Vec3f(0, 0, 0))
        cam.AddScaleOp().Set(Gf.Vec3f(1, 1, 1))
        prim = cam.GetPrim()
        prim.CreateAttribute("omni:kit:centerOfInterest", Sdf.ValueTypeNames.Vector3d).Set(Gf.Vec3d(0, 0, -10))
    return prim


def test_aim_writes_a_kit_camera_in_the_session_layer_and_keeps_its_ops(stage):
    camera = _kit_camera(stage)
    eye, target = Gf.Vec3d(6, 3, 5), Gf.Vec3d(2, 0.5, -1)

    assert xform.camera_layer(camera).identifier == stage.GetSessionLayer().identifier
    xform.aim(camera, eye, target)
    xform.set_centre_of_interest(camera, target, xform.camera_layer(camera))

    assert xform.aim_error(camera, eye, target) is None
    assert _ops(camera) == ["xformOp:translate", "xformOp:rotateXYZ", "xformOp:scale"]
    assert not _root_spec(stage, "/OmniverseKit_Persp")
    coi = camera.GetAttribute("omni:kit:centerOfInterest").Get()
    assert Gf.IsClose(coi, Gf.Vec3d(0, 0, -(target - eye).GetLength()), 1e-6)


def test_aim_puts_a_camera_under_a_moved_parent_where_asked(stage):
    rig = UsdGeom.Xform.Define(stage, "/Rig")
    rig.AddTranslateOp().Set(Gf.Vec3d(10, 0, 0))
    rig.AddRotateYOp().Set(90.0)
    camera = UsdGeom.Camera.Define(stage, "/Rig/Cam").GetPrim()
    eye, target = Gf.Vec3d(1, 2, 3), Gf.Vec3d(-4, 0, 0)

    xform.aim(camera, eye, target)

    assert xform.aim_error(camera, eye, target) is None


def test_aim_puts_a_camera_that_resets_its_parents_transform_where_asked(stage):
    rig = UsdGeom.Xform.Define(stage, "/Rig")
    rig.AddTranslateOp().Set(Gf.Vec3d(10, 0, 0))
    cam = UsdGeom.Camera.Define(stage, "/Rig/Cam")
    cam.SetResetXformStack(True)
    eye, target = Gf.Vec3d(1, 2, 3), Gf.Vec3d(0, 0, 0)

    xform.aim(cam.GetPrim(), eye, target)

    assert xform.aim_error(cam.GetPrim(), eye, target) is None
    assert cam.GetResetXformStack()


def test_aim_error_says_what_is_off(stage):
    camera = UsdGeom.Camera.Define(stage, "/Cam").GetPrim()
    eye, target = Gf.Vec3d(0, 0, 10), Gf.Vec3d(0, 0, 0)
    set_local_transform(camera, position=[0, 0, 10])
    assert xform.aim_error(camera, eye, target) is None  # -Z faces the origin

    assert "not [1" in (xform.aim_error(camera, Gf.Vec3d(1, 0, 10), target) or "")
    set_local_transform(camera, rotation=[0, 90, 0])
    assert "degrees off" in (xform.aim_error(camera, eye, target) or "")
    set_local_transform(camera, rotation=[0, 0, 0], scale=3.4e38)
    assert "scale went from" in (xform.aim_error(camera, eye, target, (1.0, 1.0, 1.0)) or "")


def test_aim_error_takes_a_float_translate_far_from_the_origin(stage):
    camera = UsdGeom.Camera.Define(stage, "/Cam")
    camera.AddTranslateOp(UsdGeom.XformOp.PrecisionFloat).Set(Gf.Vec3f(100000.1, 0, 0))
    eye = Gf.Vec3d(100000.1, 0, 0)
    assert xform.aim_error(camera.GetPrim(), eye, eye + Gf.Vec3d(0, 0, -0.5)) is None


def test_a_snapshot_puts_back_what_a_call_broke(stage):
    camera = _kit_camera(stage)
    snapshot = xform.Snapshot.take(camera)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        # What Isaac Sim's call left straight down a Y-up stage
        camera.GetAttribute("xformOp:translate").Set(Gf.Vec3d(0, 0, 0))
        camera.GetAttribute("xformOp:scale").Set(Gf.Vec3f(3.4e38, 3.4e38, 3.4e38))

    snapshot.restore(camera, stage.GetSessionLayer())

    assert camera.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(0, 0, 10)
    assert camera.GetAttribute("xformOp:scale").Get() == Gf.Vec3f(1, 1, 1)


def test_a_camera_with_no_centre_of_interest_is_left_without_one(stage):
    camera = UsdGeom.Camera.Define(stage, "/Cam").GetPrim()
    xform.set_centre_of_interest(camera, Gf.Vec3d(0, 0, 0), stage.GetRootLayer())
    assert not camera.GetAttribute("omni:kit:centerOfInterest")


def test_parts_given_as_parts_are_written_as_they_are(stage):
    prim = UsdGeom.Xform.Define(stage, "/P").GetPrim()
    xform.write_transform(prim, Parts(position=Gf.Vec3d(1, 2, 3)))
    assert _value(prim, "xformOp:translate") == Gf.Vec3d(1, 2, 3)


def _camera_up(matrix: Gf.Matrix4d) -> Gf.Vec3d:
    return matrix.TransformDir(Gf.Vec3d(0, 1, 0))


@pytest.mark.parametrize(
    ("up_axis", "above", "front"),
    [
        ("Y", Gf.Vec3d(0, 1, 0), Gf.Vec3d(0, 0, 1)),
        ("Z", Gf.Vec3d(0, 0, 1), Gf.Vec3d(0, 1, 0)),
    ],
)
def test_look_at_straight_down_and_up_tips_the_cameras_up_as_it_comes_over_from_the_front(up_axis, above, front):
    # The bottom view had its up minus front, rolled 180 degrees from the front view's.
    top = xform.look_at(above * 5, Gf.Vec3d(0, 0, 0), up_axis)
    bottom = xform.look_at(-above * 5, Gf.Vec3d(0, 0, 0), up_axis)

    assert Gf.IsClose(_camera_up(top), -front, 1e-9)
    assert Gf.IsClose(_camera_up(bottom), front, 1e-9)
    assert _orthonormal(top)
    assert _orthonormal(bottom)


def test_a_snapshot_of_a_bare_camera_clears_what_the_call_authored(stage):
    # No order before, so restore wrote none and the FLT_MAX scale stayed.
    camera = UsdGeom.Camera.Define(stage, "/Cam").GetPrim()
    layer = stage.GetSessionLayer()
    snapshot = xform.Snapshot.take(camera)
    with Usd.EditContext(stage, layer):
        xformable = UsdGeom.Xformable(camera)
        xformable.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
        xformable.AddScaleOp().Set(Gf.Vec3f(3.4e38, 3.4e38, 3.4e38))

    snapshot.restore(camera, layer)

    assert not camera.GetAttribute("xformOp:scale")
    assert not camera.GetAttribute("xformOp:translate")
    assert UsdGeom.Xformable(camera).GetXformOpOrderAttr().Get() is None
    assert xform.aim_error(camera, Gf.Vec3d(0, 0, 0), Gf.Vec3d(0, 0, -1), (1.0, 1.0, 1.0)) is None
