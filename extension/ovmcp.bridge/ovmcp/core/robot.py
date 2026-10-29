"""Where create_robot loads a robot's USD file from, and the prim it makes for it; where get_joint_states finds a
robot's articulation.

Kit-free, so unit-tested without Kit: the handler passes in how to find Isaac Sim's asset root and whether a file
exists on the Kit app's machine.
"""

import re
from collections.abc import Callable
from pathlib import PureWindowsPath

from pxr import Tf, Usd, UsdPhysics

from .usd import has_api

# A path in Isaac Sim's asset library, such as the robots' own, is found under the library's root, a URL Isaac Sim
# knows; any other path is a file on the Kit app's machine.
LIBRARY_PREFIX = "/Isaac/"
USD_SUFFIXES = (".usd", ".usda", ".usdc", ".usdz")
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def is_usd_file(robot_type: str) -> bool:
    """Whether robot_type names a USD file, rather than a robot of the library by its name."""
    return robot_type.lower().endswith(USD_SUFFIXES)


def robot_prim_path(robot_type: str) -> str:
    """The prim a robot gets when create_robot is given none: `/World/Franka` for a name, `/World/<stem>` for a file."""
    # PureWindowsPath splits on both / and \, so a URL, a POSIX path and a Windows path all give their file's stem.
    name = PureWindowsPath(robot_type).stem if is_usd_file(robot_type) else robot_type.capitalize()
    return "/World/" + Tf.MakeValidIdentifier(name)


def robot_usd_url(
    usd_path: str,
    assets_root: Callable[[], str | None],
    is_file: Callable[[str], bool],
    whole: Callable[[str], str],
) -> str | None:
    """Where to load usd_path from: a URL as given, a file on this machine made whole, a library path under the
    library's root; None for a path that is none of these. assets_root is asked only for a library path: Isaac Sim may
    look on the network to find it."""
    if _URL.match(usd_path):
        return usd_path
    if is_file(usd_path):
        # A reference reads a relative path against the stage's own folder, not the one Kit was started in.
        return whole(usd_path)
    if usd_path.startswith(LIBRARY_PREFIX):
        root = assets_root()
        return root.rstrip("/") + usd_path if root else usd_path
    return None


def articulation_root(prim: Usd.Prim) -> str | None:
    """The path of the robot's articulation root: prim itself, or its first descendant with ArticulationRootAPI, inside
    instanced assets too, as get_robot_info finds it. Isaac Sim 5.1 and 6.2 look for it each their own way, so the
    bridge finds it once for both. None when prim holds no articulation."""
    for desc in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if has_api(desc, UsdPhysics.ArticulationRootAPI):
            return str(desc.GetPath())
    return None
