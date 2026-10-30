"""Typed forms of the pxr calls whose stubs (types-usd) don't say what USD does, so the core type-checks in full.

- An int index into a Gf vector is typed as giving a list; it gives a float.
- IsA and HasAPI are typed to take a TfType or a schema's name; pxr converts a schema class to its TfType.
- Prim.GetChildren is typed as a list of unknowns; GetChildrenNames, which gives the same children, is typed.
- A layer's GetPrimAtPath, GetAttributeAtPath and GetRelationshipAtPath are typed as always finding a spec; they give
  None for a path the layer has none for.
- A prim spec's nameChildren is typed without __delitem__.
"""

from typing import Protocol, cast

from pxr import Sdf, Tf, Usd


class Vec(Protocol):
    """A Gf vector, a quaternion's imaginary part, a matrix's row or a list: indexed by position to a float."""

    def __getitem__(self, index: int, /) -> float: ...


class _Deletable(Protocol):
    def __delitem__(self, key: str, /) -> None: ...


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
