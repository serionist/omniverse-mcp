"""Whether create_robot was given a USD file or a robot's name, and the prim it makes for it; where
/robot/joint_states, which get_robot_info reads, finds a robot's articulation. Where the file loads from is
ovmcp.core.usd_files's rule, which open_scene shares; the turn and the scale that bring it to the stage are
ovmcp.core.metrics', which create_prim shares.

Kit-free, so unit-tested without Kit.
"""

from pathlib import PureWindowsPath

from pxr import Tf, Usd, UsdPhysics

from .usd import has_api

USD_SUFFIXES = (".usd", ".usda", ".usdc", ".usdz")


def is_usd_file(robot_type: str) -> bool:
    """Whether robot_type names a USD file, rather than a robot of the library by its name."""
    return robot_type.lower().endswith(USD_SUFFIXES)


def robot_prim_path(robot_type: str) -> str:
    """The prim a robot gets when create_robot is given none: `/World/Franka` for a name, `/World/<stem>` for a file."""
    # PureWindowsPath splits on both / and \, so a URL, a POSIX path and a Windows path all give their file's stem.
    name = PureWindowsPath(robot_type).stem if is_usd_file(robot_type) else robot_type.capitalize()
    return "/World/" + Tf.MakeValidIdentifier(name)


def articulation_root(prim: Usd.Prim) -> str | None:
    """The path of the robot's articulation root: prim itself, or its first descendant with ArticulationRootAPI, inside
    instanced assets too, as get_robot_info finds it. Isaac Sim 5.1 and 6.2 look for it each their own way, so the
    bridge finds it once for both. None when prim holds no articulation."""
    for desc in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if has_api(desc, UsdPhysics.ArticulationRootAPI):
            return str(desc.GetPath())
    return None
