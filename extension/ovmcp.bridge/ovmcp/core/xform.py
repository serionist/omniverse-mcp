"""Every transform the bridge writes (#82): a prim's position, rotation and scale, into the prim's own xform ops, and a
camera aimed at a point.

Each part has its own ops, found by name: the unsuffixed translate op, every unsuffixed rotate op (orient, an Euler
triple, a single axis) and the unsuffixed scale op. A prim with an unsuffixed matrix op (xformOp:transform) takes a part
that has no op of its own into the matrix, as Kit's TransformPrimCommand does. Every other op, a pivot pair, Kit's
metrics assembler's :unitsResolve ops, an inverse op, stays as it is and where it is, and so does !resetXformStack!.

A write that couldn't show is refused before anything is written: another of the stage's own layers outranks the one
written, or an op it would write has time samples. Needs pxr, not Kit: the tests run it on usd-core.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from pxr import Gf, Sdf, Tf, Usd, UsdGeom

from .usd import Vec, add_xform_op, attribute_has_default, factors, floats, is_a, prim_spec, xform_ops

_DEFAULT = Usd.TimeCode.Default()
_AXES = {"X": Gf.Vec3d.XAxis(), "Y": Gf.Vec3d.YAxis(), "Z": Gf.Vec3d.ZAxis()}

# Each Euler op's axes, the first named turning first (most local): rotateXYZ turns about X, then Y, then Z.
_EULER = {
    UsdGeom.XformOp.TypeRotateXYZ: "XYZ",
    UsdGeom.XformOp.TypeRotateXZY: "XZY",
    UsdGeom.XformOp.TypeRotateYXZ: "YXZ",
    UsdGeom.XformOp.TypeRotateYZX: "YZX",
    UsdGeom.XformOp.TypeRotateZXY: "ZXY",
    UsdGeom.XformOp.TypeRotateZYX: "ZYX",
}
_SINGLE = {
    UsdGeom.XformOp.TypeRotateX: "X",
    UsdGeom.XformOp.TypeRotateY: "Y",
    UsdGeom.XformOp.TypeRotateZ: "Z",
}

# How far an aimed camera's -Z axis may point from its target, and the kinds of op this module adds, as the bridge has
# always added them, though Kit's own prims get double precision and orient (#82's E1).
AIM_DEGREES = 0.5
_NEW_PRECISION = {
    UsdGeom.XformOp.TypeTranslate: UsdGeom.XformOp.PrecisionDouble,
    UsdGeom.XformOp.TypeRotateXYZ: UsdGeom.XformOp.PrecisionFloat,
    UsdGeom.XformOp.TypeOrient: UsdGeom.XformOp.PrecisionDouble,
    UsdGeom.XformOp.TypeScale: UsdGeom.XformOp.PrecisionFloat,
}


@dataclass(frozen=True)
class Parts:
    """A transform's parts, checked; None leaves a part as it is.

    `euler` and `quat` keep the rotation as it was given, for an op of its own kind to take unchanged: a round trip
    through Gf.Rotation would store [0, 120, 0] as about [180, 60, 180].
    """

    position: Gf.Vec3d | None = None
    rotation: Gf.Rotation | None = None
    euler: tuple[float, float, float] | None = None
    quat: Gf.Quatd | None = None
    scale: Gf.Vec3d | None = None


def _numbers(value: object) -> list[float] | None:
    """value as finite floats, or None when it isn't a list of numbers."""
    if not isinstance(value, (list, tuple)):
        return None
    items = cast("Sequence[object]", value)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in items):
        return None
    numbers = [float(cast("float", v)) for v in items]
    return numbers if all(math.isfinite(v) for v in numbers) else None


def euler_rotation(angles: Sequence[float]) -> Gf.Rotation:
    """Euler angles in degrees as a rotateXYZ op means them: about X first, then Y, then Z."""
    return Gf.Rotation(_AXES["X"], angles[0]) * Gf.Rotation(_AXES["Y"], angles[1]) * Gf.Rotation(_AXES["Z"], angles[2])


