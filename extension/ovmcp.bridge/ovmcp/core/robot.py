"""Whether create_robot was given a USD file or a robot's name, the prim it makes for it, and the turn that stands a
file of another up axis on the stage; where /robot/joint_states, which get_robot_info reads, finds a robot's
articulation. Where the file loads from is ovmcp.core.usd_files's rule, which open_scene shares.

Kit-free, so unit-tested without Kit.
"""

from pathlib import PureWindowsPath
from typing import cast

from pxr import Sdf, Tf, Usd, UsdGeom, UsdPhysics

from .usd import has_api, xform_ops

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


# The op Kit's metrics assembler writes to stand a referenced file of another up axis on the stage: a turn about X,
# outside the file's content and inside the prim's own ops (omni.usd.metrics.assembler's referenceTests).
UP_AXIS_OP = "xformOp:rotateX:unitsResolve"
_TURNS = {("Z", "Y"): -90.0, ("Y", "Z"): 90.0}


def file_up_axis(layer: Sdf.Layer) -> str | None:
    """The up axis the file's root layer authors, or None: USD's fallback, Y, is a guess about a file that doesn't say,
    and turning on it would lay down a robot that stood."""
    root = layer.pseudoRoot
    return str(root.GetInfo("upAxis")) if root.HasInfo("upAxis") else None


def up_axis_turn(file_axis: str | None, stage_axis: str) -> float | None:
    """The degrees about X that stand a file of file_axis up on a stage of stage_axis: -90 for a Z-up file on a Y-up
    stage, +90 the other way, None when they agree or the file doesn't say."""
    return _TURNS.get((file_axis, stage_axis)) if file_axis else None


def stand_upright(prim: Usd.Prim, degrees: float) -> float:
    """Turns prim by degrees about X in UP_AXIS_OP, in the edit target's layer, and gives the op's value after.

    A prim whose ops hold the op already, such as a file Kit resolved and saved, gets the sum: that op turned the
    file's content to the file's own up axis, and the turn to the stage's is still owed. A new op goes where Kit puts
    it, before the first inverse op, else last, so a pivot pair stays around it.
    """
    xformable = UsdGeom.Xformable(prim)
    order = xform_ops(xformable)
    held = next((op for op in order if op.GetOpName() == UP_AXIS_OP), None)
    if held is not None:
        attr = held.GetAttr()
        if attr.GetNumTimeSamples():
            raise ValueError(f"{prim.GetPath()}'s {UP_AXIS_OP} is animated, so it can't be turned upright")
        value = float(cast("float", attr.Get() or 0.0)) + degrees
        attr.Set(value)
        return value
    added = xformable.AddRotateXOp(opSuffix="unitsResolve")
    added.Set(degrees)
    inverse = [i for i, op in enumerate(order) if op.IsInverseOp()]
    if inverse:
        order.insert(inverse[0], added)
        xformable.SetXformOpOrder(order, xformable.GetResetXformStack())
    return degrees
