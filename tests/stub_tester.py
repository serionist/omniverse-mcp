"""A stand-in for a headless Claude Code tester, for tests/test_scenario_runs.py: writes stream-json events as
`claude -p --output-format stream-json` does, as step 2 of the scenario-skill plan recorded them.

    python stub_tester.py <mode> <plugin dir>

ok: a clean init, a skill load, and a last message with rows. foreign: an init with another MCP server, then a long
wait the runner must cut short. slow: a clean init, then a long wait. busy: a clean init, then an execute_script
call that gets no answer.
"""

import json
import sys
import time

mode, plugin_dir = sys.argv[1], sys.argv[2]


def say(event: dict) -> None:
    print(json.dumps(event), flush=True)


servers = [{"name": "omniverse", "status": "connected"}]
if mode == "foreign":
    servers.append({"name": "claude_ai_Gmail", "status": "connected"})
say(
    {
        "type": "system",
        "subtype": "init",
        "model": "claude-test-1",
        "tools": ["Glob", "Grep", "Read", "Skill", "mcp__omniverse__get_sim_state"],
        "mcp_servers": servers,
        "plugins": [
            {"name": "omniverse-mcp", "path": plugin_dir, "source": "omniverse-mcp@inline"},
            {"name": "cc-plugin-telemetry", "path": "builtin", "source": "cc-plugin-telemetry@builtin"},
        ],
    }
)
if mode == "busy":
    capture = {"type": "tool_use", "id": "t0", "name": "mcp__omniverse__capture_viewport", "input": {}}
    say({"type": "assistant", "message": {"content": [capture]}})
    failed = "Error executing tool capture_viewport: Kit app connection failed: timed out"
    say(
        {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t0", "is_error": True, "content": failed}]},
        }
    )
    call = {"type": "tool_use", "id": "t1", "name": "mcp__omniverse__execute_script", "input": {"code": "..."}}
    say({"type": "assistant", "message": {"content": [call]}})
if mode in ("foreign", "slow", "busy"):
    time.sleep(60)
    sys.exit(0)
load = {"type": "tool_use", "id": "s1", "name": "Skill", "input": {"skill": "omniverse-mcp:scene"}}
say({"type": "assistant", "message": {"content": [load]}})
loaded = {"type": "tool_result", "tool_use_id": "s1", "content": "Launching skill: omniverse-mcp:scene"}
say({"type": "user", "message": {"content": [loaded]}})
rows = "| ID | Test | Status | Notes |\n|---|---|---|---|\n| 1.1 | Health Check | PASS | state=stopped |"
say({"type": "assistant", "message": {"content": [{"type": "text", "text": f"Done.\n\n{rows}"}]}})
usage = {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "service_tier": "standard"}
say(
    {
        "type": "result",
        "subtype": "success",
        "total_cost_usd": 0.25,
        "num_turns": 3,
        "usage": usage,
        "result": f"Done.\n\n{rows}",
    }
)
