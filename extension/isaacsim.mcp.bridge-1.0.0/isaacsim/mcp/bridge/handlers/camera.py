"""
Camera and viewport handlers: set_camera, look_at, inspect, capture, viewport_light.
"""

import base64
import math
import os
import traceback

import carb
import omni.kit.app
import omni.usd
from pxr import Gf, Usd, UsdGeom

from ..core.framing import apply_zoom, bounding_radius, fit_distance, inspect_args, require_perspective
from ..core.isolation import LIGHT_TYPES, Hidden, is_light, prims_to_hide
from ..core.lighting import camera_light_switch, current_mode
from ..core.serial import LazyLock, serial
from ._utils import (
    CAMERA_SETTLE_FRAMES,
    _compute_world_bbox,
    _encode_png,
    _get_active_camera_path,
    _get_stage,
    _next_update,
    _reset_renderer,
    _settle_viewport,
)


SEGMENTATION_RETRY_FRAMES = 10

# Held for the whole of every handler that moves the viewport camera, hides prims or captures, so one request never
# sees another's half-done viewport. Not re-entrant: these handlers call _capture_frame, never each other.
_viewport = LazyLock()

_warned: set[str] = set()


def _warn_once(key: str, message: str):
    """Log a warning the first time only, for fallbacks that would otherwise repeat on every call."""
    if key not in _warned:
        _warned.add(key)
        carb.log_warn(message)


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
        import numpy as np
        from PIL import Image
        import io as _io
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


def _viewport_resolution(requested: tuple[int, int]) -> tuple[int, int]:
    """The pixels the viewport renders, which is what a capture gets; the requested size if it can't be read."""
    try:
        import omni.syntheticdata as syn
        from omni.kit.viewport.utility import get_active_viewport

        viewport = get_active_viewport()
        if viewport is not None:
            params = syn.helpers.get_view_params(viewport)
            return int(params["width"]), int(params["height"])
    except Exception as e:
        _warn_once("resolution", f"[MCP Bridge] Could not read the viewport's resolution, framing for "
                                 f"{requested[0]}x{requested[1]} instead: {e}")
    return requested


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

    res_w, res_h = _viewport_resolution((width, height))
    return fit_distance(bounding_radius(dims), fl, h_ap, v_ap, res_w, res_h)


async def _capture_frame(camera_path: str, width: int, height: int) -> tuple[bytes, bool]:
    """Capture a single frame as PNG bytes from the given camera.

    If the first capture is black, automatically resets the renderer
    accumulation and retries once.  This handles the common case where
    the RTX renderer has not yet warmed up after a scene change.

    Returns (png_bytes, is_black).
    """
    import tempfile

    try:
        from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    except ImportError:
        raise RuntimeError("omni.kit.viewport.utility not available")

    viewport = get_active_viewport()
    if viewport is None:
        raise RuntimeError("No active viewport found")

    # Point viewport at the requested camera if different
    current_cam = str(viewport.camera_path)
    changed_camera = camera_path and camera_path != current_cam
    if changed_camera:
        viewport.camera_path = camera_path
        await _next_update()
        await _next_update()

    async def _do_capture() -> tuple[bytes, bool]:
        out_path = os.path.join(tempfile.gettempdir(), f"mcp_capture_{id(viewport)}.png")

        cap = capture_viewport_to_file(viewport, file_path=out_path)
        await cap.wait_for_result()

        # Wait for file to be flushed to disk
        for _ in range(10):
            await _next_update()
            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                break

        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            raise RuntimeError("Viewport capture produced no output")

        with open(out_path, "rb") as f:
            data = f.read()

        try:
            os.unlink(out_path)
        except OSError:
            pass

        return data, _is_image_black(data)

    try:
        png_bytes, is_black = await _do_capture()

        if is_black:
            # First attempt: reset renderer accumulation (fixes stale cache
            # after lighting / variant changes).
            carb.log_info("[MCP Bridge] Black frame detected, resetting renderer")
            await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES)
            png_bytes, is_black = await _do_capture()

        return png_bytes, is_black
    finally:
        # Restore original camera if we changed it
        if changed_camera:
            viewport.camera_path = current_cam


