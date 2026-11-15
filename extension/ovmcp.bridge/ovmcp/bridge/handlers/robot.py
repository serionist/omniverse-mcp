"""
Robot handlers.

Handles robot creation, info, joint states, and joint target setting.
"""

import math
import os

from pxr import Sdf, Tf, Usd, UsdPhysics

from ovmcp.core.metrics import StepError, bring_to_stage
from ovmcp.core.robot import (
    articulation_root,
    is_usd_file,
    robot_prim_path,
    to_usd_gain,
    tracking_errors,
)
from ovmcp.core.usd_files import LIBRARY_PREFIX, usd_file_url
from ovmcp.core.xform import check_transform, write_transform

from ._utils import _first_missing, _get_stage, _next_update, _physics_exponents

# ---------------------------------------------------------------------------
# Robot asset registry
# ---------------------------------------------------------------------------

ROBOT_ASSETS = {
    "franka": "/Isaac/Robots/FrankaRobotics/FrankaEmika/panda_instanceable.usd",
    "ur10": "/Isaac/Robots/UniversalRobots/ur10/ur10.usd",
    "carter": "/Isaac/Robots/NVIDIA/Carter/carter_v1.usd",
    "jetbot": "/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd",
    "g1": "/Isaac/Robots/Unitree/G1/g1.usd",
    "go1": "/Isaac/Robots/Unitree/Go1/go1.usd",
    "go2": "/Isaac/Robots/Unitree/Go2/go2.usd",
    "h1": "/Isaac/Robots/Unitree/H1/h1.usd",
    "spot": "/Isaac/Robots/BostonDynamics/spot/spot.usd",
    "anymal": "/Isaac/Robots/ANYbotics/anymal_c/anymal_c.usd",
}


# ---------------------------------------------------------------------------
# /robot/create
# ---------------------------------------------------------------------------


def _assets_root() -> str | None:
    """Isaac Sim's asset library root, a URL; None outside Isaac Sim."""
    try:
        from isaacsim.storage.native import get_assets_root_path
    except ImportError:
        return None
    return get_assets_root_path()


