"""The AI scenario suite's runs (tools/scenarios.py, #102): scenarios.md's phases and their Needs: lines, which
sessions a run holds, what a tester is told and what is read back, the checks before a run, a session's stream, and
the comparison of runs."""

import json
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import gate
import pytest
import scenarios

from .mock_bridge import MockIsaacServer

ROOT = Path(__file__).resolve().parents[1]
STUB = Path(__file__).with_name("stub_tester.py")


@pytest.fixture(scope="module")
def suite():
    return scenarios.parse(scenarios.SCENARIOS.read_text(encoding="utf-8"))


def labels(sessions):
    return [(s.label, s.ids if s.kind == "setup" else None, s.new_stage) for s in sessions]


# ----- scenarios.md -----


def test_the_real_scenarios_parse_with_every_needs_line_sound(suite):
    assert len(suite.phases) == 27
    # 16.9 left the suite for pytest's test_16_09 (#146), a SKIP in every run; 23.7 sets a light's intensity (#151).
    assert sum(len(p.scenarios) for p in suite.phases) == 144
    assert suite.scenario("16.9") is None
    assert scenarios.suite_problems(suite) == []
    assert suite.scenario("6.4-6.9") is not None
    assert "swap each vector's Y and Z" in suite.header
    assert suite.cleanup == 27


SMALL = """# Title

Header line.

## Phase 1: One

Needs: none

### 1.1 First
- a

## Phase 2: Two

### 2.1 Second
- b

## Phase 3: Three

Needs: 4.1, 9.9

### 3.1 Third

## Phase 4: Four

Needs: none

### 4.1 Fourth
"""


def test_a_missing_or_wrong_needs_line_is_named():
    problems = scenarios.suite_problems(scenarios.parse(SMALL))
    assert any("Phase 2: no `Needs:` line" in p for p in problems)
    assert any("Phase 3: needs 4.1, which doesn't come before it" in p for p in problems)
    assert any("Phase 3: needs 9.9, which no heading names" in p for p in problems)


def test_needs_may_not_cross_the_new_stage_nor_fill_the_cleanup_line(suite):
    text = scenarios.SCENARIOS.read_text(encoding="utf-8")
    crossing = text.replace("## Phase 19: USD Operations\n\nNeeds: 18.2", "## Phase 19: USD Operations\n\nNeeds: 2.1")
    cleanup = text.replace("## Phase 27: Cleanup\n\nNeeds: none", "## Phase 27: Cleanup\n\nNeeds: 2.1")
    assert any("across Phase 17's new stage" in p for p in scenarios.suite_problems(scenarios.parse(crossing)))
    assert any("the cleanup phase" in p for p in scenarios.suite_problems(scenarios.parse(cleanup)))


@pytest.mark.parametrize(
    ("value", "expected"),
    [("15", {15}), ("15-16", {15, 16}), ("18-21,24", {18, 19, 20, 21, 24}), ("", set(range(1, 28)))],
)
def test_phases_asked(suite, value, expected):
    assert scenarios.phases_asked(value, suite) == expected


@pytest.mark.parametrize("value", ["0", "26-30", "x", "5-3", "1-2-3"])
def test_phases_asked_refuses_what_scenarios_md_lacks(suite, value):
    with pytest.raises(ValueError, match="--phases"):
        scenarios.phases_asked(value, suite)


# ----- which sessions a run holds -----


def test_setup_runs_just_before_the_phase_after_it(suite):
    # 4.5 needs 2.1, which Phase 2 makes, so it can't run before Phase 2 (round 2, P14).
    assert labels(scenarios.plan(suite, {2, 5})) == [
        ("phase-02", None, True),
        ("setup-05", ("4.5",), False),
        ("phase-05", None, False),
        ("phase-27", None, False),
    ]


def test_each_half_starts_on_a_new_stage_with_its_own_setup(suite):
    assert labels(scenarios.plan(suite, {15, 20})) == [
        ("setup-15", ("2.1", "4.5", "10.1"), True),
        ("phase-15", None, False),
        ("setup-20", ("18.1", "18.2"), True),
        ("phase-20", None, False),
        ("phase-27", None, False),
    ]


def test_a_first_half_phase_alone_ends_with_the_cleanup_and_no_second_half(suite):
    assert [s.label for s in scenarios.plan(suite, {15})] == ["setup-15", "phase-15", "phase-27"]


def test_needs_resolve_through_the_phases_they_name(suite):
    # 26 needs 23.2, whose phase needs 18.2.
    assert labels(scenarios.plan(suite, {26}))[0] == ("setup-26", ("18.2", "23.2"), True)


def test_a_full_run_needs_no_setup_and_starts_two_stages(suite):
    sessions = scenarios.plan(suite, scenarios.phases_asked("", suite))
    assert [s.label for s in sessions] == [f"phase-{n:02d}" for n in range(1, 28)]
    assert [s.phase for s in sessions if s.new_stage] == [1, 18]


# ----- what a tester is told, and what it answers -----


def test_a_prompt_holds_the_header_the_phase_its_needs_and_the_answer_asked(suite, tmp_path):
    sessions = scenarios.plan(suite, {2, 5})
    text = scenarios.prompt(suite, sessions[2], {"2.1": "PASS", "4.5": "FAIL"}, tmp_path, 8212)
    assert "port 8212" in text
    assert "swap each vector's Y and Z" in text  # the header, with its axis rule (I8)
    assert "## Phase 5: Simulation & Physics" in text
    assert "2.1 PASS, 4.5 FAIL" in text
    assert "before anything else" not in text
    assert "one row for each of 5.1, 5.2, 5.3" in text


def test_a_prompt_fills_in_the_run_folder_and_starts_a_stage_when_first(suite, tmp_path):
    sessions = scenarios.plan(suite, {17})
    text = scenarios.prompt(suite, sessions[0], {}, tmp_path, 8212)
    # The scenarios' vectors are written for Y-up, and new_scene() alone makes a Z-up stage (#159).
    assert 'call new_scene(up_axis="Y") before anything else' in text
    assert f'"{tmp_path.as_posix()}/kit/mcp_test_scene.usd"' in text
    assert "<run>/kit" not in text.split("The scenarios' header:")[1].split("Run this phase:")[1]


def test_a_setup_prompt_holds_its_scenarios_and_what_they_need(suite, tmp_path):
    sessions = scenarios.plan(suite, {2, 5})
    text = scenarios.prompt(suite, sessions[1], {"2.1": "PASS"}, tmp_path, 8212)
    assert "### 4.5 Add Physics via Script" in text
    assert "2.1 PASS" in text
    assert "### 5.1" not in text


def test_rows_come_from_the_last_matching_table():
    text = """Earlier:

| ID | Test | Status | Notes |
|---|---|---|---|
| 1.1 | Old | FAIL | before |

Final:

| ID | Test | Status | Notes |
|----|------|--------|-------|
| 1.1 | Health Check | **PASS** | a \\| b |
| 6.4 to 6.9 | Recording | warn | odd |
| 1.2 | Tree | MAYBE | unsure |
| 9.9 | Not asked | PASS | x |
"""
    rows = scenarios.rows_from(text, ["1.1", "1.2", "6.4-6.9", "2.1"])
    assert rows["1.1"].status == "PASS"
    assert rows["1.1"].notes == "a | b"
    assert rows["6.4-6.9"].status == "WARN"
    assert rows["1.2"].status == scenarios.NOT_RUN
    assert "MAYBE" in rows["1.2"].notes
    assert "2.1" not in rows
    assert "9.9" not in rows


def test_no_table_gives_no_rows():
    assert scenarios.rows_from("I couldn't run it.", ["1.1"]) == {}


# ----- a session's configuration and command -----


def test_each_session_writes_its_files_to_a_folder_of_its_own(suite, tmp_path):
    # Each session's server numbers its files from 1: in one folder, Phase 16's captures replaced Phase 3's (step 9).
    first, second = scenarios.plan(suite, {1, 2})[:2]
    assert scenarios.session_output(tmp_path, first) == tmp_path / "mcp_output" / "phase-01"
    assert scenarios.session_output(tmp_path, first) != scenarios.session_output(tmp_path, second)


