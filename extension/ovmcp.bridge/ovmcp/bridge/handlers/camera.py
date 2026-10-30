"""
Camera and viewport handlers: set_camera, look_at, inspect, capture, viewport_light.
"""

import base64
import math
import time
import traceback

import carb
import omni.kit.app
import omni.usd
from pxr import Gf, Usd, UsdGeom

from ovmcp.core import capture
from ovmcp.core.bounds import box_corners, center_and_size, screen_box, world_bbox
from ovmcp.core.framing import apply_zoom, bounding_radius, fit_distance, inspect_args, require_perspective
from ovmcp.core.isolation import LIGHT_TYPES, Hidden, is_light, prims_to_hide
from ovmcp.core.lighting import camera_light_switch, current_mode
from ovmcp.core.png import encode_png, png_size
from ovmcp.core.recording import camera_error
from ovmcp.core.serial import LazyLock, serial

from ._utils import (
    CAMERA_SETTLE_FRAMES,
    _get_active_camera_path,
    _get_stage,
    _next_update,
    _reset_renderer,
    _settle_viewport,
    capture_feed_png,
)
from .camera_feed import CameraFeed, enable_segmentation, release

# Where a wait for instance segmentation got nothing, per stage, camera and size, so the next waits only briefly there.
_segmentation_waits = capture.SegmentationWaits()

# A request that names no size, from a Kit app whose viewport can't say its own: Isaac Sim's default.
_FALLBACK_SIZE = (1280, 720)

# Held for the whole of every handler that moves the viewport camera, hides prims or captures, so one request never
# sees another's half-done viewport. Not re-entrant: these handlers call _capture_frame, never each other.
_viewport = LazyLock()

_warned: set[str] = set()


def _warn_once(key: str, message: str):
    """Log a warning the first time only, for fallbacks that would otherwise repeat on every call."""
    if key not in _warned:
        _warned.add(key)
        carb.log_warn(message)


async def _settle_or_log(what: str):
    """Settle the viewport for a handler that answers the same with or without the frames: one that renders nothing
    costs FRAME_SECONDS and a warning, where the wait used to hang the handler and the viewport lock (#35)."""
    try:
        await _settle_viewport()
    except capture.CaptureError as e:
        carb.log_warn(f"[MCP Bridge] {what}: the viewport did not settle: {e}")


# ---------------------------------------------------------------------------
# Camera helpers
# ---------------------------------------------------------------------------


def _set_camera_xform(camera_path: str, eye: list[float], target: list[float]):
    """Set camera transform directly via UsdGeom.Xformable with look-at math.

    WARNING: This is a last-resort fallback for non-Isaac-Sim environments.
    UsdGeom.Xformable does NOT reliably move the viewport camera — the viewport
    camera controller can override USD xform ops.  Prefer set_camera_view() from
    isaacsim.core.utils.viewports whenever available.
    Handles the top-down degenerate case with explicit right vector.
    """
    stage = _get_stage()
    cam_prim = stage.GetPrimAtPath(camera_path)
    if not cam_prim.IsValid():
        return

    eye_v = Gf.Vec3d(*eye)
    target_v = Gf.Vec3d(*target)

    fwd = target_v - eye_v
    dist = fwd.GetLength()
    if dist < 1e-6:
        return
    fwd = fwd.GetNormalized()

    up_axis = UsdGeom.GetStageUpAxis(stage)
    world_up = Gf.Vec3d(0, 0, 1) if up_axis == "Z" else Gf.Vec3d(0, 1, 0)

    # Degenerate case: camera looking straight along up axis
    dot = abs(fwd[0] * world_up[0] + fwd[1] * world_up[1] + fwd[2] * world_up[2])
    if dot > 0.999:
        right = Gf.Vec3d(1, 0, 0)
    else:
        # right = world_up x back
        back = -fwd
        right = Gf.Vec3d(
            world_up[1] * back[2] - world_up[2] * back[1],
            world_up[2] * back[0] - world_up[0] * back[2],
            world_up[0] * back[1] - world_up[1] * back[0],
        ).GetNormalized()

    back = -fwd
    cam_up = Gf.Vec3d(
        back[1] * right[2] - back[2] * right[1],
        back[2] * right[0] - back[0] * right[2],
        back[0] * right[1] - back[1] * right[0],
    ).GetNormalized()

    # Row-major: row0=right, row1=up, row2=back, row3=translate
    m = Gf.Matrix4d(1)
    m[0][0], m[0][1], m[0][2] = right[0], right[1], right[2]
    m[1][0], m[1][1], m[1][2] = cam_up[0], cam_up[1], cam_up[2]
    m[2][0], m[2][1], m[2][2] = back[0], back[1], back[2]
    m[3][0], m[3][1], m[3][2] = eye_v[0], eye_v[1], eye_v[2]

    xformable = UsdGeom.Xformable(cam_prim)
    xformable.ClearXformOpOrder()
    xformable.AddTransformOp().Set(m)


