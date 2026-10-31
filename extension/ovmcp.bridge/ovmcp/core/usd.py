"""Typed forms of the pxr calls whose stubs (types-usd) don't say what USD does, so the core type-checks in full.

- An int index into a Gf vector is typed as giving a list; it gives a float.
- IsA and HasAPI are typed to take a TfType or a schema's name; pxr converts a schema class to its TfType.
- Prim.GetChildren is typed as a list of unknowns; GetChildrenNames, which gives the same children, is typed.
- A layer's GetPrimAtPath, GetAttributeAtPath and GetRelationshipAtPath are typed as always finding a spec; they give
  None for a path the layer has none for.
- A prim spec's nameChildren is typed without __delitem__.
- A layer's dirty is typed without a type; it is a bool.
- Sdf.Layer.Find is typed with a dict of unknowns and as always finding a layer; it gives None when the registry holds
  none for the path.
- Sdf.FileFormat.FindByExtension is typed as always finding a format; it gives None for an extension none reads.
- Xformable.GetOrderedXformOps is typed as a bare list; it gives XformOps.
- An op type is typed as a Tf.Type by the XformOp constants and GetOpType, and as XformOp.Type by AddXformOp; they
  are the same enum.
- Matrix4d.Factor is typed as a bare tuple; its first item says whether the matrix could be factored.
- PrimCompositionQuery.GetCompositionArcs is typed with a class pxr doesn't have (CompositionArc at run time), whose
  GetIntroducingLayer is None for the root arc; a Pcp node's layerStack is untyped.
"""

from collections.abc import Callable, Sequence
from operator import attrgetter
from typing import Protocol, cast

from pxr import Gf, Sdf, Tf, Usd, UsdGeom


class Vec(Protocol):
    """A Gf vector, a quaternion's imaginary part, a matrix's row or a list: indexed by position to a float."""

    def __getitem__(self, index: int, /) -> float: ...


class _Deletable(Protocol):
    def __delitem__(self, key: str, /) -> None: ...


class _Dirty(Protocol):
    @property
    def dirty(self) -> bool: ...


class _Registry(Protocol):
    Find: Callable[[str], "Sdf.Layer | None"]


def floats(v: Vec, n: int = 3) -> list[float]:
    """The first n components, as floats."""
    return [float(v[i]) for i in range(n)]


def is_a(prim: Usd.Prim, schema: type) -> bool:
    return prim.IsA(Tf.Type.Find(schema))


def has_api(prim: Usd.Prim, schema: type) -> bool:
    return prim.HasAPI(Tf.Type.Find(schema))


def children(prim: Usd.Prim) -> list[Usd.Prim]:
    """The prim's children as GetChildren gives them: active, loaded, defined and not abstract, in order."""
    return [prim.GetChild(name) for name in prim.GetChildrenNames()]


def prim_spec(layer: Sdf.Layer, path: Sdf.Path) -> Sdf.PrimSpec | None:
    return layer.GetPrimAtPath(path)


def attribute_spec(layer: Sdf.Layer, path: Sdf.Path) -> Sdf.AttributeSpec | None:
    return layer.GetAttributeAtPath(path)


def relationship_spec(layer: Sdf.Layer, path: Sdf.Path) -> Sdf.RelationshipSpec | None:
    return layer.GetRelationshipAtPath(path)


def remove_child_spec(parent: Sdf.PrimSpec, name: str) -> None:
    del cast("_Deletable", parent.nameChildren)[name]


def has_unsaved_edits(layer: Sdf.Layer) -> bool:
    """Whether the layer holds edits not yet saved to its file."""
    return cast("_Dirty", layer).dirty


def find_layer(path: str) -> Sdf.Layer | None:
    """The layer Sdf's registry holds for path, or None."""
    return cast("_Registry", Sdf.Layer).Find(path)


class _Ordered(Protocol):
    GetOrderedXformOps: Callable[[], list[UsdGeom.XformOp]]


class _Factors(Protocol):
    Factor: Callable[[], tuple[bool, ...]]


def xform_ops(xformable: UsdGeom.Xformable) -> list[UsdGeom.XformOp]:
    """The xformable's ops in their order, outermost first."""
    return cast("_Ordered", xformable).GetOrderedXformOps()


def add_xform_op(
    xformable: UsdGeom.Xformable, op_type: Tf.Type, precision: UsdGeom.XformOp.Precision
) -> UsdGeom.XformOp:
    """AddXformOp with an op type as the XformOp constants are typed."""
    return xformable.AddXformOp(cast("UsdGeom.XformOp.Type", op_type), precision)


def factors(matrix: Gf.Matrix4d) -> bool:
    """Whether the matrix factors into a rotation, a scale and a translation: a singular one doesn't."""
    return bool(cast("_Factors", matrix).Factor()[0])


class ArcNode(Protocol):
    """A composition arc's target: a prim path in a layer stack."""

    path: Sdf.Path


class CompositionArc(Protocol):
    """What delete_prim reads of a prim's composition arc."""

    GetArcType: Callable[[], object]
    GetTargetNode: Callable[[], ArcNode]
    GetIntroducingLayer: Callable[[], Sdf.Layer | None]
    GetIntroducingPrimPath: Callable[[], Sdf.Path]
    IsAncestral: Callable[[], bool]


class _Query(Protocol):
    GetCompositionArcs: Callable[[], list[CompositionArc]]


_node_layers = attrgetter("layerStack.layers")


def composition_arcs(prim: Usd.Prim) -> list[CompositionArc]:
    """Every arc that composes the prim, strongest first, the root arc (its own layer stack) among them."""
    return cast("_Query", Usd.PrimCompositionQuery(prim)).GetCompositionArcs()


def node_layers(node: ArcNode) -> list[Sdf.Layer]:
    """The layers of the stack an arc's node reads, strongest first."""
    return list(cast("Sequence[Sdf.Layer]", _node_layers(node)))


def attribute_has_default(spec: Sdf.PropertySpec) -> bool:
    """Whether a property spec holds a default value: an attribute's when one is authored, a relationship's never.
    A property stack is typed as PropertySpecs; its attributes' specs are AttributeSpecs."""
    return isinstance(spec, Sdf.AttributeSpec) and spec.HasDefaultValue()


def format_of(path: str) -> Sdf.FileFormat | None:
    """The file format for path's extension, in any case, or None."""
    return Sdf.FileFormat.FindByExtension(path)
