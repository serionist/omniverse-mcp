"""A referenced file's up axis and units brought to the stage's, as Kit's metrics assembler brings a dropped file:
the turn that stands a file of another up axis upright (#105), and the scale and the converted values that bring a
file of other units to the stage's (#112). create_robot and create_prim share them.

Kit-free, so unit-tested without Kit: the PhysX schema's table of units, which only Kit ships, comes in as an argument.
"""

import math
import re
from collections.abc import Callable
from typing import NamedTuple, cast

from pxr import Gf, Sdf, Tf, Usd, UsdGeom, UsdPhysics

from .usd import attribute_spec, floats, is_a, xform_ops
from .xform import add_local_op

# The op Kit's metrics assembler writes to stand a referenced file of another up axis on the stage: a turn about X,
# outside the file's content and inside the prim's own ops (omni.usd.metrics.assembler's referenceTests).
UP_AXIS_OP = "xformOp:rotateX:unitsResolve"
_TURNS = {("Z", "Y"): -90.0, ("Y", "Z"): 90.0}


def file_up_axis(layer: Sdf.Layer) -> str | None:
    """The up axis the file's root layer authors, or None: USD's fallback, Y, is a guess about a file that doesn't say,
    and turning on it would lay down a robot that stood."""
    root = layer.pseudoRoot
    return str(root.GetInfo("upAxis")) if root.HasInfo("upAxis") else None


def up_axis_turn(file_axis: str | None, stage_axis: str) -> float | None:
    """The degrees about X that stand a file of file_axis up on a stage of stage_axis: -90 for a Z-up file on a Y-up
    stage, +90 the other way, None when they agree or the file doesn't say."""
    return _TURNS.get((file_axis, stage_axis)) if file_axis else None


def stand_upright(prim: Usd.Prim, degrees: float) -> float:
    """Turns prim by degrees about X in UP_AXIS_OP, in the edit target's layer, and gives the op's value after.

    A prim whose ops hold the op already, such as a file Kit resolved and saved, gets the sum: that op turned the
    file's content to the file's own up axis, and the turn to the stage's is still owed. A new op goes where Kit puts
    it, before the first inverse op, else last, so a pivot pair stays around it.
    """
    xformable = UsdGeom.Xformable(prim)
    order = xform_ops(xformable)
    held = next((op for op in order if op.GetOpName() == UP_AXIS_OP), None)
    if held is not None:
        attr = held.GetAttr()
        if attr.GetNumTimeSamples():
            raise ValueError(f"{prim.GetPath()}'s {UP_AXIS_OP} is animated, so it can't be turned upright")
        value = float(cast("float", attr.Get() or 0.0)) + degrees
        attr.Set(value)
        return value
    add_local_op(prim, UsdGeom.XformOp.TypeRotateX, "unitsResolve").GetAttr().Set(degrees)
    return degrees


# ---- bringing a file of other units to the stage's (#112) ----

# The op Kit's metrics assembler writes to scale a referenced file of other metersPerUnit to the stage, beside the turn.
UNITS_OP = "xformOp:scale:unitsResolve"
# Units within this of each other are the same: 0.3 / 0.30000000000000004 isn't a conversion.
_SAME = 1e-9
_DEFAULT = Usd.TimeCode.Default()


class Units(NamedTuple):
    """metersPerUnit and kilogramsPerUnit: what a layer authors, each None where it authors none, or the stage's."""

    meters: float | None
    kilograms: float | None


class Factors(NamedTuple):
    """What a length and a mass in the file's units are multiplied by in the stage's."""

    distance: float
    mass: float


class Exponents(NamedTuple):
    """A value's units as powers of mass and of distance: the first two of the PhysX schema's table's five."""

    mass: int
    distance: int


class Converted(NamedTuple):
    """What convert_units did: how many values it converted, and the paths of those it left in the file's units."""

    values: int
    left: list[str]


# A value's exponents by its attribute's name and its prim, as the PhysX schema's table gives them; None for one it
# doesn't hold or can't tell for that prim.
Table = Callable[[str, Usd.Prim], Exponents | None]


def _units_value(root: Sdf.PrimSpec, key: str) -> float | None:
    if not root.HasInfo(key):
        return None
    value = float(cast("float", root.GetInfo(key)))
    # A unit of 0, below 0 or infinite would collapse or blow up the robot: taken as not said.
    return value if math.isfinite(value) and value > 0 else None