async def handle_create_robot(body: dict) -> dict:
    given = body.get("robot_type", "")
    prim_path = body.get("prim_path", "")
    position = body.get("position", [0, 0, 0])

    if not given:
        return {"status": "error", "error": f"No robot_type. Available: {list(ROBOT_ASSETS.keys())}"}
    # Before the prim is made: a refusal after it would leave a robot the retry then finds in the way.
    try:
        parts = check_transform(position, body.get("rotation"))
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    robot_type = given.lower()
    if robot_type in ROBOT_ASSETS:
        usd_path = ROBOT_ASSETS[robot_type]
    elif is_usd_file(given):
        # A file keeps its case: Linux's file systems and omniverse:// URLs tell MyBot.usd from mybot.usd.
        robot_type = usd_path = given
    else:
        return {"status": "error", "error": f"Unknown robot_type: {given}. Available: {list(ROBOT_ASSETS.keys())}"}

    if not prim_path:
        prim_path = robot_prim_path(robot_type)

    await _next_update()

    full_usd_path = usd_file_url(usd_path, _assets_root, os.path.isfile, os.path.abspath)
    if full_usd_path is None:
        return {
            "status": "error",
            "error": f"No USD file at {usd_path} on the Kit app's machine. A URL loads as given, and a path in "
            f"Isaac Sim's asset library starts {LIBRARY_PREFIX}",
        }

    stage = _get_stage()
    if stage.GetPrimAtPath(prim_path).IsValid():
        # A second reference would compose two robots into one prim, or a robot into the scene's own prim.
        return {
            "status": "error",
            "error": f"A prim already exists at {prim_path}: pass another prim_path, or delete it first",
        }
    # Opened first: a URL or a library path that doesn't answer would otherwise leave an empty prim, reported as
    # created. The reference then reuses the layer this opened.
    try:
        layer = Sdf.Layer.FindOrOpen(full_usd_path)
    except Tf.ErrorException as e:
        return {"status": "error", "error": f"Could not open {full_usd_path}: {e}"}
    if layer is None:
        return {"status": "error", "error": f"Could not open {full_usd_path}"}

    made = _first_missing(stage, prim_path)
    prim = stage.DefinePrim(prim_path)
    prim.GetReferences().AddReference(full_usd_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Failed to create robot at {prim_path}"}

    step = "Bringing the robot to the stage"
    try:
        # A file of another up axis lies on its side here, and one of other units comes in at its own scale: Isaac
        # Sim's robots are Z-up, and Kit stands one dropped on a Y-up stage and scales one of other units with ops
        # this call writes as Kit does, measured against the frame it lands in, and converts its drives and inertia
        # as Kit's physics rules do (#105, #112, #119).
        brought = bring_to_stage(prim, layer, _physics_exponents(), "robot")
        step = "Placing the robot"
        write_transform(prim, parts)
    except (ValueError, Tf.ErrorException) as e:
        # Such as an animated root op in the file, or USD refusing an op: what this call made goes, so a retry isn't
        # refused as taken. The converted values go with it: they sit under the prim's path in the same layer.
        stage.RemovePrim(made)
        return {"status": "error", "error": f"{e}. The robot was not added"}
    except Exception as e:
        # Any other, such as the PhysX schema's table changed in a later Kit: the same cleanup, the step named.
        stage.RemovePrim(made)
        failed = str(e) if isinstance(e, StepError) else f"{step} failed: {type(e).__name__}: {e}"
        return {"status": "error", "error": f"{failed}. The robot was not added"}

    joint_info = []
    for desc_prim in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if desc_prim.IsA(UsdPhysics.Joint):
            joint_info.append({"path": str(desc_prim.GetPath()), "type": desc_prim.GetTypeName()})

    return {
        "status": "success",
        "result": {
            "prim_path": str(prim.GetPath()),
            "robot_type": robot_type,
            "usd_path": full_usd_path,
            "up_axis_turn": brought.up_axis_turn,
            "units_scale": brought.units_scale,
            "frame": brought.frame,
            "joints": joint_info[:50],
        },
    }


# ---------------------------------------------------------------------------
# /robot/info
# ---------------------------------------------------------------------------


async def handle_get_robot_info(body: dict) -> dict:
    """Get robot joint info, DOF count, limits — pure USD, no sim needed."""
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    joints = []
    links = []
    is_articulation = prim.HasAPI(UsdPhysics.ArticulationRootAPI)

    for desc in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if desc.HasAPI(UsdPhysics.ArticulationRootAPI):
            is_articulation = True
        if desc.HasAPI(UsdPhysics.RigidBodyAPI):
            links.append(str(desc.GetPath()))
        if not desc.IsA(UsdPhysics.Joint):
            continue

        jd = {"path": str(desc.GetPath()), "name": desc.GetName(), "type": desc.GetTypeName()}

        if desc.IsA(UsdPhysics.RevoluteJoint):
            rev = UsdPhysics.RevoluteJoint(desc)
            lo, hi = rev.GetLowerLimitAttr().Get(), rev.GetUpperLimitAttr().Get()
            if lo is not None:
                jd["lower_limit"] = float(lo)
            if hi is not None:
                jd["upper_limit"] = float(hi)
            axis = rev.GetAxisAttr().Get()
            if axis:
                jd["axis"] = str(axis)
        elif desc.IsA(UsdPhysics.PrismaticJoint):
            pri = UsdPhysics.PrismaticJoint(desc)
            lo, hi = pri.GetLowerLimitAttr().Get(), pri.GetUpperLimitAttr().Get()
            if lo is not None:
                jd["lower_limit"] = float(lo)
            if hi is not None:
                jd["upper_limit"] = float(hi)
            axis = pri.GetAxisAttr().Get()
            if axis:
                jd["axis"] = str(axis)

        for dt in ("angular", "linear"):
            drive = UsdPhysics.DriveAPI.Get(desc, dt)
            if not drive:
                continue
            stiff = drive.GetStiffnessAttr().Get()
            damp = drive.GetDampingAttr().Get()
            if stiff is not None or damp is not None:
                jd[f"drive_{dt}"] = {
                    "stiffness": float(stiff) if stiff is not None else 0.0,
                    "damping": float(damp) if damp is not None else 0.0,
                }

        joints.append(jd)

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "is_articulation": is_articulation,
            "dof_count": sum(1 for j in joints if j["type"] != "PhysicsFixedJoint"),
            "link_count": len(links),
            "joints": joints,
            "links": links[:100],
        },
    }


