"""
Omniverse MCP Bridge Extension

Runs an HTTP server inside Isaac Sim that accepts commands from the MCP server.
Provides endpoints for scene manipulation, script execution, viewport capture,
and simulation control. The server itself lives in ovmcp/core/http.py; this module
wires it into Kit.
"""

import asyncio

import carb
import omni.ext

from ovmcp.core.http import LOOPBACK_HOSTS, BridgeServer
from ovmcp.core.protocol import EXTENSION_NAME, set_extension_version, version_from_ext_id
from ovmcp.core.token import new_token, remove_token, write_token

from .handlers import (
    handle_apply_force,
    handle_camera_inspect,
    handle_camera_look_at,
    handle_camera_set,
    handle_capture,
    handle_clone_prim,
    handle_compare_prims,
    handle_create_prim,
    handle_create_robot,
    handle_create_variant_structure,
    handle_delete_prim,
    handle_draw_debug,
    handle_execute,
    handle_export_prim,
    handle_extensions_list,
    handle_extensions_manage,
    handle_face_count_tree,
    handle_flatten_usd,
    handle_get_joint_states,
    handle_get_logs,
    handle_get_robot_info,
    handle_health,
    handle_mesh_stats,
    handle_new_scene,
    handle_prim_bounds,
    handle_prim_properties,
    handle_raycast,
    handle_recording_frame,
    handle_recording_start,
    handle_recording_stop,
    handle_save_scene,
    handle_scene_dump,
    handle_scene_tree,
    handle_set_joint_targets,
    handle_set_material,
    handle_set_physics_properties,
    handle_set_variant_selection,
    handle_set_visibility,
    handle_sim_control,
    handle_sim_state,
    handle_transform,
    handle_update_material_paths,
    handle_viewport_light,
)


def _get_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return asyncio.get_event_loop_policy().get_event_loop()


