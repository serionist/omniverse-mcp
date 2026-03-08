"""Miscellaneous tools (execute_script, manage_extensions, get_logs)."""

import json


def register(mcp, client, h):
    def _call(fn, *args, **kwargs):
        """Call client method with connection error handling."""
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "error": f"Isaac Sim connection failed: {e}"}
        return resp

    def _check_error(resp):
        """Check response for errors, including traceback."""
        if resp["status"] == "error":
            msg = f"ERROR: {resp['error']}"
            tb = resp.get("traceback", "")
            if tb:
                # Include first 5 lines of traceback for diagnosis
                tb_lines = tb.strip().split("\n")
                msg += "\n" + "\n".join(tb_lines[-5:])
            return msg
        return None

    @mcp.tool()
    def execute_script(code: str) -> str:
        """Execute Python inside the running Isaac Sim instance.

        The script has access to: omni, carb, Usd, UsdGeom, UsdLux, UsdPhysics, Sdf, Gf, mcp.
        Assign to 'result' to return data. stdout/stderr are captured.

        The `mcp` object provides async access to MCP handlers from within scripts.
        Use `await` to call its methods (the script automatically runs as async):

            viewport = await mcp.capture_viewport(width=1280)
            tree = await mcp.scene_tree()
            await mcp.set_camera([5, 3, 5], target=[0, 0, 0])
            result = {"tree": tree["result"]}

        Available mcp methods:
            mcp.capture_viewport(width, height, camera_path)
            mcp.set_camera(position, target)
            mcp.look_at(prim_path, distance, azimuth, elevation)
            mcp.inspect(prim_path, angles, width, height, distance)
            mcp.scene_tree(root, max_depth)
            mcp.prim_properties(prim_path)
            mcp.prim_bounds(prim_path)
            mcp.set_transform(prim_path, position, rotation, scale)
            mcp.create_prim(prim_path, prim_type, **kwargs)
            mcp.delete_prim(prim_path)
            mcp.set_material(prim_path, color, opacity, roughness, metallic)
            mcp.sim_control(action)  -- play/pause/stop/step
            mcp.sim_state()
            mcp.get_logs(count, min_level, channel, search)

        Each returns the full handler response dict with "status" and "result" keys.

        Use Context7 MCP (library: isaac-sim/isaacsim) to look up the correct API calls.
        """
        resp = _call(client.execute, code)
        err = _check_error(resp)
        if err:
            return err

        r = resp["result"]
        parts = []
        if r.get("stdout"):
            parts.append(f"Stdout:\n{r['stdout']}")
        if r.get("stderr"):
            parts.append(f"Stderr:\n{r['stderr']}")
        if r.get("return_value") is not None:
            parts.append(f"Return value:\n{json.dumps(r['return_value'], indent=2)}")
        text = "\n".join(parts) or "Script executed successfully (no output)"
        return h.text_response(text, "script")

    @mcp.tool()
    def manage_extensions(
        action: str = "list",
        extension_id: str = "",
        search: str = "",
        enabled_only: bool = False,
    ) -> str:
        """List, enable, or disable Isaac Sim extensions.

        Args:
            action: "list", "enable", or "disable"
            extension_id: Required for enable/disable
            search: Filter extension list by name (for action="list")
            enabled_only: Only show enabled extensions (for action="list")
        """
        if action == "list":
            resp = _call(client.extensions_list, enabled_only, search)
            err = _check_error(resp)
            if err:
                return err
            r = resp["result"]
            lines = [f"Extensions ({r['count']} found):"]
            for ext in r["extensions"][:50]:
                status = "ON " if ext["enabled"] else "OFF"
                lines.append(f"  [{status}] {ext['id']} v{ext['version']}")
            if r["count"] > 50:
                lines.append(f"  ... and {r['count'] - 50} more")
            text = "\n".join(lines)
            return h.text_response(text, "extensions")
        else:
            if not extension_id:
                return "ERROR: extension_id is required for enable/disable"
            resp = _call(client.extensions_manage, extension_id, action)
            err = _check_error(resp)
            if err:
                return err
            r = resp["result"]
            return f"Extension {r['extension_id']}: {r['action']}d (enabled={r['enabled']})"

    @mcp.tool()
    def get_logs(
        count: int = 50,
        min_level: str = "",
        channel: str = "",
        search: str = "",
    ) -> str:
        """Get recent Omniverse log entries from the ring buffer.

        Use this to investigate errors — when any tool fails, call get_logs()
        to see what Omniverse reported internally.

        Args:
            count: Number of recent entries to return (default 50, max ~2000)
            min_level: Minimum severity: verbose, info, warn, error, fatal
            channel: Filter by log channel substring (e.g. "omni.physx", "omni.usd")
            search: Filter by message substring (case-insensitive)
        """
        resp = _call(client.get_logs, count, min_level, channel, None, search)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        if not r["entries"]:
            return f"No log entries found (buffer has {r['total_captured']} total entries)"
        lines = [f"Log entries ({r['count']}/{r['total_captured']} total, buffer={r['buffer_size']}):"]
        for e in r["entries"]:
            level = e["level"].upper().ljust(5)
            chan = e["channel"][:40] if e["channel"] else ""
            msg = e["msg"][:200]
            lines.append(f"  [{level}] {chan}: {msg}")
        text = "\n".join(lines)
        return h.text_response(text, "logs")
