"""RTX's exposure schemas on a camera a feed rendered through, taken back out of the stage's files (#177).

Kit 110's RTX gives a camera it renders through two API schemas and three exposure attributes when the camera lacks
them, and writes them at the stage's edit target, the user's file: a capture through a scene camera left them in the
root layer, which the next save kept. Kit's own cameras carry them already (Isaac Sim 6.2, Kit 110.4, 2026-11-02).

Authoring them in Kit's session layer first kept RTX from writing, but Kit then hung in its own layer bookkeeping in
two live runs of three, so the bridge doesn't write while a feed renders: `Marks.take` notes what the edit target held
of a camera before a feed first renders through it, and `Marks.let_go` puts that back once the last feed through it
has gone, when the feed's render product is deleted, as Kit's own render product writes are taken back.
"""

from dataclasses import dataclass, field

from pxr import Sdf, Usd

from .usd import is_explicit, list_op_items, prim_spec, remove_child_spec

SCHEMAS = ("OmniRtxCameraAutoExposureAPI_1", "OmniRtxCameraExposureAPI_1")
ATTRIBUTES = ("exposure:fStop", "exposure:responsivity", "exposure:time")

_NOTHING = object()  # an attribute spec with no default


@dataclass
class Mark:
    """What one layer held of a camera's exposure, before RTX could write it there: its apiSchemas, the three
    attributes' specs and defaults, and which of the camera's specs and its ancestors' the layer lacked."""

    layer: Sdf.Layer
    path: Sdf.Path
    api: Sdf.TokenListOp | None = None
    attributes: dict[str, object] = field(default_factory=dict)  # each spec there before, by name: its default
    absent: list[Sdf.Path] = field(default_factory=list)

    def restore(self) -> None:
        """Puts the camera's exposure in the layer back as it was, in one change block: the schemas RTX prepended go
        and an apiSchemas the spec held comes back, each attribute that wasn't there goes and one that was gets its
        default back, and each spec the layer lacked goes once it holds nothing."""
        layer = self.layer
        with Sdf.ChangeBlock():
            spec = prim_spec(layer, self.path)
            if spec is not None:
                if self.api is None:
                    if spec.HasInfo("apiSchemas"):
                        rest = _without(spec.GetInfo("apiSchemas"), SCHEMAS)
                        if rest is None:
                            spec.ClearInfo("apiSchemas")
                        else:
                            spec.SetInfo("apiSchemas", rest)
                else:
                    spec.SetInfo("apiSchemas", self.api)
                for name in ATTRIBUTES:
                    attribute = spec.attributes.get(name)
                    if name not in self.attributes:
                        if attribute is not None:
                            spec.RemoveProperty(attribute)
                    elif attribute is not None:
                        before = self.attributes[name]
                        if before is _NOTHING:
                            attribute.ClearDefaultValue()
                        else:
                            attribute.default = before
            for path in sorted(self.absent, key=lambda p: p.pathElementCount, reverse=True):
                made = prim_spec(layer, path)
                parent = prim_spec(layer, path.GetParentPath())
                if made is not None and parent is not None and made.IsInert():
                    remove_child_spec(parent, made.name)


def _without(op: Sdf.TokenListOp, names: tuple[str, ...]) -> Sdf.TokenListOp | None:
    """op with names taken out of each of its lists; None when nothing is left in it."""
    if is_explicit(op):
        kept = [item for item in op.explicitItems if item not in names]
        return Sdf.TokenListOp.CreateExplicit(kept)
    op.prependedItems = [item for item in op.prependedItems if item not in names]
    op.appendedItems = [item for item in op.appendedItems if item not in names]
    return op if (op.prependedItems or op.appendedItems or op.deletedItems or op.orderedItems) else None


def _applied(prim: Usd.Prim) -> set[str]:
    """The API schemas the prim's layers apply, by name, registered or not: usd-core's `GetAppliedSchemas` leaves out
    a schema it has no definition of, as it has none of RTX's."""
    op = prim.GetMetadata("apiSchemas")
    named = set(list_op_items(op)) if isinstance(op, Sdf.TokenListOp) else set[str]()
    return named | set(prim.GetAppliedSchemas())


def bare(prim: Usd.Prim) -> bool:
    """Whether RTX would write onto the camera: it lacks a schema or an attribute's value."""
    return not set(SCHEMAS) <= _applied(prim) or not all(prim.GetAttribute(n).HasAuthoredValue() for n in ATTRIBUTES)


def mark(layer: Sdf.Layer, camera_path: str) -> Mark:
    """What `layer` holds of the camera at `camera_path`'s exposure now."""
    path = Sdf.Path(camera_path)
    noted = Mark(layer, path, absent=[p for p in path.GetPrefixes() if prim_spec(layer, p) is None])
    spec = prim_spec(layer, path)
    if spec is not None:
        noted.api = spec.GetInfo("apiSchemas") if spec.HasInfo("apiSchemas") else None
        for name in ATTRIBUTES:
            attribute = spec.attributes.get(name)
            if attribute is not None:
                noted.attributes[name] = attribute.default if attribute.HasDefaultValue() else _NOTHING
    return noted


@dataclass
class _Taken:
    mark: Mark
    feeds: int = 1


class Marks:
    """The cameras feeds render through that RTX may write onto, by layer and camera: the first feed's mark, kept
    while any feed renders through the camera, and put back when the last lets go."""

    def __init__(self) -> None:
        self._taken: dict[tuple[str, Sdf.Path], _Taken] = {}

    def take(self, stage: Usd.Stage, camera_path: str) -> tuple[str, Sdf.Path] | None:
        """Notes the camera for one more feed, before it renders: its key for `let_go`, or None when RTX writes nothing
        onto it (no prim, one inside an instance, or one that carries everything already) and no feed holds a mark."""
        layer = stage.GetEditTarget().GetLayer()
        key = (layer.identifier, Sdf.Path(camera_path))
        taken = self._taken.get(key)
        if taken is not None:
            taken.feeds += 1
            return key
        prim = stage.GetPrimAtPath(camera_path)
        if not prim.IsValid() or prim.IsInstanceProxy() or not bare(prim):
            return None
        self._taken[key] = _Taken(mark(layer, camera_path))
        return key

    def let_go(self, key: tuple[str, Sdf.Path], layers: list[Sdf.Layer]) -> None:
        """One feed less on the camera; the last puts its mark back, when its layer is still one of `layers`, the
        stage's: a layer the stage no longer holds went with what RTX wrote into it."""
        taken = self._taken.get(key)
        if taken is None:
            return
        taken.feeds -= 1
        if taken.feeds > 0:
            return
        del self._taken[key]
        if any(layer.identifier == key[0] for layer in layers):
            taken.mark.restore()

    def feeds(self, key: tuple[str, Sdf.Path]) -> int:
        """How many feeds hold the camera's mark."""
        taken = self._taken.get(key)
        return taken.feeds if taken is not None else 0

    def forget(self) -> None:
        """Drops every mark, put back or not: Kit is going."""
        self._taken.clear()


MARKS = Marks()
