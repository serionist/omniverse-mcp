"""The AI scenario suite's runs (#102, docs/plans/2026-11-01-scenario-skill.md): check the Kit app a run would drive,
run test_project/scenarios.md's phases, each in a headless Claude Code tester of its own, and compare a run's rows
with earlier runs'. The run-scenarios skill calls it.

test_project/outcomes.md's outcomes (#146, docs/plans/2026-11-02-outcome-scenarios.md) run after the phases: an agent
gets a user's request alone, on a stage the runner prepared, and a read-only judge checks what it did.

    uv run tools/scenarios.py check [--port N]
    uv run tools/scenarios.py run [--phases 15,18-21|none] [--outcomes all|none|O1,O3] [--port N] [--budget USD]
        [--model M] [--dry-run]
    uv run tools/scenarios.py compare [RUN] [--against RUN_OR_TAG]

Unlike the gate, it imports the server's client, so it needs `uv sync` (write-skill, step 5).
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import gate

from omniverse_mcp.bridge_token import token_path
from omniverse_mcp.client import BridgeClient, BridgeError

ROOT = Path(__file__).resolve().parents[1]
TEST_PROJECT = ROOT / "test_project"
SCENARIOS = TEST_PROJECT / "scenarios.md"
TESTER_RULES = TEST_PROJECT / "AGENTS.md"
OUTCOMES = TEST_PROJECT / "outcomes.md"
# What an outcome's agent is told in place of the tester's rules: nothing about tests, Verify lines or tools.
AGENT_BRIEF = TEST_PROJECT / "assistant.md"
TOOL_CONTRACT = ROOT / "tests" / "fixtures" / "mcp-tools.json"
PLUGIN = ROOT / "plugin"
BRIDGE = "extension/ovmcp.bridge"

LOOPBACK = "127.0.0.1"
DEFAULT_PORT = 8212
GUI_PORT = 8211  # every Kit app's default, and the maintainer's own Kit app: a run wipes the stage it drives
# Phase 17 makes a new stage; the phases from here on start on one of their own (the plan's two halves).
SECOND_HALF = 18
STATUSES = ("PASS", "FAIL", "WARN", "SKIP")
NOT_RUN = "NOT RUN"
# The tester's server, as the run's mcp.json names it, and the built-in tools it keeps: the strict MCP flag drops a
# plugin's own server, so the server is the run's (the plan's step 2, S1).
SERVER = "omniverse"
BUILTIN_TOOLS = ("Read", "Grep", "Glob", "Skill")
# A judge's built-in tools: it loads no skill, and its file tools reach only its folders (--restricted).
JUDGE_TOOLS = ("Read", "Grep", "Glob")
PLUGIN_NAME = "omniverse-mcp"
# Each of the agent's answers as a judge's prompt quotes it; the transcript keeps them whole. An answer is kept up to
# ANSWER_KEPT characters while a session runs.
ANSWER_CHARS = 600
ANSWER_KEPT = 4000
# The runner's play before a judge (an outcome's Play: line): a wall-clock limit of PLAY_TIMES its seconds plus
# PLAY_SLACK, read every PLAY_EVERY seconds.
PLAY_TIMES = 4
PLAY_SLACK = 10.0
PLAY_EVERY = 0.25
# The /health watch (#54): probes as conftest's, and a stop only after a silence longer than the server's 120 s call
# limit plus one probe, counted from the first probe that got no answer, since a long handler holds /health back too.
PROBE_SECONDS = 20.0
PROBE_EVERY = 30.0
SILENCE_LIMIT = 140.0
# A session's limit, for a tester that runs on: step 9's longest session took 195 s, and the /health watch, not this,
# catches a Kit that hangs.
SESSION_SECONDS = 15 * 60

START_HINT = (
    "A run needs a Kit app without its window on that port, with this checkout's bridge: "
    "--ext-folder <checkout>/extension --enable ovmcp.bridge --/exts/ovmcp.bridge/port=<port> "
    "(docs/SETUP.md, Headless Kit and Ports). Ask the maintainer to start it, or to approve their command for it"
)

# execute_script code for check: where the bridge Kit loaded lives, found from its own package so no Kit API names
# it, and the Kit app's name and versions where Kit says them.
KIT_FACTS = """
from pathlib import Path
import omni.kit.app
import ovmcp.bridge
app = omni.kit.app.get_app()
def ask(name):
    try:
        return str(getattr(app, name)())
    except Exception:
        return ""
