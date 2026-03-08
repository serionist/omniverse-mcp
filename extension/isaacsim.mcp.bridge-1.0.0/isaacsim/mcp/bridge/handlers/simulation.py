"""
Simulation and physics handlers.

Handles sim control, sim state, physics properties, apply force, and raycast.
"""

import carb
import omni.kit.app
from pxr import Gf, Sdf, UsdGeom, UsdPhysics, UsdShade

from ._utils import _get_stage, _next_update


# Import _recording_state for sim_state handler to report recording status
def _get_recording_active():
    """Get recording state without circular import."""
    from .recording import _recording_state
    return _recording_state["active"]


# ---------------------------------------------------------------------------
# /sim/control
# ---------------------------------------------------------------------------

async def handle_sim_control(body: dict) -> dict:
    action = body.get("action", "").lower()
    valid_actions = ["play", "pause", "stop", "step"]
    if action not in valid_actions:
        return {"status": "error", "error": f"Invalid action: {action}. Use one of {valid_actions}"}

    await _next_update()

    timeline = omni.timeline.get_timeline_interface()
    if action == "play":
        timeline.play()
    elif action == "pause":
        timeline.pause()
    elif action == "stop":
        timeline.stop()
    elif action == "step":
        timeline.play()
        await _next_update()
        await _next_update()
        timeline.pause()

    # Let the timeline state settle before reading it
    await _next_update()

    is_playing = timeline.is_playing()
    is_stopped = timeline.is_stopped()
    state = "playing" if is_playing else ("stopped" if is_stopped else "paused")

    return {"status": "success", "result": {"action": action, "current_state": state}}


# ---------------------------------------------------------------------------
# /sim/state
# ---------------------------------------------------------------------------

async def handle_sim_state(_body: dict) -> dict:
    timeline = omni.timeline.get_timeline_interface()
    is_playing = timeline.is_playing()
    is_stopped = timeline.is_stopped()
    state = "playing" if is_playing else ("stopped" if is_stopped else "paused")

    stage = _get_stage()
    prim_count = sum(1 for _ in stage.Traverse())  # O(n) — acceptable for status endpoint

    tps = timeline.get_time_codes_per_seconds() or 60.0
    # get_current_time() already returns seconds in Isaac Sim 5.1
    sim_time = timeline.get_current_time()

    return {
        "status": "success",
        "result": {
            "state": state,
            "sim_time": sim_time,
            "fps": tps,
            "prim_count": prim_count,
            "up_axis": UsdGeom.GetStageUpAxis(stage),
            "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
            "recording_active": _get_recording_active(),
        },
    }


# ---------------------------------------------------------------------------
# /physics/properties
# ---------------------------------------------------------------------------

async def handle_set_physics_properties(body: dict) -> dict:
    """Set mass, friction, restitution on a prim."""
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()
    applied = []

    mass = body.get("mass")
    density = body.get("density")
    if mass is not None or density is not None:
        if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
            UsdPhysics.RigidBodyAPI.Apply(prim)
            applied.append("RigidBodyAPI")
        if not prim.HasAPI(UsdPhysics.MassAPI):
            UsdPhysics.MassAPI.Apply(prim)
        mass_api = UsdPhysics.MassAPI(prim)
        if mass is not None:
            mass_api.GetMassAttr().Set(float(mass))
        if density is not None:
            mass_api.GetDensityAttr().Set(float(density))
        applied.append("MassAPI")

    friction = body.get("friction")
    restitution = body.get("restitution")
    if friction is not None or restitution is not None:
        if not prim.HasAPI(UsdPhysics.CollisionAPI):
            UsdPhysics.CollisionAPI.Apply(prim)
            applied.append("CollisionAPI")

        prim_name = prim_path.rstrip("/").split("/")[-1]
        mat_path = f"/World/PhysicsMaterials/{prim_name}_PhysMat"
        mat_prim = stage.GetPrimAtPath(mat_path)
        if not mat_prim.IsValid():
            UsdShade.Material.Define(stage, mat_path)
            mat_prim = stage.GetPrimAtPath(mat_path)
            UsdPhysics.MaterialAPI.Apply(mat_prim)
        phys_mat = UsdPhysics.MaterialAPI(mat_prim)

        if friction is not None:
            phys_mat.GetStaticFrictionAttr().Set(float(friction))
            phys_mat.GetDynamicFrictionAttr().Set(float(friction))
        if restitution is not None:
            phys_mat.GetRestitutionAttr().Set(float(restitution))

        binding = UsdShade.MaterialBindingAPI.Apply(prim)
        binding.Bind(
            UsdShade.Material(mat_prim),
            UsdShade.Tokens.weakerThanDescendants,
            "physics",
        )
        applied.append("PhysicsMaterial")

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path, "applied": applied,
            "mass": mass, "density": density,
            "friction": friction, "restitution": restitution,
        },
    }


