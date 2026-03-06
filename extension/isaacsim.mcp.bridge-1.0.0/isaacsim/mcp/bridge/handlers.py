"""
Request handlers for the MCP Bridge HTTP server.

Each handler receives a dict (parsed JSON body) and returns a dict (JSON response).
All handlers run on Isaac Sim's asyncio event loop.
"""

import asyncio
import base64
import io
import json
import math
import os
import struct
import sys
import time
import traceback
import zlib
from typing import Any

import carb
import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stage() -> Usd.Stage:
    ctx = omni.usd.get_context()
    stage = ctx.get_stage()
    if stage is None:
        raise RuntimeError("No USD stage is open")
    return stage


async def _next_update():
    """Wait for next sim update frame to ensure thread safety."""
    await omni.kit.app.get_app().next_update_async()


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
        prec = old_scale_prec if old_scale is not None else UsdGeom.XformOp.PrecisionFloat
        if prec == UsdGeom.XformOp.PrecisionDouble:
            xformable.AddScaleOp(precision=prec).Set(Gf.Vec3d(*scale))
        else:
            xformable.AddScaleOp(precision=prec).Set(Gf.Vec3f(*scale))
    elif old_scale is not None:
        xformable.AddScaleOp(precision=old_scale_prec).Set(old_scale)


def _encode_png(img_array) -> bytes:
    """Encode a numpy array as PNG bytes without requiring PIL."""
    import numpy as np

    if len(img_array.shape) != 3:
        return b""

    h, w, c = img_array.shape
    img = img_array.astype(np.uint8)

    if c == 4:
        img = img[:, :, :3]
        c = 3

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        chunk = chunk_type + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ihdr = make_chunk(b"IHDR", ihdr_data)

    raw_data = b""
    for row in range(h):
        raw_data += b"\x00"
        raw_data += img[row].tobytes()

    compressed = zlib.compress(raw_data)
    idat = make_chunk(b"IDAT", compressed)
    iend = make_chunk(b"IEND", b"")

    return b"\x89PNG\r\n\x1a\n" + ihdr + idat + iend


def _compute_world_bbox(prim) -> tuple[list[float], list[float], list[float]]:
    """Compute world-space bounding box for a prim.

    Returns (center, dimensions, [min_corner, max_corner]).
    """
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    bbox = bbox_cache.ComputeWorldBound(prim)
    box = bbox.ComputeAlignedRange()
    if box.IsEmpty():
        # Fallback to prim world position
        if prim.IsA(UsdGeom.Xformable):
            xf = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            pos = xf.ExtractTranslation()
            center = [float(pos[0]), float(pos[1]), float(pos[2])]
        else:
            center = [0.0, 0.0, 0.0]
        return center, [0.1, 0.1, 0.1], [center, center]

    min_pt = box.GetMin()
    max_pt = box.GetMax()
    center = [(float(min_pt[i]) + float(max_pt[i])) / 2.0 for i in range(3)]
    dims = [float(max_pt[i]) - float(min_pt[i]) for i in range(3)]
    return center, dims, [[float(min_pt[i]) for i in range(3)], [float(max_pt[i]) for i in range(3)]]


async def _capture_frame(camera_path: str, width: int, height: int) -> bytes:
    """Capture a single frame as PNG bytes from the given camera."""
    import os
    import tempfile

    # Use viewport capture utility — works reliably even when sim is stopped
    try:
        from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport
    except ImportError:
        raise RuntimeError("omni.kit.viewport.utility not available")

    viewport = get_active_viewport()
    if viewport is None:
        raise RuntimeError("No active viewport found")

    # Point viewport at the requested camera if different
    current_cam = str(viewport.camera_path)
    if camera_path and camera_path != current_cam:
        viewport.camera_path = camera_path
        await _next_update()
        await _next_update()

    out_path = os.path.join(tempfile.gettempdir(), f"mcp_capture_{id(viewport)}.png")

    cap = capture_viewport_to_file(viewport, file_path=out_path)
    await cap.wait_for_result()

    # Wait for file to be flushed to disk
    for _ in range(10):
        await _next_update()
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            break

    # Restore original camera if we changed it
    if camera_path and camera_path != current_cam:
        viewport.camera_path = current_cam

    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("Viewport capture produced no output")

    with open(out_path, "rb") as f:
        png_bytes = f.read()

    os.unlink(out_path)
    return png_bytes


def _project_world_to_screen(world_points, camera_path: str, img_width: int, img_height: int):
    """Project world-space 3D points to screen-space 2D pixel coordinates.

    Returns list of [px_x, px_y] for each input point, or None if behind camera.
    Uses the camera's view/projection matrices for accurate projection.
    """
    import numpy as np

    stage = _get_stage()
    cam_prim = stage.GetPrimAtPath(camera_path)
    if not cam_prim or not cam_prim.IsValid():
        return None

    camera = UsdGeom.Camera(cam_prim)
    if not camera:
        return None

    # Get camera-to-world transform and invert for world-to-camera
    xformable = UsdGeom.Xformable(cam_prim)
    cam_to_world = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    world_to_cam = cam_to_world.GetInverse()

    # Get camera properties for projection
    gf_camera = camera.GetCamera(Usd.TimeCode.Default())
    frustum = gf_camera.frustum

    results = []
    for wp in world_points:
        world_pt = Gf.Vec3d(wp[0], wp[1], wp[2])

        # Transform to camera space
        cam_pt = world_to_cam.Transform(world_pt)

        # Project using the camera frustum
        try:
            screen_pt = frustum.ComputeProjectedPoint(cam_pt)
        except Exception:
            results.append(None)
            continue

        # screen_pt is in NDC [-1, 1] range — convert to pixel coordinates
        px_x = (screen_pt[0] * 0.5 + 0.5) * img_width
        px_y = (1.0 - (screen_pt[1] * 0.5 + 0.5)) * img_height

        # Check if behind camera (negative z in camera space means in front)
        # Camera looks down -Z in USD convention
        if cam_pt[2] > 0:
            results.append(None)  # Behind camera
        else:
            results.append([round(px_x, 1), round(px_y, 1)])

    return results