result = {
    "folder": str(Path(ovmcp.bridge.__file__).resolve().parents[2]),
    "app": ask("get_app_name"),
    "version": ask("get_app_version"),
    "kit": ask("get_kit_version"),
}
"""


# ----- scenarios.md -----

PHASE = re.compile(r"^## Phase (\d+): (.+)$", re.MULTILINE)
SCENARIO = re.compile(r"^### (\d+)\.(\d+)(?: to (\d+)\.(\d+))? (.+)$", re.MULTILINE)
NEEDS = re.compile(r"^Needs: (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Scenario:
    id: str  # "6.3", or "6.4-6.9" for a heading that holds several
    phase: int
    order: tuple[int, int]
    title: str
    text: str


@dataclass(frozen=True)
class Phase:
    number: int
    title: str
    needs: tuple[str, ...] | None  # None: the phase has no Needs: line
    text: str
    scenarios: tuple[Scenario, ...]


@dataclass(frozen=True)
class Suite:
    header: str
    phases: tuple[Phase, ...]

    def phase(self, number: int) -> Phase:
        return next(p for p in self.phases if p.number == number)

    def scenario(self, scenario_id: str) -> Scenario | None:
        return next((s for p in self.phases for s in p.scenarios if s.id == scenario_id), None)

    @property
    def cleanup(self) -> int:
        """The last phase, which ends every run."""
        return self.phases[-1].number


def half(phase: int) -> int:
    return 0 if phase < SECOND_HALF else 1


def parse(text: str) -> Suite:
    """scenarios.md: the header before the first phase, and each phase with its Needs: line and its scenarios."""
    heads = list(PHASE.finditer(text))
    first = heads[0].start() if heads else len(text)
    header = _trim(text[:first].split("\n", 1)[1] if "\n" in text[:first] else "")
    phases = []
    for i, head in enumerate(heads):
        section = _trim(text[head.start() : heads[i + 1].start() if i + 1 < len(heads) else len(text)])
        number = int(head.group(1))
        marks = list(SCENARIO.finditer(section))
        intro = section[: marks[0].start()] if marks else section
        needs_line = NEEDS.search(intro)
        needs = None
        if needs_line:
            value = needs_line.group(1).strip()
            needs = () if value == "none" else tuple(v.strip() for v in value.split(","))
        scenarios = []
        for j, mark in enumerate(marks):
            body = _trim(section[mark.start() : marks[j + 1].start() if j + 1 < len(marks) else len(section)])
            sid = f"{mark.group(1)}.{mark.group(2)}"
            if mark.group(3):
                sid += f"-{mark.group(3)}.{mark.group(4)}"
            scenarios.append(Scenario(sid, number, (int(mark.group(1)), int(mark.group(2))), mark.group(5), body))
        phases.append(Phase(number, head.group(2).strip(), needs, section, tuple(scenarios)))
    return Suite(header, tuple(phases))


def _trim(text: str) -> str:
    """A section without the rule that closes it and the blank lines around it."""
    text = text.strip()
    while text.endswith("---"):
        text = text[:-3].rstrip()
    return text


def suite_problems(suite: Suite) -> list[str]:
    """What breaks a run's resolution: a phase without its Needs: line, or a needed ID that doesn't exist, points
    forward, crosses Phase 17's new stage, or sits in the cleanup phase's line."""
    problems = []
    numbers = [p.number for p in suite.phases]
    if len(set(numbers)) != len(numbers):
        problems.append("scenarios.md: a phase number appears twice")
    ids = [s.id for p in suite.phases for s in p.scenarios]
    if len(set(ids)) != len(ids):
        problems.append("scenarios.md: a scenario ID appears twice")
    for phase in suite.phases:
        where = f"scenarios.md, Phase {phase.number}"
        if phase.needs is None:
            problems.append(f"{where}: no `Needs:` line under its heading (`Needs: none` when it needs nothing)")
            continue
        if phase.number == suite.cleanup and phase.needs:
            problems.append(f"{where}: the cleanup phase ends every run, so it needs nothing")
        for needed in phase.needs:
            found = suite.scenario(needed)
            if found is None:
                problems.append(f"{where}: needs {needed}, which no heading names")
            elif found.phase >= phase.number:
                problems.append(f"{where}: needs {needed}, which doesn't come before it")
            elif half(found.phase) != half(phase.number):
                problems.append(f"{where}: needs {needed}, across Phase 17's new stage")
    return problems


# ----- outcomes.md -----

OUTCOME = re.compile(r"^## (O\d+): (.+)$", re.MULTILINE)
FIELD = re.compile(r"^(Given|Ask|Verify|Calls|Play):[ \t]*(.*)$", re.MULTILINE)
FENCE = re.compile(r"^```python\n(.*?)^```$", re.MULTILINE | re.DOTALL)
FIELDS = ("Given", "Ask", "Verify", "Calls", "Play")
CALLS = ("any", "no execute_script")
NO_SCRIPT = "execute_script"
PLAY = re.compile(r"^(\d+(?:\.\d+)?) s$")


@dataclass(frozen=True)
class OutcomeCase:
    id: str  # "O1"
    title: str
    given: str  # Python the runner sends through /execute after new_scene(); "" for none
    ask: str  # the request, all the agent gets
    verify: str  # what the judge checks
    calls: str  # one of CALLS
    play: float  # the runner's seconds of play before the judge; 0 for none


@dataclass(frozen=True)
class Outcomes:
    header: str
    cases: tuple[OutcomeCase, ...]

    def case(self, case_id: str) -> OutcomeCase | None:
        return next((c for c in self.cases if c.id == case_id), None)


def parse_outcomes(text: str) -> tuple[Outcomes, list[str]]:
    """outcomes.md: the header, and each `## O<n>: Title` with its five fields; with what is wrong in any of them."""
    heads = list(OUTCOME.finditer(text))
    first = heads[0].start() if heads else len(text)
    header = _trim(text[:first].split("\n", 1)[1] if "\n" in text[:first] else "")
    cases: list[OutcomeCase] = []
    problems: list[str] = []
    for i, head in enumerate(heads):
        section = _trim(text[head.end() : heads[i + 1].start() if i + 1 < len(heads) else len(text)])
        cid = head.group(1)
        where = f"outcomes.md, {cid}"
        # A field line inside Given's code is code, not a field.
        fenced = [(m.start(), m.end()) for m in FENCE.finditer(section)]
        marks = [m for m in FIELD.finditer(section) if not any(a <= m.start() < b for a, b in fenced)]
        values: dict[str, str] = {}
        for j, mark in enumerate(marks):
            name = mark.group(1)
            end = marks[j + 1].start() if j + 1 < len(marks) else len(section)
            if name in values:
                problems.append(f"{where}: `{name}:` appears twice")
            values[name] = (mark.group(2) + section[mark.end() : end]).strip()
        missing = [f for f in FIELDS if f not in values]
        if missing:
            problems.append(f"{where}: no {', '.join(f'`{f}:`' for f in missing)} line")
            continue
        given = ""
        if values["Given"] != "none":
            code = FENCE.search(values["Given"] + "\n")
            if code is None:
                problems.append(f"{where}: `Given:` is `none` or a fenced python block")
            else:
                given = code.group(1)
                try:
                    # As the bridge runs it: a top-level await is no error.
                    compile(given, f"{where} Given", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
                except SyntaxError as e:
                    problems.append(f"{where}: its Given doesn't compile: {e}")
        if values["Calls"] not in CALLS:
            problems.append(f"{where}: `Calls:` is one of {', '.join(CALLS)}, not {values['Calls']!r}")
        play = 0.0
        if values["Play"] != "none":
            seconds = PLAY.match(values["Play"])
            if seconds is None or float(seconds.group(1)) <= 0:
                problems.append(f"{where}: `Play:` is `none` or seconds such as `2 s`, not {values['Play']!r}")
            else:
                play = float(seconds.group(1))
        for name in ("Ask", "Verify"):
            if not values[name] or values[name] == "none":
                problems.append(f"{where}: its `{name}:` is empty")
        cases.append(
            OutcomeCase(cid, head.group(2).strip(), given, values["Ask"], values["Verify"], values["Calls"], play)
        )
    ids = [c.id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append("outcomes.md: an outcome ID appears twice")
    return Outcomes(header, tuple(cases)), problems


def outcomes_asked(value: str | None, phases_given: bool, outcomes: Outcomes) -> list[str]:
    """`all`, `none` or `O1,O3`; when left out, every outcome in a run of every phase and none in a run of some."""
    known = [c.id for c in outcomes.cases]
    if value is None:
        return [] if phases_given else known
    value = value.strip()
    if value in ("all", "none"):
        return known if value == "all" else []
    asked = [part.strip() for part in value.split(",")]
    unknown = [part for part in asked if part not in known]
    if unknown:
        raise ValueError(f"--outcomes: {', '.join(unknown)} isn't an outcome outcomes.md has (all, none or O1,O3)")
    return [cid for cid in known if cid in asked]


# ----- which sessions a run holds -----


AGENT, JUDGE = "outcome", "judge"


@dataclass(frozen=True)
class Session:
    # "phase"; "setup": the needed scenarios a later phase in the run uses; AGENT: an outcome's agent; JUDGE: its judge
    kind: str
    ids: tuple[str, ...]
    phase: int  # the phase it runs, or for setup the phase it comes before; 0 for an outcome's sessions
    new_stage: bool  # the first session of a half: new_scene() first

    @property
    def label(self) -> str:
        if self.kind in (AGENT, JUDGE):
            return f"{self.kind}-{self.ids[0]}"
        return f"{self.kind}-{self.phase:02d}"


def phases_asked(value: str | None, suite: Suite) -> set[int]:
    """`15`, `15-16` or `18-21,24`; every phase when empty; none for `none`, a run of outcomes alone."""
    known = {p.number for p in suite.phases}
    if not value:
        return known
    if value.strip() == "none":
        return set()
    asked: set[int] = set()
    for part in value.split(","):
        bounds = part.strip().split("-")
        if not all(b.strip().isdigit() for b in bounds) or len(bounds) > 2:
            raise ValueError(f"--phases: {part.strip()!r} isn't a phase or a range like 18-21")
        low, high = int(bounds[0]), int(bounds[-1])
        unknown = sorted(n for n in range(low, high + 1) if n not in known)
        if low > high or unknown:
            raise ValueError(f"--phases: {part.strip()!r} names phases scenarios.md doesn't have")
        asked.update(range(low, high + 1))
    return asked


def plan(suite: Suite, asked: Iterable[int], outcomes: Sequence[str] = ()) -> list[Session]:
    """The run's sessions: each half asked starts on a new stage; in it the needed scenarios the run lacks and the
    asked phases go in ID order, each group of needed ones just before the first asked phase after them; then each
    outcome asked, its agent and its judge, on a stage the runner prepares; the cleanup phase ends the run."""
    cleanup = suite.cleanup
    wanted = set(asked) - {cleanup}
    sessions: list[Session] = []
    for side in (0, 1):
        mine = sorted(p for p in wanted if half(p) == side)
        if not mine:
            continue
        in_run = {s.id for p in mine for s in suite.phase(p).scenarios}
        needed: set[str] = set()
        stack = [n for p in mine for n in suite.phase(p).needs or ()]
        while stack:
            sid = stack.pop()
            found = suite.scenario(sid)
            if sid in in_run or sid in needed or found is None:
                continue
            needed.add(sid)
            stack.extend(suite.phase(found.phase).needs or ())
        order = {sid: s.order for sid in needed if (s := suite.scenario(sid))}
        waiting = sorted(needed, key=lambda sid: order[sid])
        start = len(sessions)
        for number in mine:
            group = tuple(sid for sid in waiting if order[sid] < (number, 0))
            waiting = [sid for sid in waiting if sid not in group]
            if group:
                sessions.append(Session("setup", group, number, len(sessions) == start))
            ids = tuple(s.id for s in suite.phase(number).scenarios)
            sessions.append(Session("phase", ids, number, len(sessions) == start))
    for case_id in outcomes:
        sessions += [Session(AGENT, (case_id,), 0, False), Session(JUDGE, (case_id,), 0, False)]
    sessions.append(Session("phase", tuple(s.id for s in suite.phase(cleanup).scenarios), cleanup, False))
    return sessions


# ----- what a tester is told, and what it answers -----


def session_needs(suite: Suite, session: Session) -> list[str]:
    """The IDs a session uses from earlier sessions: a phase's Needs: line, or for setup what its scenarios' phases
    need beyond the group itself."""
    if session.kind == "phase":
        return list(suite.phase(session.phase).needs or ())
    found = [s for sid in session.ids if (s := suite.scenario(sid))]
    wanted = [n for s in found for n in suite.phase(s.phase).needs or ()]
    return sorted({n for n in wanted if n not in session.ids}, key=lambda n: _order(suite, n))


def _order(suite: Suite, sid: str) -> tuple[int, int]:
    found = suite.scenario(sid)
    return found.order if found else (0, 0)


def prompt(suite: Suite, session: Session, statuses: Mapping[str, str], run_dir: Path, port: int) -> str:
    """The text a session's tester gets: the header, its scenarios with `<run>` filled in, what it needs with their
    status so far, and how to answer."""
    run = run_dir.as_posix()
    lines = [f"You are the scenario tester for the Omniverse MCP. The Kit app is at port {port}."]
    if session.new_stage:
        lines.append("This session starts a new stage: call new_scene() before anything else.")
    needs = session_needs(suite, session)
    if needs:
        seen = ", ".join(f"{n} {statuses.get(n, NOT_RUN)}" for n in needs)
        lines.append(
            f"These scenarios use what {', '.join(needs)} made. Their status in this run so far: {seen}. SKIP a "
            "scenario that needs one whose status isn't PASS or WARN, and say which."
        )
    lines += ["", "The scenarios' header:", "", suite.header, ""]
    if session.kind == "setup":
        lines.append("Run these scenarios, which make what a later phase uses, in this order:")
        lines.append("")
        lines += [s.text.replace("<run>", run) for sid in session.ids if (s := suite.scenario(sid))]
    else:
        lines += ["Run this phase:", "", suite.phase(session.phase).text.replace("<run>", run)]
    lines += [
        "",
        "End your last message with your rows as one Markdown table with the columns | ID | Test | Status | Notes |: "
        f"one row for each of {', '.join(session.ids)}, in that order. Status is PASS, FAIL, WARN or SKIP. Notes say "
        "what you saw, with its numbers, and name the capture under mcp_output/ for a FAIL or WARN.",
    ]
    return "\n".join(lines)


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]} [... {len(text) - limit} more characters]"


def judge_prompt(case: OutcomeCase, agent: Outcome, files: Sequence[Path], port: int) -> str:
    """The text an outcome's judge gets: the request, the Verify lines, what the agent called and answered, its last
    message and the files its server wrote, by absolute path, and how to answer."""
    played = (
        f"The runner then played the simulation for {case.play:g} s and paused it: the stage is as physics left it."
        if case.play
        else "The timeline is stopped: the stage is as the assistant left it, with any play it ran stopped."
    )
    lines = [
        f"You judge outcome {case.id} of the Omniverse MCP's scenario suite. The Kit app is at port {port}. An "
        "assistant was given a user's request, below, and acted on the Kit app with the MCP's tools. It never saw the "
        f"Verify lines: judge what it did against them, as the judging rules say. {played}",
        "",
        "The request:",
        "",
        case.ask,
        "",
        "Verify:",
        "",
        case.verify,
        "",
        f"The assistant's calls, in order, each answer cut to {ANSWER_CHARS} characters:",
        "",
    ]
    for n, call in enumerate(agent.calls, 1):
        lines.append(f"{n}. {call['name']} {_cut(call['input'], ANSWER_CHARS)}")
        lines.append(f"   -> {_cut(call['answer'], ANSWER_CHARS)}" if call["answer"] else "   -> (no answer came)")
    if not agent.calls:
        lines.append("none")
    if agent.stopped:
        lines += ["", f"The runner stopped the assistant: {agent.stopped}."]
    lines += ["", "The assistant's last message:", "", agent.text.strip() or "(none)", ""]
    lines += ["The files the assistant's server wrote, which your Read reaches:", ""]
    lines += [f"- {path.as_posix()}" for path in files] or ["none"]
    lines += [
        "",
        "End your last message with your row as one Markdown table with the columns | ID | Test | Status | Notes |: "
        f"one row, for {case.id}. Status is PASS, FAIL, WARN or SKIP. Notes say what you checked, with its numbers, "
        "and name the capture for a FAIL or WARN.",
    ]
    return "\n".join(lines)


def calls_note(case: OutcomeCase, names: Sequence[str]) -> str:
    """What breaks the outcome's Calls: line, or ""."""
    scripts = sum(1 for name in names if name == NO_SCRIPT)
    if case.calls == "no execute_script" and scripts:
        return f"Calls: execute_script {scripts}, where the line says none"
    return ""