def _is_image_black(png_bytes: bytes, threshold: int = 5) -> bool:
    """Check if a PNG image is all black (no lighting or renderer not warmed up)."""
    try:
        import io as _io

        import numpy as np
        from PIL import Image

        img = Image.open(_io.BytesIO(png_bytes)).convert("RGB")
        arr = np.array(img)
        return int(arr.max()) <= threshold
    except ImportError:
        # PIL/numpy not available — can't detect, assume not black
        return False


def _has_scene_lights() -> bool:
    """Check if the stage has any active UsdLux light prims."""
    return any(is_light(prim) for prim in _get_stage().Traverse())


def _get_camera_light_enabled() -> bool:
    """Check if the viewport camera light is enabled."""
    try:
        settings = carb.settings.get_settings()
        return bool(settings.get("/rtx/useViewLightingMode"))
    except Exception:
        return False


def _get_current_lighting_mode() -> str:
    """Get the current viewport lighting mode.

    Returns one of: "camera", "stage", "off", or a light rig name
    (e.g., "Default", "Colored Lights", "Grey Studio"); core/lighting.py decides.
    """
    menu_mode = None
    try:
        from omni.kit.viewport.menubar.lighting.utility import _make_light_mode_setting_key

        settings = carb.settings.get_settings()
        menu_mode = settings.get(_make_light_mode_setting_key(omni.usd.get_context()))
    except Exception as e:
        _warn_once("lighting-mode", f"[MCP Bridge] Can't read the lighting menu's mode, using the renderer's flag: {e}")
    return current_mode(_get_camera_light_enabled(), menu_mode)


def _get_available_lighting_modes() -> list[str]:
    """Get all available lighting modes including light rig presets."""
    modes = ["off", "camera", "stage"]
    try:
        from omni.kit.viewport.menubar.lighting.utility import _get_rig_names_and_paths

        rigs = _get_rig_names_and_paths("omni.kit.viewport.menubar.lighting")
        if rigs:
            modes.extend(name for name, _ in rigs)
    except Exception as e:
        _warn_once("lighting-rigs", f"[MCP Bridge] Can't list the lighting menu's light rigs: {e}")
    return modes


def _set_lighting_mode(mode: str) -> str | None:
    """Switch the viewport's lighting mode; the reason it did not change, or None.

    Goes through the lighting menu's command. Without it (headless or minimal
    Kit apps), "camera" and "stage" fall back to the renderer's camera-light
    flag, which needs no other extension.
    """
    ran = False
    reason = ""
    try:
        import omni.kit.commands

        outcome = omni.kit.commands.execute("SetLightingMenuModeCommand", lighting_mode=mode)
        # Kit returns (success, result) and logs, rather than raises, for a missing command.
        ran = bool(outcome[0] if isinstance(outcome, tuple) else outcome)
        if not ran:
            reason = "SetLightingMenuModeCommand did not run (is omni.kit.viewport.menubar.lighting enabled?)"
    except Exception as e:
        reason = f"SetLightingMenuModeCommand failed: {e}"

    if not ran and mode not in ("camera", "stage"):
        return f"Lighting mode not changed to '{mode}': {reason}"
    # The camera-light flag decides what current_mode() reports, so it follows every mode that takes: on for
    # "camera", off for the rest. For "camera" and "stage" it also stands in for a missing menu.
    flag = mode == "camera"
    carb.settings.get_settings().set("/rtx/useViewLightingMode", flag)
    if _get_camera_light_enabled() != flag:
        return f"Lighting mode not changed to '{mode}': the renderer's camera-light flag did not take. {reason}".strip()
    return None