def check_transform(position: object = None, rotation: object = None, scale: object = None) -> Parts:
    """The parts a tool was given, checked before any prim is touched; ValueError with the reason."""
    pos = rot = quat = scl = None
    euler: tuple[float, float, float] | None = None
    if position is not None:
        values = _numbers(position)
        if values is None or len(values) != 3:
            raise ValueError(f"position must be [x, y, z], 3 numbers, got {position!r}")
        pos = Gf.Vec3d(*values)
    if rotation is not None:
        values = _numbers(rotation)
        if values is not None and len(values) == 3:
            euler = (values[0], values[1], values[2])
            rot = euler_rotation(euler)
        elif values is not None and len(values) == 4:
            given = Gf.Quatd(values[0], Gf.Vec3d(values[1], values[2], values[3]))
            if given.GetLength() == 0:
                raise ValueError("rotation [0, 0, 0, 0] is no quaternion: give [w, x, y, z], not all zero")
            quat = given.GetNormalized()
            rot = Gf.Rotation(quat)
        else:
            raise ValueError(
                f"rotation must be Euler angles [rx, ry, rz] in degrees or a quaternion [w, x, y, z], got {rotation!r}"
            )
    if scale is not None:
        values = _numbers([scale]) if isinstance(scale, (int, float)) and not isinstance(scale, bool) else None
        values = values * 3 if values is not None else _numbers(scale)
        if values is None or len(values) != 3:
            raise ValueError(f"scale must be a number or [sx, sy, sz], got {scale!r}")
        scl = Gf.Vec3d(*values)
    return Parts(position=pos, rotation=rot, euler=euler, quat=quat, scale=scl)


def layer_name(stage: Usd.Stage, layer: Sdf.Layer) -> str:
    """A layer as an answer names it: never by an anonymous layer's identifier, which tells the reader nothing."""
    if layer.identifier == stage.GetSessionLayer().identifier:
        return "Kit's session layer"
    if layer.identifier == stage.GetRootLayer().identifier:
        return f"the stage's root layer ({layer.realPath})" if layer.realPath else "the stage's root layer"
    # An anonymous layer's display name is the tag it was made with, such as asset.usda.
    return layer.realPath or layer.GetDisplayName() or layer.identifier


def _rank(stage: Usd.Stage) -> dict[str, int]:
    """Each of the stage's own layers by strength, strongest first: the session layers, the root, its sublayers."""
    return {layer.identifier: i for i, layer in enumerate(stage.GetLayerStack(includeSessionLayers=True))}


def _blocker(prim: Usd.Prim, attr: Usd.Attribute, layer: Sdf.Layer) -> str | None:
    """Why a value written to attr in layer wouldn't show, or None.

    The strongest opinion decides: a stronger layer's value outranks the write; time samples in the written layer or a
    stronger one hide its default value; samples only in a weaker layer, such as an animated asset's, are overridden by
    it, which freezes the animation. A default already held at or above the written layer froze it before, so the
    write freezes nothing new and samples below it don't refuse.
    """
    stage = prim.GetStage()
    rank = _rank(stage)
    target = rank.get(layer.identifier, len(rank))
    name = attr.GetName()
    stack = attr.GetPropertyStack(_DEFAULT)
    frozen = any(
        rank.get(spec.layer.identifier, len(rank) + 1) <= target and attribute_has_default(spec) for spec in stack
    )
    for spec in stack:
        # A layer outside the stage's own, a referenced file's, is weaker than all of them.
        where = rank.get(spec.layer.identifier, len(rank) + 1)
        samples = spec.layer.GetNumTimeSamplesForPath(spec.path)
        if samples and where <= target:
            return (
                f"{prim.GetPath()}'s {name} is animated in {layer_name(stage, spec.layer)}: a value set now would be "
                "hidden by its time samples"
            )
        if samples and not frozen:
            return (
                f"{prim.GetPath()}'s {name} is animated in {layer_name(stage, spec.layer)}: a value set in "
                f"{layer_name(stage, layer)} would override the animation and freeze it"
            )
        if where < target and attribute_has_default(spec):
            return (
                f"{prim.GetPath()}'s {name} is held by {layer_name(stage, spec.layer)}, which outranks "
                f"{layer_name(stage, layer)}, where it would be written: nothing would change"
            )
    return None


@dataclass
class _New:
    """An op to add: its type and precision, and its attribute's name."""

    op_type: Tf.Type
    precision: UsdGeom.XformOp.Precision
    name: str


