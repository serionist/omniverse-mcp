"""The AI scenario suite's runs (tools/scenarios.py, #102): scenarios.md's phases and their Needs: lines, which
sessions a run holds, what a tester is told and what is read back, the checks before a run, a session's stream, and
the comparison of runs."""

import json
import shutil
import sys
import time
from pathlib import Path

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
    assert sum(len(p.scenarios) for p in suite.phases) == 144
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
    assert "new_scene() before anything else" not in text
    assert "one row for each of 5.1, 5.2, 5.3" in text


def test_a_prompt_fills_in_the_run_folder_and_starts_a_stage_when_first(suite, tmp_path):
    sessions = scenarios.plan(suite, {17})
    text = scenarios.prompt(suite, sessions[0], {}, tmp_path, 8212)
    assert "new_scene() before anything else" in text
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


def test_the_config_holds_the_skills_without_their_server_and_the_server_pinned(tmp_path):
    run_dir = tmp_path / "run"
    scenarios.write_config(tmp_path / "config", 8212, run_dir)
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
        "OMNIVERSE_MCP_OUTPUT_DIR": (run_dir / "mcp_output").as_posix(),
    }


def test_the_tester_command_is_the_one_step_2_proved(tmp_path):
    cmd = scenarios.tester_command("claude", "PROMPT", tmp_path, "RULES", 1.5, "opus")
    assert cmd[:3] == ["claude", "-p", "PROMPT"]
    joined = " ".join(cmd)
    for part in (
        "--strict-mcp-config",
        "--setting-sources  --append-system-prompt RULES",
        "--tools Read,Grep,Glob,Skill",
        "--permission-mode dontAsk",
        "--allowedTools mcp__omniverse Read Grep Glob Skill(omniverse-mcp:geometry) Skill(omniverse-mcp:scene) "
        "Skill(omniverse-mcp:script) Skill(omniverse-mcp:setup) Skill(omniverse-mcp:simulate) --output-format",
        "--output-format stream-json --verbose",
        "--max-budget-usd 1.50",
        "--model opus",
    ):
        assert part in joined
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
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
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
    assert "#54" in reason


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
    assert outcome.cost == 0.25
    assert scenarios.rows_from(outcome.text, ["1.1"])["1.1"].status == "PASS"
    assert len(transcript.read_text(encoding="utf-8").splitlines()) == 4


def test_a_foreign_server_stops_the_tester_at_once(tmp_path):
    began = time.monotonic()
    outcome = scenarios.run_session(stub("foreign", tmp_path), tmp_path / "t.jsonl", tmp_path, cwd=tmp_path)
    assert time.monotonic() - began < 30
    assert "claude_ai_Gmail" in outcome.stopped


def test_a_session_stops_at_its_limit(tmp_path):
    outcome = scenarios.run_session(stub("slow", tmp_path), tmp_path / "t.jsonl", tmp_path, limit=2, cwd=tmp_path)
    assert "limit" in outcome.stopped


# ----- a run -----


def outcome(text="", cost=0.1, **kw):
    return scenarios.Outcome(exit=0, text=text, cost=cost, model="claude-test-1", **kw)


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
    old = run_record("20261101-000000", [("1.1", "PASS"), ("1.2", "FAIL"), ("2.1", "PASS"), ("2.2", "WARN")])
    older = run_record("20261031-000000", [("3.1", "PASS")], models=("claude-old",))
    new = run_record(
        "20261102-000000",
        [
            ("1.1", "FAIL"),
            ("1.2", "PASS"),
            ("2.1", scenarios.NOT_RUN),
            ("2.2", "SKIP"),
            ("3.1", "PASS"),
            ("4.1", "PASS"),
        ],
        skills=("omniverse-mcp:scene",),
    )
    report = scenarios.compare(new, [older, old])
    assert [e["now"]["id"] for e in report["regressions"]] == ["1.1"]
    assert [e["now"]["id"] for e in report["fixed"]] == ["1.2"]
    assert [e["now"]["id"] for e in report["changed"]] == ["2.2"]
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
