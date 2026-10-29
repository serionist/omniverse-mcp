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

import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade

from ovmcp.core.extensions import extension_step, is_listed
from ovmcp.core.png import is_complete_png

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


async def _next_update():
    """Wait for next sim update frame to ensure thread safety."""
    await omni.kit.app.get_app().next_update_async()


# How long a capture may take to reach disk. On Kit 110 capture_viewport_to_file's wait_for_result returns before
# the file is written, so the file is waited for, not the capture.
CAPTURE_TIMEOUT_SECONDS = 10.0


async def capture_viewport_png(viewport) -> bytes:
    """The viewport's frame as PNG bytes, read once Kit has written all of it. RuntimeError when no whole file arrives.

    Each capture gets a file of its own: with one path for every capture, a capture whose file wasn't written yet read
    the previous capture's file, so every image was one capture behind (#32).
    """
    from omni.kit.viewport.utility import capture_viewport_to_file

    path = Path(tempfile.gettempdir()) / f"ovmcp_capture_{uuid.uuid4().hex}.png"
    try:
        await capture_viewport_to_file(viewport, file_path=str(path)).wait_for_result()
        deadline = time.monotonic() + CAPTURE_TIMEOUT_SECONDS
        while True:
            with contextlib.suppress(OSError):
                data = path.read_bytes()
                if is_complete_png(data):
                    return data
            if time.monotonic() > deadline:
                raise RuntimeError("Viewport capture produced no output")
            await _next_update()
    finally:
        # A file Kit is still writing can't be deleted on Windows; its name is never read again.
        with contextlib.suppress(OSError):
            path.unlink()


async def _settle_viewport(frames: int = None):
    """Wait for the viewport renderer to settle after camera/scene changes.

    Camera moves, resolution changes, and render product updates don't
    propagate instantly through the rendering pipeline.  This helper uses
    ``viewport_api.wait_for_rendered_frames()`` when available (Kit 105+)
    and falls back to pumping ``_next_update()`` in a loop.

    Args:
        frames: Number of frames to wait.  Defaults to CAMERA_SETTLE_FRAMES (20).
    """
    if frames is None:
        frames = CAMERA_SETTLE_FRAMES
    try:
        from omni.kit.viewport.utility import get_active_viewport

        viewport = get_active_viewport()
        if viewport and hasattr(viewport, "wait_for_rendered_frames"):
            await viewport.wait_for_rendered_frames(frames)
            return
    except (ImportError, Exception):
        pass
    # Fallback: pump update loop
    for _ in range(frames):
        await _next_update()


async def _reset_renderer(wait_frames: int = 10):
    """Reset renderer accumulation and wait for fresh frames.

    This forces the RTX renderer to discard its cached frame data and
    re-render from scratch.  Call after lighting changes, scene creation,
    or whenever the viewport shows stale/black content.

    Temporarily disables Eco Mode (which pauses rendering on static
    scenes) so that the reset actually produces new frames.

    Args:
        wait_frames: Number of viewport frames to wait after the reset.
    """
    import carb as _carb

    settings = _carb.settings.get_settings()

    # Eco Mode pauses rendering when the scene is static, which prevents
    # the renderer from producing new frames after a reset.  Temporarily
    # disable it so our wait actually sees fresh renders.
    eco_was_on = bool(settings.get("/rtx/ecoMode/enabled"))
    if eco_was_on:
        settings.set_bool("/rtx/ecoMode/enabled", False)

    try:
        ctx = omni.usd.get_context()
        ctx.reset_renderer_accumulation()
    except Exception:
        pass

    # Use viewport-level frame waiting if available (more accurate than
    # app-level next_update which doesn't guarantee a render completed).
    try:
        from omni.kit.viewport.utility import (
            get_active_viewport,
            next_viewport_frame_async,
        )

        viewport = get_active_viewport()
        if viewport:
            await next_viewport_frame_async(viewport, wait_frames)
            if eco_was_on:
                settings.set_bool("/rtx/ecoMode/enabled", True)
            return
    except (ImportError, Exception):
        pass

    # Fallback: pump app updates
    for _ in range(wait_frames):
        await _next_update()

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