_Item = UsdGeom.XformOp | _New


def _own(op: UsdGeom.XformOp) -> bool:
    """An op without a suffix of its own, nor inverse: the one a part's value goes into."""
    return not op.IsInverseOp() and len(op.SplitName()) == 2


def _is_scale(item: _Item) -> bool:
    return isinstance(item, UsdGeom.XformOp) and _own(item) and item.GetOpType() == UsdGeom.XformOp.TypeScale


def _is_inverse(item: _Item) -> bool:
    return isinstance(item, UsdGeom.XformOp) and item.IsInverseOp()


def _is_units(item: _Item) -> bool:
    """Kit's metrics assembler's op, which stays most local."""
    return isinstance(item, UsdGeom.XformOp) and item.SplitName()[-1] == "unitsResolve"


def _before(order: list[_Item], *tests: Callable[[_Item], bool]) -> int:
    """Where an op goes: before the first item any test picks, else last."""
    found = [i for i, item in enumerate(order) if any(test(item) for test in tests)]
    return min(found) if found else len(order)


def _vector(value: Vec, precision: UsdGeom.XformOp.Precision) -> Gf.Vec3d | Gf.Vec3f | Gf.Vec3h:
    if precision == UsdGeom.XformOp.PrecisionDouble:
        return Gf.Vec3d(value[0], value[1], value[2])
    if precision == UsdGeom.XformOp.PrecisionFloat:
        return Gf.Vec3f(value[0], value[1], value[2])
    return Gf.Vec3h(value[0], value[1], value[2])


def _quaternion(quat: Gf.Quatd, precision: UsdGeom.XformOp.Precision) -> Gf.Quatd | Gf.Quatf | Gf.Quath:
    imaginary = floats(quat.GetImaginary())
    if precision == UsdGeom.XformOp.PrecisionDouble:
        return quat
    if precision == UsdGeom.XformOp.PrecisionFloat:
        return Gf.Quatf(quat.GetReal(), Gf.Vec3f(imaginary[0], imaginary[1], imaginary[2]))
    return Gf.Quath(quat.GetReal(), Gf.Vec3h(imaginary[0], imaginary[1], imaginary[2]))


def _euler_angles(rotation: Gf.Rotation, axes: str) -> Gf.Vec3d:
    """The angles, by axis as (x, y, z), of an Euler op whose axes are `axes`, first turning first."""
    first, second, third = axes
    # Gf.Rotation.Decompose names the axes the other way round (#82's U4).
    angles = floats(rotation.Decompose(_AXES[third], _AXES[second], _AXES[first]))
    by_axis = {third: angles[0], second: angles[1], first: angles[2]}
    return Gf.Vec3d(by_axis["X"], by_axis["Y"], by_axis["Z"])


@dataclass
class _Plan:
    """What a write does: the order of ops, whether it changed, and each value, by op."""

    order: list[_Item]
    changed: bool = False
    values: list[tuple[_Item, object]] = field(default_factory=list[tuple[_Item, object]])


def _new_op(prim: Usd.Prim, op_type: Tf.Type) -> _New:
    """An op to add, in the precision of an attribute of its name that is already there out of the order (#82's U5)."""
    name = f"xformOp:{UsdGeom.XformOp.GetOpTypeToken(op_type)}"
    there = prim.GetAttribute(name)
    precision = UsdGeom.XformOp(there).GetPrecision() if there else _NEW_PRECISION[op_type]
    return _New(op_type, precision, name)


