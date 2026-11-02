"""RTX's exposure schemas on a camera a feed renders through, kept out of the stage's files (#177).

Kit 110's RTX gives a camera it renders through two API schemas and three exposure attributes when the camera lacks
them, and writes them at the stage's edit target, the user's file: a capture through a scene camera left them in the
root layer, which the next save keeps. Kit's own cameras carry them already. `shield` authors what a camera lacks in
Kit's session layer before a feed renders through it, which was measured to keep RTX from writing anything (Isaac Sim
6.2, Kit 110.4, 2026-11-02; with only the schemas there, RTX still wrote the attributes), and `Shield.lift` takes
exactly that back once the feed renders through another camera or none.
"""

from dataclasses import dataclass, field

from pxr import Sdf, Usd

from .usd import is_explicit, list_op_items, prim_spec, remove_child_spec

SCHEMAS = ("OmniRtxCameraAutoExposureAPI_1", "OmniRtxCameraExposureAPI_1")
# The values RTX wrote for a camera that had none, so a shielded camera renders as it would have unshielded.
ATTRIBUTES = (("exposure:fStop", 5.0), ("exposure:responsivity", 1.1026709), ("exposure:time", 0.02))


@dataclass
class Shield:
    """What `shield` wrote into one layer for one camera, and what the layer held there before."""

    layer: Sdf.Layer
    path: Sdf.Path
    api_before: Sdf.TokenListOp | None = None  # the spec's apiSchemas before; None when it held none
    schemas: list[str] = field(default_factory=list)
    attributes: list[str] = field(default_factory=list)  # attribute specs it made
    defaults: list[str] = field(default_factory=list)  # attribute specs that were there with no value
    created: list[Sdf.Path] = field(default_factory=list)  # prim specs the layer lacked: the camera's, its ancestors'

    def lift(self) -> None:
        """Puts the layer back as it was at the camera, in one change block: the schemas, the attributes and the specs
        it made go, an apiSchemas the spec held comes back as it was."""
        layer = self.layer
        with Sdf.ChangeBlock():
            spec = prim_spec(layer, self.path)
            if spec is not None:
                for name in self.attributes:
                    attribute = spec.attributes.get(name)
                    if attribute is not None:
                        spec.RemoveProperty(attribute)
                for name in self.defaults:
                    attribute = spec.attributes.get(name)
                    if attribute is not None:
                        attribute.ClearDefaultValue()
                if self.schemas:
                    if self.api_before is None:
                        spec.ClearInfo("apiSchemas")
                    else:
                        spec.SetInfo("apiSchemas", self.api_before)
            for path in sorted(self.created, key=lambda p: p.pathElementCount, reverse=True):
                made = prim_spec(layer, path)
                parent = prim_spec(layer, path.GetParentPath())
                if made is not None and parent is not None and made.IsInert():
                    remove_child_spec(parent, made.name)


def _with_schemas(before: Sdf.TokenListOp | None, schemas: list[str]) -> Sdf.TokenListOp:
    """`before` with `schemas` added: to its explicit items when it is explicit, else prepended."""
    if before is not None and is_explicit(before):
        return Sdf.TokenListOp.CreateExplicit([*before.explicitItems, *schemas])
    op = Sdf.TokenListOp()
    if before is not None:
        op.appendedItems = before.appendedItems
        op.deletedItems = before.deletedItems
        op.orderedItems = before.orderedItems
    op.prependedItems = [*(before.prependedItems if before is not None else []), *schemas]
    return op


def _applied(prim: Usd.Prim) -> set[str]:
    """The API schemas the prim's layers apply, by name, registered or not: usd-core's `GetAppliedSchemas` leaves out
    a schema it has no definition of, as it has none of RTX's."""
    op = prim.GetMetadata("apiSchemas")
    named = set(list_op_items(op)) if isinstance(op, Sdf.TokenListOp) else set[str]()
    return named | set(prim.GetAppliedSchemas())


def shield(stage: Usd.Stage, camera_path: str) -> Shield | None:
    """Authors in `stage`'s session layer the exposure schemas and attributes the camera at `camera_path` lacks, so RTX
    writes none of them at the edit target; None when it lacks none, or there is no prim to shield."""
    prim = stage.GetPrimAtPath(camera_path)
    if not prim.IsValid() or prim.IsInstanceProxy():
        return None
    applied = _applied(prim)
    schemas = [name for name in SCHEMAS if name not in applied]
    missing = [(name, value) for name, value in ATTRIBUTES if not prim.GetAttribute(name).HasAuthoredValue()]
    if not schemas and not missing:
        return None
    layer = stage.GetSessionLayer()
    path = Sdf.Path(camera_path)
    made = Shield(layer, path, created=[p for p in path.GetPrefixes() if prim_spec(layer, p) is None])
    with Sdf.ChangeBlock():
        spec = Sdf.CreatePrimInLayer(layer, path)
        if schemas:
            made.api_before = spec.GetInfo("apiSchemas") if spec.HasInfo("apiSchemas") else None
            spec.SetInfo("apiSchemas", _with_schemas(made.api_before, schemas))
            made.schemas = schemas
        for name, value in missing:
            attribute = spec.attributes.get(name)
            if attribute is None:
                attribute = Sdf.AttributeSpec(spec, name, Sdf.ValueTypeNames.Float)
                made.attributes.append(name)
            else:
                made.defaults.append(name)
            attribute.default = value
    return made