def layer_units(layer: Sdf.Layer) -> Units:
    """The units the layer's root authors. A file that says none is taken in the stage's units, as Kit's metrics
    assembler takes it, not in USD's fallback, centimetres, which would shrink a hand-written metre robot."""
    root = layer.pseudoRoot
    return Units(_units_value(root, "metersPerUnit"), _units_value(root, "kilogramsPerUnit"))


def _ratio(value: float | None, stage: float | None) -> float:
    """value over stage, 1 when either is unknown or they agree."""
    if value is None or stage is None or stage <= 0:
        return 1.0
    ratio = value / stage
    return 1.0 if abs(ratio - 1.0) <= _SAME else ratio


def units_factors(file: Units, stage: Units) -> Factors | None:
    """The file's units over the stage's, 1 for one the file doesn't author; None when both agree."""
    factors = Factors(_ratio(file.meters, stage.meters), _ratio(file.kilograms, stage.kilograms))
    return None if factors == (1.0, 1.0) else factors


def scale_to_stage(prim: Usd.Prim, factor: float) -> list[float]:
    """Scales prim by factor in UNITS_OP, in the edit target's layer, and gives the op's three values after.

    A new op is double, as Kit writes it, and goes where Kit puts it: after create_robot's turn, before the first
    inverse op, else last. A prim whose ops hold the op already, such as a robot Kit dropped on a stage of other units
    and saved, gets it multiplied: that op brought the file's content to the saved file's units, and the scale to the
    stage's is still owed.
    """
    xformable = UsdGeom.Xformable(prim)
    held = next((op for op in xform_ops(xformable) if op.GetOpName() == UNITS_OP), None)
    if held is None:
        op = add_local_op(prim, UsdGeom.XformOp.TypeScale, "unitsResolve", UsdGeom.XformOp.PrecisionDouble)
        attr, before = op.GetAttr(), [1.0, 1.0, 1.0]
    else:
        attr = held.GetAttr()
        if attr.GetNumTimeSamples():
            raise ValueError(f"{prim.GetPath()}'s {UNITS_OP} is animated, so it can't be scaled to the stage's units")
        current = attr.Get()
        before = [1.0, 1.0, 1.0] if current is None else floats(cast("Gf.Vec3d", current))
    after = [v * factor for v in before]
    # A tuple, which USD casts to the op's own precision: a held op keeps its own.
    attr.Set((after[0], after[1], after[2]))
    return after


# Kit's camera rules (omni.usd.metrics.assembler.usdgeom) convert these two, which UsdGeomCamera holds in scene units.
# The focal length and the apertures are tenths of a scene unit, which renderers correct for, so they stay.
_CAMERA_DISTANCES = frozenset({"focusDistance", "clippingRange"})
_ANGULAR_GAIN = re.compile(r"drive:(angular|rotX|rotY|rotZ):physics:(stiffness|damping)")


def _force_drive(prim: Usd.Prim, instance: str) -> bool:
    """Whether the drive is of type force, as the PhysX schema's units.py tells its variants apart: a type that
    isn't there is acceleration."""
    kind = prim.GetAttribute(f"drive:{instance}:physics:type")
    return bool(kind.IsValid()) and kind.Get() == UsdPhysics.Tokens.force


def unit_exponents(name: str, prim: Usd.Prim, table: Table) -> Exponents | None:
    """A value's exponents: the camera's two distances, an angular acceleration drive's gains, then table's.

    An acceleration drive's gains hold no mass and no distance: PhysX scales them by the joint's inertia, so a
    stiffness is degrees per second squared per degree. The PhysX schema's table says so of its linear ones and keeps
    the force drive's square metres on its angular ones, which would make the drive 10^4 times too stiff on a
    centimetre stage. test_27c checks live that PhysX holds the same gains on a metre and a centimetre stage.
    """
    if name in _CAMERA_DISTANCES:
        return Exponents(mass=0, distance=1)
    gain = _ANGULAR_GAIN.fullmatch(name)
    if gain is not None and not _force_drive(prim, gain[1]):
        return Exponents(mass=0, distance=0)
    return table(name, prim)