def _plan_rotation(
    prim: Usd.Prim, parts: Parts, rotation: Gf.Rotation, rotate: list[UsdGeom.XformOp], plan: _Plan
) -> None:
    if len(rotate) == 1 and rotate[0].GetOpType() == UsdGeom.XformOp.TypeOrient:
        quat = parts.quat if parts.quat is not None else rotation.GetQuat()
        plan.values.append((rotate[0], _quaternion(quat, rotate[0].GetPrecision())))
        return
    if len(rotate) == 1 and rotate[0].GetOpType() in _EULER:
        op = rotate[0]
        if parts.euler is not None and op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
            angles = Gf.Vec3d(*parts.euler)
        else:
            angles = _euler_angles(rotation, _EULER[op.GetOpType()])
        plan.values.append((op, _vector(angles, op.GetPrecision())))
        return
    axes = "".join(_SINGLE.get(op.GetOpType(), "?") for op in rotate)
    if len(rotate) == 3 and sorted(axes) == ["X", "Y", "Z"]:
        # Kit's TransformPrimCommand writes [rotateZ, rotateY, rotateX]: the ops listed first turn last.
        first, second, third = axes[::-1]
        angles = floats(_euler_angles(rotation, first + second + third))
        by_axis = {"X": angles[0], "Y": angles[1], "Z": angles[2]}
        plan.values += [(op, by_axis[axis]) for op, axis in zip(rotate, axes, strict=True)]
        return
    # A single axis can't hold any rotation, and other rotate ops would compose with it: one op takes their place.
    op_type = UsdGeom.XformOp.TypeOrient if parts.euler is None else UsdGeom.XformOp.TypeRotateXYZ
    kept = next((op for op in rotate if op.GetOpType() == op_type), None)
    item: _Item = kept if kept is not None else _new_op(prim, op_type)
    at = plan.order.index(rotate[0])
    plan.order = [o for o in plan.order if not any(o is op for op in rotate)]
    plan.order.insert(at, item)
    plan.changed = True
    _plan_new_rotation(item, parts, rotation, plan)


def _plan_new_rotation(item: _Item, parts: Parts, rotation: Gf.Rotation, plan: _Plan) -> None:
    """The value of a rotation op the write adds or puts in the others' place: the rotation's own kind."""
    precision = item.precision if isinstance(item, _New) else item.GetPrecision()
    op_type = item.op_type if isinstance(item, _New) else item.GetOpType()
    if op_type == UsdGeom.XformOp.TypeOrient:
        quat = parts.quat if parts.quat is not None else rotation.GetQuat()
        plan.values.append((item, _quaternion(quat, precision)))
    else:
        angles = Gf.Vec3d(*parts.euler) if parts.euler else _euler_angles(rotation, "XYZ")
        plan.values.append((item, _vector(angles, precision)))


def _matrix(prim: Usd.Prim, op: UsdGeom.XformOp, parts: Parts, position: bool, rotation: bool, scale: bool) -> object:
    """The matrix op's new value, with the parts that have no op of their own."""
    held = op.Get()
    matrix = Gf.Matrix4d(cast("Gf.Matrix4d", held)) if held is not None else Gf.Matrix4d(1)
    if rotation or scale:
        if not factors(matrix):
            raise ValueError(
                f"{prim.GetPath()}'s xformOp:transform is singular, as a scale of 0 leaves it, so it has no rotation "
                "or scale to change: set its position, or give it a whole new matrix with execute_script"
            )
        factored = Gf.Transform()
        factored.SetMatrix(matrix)
        if rotation and parts.rotation is not None:
            factored.SetRotation(parts.rotation)
        if scale and parts.scale is not None:
            factored.SetScale(parts.scale)
        matrix = factored.GetMatrix()
    if position and parts.position is not None:
        matrix.SetTranslateOnly(parts.position)
    return matrix


