"""One attribute of a prim set to a value given in JSON (#151): the refusals, the conversion to the attribute's type,
the layer written, and the shape's extent kept in step with its size. Needs pxr, not Kit: the tests run it on usd-core.

USD's Attribute.Set takes an int for a float, True for a double, NaN, and a token its schema doesn't list, and raises on
a Python list for a vector; so every value is converted and checked here, and nothing is written until it passes.
"""

import difflib
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from pxr import Gf, Sdf, Usd, UsdGeom

from .deletion import instance_of
from .formatter import format_value
from .usd import attribute_spec, is_a, prim_spec
from .xform import write_blocker

_DEFAULT = Usd.TimeCode.Default()
# The names other tools own, which have rules of their own there.
_OWNED = {
    "visibility": "set_visibility shows and hides a prim, a hidden parent included",
    "xformOpOrder": "set_prim_transform sets a prim's position, rotation and scale",
}
_NAMES_SHOWN = 12
_HALF_MAX = 65504.0
_FLOAT_MAX = 3.4028234663852886e38


@dataclass(frozen=True)
class Written:
    name: str
    type_name: str
    before: object  # as USD gave it before the write: None when unset and without a fallback
    after: object  # as USD gives it after: what it stored, a float rounded
    layer: Sdf.Layer
    note: str = ""
    extent: object = None  # the extent written with it, when the write changed the shape's box


# ----- what is refused -----


def _close_names(name: str, names: Sequence[str]) -> list[str]:
    """The prim's names closest to name, by the whole name and by the part after its last namespace, so `intensity`
    finds `inputs:intensity` and `colour` finds `inputs:color`; then the others, up to _NAMES_SHOWN."""
    close = difflib.get_close_matches(name, names, n=5, cutoff=0.6)
    tail = name.rsplit(":", 1)[-1]
    by_tail: dict[str, list[str]] = {}
    for n in names:
        by_tail.setdefault(n.rsplit(":", 1)[-1], []).append(n)
    for match in difflib.get_close_matches(tail, list(by_tail), n=5, cutoff=0.6):
        close += by_tail[match]
    ordered = list(dict.fromkeys([*close, *names]))
    return ordered[:_NAMES_SHOWN]


def attribute_refusal(prim: Usd.Prim, name: str) -> str | None:
    """Why name on prim isn't set here, or None: a prim a write couldn't change, a name that isn't an attribute or that
    another tool owns, or one the prim lacks (its closest names given)."""
    path = prim.GetPath()
    if not prim.IsActive():
        return f"{path} is inactive, so a value set on it wouldn't show: activate it first"
    if prim.IsInstanceProxy():
        instance = instance_of(prim)
        return (
            f"{path} is inside the instance {instance.GetPath()}, whose prims can't be changed one by one: set it in "
            f"the asset the instance references, or turn off {instance.GetPath()}'s instanceable"
        )
    if prim.IsInPrototype():
        # USD raises on a write in a prototype; this says why instead of a traceback.
        return (
            f"{path} is in an instance prototype, which USD lets no one edit: set it in the asset the instances share"
        )
    if not name or not Sdf.Path.IsValidNamespacedIdentifier(name):
        return f"name must be an attribute's name, such as inputs:intensity, got {name!r}"
    if prim.GetRelationship(name):
        return f"{path}'s {name} is a relationship, not an attribute: set_material binds a prim's material"
    if name in _OWNED:
        return f"{name} isn't set here: {_OWNED[name]}"
    if name.startswith("xformOp:"):
        return f"{name} isn't set here: {_OWNED['xformOpOrder']}"
    if not prim.GetAttribute(name):
        names = [a.GetName() for a in prim.GetAttributes()]
        listed = ", ".join(_close_names(name, names)) or "none"
        return f"{path} has no attribute {name}; its attributes, closest first: {listed}"
    return None


# ----- the conversion -----


