"""
Isaac Sim MCP Bridge Extension

Runs an HTTP server inside Isaac Sim that accepts commands from the MCP server.
Provides endpoints for scene manipulation, script execution, viewport capture,
and simulation control.
"""

import asyncio
import io
import json
import sys
import traceback

import carb
import omni.ext
import omni.kit.app
import omni.usd

MAX_BODY_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_CONNECTIONS = 20

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


class Extension(omni.ext.IExt):
    def on_startup(self, ext_id: str):
        self._server = None
        self._connection_semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
        settings = carb.settings.get_settings()
        self._host = settings.get("/exts/isaacsim.mcp.bridge/host") or "127.0.0.1"
        self._port = settings.get("/exts/isaacsim.mcp.bridge/port") or 8211

        self._routes = {
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

        host = self._host
        if host not in ("127.0.0.1", "::1", "localhost"):
            carb.log_warn(
                f"[MCP Bridge] WARNING: Binding to non-loopback address {host}. "
                "The MCP bridge has no authentication — any network client can execute arbitrary code. "
                "Consider using 127.0.0.1 for security."
            )

        # Start log buffer before anything else so it captures startup messages
        from .handlers.logging import log_buffer
        self._log_buffer = log_buffer
        self._log_buffer.start()

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

            syn.sensors.create_or_retrieve_sensor(
                vp, syn._syntheticdata.SensorType.InstanceSegmentation
            )
            syn.sensors.enable_sensors(
                vp, [syn._syntheticdata.SensorType.InstanceSegmentation]
            )
            carb.log_info("[MCP Bridge] Instance segmentation sensor initialized")
        except Exception as e:
            carb.log_warn(f"[MCP Bridge] Sensor init failed (non-fatal): {e}")

    async def _start_server(self):
        try:
            self._server = await asyncio.start_server(
                self._handle_connection, self._host, self._port
            )
            addr = self._server.sockets[0].getsockname()
            carb.log_info(f"[MCP Bridge] Listening on {addr[0]}:{addr[1]}")
        except Exception as e:
            carb.log_error(f"[MCP Bridge] Failed to start server: {e}")

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        carb.log_info(f"[MCP Bridge] Connection from {peer}")
        if not hasattr(self, "_routes"):
            # Connection arrived before on_startup finished (e.g., hot-reload)
            carb.log_warn("[MCP Bridge] Connection rejected — server not ready")
            writer.close()
            return
        async with self._connection_semaphore:
            try:
                while True:
                    # Read HTTP request
                    request_line = await reader.readline()
                    if not request_line:
                        break
                    request_line = request_line.decode("utf-8").strip()
                    if not request_line:
                        continue

                    # Parse method and path
                    parts = request_line.split(" ")
                    if len(parts) < 2:
                        await self._send_response(writer, 400, {"status": "error", "error": "Bad request"})
                        continue
                    method = parts[0]
                    path = parts[1]

                    # Read headers
                    content_length = 0
                    while True:
                        header_line = await reader.readline()
                        if header_line in (b"\r\n", b"\n", b""):
                            break
                        header = header_line.decode("utf-8").strip()
                        if header.lower().startswith("content-length:"):
                            try:
                                content_length = int(header.split(":", 1)[1].strip())
                            except ValueError:
                                content_length = 0

                    if content_length > MAX_BODY_SIZE:
                        await self._send_response(writer, 413, {
                            "status": "error",
                            "error": f"Request body too large ({content_length} bytes, max {MAX_BODY_SIZE})"
                        })
                        continue

                    # Read body
                    body = {}
                    if content_length > 0:
                        raw_body = await reader.readexactly(content_length)
                        try:
                            body = json.loads(raw_body.decode("utf-8"))
                        except json.JSONDecodeError:
                            await self._send_response(writer, 400, {"status": "error", "error": "Invalid JSON body"})
                            continue

                    # Route to handler
                    handler = self._routes.get(path)
                    if handler is None:
                        await self._send_response(writer, 404, {"status": "error", "error": f"Unknown endpoint: {path}"})
                        continue

                    if method == "GET" and path == "/health":
                        try:
                            result = await handle_health(_body={})
                            await self._send_response(writer, 200, result)
                        except Exception as e:
                            tb = traceback.format_exc()
                            carb.log_error(f"[MCP Bridge] Health check error: {e}")
                            await self._send_response(writer, 500, {
                                "status": "error",
                                "error": str(e),
                                "traceback": tb
                            })
                        continue

                    if method != "POST":
                        await self._send_response(writer, 405, {"status": "error", "error": "Method not allowed, use POST"})
                        continue

                    try:
                        result = await handler(body)
                        await self._send_response(writer, 200, result)
                    except Exception as e:
                        tb = traceback.format_exc()
                        carb.log_error(f"[MCP Bridge] Handler error on {path}: {tb}")
                        await self._send_response(writer, 500, {"status": "error", "error": str(e), "traceback": tb})

            except asyncio.IncompleteReadError:
                pass
            except ConnectionResetError:
                pass
            except Exception as e:
                carb.log_error(f"[MCP Bridge] Connection error: {e}")
            finally:
                writer.close()
                carb.log_info(f"[MCP Bridge] Connection closed from {peer}")

    async def _send_response(self, writer: asyncio.StreamWriter, status_code: int, body: dict):
        status_texts = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 413: "Payload Too Large", 500: "Internal Server Error"}
        status_text = status_texts.get(status_code, "Unknown")
        body_bytes = json.dumps(body).encode("utf-8")
        header = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
        writer.write(header.encode("utf-8") + body_bytes)
        await writer.drain()
