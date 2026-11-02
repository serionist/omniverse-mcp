"""
Miscellaneous handlers.

Handles health, execute, and extension management.
"""

import traceback
from typing import Any

import carb
import omni.kit.app
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics

from ovmcp.core import output, script
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


def script_namespace() -> dict[str, Any]:
    """What a script, /execute's or a job's, finds already imported: Kit, USD, and `mcp`, the handlers."""
    from ._mcp_bridge import mcp_bridge

    return {
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


async def handle_execute(body: dict) -> dict:
    code = body.get("code", "")
    if not isinstance(code, str) or not code.strip():
        return {"status": "error", "error": "No code provided"}

    await _next_update()

    namespace = script_namespace()
    exec_error = None
    exec_tb = None
    # On this handler's own task, Kit's main thread: USD from another thread crashes Kit. Its prints go to this call's
    # answer alone, whatever else prints while it awaits (ovmcp.core.output).
    with output.collect(output.Printed()) as printed:
        try:
            await script.run(script.compile_script(code), namespace)
        except SystemExit as e:
            exec_error = f"Script called sys.exit({e.code}). This is not allowed."
            exec_tb = traceback.format_exc()
        except Exception as e:
            exec_error = str(e)
            exec_tb = traceback.format_exc()

    stdout_text = printed.text(output.STDOUT)
    stderr_text = printed.text(output.STDERR)
    script_result = script.jsonable(namespace.get("result"))

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