def _holds(layer: Sdf.Layer, path: Sdf.Path, samples: bool) -> bool:
    if samples:
        return layer.GetNumTimeSamplesForPath(path) > 0
    spec = attribute_spec(layer, path)
    return spec is not None and spec.HasDefaultValue()


def _value_units(attr: Usd.Attribute, info: Usd.ResolveInfo, samples: bool, file: Units, stage: Units) -> Units:
    """The units a value is authored in: its own layer's, else its layer stack root's, as a sublayer takes its
    file's, else the robot file's. Not the robot file's alone: a robot Kit dropped and saved leaves its values in the
    metre file it references, which the saved file's units would convert a second time. Kit's assembler takes one
    layer's units for every value under the prim it resolves, and gets that case wrong. A value of the stage's own
    layers is in the stage's units."""
    node = info.GetNode()
    # The stage's own layers, whether the value is the prim's own or comes through an arc USD implies into them.
    if node.layerStack == node.GetRootNode().layerStack:
        return stage
    stack = node.layerStack
    path = node.path.AppendProperty(attr.GetName())
    own = next((layer for layer in stack.layers if _holds(layer, path, samples)), None)
    root = cast("Sdf.Layer", stack.identifier.rootLayer)
    said = [layer_units(layer) for layer in (own, root) if layer is not None]
    meters = next((u.meters for u in said if u.meters is not None), file.meters)
    kilograms = next((u.kilograms for u in said if u.kilograms is not None), file.kilograms)
    return Units(meters, kilograms)


def _factor(units: Units, stage: Units, exponents: Exponents) -> float:
    factor = _ratio(units.meters, stage.meters) ** exponents.distance
    factor *= _ratio(units.kilograms, stage.kilograms) ** exponents.mass
    return 1.0 if abs(factor - 1.0) <= _SAME else factor


_VECTORS = (Gf.Vec2d, Gf.Vec2f, Gf.Vec2h, Gf.Vec3d, Gf.Vec3f, Gf.Vec3h, Gf.Vec4d, Gf.Vec4f, Gf.Vec4h)


class _UnconvertibleError(Exception):
    """A value convert_units can't multiply, or whose source it can't write over."""


def _times(value: object, factor: float) -> object:
    """value times factor: a number or a Gf vector; a blocked sample stays blocked."""
    if value is None:
        return Sdf.ValueBlock()
    if isinstance(value, float):
        return value * factor
    if isinstance(value, _VECTORS):
        return cast("Gf.Vec3d", value) * factor
    raise _UnconvertibleError


def _changes(old: object, new: object) -> bool:
    return not isinstance(new, Sdf.ValueBlock) and new != old


def _writes(attr: Usd.Attribute, exponents: Exponents, file: Units, stage: Units) -> list[tuple[Usd.TimeCode, object]]:
    """What converting attr writes: the default, when a default is what resolves at default time and it changes, and
    every sample, when samples are what resolve at other times and one changes or the default is written. All read
    before any is written: a stronger layer's first sample hides every sample of the file's, and a default written
    into the stage's layer beats the file's samples at every time. Raises _UnconvertibleError for a value from value
    clips or a spline, or of a type that doesn't multiply."""
    default: tuple[Usd.TimeCode, object] | None = None
    at_default = attr.GetResolveInfo(_DEFAULT)
    if at_default.GetSource() == Usd.ResolveInfoSourceDefault:
        factor = _factor(_value_units(attr, at_default, False, file, stage), stage, exponents)
        if factor != 1.0:
            value = attr.Get(_DEFAULT)
            scaled = _times(value, factor)
            if _changes(value, scaled):
                default = (_DEFAULT, scaled)
    writes: list[tuple[Usd.TimeCode, object]] = []
    any_time = attr.GetResolveInfo()
    source = any_time.GetSource()
    if source == Usd.ResolveInfoSourceTimeSamples:
        factor = _factor(_value_units(attr, any_time, True, file, stage), stage, exponents)
        if factor != 1.0 or default is not None:
            samples = [(t, attr.Get(t)) for t in attr.GetTimeSamples()]
            scaled = [(Usd.TimeCode(t), _times(v, factor)) for t, v in samples]
            if default is not None or any(
                _changes(old, new) for (_, old), (_, new) in zip(samples, scaled, strict=True)
            ):
                writes += scaled
    elif source not in (Usd.ResolveInfoSourceDefault, Usd.ResolveInfoSourceNone, Usd.ResolveInfoSourceFallback):
        raise _UnconvertibleError
    if default is not None:
        writes.append(default)
    return writes