def _compute_screen_bboxes(camera_path: str, img_width: int, img_height: int):
    """Compute screen-space bounding boxes for visible prims using omni.syntheticdata.

    Returns list of {prim_path, type, screen_bbox [x_min, y_min, x_max, y_max],
    world_center, world_dimensions}.
    """
    import numpy as np
    import omni.syntheticdata as syn
    from omni.kit.viewport.utility import get_active_viewport

    viewport = get_active_viewport()
    if viewport is None:
        return []

    vp_params = syn.helpers.get_view_params(viewport)
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

        # 8 corners of world-space bbox
        corners = []
        for i in range(8):
            x = float(max_pt[0]) if (i & 1) else float(min_pt[0])
            y = float(max_pt[1]) if (i & 2) else float(min_pt[1])
            z = float(max_pt[2]) if (i & 4) else float(min_pt[2])
            corners.append([x, y, z])

        pts = np.array(corners, dtype=np.float64)
        projected = syn.helpers.world_to_image(pts, viewport, vp_params)
        # projected is (N, 3): normalized [0,1] coords + depth

        xs = projected[:, 0] * vp_w
        ys = projected[:, 1] * vp_h

        sx_min, sx_max = float(np.min(xs)), float(np.max(xs))
        sy_min, sy_max = float(np.min(ys)), float(np.max(ys))

        # Skip if entirely off-screen
        if sx_max < 0 or sx_min > vp_w or sy_max < 0 or sy_min > vp_h:
            continue

        # Clamp to viewport bounds, then scale to requested output size
        sx_min = max(0.0, sx_min) * img_width / vp_w
        sy_min = max(0.0, sy_min) * img_height / vp_h
        sx_max = min(float(vp_w), sx_max) * img_width / vp_w
        sy_max = min(float(vp_h), sy_max) * img_height / vp_h

        center = [(float(min_pt[i]) + float(max_pt[i])) / 2.0 for i in range(3)]
        dims = [float(max_pt[i]) - float(min_pt[i]) for i in range(3)]

        results.append({
            "prim_path": path_str,
            "type": type_name,
            "screen_bbox": [round(sx_min, 1), round(sy_min, 1),
                            round(sx_max, 1), round(sy_max, 1)],
            "world_center": [round(c, 4) for c in center],
            "world_dimensions": [round(d, 4) for d in dims],
        })

    return results


def _capture_instance_segmentation():
    """Capture instance segmentation: each prim gets a unique color.

    Returns (png_bytes, color_legend) where color_legend maps prim_path -> [R,G,B].
    Uses omni.syntheticdata sensors (synchronous — sensors must already be active).
    """
    import numpy as np
    import omni.syntheticdata as syn
    from omni.kit.viewport.utility import get_active_viewport

    viewport = get_active_viewport()
    if viewport is None:
        return None, {}

    # Get raw instance segmentation (uint32 per pixel)
    seg_array = syn.sensors.get_instance_segmentation(viewport)
    if seg_array is None or seg_array.size == 0:
        # Sensor may not be initialized — try to init and retry once
        try:
            syn.sensors.create_or_retrieve_sensor(
                viewport, syn._syntheticdata.SensorType.InstanceSegmentation
            )
            syn.sensors.enable_sensors(
                viewport, [syn._syntheticdata.SensorType.InstanceSegmentation]
            )
            seg_array = syn.sensors.get_instance_segmentation(viewport)
        except Exception:
            pass
        if seg_array is None or seg_array.size == 0:
            return None, {}

    # Map instance IDs to prim paths
    sd_iface = syn._syntheticdata.acquire_syntheticdata_interface()
    unique_ids = np.unique(seg_array)

    h, w = seg_array.shape[:2]
    color_img = np.zeros((h, w, 3), dtype=np.uint8)
    color_legend = {}  # prim_path -> [R, G, B]
    id_to_color = {}

    for idx, uid in enumerate(unique_ids):
        uid_int = int(uid)
        if uid_int == 0:
            continue  # Background stays black

        # Get prim path for this instance ID
        try:
            prim_path = sd_iface.get_uri_from_instance_segmentation_id(uid_int)
        except Exception:
            prim_path = f"instance_{uid_int}"

        # Generate distinct color using golden-ratio hue spacing
        hue = ((idx * 0.618033988749895) % 1.0)
        h_i = int(hue * 6)
        f = hue * 6 - h_i
        q = int(255 * (1 - f))
        t = int(255 * f)
        if h_i == 0:
            r, g, b = 255, t, 0
        elif h_i == 1:
            r, g, b = q, 255, 0
        elif h_i == 2:
            r, g, b = 0, 255, t
        elif h_i == 3:
            r, g, b = 0, q, 255
        elif h_i == 4:
            r, g, b = t, 0, 255
        else:
            r, g, b = 255, 0, q

        id_to_color[uid_int] = [r, g, b]
        mask = seg_array == uid
        color_img[mask] = [r, g, b]

        # Aggregate by prim path (multiple IDs can map to same prim)
        if prim_path not in color_legend:
            color_legend[prim_path] = [r, g, b]

    png_bytes = _encode_png(color_img)
    return png_bytes, color_legend


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
    await _settle_viewport()

    return {
        "status": "success",
        "result": {"camera_path": camera_path, "position": position, "target": target},
    }