class _CarbLog:
    """Lets the core server log through carb, so its lines land in Kit's console and log file."""

    info = staticmethod(carb.log_info)
    warning = staticmethod(carb.log_warn)
    error = staticmethod(carb.log_error)


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._server = None
        set_extension_version(version_from_ext_id(ext_id))
        settings = carb.settings.get_settings()
        prefix = f"/exts/{EXTENSION_NAME}"
        self._host = settings.get(f"{prefix}/host") or "127.0.0.1"
        self._port = settings.get(f"{prefix}/port") or 8211
        configured = settings.get(f"{prefix}/token")
        self._token = (str(configured).strip() if configured is not None else "") or new_token()

        routes = {
            "/health": handle_health,
            "/execute": handle_execute,
            "/scene/tree": handle_scene_tree,
            "/scene/dump": handle_scene_dump,
            "/scene/prim": handle_prim_properties,
            "/scene/bounds": handle_prim_bounds,
            "/scene/transform": handle_transform,
            "/scene/create": handle_create_prim,
            "/scene/delete": handle_delete_prim,
            "/scene/material": handle_set_material,
            "/scene/clone": handle_clone_prim,
            "/scene/visibility": handle_set_visibility,
            "/scene/save": handle_save_scene,
            "/scene/new": handle_new_scene,
            "/robot/create": handle_create_robot,
            "/robot/info": handle_get_robot_info,
            "/robot/joint_states": handle_get_joint_states,
            "/robot/joint_targets": handle_set_joint_targets,
            "/sim/control": handle_sim_control,
            "/sim/capture": handle_capture,
            "/sim/state": handle_sim_state,
            "/physics/properties": handle_set_physics_properties,
            "/physics/apply_force": handle_apply_force,
            "/physics/raycast": handle_raycast,
            "/debug/draw": handle_draw_debug,
            "/camera/set": handle_camera_set,
            "/camera/look_at": handle_camera_look_at,
            "/camera/inspect": handle_camera_inspect,
            "/recording/start": handle_recording_start,
            "/recording/stop": handle_recording_stop,
            "/recording/frame": handle_recording_frame,
            "/extensions/list": handle_extensions_list,
            "/extensions/manage": handle_extensions_manage,
            "/scene/mesh_stats": handle_mesh_stats,
            "/scene/face_count_tree": handle_face_count_tree,
            "/scene/flatten": handle_flatten_usd,
            "/scene/export": handle_export_prim,
            "/scene/variant_selection": handle_set_variant_selection,
            "/scene/create_variant_structure": handle_create_variant_structure,
            "/scene/compare": handle_compare_prims,
            "/scene/update_material_paths": handle_update_material_paths,
            "/viewport/light": handle_viewport_light,
            "/logs": handle_get_logs,
        }

        if self._host not in LOOPBACK_HOSTS:
            carb.log_warn(
                f"[MCP Bridge] WARNING: Binding to non-loopback address {self._host}. "
                "Any client on the network that holds the bridge token can run arbitrary code in this app. "
                "Keep the token secret and the port off untrusted networks, or use 127.0.0.1."
            )

        # Start log buffer before anything else so it captures startup messages
        from .handlers.logging import log_buffer

        self._log_buffer = log_buffer
        self._log_buffer.start()

        self._token_port = None
        self._server = BridgeServer(routes, self._token, self._host, self._port, log=_CarbLog())
        _get_event_loop().create_task(self._start_server())
        _get_event_loop().create_task(self._init_sensors())
        carb.log_info(f"[MCP Bridge] Starting on {self._host}:{self._port}")

    def on_shutdown(self):
        try:
            from .handlers.recording import _recording_state

            if _recording_state.get("active"):
                _recording_state["active"] = False
                _recording_state.pop("_sub", None)
                carb.log_info("[MCP Bridge] Stopped active recording on shutdown")
        except Exception:
            pass

        # Only drops the drawing subscription and the book: a clear now could meet a stage tearing down.
        from .handlers.debug_draw import stop_drawing

        stop_drawing()

        try:
            from .handlers.robot import _clear_articulation_cache

            _clear_articulation_cache()
        except Exception:
            pass

        if hasattr(self, "_log_buffer") and self._log_buffer is not None:
            self._log_buffer.stop()

        if self._server is not None:
            self._server.close()
            carb.log_info("[MCP Bridge] Server shut down")
            self._server = None
        if self._token_port is not None:
            remove_token(self._token_port, self._token)

    async def _init_sensors(self):
        """Pre-initialize syntheticdata sensors so capture_viewport works on first call."""
        try:
            import omni.syntheticdata as syn
            from omni.kit.viewport.utility import get_active_viewport

            # Wait for viewport to be ready
            for _ in range(30):
                await asyncio.sleep(0.5)
                vp = get_active_viewport()
                if vp is not None:
                    break

            if vp is None:
                carb.log_warn("[MCP Bridge] No viewport found, segmentation won't be available")
                return

            syn.sensors.create_or_retrieve_sensor(vp, syn._syntheticdata.SensorType.InstanceSegmentation)
            syn.sensors.enable_sensors(vp, [syn._syntheticdata.SensorType.InstanceSegmentation])
            carb.log_info("[MCP Bridge] Instance segmentation sensor initialized")
        except Exception as e:
            carb.log_warn(f"[MCP Bridge] Sensor init failed (non-fatal): {e}")

    async def _start_server(self):
        server = self._server
        try:
            if not await server.start():
                return  # the extension was shut down while the port was being bound
        except Exception as e:
            carb.log_error(f"[MCP Bridge] Failed to start server: {e}")
            return
        # Only once the port is ours, and under the port actually bound: an instance that fails to bind must not
        # replace the running one's token.
        try:
            token_file = write_token(server.port, self._token)
            self._token_port = server.port
            carb.log_info(f"[MCP Bridge] Token written to {token_file}")
        except OSError as e:
            carb.log_error(
                f"[MCP Bridge] Could not write the bridge token file ({e}). Set the extension's token setting "
                "and give the MCP server the same value in OMNIVERSE_MCP_TOKEN."
            )