def _compute_screen_bboxes(camera_path: str, img_width: int, img_height: int):
    """Compute screen-space bounding boxes for all visible prims.

    Returns list of {prim_path, type, screen_bbox [x_min, y_min, x_max, y_max],
    world_center, world_dimensions}.
    """
    import numpy as np

    stage = _get_stage()
    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    results = []

    skip_types = {"Camera", "DomeLight", "DistantLight", "Scope", "Shader", "Material", "NodeGraph"}

    for prim in stage.Traverse():
        path_str = str(prim.GetPath())

        # Skip internal/hidden prims
        if path_str.startswith("/OmniverseKit") or path_str.startswith("/Render"):
            continue

        type_name = prim.GetTypeName()
        if type_name in skip_types:
            continue

        # Skip invisible prims
        if prim.IsA(UsdGeom.Imageable):
            vis = UsdGeom.Imageable(prim).ComputeVisibility(Usd.TimeCode.Default())
            if vis == UsdGeom.Tokens.invisible:
                continue

        # Compute world-space bbox
        bbox = bbox_cache.ComputeWorldBound(prim)
        box = bbox.ComputeAlignedRange()
        if box.IsEmpty():
            continue

        min_pt = box.GetMin()
        max_pt = box.GetMax()

        # Get 8 corners of the world-space bounding box
        corners = []
        for i in range(8):
            x = float(max_pt[0]) if (i & 1) else float(min_pt[0])
            y = float(max_pt[1]) if (i & 2) else float(min_pt[1])
            z = float(max_pt[2]) if (i & 4) else float(min_pt[2])
            corners.append([x, y, z])

        projected = _project_world_to_screen(corners, camera_path, img_width, img_height)
        if projected is None:
            continue

        # Filter out None (behind camera) and compute screen bbox
        valid = [p for p in projected if p is not None]
        if not valid:
            continue

        xs = [p[0] for p in valid]
        ys = [p[1] for p in valid]
        sx_min, sx_max = min(xs), max(xs)
        sy_min, sy_max = min(ys), max(ys)

        # Skip if entirely off-screen
        if sx_max < 0 or sx_min > img_width or sy_max < 0 or sy_min > img_height:
            continue

        # Clamp to image bounds
        sx_min = max(0, round(sx_min, 1))
        sy_min = max(0, round(sy_min, 1))
        sx_max = min(img_width, round(sx_max, 1))
        sy_max = min(img_height, round(sy_max, 1))

        center = [(float(min_pt[i]) + float(max_pt[i])) / 2.0 for i in range(3)]
        dims = [float(max_pt[i]) - float(min_pt[i]) for i in range(3)]

        results.append({
            "prim_path": path_str,
            "type": type_name,
            "screen_bbox": [sx_min, sy_min, sx_max, sy_max],
            "world_center": [round(c, 4) for c in center],
            "world_dimensions": [round(d, 4) for d in dims],
        })

    return results


async def _capture_instance_segmentation(camera_path: str, width: int, height: int):
    """Capture instance segmentation image where each prim has a unique color.

    Returns (png_bytes, id_to_labels) where id_to_labels maps color IDs to prim paths.
    """
    import numpy as np

    try:
        import omni.syntheticdata as syn
        from omni.kit.viewport.utility import get_active_viewport
    except ImportError:
        return None, {}

    viewport = get_active_viewport()
    if viewport is None:
        return None, {}

    # Point viewport at the requested camera if different
    current_cam = str(viewport.camera_path)
    if camera_path and camera_path != current_cam:
        viewport.camera_path = camera_path
        await _next_update()
        await _next_update()

    try:
        # Initialize the instance segmentation sensor
        sensor_type = syn._syntheticdata.SensorType.InstanceSegmentation
        await syn.sensors.create_or_retrieve_sensor_async(viewport, sensor_type)
        await _next_update()
        await syn.sensors.next_sensor_data_async(viewport, True)
        await _next_update()

        # Get the segmentation data with prim path mapping
        data = syn.sensors.get_instance_segmentation(
            viewport, parsed=True, return_mapping=True
        )

        if isinstance(data, tuple) and len(data) == 2:
            seg_array, mapping = data
        else:
            seg_array = data
            mapping = {}

        # seg_array is uint32 (height, width) with instance IDs per pixel
        # Convert to a colorized RGB image: deterministic color per ID
        unique_ids = np.unique(seg_array)
        h, w = seg_array.shape[:2]
        color_img = np.zeros((h, w, 3), dtype=np.uint8)

        id_to_color = {}
        id_to_labels = {}

        for idx, uid in enumerate(unique_ids):
            uid_int = int(uid)
            if uid_int == 0:
                # Background — keep black
                id_to_color[uid_int] = [0, 0, 0]
                id_to_labels[uid_int] = "BACKGROUND"
                continue

            # Generate a distinct, saturated color from the ID
            # Use golden-ratio hue spacing for visual distinction
            hue = ((idx * 0.618033988749895) % 1.0)
            # HSV to RGB with full saturation and value
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

            # Extract label from mapping if available
            if isinstance(mapping, dict):
                label_info = mapping.get(uid_int, mapping.get(str(uid_int), {}))
                if isinstance(label_info, dict):
                    id_to_labels[uid_int] = label_info.get("prim_path", label_info.get("name", f"instance_{uid_int}"))
                elif isinstance(label_info, str):
                    id_to_labels[uid_int] = label_info
                else:
                    id_to_labels[uid_int] = f"instance_{uid_int}"
            else:
                id_to_labels[uid_int] = f"instance_{uid_int}"

        png_bytes = _encode_png(color_img)

        # Build color legend: map prim path -> RGB color
        color_legend = {}
        for uid_int, label in id_to_labels.items():
            if uid_int == 0:
                continue
            color = id_to_color.get(uid_int, [128, 128, 128])
            color_legend[label] = color

    except Exception as e:
        carb.log_warn(f"Instance segmentation failed: {e}")
        # Restore camera and return None — caller handles gracefully
        if camera_path and camera_path != current_cam:
            viewport.camera_path = current_cam
        return None, {}

    # Restore camera
    if camera_path and camera_path != current_cam:
        viewport.camera_path = current_cam

    return png_bytes, color_legend


