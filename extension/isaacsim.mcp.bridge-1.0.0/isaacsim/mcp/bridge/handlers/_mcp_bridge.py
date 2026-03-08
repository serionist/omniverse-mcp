"""
MCPBridge — async helper object injected into execute_script as `mcp`.

Provides access to MCP handler functions from within scripts.
All methods are async — use `await` in your execute_script code.

Example:
    # In execute_script code:
    viewport = await mcp.capture_viewport(width=1280)
    tree = await mcp.scene_tree()
    result = {"image_size": len(viewport["result"]["image_base64"]), "tree": tree["result"]}
"""


class MCPBridge:
    """Async interface to MCP handlers, available as `mcp` in execute_script."""

    # --- Camera & viewport ---

    async def capture_viewport(self, width: int = 640, height: int = 480, camera_path: str = ""):
        """Capture the viewport. Returns full handler response with image_base64, bboxes, segmentation."""
        from .camera import handle_capture
        body = {"width": width, "height": height}
        if camera_path:
            body["camera_path"] = camera_path
        return await handle_capture(body)

    async def set_camera(self, position: list, target: list = None):
        """Set viewport camera position and optional look-at target."""
        from .camera import handle_camera_set
        body = {"position": position}
        if target is not None:
            body["target"] = target
        return await handle_camera_set(body)

    async def look_at(self, prim_path: str, distance: float = None,
                      azimuth: float = 45.0, elevation: float = 30.0):
        """Point camera at a prim."""
        from .camera import handle_camera_look_at
        body = {"prim_path": prim_path, "azimuth": azimuth, "elevation": elevation}
        if distance is not None:
            body["distance"] = distance
        return await handle_camera_look_at(body)

    async def inspect(self, prim_path: str, angles: list = None,
                      width: int = 640, height: int = 480, distance: float = None):
        """Orbit-capture a prim from multiple angles."""
        from .camera import handle_camera_inspect
        body = {"prim_path": prim_path, "width": width, "height": height}
        if angles is not None:
            body["angles"] = angles
        if distance is not None:
            body["distance"] = distance
        return await handle_camera_inspect(body)

    # --- Scene ---

    async def scene_tree(self, root: str = "/", max_depth: int = 8):
        """Get the scene prim hierarchy."""
        from .scene import handle_scene_tree
        return await handle_scene_tree({"root": root, "max_depth": max_depth})

    async def prim_properties(self, prim_path: str):
        """Get all properties of a prim."""
        from .scene import handle_prim_properties
        return await handle_prim_properties({"prim_path": prim_path})

    async def prim_bounds(self, prim_path: str):
        """Get world-space bounding box of a prim."""
        from .scene import handle_prim_bounds
        return await handle_prim_bounds({"prim_path": prim_path})

    async def set_transform(self, prim_path: str, position=None, rotation=None, scale=None):
        """Set position/rotation/scale on a prim."""
        from .scene import handle_transform
        body = {"prim_path": prim_path}
        if position is not None:
            body["position"] = position
        if rotation is not None:
            body["rotation"] = rotation
        if scale is not None:
            body["scale"] = scale
        return await handle_transform(body)

    async def create_prim(self, prim_path: str, prim_type: str = "Xform", **kwargs):
        """Create a prim (optionally with USD reference, position, physics)."""
        from .scene import handle_create_prim
        body = {"prim_path": prim_path, "prim_type": prim_type, **kwargs}
        return await handle_create_prim(body)

    async def delete_prim(self, prim_path: str):
        """Delete a prim and its descendants."""
        from .scene import handle_delete_prim
        return await handle_delete_prim({"prim_path": prim_path})

    async def set_material(self, prim_path: str, color: list, opacity: float = 1.0,
                           roughness: float = 0.5, metallic: float = 0.0):
        """Create and bind a PBR material."""
        from .scene import handle_set_material
        return await handle_set_material({
            "prim_path": prim_path, "color": color,
            "opacity": opacity, "roughness": roughness, "metallic": metallic,
        })

    # --- Simulation ---

    async def sim_control(self, action: str):
        """Control simulation: play, pause, stop, step."""
        from .simulation import handle_sim_control
        return await handle_sim_control({"action": action})

    async def sim_state(self):
        """Get simulation state (playing/paused/stopped, time, fps, etc.)."""
        from .simulation import handle_sim_state
        return await handle_sim_state({})

    # --- Logs ---

    async def get_logs(self, count: int = 50, min_level: str = None,
                       channel: str = None, search: str = None):
        """Get recent Omniverse log entries."""
        from .logging import handle_get_logs
        body = {"count": count}
        if min_level:
            body["min_level"] = min_level
        if channel:
            body["channel"] = channel
        if search:
            body["search"] = search
        return await handle_get_logs(body)


# Singleton
mcp_bridge = MCPBridge()
