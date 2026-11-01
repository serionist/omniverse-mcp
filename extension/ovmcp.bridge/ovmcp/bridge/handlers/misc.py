"""
Miscellaneous handlers.

Handles health, execute, and extension management.
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

from ovmcp.core.protocol import PROTOCOL, extension_version, kit_app

from ._utils import _get_stage, _next_update

# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


async def handle_health(_body: dict) -> dict:
    from .recording import recording_active

    stage = _get_stage()
    ext_mgr = omni.kit.app.get_app().get_extension_manager()
    return {
        "status": "success",
        "result": {
            "stage_path": stage.GetRootLayer().realPath or "(unsaved)",
            "up_axis": UsdGeom.GetStageUpAxis(stage),
            "meters_per_unit": UsdGeom.GetStageMetersPerUnit(stage),
            "recording_active": recording_active(),
            "protocol": PROTOCOL,
            "extension_version": extension_version(),
            **kit_app(),
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

    script_result = local_ns.get("result")
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

        extensions.append(
            {
                "id": ext_id,
                "name": name,
                "enabled": enabled,
                "version": ext.get("version", ""),
            }
        )

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