# ---------------------------------------------------------------------------
# Global recording state
# ---------------------------------------------------------------------------

_recording_state = {
    "active": False,
    "session_id": None,
    "output_dir": None,
    "frame_count": 0,
    "fps": 5,
    "width": 640,
    "height": 480,
    "camera_path": "",
    "start_time": 0.0,
    "metadata": [],
    "callback_name": None,
    "_step_counter": 0,
    "_steps_per_frame": 1,
}


# =========================================================================
# HANDLER IMPLEMENTATIONS
# =========================================================================


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

async def handle_health(_body: dict) -> dict:
    stage = _get_stage()
    ext_mgr = omni.kit.app.get_app().get_extension_manager()
    return {
        "status": "success",
        "result": {
            "stage_path": stage.GetRootLayer().realPath or "(unsaved)",
            "up_axis": UsdGeom.GetStageUpAxis(stage),
            "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
            "recording_active": _recording_state["active"],
        },
    }


# ---------------------------------------------------------------------------
# /execute
# ---------------------------------------------------------------------------

async def handle_execute(body: dict) -> dict:
    code = body.get("code", "")
    if not code.strip():
        return {"status": "error", "error": "No code provided"}

    await _next_update()

    old_stdout, old_stderr = sys.stdout, sys.stderr
    captured_out = io.StringIO()
    captured_err = io.StringIO()
    sys.stdout = captured_out
    sys.stderr = captured_err

    local_ns: dict[str, Any] = {
        "omni": omni,
        "carb": carb,
        "Usd": Usd,
        "UsdGeom": UsdGeom,
        "UsdLux": UsdLux,
        "UsdPhysics": UsdPhysics,
        "Sdf": Sdf,
        "Gf": Gf,
    }

    error = None
    tb = None
    try:
        exec(code, local_ns)
    except Exception as e:
        error = str(e)
        tb = traceback.format_exc()
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr

    stdout_text = captured_out.getvalue()
    stderr_text = captured_err.getvalue()

    script_result = local_ns.get("result", None)
    if script_result is not None:
        try:
            json.dumps(script_result)
        except (TypeError, ValueError):
            script_result = str(script_result)

    if error:
        return {
            "status": "error",
            "error": error,
            "traceback": tb,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }

    return {
        "status": "success",
        "result": {
            "stdout": stdout_text,
            "stderr": stderr_text,
            "return_value": script_result,
        },
    }


# ---------------------------------------------------------------------------
# /scene/tree
# ---------------------------------------------------------------------------

async def handle_scene_tree(body: dict) -> dict:
    root_path = body.get("root", "/")
    max_depth = body.get("max_depth", 8)
    include_properties = body.get("include_properties", False)
    fmt = body.get("format", "json")  # "json" or "text"

    stage = _get_stage()
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {root_path}"}

    if fmt == "text":
        # Lightweight prim-block text: path + type + position only (no full properties)
        from .formatter import format_value
        lines = []
        prim_count = 0
        def _walk_text(prim, depth):
            nonlocal prim_count
            if depth > max_depth:
                child_count = len(prim.GetChildren())
                if child_count > 0:
                    lines.append(f"[{prim.GetPath()}]")
                    lines.append(f"type = {prim.GetTypeName() or 'Xform'}")
                    lines.append(f"children = {child_count} (truncated)")
                    lines.append("")
                return
            prim_count += 1
            block = [f"[{prim.GetPath()}]"]
            block.append(f"type = {prim.GetTypeName() or 'Xform'}")
            if prim.IsA(UsdGeom.Xformable):
                xf = UsdGeom.Xformable(prim)
                t = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
                block.append(f"pos = {float(t[0]):.4f}, {float(t[1]):.4f}, {float(t[2]):.4f}")
            if include_properties:
                for prop in prim.GetProperties():
                    try:
                        val = prop.Get()
                        if val is not None:
                            block.append(f"{prop.GetName()} = {format_value(val)}")
                    except Exception:
                        pass
            lines.append("\n".join(block))
            lines.append("")
            for child in prim.GetChildren():
                _walk_text(child, depth + 1)

        lines.append(f"# scene_tree root={root_path} up_axis={UsdGeom.GetStageUpAxis(stage)}")
        lines.append("")
        _walk_text(root_prim, 0)
        text = "\n".join(lines)
        return {"status": "success", "result": {"text": text, "prim_count": prim_count}}

    def _build_tree(prim: Usd.Prim, depth: int) -> dict:
        node: dict[str, Any] = {
            "path": str(prim.GetPath()),
            "type": prim.GetTypeName() or "Xform",
        }

        if prim.IsA(UsdGeom.Xformable):
            xformable = UsdGeom.Xformable(prim)
            local_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            translate = local_xform.ExtractTranslation()
            node["world_position"] = [round(translate[0], 4), round(translate[1], 4), round(translate[2], 4)]

        if include_properties:
            props = {}
            for prop in prim.GetProperties():
                try:
                    props[prop.GetName()] = _serialize_value(prop.Get())
                except Exception:
                    props[prop.GetName()] = "<unreadable>"
            node["properties"] = props

        if depth < max_depth:
            children = []
            for child in prim.GetChildren():
                children.append(_build_tree(child, depth + 1))
            if children:
                node["children"] = children
        else:
            child_count = len(prim.GetChildren())
            if child_count > 0:
                node["children_count"] = child_count
                node["truncated"] = True

        return node

    tree = _build_tree(root_prim, 0)
    return {"status": "success", "result": tree}


# ---------------------------------------------------------------------------
# /scene/dump  (writes full scene to file, returns file path)
# ---------------------------------------------------------------------------

