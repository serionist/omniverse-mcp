"""A prim's variant sets, and a switch of any number of them in one layer, with a snapshot that puts that layer back
exactly (#155). Needs pxr, not Kit: the tests run it on usd-core.

A check switches in Kit's session layer, which no save writes, so every file stays as it found it; a selection meant to
stay goes to the edit target. Putting a layer back means writing each field back as it was, never writing the old
selection: that turned a selection the file never held into one it holds. Usd's ClearVariantSelection() and
Sdf.CleanupEnabler can't do it either: the first leaves an over for each prim on the way, in the user's file too, and
the second also deletes a bare over that was already there (both measured on usd-core 26.11).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pxr import Sdf, Usd

from .deletion import instance_of
from .usd import prim_spec, remove_child_spec, select, selections, unselect
from .xform import layer_name, layer_ranks


@dataclass(frozen=True)
class VariantSet:
    """One variant set of a prim as the prim block gives it."""

    name: str
    selection: str  # "" when none is selected, a blocked selection too
    options: tuple[str, ...]  # USD's order, by name
    layer: str | None  # the layer holding the selection: session, root or a file's name; None when none holds one


def _label(stage: Usd.Stage, layer: Sdf.Layer) -> str:
    if layer == stage.GetSessionLayer():
        return "session"
    if layer == stage.GetRootLayer():
        return "root"
    return layer.GetDisplayName() or layer.identifier


def variant_sets(prim: Usd.Prim) -> list[VariantSet]:
    """Each of prim's variant sets in order, with its selection, its options and the layer holding the selection: the
    strongest spec of the prim that holds one for the set."""
    sets = prim.GetVariantSets()
    names = sets.GetNames()
    if not names:
        return []
    stage = prim.GetStage()
    stack = [(spec.layer, selections(spec)) for spec in prim.GetPrimStack()]
    found: list[VariantSet] = []
    for name in names:
        variant_set = sets.GetVariantSet(name)
        holder = next((layer for layer, held in stack if name in held), None)
        found.append(
            VariantSet(
                name,
                variant_set.GetVariantSelection(),
                tuple(variant_set.GetVariantNames()),
                _label(stage, holder) if holder is not None else None,
            )
        )
    return found


def format_variant_sets(sets: Iterable[VariantSet]) -> str:
    """The prim block's value: `state: open [closed, open] (session); lod: none [high, low]`, or [] for no set."""
    parts = [
        f"{s.name}: {s.selection or 'none'} [{', '.join(s.options)}]" + (f" ({s.layer})" if s.layer else "")
        for s in sets
    ]
    return "; ".join(parts) or "[]"


def variant_json(prim: Usd.Prim) -> list[dict[str, object]]:
    """variant_sets as the JSON forms give them."""
    return [
        {"name": s.name, "selection": s.selection, "options": list(s.options), "layer": s.layer}
        for s in variant_sets(prim)
    ]


# ----- what is refused -----


def _stronger_holder(prim: Usd.Prim, variant_set: str, layer: Sdf.Layer) -> tuple[Sdf.Layer, str] | None:
    """The strongest of the stage's own layers above layer that holds a selection for prim's variant_set, with it."""
    rank = layer_ranks(prim.GetStage())
    target = rank.get(layer.identifier, len(rank))
    for spec in prim.GetPrimStack():
        held = selections(spec)
        if rank.get(spec.layer.identifier, len(rank) + 1) < target and variant_set in held:
            return spec.layer, held[variant_set]
    return None


