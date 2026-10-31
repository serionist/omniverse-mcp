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


def _first_missing(stage, path: str) -> str:
    """The shallowest of path and its ancestors with no prim: what DefinePrim(path) makes, missing parents included, so
    a call that refuses after it can take away all it made."""
    for prefix in Sdf.Path(path).GetPrefixes():
        if not stage.GetPrimAtPath(prefix).IsValid():
            return str(prefix)
    return path


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


async def capture_feed_png(feed, budget: capture.Budget | None = None) -> bytes:
    """A camera feed's next frame as PNG bytes (capture_file_png), taken as the viewport's are (camera_feed.py).

    The feed renders with the update, so its next frame shows the simulation within one update of the request (#25's
    E17), where the viewport's next frame trailed by about 3 (#57): recording, capture_viewport and inspect_prim all
    capture this way (#25, #51).
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


async def capture_file_png(schedule, budget: capture.Budget | None = None) -> bytes:
    """What `schedule(path)` captures into `path`, as PNG bytes, read once Kit has written all of it
    (ovmcp.core.capture.capture_png).

    A CaptureError, a RuntimeError, when no whole file arrives in time; each wait is bounded, and capped by `budget`.
    Each capture gets a file of its own: with one path for every capture, a capture whose file wasn't written yet read
    the previous capture's file, so every image was one capture behind (#32). On Kit 110 wait_for_result returns before
    the file is written, so the file is waited for too.
    """
    path = Path(tempfile.gettempdir()) / f"ovmcp_capture_{uuid.uuid4().hex}.png"
    started = time.monotonic()
    try:
        png = await capture.capture_png(lambda: schedule(str(path)), path.read_bytes, _next_update, budget)
    except capture.CaptureError as e:
        carb.log_warn(f"[MCP Bridge] Capture failed after {time.monotonic() - started:.1f} s: {e}")
        raise
    finally:
        # A file Kit is still writing can't be deleted on Windows; its name is never read again.
        with contextlib.suppress(OSError):
            path.unlink()
    if png.frame_seconds + png.file_seconds > SLOW_CAPTURE_SECONDS:
        carb.log_info(
            f"[MCP Bridge] Slow capture: the frame took {png.frame_seconds:.2f} s, the file {png.file_seconds:.2f} s"
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


async def _reset_renderer(wait_frames: int = 10, budget: capture.Budget | None = None, frames=None):
    """Reset renderer accumulation and wait for fresh frames.

    This forces the RTX renderer to discard its cached frame data and
    re-render from scratch.  Call after lighting changes, scene creation,
    or whenever the viewport shows stale/black content.

    Temporarily disables Eco Mode (which pauses rendering on static
    scenes) so that the reset actually produces new frames. The frames are
    bounded as _settle_viewport's are, and Eco Mode comes back on whatever
    the wait gives.

    Args:
        wait_frames: Number of frames to wait after the reset.
        budget: The calling handler's time, if it has one.
        frames: What waits for them, `(count, budget)`: a camera feed's `wait_frames` for a capture, which renders
            through a feed of its own (#51); the viewport's frames when None.
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
        await (frames or _viewport_frames)(wait_frames, budget)
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