async def handle_scene_dump(body: dict) -> dict:
    output_dir = body.get("output_dir", "")
    root_path = body.get("root", "/")
    max_depth = body.get("max_depth", 15)
    include_properties = body.get("include_properties", True)
    filter_types = body.get("filter_types", [])  # e.g. ["Mesh", "Xform"]
    property_filter = body.get("property_filter", [])  # e.g. ["joint", "position"]

    if not output_dir:
        return {"status": "error", "error": "No output_dir provided"}

    os.makedirs(output_dir, exist_ok=True)

    stage = _get_stage()
    root_prim = stage.GetPrimAtPath(root_path)
    if not root_prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {root_path}"}

    from .formatter import format_scene_dump
    text = format_scene_dump(
        stage, root_path, max_depth,
        include_properties=include_properties,
        include_bounds=True,
        filter_types=filter_types or None,
        property_filter=property_filter or None,
    )

    file_path = os.path.join(output_dir, "scene_dump.txt")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    file_size = os.path.getsize(file_path)
    prim_count = sum(1 for _ in stage.Traverse())

    return {
        "status": "success",
        "result": {
            "file_path": file_path,
            "file_size_bytes": file_size,
            "prim_count": prim_count,
            "root": root_path,
        },
    }


# ---------------------------------------------------------------------------
# /scene/prim
# ---------------------------------------------------------------------------

async def handle_prim_properties(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    fmt = body.get("format", "json")  # "json" or "text"
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    if fmt == "text":
        from .formatter import format_prim_block
        text = format_prim_block(prim, include_properties=True,
                                 include_transform=True, include_bounds=True)
        return {"status": "success", "result": {"text": text, "prim_path": prim_path}}

    props = {}
    for prop in prim.GetProperties():
        try:
            props[prop.GetName()] = _serialize_value(prop.Get())
        except Exception:
            props[prop.GetName()] = "<unreadable>"

    result: dict[str, Any] = {
        "prim_path": prim_path,
        "type": prim.GetTypeName(),
        "is_active": prim.IsActive(),
        "properties": props,
    }

    if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
        result["is_articulation_root"] = True

    try:
        center, dims, corners = _compute_world_bbox(prim)
        result["bbox_center"] = center
        result["bbox_dimensions"] = dims
        result["bbox_min"] = corners[0]
        result["bbox_max"] = corners[1]
    except Exception:
        pass

    return {"status": "success", "result": result}


# ---------------------------------------------------------------------------
# /scene/bounds
# ---------------------------------------------------------------------------

async def handle_prim_bounds(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    center, dims, corners = _compute_world_bbox(prim)
    max_dim = max(dims)
    diagonal = math.sqrt(sum(d * d for d in dims))

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "center": center,
            "dimensions": dims,
            "min": corners[0],
            "max": corners[1],
            "max_dimension": round(max_dim, 4),
            "diagonal": round(diagonal, 4),
        },
    }


# ---------------------------------------------------------------------------
# /scene/transform
# ---------------------------------------------------------------------------

async def handle_transform(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}
    if not prim.IsA(UsdGeom.Xformable):
        return {"status": "error", "error": f"Prim is not transformable: {prim_path}"}

    await _next_update()
    _apply_xform(prim, body.get("position"), body.get("rotation"), body.get("scale"))

    return {
        "status": "success",
        "result": {"prim_path": prim_path, "message": "Transform updated"},
    }


# ---------------------------------------------------------------------------
# /scene/create
# ---------------------------------------------------------------------------

async def handle_create_prim(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    prim_type = body.get("prim_type", "Xform")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    await _next_update()
    stage = _get_stage()

    usd_path = body.get("usd_path")
    if usd_path:
        prim = stage.DefinePrim(prim_path)
        prim.GetReferences().AddReference(usd_path)
    else:
        prim = stage.DefinePrim(prim_path, prim_type)

    if not prim.IsValid():
        return {"status": "error", "error": f"Failed to create prim at {prim_path}"}

    _apply_xform(prim, body.get("position"), body.get("rotation"), body.get("scale"))

    if body.get("enable_physics", False):
        UsdPhysics.RigidBodyAPI.Apply(prim)
        UsdPhysics.CollisionAPI.Apply(prim)

    return {
        "status": "success",
        "result": {"prim_path": str(prim.GetPath()), "type": prim.GetTypeName()},
    }


# ---------------------------------------------------------------------------
# /scene/delete
# ---------------------------------------------------------------------------

async def handle_delete_prim(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    await _next_update()
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    stage.RemovePrim(prim_path)
    return {
        "status": "success",
        "result": {"prim_path": prim_path, "message": "Prim deleted"},
    }


# ---------------------------------------------------------------------------
# /scene/material
# ---------------------------------------------------------------------------

def _ensure_material(stage, mat_path: str):
    """Get or create an OmniPBR material at the given path. Returns (material, shader)."""
    prim = stage.GetPrimAtPath(mat_path)
    if prim.IsValid():
        mat = UsdShade.Material(prim)
        shader = UsdShade.Shader(stage.GetPrimAtPath(f"{mat_path}/Shader"))
        if mat and shader:
            return mat, shader

    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    shader.CreateIdAttr("OmniPBR")

    # Wire shader output to material surface
    shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "out")

    return mat, shader


async def handle_set_material(body: dict) -> dict:
    """Apply a PBR material to a prim.

    Body params:
        prim_path: str          - target prim
        color: [r, g, b]        - diffuse color (0-1 floats or 0-255 ints)
        opacity: float           - 0.0 (transparent) to 1.0 (opaque), default 1.0
        roughness: float         - 0.0 (glossy) to 1.0 (rough), default 0.5
        metallic: float          - 0.0 (dielectric) to 1.0 (metal), default 0.0
        material_path: str       - custom material prim path (auto-generated if omitted)
    """
    prim_path = body.get("prim_path", "")
    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    color = body.get("color")
    if not color or len(color) != 3:
        return {"status": "error", "error": "color must be [r, g, b] with 3 values"}

    # Normalize color to 0-1 range
    r, g, b = [float(c) for c in color]
    if r > 1.0 or g > 1.0 or b > 1.0:
        r, g, b = r / 255.0, g / 255.0, b / 255.0

    opacity = float(body.get("opacity", 1.0))
    roughness = float(body.get("roughness", 0.5))
    metallic = float(body.get("metallic", 0.0))

    await _next_update()
    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    # Create material under /World/Looks/<PrimName>_Mat
    prim_name = prim_path.rstrip("/").split("/")[-1]
    mat_path = body.get("material_path", "")
    if not mat_path:
        mat_path = f"/World/Looks/{prim_name}_Mat"

    mat, shader = _ensure_material(stage, mat_path)

    # Set PBR properties
    shader.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(r, g, b))
    shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(metallic)

    if opacity < 1.0:
        shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(True)
        shader.CreateInput("opacity_constant", Sdf.ValueTypeNames.Float).Set(opacity)

    # Bind material to the target prim
    UsdShade.MaterialBindingAPI.Apply(prim)
    UsdShade.MaterialBindingAPI(prim).Bind(mat)

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "material_path": mat_path,
            "color": [r, g, b],
            "opacity": opacity,
            "roughness": roughness,
            "metallic": metallic,
        },
    }