def test_the_config_holds_the_skills_without_their_server_and_the_server_pinned(tmp_path):
    run_dir = tmp_path / "run"
    scenarios.write_config(tmp_path / "config", 8212, run_dir / "mcp_output" / "phase-03")
    plugin = tmp_path / "config" / "plugin"
    assert (plugin / "skills" / "scene" / "SKILL.md").is_file()
    assert not (plugin / ".mcp.json").exists()  # the strict MCP flag drops a plugin's server (step 2, S1)
    server = json.loads((tmp_path / "config" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["omniverse"]
    assert server["args"] == ["run", "--no-sync", "--project", ROOT.as_posix(), "omniverse-mcp"]
    assert server["env"] == {
        "PYTHONPATH": "",
        "OMNIVERSE_MCP_HOST": "127.0.0.1",
        "OMNIVERSE_MCP_PORT": "8212",
        "OMNIVERSE_MCP_TOKEN": "",
        "OMNIVERSE_MCP_OUTPUT_DIR": (run_dir / "mcp_output" / "phase-03").as_posix(),
    }


def test_the_tester_command_is_the_one_step_2_proved(tmp_path):
    cmd = scenarios.tester_command("claude", tmp_path, "RULES", 1.5, "opus")
    # The prompt goes to stdin: a judge's passed Windows' limit for a command line in the first outcome run (#146).
    assert cmd[:3] == ["claude", "-p", "--plugin-dir"]
    joined = " ".join(cmd)
    for part in (
        "--strict-mcp-config",
        "--setting-sources  --append-system-prompt RULES",
        "--tools Read,Grep,Glob,Skill",
        "--permission-mode dontAsk",
        "--allowedTools mcp__omniverse Read Grep Glob Skill(omniverse-mcp:geometry) Skill(omniverse-mcp:report-bug) "
        "Skill(omniverse-mcp:scene) Skill(omniverse-mcp:script) Skill(omniverse-mcp:setup) "
        "Skill(omniverse-mcp:simulate) --output-format",
        "--output-format stream-json --verbose --no-session-persistence",
        "--max-budget-usd 1.50",
        "--model opus",
    ):
        assert part in joined
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob,Skill"
    assert "Write" not in cmd and "Edit" not in cmd  # the tester writes nothing (I1)
    assert scenarios.tester_env()["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


# ----- check -----


def test_8211_is_refused_before_any_request_or_token_read(tmp_path, monkeypatch):
    def nothing(*_args):
        raise AssertionError("reached I/O for a refused port")

    monkeypatch.setattr(scenarios, "token_path", nothing)
    problems, _ = scenarios.check(8211, tmp_path, connect=nothing)
    assert len(problems) == 1
    assert "--allow-port-8211" in problems[0]


def test_no_token_file_says_how_to_start_kit(tmp_path, state):
    problems, _ = scenarios.check(8212, tmp_path, connect=lambda port: pytest.fail("connected"))
    assert "no bridge token" in problems[0]
    assert "--/exts/ovmcp.bridge/port=<port>" in problems[0]


@pytest.mark.parametrize(
    ("stage", "allowed"),
    [
        ("(unsaved)", True),
        ("", True),
        ("RUNS/20261101-000000/kit/opened_scene.usda", True),
        ("TEMP/ovmcp-open-1/gone.usda", True),
        ("TEMP/there.usda", False),
        ("OTHER/scene.usd", False),
        ("omniverse://server/scene.usd", False),
        ("https://example.com/scene.usd", False),
    ],
)
def test_the_stage_rule(tmp_path, stage, allowed):
    runs, temp, other = tmp_path / "runs", tmp_path / "temp", tmp_path / "other"
    for folder in (runs, temp, other):
        folder.mkdir()
    (temp / "there.usda").write_text("#usda 1.0\n", encoding="utf-8")
    (other / "scene.usd").write_text("", encoding="utf-8")
    path = stage.replace("RUNS", str(runs)).replace("TEMP", str(temp)).replace("OTHER", str(other))
    assert (scenarios.stage_problem(path, runs, temp) is None) is allowed


def copy_bridge(dest: Path) -> list[str]:
    tracked = scenarios.tracked_bridge_files()
    for rel in tracked:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / scenarios.BRIDGE / rel, dest / rel)
    return tracked


def test_a_copy_of_the_bridge_passes_with_kits_caches_in_it(tmp_path):
    tracked = copy_bridge(tmp_path)
    cache = tmp_path / "ovmcp" / "core" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "capture.cpython-311.pyc").write_bytes(b"\0")
    assert scenarios.bridge_problems(ROOT, tmp_path, tracked) == []


def test_a_copy_with_crlf_line_endings_is_the_same_bridge(tmp_path):
    # A copy from a Windows checkout made before .gitattributes, or from a zip, keeps CRLF: git stores it as LF.
    tracked = copy_bridge(tmp_path)
    for rel in tracked:
        path = tmp_path / rel
        data = path.read_bytes()
        # Git converts text only: .gitattributes marks the bridge's images binary, and they keep their bytes.
        if b"\0" not in data:
            path.write_bytes(data.replace(b"\n", b"\r\n"))
    assert scenarios.bridge_problems(ROOT, tmp_path, tracked) == []
    (tmp_path / tracked[0]).write_bytes(b"changed\r\n")
    assert tracked[0] in scenarios.bridge_problems(ROOT, tmp_path, tracked)[0]


def test_a_bridge_that_differs_is_named(tmp_path):
    tracked = copy_bridge(tmp_path)
    (tmp_path / "config" / "extension.toml").write_text("[package]\n", encoding="utf-8")
    (tmp_path / "ovmcp" / "extra.py").write_text("", encoding="utf-8")
    problems = scenarios.bridge_problems(ROOT, tmp_path, tracked)
    assert "config/extension.toml" in problems[0]
    assert "ovmcp/extra.py" in problems[1]
    assert "isn't on this machine" in scenarios.bridge_problems(ROOT, tmp_path / "nowhere", tracked)[0]


@pytest.fixture
def kit(tmp_path, state):
    bridge = MockIsaacServer()
    bridge.set_response("/bridge", {"status": "success", "result": {"protocol": 1, "extension_version": "0.3.0"}})
    bridge.set_response(
        "/health", {"status": "success", "result": {"stage_path": "(unsaved)", "extension_version": "0.3.0"}}
    )
    folder = tmp_path / "kit-bridge"
    copy_bridge(folder)
    facts = {"folder": str(folder), "app": "Isaac-Sim", "version": "6.2.0", "kit": "110.0"}
    bridge.set_response("/execute", {"status": "success", "result": {"return_value": facts}})
    bridge.set_response("/sim/state", {"status": "success", "result": {"prim_count": 11}})
    bridge.start()
    (state / f"bridge-{bridge.port}.token").write_text("fake-token", encoding="utf-8")
    yield bridge
    bridge.stop()


def test_check_passes_a_kit_app_with_this_checkouts_bridge(kit, tmp_path):
    problems, found = scenarios.check(kit.port, tmp_path / "runs")
    assert problems == []
    assert (found.app, found.version, found.prim_count, found.stage) == ("Isaac-Sim", "6.2.0", 11, "(unsaved)")
    assert "Isaac-Sim 6.2.0" in scenarios.describe(found, kit.port)


def test_check_refuses_a_saved_stage_and_a_held_lock(kit, tmp_path):
    kit.set_response(
        "/health", {"status": "success", "result": {"stage_path": str(ROOT / "README.md"), "extension_version": "x"}}
    )
    runs = tmp_path / "runs"
    runs.mkdir()
    scenarios.lock_path(runs, kit.port).write_text("run 20261101-000000\n", encoding="utf-8")
    problems, _ = scenarios.check(kit.port, runs)
    assert "README.md open" in problems[0]
    assert "delete the file once no run is going" in problems[1]
    problems, _ = scenarios.check(kit.port, runs, any_stage=True)
    assert len(problems) == 1


def test_allow_port_8211_passes_the_port_rule(state, tmp_path):
    # With the override, check goes on to the next rule: here, no token file for 8211.
    problems, _ = scenarios.check(8211, tmp_path, allow_gui_port=True, connect=lambda port: pytest.fail("connected"))
    assert "no bridge token" in problems[0]


def test_any_bridge_passes_a_bridge_that_differs(kit, tmp_path):
    other = tmp_path / "other-bridge"
    other.mkdir()
    facts = {"folder": str(other), "app": "Isaac-Sim", "version": "6.2.0", "kit": "110.0"}
    kit.set_response("/execute", {"status": "success", "result": {"return_value": facts}})
    problems, _ = scenarios.check(kit.port, tmp_path / "runs")
    assert "differs from this checkout's" in problems[0]
    assert scenarios.check(kit.port, tmp_path / "runs", any_bridge=True)[0] == []


def test_a_kit_that_answers_with_a_refusal_says_so(kit, tmp_path):
    # Not "no answer": starting Kit wouldn't mend a refused token or a failed script (round 1, IA5).
    kit.set_response("/health", {"status": "error", "error": "the token was refused"})
    problems, _ = scenarios.check(kit.port, tmp_path / "runs")
    assert problems == [f"the Kit app at 127.0.0.1:{kit.port} refused: the token was refused"]


def test_settle_stops_the_timeline_and_a_recording_left_running(kit):
    scenarios.settle(kit.port)
    paths = [path for _, path, _ in kit.requests]
    assert ("POST", "/sim/control", {"action": "stop"}) in kit.requests
    assert "/sim/state" in paths
    assert "/recording/stop" not in paths
    kit.set_response("/sim/state", {"status": "success", "result": {"recording_active": True}})
    scenarios.settle(kit.port)
    assert "/recording/stop" in [path for _, path, _ in kit.requests]


def test_check_says_when_no_kit_answers(state, tmp_path):
    (state / "bridge-1.token").write_text("fake-token", encoding="utf-8")
    problems, _ = scenarios.check(1, tmp_path)
    assert "no answer from a Kit app at 127.0.0.1:1" in problems[0]


# ----- one session -----


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def watch_over(clock: Clock, busy_from: float, busy_until: float):
    """A watch whose probes take 20 s each while Kit is busy, and answer at once otherwise."""

    def probe() -> bool:
        if busy_from <= clock.now < busy_until:
            clock.now += scenarios.PROBE_SECONDS
            return False
        return True

    return scenarios.HealthWatch(probe, clock)


def drive(watch, clock: Clock, until: float):
    while clock.now < until:
        if reason := watch.check():
            return clock.now, reason
        clock.now += 1
    return None


def test_a_long_call_just_before_a_probe_doesnt_stop_the_run():
    # A probe answers at 0; a handler holds Kit from 29 s for 120 s, within the server's call limit (round 2, P15).
    clock = Clock()
    assert drive(watch_over(clock, 29, 149), clock, 400) is None


def test_a_kit_that_stays_silent_stops_the_run_140_s_after_the_first_unanswered_probe():
    clock = Clock()
    stopped = drive(watch_over(clock, 29, 10_000), clock, 400)
    assert stopped is not None
    at, reason = stopped
    assert 30 + scenarios.SILENCE_LIMIT <= at <= 30 + scenarios.SILENCE_LIMIT + scenarios.PROBE_EVERY
    assert "Kit stopped answering" in reason


B2_INIT = {
    "type": "system",
    "subtype": "init",
    "tools": ["Glob", "Grep", "Read", "Skill", "mcp__omniverse__get_sim_state"],
    "mcp_servers": [{"name": "omniverse", "status": "connected", "source": "dynamic"}],
    "plugins": [
        {"name": "omniverse-mcp", "path": "PLUGIN", "source": "omniverse-mcp@inline"},
        {"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"},
    ],
    "memory_paths": None,
}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, None),
        ({"mcp_servers": [{"name": "omniverse", "status": "connected"}, {"name": "claude_ai_Gmail"}]}, "MCP servers"),
        ({"mcp_servers": [{"name": "omniverse", "status": "failed"}]}, "not connected"),
        ({"tools": ["Read", "Bash"]}, "tools outside the run's list: Bash"),
        ({"plugins": [{"name": "slack", "path": "C:/plugins/slack"}]}, "a plugin other than the run's"),
        ({"memory_paths": {"auto": "C:/Users/me/.claude/projects/x/memory/"}}, "a memory path"),
    ],
)
def test_the_init_check(tmp_path, change, expected):
    event = json.loads(json.dumps(B2_INIT).replace("PLUGIN", tmp_path.as_posix())) | change
    problems = scenarios.init_problems(event, tmp_path)
    if expected is None:
        assert problems == []
    else:
        assert any(expected in p for p in problems), problems


