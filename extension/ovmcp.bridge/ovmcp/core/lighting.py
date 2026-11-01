"""Which viewport lighting mode is in effect, what the legacy camera-light switch sets, and which lights are the
stage's own: no Kit."""

from collections.abc import Iterator

from pxr import Sdf, Usd

from .isolation import is_light

# Where Kit's lighting menu (omni.kit.viewport.menubar.lighting, 107.3) puts a light rig: an over in the session layer
# that references the rig's file, whose prims define the lights. The path is a literal in Kit's code, exported nowhere;
# NVIDIA's asset validator skips it too, as a prim Kit makes (#117).
LIGHT_RIG = Sdf.Path("/OmniKit_Viewport_LightRig")


def current_mode(camera_light_flag: bool, menu_mode: str | None) -> str:
    """The renderer's camera-light flag is the truth for "camera"; otherwise the lighting menu's mode, or "stage".

    The menu keeps its own record, which goes stale when a script or an older bridge sets the flag directly.
    """
    if camera_light_flag:
        return "camera"
    if not menu_mode or menu_mode == "camera":
        return "stage"
    return menu_mode


def camera_light_switch(enabled: bool, current: str) -> str | None:
    """The mode set_camera_light sets, or None to only clear the camera-light flag and leave a rig alone."""
    if enabled:
        return "camera"
    return "stage" if current == "camera" else None


def scene_lights(stage: Usd.Stage) -> Iterator[Usd.Prim]:
    """The stage's own active lights, inside instances too, as the walk inside every instance finds them and in its
    order; never a light rig's, which lights the viewport and is gone in mode stage (#117).

    A light an instanceable reference brings, a lamp asset's, lights the scene as much (#105, review I7). It comes as
    its instance proxy, from the instance's prototype, which is walked once however many instances share it: a stage
    of many instanced assets would cost a walk of every copy on Kit's main thread. Lazy, so a yes or no stops at the
    first light.
    """
    in_prototype: dict[Sdf.Path, list[Sdf.Path]] = {}

    def inside(instance: Usd.Prim) -> list[Sdf.Path]:
        """The paths, relative to the instance, of the lights its prototype holds, a nested instance's included."""
        prototype = instance.GetPrototype()
        key = prototype.GetPath()
        if key not in in_prototype:
            found: list[Sdf.Path] = []
            for prim in Usd.PrimRange(prototype):
                if prim == prototype:
                    continue  # the instance itself, which the stage's walk has seen
                relative = prim.GetPath().MakeRelativePath(key)
                if is_light(prim):
                    found.append(relative)
                if prim.IsInstance():
                    found.extend(relative.AppendPath(path) for path in inside(prim))
            in_prototype[key] = found
        return in_prototype[key]

    walk = iter(Usd.PrimRange.Stage(stage))
    for prim in walk:
        if prim.GetPath() == LIGHT_RIG:
            walk.PruneChildren()
            continue
        if is_light(prim):
            yield prim
        if prim.IsInstance():
            for relative in inside(prim):
                yield stage.GetPrimAtPath(prim.GetPath().AppendPath(relative))