# ---------------------------------------------------------------------------
# /scene/clone
# ---------------------------------------------------------------------------

async def handle_clone_prim(body: dict) -> dict:
    """Clone a prim (deep copy). Optionally create multiple copies with offset."""
    source_path = body.get("source_path", "")
    target_path = body.get("target_path", "")
    count = body.get("count", 1)
    offset = body.get("offset", None)  # [x, y, z] per-copy offset

    if not source_path:
        return {"status": "error", "error": "No source_path provided"}
    if not target_path:
        return {"status": "error", "error": "No target_path provided"}

    await _next_update()
    stage = _get_stage()
    source_prim = stage.GetPrimAtPath(source_path)
    if not source_prim.IsValid():
        return {"status": "error", "error": f"Source prim not found: {source_path}"}

    src_layer = stage.GetRootLayer()
    created = []
    for i in range(count):
        dest_path = target_path if count == 1 else f"{target_path}_{i + 1:03d}"
        if not Sdf.CopySpec(src_layer, source_path, src_layer, dest_path):
            return {"status": "error", "error": f"Failed to clone to {dest_path}"}
        if offset and i > 0:
            dest_prim = stage.GetPrimAtPath(dest_path)
            if dest_prim.IsValid() and dest_prim.IsA(UsdGeom.Xformable):
                xf = UsdGeom.Xformable(dest_prim)
                cur = [0.0, 0.0, 0.0]
                for op in xf.GetOrderedXformOps():
                    if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                        v = op.Get()
                        cur = [float(v[0]), float(v[1]), float(v[2])]
                        break
                _apply_xform(dest_prim, position=[cur[j] + offset[j] * i for j in range(3)])
        created.append(dest_path)

    return {
        "status": "success",
        "result": {"source": source_path, "clones": created, "count": len(created)},
    }


# ---------------------------------------------------------------------------
# /scene/visibility
# ---------------------------------------------------------------------------

async def handle_set_visibility(body: dict) -> dict:
    prim_path = body.get("prim_path", "")
    visible = body.get("visible", True)

    if not prim_path:
        return {"status": "error", "error": "No prim_path provided"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    imageable = UsdGeom.Imageable(prim)
    if not imageable:
        return {"status": "error", "error": f"Prim is not imageable: {prim_path}"}

    if visible:
        imageable.MakeVisible()
    else:
        imageable.MakeInvisible()

    return {"status": "success", "result": {"prim_path": prim_path, "visible": visible}}


# ---------------------------------------------------------------------------
# /scene/save
# ---------------------------------------------------------------------------

async def handle_save_scene(body: dict) -> dict:
    file_path = body.get("file_path", "")

    await _next_update()
    stage = _get_stage()

    if file_path:
        stage.GetRootLayer().Export(file_path)
        return {"status": "success", "result": {"file_path": file_path, "action": "save_as"}}

    current_path = stage.GetRootLayer().realPath
    if not current_path:
        return {"status": "error", "error": "No file path set. Provide file_path for save-as."}
    stage.GetRootLayer().Save()
    return {"status": "success", "result": {"file_path": current_path, "action": "save"}}


# ---------------------------------------------------------------------------
# /scene/new
# ---------------------------------------------------------------------------

async def handle_new_scene(_body: dict) -> dict:
    await _next_update()
    ctx = omni.usd.get_context()
    result, error = await ctx.new_stage_async()
    if not result:
        return {"status": "error", "error": f"Failed to create new scene: {error}"}

    await _next_update()
    await _next_update()

    stage = _get_stage()
    world = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(world)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)

    return {"status": "success", "result": {"message": "New scene created", "default_prim": "/World"}}


# ---------------------------------------------------------------------------
# /robot/create
# ---------------------------------------------------------------------------

ROBOT_ASSETS = {
    "franka": "/Isaac/Robots/FrankaEmika/panda_arm.usd",
    "ur10": "/Isaac/Robots/UniversalRobots/ur10/ur10.usd",
    "carter": "/Isaac/Robots/Carter/carter_v2.usd",
    "jetbot": "/Isaac/Robots/Jetbot/jetbot.usd",
    "g1": "/Isaac/Robots/Unitree/G1/g1.usd",
    "go1": "/Isaac/Robots/Unitree/Go1/go1.usd",
    "go2": "/Isaac/Robots/Unitree/Go2/go2.usd",
    "h1": "/Isaac/Robots/Unitree/H1/h1.usd",
    "spot": "/Isaac/Robots/BostonDynamics/Spot/spot.usd",
    "anymal": "/Isaac/Robots/ANYbotics/anymal_c.usd",
}


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

    _apply_xform(prim, position, body.get("rotation"))

    joint_info = []
    for desc_prim in Usd.PrimRange(prim):
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

    for desc in Usd.PrimRange(prim):
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