def variant_refusal(prim: Usd.Prim, variant_set: str, name: str, layer: Sdf.Layer) -> str | None:
    """Why selecting name in prim's variant_set, written to layer, isn't done, or None; name "" clears the layer's
    selection. A prim inside an instance, a set or a variant the prim lacks, and a stronger layer's selection, which
    would hide the write, are refused."""
    path = prim.GetPath()
    stage = prim.GetStage()
    if prim.IsInstanceProxy():
        instance = instance_of(prim).GetPath()
        return (
            f"{path} is inside the instance {instance}, whose prims can't be switched one by one: switch a variant set "
            f"of {instance} itself (get_prim_properties lists its variant_sets), or turn off its instanceable"
        )
    if prim.IsInPrototype():
        return f"{path} is in an instance prototype, which USD lets no one edit: switch the instance itself"
    sets = prim.GetVariantSets()
    if not sets.HasVariantSet(variant_set):
        if prim.HasAuthoredPayloads() and not prim.IsLoaded():
            return (
                f"{path} has no variant set {variant_set!r} while its payload isn't loaded, and the sets in the "
                "payload's file aren't composed: load it first, with execute_script (stage.Load(path))"
            )
        there = ", ".join(sets.GetNames()) or "none"
        return f"{path} has no variant set {variant_set!r}; its sets: {there}"
    options = sets.GetVariantSet(variant_set).GetVariantNames()
    if name and name not in options:
        return f"{path}'s variant set {variant_set!r} has no variant {name!r}; its variants: {', '.join(options)}"
    stronger = _stronger_holder(prim, variant_set, layer)
    if stronger is not None:
        holder, held = stronger
        way_out = (
            ': clear it there first with set_variant_selection(variant_name="", layer="session")'
            if holder == stage.GetSessionLayer()
            else ""
        )
        return (
            f"{layer_name(stage, holder)} holds {path}'s {variant_set} selection ({held or 'none'}), which outranks "
            f"{layer_name(stage, layer)}, where it would be written: nothing would change{way_out}"
        )
    return None


def beneath(prim: Usd.Prim, variant_set: str, layer: Sdf.Layer) -> str | None:
    """The selection for prim's variant_set that the layers under layer hold, what shows once layer holds none: a
    variant's name, "" for a blocked one, None when none of them holds one."""
    rank = layer_ranks(prim.GetStage())
    target = rank.get(layer.identifier, len(rank))
    for spec in prim.GetPrimStack():
        held = selections(spec)
        if rank.get(spec.layer.identifier, len(rank) + 1) > target and variant_set in held:
            return held[variant_set]
    return None


# ----- the snapshot and the switch -----


def selections_of(layer: Sdf.Layer, path: Sdf.Path | str) -> dict[str, str]:
    """The selections layer holds for the prim at path, {} without a spec."""
    spec = prim_spec(layer, Sdf.Path(path))
    return selections(spec) if spec is not None else {}


class Snapshot:
    """What one layer held of some prims before a switch or a deactivation, and how to put each field back exactly: a
    selection absent, blocked or named, the active field, and the specs it lacked, removed once they hold nothing."""

    def __init__(self, layer: Sdf.Layer) -> None:
        self.layer = layer
        self.notes: list[str] = []
        self.wrote = False  # whether the switch it was taken for wrote anything
        self._selections: list[tuple[Sdf.Path, str, str | None]] = []
        self._active: list[tuple[Sdf.Path, bool | None]] = []
        self._absent: list[Sdf.Path] = []

    def keep(self, path: Sdf.Path, variant_sets: Iterable[str] = ()) -> None:
        """Records what the layer holds of the prim at path: its selections for variant_sets, its active field, and
        which of its specs, its ancestors' included, it lacks."""
        for prefix in path.GetPrefixes():
            if prim_spec(self.layer, prefix) is None and prefix not in self._absent:
                self._absent.append(prefix)
        spec = prim_spec(self.layer, path)
        held = selections(spec) if spec is not None else {}
        for name in variant_sets:
            self._selections.append((path, name, held.get(name)))
        self._active.append((path, spec.active if spec is not None and spec.HasActive() else None))

    def restore(self) -> None:
        """Puts back each field it recorded, in one change block of Sdf writes, and removes each spec the layer lacked
        that holds nothing now, children first. The earliest record of a field wins."""
        layer = self.layer
        with Sdf.ChangeBlock():
            for path, name, before in reversed(self._selections):
                spec = prim_spec(layer, path)
                if before is None:
                    if spec is not None and name in selections(spec):
                        unselect(spec, name)
                    continue
                select(spec if spec is not None else Sdf.CreatePrimInLayer(layer, path), name, before)
            for path, active in reversed(self._active):
                spec = prim_spec(layer, path)
                if active is not None:
                    (spec if spec is not None else Sdf.CreatePrimInLayer(layer, path)).active = active
                elif spec is not None and spec.HasActive():
                    spec.ClearActive()
            for path in sorted(self._absent, key=lambda p: p.pathElementCount, reverse=True):
                spec = prim_spec(layer, path)
                parent = prim_spec(layer, path.GetParentPath())
                if spec is not None and parent is not None and spec.IsInert():
                    remove_child_spec(parent, spec.name)
        self._selections.clear()
        self._active.clear()
        self._absent.clear()


