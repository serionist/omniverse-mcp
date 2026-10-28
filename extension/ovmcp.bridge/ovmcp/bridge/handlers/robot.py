"""
Robot handlers.

Handles robot creation, info, joint states, and joint target setting.
"""

from typing import Any

from pxr import Usd, UsdGeom, UsdPhysics

from ._utils import _apply_xform, _get_stage, _next_update


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


# Articulation cache for joint state queries
_articulation_cache: dict[str, Any] = {}


def _clear_articulation_cache():
    """Clear the articulation cache. Called on scene changes."""
    _articulation_cache.clear()


# ---------------------------------------------------------------------------
# /robot/create
# ---------------------------------------------------------------------------

async def handle_create_robot(body: dict) -> dict:
    robot_type = body.get("robot_type", "").lower()
    prim_path = body.get("prim_path", "")
    position = body.get("position", [0, 0, 0])

    if not robot_type:
        return {"status": "error", "error": f"No robot_type. Available: {list(ROBOT_ASSETS.keys())}"}

    if robot_type in ROBOT_ASSETS:
        usd_path = ROBOT_ASSETS[robot_type]
    elif robot_type.endswith((".usd", ".usda", ".usdc")):
        usd_path = robot_type
    else:
        return {"status": "error", "error": f"Unknown robot_type: {robot_type}. Available: {list(ROBOT_ASSETS.keys())}"}

    if not prim_path:
        prim_path = f"/World/{robot_type.capitalize()}"

    await _next_update()

    try:
        from isaacsim.storage.native import get_assets_root_path
        assets_root = get_assets_root_path()
        full_usd_path = (assets_root + usd_path) if assets_root else usd_path
    except ImportError:
        full_usd_path = usd_path

    stage = _get_stage()
    prim = stage.DefinePrim(prim_path)
    prim.GetReferences().AddReference(full_usd_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Failed to create robot at {prim_path}"}

    if prim_path in _articulation_cache:
        del _articulation_cache[prim_path]

    _apply_xform(prim, position, body.get("rotation"))

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
            if lo is not None: jd["lower_limit"] = float(lo)
            if hi is not None: jd["upper_limit"] = float(hi)
            axis = rev.GetAxisAttr().Get()
            if axis: jd["axis"] = str(axis)
        elif desc.IsA(UsdPhysics.PrismaticJoint):
            pri = UsdPhysics.PrismaticJoint(desc)
            lo, hi = pri.GetLowerLimitAttr().Get(), pri.GetUpperLimitAttr().Get()
            if lo is not None: jd["lower_limit"] = float(lo)
            if hi is not None: jd["upper_limit"] = float(hi)
            axis = pri.GetAxisAttr().Get()
            if axis: jd["axis"] = str(axis)

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
    """Get current joint positions/velocities. Requires sim to have been played."""
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()

    # Try isaacsim.core Articulation API
    try:
        art = _articulation_cache.get(prim_path)
        if art is None:
            try:
                from isaacsim.core.api.articulations import Articulation
            except ImportError:
                from omni.isaac.core.articulations import Articulation
            art = Articulation(prim_path=prim_path)
            art.initialize()
            _articulation_cache[prim_path] = art

        positions = art.get_joint_positions()
        velocities = art.get_joint_velocities()

        pos_list = positions.tolist() if hasattr(positions, 'tolist') else list(positions)
        vel_list = velocities.tolist() if hasattr(velocities, 'tolist') else list(velocities)

        names = []
        try:
            names = list(art.dof_names) if hasattr(art, 'dof_names') and art.dof_names else []
        except Exception:
            pass

        return {
            "status": "success",
            "result": {
                "prim_path": prim_path,
                "dof_count": len(pos_list),
                "names": names,
                "positions": pos_list,
                "velocities": vel_list,
            },
        }
    except Exception as e:
        _articulation_cache.pop(prim_path, None)
        return {
            "status": "error",
            "error": f"Failed to read joint states: {e}. Sim must be playing or have been played at least once.",
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
    elif joint_prim.IsA(UsdPhysics.PrismaticJoint):
        drive = UsdPhysics.DriveAPI.Apply(joint_prim, "linear")
        drive.CreateTargetPositionAttr(float(value))
        if drive.GetStiffnessAttr().Get() is None:
            drive.CreateStiffnessAttr(1000.0)
            drive.CreateDampingAttr(100.0)
        return True
    return False