def summarise_calls(names: Sequence[str]) -> str:
    """`create_prim, set_material x2, capture_viewport (4 calls, 0 execute_script)`: repeats in a row counted once."""
    if not names:
        return "none"
    runs: list[list[Any]] = []
    for name in names:
        if runs and runs[-1][0] == name:
            runs[-1][1] += 1
        else:
            runs.append([name, 1])
    order = ", ".join(name if n == 1 else f"{name} x{n}" for name, n in runs)
    return f"{order} ({len(names)} calls, {sum(1 for n in names if n == NO_SCRIPT)} execute_script)"


@dataclass
class Row:
    id: str
    test: str
    status: str
    notes: str
    session: str = ""
    setup: bool = False


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body.removeprefix("|").removesuffix("|")
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", body)]


def rows_from(text: str, ids: Sequence[str]) -> dict[str, Row]:
    """The rows of the last `| ID | Test | Status | Notes |` table in a tester's message, for the IDs asked; a status
    other than the four counts as not run, and says what the tester wrote."""
    tables: list[list[str]] = []
    current: list[str] = []
    for line in [*text.splitlines(), ""]:
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    for table in reversed(tables):
        head = [c.lower() for c in _cells(table[0])]
        if head[:4] != ["id", "test", "status", "notes"]:
            continue
        rows: dict[str, Row] = {}
        for line in table[1:]:
            cells = _cells(line)
            if len(cells) < 4 or set(cells[0]) <= set("-: "):
                continue
            sid = cells[0].strip("*` ").replace(" to ", "-")
            if sid not in ids or sid in rows:
                continue
            status = cells[2].strip("*` ").upper()
            notes = " | ".join(cells[3:])
            if status not in STATUSES:
                notes = f"the tester wrote status {cells[2]!r}: {notes}"
                status = NOT_RUN
            rows[sid] = Row(sid, cells[1], status, notes)
        return rows
    return {}


# ----- the run's folders -----


def main_checkout(cwd: Path = ROOT) -> Path:
    """The repository's main working tree, the first `git worktree list` names: every worktree's runs go there."""
    out = gate.git("worktree", "list", "--porcelain", cwd=cwd).stdout
    first = next((line[len("worktree ") :] for line in out.splitlines() if line.startswith("worktree ")), "")
    return Path(first) if first else cwd


def runs_root(cwd: Path = ROOT) -> Path:
    return main_checkout(cwd) / "test_project" / "results" / "runs"


def lock_path(runs: Path, port: int) -> Path:
    return runs / f".lock-{port}"


def session_output(run_dir: Path, session: Session) -> Path:
    """A session's own output folder: each session starts a server whose file numbers start at 1, which would write
    over the captures an earlier session's rows cite (step 9)."""
    return run_dir / "mcp_output" / session.label


def server_entry(port: int, output: Path, checkout: Path = ROOT) -> dict[str, Any]:
    """The tester's one MCP server: this checkout's, on the loopback at the port, with the port's token file (an
    empty OMNIVERSE_MCP_TOKEN counts as unset) and the session's output folder."""
    return {
        "command": "uv",
        "args": ["run", "--no-sync", "--project", checkout.as_posix(), "omniverse-mcp"],
        "env": {
            "PYTHONPATH": "",
            "OMNIVERSE_MCP_HOST": LOOPBACK,
            "OMNIVERSE_MCP_PORT": str(port),
            "OMNIVERSE_MCP_TOKEN": "",
            "OMNIVERSE_MCP_OUTPUT_DIR": output.as_posix(),
        },
    }


def write_config(dest: Path, port: int, output: Path, checkout: Path = ROOT) -> None:
    """A session's configuration, written afresh outside the runs folder: the plugin's skills without its server, and
    the server in mcp.json."""
    shutil.copytree(checkout / "plugin", dest / "plugin", ignore=shutil.ignore_patterns(".mcp.json"))
    servers = {"mcpServers": {SERVER: server_entry(port, output, checkout)}}
    (dest / "mcp.json").write_text(json.dumps(servers, indent=2) + "\n", encoding="utf-8")


def skill_names(checkout: Path = ROOT) -> list[str]:
    return sorted(p.parent.name for p in (checkout / "plugin" / "skills").glob("*/SKILL.md"))


def tester_command(
    claude: str,
    config: Path,
    rules: str,
    budget_left: float | None = None,
    model: str | None = None,
    checkout: Path = ROOT,
    *,
    tools: Sequence[str] = BUILTIN_TOOLS,
    allowed: Sequence[str] | None = None,
    disallowed: Sequence[str] = (),
    restricted: bool = False,
    add_dirs: Sequence[Path] = (),
) -> list[str]:
    """The tester's command line, as step 2 found it works: only the run's server, no settings source, the tester's
    rules appended, no shell, web or writes, every omniverse tool and the plugin's skills allowed, the rest refused.

    The prompt goes to its stdin, not the command line: a judge's, with the agent's calls and answers, passed Windows'
    32,767 characters for a command line in the first outcome run. An outcome's sessions narrow it: `restricted`
    confines the file tools to the working folder and `add_dirs`; a judge gets its own `tools`, `allowed` and
    `disallowed` lists."""
    skills = [f"Skill({PLUGIN_NAME}:{name})" for name in skill_names(checkout)]
    if allowed is None:
        allowed = [f"mcp__{SERVER}", "Read", "Grep", "Glob", *skills]
    cmd = [
        claude,
        "-p",
        "--plugin-dir",
        str(config / "plugin"),
        "--strict-mcp-config",
        "--mcp-config",
        str(config / "mcp.json"),
        "--setting-sources",
        "",
        "--append-system-prompt",
        rules,
        "--tools",
        ",".join(tools),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        *allowed,
        "--output-format",
        "stream-json",
        "--verbose",
        # Each session's working folder would otherwise become a project of its own in ~/.claude/projects.
        "--no-session-persistence",
    ]
    if disallowed:
        cmd += ["--disallowedTools", *disallowed]
    if restricted:
        cmd.append("--restricted")
    for folder in add_dirs:
        cmd += ["--add-dir", str(folder)]
    if budget_left is not None:
        cmd += ["--max-budget-usd", f"{budget_left:.2f}"]
    if model:
        cmd += ["--model", model]
    return cmd