def _viewport_size() -> tuple[int, int]:
    """The size the active viewport renders at, for a request that names none, so it gets the image it always got."""
    viewport = _active_viewport()
    try:
        if viewport is not None:
            width, height = viewport.resolution
            return int(width), int(height)
    except Exception as e:
        _warn_once("resolution", f"[MCP Bridge] Can't read the viewport's resolution, capturing at 1280x720: {e}")
    return _FALLBACK_SIZE


def _new_feed(camera_path: str, width: int, height: int) -> CameraFeed:
    """A feed of `camera_path` at the size asked for, for one call: the image, its segmentation and its boxes all come
    from it, so they agree with each other and with the size (#51); the user's viewport is never touched."""
    try:
        return CameraFeed(camera_path, width, height, prefix="ovmcp_capture")
    except ImportError as e:
        raise RuntimeError(f"This Kit app can't render a camera into a texture of its own: {e}") from None


def _turn_segmentation_on(feed: CameraFeed) -> str | None:
    """enable_segmentation, whose failure costs the segmentation alone, never the capture: why there is none, or
    None."""
    try:
        return enable_segmentation(feed)
    except Exception as e:
        carb.log_warn(f"[MCP Bridge] Instance segmentation could not be turned on: {e}")
        return f"Instance segmentation failed: {e}"


def _settle_frames() -> int:
    """The frames a feed renders after its first before a capture: for Path Tracing to reach its samples (core)."""
    settings = carb.settings.get_settings()
    return capture.settle_frames(
        settings.get("/rtx/rendermode"), settings.get("/rtx/pathtracing/spp"), settings.get("/rtx/pathtracing/totalSpp")
    )


def _segmentation_key(feed: CameraFeed) -> tuple:
    """What a capture's segmentation waits are kept by: its feed's render product is new with every call."""
    return (omni.usd.get_context().get_stage_id(), feed.camera_path, feed.resolution)


def _compute_autofit_distance(dims, camera_path, stage, width, height):
    """Camera distance at which the prim's bounding sphere fills the captured frame (core/framing.py)."""
    cam_prim = stage.GetPrimAtPath(camera_path)
    fl, h_ap, v_ap = 18.14756, 20.955, 15.2908  # Omniverse defaults
    if cam_prim.IsValid():
        cam = UsdGeom.Camera(cam_prim)
        require_perspective(cam.GetProjectionAttr().Get(), camera_path)
        fl_val = cam.GetFocalLengthAttr().Get()
        h_val = cam.GetHorizontalApertureAttr().Get()
        v_val = cam.GetVerticalApertureAttr().Get()
        if fl_val and fl_val > 0:
            fl = fl_val
        if h_val and h_val > 0:
            h_ap = h_val
        if v_val and v_val > 0:
            v_ap = v_val

    return fit_distance(bounding_radius(dims), fl, h_ap, v_ap, width, height)


async def _capture_frame(feed: CameraFeed, budget: capture.Budget | None = None) -> tuple[bytes, bool]:
    """A frame of `feed` as PNG bytes, and whether it is black.

    A black frame is taken once more after the renderer's accumulation is reset and the feed has rendered
    CAMERA_SETTLE_FRAMES more: the common case is an RTX renderer not yet warm after a scene change. A capture that
    fails is not retried. Each wait is capped by `budget`.
    """
    png_bytes = await capture_feed_png(feed, budget)
    is_black = _is_image_black(png_bytes)
    if is_black:
        carb.log_info("[MCP Bridge] Black frame detected, resetting renderer")
        await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES, budget=budget, frames=feed.wait_frames)
        png_bytes = await capture_feed_png(feed, budget)
        is_black = _is_image_black(png_bytes)
    return png_bytes, is_black


