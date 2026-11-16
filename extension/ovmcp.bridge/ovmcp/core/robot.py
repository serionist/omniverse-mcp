"""Whether create_robot was given a USD file or a robot's name, and the prim it makes for it; where
/robot/joint_states, which get_robot_info reads, finds a robot's articulation. Where the file loads from is
ovmcp.core.usd_files's rule, which open_scene shares; the turn and the scale that bring it to the stage are
ovmcp.core.metrics', which create_prim shares.

Kit-free, so unit-tested without Kit.
"""

import math
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


BODY = "body"
ARTICULATION = "articulation"

# USD holds an angular drive's stiffness and damping per degree, and PhysX, through Isaac Sim's Articulation, per
# radian: its USD backend converts by 180/pi (isaacsim.core.experimental.prims' get_dof_gains and set_dof_gains, 6.2).
# A linear drive's are per stage unit in both, and a force limit has no angle in it (#199).
_PER_RADIAN_FROM_PER_DEGREE = 180.0 / math.pi


def from_usd_gain(value: float, angular: bool) -> float:
    """A drive's stiffness or damping as USD holds it, per degree for an angular drive, in physics' units, per
    radian."""
    return value * _PER_RADIAN_FROM_PER_DEGREE if angular else value


def to_usd_gain(value: float, angular: bool) -> float:
    """from_usd_gain's inverse: a gain per radian, as physics reads it, as USD holds it."""
    return value / _PER_RADIAN_FROM_PER_DEGREE if angular else value


def tracking_errors(positions: list[float], targets: list[float], stiffnesses: list[float]) -> list[float | None]:
    """Each degree of freedom's target minus its position, where a position drive acts on it (stiffness above 0);
    None elsewhere, as a velocity-driven wheel or an undriven joint, which no position target pulls (#199)."""
    return [
        target - position if stiffness > 0 else None
        for position, target, stiffness in zip(positions, targets, stiffnesses, strict=True)
    ]


def observed_kinds(prim: Usd.Prim) -> frozenset[str]:
    """What a stepped read of prim gives (#198): BODY for a rigid body, ARTICULATION when an articulation root is at or
    under it, both for a prim that is both, as a G1's pelvis is, and neither for anything else."""
    kinds: set[str] = set()
    if has_api(prim, UsdPhysics.RigidBodyAPI):
        kinds.add(BODY)
    if articulation_root(prim) is not None:
        kinds.add(ARTICULATION)
    return frozenset(kinds)


def articulation_root(prim: Usd.Prim) -> str | None:
    """The path of the robot's articulation root: prim itself, or its first descendant with ArticulationRootAPI, inside
    instanced assets too, as get_robot_info finds it. Isaac Sim 5.1 and 6.2 look for it each their own way, so the
    bridge finds it once for both. None when prim holds no articulation."""
    for desc in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if has_api(desc, UsdPhysics.ArticulationRootAPI):
            return str(desc.GetPath())
    return None
