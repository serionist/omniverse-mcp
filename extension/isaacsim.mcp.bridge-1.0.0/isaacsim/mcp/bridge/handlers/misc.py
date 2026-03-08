"""
Miscellaneous handlers.

Handles health, execute, debug draw, and extension management.
"""

import io
import json
import sys
import textwrap
import traceback
from typing import Any

import carb
import omni.kit.app
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics

from ._utils import _get_stage, _next_update


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

async def handle_health(_body: dict) -> dict:
    from .recording import _recording_state

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

    from ._mcp_bridge import mcp_bridge

    local_ns: dict[str, Any] = {
        "omni": omni,
        "carb": carb,
        "Usd": Usd,
        "UsdGeom": UsdGeom,
        "UsdLux": UsdLux,
        "UsdPhysics": UsdPhysics,
        "Sdf": Sdf,
        "Gf": Gf,
        "mcp": mcp_bridge,
    }

    captured_out = io.StringIO()
    captured_err = io.StringIO()

    exec_error = None
    exec_tb = None

    # Detect async code: if it won't compile as-is but compiles when wrapped
    # in an async function, run it as a coroutine. This lets scripts use
    # `await mcp.capture_viewport()` etc.
    is_async = False
    try:
        compile(code, "<script>", "exec")
    except SyntaxError:
        try:
            wrapped = "async def __mcp_exec__():\n" + textwrap.indent(code, "    ")
            compile(wrapped, "<script>", "exec")
            is_async = True
        except SyntaxError:
            pass  # Real syntax error — let exec() report it

    # Run exec on the main thread — USD/Omniverse APIs are NOT thread-safe.
    # Using run_in_executor would crash Isaac Sim on any USD call.
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = captured_out
    sys.stderr = captured_err
    try:
        if is_async:
            wrapped = "async def __mcp_exec__():\n" + textwrap.indent(code, "    ")
            wrapped += "\n    return locals().get('result')"
            exec(wrapped, local_ns)
            async_result = await local_ns["__mcp_exec__"]()
            if async_result is not None:
                local_ns["result"] = async_result
        else:
            exec(code, local_ns)
    except SystemExit as e:
        exec_error = f"Script called sys.exit({e.code}). This is not allowed."
        exec_tb = traceback.format_exc()
    except Exception as e:
        exec_error = str(e)
        exec_tb = traceback.format_exc()
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

    if exec_error:
        return {
            "status": "error",
            "error": exec_error,
            "traceback": exec_tb,
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