def tester_env() -> dict[str, str]:
    """The tester's environment: the maintainer's auto-memory stays out (step 2, S4)."""
    return {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


def server_tools(contract: Path = TOOL_CONTRACT) -> tuple[list[str], list[str]]:
    """The server's tools as Claude Code names them, read-only first by the contract's readOnlyHint, then the rest: a
    judge gets the first and is refused the second, so a new read-only tool joins it on its own."""
    tools = json.loads(contract.read_text(encoding="utf-8"))["tools"]
    names = {name: bool((tool.get("annotations") or {}).get("readOnlyHint")) for name, tool in tools.items()}
    read_only = [f"mcp__{SERVER}__{name}" for name, ro in sorted(names.items()) if ro]
    others = [f"mcp__{SERVER}__{name}" for name, ro in sorted(names.items()) if not ro]
    return read_only, others


# ----- check -----


@dataclass
class Kit:
    stage: str = ""
    bridge_version: str = ""
    bridge_folder: str = ""
    app: str = ""
    version: str = ""
    kit: str = ""
    prim_count: int | None = None


def connect(port: int, timeout: float = PROBE_SECONDS) -> BridgeClient:
    """A client for the loopback at the port with the port's token file alone: the shell's OMNIVERSE_MCP_HOST and
    OMNIVERSE_MCP_TOKEN may be set for another Kit app."""
    path = token_path(port)
    token = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    return BridgeClient(host=LOOPBACK, port=port, timeout=timeout, token=token)


def answer(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status") != "success":
        raise BridgeError(str(response.get("error", response)))
    result: dict[str, Any] = response.get("result") or {}
    return result


def _inside(path: Path, folder: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(path), os.path.normcase(folder)]) == os.path.normcase(folder)
    except ValueError:  # another drive
        return False


def stage_problem(stage: str, runs: Path, temp: Path) -> str | None:
    """A stage the scenarios may wipe: unsaved, a file under the runs folder, or a local path under the system temp
    folder that no longer exists (the live suites leave the stage tied to a deleted copy). Anything else, a URL
    included, is someone's scene."""
    if stage in ("", "(unsaved)"):
        return None
    if "://" not in stage:
        path = Path(stage).resolve()
        if _inside(path, runs.resolve()):
            return None
        if _inside(path, temp.resolve()) and not path.exists():
            return None
    return (
        f"the Kit app has {stage} open, and the scenarios wipe the stage: close it, or pass --any-stage on the "
        "maintainer's word"
    )


def tracked_bridge_files(checkout: Path = ROOT) -> list[str]:
    prefix = BRIDGE + "/"
    out = gate.git("ls-files", BRIDGE, cwd=checkout).stdout.splitlines()
    return [line[len(prefix) :] for line in out if line.startswith(prefix)]


def _digest(path: Path) -> str | None:
    """A file's hash as git stores it under .gitattributes' `text=auto eol=lf`: CRLF as LF unless the file holds a NUL,
    git's sign of a binary. A copy from an older Windows checkout or a zip keeps CRLF, and is the same code."""
    if not path.is_file():
        return None
    data = path.read_bytes()
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def bridge_problems(checkout: Path, kit_folder: Path, tracked: Sequence[str]) -> list[str]:
    """Whether the bridge Kit loaded has this checkout's files: each tracked file by its relative path, Kit's caches
    ignored, and any .py Kit's copy holds beyond them named."""
    if not kit_folder.is_dir():
        return [
            f"the bridge Kit loaded is in {kit_folder}, which isn't on this machine: pass --any-bridge to run anyway"
        ]
    ours = checkout / BRIDGE
    differ = [rel for rel in tracked if _digest(ours / rel) != _digest(kit_folder / rel)]
    known = set(tracked)
    extra = sorted(
        p.relative_to(kit_folder).as_posix()
        for p in kit_folder.rglob("*.py")
        if "__pycache__" not in p.parts and p.relative_to(kit_folder).as_posix() not in known
    )
    problems = []
    if differ:
        shown = ", ".join(differ[:5]) + (f" and {len(differ) - 5} more" if len(differ) > 5 else "")
        problems.append(
            f"the bridge in {kit_folder} differs from this checkout's {BRIDGE}: {shown}. Copy this checkout's bridge "
            "there and restart Kit, or pass --any-bridge"
        )
    if extra:
        problems.append(f"the bridge in {kit_folder} holds Python this checkout doesn't: {', '.join(extra[:5])}")
    return problems


def check(
    port: int,
    runs: Path,
    *,
    allow_gui_port: bool = False,
    any_stage: bool = False,
    any_bridge: bool = False,
    connect: Callable[[int], BridgeClient] = connect,
    checkout: Path = ROOT,
    temp: Path | None = None,
) -> tuple[list[str], Kit]:
    """Whether a run may drive the Kit app at the port, in the plan's order: the port before any request or token
    read, then /health, the stage, the bridge's files, and the lock. Kit's facts, as far as it got."""
    kit = Kit()
    if port == GUI_PORT and not allow_gui_port:
        return [
            f"port {GUI_PORT} is every Kit app's default and the maintainer's own, and a run wipes its stage: pass "
            f"--port {GUI_PORT} --allow-port-{GUI_PORT} only when the maintainer named it"
        ], kit
    if not token_path(port).is_file():
        return [f"no bridge token at {token_path(port)}, so no ovmcp.bridge has run on port {port}. {START_HINT}"], kit
    client = connect(port)
    problems: list[str] = []
    try:
        health = answer(client.health())
        kit.stage = str(health.get("stage_path", ""))
        kit.bridge_version = str(health.get("extension_version", ""))
        stage = stage_problem(kit.stage, runs, temp or Path(tempfile.gettempdir()))
        if stage and not any_stage:
            problems.append(stage)
        facts = answer(client.execute(KIT_FACTS)).get("return_value") or {}
        kit.bridge_folder = str(facts.get("folder", ""))
        kit.app, kit.version, kit.kit = (str(facts.get(k, "")) for k in ("app", "version", "kit"))
        if not any_bridge:
            problems += bridge_problems(checkout, Path(kit.bridge_folder), tracked_bridge_files(checkout))
        kit.prim_count = answer(client.sim_state()).get("prim_count")
    except BridgeError as e:
        # It answered: a refused token, another protocol or a failed script, which starting Kit wouldn't mend.
        return [f"the Kit app at {LOOPBACK}:{port} refused: {e}"], kit
    except OSError as e:
        return [f"no answer from a Kit app at {LOOPBACK}:{port}: {e}. {START_HINT}"], kit
    finally:
        client.close()
    lock = lock_path(runs, port)
    if lock.exists():
        problems.append(
            f"{lock} says a run drives port {port}: wait for it, or delete the file once no run is going "
            f"({lock.read_text(encoding='utf-8').strip()})"
        )
    return problems, kit


def describe(kit: Kit, port: int) -> str:
    app = " ".join(v for v in (kit.app, kit.version) if v) or "a Kit app"
    prims = "?" if kit.prim_count is None else kit.prim_count
    return (
        f"{app} (Kit {kit.kit or '?'}) at {LOOPBACK}:{port}; ovmcp.bridge {kit.bridge_version or '?'} from "
        f"{kit.bridge_folder or '?'}; stage {kit.stage or '?'} with {prims} prims"
    )


# ----- one session -----


class HealthWatch:
    """Ends a run when Kit stops answering: a probe every PROBE_EVERY seconds, and a stop once no probe has answered
    for SILENCE_LIMIT seconds, counted from the start of the first one that got no answer. The cause may be a
    tester's script holding Kit's main thread, or a hang inside Kit (#54): the session names the call in flight."""

    def __init__(self, probe: Callable[[], bool], clock: Callable[[], float] = time.monotonic) -> None:
        self.probe = probe
        self.clock = clock
        self.next_at: float | None = None
        self.silent_since: float | None = None

    def check(self) -> str | None:
        started = self.clock()
        if self.next_at is not None and started < self.next_at:
            return None
        answered = self.probe()
        self.next_at = started + PROBE_EVERY
        if answered:
            self.silent_since = None
            return None
        if self.silent_since is None:
            self.silent_since = started
        silent = self.clock() - self.silent_since
        if silent >= SILENCE_LIMIT:
            return f"Kit stopped answering: /health has given no answer for {silent:.0f} s"
        return None


def health_probe(port: int) -> Callable[[], bool]:
    def probe() -> bool:
        client = connect(port)
        try:
            client.health()
        except BridgeError:
            return True  # a refusal is an answer: Kit runs
        except OSError:
            return False
        finally:
            client.close()
        return True

    return probe


@dataclass(frozen=True)
class Expect:
    """What a session's init event must show beyond every tester's rules: a judge's exact tools, an agent's plugin."""

    tools: frozenset[str] | None = None  # every tool it may list; None: the built-ins and any of the run's server's
    plugin: bool = False  # the run's plugin must be there: --restricted is new to the testers


def init_problems(event: Mapping[str, Any], plugin_dir: Path, expect: Expect | None = None) -> list[str]:
    """What the session's first event shows that a tester must not have: a server other than the run's, the run's
    not connected, a tool outside the command's list, a plugin other than the run's copy and Claude Code's built-in
    ones, or a memory path; and what `expect` asks for that it lacks."""
    expect = expect or Expect()
    problems = []
    servers = list(event.get("mcp_servers") or [])
    names = [str(s.get("name")) for s in servers]
    if names != [SERVER]:
        problems.append(f"MCP servers {names}, where only {SERVER!r} may run")
    elif servers[0].get("status") != "connected":
        problems.append(f"the {SERVER!r} server is {servers[0].get('status')!r}, not connected")
    tools = [str(t) for t in event.get("tools") or []]
    if expect.tools is not None:
        foreign = [t for t in tools if t not in expect.tools]
    else:
        foreign = [t for t in tools if t not in BUILTIN_TOOLS and not t.startswith(f"mcp__{SERVER}__")]
    if foreign:
        problems.append(f"tools outside the run's list: {', '.join(foreign)}")
    ours = os.path.normcase(plugin_dir.resolve())
    found = False
    for plugin in event.get("plugins") or []:
        path = str(plugin.get("path", ""))
        if path == "builtin":
            continue
        if os.path.normcase(Path(path).resolve()) != ours:
            problems.append(f"a plugin other than the run's: {plugin.get('name')} from {path}")
        else:
            found = True
    if expect.plugin and not found:
        problems.append(f"no {PLUGIN_NAME} plugin from the run's copy, so none of its skills")
    if event.get("memory_paths"):
        problems.append(f"a memory path: {event.get('memory_paths')}")
    return problems


@dataclass
class Outcome:
    exit: int | None = None
    text: str = ""  # the tester's last message
    cost: float = 0.0
    cost_known: bool = False  # a stopped tester sends no result event, so its cost is unknown
    turns: int | None = None
    tokens: dict[str, int] = field(default_factory=dict)  # the result event's usage
    model: str = ""
    skills: list[str] = field(default_factory=list)  # the plugin's skills a call loaded, not the refused ones
    stopped: str = ""  # why the script ended the session, if it did
    kit_hung: bool = False
    init_failed: bool = False  # the session's first event showed what a tester must not have, or never came
    started: str = ""
    ended: str = ""
    seconds: float = 0.0
    in_flight: dict[str, str] = field(default_factory=dict)  # the tool calls sent and not yet answered, by id
    timed_out: list[str] = field(default_factory=list)  # the tool calls whose answer was a timeout
    init_seen: bool = False
    skill_calls: dict[str, str] = field(default_factory=dict)  # the Skill calls awaiting their result, by id
    # The run's server's calls in order, each {"name", "input", "answer"}, the name without its prefix: an outcome's
    # judge reads them, and the Calls: check counts them.
    calls: list[dict[str, str]] = field(default_factory=list)
    call_at: dict[str, int] = field(default_factory=dict)  # each server call's place in `calls`, by id

    @property
    def call_names(self) -> list[str]:
        return [call["name"] for call in self.calls]


def _named(tools: Iterable[str]) -> str:
    return ", ".join(sorted({f"`{name.removeprefix(f'mcp__{SERVER}__')}`" for name in tools}))


def stop_message(hung: str, outcome: Outcome) -> str:
    """Why the watch stopped a session, with the calls it had in flight and those that timed out: step 9 met both a
    tester's script holding Kit's main thread and a hang inside NVIDIA's code (#54)."""
    held = f", while {_named(outcome.in_flight.values())} ran" if outcome.in_flight else ""
    after = f", after {_named(outcome.timed_out)} timed out" if outcome.timed_out else ""
    return f"{hung}{held}{after}: a script holding Kit's main thread, or a hang inside Kit"


def end_tree(proc: subprocess.Popen[str]) -> None:
    """End a tester and everything it started, its server among them: on Windows Popen.kill ends only claude.exe,
    and the server's call in Kit could run on into the next session."""
    if proc.poll() is None:
        if os.name == "nt":
            taskkill = shutil.which("taskkill") or "taskkill"
            gate.run([taskkill, "/T", "/F", "/PID", str(proc.pid)])
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=60)