def _number(value: object, what: str, limit: float | None) -> float:
    """value as a finite float within limit, which the type would store as infinity past it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} takes a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} takes a finite number, got {value!r}")
    if limit is not None and abs(number) > limit:
        raise ValueError(f"{what} holds numbers up to {limit:g} either way, got {value!r}")
    return number


def _whole(value: object, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} takes a whole number, got {value!r}")
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise ValueError(f"{what} takes a whole number, got {value!r}")
    number = int(value)
    if not low <= number <= high:
        raise ValueError(f"{what} holds whole numbers from {low} to {high}, got {value!r}")
    return number


def _text(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} takes a string, got {value!r}")
    return value


def _bool(value: object, what: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{what} takes true or false, got {value!r}")
    return value


def _half(value: object, what: str) -> float:
    return _number(value, what, _HALF_MAX)


def _float(value: object, what: str) -> float:
    return _number(value, what, _FLOAT_MAX)


def _double(value: object, what: str) -> float:
    return _number(value, what, None)


def _int(value: object, what: str) -> int:
    return _whole(value, what, -(2**31), 2**31 - 1)


Convert = Callable[[object, str], object]
_T = Sdf.ValueTypeNames
# Each scalar type the tool converts, by its Tf.Type, which names a type the same on every platform (int64 is __int64
# on Windows): what one JSON value becomes.
_SCALARS: dict[object, Convert] = {
    _T.Bool.type: _bool,
    _T.UChar.type: lambda v, w: _whole(v, w, 0, 255),
    _T.Int.type: _int,
    _T.UInt.type: lambda v, w: _whole(v, w, 0, 2**32 - 1),
    _T.Int64.type: lambda v, w: _whole(v, w, -(2**63), 2**63 - 1),
    _T.UInt64.type: lambda v, w: _whole(v, w, 0, 2**64 - 1),
    _T.Half.type: _half,
    _T.Float.type: _float,
    _T.Double.type: _double,
    _T.TimeCode.type: lambda v, w: Sdf.TimeCode(_double(v, w)),
    _T.String.type: _text,
    _T.Token.type: _text,
    _T.Asset.type: lambda v, w: Sdf.AssetPath(_text(v, w)),
}
# Each vector type: its Gf class, its length and what each component is.
_COMPONENTS: dict[str, tuple[str, Convert]] = {
    "f": ("Float", _float),
    "d": ("Double", _double),
    "h": ("Half", _half),
    "i": ("Int", _int),
}
_VECTORS: dict[object, tuple[type, int, Convert]] = {
    getattr(_T, f"{kind}{n}").type: (getattr(Gf, f"Vec{n}{suffix}"), n, component)
    for n in (2, 3, 4)
    for suffix, (kind, component) in _COMPONENTS.items()
}
_QUATS: dict[object, tuple[type, type, float | None]] = {
    _T.Quatf.type: (Gf.Quatf, Gf.Vec3f, _FLOAT_MAX),
    _T.Quatd.type: (Gf.Quatd, Gf.Vec3d, None),
    _T.Quath.type: (Gf.Quath, Gf.Vec3h, _HALF_MAX),
}


def _list(value: object) -> list[object] | None:
    return cast("list[object]", value) if isinstance(value, list) else None


def _scalar(type_name: Sdf.ValueTypeName, value: object, what: str) -> object:
    """One value of the attribute's scalar type."""
    kind = type_name.scalarType.type
    if kind in _SCALARS:
        return _SCALARS[kind](value, what)
    if kind in _VECTORS:
        cls, n, component = _VECTORS[kind]
        items = _list(value)
        if items is None or len(items) != n:
            raise ValueError(f"{what} takes a list of {n} numbers, got {value!r}")
        return cls(*(component(x, f"{what}'s component") for x in items))
    if kind in _QUATS:
        cls, imaginary, limit = _QUATS[kind]
        items = _list(value)
        if items is None or len(items) != 4:
            raise ValueError(f"{what} takes a quaternion as [w, x, y, z], got {value!r}")
        w, x, y, z = (_number(c, f"{what}'s component", limit) for c in items)
        return cls(w, imaginary(x, y, z))
    raise ValueError(f"{what} is a {type_name.scalarType}, which this tool doesn't set")


