"""
Robot handlers.

Handles robot creation, info, joint states, and joint target setting.
"""

import os

from pxr import Sdf, Tf, Usd, UsdPhysics

from ovmcp.core.robot import articulation_root, is_usd_file, robot_prim_path
from ovmcp.core.usd_files import LIBRARY_PREFIX, usd_file_url
from ovmcp.core.xform import check_transform, write_transform

from ._utils import _first_missing, _get_stage, _next_update

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

    try:
        write_transform(prim, parts)
    except ValueError as e:
        # Such as an animated root op in the file: what this call made goes, so a retry isn't refused as taken.
        stage.RemovePrim(made)
        return {"status": "error", "error": f"{e}. The robot was not added"}

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
    isaacsim.core.experimental.prims.Articulation, which 5.1 and 6.x ship (tested live on 6.2): radians or metres,
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

    try:
        from isaacsim.core.experimental.prims import Articulation
    except ImportError as e:
        return {
            "status": "error",
            "error": f"get_joint_states needs Isaac Sim's isaacsim.core.experimental.prims extension: {e}",
        }

    # The call under way, so an error names the one Isaac Sim's experimental API changed.
    call = "Articulation()"
    try:
        articulation = Articulation(root)
        call = "is_physics_tensor_entity_valid()"
        if not articulation.is_physics_tensor_entity_valid():
            # Never load physics from here: that blocks Kit's main thread as a play does.
            return {
                "status": "error",
                "error": f"No physics view of {root}: play or step the simulation first; joint states are read "
                "while it plays or is paused. If it already plays, get_logs(min_level='warn') says why Isaac Sim "
                "made none.",
            }
        call = "dof_names"
        names = list(articulation.dof_names)
        # (N, D) arrays, a row per articulation the path matched: one here.
        call = "get_dof_positions()"
        positions = articulation.get_dof_positions().numpy()[0].tolist()
        call = "get_dof_velocities()"
        velocities = articulation.get_dof_velocities().numpy()[0].tolist()
    except Exception as e:
        return {
            "status": "error",
            "error": f"Reading {root}'s joints failed at isaacsim.core.experimental.prims.Articulation's {call}: "
            f"{type(e).__name__}: {e}",
        }

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "dof_count": len(positions),
            "names": names,
            "positions": positions,
            "velocities": velocities,
        },
    }


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
    # Check if a drive is already applied (same check as handle_get_robot_info)
    for dt in ("angular", "linear"):
        drive = UsdPhysics.DriveAPI.Get(joint_prim, dt)
        if not drive:
            continue
        stiff = drive.GetStiffnessAttr().Get()
        damp = drive.GetDampingAttr().Get()
        if stiff is not None or damp is not None:
            # Drive exists — set or create target position attribute
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