_articulation_cache: dict[str, Any] = {}

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
    for desc in Usd.PrimRange(prim):
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
        timeline.pause()
        await _next_update()

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
    prim_count = sum(1 for _ in stage.Traverse())

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
            "recording_active": _recording_state["active"],
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


# ---------------------------------------------------------------------------
# /debug/draw
# ---------------------------------------------------------------------------

async def handle_draw_debug(body: dict) -> dict:
    """Draw debug primitives (lines, spheres, points) in the viewport."""
    draw_type = body.get("type", "line")
    color = body.get("color", [1, 0, 0])
    duration = body.get("duration", 5.0)

    r, g, b = [float(c) for c in color[:3]]
    color_uint = (255 << 24) | (int(r * 255) << 16) | (int(g * 255) << 8) | int(b * 255)

    try:
        from omni.debugdraw import _debugDraw
        draw = _debugDraw.acquire_debug_draw_interface()
    except ImportError:
        return {"status": "error", "error": "omni.debugdraw not available. Enable the extension."}

    drawn = []

    if draw_type == "line":
        start = body.get("start")
        end = body.get("end")
        if not start or not end:
            return {"status": "error", "error": "start and end required for line"}
        draw.draw_line(carb.Float3(*start), color_uint, carb.Float3(*end), color_uint)
        drawn.append({"type": "line", "start": start, "end": end})

    elif draw_type == "sphere":
        center = body.get("center")
        radius = body.get("radius", 0.1)
        if not center:
            return {"status": "error", "error": "center required for sphere"}
        # Approximate sphere with crossing lines
        for axis in range(3):
            s = list(center)
            e = list(center)
            s[axis] -= radius
            e[axis] += radius
            draw.draw_line(carb.Float3(*s), color_uint, carb.Float3(*e), color_uint)
        drawn.append({"type": "sphere", "center": center, "radius": radius})

    elif draw_type == "point":
        position = body.get("position")
        size = body.get("size", 0.05)
        if not position:
            return {"status": "error", "error": "position required for point"}
        for axis in range(3):
            s = list(position)
            e = list(position)
            s[axis] -= size
            e[axis] += size
            draw.draw_line(carb.Float3(*s), color_uint, carb.Float3(*e), color_uint)
        drawn.append({"type": "point", "position": position})

    elif draw_type == "points":
        points = body.get("points", [])
        pt_size = body.get("size", 0.05)
        if not points:
            return {"status": "error", "error": "points list required for points"}
        for pt in points:
            for axis in range(3):
                s = list(pt)
                e = list(pt)
                s[axis] -= pt_size
                e[axis] += pt_size
                draw.draw_line(carb.Float3(*s), color_uint, carb.Float3(*e), color_uint)
            drawn.append({"type": "point", "position": pt})

    elif draw_type == "lines":
        points = body.get("points", [])
        if len(points) < 2:
            return {"status": "error", "error": "At least 2 points needed for lines"}
        for i in range(len(points) - 1):
            draw.draw_line(
                carb.Float3(*points[i]), color_uint,
                carb.Float3(*points[i + 1]), color_uint,
            )
        drawn.append({"type": "lines", "segments": len(points) - 1})

    return {"status": "success", "result": {"drawn": drawn}}


# ---------------------------------------------------------------------------
# /camera/set
# ---------------------------------------------------------------------------

async def handle_camera_set(body: dict) -> dict:
    """Set the viewport camera position and target."""
    position = body.get("position")
    target = body.get("target")

    if position is None:
        return {"status": "error", "error": "position is required ([x, y, z])"}

    await _next_update()

    try:
        from omni.kit.viewport.utility import get_active_viewport
        viewport = get_active_viewport()
        camera_path = str(viewport.camera_path) if viewport else "/OmniverseKit_Persp"
    except ImportError:
        camera_path = "/OmniverseKit_Persp"

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
        _apply_xform(cam_prim, position=position)

    await _next_update()

    return {
        "status": "success",
        "result": {"camera_path": camera_path, "position": position, "target": target},
    }


# ---------------------------------------------------------------------------
# /camera/look_at
# ---------------------------------------------------------------------------

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
        try:
            from omni.kit.viewport.utility import get_active_viewport
            viewport = get_active_viewport()
            camera_path = str(viewport.camera_path) if viewport else "/OmniverseKit_Persp"
        except ImportError:
            camera_path = "/OmniverseKit_Persp"

        set_camera_view(eye=cam_pos, target=center, camera_prim_path=camera_path)
    except ImportError:
        # Fallback: manually set transform
        camera_path = "/OmniverseKit_Persp"
        cam_prim = stage.GetPrimAtPath(camera_path)
        if cam_prim.IsValid():
            xformable = UsdGeom.Xformable(cam_prim)
            xformable.ClearXformOpOrder()
            xformable.AddTranslateOp().Set(Gf.Vec3d(*cam_pos))

    await _next_update()

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


# ---------------------------------------------------------------------------
# /camera/inspect
# ---------------------------------------------------------------------------

async def handle_camera_inspect(body: dict) -> dict:
    """Orbit-capture: take screenshots from multiple angles around a prim."""
    prim_path = body.get("prim_path", "")
    angles = body.get("angles", ["front", "right", "back", "left", "top"])
    width = body.get("width", 800)
    height = body.get("height", 600)
    distance = body.get("distance", None)

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

    ANGLE_MAP = {
        "front": (0, 20),
        "right": (90, 20),
        "back": (180, 20),
        "left": (270, 20),
        "top": (0, 80),
        "front_high": (0, 45),
        "perspective": (45, 30),
    }

    up_axis = UsdGeom.GetStageUpAxis(stage)
    try:
        from omni.kit.viewport.utility import get_active_viewport
        viewport = get_active_viewport()
        camera_path = str(viewport.camera_path) if viewport else "/OmniverseKit_Persp"
    except ImportError:
        camera_path = "/OmniverseKit_Persp"

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

        try:
            from isaacsim.core.utils.viewports import set_camera_view
            set_camera_view(eye=cam_pos, target=center, camera_prim_path=camera_path)
        except ImportError:
            pass

        # Let viewport settle after camera move
        for _ in range(3):
            await _next_update()

        try:
            png_bytes = await _capture_frame(camera_path, width, height)
            b64 = base64.b64encode(png_bytes).decode("utf-8")
            captures.append({
                "angle": angle_name if isinstance(angle_name, str) else f"az{az}_el{el}",
                "azimuth": az,
                "elevation": el,
                "camera_position": [round(v, 4) for v in cam_pos],
                "image_base64": b64,
            })
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