def _compute_screen_bboxes(view, img_width: int, img_height: int):
    """Screen boxes of the visible prims as `view` sees them, in the image's pixels, through omni.syntheticdata's
    projection: `view` is a capture's camera feed, which it reads as it reads a viewport (camera_feed.py).

    Returns list of {prim_path, type, screen_bbox [x_min, y_min, x_max, y_max],
    world_center, world_dimensions}.
    """
    import numpy as np
    import omni.syntheticdata as syn

    vp_params = syn.helpers.get_view_params(view)
    vp_w = vp_params["width"]
    vp_h = vp_params["height"]

    stage = _get_stage()
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    results = []

    skip_types = {"Camera", "Scope", "Shader", "Material", "NodeGraph", *LIGHT_TYPES}

    world_prim = stage.GetPrimAtPath("/World")
    if not world_prim.IsValid():
        return []
    for prim in Usd.PrimRange(world_prim, Usd.TraverseInstanceProxies()):
        path_str = str(prim.GetPath())

        type_name = prim.GetTypeName()
        if type_name in skip_types:
            continue

        # Only include geometry prims (Mesh, Cube, Sphere, etc.)
        if not prim.IsA(UsdGeom.Gprim) and type_name not in ("Xform",):
            continue

        # For Xform, skip unless it has no Gprim children (leaf group)
        if type_name == "Xform":
            continue

        # Skip invisible prims
        if prim.IsA(UsdGeom.Imageable):
            vis = UsdGeom.Imageable(prim).ComputeVisibility(Usd.TimeCode.Default())
            if vis == UsdGeom.Tokens.invisible:
                continue

        bbox = bbox_cache.ComputeWorldBound(prim)
        box = bbox.ComputeAlignedRange()
        if box.IsEmpty():
            continue

        min_pt = box.GetMin()
        max_pt = box.GetMax()

        pts = np.array(box_corners(min_pt, max_pt), dtype=np.float64)
        # (8, 3): x and y as fractions of the viewport, then depth
        projected = syn.helpers.world_to_image(pts, view, vp_params)
        screen_bbox = screen_box(projected.tolist(), (vp_w, vp_h), (img_width, img_height))
        if screen_bbox is None:
            continue

        center, dims = center_and_size(min_pt, max_pt)

        results.append(
            {
                "prim_path": path_str,
                "type": type_name,
                "screen_bbox": screen_bbox,
                "world_center": [round(c, 4) for c in center],
                "world_dimensions": [round(d, 4) for d in dims],
            }
        )

    return results


def _active_viewport():
    """The active viewport, or None without one or without the viewport utility."""
    try:
        from omni.kit.viewport.utility import get_active_viewport
    except ImportError:
        return None
    return get_active_viewport()


# Why an answer has no segmentation. Neither points at a new stage, which would throw the user's scene away. get_logs'
# search matches only a message, and omni.syntheticdata's own lines rarely name it, so they are found by their channel.
_SEGMENTATION_NONE = (
    "Instance segmentation gave no data within {seconds:g} s of enabling it: capture again, and if it stays empty, "
    'get_logs(channel="syntheticdata") shows what omni.syntheticdata reported'
)
_SEGMENTATION_AS_BEFORE = (
    "Instance segmentation gave no data for this camera and size on this stage before, and none in the {seconds:g} s "
    'this capture waited: capture again in a few seconds; get_logs(channel="syntheticdata") shows what '
    "omni.syntheticdata reported"
)


