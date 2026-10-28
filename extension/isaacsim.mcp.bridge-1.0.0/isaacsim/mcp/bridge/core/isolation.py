"""Hiding everything but one prim while inspect_prim captures it, and putting each prim's visibility back exactly.

Needs pxr, not Kit: the tests run it on usd-core.
"""

from pxr import Sdf, Usd, UsdGeom, UsdLux

LIGHT_TYPES = ("DistantLight", "DomeLight", "SphereLight", "RectLight", "DiskLight", "CylinderLight")

_NO_SPEC = object()  # the session layer had no visibility opinion for the prim
_NO_DEFAULT = object()  # it had a visibility spec, without a default value


def is_light(prim: Usd.Prim) -> bool:
    return (
        prim.HasAPI(UsdLux.LightAPI)
        or prim.IsA(UsdLux.BoundableLightBase)
        or prim.IsA(UsdLux.NonboundableLightBase)
        or prim.GetTypeName() in LIGHT_TYPES
    )


def prims_to_hide(stage: Usd.Stage, target_path: str) -> list[Sdf.Path]:
    """The prims to make invisible so that only the target's subtree, and the scene's lights, still render.

    Walks from the root down to the target and takes every visible sibling on the way. A prim that holds a light is
    not hidden whole, or the light would go dark with it; its children are taken instead.
    """
    target = Sdf.Path(target_path)
    if target == Sdf.Path.absoluteRootPath:
        return []
    holds_light: set[Sdf.Path] = set()
    for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies()):
        if is_light(prim):
            holds_light.update(prim.GetPath().GetPrefixes())

    found: list[Sdf.Path] = []

    def take(prim: Usd.Prim) -> None:
        path = prim.GetPath()
        if path == target or is_light(prim) or prim.IsA(UsdGeom.Camera):
            return
        if target.HasPrefix(path) or path in holds_light or not prim.IsA(UsdGeom.Imageable):
            # Stays visible: it leads to the target, holds a light, or has no visibility of its own.
            for child in prim.GetChildren():
                take(child)
            return
        if UsdGeom.Imageable(prim).ComputeVisibility(Usd.TimeCode.Default()) != UsdGeom.Tokens.invisible:
            found.append(path)

    for child in stage.GetPseudoRoot().GetChildren():
        take(child)
    return found


class Hidden:
    """Visibility opinions authored in a session layer to hide prims, and how to undo each one exactly."""

    def __init__(self, layer: Sdf.Layer):
        self.layer = layer
        self._attrs: list[tuple[Sdf.Path, object]] = []
        self._created: list[Sdf.Path] = []

    def __len__(self) -> int:
        return len(self._attrs)

    def hide(self, paths: list[Sdf.Path]) -> None:
        with Sdf.ChangeBlock():
            for path in paths:
                for prefix in path.GetPrefixes():
                    if self.layer.GetPrimAtPath(prefix) is None:
                        self._created.append(prefix)
                spec = Sdf.CreatePrimInLayer(self.layer, path)
                attr_path = path.AppendProperty(UsdGeom.Tokens.visibility)
                attr = self.layer.GetAttributeAtPath(attr_path)
                if attr is None:
                    self._attrs.append((attr_path, _NO_SPEC))
                    attr = Sdf.AttributeSpec(spec, UsdGeom.Tokens.visibility, Sdf.ValueTypeNames.Token)
                else:
                    self._attrs.append((attr_path, attr.default if attr.HasDefaultValue() else _NO_DEFAULT))
                attr.default = UsdGeom.Tokens.invisible

    def restore(self) -> None:
        """Put back what each hidden prim's session layer said before, and remove the specs hide() created."""
        with Sdf.ChangeBlock():
            for attr_path, before in reversed(self._attrs):
                attr = self.layer.GetAttributeAtPath(attr_path)
                if attr is None:
                    continue
                if before is _NO_SPEC:
                    self.layer.GetPrimAtPath(attr_path.GetPrimPath()).RemoveProperty(attr)
                elif before is _NO_DEFAULT:
                    attr.ClearDefaultValue()
                else:
                    attr.default = before
            # A parent is always created before its children, so reversed order removes children first.
            for path in reversed(self._created):
                spec = self.layer.GetPrimAtPath(path)
                if spec is not None and spec.IsInert():
                    del self.layer.GetPrimAtPath(path.GetParentPath()).nameChildren[spec.name]
        self._attrs.clear()
        self._created.clear()