def convert_units(root: Usd.Prim, file: Units, stage: Units, table: Table) -> Converted:
    """Converts every value under root that has units to the stage's, in the edit target's layer, as Kit's metrics
    assembler does with its physics and camera rules: each value times its layer's metersPerUnit over the stage's to
    its distance exponent, and the same of kilogramsPerUnit to its mass exponent.

    Only values that change are written: an override that changes nothing would hide a later change to the file.
    Values inside instances, which no layer of the stage can override, and values animated by value clips or splines,
    or of a type that doesn't multiply, are left, and their paths given.
    """
    planned: list[tuple[Usd.Attribute, list[tuple[Usd.TimeCode, object]]]] = []
    left: list[str] = []
    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        for attr in prim.GetAuthoredAttributes():
            exponents = unit_exponents(attr.GetName(), prim, table)
            if exponents is None or exponents == (0, 0):
                continue
            try:
                writes = _writes(attr, exponents, file, stage)
            except _UnconvertibleError:
                left.append(str(attr.GetPath()))
                continue
            if not writes:
                continue
            if prim.IsInstanceProxy():
                left.append(str(attr.GetPath()))
                continue
            planned.append((attr, writes))
    # Every write after every read: a value written under the robot shows through an inherits or specializes arc to
    # another of its prims, which would read it as its own and convert it a second time.
    for attr, writes in planned:
        for time, value in writes:
            attr.Set(value, time)
    return Converted(len(planned), left)


# ---- the frame a prim lands in, and a file brought to it (#119) ----

_UP = {"Y": Gf.Vec3d(0, 1, 0), "Z": Gf.Vec3d(0, 0, 1)}


def _up_under(turn: float, up: str | None) -> str | None:
    """The axis, Y or Z, that a turn of `turn` degrees about X takes to `up`: what stands up inside a frame so turned.
    None when neither does, or up is none of them."""
    target = _UP.get(up or "")
    if target is None:
        return None
    rotation = Gf.Rotation(Gf.Vec3d.XAxis(), turn)
    return next((axis for axis, v in _UP.items() if Gf.IsClose(rotation.TransformDir(v), target, 1e-6)), None)


class Frame(NamedTuple):
    """The frame a prim lands in, or the one inside a prim: its up axis, None when its turn stands neither Y nor Z
    up; its metersPerUnit; and the prims whose :unitsResolve ops make it differ from the stage's."""

    up_axis: str | None
    meters: float
    prims: list[str]


def frame_of(start: Usd.Prim, stage_axis: str, stage_meters: float) -> Frame:
    """The frame inside start: the stage's, turned and scaled by the :unitsResolve ops of start and its ancestors, as
    Kit's metrics assembler measures a file referenced inside a prim it brought to the stage. For a new prim, start is
    its parent; for a prim already there, the prim itself, its own ops counted.

    Only those ops count: a prim's own scale is the user's, which scales what is under it as asked, and a prim that
    composes a file of other units but holds no op hasn't changed the frame. The walk stops after a prim whose op
    order resets the transform stack, since the ops above it don't reach what is under it.
    """
    turn, scale, prims = 0.0, 1.0, list[str]()
    prim = start
    while prim and not prim.IsPseudoRoot():
        xformable = UsdGeom.Xformable(prim)
        if xformable:
            held = False
            for op in xform_ops(xformable):
                if op.GetOpName() == UP_AXIS_OP:
                    turn += float(cast("float", op.GetAttr().Get() or 0.0))
                    held = True
                elif op.GetOpName() == UNITS_OP:
                    value = op.GetAttr().Get()
                    scale *= 1.0 if value is None else floats(cast("Gf.Vec3d", value))[0]
                    held = True
            if held:
                prims.append(str(prim.GetPath()))
            if xformable.GetResetXformStack():
                break
        prim = prim.GetParent()
    prims.reverse()
    return Frame(_up_under(turn, stage_axis), stage_meters * scale, prims)


