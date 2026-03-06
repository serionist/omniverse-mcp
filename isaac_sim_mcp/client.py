"""
HTTP client for communicating with the Isaac Sim MCP Bridge extension.

Uses persistent HTTP connections with keep-alive for efficiency.
"""

import json
import socket
from typing import Any


class IsaacSimClient:
    """Persistent HTTP client that talks to the Isaac Sim extension."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8211, timeout: float = 120.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None

    def _connect(self):
        if self._sock is not None:
            return
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))

    def _disconnect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def request(self, path: str, body: dict | None = None, method: str = "POST") -> dict:
        """Send an HTTP request and return the parsed JSON response."""
        body_bytes = b""
        if body is not None:
            body_bytes = json.dumps(body).encode("utf-8")

        request_line = f"{method} {path} HTTP/1.1\r\n"
        headers = (
            f"Host: {self.host}:{self.port}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: keep-alive\r\n"
            f"\r\n"
        )
        raw_request = (request_line + headers).encode("utf-8") + body_bytes

        for attempt in range(2):
            try:
                self._connect()
                self._sock.sendall(raw_request)
                return self._read_response()
            except (ConnectionError, BrokenPipeError, OSError):
                self._disconnect()
                if attempt == 1:
                    raise

        raise ConnectionError("Failed to communicate with Isaac Sim extension")

    def _read_response(self) -> dict:
        """Read an HTTP response from the socket."""
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Connection closed by Isaac Sim extension")
            buf += chunk

        header_end = buf.index(b"\r\n\r\n") + 4
        header_section = buf[:header_end].decode("utf-8")
        body_start = buf[header_end:]

        content_length = 0
        for line in header_section.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())

        body_buf = body_start
        while len(body_buf) < content_length:
            remaining = content_length - len(body_buf)
            chunk = self._sock.recv(min(remaining, 65536))
            if not chunk:
                raise ConnectionError("Connection closed mid-response")
            body_buf += chunk

        return json.loads(body_buf[:content_length].decode("utf-8"))

    # ----- Core endpoints -----

    def health(self) -> dict:
        return self.request("/health", {}, method="GET")

    def execute(self, code: str) -> dict:
        return self.request("/execute", {"code": code})

    # ----- Scene endpoints -----

    def scene_tree(self, root: str = "/", max_depth: int = 8, include_properties: bool = False,
                   fmt: str = "json") -> dict:
        body: dict[str, Any] = {"root": root, "max_depth": max_depth, "include_properties": include_properties}
        if fmt != "json":
            body["format"] = fmt
        return self.request("/scene/tree", body)

    def scene_dump(self, output_dir: str, root: str = "/", max_depth: int = 15,
                   include_properties: bool = True, filter_types: list[str] | None = None,
                   property_filter: list[str] | None = None) -> dict:
        body: dict[str, Any] = {"output_dir": output_dir, "root": root, "max_depth": max_depth,
                                "include_properties": include_properties}
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

    def set_material(self, prim_path: str, color: list[float], opacity: float = 1.0,
                     roughness: float = 0.5, metallic: float = 0.0,
                     material_path: str = "") -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "color": color,
                                "opacity": opacity, "roughness": roughness, "metallic": metallic}
        if material_path:
            body["material_path"] = material_path
        return self.request("/scene/material", body)

    def clone_prim(self, source_path: str, target_path: str = "", count: int = 1,
                   offset: list[float] | None = None) -> dict:
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

    def capture_viewport(self, width: int = 1280, height: int = 720, camera_path: str = "") -> dict:
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

    def camera_look_at(self, prim_path: str, distance: float | None = None,
                       azimuth: float = 45.0, elevation: float = 30.0) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "azimuth": azimuth, "elevation": elevation}
        if distance is not None:
            body["distance"] = distance
        return self.request("/camera/look_at", body)

    def camera_inspect(self, prim_path: str, angles: list | None = None,
                       width: int = 800, height: int = 600, distance: float | None = None) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "width": width, "height": height}
        if angles is not None:
            body["angles"] = angles
        if distance is not None:
            body["distance"] = distance
        return self.request("/camera/inspect", body)

    # ----- Recording -----

    def recording_start(self, output_dir: str, fps: int = 5, width: int = 640,
                        height: int = 480, camera_path: str = "",
                        track_prims: list[str] | None = None,
                        property_filter: list[str] | None = None) -> dict:
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

    def set_physics_properties(self, prim_path: str, mass: float | None = None,
                                density: float | None = None, friction: float | None = None,
                                restitution: float | None = None) -> dict:
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

    def apply_force(self, prim_path: str, force: list[float], position: list[float] | None = None,
                    impulse: bool = False) -> dict:
        body: dict[str, Any] = {"prim_path": prim_path, "force": force, "impulse": impulse}
        if position is not None:
            body["position"] = position
        return self.request("/physics/apply_force", body)

    def raycast(self, origin: list[float], direction: list[float],
                max_distance: float = 1000.0) -> dict:
        return self.request("/physics/raycast", {
            "origin": origin, "direction": direction, "max_distance": max_distance,
        })

    # ----- Debug -----

    def draw_debug(self, shape_type: str, **kwargs) -> dict:
        body = {"type": shape_type, **kwargs}
        return self.request("/debug/draw", body)

    def close(self):
        self._disconnect()
