"""Hiding everything but one prim while inspect_prim captures it, and putting each prim's visibility back exactly.

Needs pxr, not Kit: the tests run it on usd-core.
"""

from pxr import Sdf, Usd, UsdGeom, UsdLux

from .usd import attribute_spec, children, has_api, is_a, prim_spec, remove_child_spec

LIGHT_TYPES = ("DistantLight", "DomeLight", "SphereLight", "RectLight", "DiskLight", "CylinderLight")

_NO_SPEC = object()  # the session layer had no visibility opinion for the prim
_NO_DEFAULT = object()  # it had a visibility spec, without a default value


def is_light(prim: Usd.Prim) -> bool:
    return (
        has_api(prim, UsdLux.LightAPI)
        or is_a(prim, UsdLux.BoundableLightBase)
        or is_a(prim, UsdLux.NonboundableLightBase)
        or prim.GetTypeName() in LIGHT_TYPES
    )


def prims_to_hide(stage: Usd.Stage, target_path: str) -> tuple[list[Sdf.Path], list[str]]:
    """The prims to make invisible so that only the target's subtree, and the scene's lights, still render.

    Walks from the root down to the target and takes every visible sibling on the way. A prim that holds a light is
    not hidden whole, or the light would go dark with it; its children are taken instead. An instance's children
    can't be authored, so an instance the walk would go into is left as it is, with a warning; the warnings come
    back with the paths.
    """
    target = Sdf.Path(target_path)
    if target == Sdf.Path.absoluteRootPath:
        return [], []
    holds_light = _paths_holding_lights(stage)

    found: list[Sdf.Path] = []
    warnings: list[str] = []

    def take(prim: Usd.Prim) -> None:
        path = prim.GetPath()
        if path == target or is_light(prim) or is_a(prim, UsdGeom.Camera):
            return
        leads_to_target = target.HasPrefix(path)
        if leads_to_target or path in holds_light or not is_a(prim, UsdGeom.Imageable):
            # Stays visible: it leads to the target, holds a light, or has no visibility of its own.
            if prim.IsInstance():
                holds = "the target" if leads_to_target else "a light"
                warnings.append(
                    f"{path} is an instance that holds {holds}; children of an instance can't be hidden, "
                    "so all of it stays visible"
                )
                return
            for child in children(prim):
                take(child)
            return
        if UsdGeom.Imageable(prim).ComputeVisibility(Usd.TimeCode.Default()) != UsdGeom.Tokens.invisible:
            found.append(path)

    for child in children(stage.GetPseudoRoot()):
        take(child)
    return found, warnings


def _paths_holding_lights(stage: Usd.Stage) -> set[Sdf.Path]:
    """Every prim path that is a light or has one below it; an instance counts when its prototype holds one.

    Instance proxies are never visited, and each prototype is walked once however many instances share it.
    """
    lit_prototypes: dict[Sdf.Path, bool] = {}

    def lit(prim: Usd.Prim) -> bool:
        if is_light(prim):
            return True
        if not prim.IsInstance():
            return False
        prototype = prim.GetPrototype()
        key = prototype.GetPath()
        if key not in lit_prototypes:
            lit_prototypes[key] = any(lit(p) for p in Usd.PrimRange(prototype))
        return lit_prototypes[key]

    holds: set[Sdf.Path] = set()
    for prim in stage.Traverse():
        if lit(prim):
            holds.update(prim.GetPath().GetPrefixes())
    return holds


class Hidden:
    """Visibility opinions authored in a session layer to hide prims, and how to undo each one exactly."""

    def __init__(self, layer: Sdf.Layer):
        self.layer = layer
        self.warnings: list[str] = []
        self._attrs: list[tuple[Sdf.Path, object]] = []
        self._created: list[Sdf.Path] = []

    def __len__(self) -> int:
        return len(self._attrs)

    def hide(self, paths: list[Sdf.Path]) -> None:
        with Sdf.ChangeBlock():
            for path in paths:
                attr_path = path.AppendProperty(UsdGeom.Tokens.visibility)
                if self.layer.GetNumTimeSamplesForPath(attr_path):
                    # Time samples outrank the default this would author; leave them, and the prim, alone.
                    self.warnings.append(
                        f"{path} has time-sampled visibility in the session layer, so isolate left it visible"
                    )
                    continue
                for prefix in path.GetPrefixes():
                    if prim_spec(self.layer, prefix) is None:
                        self._created.append(prefix)
                spec = Sdf.CreatePrimInLayer(self.layer, path)
                attr = attribute_spec(self.layer, attr_path)
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
                attr = attribute_spec(self.layer, attr_path)
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
                spec = prim_spec(self.layer, path)
                if spec is not None and spec.IsInert():
                    remove_child_spec(self.layer.GetPrimAtPath(path.GetParentPath()), spec.name)
        self._attrs.clear()
        self._created.clear()
