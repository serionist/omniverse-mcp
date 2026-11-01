"""Whether delete_prim can take a prim off the stage (#82).

RemovePrim removes only what the edit target's layer holds at a path. A prim another of the stage's own layers defines
too, or that a reference, payload, inherit, specialize or variant on a prim above brings, is still on the stage after
it, while the answer said deleted, and the edit layer's overrides of it are gone. So the check comes first, and a
refusal changes nothing; Kit's own delete refuses such an ancestral prim too (omni.usd.check_ancestral).

An arc authored on the prim itself in the edit layer goes with the prim's spec, so a prim that references a file is
deleted whole. Needs pxr, not Kit: the tests run it on usd-core.
"""

from pxr import Pcp, Sdf, Usd

from .usd import composition_arcs, node_layers, prim_spec, stage_prim_of
from .xform import layer_name

_DEFINING = (Sdf.SpecifierDef, Sdf.SpecifierClass)
_ARC_NAMES: dict[object, str] = {
    Pcp.ArcTypeReference: "a reference",
    Pcp.ArcTypePayload: "a payload",
    Pcp.ArcTypeInherit: "an inherit",
    Pcp.ArcTypeSpecialize: "a specialize",
    Pcp.ArcTypeVariant: "a variant",
}
_HIDE = "set_visibility hides it"


def _defines(layer: Sdf.Layer, path: Sdf.Path) -> bool:
    spec = prim_spec(layer, path)
    return spec is not None and spec.specifier in _DEFINING


def instance_of(prim: Usd.Prim) -> Usd.Prim:
    """The instance prim a proxy is inside."""
    instance = prim.GetParent()
    while instance and not instance.IsInstance():
        instance = instance.GetParent()
    return instance


def why_kept(prim: Usd.Prim, edit_layer: Sdf.Layer) -> str | None:
    """Why prim would stay on the stage after RemovePrim in edit_layer, or None when the removal takes it off."""
    stage = prim.GetStage()
    path = prim.GetPath()
    if prim.IsInstanceProxy():
        instance = instance_of(prim).GetPath()
        # set_visibility can't author on the proxy itself either (core/isolation.py): the instance is what it hides.
        return (
            f"{path} is not deleted: it is inside the instance {instance}, whose prims can't be changed one by one. "
            f"set_visibility hides {instance} whole, and delete_prim deletes it"
        )
    for arc in composition_arcs(prim):
        node = arc.GetTargetNode()
        defining = [layer for layer in node_layers(node) if _defines(layer, node.path)]
        if not defining:
            continue
        kind = arc.GetArcType()
        if kind == Pcp.ArcTypeRoot:
            others = [layer for layer in defining if layer.identifier != edit_layer.identifier]
            if others:
                return f"{path} is not deleted: {layer_name(stage, others[0])} defines it too. {_HIDE}"
            continue
        what = _ARC_NAMES.get(kind, f"a {kind}")
        source = layer_name(stage, defining[0])
        if arc.IsAncestral():
            return f"{path} is not deleted: it comes through {what} on {stage_prim_of(arc)} ({source}). {_HIDE}"
        # An arc the referenced file itself authors goes with the reference the edit layer holds, so only arcs of the
        # stage's own layer stack count.
        if not arc.IsIntroducedInRootLayerStack():
            continue
        introducing = arc.GetIntroducingLayer()
        if introducing is not None and introducing.identifier != edit_layer.identifier:
            return (
                f"{path} is not deleted: {layer_name(stage, introducing)} gives it {what} to {source}, which "
                f"defines it. {_HIDE}"
            )
    return None