class Brought(NamedTuple):
    """What bring_to_stage did, as the answer's fields: the turn, the scale and the values converted, and the frame
    they were measured against when it isn't the stage's; each None when there was nothing to say."""

    up_axis_turn: dict[str, object] | None
    units_scale: dict[str, object] | None
    frame: dict[str, object] | None


class StepError(Exception):
    """bring_to_stage's failure, other than a ValueError's or a USD error's, which pass as they are: the step under
    way, and the exception it raised, so the handler's error names both."""

    def __init__(self, step: str, cause: Exception) -> None:
        super().__init__(f"{step} failed: {type(cause).__name__}: {cause}")
        self.step = step
        self.cause = cause


def _no_table(_name: str, _prim: Usd.Prim) -> Exponents | None:
    return None


def _units_answer(
    file: Units, stage: Units, frame_meters: float | None, factor: float, op: list[float] | None, done: Converted | None
) -> dict[str, object]:
    """The answer's units_scale: the units that differ, with the frame's under a frame; the factor, against the frame,
    and the op's value after, which differ when the file's root held the op; what was converted to the stage's units
    and what was left, or None for converted when the file's units are the stage's."""
    meters = _ratio(file.meters, stage.meters) != 1.0 or (
        frame_meters is not None and _ratio(file.meters, frame_meters) != 1.0
    )
    pair: dict[str, float | None] = {"file": file.meters, "stage": stage.meters}
    if frame_meters is not None:
        pair["frame"] = frame_meters
    kilograms = None
    if _ratio(file.kilograms, stage.kilograms) != 1.0:
        kilograms = {"file": file.kilograms, "stage": stage.kilograms}
    return {
        "meters_per_unit": pair if meters else None,
        "kilograms_per_unit": kilograms,
        "factor": None if op is None else factor,
        "op": op,
        "op_name": None if op is None else UNITS_OP,
        "converted": None if done is None else done.values,
        "left": [] if done is None else done.left[:10],
        "left_count": 0 if done is None else len(done.left),
    }


def _stage_metrics(prim: Usd.Prim) -> tuple[str, float, Units]:
    """The up axis, metersPerUnit and units of prim's stage."""
    stage = prim.GetStage()
    meters = float(UsdGeom.GetStageMetersPerUnit(stage))
    return str(UsdGeom.GetStageUpAxis(stage)), meters, Units(meters, float(UsdPhysics.GetStageKilogramsPerUnit(stage)))


# The types a file holds its content in that USD gives no transform: made an Xform, that content turns and scales.
_GROUPS = ("", "Scope")


def bring_to_stage(prim: Usd.Prim, layer: Sdf.Layer, table: Table | None, noun: str) -> Brought:
    """Brings prim, new on its stage and referencing layer's file, to the stage as Kit's metrics assembler brings a
    dropped file: the turn from the file's up axis to the frame prim lands in, the scale by the file's metersPerUnit
    over the frame's, and its values converted from the file's units to the stage's, whatever the frame, as Kit
    converts them. In the edit target's layer, where a refusal's RemovePrim takes them all.

    A prim whose file's root is typeless or a Scope, as 42 of Isaac Sim's 179 bundled .usda files with a default prim
    have it, has no transform to hold the ops, which would answer a turn that moved nothing: it is made an Xform here
    first, so its content turns and scales. A root of any other type USD gives no transform, such as a Material, holds
    nothing a turn or a scale would move, and gets neither. noun, "robot" or "file", names what a failed step was
    working on. table None, a Kit app without the PhysX schema, converts only the cameras' distances, and the answer
    says so. A frame whose turn stands neither axis up is taken as the stage's.
    """
    stage_axis, stage_meters, stage = _stage_metrics(prim)
    frame = frame_of(prim.GetParent(), stage_axis, stage_meters)
    file_axis, file_units = file_up_axis(layer), layer_units(layer)
    axis = frame.up_axis or stage_axis
    framed = axis != stage_axis or _ratio(frame.meters, stage_meters) != 1.0
    degrees = up_axis_turn(file_axis, axis)
    factor = _ratio(file_units.meters, frame.meters)
    turned: dict[str, object] | None = None
    op: list[float] | None = None
    done: Converted | None = None
    step = f"Turning the {noun} upright"
    try:
        if (degrees is not None or factor != 1.0) and not is_a(prim, UsdGeom.Xformable):
            if prim.GetTypeName() in _GROUPS:
                prim.SetTypeName("Xform")
            else:
                degrees, factor = None, 1.0
        if degrees is not None:
            value = stand_upright(prim, degrees)
            turned = {"file": file_axis, "stage": stage_axis, "degrees": degrees, "op": value, "op_name": UP_AXIS_OP}
            if framed:
                turned["frame"] = axis
        if factor != 1.0:
            step = f"Scaling the {noun} to the stage's units"
            op = scale_to_stage(prim, factor)
        if units_factors(file_units, stage) is not None:
            step = f"Converting the {noun}'s values to the stage's units"
            done = convert_units(prim, file_units, stage, table or _no_table)
    except (ValueError, Tf.ErrorException):
        raise
    except Exception as e:
        raise StepError(step, e) from e
    scaled = None
    if op is not None or done is not None:
        scaled = _units_answer(file_units, stage, frame.meters if framed else None, factor, op, done)
        scaled["table"] = table is not None
    where: dict[str, object] | None = None
    # A file that authors neither is left as it is, wherever it lands: no frame to name.
    if framed and (file_axis is not None or file_units.meters is not None):
        where = {"up_axis": axis, "meters_per_unit": frame.meters, "prims": frame.prims}
    return Brought(turned, scaled, where)