# ---------------------------------------------------------------------------
# /sim/capture
# ---------------------------------------------------------------------------

async def handle_capture(body: dict) -> dict:
    width = body.get("width", 1280)
    height = body.get("height", 720)
    camera_path = body.get("camera_path", "")

    await _next_update()

    if not camera_path:
        try:
            from omni.kit.viewport.utility import get_active_viewport
            viewport = get_active_viewport()
            camera_path = str(viewport.camera_path) if viewport else "/OmniverseKit_Persp"
        except ImportError:
            camera_path = "/OmniverseKit_Persp"

    camera_path = str(camera_path)

    try:
        # 1. Capture the viewport image
        png_bytes = await _capture_frame(camera_path, width, height)
        b64_image = base64.b64encode(png_bytes).decode("utf-8")

        result = {
            "image_base64": b64_image,
            "width": width,
            "height": height,
            "camera_path": camera_path,
            "format": "png",
        }

        # 2. Compute screen-space bounding boxes for visible prims
        try:
            bboxes = _compute_screen_bboxes(camera_path, width, height)
            result["screen_bboxes"] = bboxes
        except Exception as e:
            carb.log_warn(f"Screen bbox computation failed: {e}")
            result["screen_bboxes"] = []

        # 3. Capture instance segmentation image
        try:
            seg_png, color_legend = await _capture_instance_segmentation(
                camera_path, width, height
            )
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


# ---------------------------------------------------------------------------
# /recording/start
# ---------------------------------------------------------------------------

