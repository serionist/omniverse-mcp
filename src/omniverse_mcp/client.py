"""
HTTP client for communicating with the Omniverse MCP Bridge extension (ovmcp.bridge).

Uses persistent HTTP connections with keep-alive for efficiency.
"""

import json
import logging
import os
import socket
from typing import Any

from .bridge_token import ENV_TOKEN, read_token, token_path

logger = logging.getLogger(__name__)

# The bridge protocol this server speaks. The extension answers its own to GET /bridge; its copy is
# ovmcp.core.protocol.PROTOCOL, and tests/test_bridge_token.py keeps them equal.
PROTOCOL = 1


class BridgeError(RuntimeError):
    """The bridge refused the request, or speaks another protocol. The message says what to do."""


class BridgeClient:
    """Persistent HTTP client that talks to the ovmcp.bridge extension inside a Kit app."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8211, timeout: float = 120.0, token: str | None = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._received = False  # any bytes back for the request in flight
        # A token handed in stays. Otherwise it comes from the environment or the token file, and is read again
        # after a 401: Kit may start after this server, and makes a new token at every start.
        self._fixed_token = token is not None
        self._token = token if token is not None else read_token(port)

    def _connect(self):
        if self._sock is not None:
            return
        self._sock = socket.create_connection((self.host, self.port), timeout=10.0)
        self._sock.settimeout(self.timeout)

    def _disconnect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def request(self, path: str, body: dict | None = None, method: str = "POST") -> dict:
        """Send an HTTP request and return the parsed JSON response."""
        status, data = self._exchange(path, body, method)
        if status == 401 and self._reload_token():
            status, data = self._exchange(path, body, method)
        if status in (401, 403):
            raise BridgeError(self._refusal(status, data))
        return data

    def _reload_token(self) -> bool:
        """Read the token again; True when it changed."""
        if self._fixed_token:
            return False
        fresh = read_token(self.port)
        if fresh and fresh != self._token:
            self._token = fresh
            return True
        return False

    def _refusal(self, status: int, data: dict) -> str:
        message = data.get("error", f"HTTP {status}")
        if status != 401:
            return message
        if self._fixed_token:
            return f"{message} The token this client was given was refused."
        if os.environ.get(ENV_TOKEN, "").strip():
            return f"{message} The token in {ENV_TOKEN} was refused: it must equal the extension's token setting."
        path = token_path(self.port)
        if not path.exists():
            return (
                f"{message} No token found ({ENV_TOKEN} is not set and there is no {path}): is the MCP "
                "Bridge extension enabled in a running Kit app on this machine?"
            )
        return (
            f"{message} The token in {path} is not the running extension's: is another Kit app on port "
            f"{self.port}, or did the extension fail to write it? Kit's log says which."
        )

    def _check_handshake(self, status: int, data: dict) -> None:
        """Refuse an extension that speaks another protocol, before any request runs on it."""
        problem = None
        result = data.get("result") or {}
        if status == 404:
            problem = (
                f"The Kit extension is older than this MCP server: it has no bridge handshake, the server "
                f"speaks protocol {PROTOCOL}. Update the extension (git pull in the omniverse-mcp checkout) "
                "and restart Kit."
            )
        elif status != 200 or "protocol" not in result:
            problem = f"Unexpected handshake answer from the Kit extension (HTTP {status}): {data.get('error', data)}"
        elif result["protocol"] != PROTOCOL:
            problem = (
                f"The Kit extension {result.get('extension_version', 'unknown')} speaks bridge protocol "
                f"{result['protocol']} and this MCP server speaks {PROTOCOL}. Update the older of the two "
                "and restart it."
            )
        if problem:
            # The next request reconnects and asks again.
            self._disconnect()
            raise BridgeError(problem)

    def _build(self, path: str, body: dict | None, method: str) -> bytes:
        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body).encode("utf-8")

        host = f"[{self.host}]" if ":" in self.host else self.host
        auth = f"Authorization: Bearer {self._token}\r\n" if self._token else ""
        request_line = f"{method} {path} HTTP/1.1\r\n"
        headers = (
            f"Host: {host}:{self.port}\r\n"
            f"{auth}"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
        return (request_line + headers).encode("utf-8") + body_bytes

    def _exchange(self, path: str, body: dict | None, method: str) -> tuple[int, dict]:
        raw_request = self._build(path, body, method)
        for attempt in range(2):
            reused = self._sock is not None
            self._received = False
            try:
                if self._sock is None:
                    self._connect()
                    # Every new connection starts with the handshake, a request without a body: a stale token is
                    # refused there, and a Kit restarted with another extension is caught before the request runs.
                    self._sock.sendall(self._build("/bridge", None, "GET"))
                    status, data = self._read_response()
                    if status in (401, 403):
                        return status, data
                    self._check_handshake(status, data)
                self._sock.sendall(raw_request)
                return self._read_response()
            except OSError as e:
                self._disconnect()
                # Retry only a kept-alive connection gone stale: the bridge closed it before reading the request, so
                # nothing came back. After a timeout or a cut-off reply the request may have run; sending it again
                # would run a script twice.
                if attempt == 1 or not reused or self._received or isinstance(e, TimeoutError):
                    raise
                logger.warning(f"Connection failed (attempt {attempt + 1}/2), retrying: {e}")

        raise ConnectionError(
            f"Failed to communicate with the Kit app at {self.host}:{self.port}. "
            "Ensure the Kit app (Isaac Sim, USD Composer, ...) is running with the ovmcp.bridge extension enabled."
        )

    def _read_response(self) -> tuple[int, dict]:
        """Read an HTTP response from the socket: its status code and JSON body."""
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed by the ovmcp.bridge extension")
            self._received = True
            buf += chunk

        header_end = buf.index(b"\r\n\r\n") + 4
        header_lines = buf[:header_end].decode("utf-8").split("\r\n")
        body_start = buf[header_end:]

        try:
            status = int(header_lines[0].split(" ")[1])
        except (IndexError, ValueError):
            self._disconnect()
            raise ConnectionError(f"Malformed status line from the Kit app: {header_lines[0]!r}")

        content_length = 0
        close = False
        for line in header_lines[1:]:
            name, _, value = line.partition(":")
            name = name.strip().lower()
            if name == "content-length":
                content_length = int(value.strip())
            elif name == "connection":
                close = value.strip().lower() == "close"

        if content_length <= 0:
            self._disconnect()
            raise ConnectionError("The Kit app returned a response with no Content-Length")

        chunks = [body_start]
        bytes_read = len(body_start)
        while bytes_read < content_length:
            remaining = content_length - bytes_read
            chunk = self._sock.recv(min(remaining, 65536))
            if not chunk:
                raise ConnectionError("Connection closed mid-response")
            chunks.append(chunk)
            bytes_read += len(chunk)
        body_bytes = b"".join(chunks)
        if close:
            self._disconnect()

        try:
            return status, json.loads(body_bytes[:content_length].decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._disconnect()
            raise ConnectionError(f"Malformed response from the Kit app: {e}")

    # ----- Core endpoints -----

    def health(self) -> dict:
        return self.request("/health", {}, method="GET")

    def execute(self, code: str) -> dict:
        return self.request("/execute", {"code": code})

    # ----- Scene endpoints -----

    def scene_tree(
        self, root: str = "/", max_depth: int = 8, include_properties: bool = False, fmt: str = "json"
    ) -> dict:
        body: dict[str, Any] = {"root": root, "max_depth": max_depth, "include_properties": include_properties}
        if fmt != "json":
            body["format"] = fmt
        return self.request("/scene/tree", body)

    def scene_dump(
        self,
        output_dir: str,
        root: str = "/",
        max_depth: int = 15,
        include_properties: bool = True,
        filter_types: list[str] | None = None,
        property_filter: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {
            "output_dir": output_dir,
            "root": root,
            "max_depth": max_depth,
            "include_properties": include_properties,
        }
        if filter_types:
            body["filter_types"] = filter_types
        if property_filter:
            body["property_filter"] = property_filter
        return self.request("/scene/dump", body)

    def prim_properties(self, prim_path: str, fmt: str = "json") -> dict:
        body: dict[str, Any] = {"prim_path": prim_path}
        if fmt != "json":
            body["format"] = fmt
        return self.request("/scene/prim", body)

    def prim_bounds(self, prim_path: str) -> dict:
        return self.request("/scene/bounds", {"prim_path": prim_path})

    def set_transform(self, prim_path: str, position=None, rotation=None, scale=None) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path}
        if position is not None:
            body["position"] = position
        if rotation is not None:
            body["rotation"] = rotation
        if scale is not None:
            body["scale"] = scale
        return self.request("/scene/transform", body)

    def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs) -> dict:
        body = {"prim_path": prim_path, "prim_type": prim_type, **kwargs}
        return self.request("/scene/create", body)

    def delete_prim(self, prim_path: str) -> dict:
        return self.request("/scene/delete", {"prim_path": prim_path})

    def set_material(
        self,
        prim_path: str,
        color: list[float],
        opacity: float = 1.0,
        roughness: float = 0.5,
        metallic: float = 0.0,
        material_path: str = "",
    ) -> dict:
        body: dict[str, Any] = {
            "prim_path": prim_path,
            "color": color,
            "opacity": opacity,
            "roughness": roughness,
            "metallic": metallic,
        }
        if material_path:
            body["material_path"] = material_path
        return self.request("/scene/material", body)

    def clone_prim(
        self, source_path: str, target_path: str = "", count: int = 1, offset: list[float] | None = None
    ) -> dict:
        body: dict[str, Any] = {"source_path": source_path, "target_path": target_path, "count": count}
        if offset is not None:
            body["offset"] = offset
        return self.request("/scene/clone", body)

    def set_visibility(self, prim_path: str, visible: bool = True) -> dict:
        return self.request("/scene/visibility", {"prim_path": prim_path, "visible": visible})

    def save_scene(self, file_path: str = "") -> dict:
        body: dict[str, Any] = {}
        if file_path:
            body["file_path"] = file_path
        return self.request("/scene/save", body)

    def new_scene(self) -> dict:
        return self.request("/scene/new", {})

    # ----- Robot -----

    def create_robot(self, robot_type: str, prim_path: str = "", position=None, rotation=None) -> dict:
        body: dict[str, Any] = {"robot_type": robot_type}
        if prim_path:
            body["prim_path"] = prim_path
        if position is not None:
            body["position"] = position
        if rotation is not None:
            body["rotation"] = rotation
        return self.request("/robot/create", body)

    def get_robot_info(self, prim_path: str) -> dict:
        return self.request("/robot/info", {"prim_path": prim_path})

    def get_joint_states(self, prim_path: str) -> dict:
        return self.request("/robot/joint_states", {"prim_path": prim_path})

    def set_joint_targets(self, prim_path: str, targets=None) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path}
        if targets is not None:
            body["targets"] = targets
        return self.request("/robot/joint_targets", body)

    # ----- Simulation -----

    def sim_control(self, action: str) -> dict:
        return self.request("/sim/control", {"action": action})

    def sim_state(self) -> dict:
        return self.request("/sim/state", {})

    def capture_viewport(self, width: int = 640, height: int = 480, camera_path: str = "") -> dict:
        body: dict[str, Any] = {"width": width, "height": height}
        if camera_path:
            body["camera_path"] = camera_path
        return self.request("/sim/capture", body)

    # ----- Camera -----

    def camera_set(self, position: list[float], target: list[float] | None = None) -> dict:
        body: dict[str, Any] = {"position": position}
        if target is not None:
            body["target"] = target
        return self.request("/camera/set", body)

    def camera_look_at(
        self, prim_path: str, distance: float | None = None, azimuth: float = 45.0, elevation: float = 30.0
    ) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "azimuth": azimuth, "elevation": elevation}
        if distance is not None:
            body["distance"] = distance
        return self.request("/camera/look_at", body)

    def camera_inspect(
        self,
        prim_path: str,
        angles: list | None = None,
        width: int = 640,
        height: int = 480,
        *,
        zoom_offset: float = 0.0,
        isolate: bool = False,
        include_segmentation: bool = False,
    ) -> dict:
        # Keyword-only: zoom_offset now sits where distance was, and an old positional distance must not become one.
        body: dict[str, Any] = {"prim_path": prim_path, "width": width, "height": height}
        if angles is not None:
            body["angles"] = angles
        if zoom_offset != 0.0:
            body["zoom_offset"] = zoom_offset
        if isolate:
            body["isolate"] = True
        if include_segmentation:
            body["include_segmentation"] = True
        return self.request("/camera/inspect", body)

    # ----- Recording -----

    def recording_start(
        self,
        output_dir: str,
        fps: int = 5,
        width: int = 640,
        height: int = 480,
        camera_path: str = "",
        track_prims: list[str] | None = None,
        property_filter: list[str] | None = None,
    ) -> dict:
        body: dict[str, Any] = {"output_dir": output_dir, "fps": fps, "width": width, "height": height}
        if camera_path:
            body["camera_path"] = camera_path
        if track_prims:
            body["track_prims"] = track_prims
        if property_filter:
            body["property_filter"] = property_filter
        return self.request("/recording/start", body)

    def recording_stop(self) -> dict:
        return self.request("/recording/stop", {})

    def recording_frame(self, session_dir: str = "", frame_index: int = 0) -> dict:
        body: dict[str, Any] = {"frame_index": frame_index}
        if session_dir:
            body["session_dir"] = session_dir
        return self.request("/recording/frame", body)

    # ----- Extensions -----

    def extensions_list(self, enabled_only: bool = False, search: str = "") -> dict:
        body: dict[str, Any] = {}
        if enabled_only:
            body["enabled_only"] = True
        if search:
            body["search"] = search
        return self.request("/extensions/list", body)

    def extensions_manage(self, extension_id: str, action: str) -> dict:
        return self.request("/extensions/manage", {"extension_id": extension_id, "action": action})

    # ----- Physics -----

    def set_physics_properties(
        self,
        prim_path: str,
        mass: float | None = None,
        density: float | None = None,
        friction: float | None = None,
        restitution: float | None = None,
    ) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path}
        if mass is not None:
            body["mass"] = mass
        if density is not None:
            body["density"] = density
        if friction is not None:
            body["friction"] = friction
        if restitution is not None:
            body["restitution"] = restitution
        return self.request("/physics/properties", body)

    def apply_force(
        self, prim_path: str, force: list[float], position: list[float] | None = None, impulse: bool = False
    ) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "force": force, "impulse": impulse}
        if position is not None:
            body["position"] = position
        return self.request("/physics/apply_force", body)

    def raycast(self, origin: list[float], direction: list[float], max_distance: float = 1000.0) -> dict:
        return self.request(
            "/physics/raycast",
            {
                "origin": origin,
                "direction": direction,
                "max_distance": max_distance,
            },
        )

    # ----- Debug -----

    def draw_debug(self, shape_type: str, **kwargs) -> dict:
        body = {"type": shape_type, **kwargs}
        return self.request("/debug/draw", body)

    # ----- New scene tools -----

    def mesh_stats(self, prim_path: str) -> dict:
        return self.request("/scene/mesh_stats", {"prim_path": prim_path})

    def face_count_tree(self, root: str = "/World", max_depth: int = 10) -> dict:
        return self.request("/scene/face_count_tree", {"root": root, "max_depth": max_depth})

    def flatten_usd(self, output_path: str, input_path: str = "") -> dict:
        body: dict[str, Any] = {"output_path": output_path}
        if input_path:
            body["input_path"] = input_path
        return self.request("/scene/flatten", body)

    def export_prim(self, prim_path: str, output_path: str) -> dict:
        return self.request("/scene/export", {"prim_path": prim_path, "output_path": output_path})

    def set_variant_selection(self, prim_path: str, variant_set: str, variant_name: str) -> dict:
        return self.request(
            "/scene/variant_selection",
            {
                "prim_path": prim_path,
                "variant_set": variant_set,
                "variant_name": variant_name,
            },
        )

    def create_variant_structure(
        self, prim_path: str, variant_set_name: str, variant_names: list[str], default_variant: str = ""
    ) -> dict:
        body: dict[str, Any] = {
            "prim_path": prim_path,
            "variant_set_name": variant_set_name,
            "variant_names": variant_names,
        }
        if default_variant:
            body["default_variant"] = default_variant
        return self.request("/scene/create_variant_structure", body)

    def compare_prims(
        self,
        prim_path_a: str = "",
        prim_path_b: str = "",
        prim_path: str = "",
        variant_set: str = "",
        variant_a: str = "",
        variant_b: str = "",
    ) -> dict:
        body: dict[str, Any] = {}
        if prim_path_a:
            body["prim_path_a"] = prim_path_a
        if prim_path_b:
            body["prim_path_b"] = prim_path_b
        if prim_path:
            body["prim_path"] = prim_path
        if variant_set:
            body["variant_set"] = variant_set
        if variant_a:
            body["variant_a"] = variant_a
        if variant_b:
            body["variant_b"] = variant_b
        return self.request("/scene/compare", body)

    def update_material_paths(self, old_prefix: str, new_prefix: str, prim_path: str = "/") -> dict:
        return self.request(
            "/scene/update_material_paths",
            {
                "prim_path": prim_path,
                "old_prefix": old_prefix,
                "new_prefix": new_prefix,
            },
        )

    # ----- Logs -----

    def get_logs(
        self, count: int = 50, min_level: str = "", channel: str = "", since_index: int | None = None, search: str = ""
    ) -> dict:
        body: dict[str, Any] = {"count": count}
        if min_level:
            body["min_level"] = min_level
        if channel:
            body["channel"] = channel
        if since_index is not None:
            body["since_index"] = since_index
        if search:
            body["search"] = search
        return self.request("/logs", body)

    # ----- Viewport light -----

    def viewport_light(self, action: str = "get", enabled: bool = True, *, mode: str = "") -> dict:
        body: dict[str, Any] = {"action": action}
        if action == "set" and mode:
            body["mode"] = mode
        elif action == "set_camera_light":
            body["enabled"] = enabled
        return self.request("/viewport/light", body)

    def close(self):
        self._disconnect()