def stub(mode: str, plugin_dir: Path) -> list[str]:
    return [sys.executable, str(STUB), mode, str(plugin_dir)]


def test_a_session_reads_its_model_skills_cost_and_rows(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    outcome = scenarios.run_session(stub("ok", tmp_path), transcript, tmp_path, cwd=tmp_path)
    assert (outcome.exit, outcome.stopped, outcome.model) == (0, "", "claude-test-1")
    assert outcome.skills == ["omniverse-mcp:scene"]
    assert (outcome.cost, outcome.cost_known) == (0.25, True)
    assert outcome.tokens == {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100}
    assert outcome.started and outcome.ended
    assert scenarios.rows_from(outcome.text, ["1.1"])["1.1"].status == "PASS"
    assert len(transcript.read_text(encoding="utf-8").splitlines()) == 5


def test_the_prompt_reaches_the_tester_by_stdin_whatever_its_length(tmp_path):
    # A judge's prompt, with the agent's calls and answers, passed Windows' 32,767 characters for a command line (#146).
    prompt = "You judge outcome O1.\n" + "x" * 100_000
    outcome = scenarios.run_session(stub("echo", tmp_path), tmp_path / "t.jsonl", tmp_path, cwd=tmp_path, prompt=prompt)
    assert outcome.text == f"read {len(prompt)} characters, the first line 'You judge outcome O1.'"


def test_a_tester_that_ends_without_reading_its_prompt_ends_the_session_as_usual(tmp_path):
    prompt = "x" * 100_000  # more than a pipe holds, so the feeder's write meets a closed pipe
    outcome = scenarios.run_session(stub("deaf", tmp_path), tmp_path / "t.jsonl", tmp_path, cwd=tmp_path, prompt=prompt)
    assert (outcome.exit, outcome.text) == (0, "done without reading")


def test_a_foreign_server_stops_the_tester_at_once(tmp_path):
    began = time.monotonic()
    outcome = scenarios.run_session(stub("foreign", tmp_path), tmp_path / "t.jsonl", tmp_path, cwd=tmp_path)
    assert time.monotonic() - began < 30
    assert "claude_ai_Gmail" in outcome.stopped


def test_a_session_stops_at_its_limit(tmp_path):
    outcome = scenarios.run_session(stub("slow", tmp_path), tmp_path / "t.jsonl", tmp_path, limit=2, cwd=tmp_path)
    assert "limit" in outcome.stopped


def test_a_silent_kit_stops_the_session_and_says_what_may_hold_it(tmp_path):
    # Step 9's full run: a tester's own script held Kit's main thread, and Kit answered again after it.
    clock = Clock()

    def silent() -> bool:
        clock.now += 100
        return False

    watch = scenarios.HealthWatch(silent, clock)
    outcome = scenarios.run_session(stub("busy", tmp_path), tmp_path / "t.jsonl", tmp_path, watch, cwd=tmp_path)
    assert outcome.kit_hung
    assert "a script holding Kit's main thread, or a hang inside Kit" in outcome.stopped


def test_the_stop_names_the_call_in_flight_and_the_one_that_timed_out():
    # Step 9's rerun: capture_viewport timed out inside NVIDIA's driver, then get_logs got no answer either.
    def event(kind, part):
        return json.dumps({"type": kind, "message": {"content": [part]}})

    outcome = scenarios.Outcome()
    for line in (
        event("assistant", {"type": "tool_use", "id": "a", "name": "mcp__omniverse__capture_viewport"}),
        event("user", {"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "...: timed out"}),
        event("assistant", {"type": "tool_use", "id": "b", "name": "mcp__omniverse__get_logs"}),
    ):
        scenarios._read_event(line, outcome, Path())
    message = scenarios.stop_message("Kit stopped answering", outcome)
    assert message.startswith("Kit stopped answering, while `get_logs` ran, after `capture_viewport` timed out: ")


def stream(*events):
    """Stream lines for _read_event, one per (kind, part) pair, and nothing else: no init event unless one is given."""
    return [json.dumps({"type": kind, "message": {"content": [part]}}) for kind, part in events]


def test_only_a_plugin_skill_that_loaded_counts(tmp_path):
    # A bundled skill dontAsk refused, and a load still waiting for its result, aren't loads (round 1, F3).
    outcome = scenarios.Outcome()
    for line in [
        json.dumps(B2_INIT).replace("PLUGIN", tmp_path.as_posix()),
        *stream(
            ("assistant", {"type": "tool_use", "id": "a", "name": "Skill", "input": {"skill": "keybindings-help"}}),
            ("user", {"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "denied"}),
            ("assistant", {"type": "tool_use", "id": "b", "name": "Skill", "input": {"skill": "omniverse-mcp:scene"}}),
            ("user", {"type": "tool_result", "tool_use_id": "b", "content": "Launching skill: omniverse-mcp:scene"}),
            ("assistant", {"type": "tool_use", "id": "c", "name": "Skill", "input": {"skill": "omniverse-mcp:script"}}),
        ),
    ]:
        scenarios._read_event(line, outcome, tmp_path)
    assert outcome.skills == ["omniverse-mcp:scene"]


def test_a_session_that_acts_before_its_init_event_is_stopped(tmp_path):
    outcome = scenarios.Outcome()
    (line,) = stream(("assistant", {"type": "tool_use", "id": "a", "name": "mcp__omniverse__new_scene"}))
    scenarios._read_event(line, outcome, tmp_path)
    assert outcome.init_failed
    assert "before its init event" in outcome.stopped


def test_an_error_in_the_session_still_ends_the_tester(tmp_path, monkeypatch):
    # An interrupt or an error mustn't leave a tester driving Kit with execute_script pre-approved (round 1, F5).
    ended = []
    real_end_tree = scenarios.end_tree

    def end_tree(proc):
        ended.append(proc.pid)
        real_end_tree(proc)

    def broken(*_args):
        raise RuntimeError("a failed write")

    monkeypatch.setattr(scenarios, "end_tree", end_tree)
    monkeypatch.setattr(scenarios, "_read_event", broken)
    with pytest.raises(RuntimeError, match="a failed write"):
        scenarios.run_session(stub("slow", tmp_path), tmp_path / "t.jsonl", tmp_path, cwd=tmp_path)
    assert len(ended) == 1


# ----- a run -----


def outcome(text="", cost=0.1, **kw):
    fields = {"exit": 0, "text": text, "cost": cost, "cost_known": True, "model": "claude-test-1"} | kw
    return scenarios.Outcome(**fields)


def table(*rows):
    return "| ID | Test | Status | Notes |\n|---|---|---|---|\n" + "\n".join(f"| {r} |" for r in rows)


def test_a_run_tells_each_session_the_status_of_what_it_needs(suite, tmp_path):
    seen = []

    def launch(session, text, left):
        seen.append(text)
        if session.label == "phase-02":
            return outcome(
                table(*[f"{s.id} | t | {'FAIL' if s.id == '2.1' else 'PASS'} | n" for s in suite.phase(2).scenarios])
            )
        return outcome("I couldn't finish.")

    records, rows = scenarios.run_sessions(suite, scenarios.plan(suite, {2, 5}), tmp_path, 8212, launch, lambda: None)
    assert "2.1 FAIL" in seen[1]
    by_id = {r.id: r for r in rows}
    assert by_id["2.1"].status == "FAIL"
    assert by_id["4.5"].status == scenarios.NOT_RUN and by_id["4.5"].setup
    assert (tmp_path / "phase-02.md").is_file()
    assert [r.label for r in records] == ["phase-02", "setup-05", "phase-05", "phase-27"]


def test_the_budget_and_a_hung_kit_stop_the_next_sessions(suite, tmp_path):
    budgets = []

    def launch(session, text, left):
        budgets.append(left)
        return outcome(cost=0.6)

    records, _ = scenarios.run_sessions(suite, scenarios.plan(suite, {1, 2}), tmp_path, 8212, launch, lambda: None, 1.0)
    assert budgets == [1.0, pytest.approx(0.4)]
    assert "budget" in records[2].stopped

    def hangs(session, text, left):
        return outcome(stopped="Kit stopped answering (#54)", kit_hung=True)

    records, rows = scenarios.run_sessions(suite, scenarios.plan(suite, {1, 2}), tmp_path, 8212, hangs, lambda: None)
    assert records[1].stopped.startswith("not run: Kit stopped answering")
    assert {r.status for r in rows} == {scenarios.NOT_RUN}


def test_a_kit_that_cant_be_settled_stops_the_run(suite, tmp_path):
    def settle():
        raise OSError("refused")

    records, _ = scenarios.run_sessions(
        suite, scenarios.plan(suite, {1}), tmp_path, 8212, lambda *a: pytest.fail("launched"), settle
    )
    assert all("Kit didn't answer between sessions" in r.stopped for r in records)


def test_a_stopped_session_counts_its_whole_allowance_and_its_cost_as_unknown(suite, tmp_path):
    # A tester the script stops sends no result event: its spend still counts, so --budget stays a cap (round 1, F2).
    budgets = []

    def launch(session, text, left):
        budgets.append(left)
        return outcome(cost=0.0, cost_known=False, stopped="stopped at the session's limit, 900 s")

    records, _ = scenarios.run_sessions(suite, scenarios.plan(suite, {1, 2}), tmp_path, 8212, launch, lambda: None, 1.0)
    assert budgets == [1.0]
    assert records[1].stopped == "not run: the budget may be spent: phase-01's cost is unknown"
    record = {"sessions": [asdict(r) for r in records]}
    assert "cost unknown for phase-01" in scenarios.results_md(record)


def test_a_failed_init_check_stops_the_run(suite, tmp_path):
    # The same flags give every session the same init event (round 1, IA2).
    launched = []

    def launch(session, text, left):
        launched.append(session.label)
        return outcome(stopped="the session's init event: MCP servers ['x']", init_failed=True)

    records, _ = scenarios.run_sessions(suite, scenarios.plan(suite, {1, 2}), tmp_path, 8212, launch, lambda: None)
    assert launched == ["phase-01"]
    assert records[1].stopped.startswith("not run: the session's init event")


def test_results_md_lists_rows_in_order_and_the_issues():
    record = {
        "name": "20261102-141000",
        "kit": {"app": "Isaac-Sim", "version": "6.2.0"},
        "sessions": [{"label": "phase-01", "skills": [], "stopped": ""}],
        "rows": [
            {"id": "10.1", "test": "Spawn", "status": "PASS", "notes": "ok", "setup": True},
            {"id": "2.1", "test": "Create", "status": "FAIL", "notes": "a | b"},
        ],
    }
    text = scenarios.results_md(record)
    assert text.index("| 2.1 |") < text.index("| 10.1 |")
    assert "setup: ok" in text
    assert "a \\| b" in text
    assert "- **FAIL 2.1** Create" in text
    assert "| phase-01 | none |" in text


# ----- compare -----


def run_record(name, rows, commit="c0", models=("claude-test-1",), skills=()):
    return {
        "name": name,
        "commit": commit,
        "models": list(models),
        "port": 8212,
        "sessions": [{"label": "phase-01", "skills": list(skills)}, {"label": "phase-02", "skills": []}],
        "rows": [{"id": i, "test": "t", "status": s, "notes": f"{i} {s}"} for i, s in rows],
    }


def test_compare_names_regressions_fixes_new_and_not_run():
    old = run_record(
        "20261101-000000", [("1.1", "PASS"), ("1.2", "FAIL"), ("1.3", "FAIL"), ("2.1", "PASS"), ("2.2", "WARN")]
    )
    older = run_record("20261031-000000", [("3.1", "PASS")], models=("claude-old",))
    new = run_record(
        "20261102-000000",
        [
            ("1.1", "FAIL"),
            ("1.2", "PASS"),
            ("1.3", "WARN"),
            ("2.1", scenarios.NOT_RUN),
            ("2.2", "SKIP"),
            ("3.1", "PASS"),
            ("4.1", "PASS"),
        ],
        skills=("omniverse-mcp:scene",),
    )
    new["sessions"].append({"label": "phase-03", "skills": [], "stopped": "not run: Kit stopped answering"})
    report = scenarios.compare(new, [older, old])
    assert [e["now"]["id"] for e in report["regressions"]] == ["1.1"]
    assert [e["now"]["id"] for e in report["fixed"]] == ["1.2"]
    # FAIL to WARN is the same answer judged again, step 9 found, so no fix.
    assert [e["now"]["id"] for e in report["changed"]] == ["1.3", "2.2"]
    assert [r["id"] for r in report["new"]] == ["4.1"]
    assert [r["id"] for r in report["not_run"]] == ["2.1"]
    assert report["models"] == ["claude-old"]  # 3.1 was last judged by another model
    text = scenarios.format_report(new, report)
    assert "1.1  PASS -> FAIL" in text
    assert "(was PASS in 20261101-000000" in text
    assert "Skills loaded: omniverse-mcp:scene 1; none in 1 of 2 sessions" in text


def test_against_takes_a_run_or_the_newest_run_at_a_refs_commit():
    head = gate.git("rev-parse", "HEAD", cwd=ROOT).stdout.strip()
    runs = [run_record("a", [], commit=head), run_record("b", [], commit=head), run_record("c", [], commit="x")]
    assert scenarios.pick_against(runs, "a")["name"] == "a"
    assert scenarios.pick_against(runs, "HEAD")["name"] == "b"
    with pytest.raises(ValueError, match="no run"):
        scenarios.pick_against(runs, "no-such-ref-anywhere")


def test_against_finds_a_release_run_by_the_tree_its_squash_merge_keeps():
    tree = gate.git("rev-parse", "HEAD^{tree}", cwd=ROOT).stdout.strip()
    pr_head = run_record("pr", [], commit="not-the-merge-commit") | {"tree": tree, "clean": True}
    dirty = run_record("dirty", [], commit="other") | {"tree": tree, "clean": False}
    assert scenarios.pick_against([pr_head, dirty], "HEAD")["name"] == "pr"


def test_the_compare_command_exits_1_on_a_regression_or_a_not_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(scenarios, "runs_root", lambda: tmp_path)
    for record in (run_record("20261101-000000", [("1.1", "PASS")]), run_record("20261102-000000", [("1.1", "PASS")])):
        (tmp_path / record["name"]).mkdir()
        (tmp_path / record["name"] / "run.json").write_text(json.dumps(record), encoding="utf-8")
    assert scenarios.main(["compare"]) == 0
    worse = run_record("20261103-000000", [("1.1", scenarios.NOT_RUN)])
    (tmp_path / worse["name"]).mkdir()
    (tmp_path / worse["name"] / "run.json").write_text(json.dumps(worse), encoding="utf-8")
    assert scenarios.main(["compare"]) == 1
    assert "Not run (1): 1.1" in capsys.readouterr().out


def test_the_dry_run_prints_every_session_and_the_command(capsys):
    assert scenarios.main(["run", "--phases", "15", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "=== setup-15: 2.1, 4.5, 10.1 (new stage)" in out
    assert "=== phase-27" in out
    assert "--permission-mode dontAsk" in out


def test_main_checkout_is_the_first_worktree():
    first = gate.git("worktree", "list", "--porcelain", cwd=ROOT).stdout.splitlines()[0].removeprefix("worktree ")
    assert scenarios.main_checkout() == Path(first)


# ----- outcomes (#146) -----


@pytest.fixture(scope="module")
def real_outcomes():
    outcomes, problems = scenarios.parse_outcomes(scenarios.OUTCOMES.read_text(encoding="utf-8"))
    assert problems == []
    return outcomes


def test_the_real_outcomes_parse_with_no_problem(real_outcomes):
    assert [c.id for c in real_outcomes.cases] == ["O1", "O2", "O3", "O4", "O5", "O6", "O7"]
    by_id = {c.id: c for c in real_outcomes.cases}
    assert (by_id["O1"].given, by_id["O1"].play, by_id["O1"].calls) == ("", 0.0, "no execute_script")
    assert (by_id["O2"].play, by_id["O2"].calls) == (2.0, "any")
    assert by_id["O4"].play == 2.0
    assert "def mesh(" in by_id["O3"].given
    # The physics outcomes make their own scene: a play on Kit's preference alone may not simulate (round 2, R2).
    assert all('UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")' in by_id[i].given for i in ("O2", "O4", "O7"))
    # Work past an execute_script call's 120 s, which a job runs (#158). The settle before the judge stops the timeline,
    # which puts every crate back where it hung: the runner's play drops those released (review G1).
    assert (by_id["O7"].play, by_id["O7"].calls) == (3.0, "no execute_script")
    assert "get_job()" in by_id["O7"].verify


def test_the_outcomes_header_names_the_job_as_o7_s_path(real_outcomes):
    assert "O7, `run_script_job`" in " ".join(real_outcomes.header.split())


SMALL_OUTCOMES = """# Outcomes

The header.

## O1: First

Given: none

Ask: Do the first thing.

Verify:
- It is done

Calls: no execute_script

Play: none

## O2: Second

Given:

```python
import omni.kit.app
Ask: int = 1  # a field's spelling inside the code is code
await omni.kit.app.get_app().next_update_async()
```

Ask: Do the second thing.

Verify:
- The ball rests

Calls: any

Play: 1.5 s
"""


def test_small_outcomes_parse_with_awaiting_code_and_a_field_spelling_inside_it():
    outcomes, problems = scenarios.parse_outcomes(SMALL_OUTCOMES)
    assert problems == []
    assert outcomes.header == "The header."
    first, second = outcomes.cases
    assert (first.ask, first.verify, first.given, first.play) == ("Do the first thing.", "- It is done", "", 0.0)
    assert second.ask == "Do the second thing."
    assert second.given.startswith("import omni.kit.app\nAsk: int = 1")
    assert second.play == 1.5


@pytest.mark.parametrize(
    ("old", "new", "says"),
    [
        ("Calls: no execute_script", "Calls: at most 3", "`Calls:` is one of any, no execute_script"),
        ("Play: none", "Play: soon", "`Play:` is `none` or seconds"),
        ("Play: 1.5 s", "Play: 0 s", "`Play:` is `none` or seconds"),
        ("Verify:\n- It is done", "Verify: none", "its `Verify:` is empty"),
        ("Ask: Do the first thing.\n", "", "no `Ask:` line"),
        ("Given: none", "Given: make a cube", "a fenced python block"),
        ("Ask: int = 1  # a field", "x = (  # a field", "its Given doesn't compile"),
        ("## O2: Second", "## O1: Second", "an outcome ID appears twice"),
        ("Play: none\n", "Play: none\n\nCalls: any\n", "`Calls:` appears twice"),
    ],
)
def test_a_malformed_outcome_is_named(old, new, says):
    assert old in SMALL_OUTCOMES
    _, problems = scenarios.parse_outcomes(SMALL_OUTCOMES.replace(old, new, 1))
    assert any(says in p for p in problems), problems


@pytest.mark.parametrize(
    ("value", "phases_given", "expected"),
    [
        (None, False, ["O1", "O2"]),  # a run of every phase runs every outcome
        (None, True, []),  # a run of some phases runs none unless asked
        ("all", True, ["O1", "O2"]),
        ("none", False, []),
        ("O2, O1", True, ["O1", "O2"]),
    ],
)
def test_outcomes_asked(value, phases_given, expected):
    outcomes, _ = scenarios.parse_outcomes(SMALL_OUTCOMES)
    assert scenarios.outcomes_asked(value, phases_given, outcomes) == expected


def test_outcomes_asked_refuses_one_outcomes_md_lacks():
    outcomes, _ = scenarios.parse_outcomes(SMALL_OUTCOMES)
    with pytest.raises(ValueError, match="O9 isn't an outcome"):
        scenarios.outcomes_asked("O1,O9", False, outcomes)


def test_outcomes_run_after_the_phases_and_before_the_cleanup(suite):
    sessions = scenarios.plan(suite, {1}, ["O1", "O2"])
    assert [s.label for s in sessions] == [
        "phase-01",
        "outcome-O1",
        "judge-O1",
        "outcome-O2",
        "judge-O2",
        "phase-27",
    ]
    assert not any(s.new_stage for s in sessions[1:])  # the runner prepares an outcome's stage itself


def test_phases_none_runs_the_outcomes_alone(suite):
    assert scenarios.phases_asked("none", suite) == set()
    assert [s.label for s in scenarios.plan(suite, set(), ["O1"])] == ["outcome-O1", "judge-O1", "phase-27"]


def test_the_server_tools_split_by_their_read_only_hint():
    read_only, others = scenarios.server_tools()
    assert len(read_only) == 12
    assert {"mcp__omniverse__get_prim_bounds", "mcp__omniverse__get_job"} <= set(read_only)
    assert "mcp__omniverse__get_performance" in read_only  # what it lifts, it puts back (#156)
    assert {"mcp__omniverse__execute_script", "mcp__omniverse__sim_control"} <= set(others)
    assert not set(read_only) & set(others)


def test_the_agent_works_restricted_to_its_own_folder_with_the_brief(tmp_path):
    session = scenarios.Session(scenarios.AGENT, ("O1",), 0, False)
    cmd, cwd, expect = scenarios.session_command("claude", session, tmp_path / "c", tmp_path, "RULES", "BRIEF")
    assert cwd == tmp_path / "mcp_output" / "outcome-O1"
    assert "--restricted" in cmd
    assert "--add-dir" not in cmd  # outcomes.md and the judges' files stay out of its reach (round 1, P2)
    assert cmd[cmd.index("--append-system-prompt") + 1] == "BRIEF"
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob,Skill"
    assert expect == scenarios.Expect(plugin=True)


def test_the_judge_has_the_read_only_tools_alone_in_its_agents_folder(tmp_path):
    session = scenarios.Session(scenarios.JUDGE, ("O1",), 0, False)
    cmd, cwd, expect = scenarios.session_command("claude", session, tmp_path / "c", tmp_path, "RULES", "BRIEF")
    read_only, others = scenarios.server_tools()
    # In the agent's folder, so the paths in its answers resolve; its own added, where its server writes (round 2, R1).
    assert cwd == tmp_path / "mcp_output" / "outcome-O1"
    assert cmd[cmd.index("--add-dir") + 1] == str(tmp_path / "mcp_output" / "judge-O1")
    assert "--restricted" in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == "RULES"
    assert cmd[cmd.index("--tools") + 1] == "Read,Grep,Glob"
    allowed = cmd[cmd.index("--allowedTools") + 1 : cmd.index("--output-format")]
    assert allowed == ["Read", "Grep", "Glob", *read_only]
    assert not any(a.startswith("Skill") or a == "mcp__omniverse" for a in allowed)
    disallowed = cmd[cmd.index("--disallowedTools") + 1 : cmd.index("--restricted")]
    assert disallowed == others
    assert expect is not None and expect.tools == frozenset(["Read", "Grep", "Glob", *read_only])


def test_the_init_check_holds_a_judge_to_its_tools_and_an_agent_to_the_plugin(tmp_path):
    event = json.loads(json.dumps(B2_INIT).replace("PLUGIN", tmp_path.as_posix()))
    judge = scenarios.Expect(tools=frozenset(["Read", "Grep", "Glob", "mcp__omniverse__get_sim_state"]))
    assert scenarios.init_problems(event | {"tools": ["Read", "mcp__omniverse__get_sim_state"]}, tmp_path, judge) == []
    wider = event | {"tools": ["Read", "mcp__omniverse__execute_script"]}
    assert "tools outside the run's list: mcp__omniverse__execute_script" in scenarios.init_problems(
        wider, tmp_path, judge
    )
    agent = scenarios.Expect(plugin=True)
    assert scenarios.init_problems(event, tmp_path, agent) == []
    without = event | {"plugins": [{"name": "cc-plugin-agents-md", "path": "builtin"}]}
    assert any("no omniverse-mcp plugin" in p for p in scenarios.init_problems(without, tmp_path, agent))
    assert scenarios.init_problems(without, tmp_path) == []  # a phase's tester, as before


def test_a_session_keeps_each_server_call_with_its_input_and_answer(tmp_path):
    outcome = scenarios.Outcome()
    lines = [
        json.dumps(B2_INIT).replace("PLUGIN", tmp_path.as_posix()),
        *stream(
            ("assistant", {"type": "tool_use", "id": "a", "name": "mcp__omniverse__create_prim", "input": {"x": 1}}),
            ("user", {"type": "tool_result", "tool_use_id": "a", "content": [{"type": "text", "text": "made"}]}),
            ("assistant", {"type": "tool_use", "id": "b", "name": "Read", "input": {"file_path": "x"}}),
            ("assistant", {"type": "tool_use", "id": "c", "name": "mcp__omniverse__execute_script", "input": {}}),
            ("user", {"type": "tool_result", "tool_use_id": "c", "is_error": True, "content": "boom"}),
        ),
    ]
    for line in lines:
        scenarios._read_event(line, outcome, tmp_path)
    assert outcome.calls == [
        {"name": "create_prim", "input": '{"x": 1}', "answer": "made"},
        {"name": "execute_script", "input": "{}", "answer": "error: boom"},
    ]
    assert outcome.call_names == ["create_prim", "execute_script"]


def _case(given: str = "", play: float = 0.0) -> scenarios.OutcomeCase:
    return scenarios.OutcomeCase("O1", "First", given, "ASK TEXT", "- VERIFY LINE", "no execute_script", play)


def test_the_judges_prompt_holds_the_request_the_verify_lines_and_what_the_agent_did(tmp_path):
    agent = outcome("All done.", stopped="stopped at the session's limit, 900 s")
    agent.calls = [{"name": "create_prim", "input": '{"prim_type": "Cube"}', "answer": "x" * 700}]
    files = [tmp_path / "mcp_output" / "outcome-O1" / "captures" / "capture_0001.png"]
    text = scenarios.judge_prompt(_case(play=2.0), agent, files, 8212)
    for part in ("ASK TEXT", "- VERIFY LINE", "All done.", "played the simulation for 2 s and paused it"):
        assert part in text
    assert '1. create_prim {"prim_type": "Cube"}' in text
    assert f"   -> {'x' * 600} [... 100 more characters]" in text
    assert "The runner stopped the assistant: stopped at the session's limit, 900 s." in text
    assert f"- {files[0].as_posix()}" in text
    assert "one row, for O1" in text
    assert "The timeline is stopped" in scenarios.judge_prompt(_case(), outcome(), [], 8212)


def test_the_judge_gets_a_job_s_script_longer_than_other_calls_arguments():
    # A judge confirms a job's order and timing from its code (#158), which ran past 600 characters in O7's run.
    script = json.dumps({"code": "await step()\n" * 400})
    agent = outcome("Done.")
    agent.calls = [
        {"name": "run_script_job", "input": script, "answer": "Job j1 started"},
        {"name": "execute_script", "input": script, "answer": ""},
    ]

    text = scenarios.judge_prompt(_case(), agent, [], 8212)

    assert f"1. run_script_job {script[:4000]} [... {len(script) - 4000} more characters]" in text
    assert f"2. execute_script {script[:600]} [... {len(script) - 600} more characters]" in text
    assert "a run_script_job's arguments to 4000" in text


def test_prepare_stage_makes_a_new_stage_lit_by_its_own_lights_then_runs_the_given(kit):
    scenarios.prepare_stage(kit.port, _case(given="print(1)\n"))
    asked = [(path, body) for _, path, body in kit.requests if path != "/bridge"]  # the client's handshake
    assert asked == [
        ("/scene/new", {"up_axis": "Z", "meters_per_unit": 1.0}),  # the frame a user's agent gets
        ("/viewport/light", {"action": "set", "mode": "stage"}),  # an earlier session's lighting stays out (P5)
        ("/execute", {"code": "print(1)\n"}),
    ]
    kit.set_response("/execute", {"status": "error", "error": "NameError: boom"})
    with pytest.raises(scenarios.BridgeError, match="boom"):
        scenarios.prepare_stage(kit.port, _case(given="boom\n"))


class FakeTimeline:
    """A client whose sim_time moves `rate` seconds of simulation for each read while playing."""

    def __init__(self, rate: float):
        self.rate, self.time, self.playing, self.actions = rate, 0.0, False, []

    def sim_control(self, action):
        self.actions.append(action)
        self.playing = action == "play"
        return {"status": "success", "result": {}}

    def sim_state(self):
        if self.playing:
            self.time += self.rate
        return {"status": "success", "result": {"sim_time": self.time}}

    def close(self):
        self.actions.append("closed")


def test_the_runners_play_pauses_once_the_time_has_moved_on_that_far():
    timeline, clock = FakeTimeline(0.5), Clock()

    def sleep(seconds):
        clock.now += seconds

    scenarios.run_play(8212, 2.0, connect=lambda _port: cast("Any", timeline), clock=clock, sleep=sleep)
    assert timeline.actions == ["play", "pause", "closed"]
    assert timeline.time >= 2.5  # the read at play, then four more


def test_a_play_that_doesnt_get_there_pauses_and_says_how_far_it_got():
    timeline, clock = FakeTimeline(0.0), Clock()

    def sleep(seconds):
        clock.now += seconds

    with pytest.raises(scenarios.PlayError, match=r"moved 0\.00 s of 2 s in 18 s"):
        scenarios.run_play(8212, 2.0, connect=lambda _port: cast("Any", timeline), clock=clock, sleep=sleep)
    assert timeline.actions == ["play", "pause", "closed"]


def outcome_run(suite, tmp_path, judge_status="PASS", agent_calls=(), prepare=None, play=None):
    """run_sessions over SMALL_OUTCOMES' two outcomes and the cleanup, everything it does in `seen`."""
    outcomes, _ = scenarios.parse_outcomes(SMALL_OUTCOMES)
    seen = []

    def launch(session, text, left):
        seen.append(("launch", session.label, text))
        if session.kind == scenarios.AGENT:
            done = outcome("I did it.", skills=["omniverse-mcp:scene"])
            done.calls = [{"name": name, "input": "{}", "answer": "ok"} for name in agent_calls]
            return done
        if session.kind == scenarios.JUDGE:
            return outcome(table(f"{session.ids[0]} | t | {judge_status} | checked"))
        return outcome(table("27.1 | t | PASS | n"))

    def default_prepare(case):
        seen.append(("prepare", case.id))

    def default_play(seconds):
        seen.append(("play", seconds))

    records, rows = scenarios.run_sessions(
        suite,
        scenarios.plan(suite, set(), ["O1", "O2"]),
        tmp_path,
        8212,
        launch,
        lambda: seen.append(("settle",)),
        outcomes=outcomes,
        prepare=prepare or default_prepare,
        play=play or default_play,
    )
    # One row an outcome, from its judge: a second, from its agent, would list it twice and make compare's not_run
    # hold it (round 1 of the code review, F2).
    assert [r.id for r in rows] == ["O1", "O2", "27.1"]
    return seen, records, {r.id: r for r in rows}


def test_an_outcome_is_prepared_acted_on_played_and_judged(suite, tmp_path):
    seen, records, rows = outcome_run(suite, tmp_path)
    steps = [s[:2] for s in seen]
    assert steps == [
        ("settle",),
        ("prepare", "O1"),
        ("launch", "outcome-O1"),
        ("settle",),
        ("launch", "judge-O1"),
        ("settle",),
        ("prepare", "O2"),
        ("launch", "outcome-O2"),
        ("settle",),
        ("play", 1.5),  # after the settle, so the judge reads where physics put things (round 1, P1)
        ("launch", "judge-O2"),
        ("settle",),
        ("launch", "phase-27"),
    ]
    agent_prompt = seen[2][2]
    assert agent_prompt == "Do the first thing."  # nothing of Verify, Calls or Given (the plan's Goal)
    assert "- It is done" in seen[4][2] and "I did it." in seen[4][2]
    assert (rows["O1"].session, rows["O1"].status, rows["O1"].notes) == ("judge-O1", "PASS", "checked")
    assert [r.label for r in records][:2] == ["outcome-O1", "judge-O1"]
    assert records[0].skills == ["omniverse-mcp:scene"]


def test_a_script_where_the_calls_line_says_none_caps_a_pass_at_warn(suite, tmp_path):
    _, records, rows = outcome_run(suite, tmp_path, agent_calls=("create_prim", "execute_script"))
    assert rows["O1"].status == "WARN"
    assert rows["O1"].notes == "checked; Calls: execute_script 1, where the line says none"
    assert rows["O2"].status == "PASS"  # O2's line is `any`
    assert records[0].calls == ["create_prim", "execute_script"]
    _, _, rows = outcome_run(suite, tmp_path, judge_status="FAIL", agent_calls=("execute_script",))
    assert rows["O1"].status == "FAIL"  # a FAIL stays a FAIL (Q3)
    assert rows["O1"].notes.endswith("where the line says none")


def test_a_given_kit_refuses_leaves_that_outcome_not_run_and_the_run_going(suite, tmp_path):
    def prepare(case):
        if case.id == "O1":
            raise scenarios.BridgeError("NameError: boom")

    seen, records, rows = outcome_run(suite, tmp_path, prepare=prepare)
    launched = [s[1] for s in seen if s[0] == "launch"]
    assert launched == ["outcome-O2", "judge-O2", "phase-27"]
    assert rows["O1"].status == scenarios.NOT_RUN
    assert rows["O1"].notes == "not run: preparing its stage: NameError: boom"
    assert records[1].stopped == "not run: preparing its stage: NameError: boom"
    assert rows["O2"].status == "PASS"


def test_no_answer_while_preparing_halts_the_run(suite, tmp_path):
    def prepare(case):
        raise OSError("connection refused")

    seen, _, rows = outcome_run(suite, tmp_path, prepare=prepare)
    assert [s for s in seen if s[0] == "launch"] == []
    assert {r.status for r in rows.values()} == {scenarios.NOT_RUN}
    assert rows["27.1"].notes == "not run: Kit didn't answer: connection refused"


def test_a_play_that_doesnt_get_there_leaves_that_outcome_not_run(suite, tmp_path):
    def play(seconds):
        raise scenarios.PlayError("the simulation's time moved 0.00 s of 1.5 s in 16 s")

    seen, _, rows = outcome_run(suite, tmp_path, play=play)
    assert "judge-O2" not in [s[1] for s in seen if s[0] == "launch"]
    assert rows["O2"].notes == "not run: the runner's play: the simulation's time moved 0.00 s of 1.5 s in 16 s"
    assert rows["27.1"].status == "PASS"


def test_an_interrupt_in_an_agent_or_in_the_runners_play_leaves_one_not_run_row_each(suite, tmp_path):
    outcomes, _ = scenarios.parse_outcomes(SMALL_OUTCOMES)
    sessions = scenarios.plan(suite, set(), ["O1", "O2"])

    def interrupted(session, text, left):
        if session.label == "outcome-O1":
            raise KeyboardInterrupt
        return outcome(table(f"{session.ids[0]} | t | PASS | n"))

    rows: list[scenarios.Row] = []
    records: list[scenarios.SessionRecord] = []
    with pytest.raises(KeyboardInterrupt):
        scenarios.run_sessions(
            suite, sessions, tmp_path, 8212, interrupted, lambda: None, None, records, rows, outcomes=outcomes
        )
    assert [(r.id, r.status) for r in rows] == [("O1", "NOT RUN"), ("O2", "NOT RUN"), ("27.1", "NOT RUN")]
    assert records[0].stopped == "cut short"

    def stopped_playing(seconds):
        raise KeyboardInterrupt  # Ctrl+C during the runner's play, which can take 18 s (round 1, F1)

    rows, records = [], []
    with pytest.raises(KeyboardInterrupt):
        scenarios.run_sessions(
            suite,
            sessions,
            tmp_path,
            8212,
            lambda session, text, left: outcome(table(f"{session.ids[0]} | t | PASS | n")),
            lambda: None,
            None,
            records,
            rows,
            outcomes=outcomes,
            play=stopped_playing,
        )
    assert [(r.id, r.status) for r in rows] == [("O1", "PASS"), ("O2", "NOT RUN"), ("27.1", "NOT RUN")]
    assert [(r.label, r.stopped) for r in records][-2:] == [
        ("judge-O2", "cut short"),
        ("phase-27", "not run: the run was cut short"),
    ]


def test_a_failed_read_after_the_play_still_pauses():
    timeline = FakeTimeline(0.5)
    reads = {"n": 0}
    real_state = timeline.sim_state

    def state():
        reads["n"] += 1
        if reads["n"] == 1:
            raise OSError("no answer")
        return real_state()

    timeline.sim_state = state
    with pytest.raises(OSError, match="no answer"):
        scenarios.run_play(8212, 2.0, connect=lambda _port: cast("Any", timeline))
    assert timeline.actions == ["play", "pause", "closed"]


def test_results_md_lists_each_outcomes_skills_and_calls():
    record = {
        "sessions": [
            {"label": "outcome-O1", "kind": "outcome", "ids": ["O1"], "skills": ["omniverse-mcp:scene"], "stopped": ""}
            | {"calls": ["create_prim", "set_material", "set_material", "capture_viewport"]},
            {"label": "judge-O1", "kind": "judge", "ids": ["O1"], "skills": [], "stopped": ""},
            {"label": "outcome-O2", "kind": "outcome", "ids": ["O2"], "skills": [], "stopped": "not run: x"},
        ],
        "rows": [
            {"id": "O2", "test": "Second", "status": scenarios.NOT_RUN, "notes": "not run: x"},
            {"id": "O1", "test": "First", "status": "PASS", "notes": "ok"},
            {"id": "27.1", "test": "Cleanup", "status": "PASS", "notes": "ok"},
        ],
    }
    text = scenarios.results_md(record | {"outcomes": "O1,O2"})
    assert "| Outcomes asked | O1,O2 |" in text
    assert text.index("| 27.1 |") < text.index("| O1 |") < text.index("| O2 |")
    assert (
        "| O1 | omniverse-mcp:scene | create_prim, set_material x2, capture_viewport (4 calls, 0 execute_script) "
        "| PASS |" in text
    )
    assert "| O2 | none | not run | NOT RUN |" in text


def test_compare_counts_skill_loads_without_the_judges():
    new = run_record("20261102-000000", [("O1", "PASS")], skills=("omniverse-mcp:scene",))
    new["sessions"] += [{"label": "judge-O1", "kind": "judge", "skills": []}]
    report = scenarios.compare(new, [])
    assert (report["sessions"], report["without_skill"]) == (2, 1)  # phase-01 and phase-02; the judge left out


def test_outcome_ids_sort_after_every_phase():
    ids = ["O10", "27.1", "O2", "1.1", "6.4-6.9"]
    assert sorted(ids, key=scenarios._id_key) == ["1.1", "6.4-6.9", "27.1", "O2", "O10"]


# ----- the run command -----


def test_claude_must_be_on_path_and_not_a_cmd_shim_on_windows():
    with pytest.raises(SystemExit, match="isn't on PATH"):
        scenarios.claude_executable(which=lambda _: None)
    with pytest.raises(SystemExit, match=r"cmd\.exe shim"):
        scenarios.claude_executable(which=lambda _: "C:/npm/claude.cmd", windows=True)
    assert scenarios.claude_executable(which=lambda _: "C:/bin/claude.exe", windows=True) == "C:/bin/claude.exe"
    assert scenarios.claude_executable(which=lambda _: "/npm/claude.cmd", windows=False) == "/npm/claude.cmd"


@pytest.fixture
def run_command(tmp_path, monkeypatch):
    """cmd_run with Kit and the tester stood in for: check passes, settle and each session are recorded."""
    runs = tmp_path / "runs"
    seen = {"settled": [], "sessions": []}
    monkeypatch.setattr(scenarios, "claude_executable", lambda: sys.executable)
    monkeypatch.setattr(scenarios, "check", lambda *a, **k: ([], scenarios.Kit(app="Isaac-Sim")))
    monkeypatch.setattr(scenarios, "runs_root", lambda: runs)
    monkeypatch.setattr(scenarios, "settle", seen["settled"].append)
    seen["prepared"], seen["played"] = [], []
    monkeypatch.setattr(scenarios, "prepare_stage", lambda port, case: seen["prepared"].append((port, case.id)))
    monkeypatch.setattr(scenarios, "run_play", lambda port, seconds: seen["played"].append((port, seconds)))

    def run_session(cmd, transcript, plugin_dir, watch, cwd, env, expect=None, prompt=""):
        seen["sessions"].append({"watch": watch, "cwd": cwd, "cmd": cmd, "expect": expect, "prompt": prompt})
        rows = table("1.1 | t | PASS | n", "1.2 | t | PASS | n", "27.1 | t | PASS | n", "O4 | t | PASS | n")
        return outcome(rows, skills=["omniverse-mcp:scene"], started="s", ended="e", tokens={"output_tokens": 5})

    monkeypatch.setattr(scenarios, "run_session", run_session)
    return runs, seen


def test_a_run_writes_its_record_and_gives_its_lock_back(run_command):
    runs, seen = run_command
    assert scenarios.main(["run", "--phases", "1"]) == 0
    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    for key in ("commit", "tree", "clean", "branch", "port", "kit", "models", "sessions", "rows", "cost"):
        assert key in record
    assert record["models"] == ["claude-test-1"]
    assert [s["label"] for s in record["sessions"]] == ["phase-01", "phase-27"]
    assert {"skills", "started", "ended", "tokens", "cost_known"} <= set(record["sessions"][0])
    assert [r["status"] for r in record["rows"]] == ["PASS", "PASS", "PASS"]
    assert (run_dir / "results.md").is_file()
    assert not scenarios.lock_path(runs, 8212).exists()
    assert seen["settled"] == [8212, 8212]
    # A watch of each session's own (round 1, F4), in the session's own folder (IA3).
    assert seen["sessions"][0]["watch"] is not seen["sessions"][1]["watch"]
    assert [s["cwd"] for s in seen["sessions"]] == [
        run_dir / "mcp_output" / "phase-01",
        run_dir / "mcp_output" / "phase-27",
    ]


def test_a_run_cut_short_gives_its_lock_back_and_writes_what_ran(run_command, monkeypatch):
    runs, _ = run_command

    def interrupted(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(scenarios, "run_session", interrupted)
    with pytest.raises(KeyboardInterrupt):
        scenarios.main(["run", "--phases", "1"])
    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    assert not scenarios.lock_path(runs, 8212).exists()
    # Not a run that finished (round 2, F10): the cut session and every later one say so, and their rows aren't run.
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    sessions = {s["label"]: s for s in record["sessions"]}
    assert (sessions["phase-01"]["stopped"], sessions["phase-01"]["cost_known"]) == ("cut short", False)
    assert sessions["phase-27"]["stopped"] == "not run: the run was cut short"
    assert [(r["id"], r["status"]) for r in record["rows"]] == [
        ("1.1", scenarios.NOT_RUN),
        ("1.2", scenarios.NOT_RUN),
        ("27.1", scenarios.NOT_RUN),
    ]


def test_a_held_lock_refuses_a_second_run(run_command, capsys):
    runs, seen = run_command
    runs.mkdir(parents=True)
    scenarios.lock_path(runs, 8212).write_text("run 20261101-000000\n", encoding="utf-8")
    assert scenarios.main(["run", "--phases", "1"]) == 1
    assert "another run took port 8212" in capsys.readouterr().out
    assert seen["sessions"] == []
    assert scenarios.lock_path(runs, 8212).read_text(encoding="utf-8") == "run 20261101-000000\n"


def test_phases_none_alone_runs_every_outcome(run_command):
    runs, seen = run_command
    assert scenarios.main(["run", "--phases", "none"]) == 0
    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert record["outcomes"] == "O1,O2,O3,O4,O5,O6,O7"
    assert [p for _, p in seen["prepared"]] == ["O1", "O2", "O3", "O4", "O5", "O6", "O7"]


def test_a_run_with_an_outcome_prepares_plays_and_records_it(run_command):
    runs, seen = run_command
    assert scenarios.main(["run", "--phases", "none", "--outcomes", "O4"]) == 0
    (run_dir,) = [p for p in runs.iterdir() if p.is_dir()]
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert (record["phases"], record["outcomes"]) == ("none", "O4")
    assert [s["label"] for s in record["sessions"]] == ["outcome-O4", "judge-O4", "phase-27"]
    assert (seen["prepared"], seen["played"]) == ([(8212, "O4")], [(8212, 2.0)])
    agent, judge, _ = seen["sessions"]
    assert agent["cwd"] == judge["cwd"] == run_dir / "mcp_output" / "outcome-O4"
    assert "--restricted" in agent["cmd"] and agent["expect"] == scenarios.Expect(plugin=True)
    assert agent["prompt"].startswith("When I press play, the box in my scene falls straight through the floor.")
    assert judge["prompt"].startswith("You judge outcome O4")
    assert judge["expect"].tools is not None
    assert {r["id"]: r["status"] for r in record["rows"]} == {"O4": "PASS", "27.1": "PASS"}
    assert "## Outcomes" in (run_dir / "results.md").read_text(encoding="utf-8")
