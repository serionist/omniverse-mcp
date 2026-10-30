"""Miscellaneous tools (execute_script, manage_extensions, get_logs)."""

import json
from typing import TYPE_CHECKING, Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import READS, RUNS, tool
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, RUNS)
    def execute_script(
        code: Annotated[str, Field(description="Python to run inside the Kit app; assign to result to return data")],
    ) -> str:
        """Run Python inside the Kit app (Isaac Sim, USD Composer, ...) on its main thread, for what no tool does.

        Prefer a tool that does the job: it checks its input and bounds its waits. The script has omni, carb, Usd,
        UsdGeom, UsdLux, UsdPhysics, Sdf, Gf and mcp. Assign to 'result' to return JSON-serialisable data (anything else
        comes back as its str); stdout and stderr come back too, and an exception as an error with the traceback's last
        lines. A script that blocks freezes Kit: the call gives up after 120 s, and the script runs on.

        `mcp` calls the tools' handlers from the script, each returning a dict with "status" and "result". Await them,
        which makes the script async: `bounds = await mcp.prim_bounds("/World/Cube")`, then
        `result = bounds["result"]`. Its methods: capture_viewport(width, height, camera_path), set_camera(position,
        target), look_at(prim_path, distance, azimuth, elevation), inspect(prim_path, angles, width, height,
        zoom_offset=0.0, isolate=False), scene_tree(root, max_depth), prim_properties(prim_path),
        prim_bounds(prim_path), set_transform(prim_path, position, rotation, scale), create_prim(prim_path, prim_type,
        **kwargs), delete_prim(prim_path), set_material(prim_path, color, opacity, roughness, metallic),
        sim_control(action), sim_state(), get_logs(count, min_level, channel, search).
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

    @tool(mcp, RUNS)
    def manage_extensions(
        action: Annotated[
            Literal["list", "enable", "disable"],
            Field(description='"list" reads; "enable" and "disable" change the running app'),
        ] = "list",
        extension_id: Annotated[
            str, Field(description='For "enable" and "disable", required: the extension, e.g. "omni.syntheticdata"')
        ] = "",
        search: Annotated[
            str, Field(description='For "list": only extensions whose name or id contains this, in any case')
        ] = "",
        enabled_only: Annotated[bool, Field(description='For "list": only enabled extensions')] = False,
    ) -> str:
        """List the Kit app's extensions, or turn one on or off in the running app.

        "list" (the default) only reads: each extension's id, version and whether it is on, the first 50 shown with the
        total. "enable" and "disable" need extension_id, last until Kit restarts, and answer whether the extension is on
        afterwards: enabled=False after an enable means it didn't take. Use enable when a tool names an extension it
        lacks, such as omni.syntheticdata for segmentation. Disabling one that other tools use breaks them, and
        disabling ovmcp.bridge cuts this server off from Kit.
        """
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

    @tool(mcp, READS)
    def get_logs(
        count: Annotated[int, Field(ge=1, description="How many of the latest entries; the buffer keeps 2000")] = 50,
        min_level: Annotated[
            Literal["", "verbose", "info", "warn", "error", "fatal"],
            Field(description="The lowest severity to return; every level when empty"),
        ] = "",
        channel: Annotated[str, Field(description='Only channels containing this, e.g. "omni.physx"')] = "",
        search: Annotated[str, Field(description="Only messages containing this, in any case")] = "",
    ) -> str:
        """Get the latest entries of the Kit app's log, read from its log file since the bridge extension started, by
        level, channel or text.

        Kit's file holds Info and above by default; verbose lines need Kit started with both --/log/level=verbose and
        --/log/fileLogLevel=verbose.
        """
        resp = bridge_call(client.get_logs, count, min_level, channel, None, search)
        r = resp["result"]
        if not r["entries"]:
            text = f"No log entries found (buffer has {r['total_captured']} total entries)"
            # The bridge's note: Kit wrote lines, in a format get_logs doesn't read.
            return f"{text}\n{r['note']}" if r.get("note") else text
        lines = [f"Log entries ({r['count']}/{r['total_captured']} total, buffer={r['buffer_size']}):"]
        for e in r["entries"]:
            level = e["level"].upper().ljust(5)
            chan = e["channel"][:40] if e["channel"] else ""
            msg = e["msg"][:200]
            lines.append(f"  [{level}] {chan}: {msg}")
        text = "\n".join(lines)
        return h.text_response(text, "logs")