async def _segmentation(feed: CameraFeed, budget: capture.Budget) -> tuple[bytes | None, dict, str | None]:
    """Instance segmentation of the feed's last frame, each prim its own colour: (png, legend, None), where the legend
    maps prim_path -> [R, G, B], or (None, {}, why there is none).

    The sensor, turned on when the feed was made (enable_segmentation), gives data only once a frame has rendered
    after that, so it is read after each app update for SEGMENTATION_SECONDS: a count of updates was too few on a cold
    start (#27). Data counts only at the feed's size. After a wait that got nothing with this camera and size on this
    stage, the next waits SEGMENTATION_RETRY_SECONDS, until a read gets data.
    """
    try:
        import omni.syntheticdata as syn
    except ImportError:
        return None, {}, "omni.syntheticdata is not loaded: enable it with manage_extensions"
    try:
        key = _segmentation_key(feed)
        width, height = feed.resolution

        def read():
            return syn.sensors.get_instance_segmentation(feed)

        def whole(seg_array) -> bool:
            return seg_array is not None and tuple(seg_array.shape[:2]) == (height, width)

        seg_array = read()
        if not whole(seg_array):
            waited_before = _segmentation_waits.failed_before(key)
            seconds = _segmentation_waits.seconds(key)
            cut_short = budget.left() < seconds
            updates = 0

            async def next_update():
                nonlocal updates
                await _next_update()
                updates += 1

            started = time.monotonic()
            seg_array = await capture.poll(read, whole, next_update, seconds, budget)
            took = time.monotonic() - started
            if seg_array is None:
                if cut_short:
                    return None, {}, "Instance segmentation gave no data before this call's time ran out"
                _segmentation_waits.failed(key)
                if waited_before:
                    return None, {}, _SEGMENTATION_AS_BEFORE.format(seconds=seconds)
                carb.log_warn(
                    f"[MCP Bridge] Instance segmentation gave no data in {updates} updates, {took:.2f} s after "
                    "enabling it"
                )
                return None, {}, _SEGMENTATION_NONE.format(seconds=seconds)
            carb.log_info(
                f"[MCP Bridge] Instance segmentation's first data came {updates} updates, {took:.2f} s after "
                "enabling it"
            )
        _segmentation_waits.got_data(key)
        png_bytes, legend = _colour_segmentation(syn, seg_array)
        return png_bytes, legend, None
    except Exception as e:
        carb.log_warn(f"[MCP Bridge] Instance segmentation failed: {e}")
        return None, {}, f"Instance segmentation failed: {e}"


def _colour_segmentation(syn, seg_array) -> tuple[bytes, dict]:
    """The sensor's instance ids as a PNG, each prim its own colour, and the legend: prim_path -> [R, G, B]
    (core/capture.py's colour_instances)."""
    sd_iface = syn._syntheticdata.acquire_syntheticdata_interface()

    def name_of(instance: int) -> str | None:
        try:
            return sd_iface.get_uri_from_instance_segmentation_id(instance)
        except Exception:
            return None  # named by its id instead

    image, legend = capture.colour_instances(seg_array, name_of)
    return encode_png(image), legend


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


@serial(_viewport)
async def handle_camera_set(body: dict) -> dict:
    """Set the viewport camera position and target."""
    position = body.get("position")
    target = body.get("target")

    if position is None:
        return {"status": "error", "error": "position is required ([x, y, z])"}

    await _next_update()

    camera_path = _get_active_camera_path()

    effective_target = target if target is not None else [0, 0, 0]

    try:
        from isaacsim.core.utils.viewports import set_camera_view

        set_camera_view(
            eye=position,
            target=effective_target,
            camera_prim_path=camera_path,
        )
    except (ImportError, Exception):
        # Fallback: set transform directly via USD
        stage = _get_stage()
        cam_prim = stage.GetPrimAtPath(camera_path)
        if not cam_prim.IsValid():
            return {"status": "error", "error": f"Camera prim not found: {camera_path}"}
        from ._utils import _apply_xform

        _apply_xform(cam_prim, position=position)

    # Wait for camera transform to propagate through the rendering pipeline
    await _settle_or_log("set_camera")

    return {
        "status": "success",
        "result": {"camera_path": camera_path, "position": position, "target": target},
    }