# ---------------------------------------------------------------------------
# /robot/joint_states
# ---------------------------------------------------------------------------


async def handle_get_joint_states(body: dict) -> dict:
    """Joint positions and velocities while physics plays or is paused, through Isaac Sim's
    isaacsim.core.experimental.prims.Articulation, which 5.1 and 6.x ship (tested live on both): radians or metres,
    and the same per second.

    A new Articulation per call, a few milliseconds while physics runs: one kept would outlive a stop.
    """
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    await _next_update()

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}
    root = articulation_root(prim)
    if root is None:
        return {
            "status": "error",
            "error": f"No articulation at or under {prim_path}: no prim there has UsdPhysics.ArticulationRootAPI",
        }
    states = read_joint_states(root)
    if "error" in states:
        return {"status": "error", "error": states["error"]}
    return {"status": "success", "result": {"prim_path": prim_path, **states}}


def read_joint_states(root: str) -> dict:
    """The joint states of the articulation rooted at `root`, read from physics: `dof_count`, `names`, `positions` and
    `velocities`, and each DOF's drive as PhysX holds it (#199): `lower_limits`, `upper_limits`, `targets`,
    `stiffnesses`, `dampings`, `max_forces`, and `tracking_errors` (None where no position drive acts), in radians or
    stage units, gains per radian or per stage unit; or `error` saying why there are none. /robot/joint_states and
    /sim/step's reads (#198) share it."""
    try:
        from isaacsim.core.experimental.prims import Articulation
    except ImportError as e:
        # get_robot_info gives this as its joint states' line, so it names the joint states, not a tool.
        return {"error": f"Joint states need Isaac Sim's isaacsim.core.experimental.prims extension: {e}"}

    # The call under way, so an error names the one Isaac Sim's experimental API changed.
    call = "Articulation()"
    try:
        articulation = Articulation(root)
        call = "is_physics_tensor_entity_valid()"
        if not articulation.is_physics_tensor_entity_valid():
            # Never load physics from here: that blocks Kit's main thread as a play does.
            return {
                "error": f"No physics view of {root}: play or step the simulation first; joint states are read "
                "while it plays or is paused. If it already plays, get_logs(min_level='warn') says why Isaac Sim "
                "made none."
            }
        call = "dof_names"
        names = list(articulation.dof_names)
        # (N, D) arrays, a row per articulation the path matched: one here.
        call = "get_dof_positions()"
        positions = articulation.get_dof_positions().numpy()[0].tolist()
        call = "get_dof_velocities()"
        velocities = articulation.get_dof_velocities().numpy()[0].tolist()
        call = "get_dof_limits()"
        lower, upper = articulation.get_dof_limits()
        call = "get_dof_position_targets()"
        targets = articulation.get_dof_position_targets().numpy()[0].tolist()
        call = "get_dof_gains()"
        stiffnesses, dampings = articulation.get_dof_gains()
        call = "get_dof_max_efforts()"
        max_forces = articulation.get_dof_max_efforts().numpy()[0].tolist()
        stiffness_row = stiffnesses.numpy()[0].tolist()
        drives = {
            "lower_limits": lower.numpy()[0].tolist(),
            "upper_limits": upper.numpy()[0].tolist(),
            "targets": targets,
            "stiffnesses": stiffness_row,
            "dampings": dampings.numpy()[0].tolist(),
            "max_forces": max_forces,
            "tracking_errors": tracking_errors(positions, targets, stiffness_row),
        }
    except Exception as e:
        return {
            "error": f"Reading {root}'s joints failed at isaacsim.core.experimental.prims.Articulation's {call}: "
            f"{type(e).__name__}: {e}"
        }
    return {"dof_count": len(positions), "names": names, "positions": positions, "velocities": velocities, **drives}


