"""Which USD files the open stage has loaded, so flatten_usd and export_prim_as_file never write over one of its
layers, and read a layer again from its file only when nothing is lost by it (#81).

Sdf keeps one layer per file in its registry while anything holds it, and every open of that file gets that layer:
the open stage's own, with its unsaved edits, and any other Kit still holds. Before #81 the two tools cleared the
layer the registry held for their input and output paths, so a stale copy couldn't be served; for a layer the open
stage uses, that emptied the open scene.

Kit-free, so unit-tested against usd-core's stages: the handlers pass in the open stage.
"""

from collections.abc import Iterable
from pathlib import Path, PurePath

from pxr import Sdf, Usd

from .usd import find_layer, has_unsaved_edits


def _same_file(path: str, real_path: str) -> bool:
    """Whether path names the file at a layer's real path as the file system sees it: Sdf's registry tells apart
    spellings of one file that the file system doesn't, such as another case on Windows or a Mac, or a link. Only a
    file name that matches but for its case is compared, since each comparison reads the disk."""
    if PurePath(path).name.casefold() != PurePath(real_path).name.casefold():
        return False
    try:
        return Path(path).samefile(real_path)
    except (OSError, ValueError):  # no such file, or a URL
        return False


def _layers_at(path: str, layers: Iterable[Sdf.Layer]) -> list[Sdf.Layer]:
    """Those of layers that path names: the one the registry finds under that name, which takes a relative path, `..`
    and either slash, and a URL whose layer's real path may be a local copy; and any whose file is the same file."""
    found = find_layer(path)
    return [
        layer for layer in layers if (found and layer == found) or (layer.realPath and _same_file(path, layer.realPath))
    ]


def _role(stage: Usd.Stage, layer: Sdf.Layer) -> str:
    if layer == stage.GetRootLayer():
        return "the open stage's root layer"
    if layer == stage.GetSessionLayer():
        return "the open stage's session layer"
    if layer in stage.GetLayerStack(includeSessionLayers=True):
        return "a sublayer of the open stage"
    return "a layer the open stage references or pays in"


def write_refusal(stage: Usd.Stage, path: str) -> str | None:
    """Why flatten_usd or export_prim_as_file must not write path, or None when it may.

    A layer the open stage uses is refused even with no unsaved edits: Export writes the file under the layer, so the
    open scene and its file would part, and the next save or reload would lose one of them. A layer only Kit holds,
    outside the open stage, is refused when it has unsaved edits, which reading it again after the write would drop.
    The open stage's layers are the ones it uses now: an unloaded payload's or a muted sublayer's file isn't one."""
    used = _layers_at(path, stage.GetUsedLayers())
    if used:
        return (
            f"{path} is {_role(stage, used[0])}: writing it would overwrite a file the open scene is made of. "
            "Write to another path; to save the open stage to its own file, use save_scene."
        )
    if any(has_unsaved_edits(layer) for layer in _layers_at(path, Sdf.Layer.GetLoadedLayers())):
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
    the second the layer was loaded in looks unchanged."""
    used = stage.GetUsedLayers()
    return [
        layer
        for layer in layers
        if not Sdf.Layer.IsAnonymousLayerIdentifier(layer.identifier)
        and layer not in used
        and not has_unsaved_edits(layer)
        and layer.Reload(force=True)
    ]


def open_to_flatten(stage: Usd.Stage, path: str) -> Usd.Stage:
    """path opened as a stage, for flatten_usd.

    The open takes the layer Kit already holds for any of its files rather than reading the file. Those the open
    stage uses, and those with unsaved edits, are flattened as Kit holds them, unsaved edits too, as the open stage is
    with no input_path: reading them again would change the open scene or drop the edits. Any other is read again from
    its file first, since nothing is lost by it, and a file changed since Kit loaded it would otherwise be flattened as
    it was: the stale copy the old Clear() was there to keep out."""
    held = set(Sdf.Layer.GetLoadedLayers())
    opened = Usd.Stage.Open(path)
    refresh(stage, [layer for layer in opened.GetUsedLayers() if layer in held])
    return opened


def refresh_written(stage: Usd.Stage, path: str) -> list[Sdf.Layer]:
    """After path is written: a layer Kit still holds for it, which write_refusal let through, read again, so the next
    open of path gets the file just written rather than the content before it."""
    return refresh(stage, _layers_at(path, Sdf.Layer.GetLoadedLayers()))