def _plan(prim: Usd.Prim, parts: Parts, layer: Sdf.Layer) -> _Plan:
    """What writing parts into prim's ops takes, or ValueError with why it can't show."""
    if prim.IsInstanceProxy():
        instance = prim.GetParent()
        while instance and not instance.IsInstance():
            instance = instance.GetParent()
        raise ValueError(
            f"{prim.GetPath()} is inside the instance {instance.GetPath()}, whose prims can't be changed one by one"
        )
    if not is_a(prim, UsdGeom.Xformable):
        raise ValueError(f"{prim.GetPath()} is a {prim.GetTypeName() or 'typeless prim'}, which has no transform")
    xformable = UsdGeom.Xformable(prim)
    ordered = xform_ops(xformable)
    own = [op for op in ordered if _own(op)]
    translate = next((op for op in own if op.GetOpType() == UsdGeom.XformOp.TypeTranslate), None)
    rotate = [op for op in own if op.GetOpType() in _EULER or op.GetOpType() in _SINGLE]
    rotate += [op for op in own if op.GetOpType() == UsdGeom.XformOp.TypeOrient]
    rotate.sort(key=ordered.index)
    scale = next((op for op in own if op.GetOpType() == UsdGeom.XformOp.TypeScale), None)
    matrix = next((op for op in own if op.GetOpType() == UsdGeom.XformOp.TypeTransform), None)

    order: list[_Item] = list(ordered)
    plan = _Plan(order=order)
    into_matrix = {"position": False, "rotation": False, "scale": False}
    if parts.position is not None:
        if translate is not None:
            plan.values.append((translate, _vector(parts.position, translate.GetPrecision())))
        elif matrix is not None:
            into_matrix["position"] = True
        else:
            item = _new_op(prim, UsdGeom.XformOp.TypeTranslate)
            plan.order.insert(0, item)
            plan.changed = True
            plan.values.append((item, _vector(parts.position, item.precision)))
    if parts.rotation is not None:
        if rotate:
            _plan_rotation(prim, parts, parts.rotation, rotate, plan)
        elif matrix is not None:
            into_matrix["rotation"] = True
        else:
            op_type = UsdGeom.XformOp.TypeOrient if parts.euler is None else UsdGeom.XformOp.TypeRotateXYZ
            item = _new_op(prim, op_type)
            plan.order.insert(_before(plan.order, _is_scale, _is_inverse, _is_units), item)
            plan.changed = True
            _plan_new_rotation(item, parts, parts.rotation, plan)
    if parts.scale is not None:
        if scale is not None:
            plan.values.append((scale, _vector(parts.scale, scale.GetPrecision())))
        elif matrix is not None:
            into_matrix["scale"] = True
        else:
            item = _new_op(prim, UsdGeom.XformOp.TypeScale)
            plan.order.insert(_before(plan.order, _is_inverse, _is_units), item)
            plan.changed = True
            plan.values.append((item, _vector(parts.scale, item.precision)))
    if matrix is not None and any(into_matrix.values()):
        plan.values.append((matrix, _matrix(prim, matrix, parts, **into_matrix)))

    attributes = [xformable.GetXformOpOrderAttr()] if plan.changed else []
    for item, _value in plan.values:
        attr = prim.GetAttribute(item.name) if isinstance(item, _New) else item.GetAttr()
        if attr:
            attributes.append(attr)
    for attr in attributes:
        why = _blocker(prim, attr, layer)
        if why:
            raise ValueError(why)
    return plan


def _edit_layer(prim: Usd.Prim, layer: Sdf.Layer | None) -> Sdf.Layer:
    return layer if layer is not None else prim.GetStage().GetEditTarget().GetLayer()


def check_writable(prim: Usd.Prim, parts: Parts, layer: Sdf.Layer | None = None) -> None:
    """ValueError when set_local_transform would refuse parts for prim; nothing is written."""
    _plan(prim, parts, _edit_layer(prim, layer))


def write_transform(prim: Usd.Prim, parts: Parts, layer: Sdf.Layer | None = None) -> None:
    """Writes parts into prim's own ops in layer, the edit target's when None; ValueError, with nothing written, when
    the write couldn't show."""
    target = _edit_layer(prim, layer)
    plan = _plan(prim, parts, target)
    xformable = UsdGeom.Xformable(prim)
    stage = prim.GetStage()
    with Usd.EditContext(stage, Usd.EditTarget(target)):
        made: dict[int, UsdGeom.XformOp] = {}
        for item in plan.order:
            if isinstance(item, _New):
                there = prim.GetAttribute(item.name)
                made[id(item)] = (
                    UsdGeom.XformOp(there) if there else add_xform_op(xformable, item.op_type, item.precision)
                )
        if plan.changed:
            final = [made[id(item)] if isinstance(item, _New) else item for item in plan.order]
            xformable.SetXformOpOrder(final, xformable.GetResetXformStack())
        for item, value in plan.values:
            op = made[id(item)] if isinstance(item, _New) else item
            op.Set(value)


def set_local_transform(
    prim: Usd.Prim,
    position: object = None,
    rotation: object = None,
    scale: object = None,
    layer: Sdf.Layer | None = None,
) -> None:
    """Sets prim's position, rotation or scale relative to its parent, each into the prim's own ops (the module's
    docstring); a part left None stays. ValueError with the reason, before anything is written."""
    write_transform(prim, check_transform(position, rotation, scale), layer)