@serial(_viewport)
async def handle_camera_look_at(body: dict) -> dict:
    """Point the camera at a prim from a given distance and angle."""
    prim_path = body.get("prim_path", "")
    distance = body.get("distance")  # Auto-compute if not provided
    azimuth = body.get("azimuth", 45.0)  # degrees, 0=front
    elevation = body.get("elevation", 30.0)  # degrees above horizontal

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, _ = world_bbox(prim)
    max_dim = max(dims) if max(dims) > 0.01 else 1.0

    if distance is None:
        distance = max_dim * 2.5  # Auto: 2.5x the object size

    # Compute camera position on a sphere around the target
    az_rad = math.radians(azimuth)
    el_rad = math.radians(elevation)

    up_axis = UsdGeom.GetStageUpAxis(stage)
    if up_axis == "Z":
        cam_pos = [
            center[0] + distance * math.cos(el_rad) * math.sin(az_rad),
            center[1] + distance * math.cos(el_rad) * math.cos(az_rad),
            center[2] + distance * math.sin(el_rad),
        ]
    else:  # Y-up
        cam_pos = [
            center[0] + distance * math.cos(el_rad) * math.sin(az_rad),
            center[1] + distance * math.sin(el_rad),
            center[2] + distance * math.cos(el_rad) * math.cos(az_rad),
        ]

    # Use the set_camera_view utility
    await _next_update()
    try:
        from isaacsim.core.utils.viewports import set_camera_view

        camera_path = _get_active_camera_path()

        set_camera_view(eye=cam_pos, target=center, camera_prim_path=camera_path)
    except ImportError:
        # Fallback: manually set transform
        camera_path = _get_active_camera_path()
        cam_prim = stage.GetPrimAtPath(camera_path)
        if cam_prim.IsValid():
            xformable = UsdGeom.Xformable(cam_prim)
            xformable.ClearXformOpOrder()
            xformable.AddTranslateOp().Set(Gf.Vec3d(*cam_pos))

    # Wait for camera transform to propagate through the rendering pipeline
    await _settle_or_log("look_at_prim")

    return {
        "status": "success",
        "result": {
            "camera_path": camera_path,
            "camera_position": [round(v, 4) for v in cam_pos],
            "target": center,
            "distance": round(distance, 4),
            "azimuth": azimuth,
            "elevation": elevation,
        },
    }


@serial(_viewport)
async def handle_camera_inspect(body: dict) -> dict:
    """Orbit-capture: take screenshots from multiple angles around a prim.

    Auto-fits camera distance so the prim fills the frame with ~10px margin, at the size asked for.
    Use zoom_offset to adjust: negative=closer, positive=further, 0=auto-fit.
    Use isolate=True to hide all other scene content during capture.
    Optionally includes instance segmentation at each angle.

    Every frame comes from one camera feed of the viewport's camera at that size, made for the call (#51), as the orbit
    moves the camera. Each wait is bounded, and the call has CALL_SECONDS (ovmcp.core.capture), under the server's
    120 s: an angle that fails says why, and once the feed gives no frame or the time runs out, the angles left say
    "Not captured".
    """
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}
    try:
        args = inspect_args(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    zoom_offset, isolate = args.zoom_offset, args.isolate
    width, height = args.size or _viewport_size()

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, _ = world_bbox(prim)

    # Auto-fit distance, then zoom_offset: 0=auto-fit, negative=closer, positive=further. The fit refuses an
    # orthographic camera, and a frame with no room inside its margins, judged on the size captured.
    camera_path = _get_active_camera_path()
    try:
        distance = apply_zoom(_compute_autofit_distance(dims, camera_path, stage, width, height), zoom_offset)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    up_axis = UsdGeom.GetStageUpAxis(stage)

    try:
        feed = _new_feed(camera_path, width, height)
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}
    call = capture.Call(capture.CALL_SECONDS)
    # Isolate: hide everything but the prim and the lights, in the session layer, inside the try so it always undoes
    hidden = Hidden(stage.GetSessionLayer())
    isolate_warnings: list[str] = []
    captures = []
    # A camera move restarts Path Tracing's samples, so each angle waits for them on top of its settle.
    settle = CAMERA_SETTLE_FRAMES + _settle_frames()
    try:
        segmentation_problem = _turn_segmentation_on(feed) if args.include_segmentation else None
        if isolate:
            paths, isolate_warnings = prims_to_hide(stage, prim_path)
            hidden.hide(paths)
            isolate_warnings += hidden.warnings
            try:
                await feed.wait_frames(CAMERA_SETTLE_FRAMES, call.budget)
            except capture.CaptureError as e:
                # No frame with the prims hidden: every angle would wait the same, so none is tried.
                call.failed(e)

        for angle_name, az, el in args.angles:
            skipped = call.skipped(angle_name)
            if skipped is not None:
                captures.append(skipped)
                continue

            az_rad = math.radians(az)
            el_rad = math.radians(el)

            if up_axis == "Z":
                cam_pos = [
                    center[0] + distance * math.cos(el_rad) * math.sin(az_rad),
                    center[1] + distance * math.cos(el_rad) * math.cos(az_rad),
                    center[2] + distance * math.sin(el_rad),
                ]
            else:
                cam_pos = [
                    center[0] + distance * math.cos(el_rad) * math.sin(az_rad),
                    center[1] + distance * math.sin(el_rad),
                    center[2] + distance * math.cos(el_rad) * math.cos(az_rad),
                ]

            # Prefer set_camera_view (reliable); fall back to USD xform (unreliable)
            try:
                from isaacsim.core.utils.viewports import set_camera_view

                set_camera_view(eye=cam_pos, target=center, camera_prim_path=camera_path)
            except ImportError:
                _set_camera_xform(camera_path, cam_pos, center)

            try:
                # The feed renders the camera's new place a few frames after the move (#51's E14: 3)
                await feed.wait_frames(settle, call.budget)
                png_bytes, is_black = await _capture_frame(feed, call.budget)
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                cap_entry = {
                    "angle": angle_name,
                    "azimuth": az,
                    "elevation": el,
                    "camera_position": [round(v, 4) for v in cam_pos],
                    "image_base64": b64,
                    "is_black": is_black,
                }

                if args.include_segmentation:
                    if segmentation_problem:
                        seg_png, legend, seg_error = None, {}, segmentation_problem
                    else:
                        seg_png, legend, seg_error = await _segmentation(feed, call.budget)
                    if seg_png:
                        cap_entry["segmentation_base64"] = base64.b64encode(seg_png).decode("utf-8")
                        cap_entry["segmentation_legend"] = legend
                    else:
                        cap_entry["segmentation_error"] = seg_error

                captures.append(cap_entry)
            except Exception as e:
                # A frame that never came, or the call's time running out, stops the angles after this one.
                call.failed(e)
                captures.append(
                    {
                        "angle": angle_name,
                        "error": str(e),
                    }
                )
    finally:
        # Put each hidden prim's session-layer visibility back as it was
        if len(hidden):
            hidden.restore()
            # Under a time of its own, since the call's may be spent; not at all after the feed gave no frame. The
            # viewport's frames: the user's view is what shows the prims again.
            if call.settle_after_restore():
                try:
                    await _settle_viewport(budget=capture.Budget(capture.CLEANUP_SECONDS))
                except capture.CaptureError as e:
                    carb.log_warn(f"[MCP Bridge] inspect_prim: the viewport did not settle after isolate: {e}")
        await release(feed)

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "center": center,
            "distance": round(distance, 4),
            "zoom_offset": zoom_offset,
            "isolate": isolate,
            "isolate_warnings": isolate_warnings,
            "width": width,
            "height": height,
            "camera_path": camera_path,
            "lighting_mode": _get_current_lighting_mode(),
            "captures": captures,
        },
    }