def _root_ops(layer: Sdf.Layer) -> tuple[float, float]:
    """The turn and the scale the :unitsResolve ops of the file's default prim hold in its own layer, as a file Kit
    resolved and saved holds them: (0, 1) where it holds none."""
    if not layer.defaultPrim:
        return 0.0, 1.0
    root = Sdf.Path.absoluteRootPath.AppendChild(layer.defaultPrim)
    order_spec = attribute_spec(layer, root.AppendProperty("xformOpOrder"))
    order = [] if order_spec is None else [str(name) for name in cast("list[str]", order_spec.default or [])]

    def held(name: str) -> object:
        spec = attribute_spec(layer, root.AppendProperty(name)) if name in order else None
        return None if spec is None else spec.default

    turn, scale = held(UP_AXIS_OP), held(UNITS_OP)
    return (
        0.0 if turn is None else float(cast("float", turn)),
        1.0 if scale is None else floats(cast("Gf.Vec3d", scale))[0],
    )


def not_brought(prim: Usd.Prim, layer: Sdf.Layer, added: bool) -> dict[str, object] | None:
    """For a prim that was there before the call and holds layer's file: what the file needs and doesn't get, else
    None. Its placing: the file's content, its upAxis and metersPerUnit as its root's own :unitsResolve ops leave
    them, against the frame inside the prim, which counts the prim's own ops, so a prim this call or an earlier one
    brought, or Kit's drop, isn't reported, and a reference an older extension left as it was is. Its values, when
    this call added the reference: only a prim the call makes has them converted, so a file of other units leaves
    them in its own. A file that authors neither is left as it is, so never reported."""
    stage_axis, stage_meters, stage = _stage_metrics(prim)
    file_axis, file_units = file_up_axis(layer), layer_units(layer)
    turn, scale = _root_ops(layer)
    content_axis = None if file_axis is None else _up_under(turn, file_axis)
    content_meters = None if file_units.meters is None else file_units.meters * scale
    inside = frame_of(prim, stage_axis, stage_meters)
    off_axis = file_axis is not None and content_axis != inside.up_axis
    off_units = content_meters is not None and _ratio(content_meters, inside.meters) != 1.0
    factors = units_factors(file_units, stage) if added else None
    if not (off_axis or off_units or factors is not None):
        return None
    placed = off_axis or off_units
    values: dict[str, object] | None = None
    if factors is not None:
        values = {
            "meters_per_unit": None if factors.distance == 1.0 else {"file": file_units.meters, "stage": stage.meters},
            "kilograms_per_unit": None
            if factors.mass == 1.0
            else {"file": file_units.kilograms, "stage": stage.kilograms},
        }
    return {
        "prim_path": str(prim.GetPath()),
        "file": {"up_axis": content_axis, "meters_per_unit": content_meters} if placed else None,
        "frame": {"up_axis": inside.up_axis, "meters_per_unit": inside.meters} if placed else None,
        "values": values,
    }
