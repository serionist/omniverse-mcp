"""
Simulation and physics handlers.

Handles sim control, sim state, physics properties, apply force, and raycast.
"""

import traceback

import carb
import omni.kit.app
import omni.usd
from pxr import UsdGeom, UsdPhysics, UsdShade

from ovmcp.core.force import (
    AT_CENTRE_OF_MASS,
    AT_GIVEN,
    Joints,
    centre_of_mass,
    fixed_refusal,
    force_args,
    one_step_force,
    refusal,
    step_seconds,
    tensor_centre_of_mass,
    world_point,
)
from ovmcp.core.material import DYNAMIC, RESTITUTION, STATIC, physics_source, physics_values, start_from
from ovmcp.core.protocol import kit_app

from ._utils import _get_stage, _next_update
from .recording import recording_active, recording_note

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
            "recording_active": recording_active(),
            **({"recording_note": note} if (note := recording_note()) else {}),
            # The Kit app, for a bug report the agent drafts (#105).
            **kit_app(),
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

        # What PhysX gives the body now, read before anything is written: the material bound to it, the scene's
        # default or PhysX's own. A value left out was USD's 0 on a new material, and a material bound before lost all
        # it held (#105).
        source = physics_source(prim)
        now = physics_values(source)

        prim_name = prim_path.rstrip("/").split("/")[-1]
        mat_path = f"/World/PhysicsMaterials/{prim_name}_PhysMat"
        mat_prim = stage.GetPrimAtPath(mat_path)
        if not mat_prim.IsValid():
            UsdShade.Material.Define(stage, mat_path)
            mat_prim = stage.GetPrimAtPath(mat_path)
            UsdPhysics.MaterialAPI.Apply(mat_prim)
        start_from(mat_prim, source)
        phys_mat = UsdPhysics.MaterialAPI(mat_prim)

        phys_mat.CreateStaticFrictionAttr().Set(float(friction) if friction is not None else now[STATIC])
        phys_mat.CreateDynamicFrictionAttr().Set(float(friction) if friction is not None else now[DYNAMIC])
        phys_mat.CreateRestitutionAttr().Set(float(restitution) if restitution is not None else now[RESTITUTION])

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
            "prim_path": prim_path,
            "applied": applied,
            "mass": mass,
            "density": density,
            "friction": friction,
            "restitution": restitution,
        },
    }


# ---------------------------------------------------------------------------
# /physics/apply_force
# ---------------------------------------------------------------------------