def convert(attr: Usd.Attribute, value: object) -> object:
    """value, as JSON gave it, in attr's type; ValueError naming the type and the value when it doesn't fit."""
    type_name = attr.GetTypeName()
    what = f"{attr.GetName()} ({type_name})"
    if not type_name.isArray:
        return _scalar(type_name, value, what)
    given = _list(value)
    if given is None:
        raise ValueError(f"{what} takes a list, [] to empty it, got {value!r}")
    items = [_scalar(type_name, item, f"{what}'s element") for item in given]
    array = cast("Callable[[list[object]], object] | None", type_name.type.pythonClass)
    if array is None:
        raise ValueError(f"{what} is an array this tool doesn't set")
    return array(items)


def _token_note(attr: Usd.Attribute, value: object) -> str:
    """A note naming attr's allowed tokens when value has one outside them: USD treats the list as a hint, and PhysX's
    own tokens, such as physics:approximation's sdf, aren't in it."""
    allowed = attr.GetMetadata("allowedTokens")
    if not allowed or attr.GetTypeName().scalarType.type != _T.Token.type:
        return ""
    given = list(cast("Iterable[object]", value)) if attr.GetTypeName().isArray else [value]
    outside = [str(v) for v in given if str(v) not in {str(a) for a in allowed}]
    if not outside:
        return ""
    return (
        f"{', '.join(outside)} isn't among {attr.GetName()}'s allowed tokens ({', '.join(str(a) for a in allowed)}); "
        "written as given"
    )


# ----- the layer -----


def target_layer(prim: Usd.Prim) -> Sdf.Layer:
    """Where prim's attribute is written: the edit target, unless the prim, or its nearest ancestor with a spec in the
    stage's own layers, is held by Kit's session layers alone, as Kit's own cameras are and a viewport light rig's
    lights, through the rig's over that references its file. Those go to the session layer, where a write lands and
    stays out of the user's file."""
    stage = prim.GetStage()
    edit = stage.GetEditTarget().GetLayer()
    own = stage.GetLayerStack(includeSessionLayers=True)
    root = stage.GetRootLayer().identifier
    ids = [layer.identifier for layer in own]
    session: set[str] = set(ids[: ids.index(root)]) if root in ids else set()
    current: Usd.Prim | None = prim
    while current and not current.IsPseudoRoot():
        holders = {spec.layer.identifier for spec in current.GetPrimStack() if spec.layer.identifier in ids}
        if holders:
            return stage.GetSessionLayer() if holders <= session else edit
        current = current.GetParent()
    return edit


# ----- the write -----


def _plugin_extent(prim: Usd.Prim) -> object:
    return UsdGeom.Boundable.ComputeExtentFromPlugins(UsdGeom.Boundable(prim), _DEFAULT)


def _same_box(a: object, b: object) -> bool:
    first = [list(cast("Iterable[float]", corner)) for corner in cast("Iterable[object]", a)]
    second = [list(cast("Iterable[float]", corner)) for corner in cast("Iterable[object]", b)]
    return len(first) == len(second) and all(
        math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-9)
        for ca, cb in zip(first, second, strict=True)
        for x, y in zip(ca, cb, strict=True)
    )


class _Undo:
    """What a layer held of one attribute before a write, so the write can be taken back exactly: its old default, or
    no spec at all, the overs the write made with it."""

    def __init__(self, layer: Sdf.Layer, prim_path: Sdf.Path, name: str) -> None:
        self.layer = layer
        self.path = prim_path.AppendProperty(name)
        spec = attribute_spec(layer, self.path)
        self.had_spec = spec is not None
        self.had_default = bool(spec is not None and spec.HasDefaultValue())
        self.default: object = spec.default if spec is not None and self.had_default else None
        self.prim_existed = prim_spec(layer, prim_path) is not None

    def __call__(self) -> None:
        spec = attribute_spec(self.layer, self.path)
        owner = prim_spec(self.layer, self.path.GetPrimPath())
        if spec is None or owner is None:
            return
        if self.had_default:
            spec.default = self.default
        elif self.had_spec:
            spec.ClearDefaultValue()
        elif self.prim_existed:
            owner.RemoveProperty(spec)
        else:
            # Usd.Attribute.Clear would leave a typed spec behind; the cleanup drops the overs this write made too.
            with Sdf.CleanupEnabler():
                owner.RemoveProperty(spec)


