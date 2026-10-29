"""Miscellaneous tools (execute_script, manage_extensions, get_logs)."""

import json
from typing import TYPE_CHECKING, Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import READS, RUNS
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=RUNS)
    def execute_script(
        code: Annotated[str, Field(description="Python to run inside the Kit app; assign to result to return data")],
    ) -> str:
        """Execute Python inside the running Kit app (Isaac Sim, USD Composer, ...).

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
            mcp.inspect(prim_path, angles, width, height, zoom_offset=0.0, isolate=False)
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
        resp = bridge_call(client.execute, code)

        r = resp["result"]
        parts: list[str] = []
        if r.get("stdout"):
            parts.append(f"Stdout:\n{r['stdout']}")
        if r.get("stderr"):
            parts.append(f"Stderr:\n{r['stderr']}")
        if r.get("return_value") is not None:
            parts.append(f"Return value:\n{json.dumps(r['return_value'], indent=2)}")
        text = "\n".join(parts) or "Script executed successfully (no output)"
        return h.text_response(text, "script")

    @mcp.tool(annotations=RUNS)
    def manage_extensions(
        action: Annotated[Literal["list", "enable", "disable"], Field(description="What to do")] = "list",
        extension_id: Annotated[str, Field(description="The extension to enable or disable")] = "",
        search: Annotated[str, Field(description='For "list": only extensions whose name contains this')] = "",
        enabled_only: Annotated[bool, Field(description='For "list": only enabled extensions')] = False,
    ) -> str:
        """List, enable, or disable the Kit app's extensions."""
        if action == "list":
            resp = bridge_call(client.extensions_list, enabled_only, search)
            r = resp["result"]
            lines = [f"Extensions ({r['count']} found):"]
            for ext in r["extensions"][:50]:
                status = "ON " if ext["enabled"] else "OFF"
                lines.append(f"  [{status}] {ext['id']} v{ext['version']}")
            if r["count"] > 50:
                lines.append(f"  ... and {r['count'] - 50} more")
            text = "\n".join(lines)
            return h.text_response(text, "extensions")
        if not extension_id:
            raise ToolError("extension_id is required for enable/disable")
        resp = bridge_call(client.extensions_manage, extension_id, action)
        r = resp["result"]
        return f"Extension {r['extension_id']}: {r['action']}d (enabled={r['enabled']})"

    @mcp.tool(annotations=READS)
    def get_logs(
        count: Annotated[int, Field(ge=1, description="How many of the latest entries; the buffer keeps 2000")] = 50,
        min_level: Annotated[
            Literal["", "verbose", "info", "warn", "error", "fatal"],
            Field(description="The lowest severity to return; every level when empty"),
        ] = "",
        channel: Annotated[str, Field(description='Only channels containing this, e.g. "omni.physx"')] = "",
        search: Annotated[str, Field(description="Only messages containing this, in any case")] = "",
    ) -> str:
        """Get recent entries of the Kit app's log, read from its log file since the bridge extension started.

        Use this to investigate errors: when any tool fails, call get_logs() to see what the Kit app reported. Kit's
        file holds Info and above by default; verbose lines need Kit started with both --/log/level=verbose and
        --/log/fileLogLevel=verbose.
        """
        resp = bridge_call(client.get_logs, count, min_level, channel, None, search)
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
