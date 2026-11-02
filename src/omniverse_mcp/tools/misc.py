"""Miscellaneous tools (execute_script, the script jobs, manage_extensions, get_logs)."""

import json
import re
from typing import TYPE_CHECKING, Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS, RUNS, tool
from ._bridge import TRACEBACK_LINES, bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

# How much of a log message get_logs shows, and how much either side of a search's match it shows when the match lies
# past that: a callstack runs to hundreds or thousands of characters.
SHOWN = 200
AROUND_MATCH = 80


def _log_lines(entry: dict[str, Any], search: str) -> list[str]:
    """An entry as get_logs prints it: its level, its channel whole and the first SHOWN characters of its message,
    saying how many more it has. When `search` matched only past them, a `matched:` line shows the match, where an
    entry whose shown text lacks the word searched for read as a wrong hit (#111)."""
    msg: str = entry["msg"]
    level: str = entry["level"]
    shown = msg[:SHOWN]
    if len(msg) > SHOWN:
        shown += f" ... (+{len(msg) - SHOWN:,} characters)"
    lines = [f"  [{level.upper().ljust(5)}] {entry['channel'] or ''}: {shown}"]
    # The bridge matches the whole message, in any case. A match ending past the shown part shows too little of itself.
    match = re.search(re.escape(search), msg, re.IGNORECASE) if search else None
    if match is not None and match.end() > SHOWN:
        lines.append(f"    matched: {_around(msg, match.start(), match.end())}")
    return lines


def _around(msg: str, start: int, end: int) -> str:
    """The line of `msg` that holds msg[start:end], cut to AROUND_MATCH characters either side of it, with `...` at
    each end cut."""
    line_start = msg.rfind("\n", 0, start) + 1
    line_end = msg.find("\n", end)
    if line_end < 0:
        line_end = len(msg)
    left = max(line_start, start - AROUND_MATCH)
    right = min(line_end, end + AROUND_MATCH)
    return f"{'...' if left > line_start else ''}{msg[left:right].strip()}{'...' if right < line_end else ''}"


