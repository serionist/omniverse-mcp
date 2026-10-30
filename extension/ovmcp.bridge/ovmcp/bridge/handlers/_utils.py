"""
Shared helper functions used across handler modules.

These are internal utilities — not exposed as HTTP endpoints.
"""

import contextlib
import json
import tempfile
import time
import uuid
from pathlib import Path

import carb
import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

# The module, not its names: its limits are read when a wait runs, so a live test can shorten one.
from ovmcp.core import capture
from ovmcp.core.extensions import extension_step, is_listed

DEFAULT_CAMERA_PATH = "/OmniverseKit_Persp"


def enable_extension(name: str) -> bool:
    """Whether the extension `name` is on, turning it on first when this Kit app has it on disk. An app without it
    gets False, with no registry fetch and nothing in Kit's log (core/extensions.py)."""
    manager = omni.kit.app.get_app().get_extension_manager()
    enabled = manager.is_extension_enabled(name)
    step = extension_step(enabled, not enabled and is_listed(name, manager.get_extensions()))
    if step == "enable":
        # The same call as Isaac Sim's own enable_extension; it returns whether it worked.
        return bool(manager.set_extension_enabled_immediate(name, True))
    return step == "ready"


def _get_active_camera_path() -> str:
    """Get the active viewport camera path, with fallback to default perspective camera."""
    try:
        from omni.kit.viewport.utility import get_active_viewport

        viewport = get_active_viewport()
        return str(viewport.camera_path) if viewport else DEFAULT_CAMERA_PATH
    except ImportError:
        return DEFAULT_CAMERA_PATH


def _get_valid_prim(prim_path: str):
    """Get a valid prim or return an error response dict.
    Returns (prim, None) on success or (None, error_dict) on failure.
    """
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return None, {
            "status": "error",
            "error": f"Prim not found: {prim_path}. Use get_scene_tree() to see available prims.",
        }
    return prim, None