def position_of(prim: Usd.Prim) -> Gf.Vec3d:
    """What `position` means for prim: its translate op's value, else its matrix's translation, else the origin."""
    ops = [op for op in xform_ops(UsdGeom.Xformable(prim)) if _own(op)]
    for op_type in (UsdGeom.XformOp.TypeTranslate, UsdGeom.XformOp.TypeTransform):
        op = next((o for o in ops if o.GetOpType() == op_type), None)
        value = op.Get() if op is not None else None
        if value is not None and op_type == UsdGeom.XformOp.TypeTranslate:
            return Gf.Vec3d(*floats(cast("Vec", value)))
        if value is not None:
            return cast("Gf.Matrix4d", value).ExtractTranslation()
    return Gf.Vec3d(0, 0, 0)


# ---------------------------------------------------------------------------
# The camera
# ---------------------------------------------------------------------------


def look_at(eye: Gf.Vec3d, target: Gf.Vec3d, up_axis: str) -> Gf.Matrix4d:
    """A camera's world matrix at eye, its -Z axis on target, its up as near the stage's up axis as it can be.

    Straight along the up axis the stage's up can't orient it, so the front axis (look_at_prim's azimuth 0: +Z on a
    Y-up stage, +Y on a Z-up one) does: the camera's up is minus front from above and plus front from below, which is
    where it tends as it comes over from the front.
    """
    forward = target - eye
    if forward.GetLength() <= 1e-9 * max(1.0, eye.GetLength()):
        raise ValueError(f"the camera's position {_short(eye)} is its target: there is nothing to look at")
    back = -forward.GetNormalized()
    up = _AXES["Z"] if up_axis == "Z" else _AXES["Y"]
    front = _AXES["Y"] if up_axis == "Z" else _AXES["Z"]
    along = Gf.Dot(back, up)
    reference = up
    if abs(along) > 0.999:
        # From above the camera's up tips away from the viewer, from below towards them.
        reference = -front if along > 0 else front
    right = Gf.Cross(reference, back).GetNormalized()
    camera_up = Gf.Cross(back, right)
    matrix = Gf.Matrix4d(1)
    for row, (v, w) in enumerate(((right, 0.0), (camera_up, 0.0), (back, 0.0), (eye, 1.0))):
        x, y, z = floats(v)
        matrix.SetRow(row, Gf.Vec4d(x, y, z, w))
    return matrix


def camera_layer(camera: Usd.Prim) -> Sdf.Layer:
    """Where a camera's transform is written: the layer of the strongest opinion on its xformOpOrder among the stage's
    own layers, when that outranks the edit target, as Kit's own cameras' session layer does (#82's E1, E4); else the
    edit target. A write under the session layer's opinions moves nothing."""
    stage = camera.GetStage()
    edit = stage.GetEditTarget().GetLayer()
    rank = _rank(stage)
    for spec in UsdGeom.Xformable(camera).GetXformOpOrderAttr().GetPropertyStack(_DEFAULT):
        where = rank.get(spec.layer.identifier)
        if where is not None:
            return spec.layer if where < rank.get(edit.identifier, len(rank)) else edit
    return edit


def aim(camera: Usd.Prim, eye: Gf.Vec3d, target: Gf.Vec3d, layer: Sdf.Layer | None = None) -> None:
    """Puts camera at eye looking at target, in its parent's space, through its own ops; ValueError when it can't."""
    world = look_at(eye, target, UsdGeom.GetStageUpAxis(camera.GetStage()))
    xformable = UsdGeom.Xformable(camera)
    if xformable.GetResetXformStack():
        local = world
    else:
        local = world * xformable.ComputeParentToWorldTransform(_DEFAULT).GetInverse()
    factored = Gf.Transform()
    factored.SetMatrix(local)
    rotation = factored.GetRotation()
    parts = Parts(position=local.ExtractTranslation(), rotation=rotation, quat=rotation.GetQuat())
    write_transform(camera, parts, layer if layer is not None else camera_layer(camera))


