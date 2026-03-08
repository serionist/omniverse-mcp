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
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux

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
    stage = _get_stage()
    for prim in stage.Traverse():
        if prim.IsA(UsdLux.BoundableLightBase) or prim.IsA(UsdLux.NonboundableLightBase):
            return True
        # Fallback: check type name for older USD versions
        type_name = prim.GetTypeName()
        if type_name in ("DistantLight", "DomeLight", "SphereLight", "RectLight",
                         "DiskLight", "CylinderLight"):
            return True
    return False


def _get_camera_light_enabled() -> bool:
    """Check if the viewport camera light is enabled."""
    try:
        settings = carb.settings.get_settings()
        return bool(settings.get("/rtx/useViewLightingMode"))
    except Exception:
        return False


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

        if is_black and not _get_camera_light_enabled():
            # Scene lights alone may not produce visible output immediately
            # in RTX Real-Time mode.  Auto-enable the camera light (a non-
            # destructive viewport fill light) and retry.
            carb.log_info(
                "[MCP Bridge] Still black — auto-enabling camera light"
            )
            settings = carb.settings.get_settings()
            settings.set("/rtx/useViewLightingMode", True)
            # The camera light needs the render pipeline to fully flush.
            # Reset accumulation, then pump extra frames to ensure the
            # light change is reflected in the next capture.
            await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES)
            # Double-capture: first capture flushes the stale render
            # product, second captures the freshly-lit frame.
            await _do_capture()
            await _settle_viewport(CAMERA_SETTLE_FRAMES)
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

    skip_types = {"Camera", "DomeLight", "DistantLight", "Scope", "Shader",
                  "Material", "NodeGraph"}

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


async def handle_camera_inspect(body: dict) -> dict:
    """Orbit-capture: take screenshots from multiple angles around a prim.

    Optionally includes instance segmentation at each angle.
    Uses isaacsim.core.utils.viewports.set_camera_view for reliable camera
    positioning, with a UsdGeom.Xformable fallback for non-Isaac-Sim apps.
    """
    prim_path = body.get("prim_path", "")
    angles = body.get("angles", None)
    width = body.get("width", 800)
    height = body.get("height", 600)
    distance = body.get("distance", None)
    include_segmentation = body.get("include_segmentation", False)

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, _ = _compute_world_bbox(prim)
    max_dim = max(dims) if max(dims) > 0.01 else 1.0
    if distance is None:
        distance = max_dim * 2.5

    # Cube-based angle system: 6 face centers + 8 cube corners = 14 angles.
    # Corners at atan(1/sqrt(2)) ≈ 35.26° elevation.
    CORNER_EL = 35.26
    ANGLE_MAP = {
        # Face centers (6)
        "front":  (0, 0),
        "back":   (180, 0),
        "right":  (90, 0),
        "left":   (270, 0),
        "top":    (0, 90),
        "bottom": (0, -90),
        # Cube corners (8)
        "top_front_right":    (45, CORNER_EL),
        "top_front_left":     (315, CORNER_EL),
        "top_back_right":     (135, CORNER_EL),
        "top_back_left":      (225, CORNER_EL),
        "bottom_front_right": (45, -CORNER_EL),
        "bottom_front_left":  (315, -CORNER_EL),
        "bottom_back_right":  (135, -CORNER_EL),
        "bottom_back_left":   (225, -CORNER_EL),
    }

    ALL_ANGLES = list(ANGLE_MAP.keys())

    if angles is None or angles == ["all"]:
        angles = ALL_ANGLES

    up_axis = UsdGeom.GetStageUpAxis(stage)
    camera_path = _get_active_camera_path()

    captures = []
    for angle_name in angles:
        if angle_name in ANGLE_MAP:
            az, el = ANGLE_MAP[angle_name]
        elif isinstance(angle_name, (list, tuple)) and len(angle_name) == 2:
            az, el = angle_name
        else:
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

        # Wait for camera transform to propagate to renderer
        await _settle_viewport()

        try:
            png_bytes, is_black = await _capture_frame(camera_path, width, height)
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            cap_entry = {
                "angle": angle_name if isinstance(angle_name, str) else f"az{az}_el{el}",
                "azimuth": az,
                "elevation": el,
                "camera_position": [round(v, 4) for v in cam_pos],
                "image_base64": b64,
                "is_black": is_black,
            }

            if include_segmentation:
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
                "angle": angle_name if isinstance(angle_name, str) else f"az{az}_el{el}",
                "error": str(e),
            })

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "center": center,
            "distance": round(distance, 4),
            "captures": captures,
        },
    }


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
        }
        if is_black:
            result["has_scene_lights"] = _has_scene_lights()
            result["camera_light_on"] = _get_camera_light_enabled()

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
    """Get or set viewport lighting state.

    Actions:
      - "get" (default): return current lighting state
      - "set_camera_light": enable/disable viewport camera light
    """
    action = body.get("action", "get")

    if action == "get":
        # Gather lighting state
        camera_light_on = _get_camera_light_enabled()

        # List scene lights
        scene_lights = []
        stage = _get_stage()
        for prim in stage.Traverse():
            type_name = prim.GetTypeName()
            if type_name in ("DistantLight", "DomeLight", "SphereLight", "RectLight",
                             "DiskLight", "CylinderLight"):
                light_info = {"path": str(prim.GetPath()), "type": type_name}
                # Try to get intensity
                intensity_attr = prim.GetAttribute("inputs:intensity")
                if not intensity_attr or not intensity_attr.HasValue():
                    intensity_attr = prim.GetAttribute("intensity")
                if intensity_attr and intensity_attr.HasValue():
                    light_info["intensity"] = float(intensity_attr.Get())
                scene_lights.append(light_info)

        has_lights = len(scene_lights) > 0

        return {
            "status": "success",
            "result": {
                "camera_light_on": camera_light_on,
                "has_scene_lights": has_lights,
                "scene_lights": scene_lights,
            },
        }

    elif action == "set_camera_light":
        enabled = body.get("enabled", True)
        try:
            settings = carb.settings.get_settings()
            settings.set("/rtx/useViewLightingMode", bool(enabled))
            # Reset renderer so the lighting change takes effect immediately
            # instead of being masked by cached frames.
            await _reset_renderer(wait_frames=CAMERA_SETTLE_FRAMES)
            return {
                "status": "success",
                "result": {
                    "camera_light_on": bool(enabled),
                    "message": f"Viewport camera light {'enabled' if enabled else 'disabled'}",
                },
            }
        except Exception as e:
            return {"status": "error", "error": f"Failed to set camera light: {e}"}

    else:
        return {"status": "error", "error": f"Unknown action: {action}. Use 'get' or 'set_camera_light'"}