@serial(_viewport)
async def handle_capture(body: dict) -> dict:
    """The image, screen boxes and instance segmentation of one frame of `camera_path` (the viewport's camera when
    empty) at the size asked for (the viewport's when none is), from a camera feed made for the call: all three agree,
    in the image's pixels, and the user's viewport never changes (#51)."""
    try:
        size = capture.capture_size(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    await _next_update()

    camera_path = str(body.get("camera_path") or _get_active_camera_path())
    problem = camera_error(_get_stage(), camera_path)
    if problem:
        return {"status": "error", "error": problem}
    width, height = size or _viewport_size()
    call = capture.Call(capture.CALL_SECONDS)

    feed = None
    try:
        feed = _new_feed(camera_path, width, height)
        # Turned on with the feed, so a capture that fails after it still frees its graphs on the way out.
        segmentation_problem = _turn_segmentation_on(feed)
        # The bound a viewport frame gets, sized for a renderer's cold start (#27).
        await feed.first_frame(capture.FRAME_SECONDS)
        settle = _settle_frames()
        if settle:
            await feed.wait_frames(settle, call.budget)

        # 1. The image
        png_bytes, is_black = await _capture_frame(feed, call.budget)
        b64_image = base64.b64encode(png_bytes).decode("utf-8")
        # The image's own size: what the boxes are in, and what the server prints.
        image_width, image_height = png_size(png_bytes) or (width, height)

        result = {
            "image_base64": b64_image,
            "width": image_width,
            "height": image_height,
            "camera_path": camera_path,
            "format": "png",
            "is_black": is_black,
            "lighting_mode": _get_current_lighting_mode(),
        }
        if is_black:
            result["has_scene_lights"] = _has_scene_lights()

        # 2. Screen-space bounding boxes of the visible prims, from the camera and size captured
        try:
            bboxes = _compute_screen_bboxes(feed, image_width, image_height)
            result["screen_bboxes"] = bboxes
        except Exception as e:
            carb.log_warn(f"Screen bbox computation failed: {e}")
            result["screen_bboxes"] = []

        # 3. Instance segmentation of the same feed
        if segmentation_problem:
            seg_png, color_legend, seg_error = None, {}, segmentation_problem
        else:
            seg_png, color_legend, seg_error = await _segmentation(feed, call.budget)
        if seg_png:
            result["segmentation_base64"] = base64.b64encode(seg_png).decode("utf-8")
            result["segmentation_legend"] = color_legend
        else:
            result["segmentation_base64"] = None
            result["segmentation_legend"] = {}
            result["segmentation_error"] = seg_error

        return {"status": "success", "result": result}
    except Exception as e:
        tb = traceback.format_exc()
        return {"status": "error", "error": str(e), "traceback": tb}
    finally:
        if feed is not None:
            await release(feed)


@serial(_viewport)
async def handle_viewport_light(body: dict) -> dict:
    """Get or set viewport lighting mode.

    Actions:
      - "get" (default): return current lighting mode and available modes
      - "set": set lighting mode (mode parameter required)
        Available modes: "off", "camera", "stage", or a light rig name
        (e.g., "Default", "Colored Lights", "Grey Studio").
      - "set_camera_light": legacy alias — enable/disable camera light
    """
    action = body.get("action", "get")

    if action == "get":
        mode_now = _get_current_lighting_mode()
        available_modes = _get_available_lighting_modes()

        # List scene lights
        scene_lights = []
        stage = _get_stage()
        for prim in stage.Traverse():
            if is_light(prim):
                light_info = {"path": str(prim.GetPath()), "type": prim.GetTypeName()}
                intensity_attr = prim.GetAttribute("inputs:intensity")
                if not intensity_attr or not intensity_attr.HasValue():
                    intensity_attr = prim.GetAttribute("intensity")
                if intensity_attr and intensity_attr.HasValue():
                    light_info["intensity"] = float(intensity_attr.Get())
                scene_lights.append(light_info)

        return {
            "status": "success",
            "result": {
                "lighting_mode": mode_now,
                "available_modes": available_modes,
                "has_scene_lights": len(scene_lights) > 0,
                "scene_lights": scene_lights,
            },
        }

    if action in ("set", "set_camera_light"):
        if action == "set":
            mode = body.get("mode", "")
            available = _get_available_lighting_modes()
            if not mode:
                return {
                    "status": "error",
                    "error": f"mode is required for 'set' action. Available: {', '.join(available)}",
                }
            if mode not in available:
                return {"status": "error", "error": f"Unknown mode: '{mode}'. Available: {', '.join(available)}"}
        else:
            # Legacy alias: on is mode "camera"; off leaves a rig alone (core/lighting.py)
            mode = camera_light_switch(bool(body.get("enabled", True)), _get_current_lighting_mode())

        try:
            if mode is None:
                carb.settings.get_settings().set("/rtx/useViewLightingMode", False)
                message = "Viewport camera light turned off; the lighting mode is unchanged"
            else:
                error = _set_lighting_mode(mode)
                if error:
                    return {"status": "error", "error": error}
                message = f"Lighting mode set to '{mode}'"
            try:
                await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES)
            except capture.CaptureError as e:
                # The mode is set; only the fresh frames after it are missing, as a viewport that renders nothing has.
                carb.log_warn(f"[MCP Bridge] viewport_light: the viewport did not render after the reset: {e}")
            return {
                "status": "success",
                "result": {
                    "lighting_mode": _get_current_lighting_mode(),
                    "message": message,
                },
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to set lighting mode: {e}"}

    else:
        return {"status": "error", "error": f"Unknown action: {action}. Use 'get', 'set', or 'set_camera_light'"}