def world_scale(prim: Usd.Prim) -> tuple[float, float, float]:
    """The lengths of prim's world axes."""
    matrix = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(_DEFAULT)
    return (matrix.GetRow3(0).GetLength(), matrix.GetRow3(1).GetLength(), matrix.GetRow3(2).GetLength())


def aim_error(
    camera: Usd.Prim, eye: Gf.Vec3d, target: Gf.Vec3d, scale: tuple[float, float, float] | None = None
) -> str | None:
    """Why camera isn't at eye looking at target, or with another world scale than `scale`; None when it is."""
    matrix = UsdGeom.Xformable(camera).ComputeLocalToWorldTransform(_DEFAULT)
    if not all(math.isfinite(v) for row in range(4) for v in floats(matrix.GetRow(row), 4)):
        return "its transform isn't finite"
    at = matrix.ExtractTranslation()
    # Relative and absolute: a float translate far from the origin is out by more than 1e-4 of a short distance.
    tolerance = 1e-4 * (target - eye).GetLength() + 1e-6 * eye.GetLength()
    if (at - eye).GetLength() > tolerance:
        return f"it is at {_short(at)}, not {_short(eye)}"
    looks = matrix.TransformDir(Gf.Vec3d(0, 0, -1))
    if looks.GetLength() == 0:
        return "it has no direction"
    cosine = Gf.Dot(looks.GetNormalized(), (target - eye).GetNormalized())
    degrees = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
    if degrees > AIM_DEGREES:
        return f"it looks {degrees:.1f} degrees off the target"
    if scale is not None:
        now = world_scale(camera)
        if not all(math.isclose(a, b, rel_tol=1e-3) for a, b in zip(now, scale, strict=True)):
            return f"its scale went from {_short(scale)} to {_short(now)}"
    return None


@dataclass(frozen=True)
class Snapshot:
    """A prim's xform ops as they compose now: the order and each op's value, to put back after a call that broke
    them (Isaac Sim's set_camera_view looking straight down a Y-up stage, #82's E5)."""

    order: object
    values: tuple[tuple[str, object], ...]
    names: frozenset[str] = frozenset()

    @classmethod
    def take(cls, prim: Usd.Prim) -> "Snapshot":
        xformable = UsdGeom.Xformable(prim)
        values = tuple((op.GetAttr().GetName(), op.GetAttr().Get()) for op in xform_ops(xformable))
        names = frozenset(name for name in prim.GetPropertyNames() if name.startswith("xformOp:"))
        return cls(order=xformable.GetXformOpOrderAttr().Get(), values=values, names=names)

    def restore(self, prim: Usd.Prim, layer: Sdf.Layer) -> None:
        """Puts the ops back in layer. A bare camera had no order and no ops, and the call authored both, so its order
        opinion is cleared and so is every op attribute it added: a FLT_MAX scale left standing would fail the check."""
        with Usd.EditContext(prim.GetStage(), Usd.EditTarget(layer)):
            if self.order is not None:
                UsdGeom.Xformable(prim).GetXformOpOrderAttr().Set(self.order)
            else:
                UsdGeom.Xformable(prim).GetXformOpOrderAttr().Clear()
            for name, value in self.values:
                if value is not None:
                    prim.GetAttribute(name).Set(value)
        spec = prim_spec(layer, prim.GetPath())
        if spec is None:
            return
        for added in [p for p in spec.properties if p.name.startswith("xformOp:") and p.name not in self.names]:
            spec.RemoveProperty(added)


def set_centre_of_interest(camera: Usd.Prim, target: Gf.Vec3d, layer: Sdf.Layer) -> None:
    """Puts Kit's centre of interest, which its viewport orbits about, on target, in the camera's own space, as
    ViewportCameraState does. A camera without the attribute is left without it."""
    attr = camera.GetAttribute("omni:kit:centerOfInterest")
    if not attr:
        return
    world = UsdGeom.Xformable(camera).ComputeLocalToWorldTransform(_DEFAULT)
    local = world.GetInverse().Transform(target)
    with Usd.EditContext(camera.GetStage(), Usd.EditTarget(layer)):
        attr.Set(Gf.Vec3d(*floats(local)))


def _short(v: Vec | Sequence[float]) -> str:
    return "[" + ", ".join(f"{float(v[i]):.4g}" for i in range(3)) + "]"
