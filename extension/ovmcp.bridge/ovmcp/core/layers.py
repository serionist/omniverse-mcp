"""Which USD files the open stage has loaded, so flatten_usd, export_prim_as_file and save_scene never write over one
of its layers, and read a layer again from its file only when nothing is lost by it (#81, #85).

Sdf keeps one layer per file in its registry while anything holds it, and every open of that file gets that layer:
the open stage's own, with its unsaved edits, and any other Kit still holds. Before #81 the two tools cleared the
layer the registry held for their input and output paths, so a stale copy couldn't be served; for a layer the open
stage uses, that emptied the open scene.

Kit-free, so unit-tested against usd-core's stages: the handlers pass in the open stage.
"""

import os
from collections.abc import Callable, Iterable
from pathlib import Path, PurePath
from typing import TypeVar

from pxr import Sdf, Tf, Usd

from .stage_open import path_of
from .usd import find_layer, has_unsaved_edits

T = TypeVar("T")


def _unless_gone(layer: Sdf.Layer, read: Callable[[Sdf.Layer], T], gone: T) -> T:
    """read(layer), or gone when the layer has gone.

    Sdf.Layer.GetLoadedLayers gives weak handles, which keep no layer alive: a stage Python's garbage collector frees
    while they are walked takes its layers with it, and any read of a gone one raises (CI's Python 3.14 met it, #85).
    Python can't hold one alive meanwhile, since Find gives back the same weak object. A gone layer is passed over,
    never refused: nothing holds it any more, so it has no edits to lose and can't go stale."""
    try:
        return read(layer)
    except TypeError:  # Boost.Python's ArgumentError, which an expired handle raises for any call
        return gone


def _stat(path: str) -> os.stat_result | None:
    """The file at path as the file system knows it, through any link, a file: URL as the path it names (Kit names a
    layer opened from one file:/C:/...); None for no such file, or another URL."""
    try:
        return Path(path_of(path)).stat()
    except (OSError, ValueError):
        return None


def _layers_at(path: str, layers: Iterable[Sdf.Layer], *, any_name: bool = False) -> list[Sdf.Layer]:
    """Those of layers that path names: the one the registry finds under that name, which takes a relative path, `..`
    and either slash; and, when path is a file that exists, those whose file is that file as the file system sees
    it: by another case on Windows or a Mac, through a link, or as a file: URL.

    Without any_name, only a layer whose file has path's file name, but for case, is looked up on disk, so a link or a
    Windows short name under another name is missed; any_name looks up every layer's file, a disk read each."""
    found = find_layer(path)
    target = _stat(path)
    name = PurePath(path_of(path)).name.casefold()

    def named(layer: Sdf.Layer) -> bool:
        if found and layer == found:
            return True
        real = _unless_gone(layer, lambda handle: handle.realPath, "")
        if target is None or not real:
            return False
        if not any_name and PurePath(path_of(real)).name.casefold() != name:
            return False
        held = _stat(real)
        return held is not None and os.path.samestat(target, held)

    return [layer for layer in layers if named(layer)]


def _role(stage: Usd.Stage, layer: Sdf.Layer) -> str:
    if layer == stage.GetRootLayer():
        return "the open stage's root layer"
    if layer == stage.GetSessionLayer():
        return "the open stage's session layer"
    if layer in stage.GetLayerStack(includeSessionLayers=True):
        return "a sublayer of the open stage"
    return "a layer the open stage references or pays in"