# ---------------------------------------------------------------------------
# /robot/joint_targets
# ---------------------------------------------------------------------------


async def handle_set_joint_targets(body: dict) -> dict:
    """Set joint drive targets via USD. Works without articulation init."""
    prim_path = body.get("prim_path", "")
    targets = body.get("targets")  # dict {joint_name: value} or list [v0, v1, ...]

    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}
    if targets is None:
        return {"status": "error", "error": "targets is required (dict or list)"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()

    # Collect all joints
    joint_prims = []
    for desc in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if desc.IsA(UsdPhysics.Joint):
            joint_prims.append(desc)

    if not joint_prims:
        return {"status": "error", "error": f"No joints found under {prim_path}"}

    applied = 0

    if isinstance(targets, dict):
        # targets = {"joint_name": value, ...}
        joint_map = {j.GetName(): j for j in joint_prims}
        for name, value in targets.items():
            jp = joint_map.get(name)
            if jp is None:
                continue
            if _set_drive_target(jp, float(value)):
                applied += 1
    elif isinstance(targets, list):
        # targets = [v0, v1, ...] in joint order
        for i, value in enumerate(targets):
            if i >= len(joint_prims):
                break
            if value is not None and _set_drive_target(joint_prims[i], float(value)):
                applied += 1

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "targets_set": applied,
            "total_joints": len(joint_prims),
        },
    }


def _set_drive_target(joint_prim, value: float) -> bool:
    """Set the drive target position on a joint prim. Returns True on success."""
    found = _existing_drive(joint_prim)
    if found is not None:
        drive, _kind = found
        target_attr = drive.GetTargetPositionAttr()
        if target_attr and target_attr.IsValid():
            target_attr.Set(float(value))
        else:
            drive.CreateTargetPositionAttr(float(value))
        return True

    # No drive exists — apply one based on joint type
    if joint_prim.IsA(UsdPhysics.RevoluteJoint):
        drive = UsdPhysics.DriveAPI.Apply(joint_prim, "angular")
        drive.CreateTargetPositionAttr(float(value))
        if drive.GetStiffnessAttr().Get() is None:
            drive.CreateStiffnessAttr(1000.0)
            drive.CreateDampingAttr(100.0)
        return True
    if joint_prim.IsA(UsdPhysics.PrismaticJoint):
        drive = UsdPhysics.DriveAPI.Apply(joint_prim, "linear")
        drive.CreateTargetPositionAttr(float(value))
        if drive.GetStiffnessAttr().Get() is None:
            drive.CreateStiffnessAttr(1000.0)
            drive.CreateDampingAttr(100.0)
        return True
    return False


def _existing_drive(joint_prim):
    """The joint's drive, `(DriveAPI, "angular" | "linear")`, when one is applied with a stiffness or a damping, as
    get_robot_info reads one; None for a joint without."""
    for kind in ("angular", "linear"):
        drive = UsdPhysics.DriveAPI.Get(joint_prim, kind)
        if not drive:
            continue
        if drive.GetStiffnessAttr().Get() is not None or drive.GetDampingAttr().Get() is not None:
            return drive, kind
    return None


# ---------------------------------------------------------------------------
# /robot/joint_drives
# ---------------------------------------------------------------------------

DRIVE_KEYS = ("stiffness", "damping", "max_force")
# How far physics' value may sit from the one written and still count as taken: float32 against a per-degree
# conversion.
_TAKEN = 1e-3