def duration(seconds: float) -> str:
    """`12.3s`, `4m 12s` or `1h 2m 3s`: a job's time as get_job and get_sim_state give it."""
    seconds = max(float(seconds), 0.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, whole = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {whole}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {whole}s"


def job_line(job: dict[str, Any]) -> str:
    """A running job as get_sim_state names it: `j3 (script, working, 4m 12s)`."""
    return f"{job['id']} ({job['kind']}, {job['state']}, {duration(job['elapsed'])})"


def _new_lines(r: dict[str, Any]) -> list[str]:
    """The lines a job printed since the last read, with the count of all, as get_job shows them while it runs."""
    total, new, shown = r["lines_total"], r["lines_new"], r["lines"]
    if not new:
        return [f"lines = {total} printed, none since the last read"]
    cut = f", the last {len(shown)} shown" if len(shown) < new else ""
    return [f"lines = {total} printed, {new} since the last read{cut}:", *(f"  {line}" for line in shown)]


def _stream(name: str, text: str, count: int) -> list[str]:
    """A stream of an ended job, saying when only its last lines were kept."""
    if not text:
        return []
    kept = text.count("\n")
    cut = f" (the last {kept} of {count} lines)" if count > kept else ""
    return [f"{name}{cut}:", text.rstrip("\n")]


def _job_text(r: dict[str, Any]) -> str:
    """get_job's answer: the job's state and time, its progress while it runs; once it ends, its result in its kind's
    form, or its error, and what it printed."""
    lines = [f"job = {r['id']} ({r['kind']})"]
    if r.get("label"):
        lines.append(f"label = {r['label']}")
    lines += [f"state = {r['state']}", f"elapsed = {duration(r['elapsed'])}"]
    if r.get("cancelling") is not None:
        lines.append(
            f"cancelling = for {duration(r['cancelling'])}, its cleanup running: a job whose code caught the cancel "
            "runs on until cancel_job cancels it again"
        )
    if r.get("message") and r["state"] != "cancelling":
        lines.append(f"message = {r['message']}")
    if r.get("last"):
        lines.append(f"last = {r['last']}")
    output = r.get("output")
    if output is None:
        return "\n".join(lines + _new_lines(r))
    if r["state"] == "completed":
        result: dict[str, Any] = r.get("result") or {}
        if r["kind"] == "script":
            value = result.get("return_value")
            lines += ["Return value:", json.dumps(value, indent=2)] if value is not None else ["Return value: none"]
        else:
            lines += ["Result:", json.dumps(result, indent=2)]
    elif r["state"] == "failed":
        lines.append(f"error = {r.get('error', '')}")
        traceback = str(r.get("traceback", "")).strip()
        if traceback:
            lines += ["Traceback (its last lines):", *traceback.splitlines()[-TRACEBACK_LINES:]]
    lines += _stream("Stdout", output.get("stdout", ""), output.get("stdout_lines", 0))
    lines += _stream("Stderr", output.get("stderr", ""), output.get("stderr_lines", 0))
    return "\n".join(lines)


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, RUNS)
    def execute_script(
        code: Annotated[str, Field(description="Python to run inside the Kit app; assign to result to return data")],
    ) -> str:
        """Run Python inside the Kit app (Isaac Sim, USD Composer, ...) on its main thread, for what no tool does.

        Prefer a tool that does the job: it checks its input and bounds its waits. The script has omni, carb, Usd,
        UsdGeom, UsdLux, UsdPhysics, Sdf, Gf and mcp. Assign to 'result' to return JSON-serialisable data (anything else
        comes back as its str); stdout and stderr come back too, and an exception as an error with the traceback's last
        lines. A script that blocks freezes Kit: the call gives up after 120 s, and the script runs on. For work that
        may outlast 120 s, such as settling many objects under physics, use run_script_job: it runs as a job while Kit
        renders and other tools answer, and get_job reads its progress and result.

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
    def run_script_job(
        code: Annotated[str, Field(description="Python to run as the job; give this or file")] = "",
        file: Annotated[
            str, Field(description="A .py file on the Kit app's machine to run as the job, read there; or give code")
        ] = "",
    ) -> str:
        """Start a long Python script inside the Kit app as a job, and answer its id at once: for work that may
        outlast execute_script's 120 s, such as dropping and settling many objects under physics one after another.

        The job runs on Kit's main thread between Kit's updates, so Kit renders and other tools answer while it runs.
        It must await once a step: `await omni.kit.app.get_app().next_update_async()` lets one update pass, physics
        stepping while the timeline plays. A script that never awaits is refused, since it would hold Kit from its
        start to its end; one that awaits once and then loops, or calls Isaac Sim's world.step(), holds Kit too, and no
        tool can read or cancel it until it ends. It has execute_script's names (omni, carb, Usd, UsdGeom, UsdLux,
        UsdPhysics, Sdf, Gf, mcp); assign to result to return data. Print a line a step: the lines are the progress
        get_job shows. Read it with get_job(id, wait=60), cancel it with cancel_job. One job runs at a time, and the
        last one is kept until the next starts.
        """
        if bool(code.strip()) == bool(file.strip()):
            raise ToolError("Give the script as code or as file, one of them")
        resp = bridge_call(client.job_script, code, file.strip())
        r = resp["result"]
        return f'Job {r["id"]} started ({r["kind"]}); read it with get_job("{r["id"]}")'

    @tool(mcp, READS)
    def get_job(
        job_id: Annotated[
            str, Field(description="The id run_script_job answered, such as j3; the running or last job when empty")
        ] = "",
        wait: Annotated[
            float,
            Field(
                ge=0,
                le=100,
                description="Seconds to wait for the job to end or change state, at most 100; new lines don't end it",
            ),
        ] = 0,
    ) -> str:
        """Read a job run_script_job started: its state, how long it has run, its last line and the lines it printed
        since the last read; once it has ended, its result, or its error and traceback, and what it printed, each
        stream's last 200 lines.

        States: working; cancelling, while its cleanup runs after a cancel; completed; failed; cancelled. With wait,
        the call returns when the job ends or changes state, or after that many seconds, so a long job is waited for
        without a call every few seconds. With no job_id it reads the running job or the last one, so a job is found
        again after the conversation was compacted. Reading changes nothing in Kit.
        """
        resp = bridge_call(client.job_get, job_id.strip(), wait)
        return h.text_response(_job_text(resp["result"]), "job")

    @tool(mcp, EDITS)
    def cancel_job(
        job_id: Annotated[
            str, Field(min_length=1, description="The job to cancel, as run_script_job answered it, such as j3")
        ],
    ) -> str:
        """Cancel a job run_script_job started, at its next await. It reads cancelling until its own cleanup, its
        finally blocks, has run, then cancelled: get_job(job_id, wait=10) reads it. A job whose code caught the cancel,
        as a bare except does, runs on: call cancel_job again. A job that has ended is left as it is.
        """
        resp = bridge_call(client.job_cancel, job_id.strip())
        r = resp["result"]
        if r["was"] not in ("working", "cancelling"):
            return f"Job {r['id']} had already ended ({r['state']}): nothing to cancel"
        again = " again" if r["was"] == "cancelling" else ""
        return (
            f"Job {r['id']} cancelled{again} at its next await: it reads cancelling until its cleanup has run; read it "
            f'with get_job("{r["id"]}", wait=10)'
        )

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
        search: Annotated[str, Field(description="Only messages containing this anywhere, in any case")] = "",
    ) -> str:
        """Get the latest entries of the Kit app's log, read from its log file since the bridge extension started, by
        level, channel or text.

        Each entry shows its channel and the first 200 characters of its message, saying how many more it has. search
        matches the whole message: an entry whose match lies past the 200 gets a matched: line with the match in its
        line. Kit's file holds Info and above by default; verbose lines need Kit started with both
        --/log/level=verbose and --/log/fileLogLevel=verbose. A script's own exception, print and stderr come back in
        execute_script's answer and never reach Kit's log; carb.log_error and the other carb.log_* calls in a script
        do.
        """
        resp = bridge_call(client.get_logs, count, min_level, channel, None, search)
        r = resp["result"]
        if not r["entries"]:
            text = f"No log entries found (buffer has {r['total_captured']} total entries)"
            # The bridge's note: Kit wrote lines, in a format get_logs doesn't read.
            return f"{text}\n{r['note']}" if r.get("note") else text
        lines = [f"Log entries ({r['count']}/{r['total_captured']} total, buffer={r['buffer_size']}):"]
        for e in r["entries"]:
            lines.extend(_log_lines(e, search))
        text = "\n".join(lines)
        return h.text_response(text, "logs")