def write_refusal(stage: Usd.Stage, path: str, *, saving: bool = False) -> str | None:
    """Why flatten_usd or export_prim_as_file must not write path, or None when it may; with saving, why save_scene
    must not write the open stage's root layer there.

    A layer the open stage uses is refused even with no unsaved edits: Export writes the file under the layer, so the
    open scene and its file would part, and the next save or reload would lose one of them. A layer only Kit holds,
    outside the open stage, is refused when it has unsaved edits, which reading it again after the write would drop.
    The open stage's layers are the ones it uses now: an unloaded payload's or a muted sublayer's file isn't one.

    Every file the open stage uses is compared with path's, whatever its name: Export writes through a link, so a link
    to the scene's file under another name would land on it. Held layers outside the stage are compared by name only,
    where a miss leaves one stale rather than writing over the scene.

    With saving, the root layer is what is written, so its own file may be, by any name: that is a save (#85)."""
    in_use = stage.GetUsedLayers()
    used = _layers_at(path, in_use, any_name=True)
    root = stage.GetRootLayer()
    # A stage never saved, such as new_scene's, has no file of its own: save_scene without a path fails for it.
    has_file = not Sdf.Layer.IsAnonymousLayerIdentifier(root.identifier)
    if saving:
        used = [layer for layer in used if layer != root]
        if used:
            own_file = ", or call save_scene without a file_path to save the open stage to its own file"
            return (
                f"{path} is {_role(stage, used[0])}: saving the root layer there would overwrite a file the open scene "
                f"is made of. Save to another path{own_file if has_file else ''}."
            )
    if used:
        own_file = "; to save the open stage to its own file, use save_scene"
        return (
            f"{path} is {_role(stage, used[0])}: writing it would overwrite a file the open scene is made of. "
            f"Write to another path{own_file if has_file else ''}."
        )
    # Only layers outside the open stage: a save lets the root layer through, and its unsaved edits are what it writes.
    held = [layer for layer in _layers_at(path, Sdf.Layer.GetLoadedLayers()) if layer not in in_use]
    if any(_unless_gone(layer, has_unsaved_edits, False) for layer in held):
        return (
            f"{path} is loaded in Kit with unsaved edits, outside the open stage: writing it would lose them. "
            "Write to another path, or save that layer first."
        )
    return None


def refresh(stage: Usd.Stage, layers: Iterable[Sdf.Layer]) -> list[Sdf.Layer]:
    """Read again from its file each of layers that the open stage doesn't use and that has no unsaved edits; the ones
    read again. One whose file is gone stays as it is.

    A layer the open stage uses stays as it is, since reading it again would change the open scene, and so does one
    with unsaved edits, which it would drop. An anonymous layer has no file: reading one again empties it. force,
    since USD compares a file's time with the time it was loaded at, to the second on Windows: a file written within
    the second the layer was loaded in looks unchanged. A layer gone since it was listed is passed over."""
    used = set(stage.GetUsedLayers())

    def read_again(layer: Sdf.Layer) -> bool:
        return (
            not Sdf.Layer.IsAnonymousLayerIdentifier(layer.identifier)
            and layer not in used
            and not has_unsaved_edits(layer)
            and layer.Reload(force=True)
        )

    return [layer for layer in layers if _unless_gone(layer, read_again, False)]


def open_to_flatten(stage: Usd.Stage, path: str) -> Usd.Stage | None:
    """path opened as a stage, for flatten_usd; None when USD can't open it, with no file there or none it reads.

    The open takes the layer Kit already holds for any of its files rather than reading the file. Those the open
    stage uses, and those with unsaved edits, are flattened as Kit holds them, unsaved edits too, as the open stage is
    with no input_path: reading them again would change the open scene or drop the edits. Any other is read again from
    its file first, since nothing is lost by it, and a file changed since Kit loaded it would otherwise be flattened as
    it was: the stale copy the old Clear() was there to keep out."""
    held = set(Sdf.Layer.GetLoadedLayers())
    try:
        opened = Usd.Stage.Open(path)
    except Tf.ErrorException:  # pxr raises its errors in Python rather than returning no stage
        return None
    refresh(stage, [layer for layer in opened.GetUsedLayers() if layer in held])
    return opened


def refresh_written(stage: Usd.Stage, path: str) -> list[Sdf.Layer]:
    """After path is written: a layer Kit still holds for it, which write_refusal let through, read again, so the next
    open of path gets the file just written rather than the content before it."""
    return refresh(stage, _layers_at(path, Sdf.Layer.GetLoadedLayers()))