async def handle_apply_force(body: dict) -> dict:
    """Apply a force or impulse to a rigid body or an articulation's link through PhysX, at a world point or at its
    centre of mass.

    Two paths. With /physics/suppressReadback on, as PhysX's Direct GPU API has it (Isaac Sim's
    SimulationManager.set_device("cuda:N") turns both on), IPhysxSimulation.apply_force_at_pos returns and moves nothing
    on a GPU scene, so the push goes through the tensor API, which pushes on a CPU scene too (#68). With the setting
    off it is apply_force_at_pos (#25, #58).

    Refused where PhysX would move nothing: the timeline stopped, a disabled or kinematic body, a prim PhysX holds no
    body for, a body a fixed joint holds to the world. A PhysX failure is an error; nothing else moves the body in its
    place.
    """
    try:
        args = force_args(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(args.prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {args.prim_path}"}
    if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
        return {"status": "error", "error": f"Prim has no RigidBodyAPI: {args.prim_path}"}

    await _next_update()

    # From here to the push nothing awaits, so the pose, the centre of mass and the push are all of one update.
    stopped = omni.timeline.get_timeline_interface().is_stopped()
    # The setting alone picks the path. apply_force_at_pos moves nothing with it on a GPU scene, and the tensor API
    # pushes with it on a CPU scene as well, so the tensor path is right either way. What the stage says of GPU
    # dynamics would be a worse guide: a scene without PhysxSceneAPI, or no scene, doesn't say what PhysX runs.
    if carb.settings.get_settings().get_as_bool("/physics/suppressReadback"):
        return _push_with_tensors(args, stage, prim, stopped)
    return _push_with_physx(args, stage, prim, stopped)


def _body_flags(prim) -> tuple[bool, bool]:
    """Whether the rigid body is enabled, and whether it is kinematic."""
    body_api = UsdPhysics.RigidBodyAPI(prim)
    # Both attributes have fallbacks (enabled, not kinematic); only an authored false disables the body.
    return body_api.GetRigidBodyEnabledAttr().Get() is not False, bool(body_api.GetKinematicEnabledAttr().Get())


def _refused(args, stage, **facts) -> str | None:
    """Why the push is refused: the cheap facts first, then the stage's joints, which take a traversal of the whole
    stage and are read only once the rest lets the push by."""
    refused = refusal(args.prim_path, **facts)
    if refused is not None:
        return refused
    joints = Joints(stage)
    fixed_base = joints.held_to_world(args.prim_path)
    if fixed_base is None:
        return None
    return fixed_refusal(args.prim_path, fixed_base, joints.articulation_holding(args.prim_path))


def _answer(args, point, at: str, method: str) -> dict:
    return {
        "status": "success",
        "result": {
            "prim_path": args.prim_path,
            "force": list(args.force),
            "position": list(point),
            "at": at,
            "impulse": args.impulse,
            "method": method,
        },
    }


def _push_with_physx(args, stage, prim, stopped: bool) -> dict:
    """The push through IPhysxSimulation.apply_force_at_pos, with /physics/suppressReadback off: exact on the CPU
    pipeline and with GPU dynamics alike."""
    try:
        from omni.physx import get_physx_interface, get_physx_simulation_interface
        from pxr import PhysicsSchemaTools
    except ImportError as e:
        return {"status": "error", "error": f"PhysX (omni.physx) is not loaded in this Kit app: {e}"}

    enabled, kinematic = _body_flags(prim)
    try:
        pose = {} if stopped else get_physx_interface().get_rigidbody_transformation(args.prim_path)
        refused = _refused(
            args,
            stage,
            stopped=stopped,
            gpu_unavailable=None,
            enabled=enabled,
            kinematic=kinematic,
            held=bool(pose.get("ret_val")),
        )
        if refused:
            return {"status": "error", "error": refused}

        if args.position is not None:
            point, at = args.position, AT_GIVEN
        else:
            # PhysX's unit-tests interface, which NVIDIA may change or drop: only a push without a point needs it.
            # Synchronous, with no Python callback for Kit to call from another thread (#5), as query_prim would need.
            try:
                from omni.physx import get_physxunittests_interface

                mass_information = get_physxunittests_interface().get_mass_information
            except (ImportError, AttributeError) as e:
                return {
                    "status": "error",
                    "error": (
                        "No centre of mass: this Kit's omni.physx lacks get_physxunittests_interface()."
                        f"get_mass_information ({e}); give a position to push at"
                    ),
                }
            info = mass_information(args.prim_path)
            point = world_point(pose["position"], pose["rotation"], centre_of_mass(info, args.prim_path))
            at = AT_CENTRE_OF_MASS

        get_physx_simulation_interface().apply_force_at_pos(
            omni.usd.get_context().get_stage_id(),
            PhysicsSchemaTools.sdfPathToInt(args.prim_path),
            carb.Float3(*args.force),
            carb.Float3(*point),
            args.mode,
        )
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    except (AttributeError, RuntimeError, TypeError, KeyError) as e:
        return {"status": "error", "error": f"PhysX could not push {args.prim_path}: {e}"}

    return _answer(args, point, at, "physx")


def _push_with_tensors(args, stage, prim, stopped: bool) -> dict:
    """The push through PhysX's tensor API, a RigidBodyView of our own, while /physics/suppressReadback is on.

    The tensor API has no impulse mode, so an impulse is the force that delivers it over one step.
    """
    tensors = wp = None
    gpu_unavailable = None
    if not stopped:
        try:
            import warp as wp
            from omni.physics import tensors
        except ImportError as e:
            # With readback on, apply_force_at_pos pushes, GPU dynamics included (measured on Isaac Sim 6.2), and
            # PhysX reads the setting when the simulation starts, hence the stop.
            gpu_unavailable = (
                "/physics/suppressReadback is true, as PhysX's Direct GPU API has it, where a push goes through "
                f"omni.physics.tensors and warp, and this Kit app lacks one ({e}) (#68). Turn the missing one on with "
                "manage_extensions (omni.physics.tensors, or omni.warp.core for warp), or push with readback on, "
                "where PhysX's own push moves the body: stop the simulation, run "
                "carb.settings.get_settings().set_bool('/physics/suppressReadback', False) with execute_script, and "
                "play again"
            )
    enabled, kinematic = _body_flags(prim)
    # Whether PhysX holds the body is the view's count, below; here the body is taken as held.
    refused = _refused(
        args, stage, stopped=stopped, gpu_unavailable=gpu_unavailable, enabled=enabled, kinematic=kinematic, held=True
    )
    if refused:
        return {"status": "error", "error": refused}

    # The step before any tensor call, so a scene with an unusable one is said so and not taken for PhysX's failure.
    try:
        force = one_step_force(args.force, args.impulse, step_seconds(stage).seconds)
    except ValueError as e:
        return {"status": "error", "error": f"the physics scene's step can't be used: {e}"}

    import numpy as np  # Kit ships it; only this path needs it

    view = None
    try:
        view = tensors.create_simulation_view("warp", omni.usd.get_context().get_stage_id())
        bodies = view.create_rigid_body_view(args.prim_path)
        # The prim's own path can match more than the prim: the view takes a plain last name at any depth under its
        # parent (/physics/tensors/recursiveLeafPatternMatch, on by default in omni.physics.tensors 110.4), so
        # /World/Cube brings /World/Table/Cube with it. The body is its own row of the view, and only that row moves.
        paths = list(bodies.prim_paths)
        if args.prim_path not in paths:
            not_held = refusal(
                args.prim_path, stopped=False, gpu_unavailable=None, enabled=True, kinematic=False, held=False
            )
            return {"status": "error", "error": not_held}
        count, row = bodies.count, paths.index(args.prim_path)

        if args.position is not None:
            point, at = args.position, AT_GIVEN
        else:
            # Both rows to the host: get_coms lives on the parameters' device, the CPU, and get_transforms on the
            # simulation's.
            transform = bodies.get_transforms().numpy().reshape(count, 7)[row]
            com = bodies.get_coms().numpy().reshape(count, 7)[row]
            point, at = tensor_centre_of_mass(transform.tolist(), com.tolist()), AT_CENTRE_OF_MASS

        # A row for each body of the view, as the call takes them, zero but the body's; the indices name its row alone.
        force_rows = np.zeros((count, 3), np.float32)
        force_rows[row] = force
        point_rows = np.zeros((count, 3), np.float32)
        point_rows[row] = point
        # The warp frontend takes float32 data and 32-bit indices only, and the backend reads each array on the device
        # it was made on, so all three are made on the view's own device: the GPU under the Direct GPU API.
        device = view.device
        forces = wp.array(force_rows, dtype=wp.float32, device=device)
        points = wp.array(point_rows, dtype=wp.float32, device=device)
        indices = wp.array(np.array([row], np.uint32), dtype=wp.uint32, device=device)
        bodies.apply_forces_and_torques_at_position(forces, None, points, indices, True)
    except Exception as e:
        # The tensor API raises a bare Exception for each of its failures, so nothing narrower catches them; the same
        # catch would hide a slip of ours in the arrays or the point, hence the traceback in Kit's log.
        carb.log_error(f"apply_force through the tensor API failed for {args.prim_path}:\n{traceback.format_exc()}")
        return {"status": "error", "error": f"PhysX's tensor API could not push {args.prim_path}: {e}"}
    finally:
        if view is not None:
            # The view is ours alone: invalidating it leaves Isaac Sim's own view valid, as measured on Isaac Sim 6.2. A
            # failing invalidate must not replace the answer.
            try:
                view.invalidate()
            except Exception as e:
                carb.log_warn(f"apply_force could not invalidate its tensor view: {e}")

    return _answer(args, point, at, "tensor")


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

        result = sqi.raycast_closest(carb.Float3(*origin), carb.Float3(*direction), float(max_distance))
        if result and result.get("hit", False):
            hit_result["hit"] = True
            pos = result.get("position", (0, 0, 0))
            hit_result["position"] = [float(pos[0]), float(pos[1]), float(pos[2])]
            nrm = result.get("normal", (0, 0, 0))
            hit_result["normal"] = [float(nrm[0]), float(nrm[1]), float(nrm[2])]
            hit_result["distance"] = float(result.get("distance", 0))
            hit_result["prim_path"] = str(result.get("rigidBody", ""))
    except Exception as e:
        return {
            "status": "error",
            "error": f"Raycast failed: {e}. Ensure PhysicsScene exists and sim has been stepped.",
        }

    return {"status": "success", "result": hit_result}