def run_session(
    cmd: Sequence[str],
    transcript: Path,
    plugin_dir: Path,
    watch: HealthWatch | None = None,
    limit: float = SESSION_SECONDS,
    cwd: Path = TEST_PROJECT,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], float] = time.monotonic,
    expect: Expect | None = None,
    prompt: str = "",
) -> Outcome:
    """Run one tester on `prompt`, sent to its stdin, keep its stream in the transcript, and read what it did: its
    model, skill loads, cost and last message. Stop it at once on a bad init event, after `limit` seconds, or when the
    watch says Kit hangs; whatever ends this function, an interrupt or an error included, ends the tester and its
    server too."""
    outcome = Outcome(started=datetime.now().isoformat(timespec="seconds"))
    started = clock()
    proc = subprocess.Popen(  # noqa: S603 - an argument list the script builds itself; nothing goes through a shell
        list(cmd),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def feed() -> None:
        # In a thread of its own: a prompt longer than the pipe holds waits for the tester to read it.
        try:
            if proc.stdin is not None:
                with proc.stdin:
                    proc.stdin.write(prompt)
        except OSError:
            pass  # the tester ended first; its exit and stream say why

    threading.Thread(target=feed, daemon=True).start()

    def pump() -> None:
        if proc.stdout is not None:
            with proc.stdout:
                for line in proc.stdout:
                    lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    last_text = ""
    exited_at: float | None = None
    finished = False
    try:
        with transcript.open("w", encoding="utf-8") as out:
            while True:
                try:
                    line = lines.get(timeout=1.0)
                except queue.Empty:
                    line = ""
                    # A child the tester started may hold its output open after it exits: don't wait on it for long.
                    if proc.poll() is not None:
                        exited_at = exited_at if exited_at is not None else clock()
                        if clock() - exited_at > 10:
                            break
                if line is None:
                    break
                if line:
                    out.write(line)
                    last_text = _read_event(line, outcome, plugin_dir, expect) or last_text
                reason = ""
                if outcome.stopped:
                    reason = outcome.stopped
                elif clock() - started > limit:
                    reason = outcome.stopped = f"stopped at the session's limit, {limit:.0f} s"
                elif watch is not None and (hung := watch.check()):
                    reason = outcome.stopped = stop_message(hung, outcome)
                    outcome.kit_hung = True
                if reason and proc.poll() is None:
                    end_tree(proc)
        finished = True
    finally:
        # A tester left running would go on driving Kit with execute_script pre-approved, unwatched: on Linux and
        # macOS its own session keeps a terminal's Ctrl+C from reaching it. After its stream ends it is on its way out.
        if finished:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                end_tree(proc)
        elif proc.poll() is None:
            end_tree(proc)
    outcome.exit = proc.wait()
    outcome.text = outcome.text or last_text
    outcome.seconds = clock() - started
    outcome.ended = datetime.now().isoformat(timespec="seconds")
    return outcome


def _answer_text(content: Any) -> str:
    """A tool result's text, its images left out: a string, or a list of parts."""
    if isinstance(content, str):
        return content
    parts = content if isinstance(content, list) else []
    return "\n".join(str(p.get("text", "")) for p in parts if isinstance(p, dict) and p.get("type") == "text")


def _read_event(line: str, outcome: Outcome, plugin_dir: Path, expect: Expect | None = None) -> str:
    """Note what one stream event says in the outcome; the assistant's text, if it holds some."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        outcome.init_seen = True
        outcome.model = str(event.get("model", ""))
        problems = init_problems(event, plugin_dir, expect)
        if problems:
            outcome.stopped = "the session's init event: " + "; ".join(problems)
            outcome.init_failed = True
    elif kind == "assistant":
        if not outcome.init_seen and not outcome.stopped:
            # Without the init event nothing says which servers and tools the tester has: fail closed.
            outcome.stopped = "the session acted before its init event, so its servers and tools are unchecked"
            outcome.init_failed = True
        texts = []
        for part in (event.get("message") or {}).get("content") or []:
            if part.get("type") == "tool_use":
                call = str(part.get("id", ""))
                name = str(part.get("name", ""))
                outcome.in_flight[call] = name
                if name == "Skill":
                    outcome.skill_calls[call] = str((part.get("input") or {}).get("skill", ""))
                elif name.startswith(f"mcp__{SERVER}__"):
                    outcome.call_at[call] = len(outcome.calls)
                    given = json.dumps(part.get("input") or {}, ensure_ascii=False)
                    outcome.calls.append({"name": name.removeprefix(f"mcp__{SERVER}__"), "input": given, "answer": ""})
            elif part.get("type") == "text":
                texts.append(str(part.get("text", "")))
        return "\n".join(texts)
    elif kind == "user":
        content = (event.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                call = str(part.get("tool_use_id", ""))
                name = outcome.in_flight.pop(call, "")
                skill = outcome.skill_calls.pop(call, "")
                if call in outcome.call_at:
                    said = _answer_text(part.get("content"))
                    said = f"error: {said}" if part.get("is_error") else said
                    outcome.calls[outcome.call_at.pop(call)]["answer"] = said[:ANSWER_KEPT]
                if part.get("is_error"):
                    if "timed out" in json.dumps(part.get("content")):
                        outcome.timed_out.append(name)
                elif skill.startswith(f"{PLUGIN_NAME}:"):
                    # Only a load that went through counts: dontAsk refuses Claude Code's own skills (step 2, S7).
                    outcome.skills.append(skill)
    elif kind == "result":
        outcome.cost = float(event.get("total_cost_usd") or 0.0)
        outcome.cost_known = True
        outcome.turns = event.get("num_turns")
        usage = event.get("usage") or {}
        outcome.tokens = {k: int(v) for k, v in usage.items() if k.endswith("_tokens") and isinstance(v, int)}
        outcome.text = str(event.get("result") or "")
    return ""


# ----- a run -----


@dataclass
class SessionRecord:
    label: str
    kind: str
    phase: int
    ids: list[str]
    new_stage: bool
    started: str = ""
    ended: str = ""
    exit: int | None = None
    cost: float = 0.0
    cost_known: bool = True
    turns: int | None = None
    tokens: dict[str, int] = field(default_factory=dict)
    model: str = ""
    seconds: float = 0.0
    skills: list[str] = field(default_factory=list)
    stopped: str = ""
    calls: list[str] = field(default_factory=list)  # an outcome's agent: the run's server's calls, in order


Launch = Callable[[Session, str, float | None], Outcome]


class PlayError(BridgeError):
    """The runner's play didn't reach its seconds: Kit answered, but the simulation's time didn't move that far."""


def written_files(folder: Path) -> list[Path]:
    """The files a session's server wrote, by absolute path: the judge's Read reaches them by these."""
    return sorted(p.resolve() for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else []


def run_sessions(
    suite: Suite,
    sessions: Sequence[Session],
    run_dir: Path,
    port: int,
    launch: Launch,
    settle: Callable[[], None],
    budget: float | None = None,
    records: list[SessionRecord] | None = None,
    rows: list[Row] | None = None,
    outcomes: Outcomes | None = None,
    prepare: Callable[[OutcomeCase], None] | None = None,
    play: Callable[[float], None] | None = None,
) -> tuple[list[SessionRecord], list[Row]]:
    """Run the sessions in order, each told its needed scenarios' status so far; stop starting them once Kit hangs, a
    session's init check fails (it would in every session), or the budget is spent. Each session's last message
    becomes its phase file, and its table its rows. `records` and `rows` fill as it goes, so a run cut short still
    has them.

    An outcome is two sessions. Before its agent the runner prepares the stage (`prepare`); before its judge, after
    the settle, it plays (`play`) when the outcome has a Play: line. The judge gives the outcome's row, a PASS capped
    at WARN when the agent broke its Calls: line. An error Kit answers there makes that outcome NOT RUN; no answer
    halts the run, as a settle's does."""
    statuses: dict[str, str] = {}
    records = [] if records is None else records
    rows = [] if rows is None else rows
    spent = 0.0
    halt = ""
    unknown: list[str] = []  # the sessions whose cost is unknown, counted at their whole allowance
    agents: dict[str, tuple[Outcome, list[Path]]] = {}  # each outcome's agent and the files its server wrote
    refused: dict[str, str] = {}  # the outcomes whose stage Kit refused to prepare or play, and why

    def title(sid: str) -> str:
        case = outcomes.case(sid) if outcomes else None
        scenario = suite.scenario(sid)
        return case.title if case else scenario.title if scenario else ""

    def not_run(session: Session, note: str) -> None:
        if session.kind == AGENT:
            return  # its judge gives the outcome's row
        for sid in session.ids:
            row = Row(sid, title(sid), NOT_RUN, note, session.label, session.kind == "setup")
            statuses[sid] = row.status
            rows.append(row)

    for index, session in enumerate(sessions):
        record = SessionRecord(session.label, session.kind, session.phase, list(session.ids), session.new_stage)
        records.append(record)
        case = outcomes.case(session.ids[0]) if outcomes and session.kind in (AGENT, JUDGE) else None
        left = None if budget is None else budget - spent
        if not halt and left is not None and left <= 0:
            known = f"the budget of ${budget:.2f} is spent"
            halt = f"the budget may be spent: {', '.join(unknown)}'s cost is unknown" if unknown else known
        why = ""
        outcome: Outcome | None = None
        try:
            if not halt:
                try:
                    settle()
                except (OSError, BridgeError) as e:
                    halt = f"Kit didn't answer between sessions: {e}"
            why = refused.get(case.id, "") if case else ""
            if not halt and case and not why:
                try:
                    if session.kind == AGENT and prepare is not None:
                        prepare(case)
                    elif session.kind == JUDGE and case.play and play is not None:
                        play(case.play)
                except BridgeError as e:
                    why = f"preparing its stage: {e}" if session.kind == AGENT else f"the runner's play: {e}"
                    refused[case.id] = why
                except OSError as e:
                    halt = f"Kit didn't answer: {e}"
            if not (halt or why):
                if case and session.kind == AGENT:
                    text = case.ask
                elif case:
                    text = judge_prompt(case, *agents[case.id], port)
                else:
                    text = prompt(suite, session, statuses, run_dir, port)
                outcome = launch(session, text, left)
        except BaseException:
            # An interrupt or an error, in the runner's own steps too (a play can take 18 s): the record says so,
            # rather than reading as a run that finished.
            record.stopped, record.cost_known = "cut short", False
            not_run(session, "the run was cut short")
            for later in sessions[index + 1 :]:
                skipped = SessionRecord(later.label, later.kind, later.phase, list(later.ids), later.new_stage)
                skipped.stopped = "not run: the run was cut short"
                records.append(skipped)
                not_run(later, "the run was cut short")
            raise
        if outcome is None:
            record.stopped = f"not run: {halt or why}"
            found: dict[str, Row] = {}
        else:
            # A stopped tester sends no result event: count what it was allowed to spend, so --budget stays a cap.
            spent += outcome.cost if outcome.cost_known else (left or 0.0)
            if not outcome.cost_known:
                unknown.append(session.label)
            record.started, record.ended, record.seconds = outcome.started, outcome.ended, outcome.seconds
            record.exit, record.cost, record.cost_known = outcome.exit, outcome.cost, outcome.cost_known
            record.turns, record.tokens, record.model = outcome.turns, outcome.tokens, outcome.model
            record.skills, record.stopped = outcome.skills, outcome.stopped
            if outcome.kit_hung or outcome.init_failed:
                halt = outcome.stopped
            heading = f"# {session.label}: {', '.join(session.ids)}"
            (run_dir / f"{session.label}.md").write_text(f"{heading}\n\n{outcome.text}\n", encoding="utf-8")
            found = rows_from(outcome.text, session.ids)
            if case and session.kind == AGENT:
                record.calls = outcome.call_names
                agents[case.id] = (outcome, written_files(session_output(run_dir, session)))
            elif case and case.id in found:
                note = calls_note(case, agents[case.id][0].call_names)
                row = found[case.id]
                if note:
                    row.status = "WARN" if row.status == "PASS" else row.status
                    row.notes = f"{row.notes}; {note}" if row.notes else note
        if session.kind == AGENT:
            continue  # its judge gives the outcome's row
        for sid in session.ids:
            row = found.get(sid) or Row(sid, title(sid), NOT_RUN, record.stopped or "no row came")
            row.session, row.setup = session.label, session.kind == "setup"
            statuses[sid] = row.status
            rows.append(row)
    return records, rows


def results_md(record: Mapping[str, Any]) -> str:
    """The run's results for people: Run Info, the skill loads per session, every row in ID order, then the issues."""
    kit = record.get("kit") or {}
    tree = "clean" if record.get("clean") else "with changes"
    info = [
        ("Started", record.get("started", "")),
        ("Commit", f"{record.get('commit', '')} ({record.get('branch', '')}, {tree})"),
        (
            "Kit app",
            " ".join(v for v in (kit.get("app"), kit.get("version")) if v)
            + f", Kit {kit.get('kit', '?')}, port {record.get('port')}",
        ),
        ("Bridge", f"ovmcp.bridge {kit.get('bridge_version', '?')} from {kit.get('bridge_folder', '?')}"),
        ("Stage at the start", f"{kit.get('stage', '?')}, {kit.get('prim_count', '?')} prims"),
        ("Tester", f"{record.get('client', '')}, model {', '.join(record.get('models') or []) or '?'}"),
        ("Phases asked", record.get("phases", "")),
        ("Outcomes asked", record.get("outcomes", "none")),
        ("Took", f"{record.get('seconds', 0) / 60:.0f} min, ${record.get('cost', 0):.2f}{_unknown_cost(record)}"),
    ]
    out = [f"# Scenario run {record.get('name', '')}", "", "| Field | Value |", "|---|---|"]
    out += [f"| {k} | {_cell(str(v))} |" for k, v in info]
    out += ["", "## Skill loads", "", "| Session | Skills loaded | Stopped |", "|---|---|---|"]
    for s in record.get("sessions") or []:
        out.append(f"| {s['label']} | {', '.join(s['skills']) or 'none'} | {_cell(s.get('stopped') or '')} |")
    out += ["", "## Results", "", "| ID | Test | Status | Notes |", "|---|---|---|---|"]
    rows = sorted(record.get("rows") or [], key=lambda r: _id_key(r["id"]))
    for r in rows:
        notes = ("setup: " if r.get("setup") else "") + r["notes"]
        out.append(f"| {r['id']} | {_cell(r['test'])} | {r['status']} | {_cell(notes)} |")
    agents = [s for s in record.get("sessions") or [] if s.get("kind") == AGENT]
    if agents:
        status = {r["id"]: r["status"] for r in rows}
        out += ["", "## Outcomes", "", "| ID | Skills loaded | Calls | Status |", "|---|---|---|---|"]
        for s in agents:
            (case_id,) = s["ids"]
            skills = ", ".join(s.get("skills") or []) or "none"
            ran = not str(s.get("stopped", "")).startswith("not run")
            calls = summarise_calls(s.get("calls") or []) if ran else "not run"
            out.append(f"| {case_id} | {skills} | {_cell(calls)} | {status.get(case_id, NOT_RUN)} |")
    issues = [r for r in rows if r["status"] in ("FAIL", "WARN", NOT_RUN)]
    out += ["", "## Issues", ""]
    out += [f"- **{r['status']} {r['id']}** {r['test']}: {r['notes']}" for r in issues] or ["None."]
    return "\n".join(out) + "\n"


def _unknown_cost(record: Mapping[str, Any]) -> str:
    ran = [s for s in record.get("sessions") or [] if not str(s.get("stopped", "")).startswith("not run")]
    unknown = [s["label"] for s in ran if not s.get("cost_known", True)]
    return f"; cost unknown for {', '.join(unknown)}, stopped before a result event" if unknown else ""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _id_key(sid: str) -> tuple[int, int]:
    """`N.M` by its numbers; an outcome's `O<n>` after every phase, in its number's order."""
    if re.fullmatch(r"O\d+", sid):
        return (10_000, int(sid[1:]))
    major, _, minor = sid.split("-", maxsplit=1)[0].partition(".")
    return (int(major), int(minor)) if major.isdigit() and minor.isdigit() else (0, 0)


# ----- compare -----

RANK = {"PASS": 2, "WARN": 1, "FAIL": 0}


def load_runs(runs: Path) -> list[dict[str, Any]]:
    """Every finished run under the runs folder, oldest first, each with its folder's name."""
    found = []
    for path in sorted(runs.glob("*/run.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        record["name"] = path.parent.name
        found.append(record)
    return found


def pick_against(runs: Sequence[Mapping[str, Any]], value: str, cwd: Path = ROOT) -> Mapping[str, Any]:
    """A run by its folder's name, or the newest run made on a tag's (or another ref's) commit or, from a clean tree,
    on its tree: a release is run on its PR's head, and the squash merge the tag marks is a new commit with that
    tree."""
    for record in runs:
        if record["name"] == value:
            return record

    def resolve(kind: str) -> str:
        return gate.git("rev-parse", "--verify", "--quiet", f"{value}^{{{kind}}}", cwd=cwd).stdout.strip()

    commit, tree = resolve("commit"), resolve("tree")
    matches = [r for r in runs if commit and (r.get("commit") == commit or (r.get("clean") and r.get("tree") == tree))]
    if not matches:
        raise ValueError(f"--against {value}: no run has that name, and no run was made on its commit or its tree")
    return matches[-1]


def compare(
    newest: Mapping[str, Any], earlier: Sequence[Mapping[str, Any]], against: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Each of the newest run's rows against the newest earlier run with a tester status for its ID, or against one
    run: regressions, fixes, other changes, new IDs, and the IDs not run."""
    base: dict[str, tuple[Mapping[str, Any], str]] = {}
    by_name = {r["name"]: r for r in [*earlier, *([against] if against else [])]}
    for record in [against] if against else list(reversed(earlier)):
        for row in record.get("rows") or []:
            if row["status"] in STATUSES and row["id"] not in base:
                base[row["id"]] = (row, record["name"])
    report: dict[str, Any] = {"regressions": [], "fixed": [], "changed": [], "new": [], "not_run": []}
    models: set[str] = set()
    for row in newest.get("rows") or []:
        if row["status"] == NOT_RUN:
            report["not_run"].append(row)
            continue
        if row["id"] not in base:
            report["new"].append(row)
            continue
        before, name = base[row["id"]]
        models.update(_models(by_name[name]))
        if before["status"] == row["status"]:
            continue
        entry = {"now": row, "before": before, "run": name}
        if before["status"] in RANK and row["status"] in RANK and RANK[row["status"]] < RANK[before["status"]]:
            kind = "regressions"
        elif row["status"] == "PASS":
            kind = "fixed"
        else:
            # FAIL to WARN among them: the same answer, judged again by a tester, is no fix (step 9).
            kind = "changed"
        report[kind].append(entry)
    report["counts"] = Counter(r["status"] for r in newest.get("rows") or [])
    report["models"] = sorted(models - set(_models(newest)))
    # What an agent reaches for: a judge loads no skill, so it would only swell "none in N of M".
    ran = [
        s
        for s in newest.get("sessions") or []
        if not str(s.get("stopped", "")).startswith("not run") and s.get("kind") != JUDGE
    ]
    report["skills"] = Counter(skill for s in ran for skill in s.get("skills") or [])
    report["sessions"] = len(ran)
    report["without_skill"] = sum(1 for s in ran if not s.get("skills"))
    return report


def _models(record: Mapping[str, Any]) -> list[str]:
    return list(record.get("models") or [])


def format_report(newest: Mapping[str, Any], report: Mapping[str, Any]) -> str:
    kit = newest.get("kit") or {}
    app = " ".join(v for v in (kit.get("app"), kit.get("version")) if v) or "a Kit app"
    lines = [
        f"Run {newest['name']} (phases {newest.get('phases', '?')}, {len(newest.get('rows') or [])} IDs; "
        f"{newest.get('branch', '?')} {str(newest.get('commit', ''))[:7]}; {app} on {newest.get('port')}; "
        f"model {', '.join(_models(newest)) or '?'})"
    ]
    if report["models"]:
        lines.append(f"Compared with runs by another model too: {', '.join(report['models'])}")
    for key, title in (("regressions", "Regressions"), ("fixed", "Fixed"), ("changed", "Other changes")):
        lines.append(f"{title} ({len(report[key])})")
        for e in report[key]:
            lines.append(
                f'  {e["now"]["id"]}  {e["before"]["status"]} -> {e["now"]["status"]}  "{e["now"]["notes"]}"  '
                f'(was {e["before"]["status"]} in {e["run"]}: "{e["before"]["notes"]}")'
            )
    lines.append(f"New ({len(report['new'])}): {', '.join(r['id'] for r in report['new']) or 'none'}")
    lines.append(f"Not run ({len(report['not_run'])}): {', '.join(r['id'] for r in report['not_run']) or 'none'}")
    counts = report["counts"]
    lines.append("Counts: " + ", ".join(f"{counts.get(s, 0)} {s}" for s in (*STATUSES, NOT_RUN)))
    skills = ", ".join(f"{name} {n}" for name, n in sorted(report["skills"].items())) or "none"
    lines.append(f"Skills loaded: {skills}; none in {report['without_skill']} of {report['sessions']} sessions")
    return "\n".join(lines)


# ----- the commands -----


def _git_facts(cwd: Path = ROOT) -> dict[str, Any]:
    return {
        "commit": gate.git("rev-parse", "HEAD", cwd=cwd).stdout.strip(),
        "tree": gate.git("rev-parse", "HEAD^{tree}", cwd=cwd).stdout.strip(),
        "branch": gate.git("branch", "--show-current", cwd=cwd).stdout.strip(),
        "clean": not gate.git("status", "--porcelain", cwd=cwd).stdout.strip(),
    }


def cmd_check(args: argparse.Namespace) -> int:
    problems, kit = check(
        args.port,
        runs_root(),
        allow_gui_port=args.allow_port_8211,
        any_stage=args.any_stage,
        any_bridge=args.any_bridge,
    )
    print(describe(kit, args.port))
    for problem in problems:
        print(f"refused: {problem}")
    return 1 if problems else 0


def claude_executable(which: Callable[[str], str | None] = shutil.which, windows: bool = os.name == "nt") -> str:
    claude = which("claude")
    if not claude:
        raise SystemExit("Claude Code (`claude`) isn't on PATH: the tester is a headless Claude Code session")
    if windows and Path(claude).suffix.lower() in (".cmd", ".bat"):
        # cmd.exe would read the prompts' | and < as its own; the native install is an .exe.
        raise SystemExit(f"{claude} is a cmd.exe shim: install Claude Code's native build, claude.exe")
    return claude


def settle(port: int, connect: Callable[[int], BridgeClient] = connect) -> None:
    """Stop the timeline and any recording a stopped session left running, before the next session starts."""
    client = connect(port)
    try:
        answer(client.sim_control("stop"))
        if answer(client.sim_state()).get("recording_active"):
            answer(client.recording_stop())
    finally:
        client.close()


def prepare_stage(port: int, case: OutcomeCase, connect: Callable[[int], BridgeClient] = connect) -> None:
    """An outcome's stage before its agent: a new one; lit by the stage's own lights alone, since the lighting mode
    is Kit's setting, which new_scene() leaves as an earlier session set it; then the Given code. An error Kit answers
    raises BridgeError, and no answer OSError."""
    client = connect(port)
    try:
        answer(client.new_scene())
        answer(client.viewport_light("set", mode="stage"))
        if case.given:
            answer(client.execute(case.given))
    finally:
        client.close()


def run_play(
    port: int,
    seconds: float,
    connect: Callable[[int], BridgeClient] = connect,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """The runner's play before a judge, after the settle: play until the simulation's time has moved on by
    `seconds`, then pause, so the judge reads where physics put things, the same every run. PlayError when the time
    doesn't get there within PLAY_TIMES the seconds plus PLAY_SLACK; it pauses either way."""
    client = connect(port)
    try:
        answer(client.sim_control("play"))
        limit = PLAY_TIMES * seconds + PLAY_SLACK
        moved = 0.0
        try:
            # Inside the try: a read that fails after the play still pauses.
            start = float(answer(client.sim_state()).get("sim_time") or 0.0)
            began = clock()
            while clock() - began < limit:
                moved = float(answer(client.sim_state()).get("sim_time") or 0.0) - start
                if moved >= seconds:
                    return
                sleep(PLAY_EVERY)
        finally:
            answer(client.sim_control("pause"))
        raise PlayError(f"the simulation's time moved {moved:.2f} s of {seconds:g} s in {limit:.0f} s")
    finally:
        client.close()


def session_command(
    claude: str,
    session: Session,
    config: Path,
    run_dir: Path,
    rules: str,
    brief: str,
    left: float | None = None,
    model: str | None = None,
    checkout: Path = ROOT,
) -> tuple[list[str], Path, Expect | None]:
    """A session's command line, its working folder and what its init event must show.

    A phase's tester works in its own folder. An outcome's agent too, with the brief for rules and its file tools
    confined there, so outcomes.md and the judges' files stay out of its reach. A judge works in its agent's folder,
    where the paths in the agent's answers resolve, and adds its own, where its server writes; it has the read-only
    tools alone, the rest refused."""
    output = session_output(run_dir, session)
    if session.kind == AGENT:
        cmd = tester_command(claude, config, brief, left, model, checkout, restricted=True)
        return cmd, output, Expect(plugin=True)
    if session.kind == JUDGE:
        read_only, others = server_tools(checkout / TOOL_CONTRACT.relative_to(ROOT))
        cmd = tester_command(
            claude,
            config,
            rules,
            left,
            model,
            checkout,
            tools=JUDGE_TOOLS,
            allowed=[*JUDGE_TOOLS, *read_only],
            disallowed=others,
            restricted=True,
            add_dirs=[output],
        )
        agent = session_output(run_dir, Session(AGENT, session.ids, session.phase, False))
        return cmd, agent, Expect(tools=frozenset([*JUDGE_TOOLS, *read_only]))
    return tester_command(claude, config, rules, left, model, checkout), output, None


def cmd_run(args: argparse.Namespace) -> int:
    suite = parse(SCENARIOS.read_text(encoding="utf-8"))
    problems = suite_problems(suite)
    outcomes, outcome_problems = parse_outcomes(OUTCOMES.read_text(encoding="utf-8"))
    problems += outcome_problems
    if problems:
        print("\n".join(problems))
        return 2
    try:
        asked = phases_asked(args.phases, suite)
        # `--phases none` asks for no phase, so it runs the outcomes, as a run without --phases does.
        cases = outcomes_asked(args.outcomes, bool(args.phases) and args.phases.strip() != "none", outcomes)
    except ValueError as e:
        print(e)
        return 2
    sessions = plan(suite, asked, cases)
    rules = TESTER_RULES.read_text(encoding="utf-8")
    brief = AGENT_BRIEF.read_text(encoding="utf-8")
    runs = runs_root()
    if args.dry_run:
        run_dir = runs / "<stamp>"
        for session in sessions:
            print(f"=== {session.label}: {', '.join(session.ids)}{' (new stage)' if session.new_stage else ''}")
            case = outcomes.case(session.ids[0]) if session.kind in (AGENT, JUDGE) else None
            if case and session.kind == AGENT:
                print(f"(the runner prepares the stage{', runs its Given' if case.given else ''})\n{case.ask}")
            elif case:
                played = f"; the runner plays {case.play:g} s first" if case.play else ""
                print(f"(the request, these Verify lines, then the agent's calls and files{played})\n{case.verify}")
            else:
                print(prompt(suite, session, {}, run_dir, args.port))
        print("=== each session runs with CLAUDE_CODE_DISABLE_AUTO_MEMORY=1; a judge works in its agent's folder:")
        for kind, ids in (("phase", ("1.1",)), (AGENT, ("O1",)), (JUDGE, ("O1",))):
            sample = Session(kind, ids, 1, False)
            cmd, _, _ = session_command("claude", sample, Path("<config>"), run_dir, "<rules>", "<brief>")
            print(f"{kind}: {subprocess.list2cmdline(cmd)}")
        return 0
    claude = claude_executable()
    problems, kit = check(
        args.port, runs, allow_gui_port=args.allow_port_8211, any_stage=args.any_stage, any_bridge=args.any_bridge
    )
    print(describe(kit, args.port))
    if problems:
        print("\n".join(f"refused: {p}" for p in problems))
        return 1
    name = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = runs / name
    version = gate.run([claude, "--version"]).stdout.strip()
    record: dict[str, Any] = {
        "name": name,
        "started": datetime.now().isoformat(timespec="seconds"),
        **_git_facts(),
        "port": args.port,
        "kit": asdict(kit),
        "client": f"Claude Code {version}",
        "phases": args.phases or "all",
        "outcomes": ",".join(cases) or "none",
        "budget": args.budget,
    }
    (run_dir / "kit").mkdir(parents=True)
    records: list[SessionRecord] = []
    rows: list[Row] = []

    def launch(session: Session, text: str, left: float | None) -> Outcome:
        config = Path(tempfile.mkdtemp(prefix="ovmcp-scenarios-"))
        output = session_output(run_dir, session)
        output.mkdir(parents=True, exist_ok=True)
        try:
            write_config(config, args.port, output)
            cmd, cwd, expect = session_command(claude, session, config, run_dir, rules, brief, left, args.model)
            print(f"{session.label}: {', '.join(session.ids)}", flush=True)
            # A watch of its own: a silence that ended with the last session isn't this one's.
            watch = HealthWatch(health_probe(args.port))
            transcript = run_dir / f"transcript-{session.label}.jsonl"
            # A folder of the run's own as its working folder, away from test_project/ and earlier runs' verdicts.
            outcome = run_session(
                cmd, transcript, config / "plugin", watch, cwd=cwd, env=tester_env(), expect=expect, prompt=text
            )
        finally:
            shutil.rmtree(config, ignore_errors=True)
        skills = ", ".join(outcome.skills) or "none"
        print(f"  ${outcome.cost:.2f}, {outcome.seconds:.0f} s, skills {skills} {outcome.stopped}".rstrip(), flush=True)
        return outcome

    lock = lock_path(runs, args.port)
    try:
        with lock.open("x", encoding="utf-8") as f:
            f.write(f"run {name}, started {datetime.now().isoformat(timespec='seconds')}\n")
    except FileExistsError:
        print(f"refused: {lock} appeared: another run took port {args.port}")
        return 1
    began = time.monotonic()
    try:
        run_sessions(
            suite,
            sessions,
            run_dir,
            args.port,
            launch,
            lambda: settle(args.port),
            args.budget,
            records,
            rows,
            outcomes=outcomes,
            prepare=lambda case: prepare_stage(args.port, case),
            play=lambda seconds: run_play(args.port, seconds),
        )
    finally:
        # Also on an interrupt or an error: the lock goes, and the sessions that ran are written down.
        lock.unlink(missing_ok=True)
        record.update(
            finished=datetime.now().isoformat(timespec="seconds"),
            seconds=time.monotonic() - began,
            cost=sum(r.cost for r in records),
            models=sorted({r.model for r in records if r.model}),
            sessions=[asdict(r) for r in records],
            rows=[asdict(r) for r in rows],
        )
        (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        (run_dir / "results.md").write_text(results_md(record), encoding="utf-8")
    print(f"Results: {run_dir / 'results.md'}; compare with `uv run tools/scenarios.py compare`")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    runs = load_runs(runs_root())
    if not runs:
        print("no finished run under the runs folder yet")
        return 1
    newest = next((r for r in runs if r["name"] == args.run), None) if args.run else runs[-1]
    if newest is None:
        print(f"no run named {args.run}")
        return 1
    earlier = [r for r in runs if r["name"] < newest["name"]]
    try:
        against = pick_against(runs, args.against) if args.against else None
    except ValueError as e:
        print(e)
        return 1
    report = compare(newest, earlier, against)
    print(format_report(newest, report))
    return 1 if report["regressions"] or report["not_run"] else 0


def main(argv: list[str] | None = None) -> int:
    gate.utf8_streams()
    parser = argparse.ArgumentParser(description="Run the AI scenario suite in headless Claude Code testers.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "run"):
        p = sub.add_parser(name)
        p.add_argument(
            "--port", type=int, default=DEFAULT_PORT, help=f"the Kit app's bridge port, {DEFAULT_PORT} by default"
        )
        p.add_argument("--allow-port-8211", action="store_true", help="drive 8211, only when the maintainer named it")
        p.add_argument(
            "--any-stage", action="store_true", help="drive a stage the rules refuse, on the maintainer's word"
        )
        p.add_argument(
            "--any-bridge", action="store_true", help="drive a bridge whose files differ from this checkout's"
        )
    run = sub.choices["run"]
    run.add_argument("--phases", help="15, 15-16 or 18-21,24; every phase when left out; none for outcomes alone")
    run.add_argument(
        "--outcomes",
        help="all, none or O1,O3 (test_project/outcomes.md); all when --phases is left out or none, else none",
    )
    run.add_argument("--budget", type=float, help="the run's total in USD; each session gets what remains")
    run.add_argument("--model", help="the tester's model; Claude Code's default when left out")
    run.add_argument("--dry-run", action="store_true", help="print the sessions, their prompts and the command line")
    comp = sub.add_parser("compare")
    comp.add_argument("run", nargs="?", help="a run's folder name; the newest when left out")
    comp.add_argument("--against", help="a run's folder name, or a tag for the newest run at its commit")
    args = parser.parse_args(argv)
    return {"check": cmd_check, "run": cmd_run, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