def set_attribute(prim: Usd.Prim, name: str, value: object, layer: Sdf.Layer | None = None) -> Written:
    """Sets name on prim to value as its default, in layer or target_layer's; ValueError, with nothing written, when it
    is refused, the value doesn't fit, a stronger layer or time samples would hide it, or it would change the shape's
    box where its authored extent can't follow."""
    why = attribute_refusal(prim, name)
    if why:
        raise ValueError(why)
    attr = prim.GetAttribute(name)
    converted = convert(attr, value)
    note = _token_note(attr, converted)
    target = layer if layer is not None else target_layer(prim)
    why = write_blocker(prim, attr, target)
    if why:
        raise ValueError(why)
    stage = prim.GetStage()
    boundable = UsdGeom.Boundable(prim) if is_a(prim, UsdGeom.Boundable) else None
    extent_attr = boundable.GetExtentAttr() if boundable is not None else None
    # An unauthored extent USD computes from the size itself; only an authored one can go stale.
    track = extent_attr is not None and name != "extent" and extent_attr.HasAuthoredValue()
    box_before = _plugin_extent(prim) if track else None
    before = attr.Get()
    undo = _Undo(target, prim.GetPath(), name)
    with Usd.EditContext(stage, Usd.EditTarget(target)):
        if not attr.Set(converted):
            undo()
            raise ValueError(f"USD refused {converted!r} for {prim.GetPath()}'s {name}; nothing was written")
    extent = None
    if track and extent_attr is not None:
        box_after = _plugin_extent(prim)
        if box_before is not None and box_after is not None and not _same_box(box_before, box_after):
            blocked = write_blocker(prim, extent_attr, target)
            if blocked:
                undo()
                raise ValueError(
                    f"{prim.GetPath()}'s {name} wasn't set: it changes the prim's box, and its extent can't follow, "
                    f"so get_prim_bounds would give the old size. {blocked}"
                )
            with Usd.EditContext(stage, Usd.EditTarget(target)):
                extent_attr.Set(box_after)
            extent = extent_attr.Get()
    return Written(name, str(attr.GetTypeName()), before, attr.Get(), target, note, extent)


# ----- the answer -----

_SHOWN_ITEMS = 8
_VECTOR_TYPES = tuple(cls for cls, _n, _c in _VECTORS.values())


def _is_array(value: object) -> bool:
    kind = type(value)
    return kind.__module__ in ("pxr.Vt", "pxr.Sdf") and kind.__name__.endswith("Array")


def _one(value: object) -> str:
    """One value as format_value writes it, a half or int vector too, which it would write as Gf prints it."""
    if isinstance(value, _VECTOR_TYPES) and not isinstance(value, (Gf.Vec2f, Gf.Vec3f, Gf.Vec4f, Gf.Vec2d)):
        return ", ".join(format_value(float(x)) for x in cast("Iterable[float]", value))
    return format_value(value)


def shown(value: object) -> str:
    """A value as the answer gives it, as get_prim_properties' block writes it; an array as its first 8 values, each
    vector in brackets, and its length, where format_value would write a Vt array whole (100,000 colours: 1.5 million
    characters)."""
    if not _is_array(value):
        return _one(value)
    items = list(cast("Iterable[object]", value))
    if not items:
        return "[]"
    parts = [
        f"({_one(v)})" if isinstance(v, (*_VECTOR_TYPES, Gf.Quatf, Gf.Quatd, Gf.Quath)) else _one(v) for v in items
    ]
    text = ", ".join(parts[:_SHOWN_ITEMS])
    return f"{text} ... ({len(items)} items)" if len(items) > _SHOWN_ITEMS else text