async def handle_set_joint_drives(body: dict) -> dict:
    """Write joint drives' stiffness, damping and force limit, given in physics' units (per radian for an angular
    drive), to USD in its own (per degree), and read back from physics what the simulation holds after one update;
    where a playing or paused simulation didn't take the USD write, write through Isaac Sim's articulation view too
    (#199)."""
    prim_path = body.get("prim_path", "")
    drives = body.get("drives")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}
    if not isinstance(drives, dict) or not drives:
        return {"status": "error", "error": "drives is required: {joint_name: {stiffness, damping, max_force}}"}
    for name, values in drives.items():
        if not isinstance(values, dict) or not values or set(values) - set(DRIVE_KEYS):
            return {"status": "error", "error": f"{name}: give any of {', '.join(DRIVE_KEYS)}, got {values!r}"}
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                return {"status": "error", "error": f"{name}.{key} must be a finite number, 0 or more (got {value!r})"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}
    await _next_update()

    joints = {p.GetName(): p for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()) if p.IsA(UsdPhysics.Joint)}
    written: dict[str, dict] = {}
    not_written: dict[str, str] = {}
    for name, values in drives.items():
        joint = joints.get(name)
        if joint is None:
            not_written[name] = f"no joint of that name under {prim_path}"
            continue
        found = _existing_drive(joint)
        if found is None:
            not_written[name] = "no drive: set_joint_targets gives it one"
            continue
        drive, kind = found
        angular = kind == "angular"
        usd: dict[str, float] = {}
        if "stiffness" in values:
            usd["stiffness"] = to_usd_gain(float(values["stiffness"]), angular)
            drive.CreateStiffnessAttr().Set(usd["stiffness"])
        if "damping" in values:
            usd["damping"] = to_usd_gain(float(values["damping"]), angular)
            drive.CreateDampingAttr().Set(usd["damping"])
        if "max_force" in values:
            usd["max_force"] = float(values["max_force"])
            drive.CreateMaxForceAttr().Set(usd["max_force"])
        written[name] = {"kind": kind, "usd": usd}

    result: dict = {"prim_path": prim_path, "written": written, "not_written": not_written}
    root = articulation_root(prim)
    if written and root is not None:
        await _next_update()
        result["in_simulation"], result["through_view"] = await _held_by_physics(root, drives, written)
    elif written:
        result["in_simulation_note"] = f"No articulation at or under {prim_path}: nothing to read back from physics"
    return {"status": "success", "result": result}


def _physics_values(states: dict, name: str) -> dict | None:
    """What physics holds for joint `name`'s drive, from read_joint_states, or None when it has no such DOF."""
    if name not in states.get("names", []):
        return None
    i = states["names"].index(name)
    return {
        "stiffness": states["stiffnesses"][i],
        "damping": states["dampings"][i],
        "max_force": states["max_forces"][i],
    }


def _took(asked: dict, held: dict | None) -> bool:
    return held is not None and all(
        abs(held[key] - value) <= _TAKEN * max(1.0, abs(value)) for key, value in asked.items()
    )


async def _held_by_physics(root: str, drives: dict, written: dict) -> tuple[dict, bool]:
    """Per joint written, what physics holds after the update, or why nothing; and whether the values had to go
    through Isaac Sim's articulation view, which they do only where the USD write wasn't taken."""
    states = read_joint_states(root)
    if "error" in states:
        return {name: {"none": states["error"]} for name in written}, False
    missed = [name for name in written if not _took(drives[name], _physics_values(states, name))]
    through_view = False
    if missed:
        _write_through_view(root, states["names"], {name: drives[name] for name in missed})
        through_view = True
        await _next_update()
        states = read_joint_states(root)
    held = {}
    for name in written:
        values = _physics_values(states, name) if "error" not in states else None
        held[name] = values if values is not None else {"none": f"physics holds no DOF named {name}"}
    return held, through_view


def _write_through_view(root: str, dof_names: list[str], drives: dict) -> None:
    """Set the drives physics didn't take from USD through Isaac Sim's articulation view, its DOFs alone."""
    from isaacsim.core.experimental.prims import Articulation

    articulation = Articulation(root)
    for name, values in drives.items():
        index = [dof_names.index(name)]
        if "stiffness" in values or "damping" in values:
            articulation.set_dof_gains(
                stiffnesses=[[values["stiffness"]]] if "stiffness" in values else None,
                dampings=[[values["damping"]]] if "damping" in values else None,
                dof_indices=index,
            )
        if "max_force" in values:
            articulation.set_dof_max_efforts([[values["max_force"]]], dof_indices=index)