async def handle_recording_start(body: dict) -> dict:
    global _recording_state

    if _recording_state["active"]:
        return {"status": "error", "error": "Recording already active. Stop it first."}

    output_dir = body.get("output_dir", "")
    fps = body.get("fps", 5)
    width = body.get("width", 640)
    height = body.get("height", 480)
    camera_path = body.get("camera_path", "")
    track_prims = body.get("track_prims", [])
    property_filter = body.get("property_filter", None)

    if not output_dir:
        return {"status": "error", "error": "output_dir is required"}

    if not camera_path:
        try:
            from omni.kit.viewport.utility import get_active_viewport
            viewport = get_active_viewport()
            camera_path = str(viewport.camera_path) if viewport else "/OmniverseKit_Persp"
        except ImportError:
            camera_path = "/OmniverseKit_Persp"

    session_id = f"rec_{int(time.time())}"
    session_dir = os.path.join(output_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    timeline = omni.timeline.get_timeline_interface()
    sim_fps = timeline.get_time_codes_per_seconds() or 60.0
    steps_per_frame = max(1, int(sim_fps / fps))

    # Resolve tracked prims (expand to include descendants)
    tracked_prim_paths = []
    if track_prims:
        stage = _get_stage()
        if stage:
            from pxr import Usd
            for path in track_prims:
                root = stage.GetPrimAtPath(path)
                if root.IsValid():
                    for p in Usd.PrimRange(root):
                        tracked_prim_paths.append(str(p.GetPath()))

    _recording_state.update({
        "active": True,
        "session_id": session_id,
        "output_dir": session_dir,
        "frame_count": 0,
        "fps": fps,
        "width": width,
        "height": height,
        "camera_path": camera_path,
        "start_time": time.time(),
        "metadata": [],
        "_step_counter": 0,
        "_steps_per_frame": steps_per_frame,
        "track_prims": tracked_prim_paths,
        "property_filter": property_filter,
    })

    # Write state file header if tracking prims
    if tracked_prim_paths:
        state_path = os.path.join(session_dir, "state.txt")
        with open(state_path, "w") as f:
            f.write(f"# Isaac Sim MCP Recording State\n")
            f.write(f"# format = isaacsim-mcp-v1\n")
            f.write(f"# session = {session_id}\n")
            f.write(f"# fps = {fps}\n")
            f.write(f"# tracked_prims = {len(tracked_prim_paths)}\n")
            if property_filter:
                f.write(f"# property_filter = {', '.join(property_filter)}\n")
            f.write(f"# track_roots = {', '.join(track_prims)}\n")
            f.write(f"\n")

    # Register a physics callback to capture frames
    callback_name = f"mcp_recording_{session_id}"
    _recording_state["callback_name"] = callback_name

    async def _record_tick():
        """Called from the app update loop to capture frames."""
        if not _recording_state["active"]:
            return

        _recording_state["_step_counter"] += 1
        if _recording_state["_step_counter"] % _recording_state["_steps_per_frame"] != 0:
            return

        frame_idx = _recording_state["frame_count"]
        try:
            import tempfile
            from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

            viewport = get_active_viewport()
            if viewport is None:
                return

            # Capture to temp file, then move to final location
            tmp_path = os.path.join(tempfile.gettempdir(), f"mcp_rec_{frame_idx}.png")
            cap = capture_viewport_to_file(viewport, file_path=tmp_path)
            await cap.wait_for_result()

            # Wait for file flush
            for _ in range(10):
                await _next_update()
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    break

            frame_path = os.path.join(
                _recording_state["output_dir"],
                f"frame_{frame_idx:05d}.png",
            )

            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                import shutil
                shutil.move(tmp_path, frame_path)
            else:
                # File not ready — write empty marker
                with open(frame_path, "wb") as f:
                    pass

            timeline = omni.timeline.get_timeline_interface()
            # get_current_time() already returns seconds in Isaac Sim 5.1
            sim_time_seconds = timeline.get_current_time()

            _recording_state["metadata"].append({
                "frame": frame_idx,
                "sim_time": sim_time_seconds,
                "wall_time": time.time() - _recording_state["start_time"],
            })

            # Capture prim state if tracking
            if _recording_state["track_prims"]:
                try:
                    from .formatter import format_frame_state
                    stage = _get_stage()
                    if stage:
                        prims = [
                            stage.GetPrimAtPath(p)
                            for p in _recording_state["track_prims"]
                        ]
                        state_text = format_frame_state(
                            prims,
                            frame_index=frame_idx,
                            sim_time=sim_time_seconds,
                            property_filter=_recording_state["property_filter"],
                        )
                        state_path = os.path.join(
                            _recording_state["output_dir"], "state.txt"
                        )
                        with open(state_path, "a") as sf:
                            sf.write(state_text)
                            sf.write("\n")
                except Exception as state_err:
                    carb.log_warn(
                        f"[MCP Recording] Frame {frame_idx} state capture failed: {state_err}"
                    )

            _recording_state["frame_count"] = frame_idx + 1

        except Exception as e:
            carb.log_warn(f"[MCP Recording] Frame {frame_idx} capture failed: {e}")

    def _on_update(event):
        if _recording_state["active"]:
            asyncio.ensure_future(_record_tick())

    app = omni.kit.app.get_app()
    _recording_state["_sub"] = app.get_update_event_stream().create_subscription_to_pop(
        _on_update, name=callback_name
    )

    return {
        "status": "success",
        "result": {
            "session_id": session_id,
            "output_dir": session_dir,
            "fps": fps,
            "resolution": [width, height],
            "camera_path": camera_path,
            "track_prims": len(tracked_prim_paths),
            "property_filter": property_filter,
        },
    }


# ---------------------------------------------------------------------------
# /recording/stop
# ---------------------------------------------------------------------------

async def handle_recording_stop(_body: dict) -> dict:
    global _recording_state

    if not _recording_state["active"]:
        return {"status": "error", "error": "No active recording"}

    _recording_state["active"] = False

    # Unsubscribe
    sub = _recording_state.get("_sub")
    if sub is not None:
        sub = None
        _recording_state["_sub"] = None

    # Write metadata
    meta_path = os.path.join(_recording_state["output_dir"], "metadata.json")
    meta = {
        "session_id": _recording_state["session_id"],
        "fps": _recording_state["fps"],
        "resolution": [_recording_state["width"], _recording_state["height"]],
        "camera_path": _recording_state["camera_path"],
        "frame_count": _recording_state["frame_count"],
        "duration_seconds": round(time.time() - _recording_state["start_time"], 2),
        "track_prims": _recording_state.get("track_prims", []),
        "property_filter": _recording_state.get("property_filter"),
        "frames": _recording_state["metadata"],
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Check if state file was written
    state_file = None
    state_path = os.path.join(_recording_state["output_dir"], "state.txt")
    if os.path.exists(state_path):
        state_file = state_path

    return {
        "status": "success",
        "result": {
            "session_id": _recording_state["session_id"],
            "output_dir": _recording_state["output_dir"],
            "frame_count": _recording_state["frame_count"],
            "duration_seconds": meta["duration_seconds"],
            "metadata_file": meta_path,
            "state_file": state_file,
        },
    }


# ---------------------------------------------------------------------------
# /recording/frame
# ---------------------------------------------------------------------------

async def handle_recording_frame(body: dict) -> dict:
    session_dir = body.get("session_dir", "")
    frame_index = body.get("frame_index", 0)

    if not session_dir:
        # Use current/last session
        session_dir = _recording_state.get("output_dir", "")
    if not session_dir:
        return {"status": "error", "error": "No session_dir provided and no recent recording"}

    frame_path = os.path.join(session_dir, f"frame_{frame_index:05d}.png")
    if not os.path.exists(frame_path):
        return {"status": "error", "error": f"Frame not found: {frame_path}"}

    with open(frame_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    # Load metadata if available
    meta_path = os.path.join(session_dir, "metadata.json")
    frame_meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        for fm in meta.get("frames", []):
            if fm.get("frame") == frame_index:
                frame_meta = fm
                break

    return {
        "status": "success",
        "result": {
            "frame_index": frame_index,
            "image_base64": b64,
            "format": "png",
            **frame_meta,
        },
    }


# ---------------------------------------------------------------------------
# /extensions/list
# ---------------------------------------------------------------------------

async def handle_extensions_list(body: dict) -> dict:
    filter_enabled = body.get("enabled_only", False)
    search = body.get("search", "").lower()

    ext_mgr = omni.kit.app.get_app().get_extension_manager()
    extensions = []

    for ext in ext_mgr.get_extensions():
        ext_id = ext.get("id", "")
        name = ext.get("name", ext_id)
        enabled = ext.get("enabled", False)

        if filter_enabled and not enabled:
            continue
        if search and search not in name.lower() and search not in ext_id.lower():
            continue

        extensions.append({
            "id": ext_id,
            "name": name,
            "enabled": enabled,
            "version": ext.get("version", ""),
        })

    return {
        "status": "success",
        "result": {"count": len(extensions), "extensions": extensions},
    }


# ---------------------------------------------------------------------------
# /extensions/manage
# ---------------------------------------------------------------------------

async def handle_extensions_manage(body: dict) -> dict:
    ext_id = body.get("extension_id", "")
    action = body.get("action", "").lower()

    if not ext_id:
        return {"status": "error", "error": "extension_id is required"}
    if action not in ("enable", "disable"):
        return {"status": "error", "error": "action must be 'enable' or 'disable'"}

    await _next_update()

    ext_mgr = omni.kit.app.get_app().get_extension_manager()

    try:
        if action == "enable":
            ext_mgr.set_extension_enabled_immediate(ext_id, True)
        else:
            ext_mgr.set_extension_enabled_immediate(ext_id, False)
    except Exception as e:
        return {"status": "error", "error": f"Failed to {action} {ext_id}: {e}"}

    # Verify
    enabled = ext_mgr.is_extension_enabled(ext_id)
    return {
        "status": "success",
        "result": {"extension_id": ext_id, "action": action, "enabled": enabled},
    }
