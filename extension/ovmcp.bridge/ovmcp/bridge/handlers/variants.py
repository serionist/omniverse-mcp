"""The viewport's refresh after a variant switch (#155).

With Fabric Scene Delegate on, a switched prim's old geometry could stay on screen (OMPE-54434, OMPE-70769, OMPE-71336):
the prims are made inactive for some updates, then active again, so Hydra rebuilds them. The toggle is written in Kit's
session layer, whichever layer the selection went to, and put back from a snapshot of its own in a finally: before,
it was written at the edit target, the user's file, and left `active = true` there, and an error or a cancel between
the two writes left the prim hidden. Without Fabric Scene Delegate, or from Kit 110, where a switch shows without the
toggle (measured on Isaac Sim 6.2), a few updates show the switch.
"""

from collections.abc import Iterable

import carb.settings
from pxr import Sdf, Usd

from ovmcp.core import protocol, variants

from ._utils import _next_update

# The updates the prims stay inactive, then the updates after, as the toggle has always waited; and the updates a switch
# waits without the toggle.
HIDDEN_UPDATES = 10
SHOWN_UPDATES = 30
PLAIN_UPDATES = 5


def fabric_scene_delegate() -> bool:
    return bool(carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate"))


async def refresh(stage: Usd.Stage, paths: Iterable[Sdf.Path]) -> None:
    """Waits until the viewport shows the switch of the prims at paths, all switched at once: with Fabric Scene
    Delegate on before Kit 110, the top-most of them are made inactive in the session layer, in one change, for
    HIDDEN_UPDATES, then the layer is put back exactly, whatever happens meanwhile."""
    if not fabric_scene_delegate() or not variants.toggle_needed(protocol.kit_app()["kit_version"]):
        for _ in range(PLAIN_UPDATES):
            await _next_update()
        return
    hidden = variants.deactivate(stage.GetSessionLayer(), variants.top_most(paths))
    try:
        for _ in range(HIDDEN_UPDATES):
            await _next_update()
    finally:
        hidden.restore()
    for _ in range(SHOWN_UPDATES):
        await _next_update()