def _validate_vec3(value, name: str) -> list[float]:
    """Validate that value is a list of 3 numbers. Returns the validated list."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{name} must be [x, y, z] with 3 numeric values, got {value}")
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        raise ValueError(f"{name} must contain numeric values, got {value}")


def _get_stage() -> Usd.Stage:
    ctx = omni.usd.get_context()
    stage = ctx.get_stage()
    if stage is None:
        raise RuntimeError("No USD stage is open")
    return stage


CAMERA_SETTLE_FRAMES = 20

# A capture that took longer than this logs how long its frame and its file took, for the cold-start runs of #27.
SLOW_CAPTURE_SECONDS = 2.0


async def _next_update():
    """Wait for next sim update frame to ensure thread safety."""
    await omni.kit.app.get_app().next_update_async()


async def capture_viewport_png(viewport, budget: capture.Budget | None = None, *, fresh: bool = True) -> bytes:
    """The viewport's frame as PNG bytes (capture_file_png).

    `fresh` lets FRESH_FRAMES frames of the viewport pass first: Kit captures the next frame it delivers, which the
    renderer made about 3 updates earlier, so a drawing or a change made just before the call was missing (#57).
    Recording asks for none (handlers/recording.py says why).
    """
    from omni.kit.viewport.utility import capture_viewport_to_file

    return await capture_file_png(
        lambda path: capture_viewport_to_file(viewport, file_path=path),
        budget,
        next_frame=(lambda: _next_frame(viewport)) if fresh else None,
    )


async def capture_feed_png(feed, budget: capture.Budget | None = None) -> bytes:
    """A camera feed's next frame as PNG bytes (capture_file_png), taken as the viewport's are (camera_feed.py).

    No fresh frames: the feed renders with the update, and its next frame shows the simulation within one update of
    the request (#25's E17), where the viewport's trails by about 3 (#57).
    """
    from omni.kit.widget.viewport.capture import FileCapture

    scheduled = []

    def schedule(path: str):
        scheduled.append(feed.schedule(FileCapture(path)))
        return scheduled[-1]

    try:
        return await capture_file_png(schedule, budget)
    finally:
        # A capture given up at its bound, or cancelled, must not be handed a frame later: its file is gone.
        for delegate in scheduled:
            feed.withdraw(delegate)


async def capture_file_png(schedule, budget: capture.Budget | None = None, *, next_frame=None) -> bytes:
    """What `schedule(path)` captures into `path`, as PNG bytes, read once Kit has written all of it
    (ovmcp.core.capture.capture_png), after the frames `next_frame` gives, if any.

    A CaptureError, a RuntimeError, when no whole file arrives in time; each wait is bounded, and capped by `budget`.
    Each capture gets a file of its own: with one path for every capture, a capture whose file wasn't written yet read
    the previous capture's file, so every image was one capture behind (#32). On Kit 110 wait_for_result returns before
    the file is written, so the file is waited for too.
    """
    path = Path(tempfile.gettempdir()) / f"ovmcp_capture_{uuid.uuid4().hex}.png"
    started = time.monotonic()
    try:
        png = await capture.capture_png(
            lambda: schedule(str(path)), path.read_bytes, _next_update, budget, next_frame=next_frame
        )
    except capture.CaptureError as e:
        carb.log_warn(f"[MCP Bridge] Capture failed after {time.monotonic() - started:.1f} s: {e}")
        raise
    finally:
        # A file Kit is still writing can't be deleted on Windows; its name is never read again.
        with contextlib.suppress(OSError):
            path.unlink()
    if png.fresh_seconds + png.frame_seconds + png.file_seconds > SLOW_CAPTURE_SECONDS:
        # The stage's frame history is how far behind the update the app lets its renderer run: a longer one than
        # Isaac Sim's 3 could need more fresh frames.
        history = carb.settings.get_settings().get("/app/settings/fabricDefaultStageFrameHistoryCount")
        carb.log_info(
            f"[MCP Bridge] Slow capture: the fresh frames took {png.fresh_seconds:.2f} s, the frame "
            f"{png.frame_seconds:.2f} s, the file {png.file_seconds:.2f} s (stage frame history: {history})"
        )
    return png.data


# Fallbacks already reported in Kit's log, so each is reported once rather than on every frame.
_warned: set[str] = set()


async def _next_frame(viewport):
    """One frame of `viewport`, through next_viewport_frame_async.

    Not ViewportAPI.wait_for_rendered_frames: that counts the call it makes on subscribe as a frame, and a cancelled
    wait leaves its callback in the viewport for good. A Kit without the frame event (no usd_context on the viewport,
    say) gets an app update instead, rather than a failed settle or capture. A wait cut short by its time limit is
    cancelled, which is not an Exception, so it is never taken for that.
    """
    try:
        from omni.kit.viewport.utility import next_viewport_frame_async

        await next_viewport_frame_async(viewport, 1)
    except Exception as e:
        if "frame event" not in _warned:
            _warned.add("frame event")
            carb.log_warn(f"[MCP Bridge] Can't wait for the viewport's frames, pumping app updates instead: {e}")
        await _next_update()


async def _viewport_frames(count: int, budget: capture.Budget | None):
    """`count` frames of the active viewport, each bounded by time (ovmcp.core.capture.frames), through _next_frame.

    Without the viewport utility or a viewport, it pumps app updates, as it always has.
    """
    try:
        from omni.kit.viewport.utility import get_active_viewport

        viewport = get_active_viewport()
    except Exception:
        viewport = None
    if viewport is None:
        for _ in range(count):
            await _next_update()
        return
    await capture.frames(lambda: _next_frame(viewport), count, budget)


async def _settle_viewport(frames: int | None = None, budget: capture.Budget | None = None):
    """Wait for the viewport renderer to settle after camera/scene changes.

    Camera moves, resolution changes, and render product updates don't propagate instantly through the rendering
    pipeline. Each frame is bounded (ovmcp.core.capture): NoFrameError when the viewport renders nothing, or
    OutOfTimeError when `budget` runs out; without a budget, all the frames share FRAME_SECONDS.

    Args:
        frames: Number of frames to wait.  Defaults to CAMERA_SETTLE_FRAMES (20).
        budget: The calling handler's time, if it has one.
    """
    await _viewport_frames(CAMERA_SETTLE_FRAMES if frames is None else frames, budget)


async def _reset_renderer(wait_frames: int = 10, budget: capture.Budget | None = None):
    """Reset renderer accumulation and wait for fresh frames.

    This forces the RTX renderer to discard its cached frame data and
    re-render from scratch.  Call after lighting changes, scene creation,
    or whenever the viewport shows stale/black content.

    Temporarily disables Eco Mode (which pauses rendering on static
    scenes) so that the reset actually produces new frames. The frames are
    bounded as _settle_viewport's are, and Eco Mode comes back on whatever
    the wait gives.

    Args:
        wait_frames: Number of viewport frames to wait after the reset.
        budget: The calling handler's time, if it has one.
    """
    settings = carb.settings.get_settings()

    # Eco Mode pauses rendering when the scene is static, which prevents
    # the renderer from producing new frames after a reset.  Temporarily
    # disable it so our wait actually sees fresh renders.
    eco_was_on = bool(settings.get("/rtx/ecoMode/enabled"))
    if eco_was_on:
        settings.set_bool("/rtx/ecoMode/enabled", False)
    try:
        try:
            ctx = omni.usd.get_context()
            ctx.reset_renderer_accumulation()
        except Exception:
            pass
        await _viewport_frames(wait_frames, budget)
    finally:
        if eco_was_on:
            settings.set_bool("/rtx/ecoMode/enabled", True)


def _serialize_value(val):
    """Convert a USD value to a JSON-serializable Python object."""
    if val is None:
        return None
    if isinstance(val, (Gf.Vec2f, Gf.Vec2d)):
        return [float(val[i]) for i in range(2)]
    if isinstance(val, (Gf.Vec3f, Gf.Vec3d)):
        return [float(val[0]), float(val[1]), float(val[2])]
    if isinstance(val, (Gf.Vec4f, Gf.Vec4d)):
        return [float(val[i]) for i in range(4)]
    if isinstance(val, (Gf.Quatf, Gf.Quatd)):
        return {"w": float(val.GetReal()), "xyz": [float(v) for v in val.GetImaginary()]}
    if isinstance(val, Gf.Matrix4d):
        return [[float(val[r][c]) for c in range(4)] for r in range(4)]
    if isinstance(val, Sdf.AssetPath):
        return str(val.resolvedPath or val.path)
    if isinstance(val, (bool, int, float, str)):
        return val
    if isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]
    try:
        json.dumps(val)
        return val
    except (TypeError, ValueError):
        return str(val)


def _apply_xform(prim, position=None, rotation=None, scale=None):
    """Apply transform ops to a prim. Preserves existing ops not being set.

    Uses existing attribute precisions to avoid type-mismatch errors when
    the prim already has xformOp attributes (e.g. from USD assets).
    """
    xformable = UsdGeom.Xformable(prim)
    if position is None and rotation is None and scale is None:
        return

    if position is not None:
        position = _validate_vec3(position, "position")

    # Read existing values and precisions before clearing
    existing_ops = xformable.GetOrderedXformOps()
    old_translate = None
    old_translate_prec = UsdGeom.XformOp.PrecisionDouble
    old_rotate = None
    old_rotate_type = None  # "xyz" or "orient"
    old_rotate_prec = UsdGeom.XformOp.PrecisionDouble
    old_scale = None
    old_scale_prec = UsdGeom.XformOp.PrecisionFloat
    for op in existing_ops:
        op_type = op.GetOpType()
        if op_type == UsdGeom.XformOp.TypeTranslate:
            old_translate = op.Get()
            old_translate_prec = op.GetPrecision()
        elif op_type == UsdGeom.XformOp.TypeRotateXYZ:
            old_rotate = op.Get()
            old_rotate_type = "xyz"
            old_rotate_prec = op.GetPrecision()
        elif op_type == UsdGeom.XformOp.TypeOrient:
            old_rotate = op.Get()
            old_rotate_type = "orient"
            old_rotate_prec = op.GetPrecision()
        elif op_type == UsdGeom.XformOp.TypeScale:
            old_scale = op.Get()
            old_scale_prec = op.GetPrecision()

    xformable.ClearXformOpOrder()

    # Translate
    t = position if position is not None else old_translate
    if t is not None:
        prec = old_translate_prec if old_translate is not None else UsdGeom.XformOp.PrecisionDouble
        xformable.AddTranslateOp(precision=prec).Set(Gf.Vec3d(*t) if position is not None else t)

    # Rotation
    if rotation is not None:
        if len(rotation) == 3:
            prec = old_rotate_prec if old_rotate_type == "xyz" else UsdGeom.XformOp.PrecisionFloat
            xformable.AddRotateXYZOp(precision=prec).Set(Gf.Vec3f(*rotation))
        elif len(rotation) == 4:
            prec = old_rotate_prec if old_rotate_type == "orient" else UsdGeom.XformOp.PrecisionDouble
            quat = Gf.Quatd(rotation[0], Gf.Vec3d(rotation[1], rotation[2], rotation[3]))
            xformable.AddOrientOp(precision=prec).Set(quat)
    elif old_rotate is not None:
        if old_rotate_type == "orient":
            xformable.AddOrientOp(precision=old_rotate_prec).Set(old_rotate)
        else:
            xformable.AddRotateXYZOp(precision=old_rotate_prec).Set(old_rotate)

    # Scale
    if scale is not None:
        if isinstance(scale, (int, float)):
            scale = [scale, scale, scale]
        elif isinstance(scale, (list, tuple)) and len(scale) == 3:
            scale = _validate_vec3(scale, "scale")
        prec = old_scale_prec if old_scale is not None else UsdGeom.XformOp.PrecisionFloat
        if prec == UsdGeom.XformOp.PrecisionDouble:
            xformable.AddScaleOp(precision=prec).Set(Gf.Vec3d(*scale))
        else:
            xformable.AddScaleOp(precision=prec).Set(Gf.Vec3f(*scale))
    elif old_scale is not None:
        xformable.AddScaleOp(precision=old_scale_prec).Set(old_scale)


def _compute_mesh_stats(prim) -> dict:
    """Compute face/vertex/triangle counts for a prim and all descendant meshes.

    Uses TraverseInstanceProxies to see through instanceable references
    (common in Isaac Sim robot assets).
    """
    stats = {
        "total_faces": 0,
        "total_vertices": 0,
        "total_triangles": 0,
        "mesh_count": 0,
        "meshes": [],
    }
    for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        if not p.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(p)
        face_counts = mesh.GetFaceVertexCountsAttr().Get()
        points = mesh.GetPointsAttr().Get()
        if face_counts is None:
            continue
        n_faces = len(face_counts)
        n_vertices = len(points) if points else 0
        n_triangles = sum(max(0, c - 2) for c in face_counts)
        stats["total_faces"] += n_faces
        stats["total_vertices"] += n_vertices
        stats["total_triangles"] += n_triangles
        stats["mesh_count"] += 1
        stats["meshes"].append(
            {
                "path": str(p.GetPath()),
                "faces": n_faces,
                "vertices": n_vertices,
                "triangles": n_triangles,
            }
        )
    return stats


def _collect_materials(prim) -> list[str]:
    """Collect unique material binding paths for a prim subtree."""
    materials = set()
    for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        binding = UsdShade.MaterialBindingAPI(p)
        mat, _ = binding.ComputeBoundMaterial()
        if mat:
            materials.add(str(mat.GetPath()))
    return sorted(materials)