@serial(_viewport)
async def handle_camera_look_at(body: dict) -> dict:
    """Point the camera at a prim from a given distance and angle."""
    prim_path = body.get("prim_path", "")
    distance = body.get("distance", None)  # Auto-compute if not provided
    azimuth = body.get("azimuth", 45.0)  # degrees, 0=front
    elevation = body.get("elevation", 30.0)  # degrees above horizontal

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, _ = _compute_world_bbox(prim)
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
    await _settle_viewport()

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

    Auto-fits camera distance so the prim fills the viewport with ~10px margin.
    Use zoom_offset to adjust: negative=closer, positive=further, 0=auto-fit.
    Use isolate=True to hide all other scene content during capture.
    Optionally includes instance segmentation at each angle.
    """
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}
    try:
        args = inspect_args(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    width, height, zoom_offset, isolate = args.width, args.height, args.zoom_offset, args.isolate

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, _ = _compute_world_bbox(prim)

    # Auto-fit distance, then zoom_offset: 0=auto-fit, negative=closer, positive=further. The fit refuses an
    # orthographic camera, and a frame with no room inside its margins, judged on the resolution actually captured.
    camera_path = _get_active_camera_path()
    try:
        distance = apply_zoom(_compute_autofit_distance(dims, camera_path, stage, width, height), zoom_offset)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    up_axis = UsdGeom.GetStageUpAxis(stage)

    # Isolate: hide everything but the prim and the lights, in the session layer, inside the try so it always undoes
    hidden = Hidden(stage.GetSessionLayer())
    isolate_warnings: list[str] = []
    captures = []
    try:
        if isolate:
            paths, isolate_warnings = prims_to_hide(stage, prim_path)
            hidden.hide(paths)
            isolate_warnings += hidden.warnings
            await _settle_viewport()

        for angle_name, az, el in args.angles:
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

            # Wait for camera transform to propagate to renderer
            await _settle_viewport()

            try:
                png_bytes, is_black = await _capture_frame(camera_path, width, height)
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
                    try:
                        seg_png, legend = _capture_instance_segmentation()
                        if not seg_png:
                            # Sensor may need warmup frames — pump and retry
                            for _ in range(SEGMENTATION_RETRY_FRAMES):
                                await _next_update()
                            seg_png, legend = _capture_instance_segmentation()
                        if seg_png:
                            cap_entry["segmentation_base64"] = base64.b64encode(seg_png).decode("utf-8")
                            cap_entry["segmentation_legend"] = legend
                    except Exception:
                        pass

                captures.append(cap_entry)
            except Exception as e:
                captures.append({
                    "angle": angle_name,
                    "error": str(e),
                })
    finally:
        # Put each hidden prim's session-layer visibility back as it was
        if len(hidden):
            hidden.restore()
            await _settle_viewport()

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "center": center,
            "distance": round(distance, 4),
            "zoom_offset": zoom_offset,
            "isolate": isolate,
            "isolate_warnings": isolate_warnings,
            "lighting_mode": _get_current_lighting_mode(),
            "captures": captures,
        },
    }


@serial(_viewport)
async def handle_capture(body: dict) -> dict:
    width = body.get("width", 1280)
    height = body.get("height", 720)
    camera_path = body.get("camera_path", "")

    await _next_update()

    if not camera_path:
        camera_path = _get_active_camera_path()

    camera_path = str(camera_path)

    try:
        # 1. Capture the viewport image
        png_bytes, is_black = await _capture_frame(camera_path, width, height)
        b64_image = base64.b64encode(png_bytes).decode("utf-8")

        result = {
            "image_base64": b64_image,
            "width": width,
            "height": height,
            "camera_path": camera_path,
            "format": "png",
            "is_black": is_black,
            "lighting_mode": _get_current_lighting_mode(),
        }
        if is_black:
            result["has_scene_lights"] = _has_scene_lights()

        # 2. Compute screen-space bounding boxes for visible prims
        try:
            bboxes = _compute_screen_bboxes(camera_path, width, height)
            result["screen_bboxes"] = bboxes
        except Exception as e:
            carb.log_warn(f"Screen bbox computation failed: {e}")
            result["screen_bboxes"] = []

        # 3. Capture instance segmentation image
        try:
            seg_png, color_legend = _capture_instance_segmentation()
            if not seg_png:
                # Sensor may need warmup frames — pump and retry
                for _ in range(SEGMENTATION_RETRY_FRAMES):
                    await _next_update()
                seg_png, color_legend = _capture_instance_segmentation()
            if seg_png:
                result["segmentation_base64"] = base64.b64encode(seg_png).decode("utf-8")
                result["segmentation_legend"] = color_legend
            else:
                result["segmentation_base64"] = None
                result["segmentation_legend"] = {}
        except Exception as e:
            carb.log_warn(f"Instance segmentation failed: {e}")
            result["segmentation_base64"] = None
            result["segmentation_legend"] = {}

        return {"status": "success", "result": result}
    except Exception as e:
        tb = traceback.format_exc()
        return {"status": "error", "error": str(e), "traceback": tb}


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

    elif action in ("set", "set_camera_light"):
        if action == "set":
            mode = body.get("mode", "")
            available = _get_available_lighting_modes()
            if not mode:
                return {"status": "error", "error": f"mode is required for 'set' action. Available: {', '.join(available)}"}
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
            await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES)
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