# ---------------------------------------------------------------------------
# /physics/apply_force
# ---------------------------------------------------------------------------

async def handle_apply_force(body: dict) -> dict:
    """Apply a force or impulse to a rigid body. Requires sim playing."""
    prim_path = body.get("prim_path", "")
    force = body.get("force")
    position = body.get("position")
    is_impulse = body.get("impulse", False)

    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}
    if not force or len(force) != 3:
        return {"status": "error", "error": "force [fx, fy, fz] is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}
    if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
        return {"status": "error", "error": f"Prim has no RigidBodyAPI: {prim_path}"}

    await _next_update()

    method = "physx"
    try:
        from omni.physx import get_physx_interface
        physx = get_physx_interface()
        pos = carb.Float3(*(position if position and len(position) == 3 else [0, 0, 0]))
        f = carb.Float3(*force)
        # Try different PhysX force API signatures
        try:
            physx.apply_force_at_pos(prim_path, f, pos)
        except (AttributeError, TypeError):
            try:
                # Isaac Sim 5.x may use different API
                from omni.physx.scripts import utils as physx_utils
                physx_utils.apply_force_at_pos(prim_path, f, pos)
            except Exception:
                raise
    except Exception as e:
        # Fallback: set velocity directly
        method = "velocity"
        try:
            vel_attr = prim.GetAttribute("physics:velocity")
            if not vel_attr or not vel_attr.IsValid():
                vel_attr = prim.CreateAttribute("physics:velocity", Sdf.ValueTypeNames.Float3, False)

            old = vel_attr.Get()
            if old is None:
                old = Gf.Vec3f(0, 0, 0)
            scale = 0.01 if not is_impulse else 1.0  # force-like: scale down
            vel_attr.Set(Gf.Vec3f(
                float(old[0]) + force[0] * scale,
                float(old[1]) + force[1] * scale,
                float(old[2]) + force[2] * scale,
            ))
        except Exception as e2:
            return {"status": "error", "error": f"PhysX force: {e}; velocity fallback: {e2}"}

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "force": force,
            "position": position,
            "impulse": is_impulse,
            "method": method,
        },
    }


# ---------------------------------------------------------------------------
# /physics/raycast
# ---------------------------------------------------------------------------

async def handle_raycast(body: dict) -> dict:
    """Cast a ray and return hit info. Requires PhysicsScene in stage."""
    origin = body.get("origin")
    direction = body.get("direction")
    max_distance = body.get("max_distance", 1000.0)

    if not origin or len(origin) != 3:
        return {"status": "error", "error": "origin [x, y, z] is required"}
    if not direction or len(direction) != 3:
        return {"status": "error", "error": "direction [dx, dy, dz] is required"}

    await _next_update()

    hit_result = {"hit": False}

    try:
        from omni.physx import get_physx_scene_query_interface
        sqi = get_physx_scene_query_interface()

        result = sqi.raycast_closest(
            carb.Float3(*origin), carb.Float3(*direction), float(max_distance)
        )
        if result and result.get("hit", False):
            hit_result["hit"] = True
            pos = result.get("position", (0, 0, 0))
            hit_result["position"] = [float(pos[0]), float(pos[1]), float(pos[2])]
            nrm = result.get("normal", (0, 0, 0))
            hit_result["normal"] = [float(nrm[0]), float(nrm[1]), float(nrm[2])]
            hit_result["distance"] = float(result.get("distance", 0))
            hit_result["prim_path"] = str(result.get("rigidBody", ""))
    except Exception as e:
        return {"status": "error", "error": f"Raycast failed: {e}. Ensure PhysicsScene exists and sim has been stepped."}

    return {"status": "success", "result": hit_result}