Switches = Mapping[Sdf.Path, Mapping[str, str]]


def switch(stage: Usd.Stage, changes: Switches, layer: Sdf.Layer) -> Snapshot:
    """Writes each selection of changes, {prim: {set: variant}}, into layer, and returns the layer's snapshot from
    before; a variant "" clears the layer's selection for the set. ValueError, with nothing written, when any one is
    refused.

    Every Usd read comes first: the refusals, the instance notes, the snapshot. The writes are Sdf alone, in one change
    block, where Usd's API is unsafe; a clear where the layer holds nothing writes nothing, so it never adds an over to
    a user's file."""
    reasons: list[str] = []
    for path, sets in changes.items():
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            reasons.append(f"Prim not found: {path}")
            continue
        reasons += [why for name, variant in sets.items() if (why := variant_refusal(prim, name, variant, layer))]
    if reasons:
        raise ValueError("\n".join(reasons))
    snapshot = Snapshot(layer)
    for path, sets in changes.items():
        snapshot.keep(path, sets)
        if stage.GetPrimAtPath(path).IsInstance() and any(sets.values()):
            snapshot.notes.append(
                f"{path} is an instance: a selection of its own gives it a prototype of its own while it differs from "
                "the other instances'"
            )
    with Sdf.ChangeBlock():
        for path, sets in changes.items():
            for name, variant in sets.items():
                spec = prim_spec(layer, path)
                if variant:
                    select(spec if spec is not None else Sdf.CreatePrimInLayer(layer, path), name, variant)
                    snapshot.wrote = True
                elif spec is not None and name in selections(spec):
                    unselect(spec, name)
                    snapshot.wrote = True
    return snapshot


def top_most(paths: Iterable[Sdf.Path]) -> list[Sdf.Path]:
    """paths without those under another of them, or twice, in their order."""
    unique = list(dict.fromkeys(paths))
    return [p for p in unique if not any(p != other and p.HasPrefix(other) for other in unique)]


def deactivate(layer: Sdf.Layer, paths: Iterable[Sdf.Path]) -> Snapshot:
    """Makes each prim of paths inactive in layer, in one change block, and returns the layer's snapshot from before,
    which makes them active again with no opinion left behind."""
    snapshot = Snapshot(layer)
    chosen = list(paths)
    for path in chosen:
        snapshot.keep(path)
    with Sdf.ChangeBlock():
        for path in chosen:
            Sdf.CreatePrimInLayer(layer, path).active = False
    snapshot.wrote = bool(chosen)
    return snapshot


def session_selections(stage: Usd.Stage) -> list[str]:
    """Each variant selection Kit's session layer holds, as `/World/Area state=open`, which no save writes: a blocked
    one reads none."""
    found: list[str] = []

    def walk(spec: Sdf.PrimSpec) -> None:
        found.extend(f"{spec.path} {name}={variant or 'none'}" for name, variant in selections(spec).items())
        for child in spec.nameChildren:
            walk(child)

    for root in stage.GetSessionLayer().rootPrims:
        walk(root)
    return sorted(found)
