"""The AI scenario suite's runs (#102, docs/plans/2026-11-01-scenario-skill.md): check the Kit app a run would drive,
run test_project/scenarios.md's phases, each in a headless Claude Code tester of its own, and compare a run's rows
with earlier runs'. The run-scenarios skill calls it.

    uv run tools/scenarios.py check [--port N]
    uv run tools/scenarios.py run [--phases 15,18-21] [--port N] [--budget USD] [--model M] [--dry-run]
    uv run tools/scenarios.py compare [RUN] [--against RUN_OR_TAG]

Unlike the gate, it imports the server's client, so it needs `uv sync` (write-skill, step 5).
"""

from __future__ import annotations

import argparse
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
PLUGIN_NAME = "omniverse-mcp"
# The /health watch (#54): probes as conftest's, and a stop only after a silence longer than the server's 120 s call
# limit plus one probe, counted from the first probe that got no answer, since a long handler holds /health back too.
PROBE_SECONDS = 20.0
PROBE_EVERY = 30.0
SILENCE_LIMIT = 140.0
SESSION_SECONDS = 45 * 60  # a session's limit; the plan sets it again from the first full run's times

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


# ----- which sessions a run holds -----


@dataclass(frozen=True)
class Session:
    kind: str  # "phase", or "setup": the needed scenarios a later phase in the run uses
    ids: tuple[str, ...]
    phase: int  # the phase it runs, or for setup the phase it comes before
    new_stage: bool  # the first session of a half: new_scene() first

    @property
    def label(self) -> str:
        return f"{self.kind}-{self.phase:02d}"


def phases_asked(value: str | None, suite: Suite) -> set[int]:
    """`15`, `15-16` or `18-21,24`; every phase when empty."""
    known = {p.number for p in suite.phases}
    if not value:
        return known
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


def plan(suite: Suite, asked: Iterable[int]) -> list[Session]:
    """The run's sessions: each half asked starts on a new stage; in it the needed scenarios the run lacks and the
    asked phases go in ID order, each group of needed ones just before the first asked phase after them; the cleanup
    phase ends the run."""
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
    text: str,
    config: Path,
    rules: str,
    budget_left: float | None = None,
    model: str | None = None,
    checkout: Path = ROOT,
) -> list[str]:
    """The tester's command line, as step 2 found it works: only the run's server, no settings source, the tester's
    rules appended, no shell, web or writes, every omniverse tool and the plugin's skills allowed, the rest refused."""
    skills = [f"Skill({PLUGIN_NAME}:{name})" for name in skill_names(checkout)]
    cmd = [
        claude,
        "-p",
        text,
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
        ",".join(BUILTIN_TOOLS),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        f"mcp__{SERVER}",
        "Read",
        "Grep",
        "Glob",
        *skills,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if budget_left is not None:
        cmd += ["--max-budget-usd", f"{budget_left:.2f}"]
    if model:
        cmd += ["--model", model]
    return cmd


def tester_env() -> dict[str, str]:
    """The tester's environment: the maintainer's auto-memory stays out (step 2, S4)."""
    return {**os.environ, "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}


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
    except (OSError, BridgeError) as e:
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


def init_problems(event: Mapping[str, Any], plugin_dir: Path) -> list[str]:
    """What the session's first event shows that a tester must not have: a server other than the run's, the run's
    not connected, a tool outside the command's list, a plugin other than the run's copy and Claude Code's built-in
    ones, or a memory path."""
    problems = []
    servers = list(event.get("mcp_servers") or [])
    names = [str(s.get("name")) for s in servers]
    if names != [SERVER]:
        problems.append(f"MCP servers {names}, where only {SERVER!r} may run")
    elif servers[0].get("status") != "connected":
        problems.append(f"the {SERVER!r} server is {servers[0].get('status')!r}, not connected")
    tools = [str(t) for t in event.get("tools") or []]
    foreign = [t for t in tools if t not in BUILTIN_TOOLS and not t.startswith(f"mcp__{SERVER}__")]
    if foreign:
        problems.append(f"tools outside the run's list: {', '.join(foreign)}")
    ours = os.path.normcase(plugin_dir.resolve())
    for plugin in event.get("plugins") or []:
        path = str(plugin.get("path", ""))
        if path != "builtin" and os.path.normcase(Path(path).resolve()) != ours:
            problems.append(f"a plugin other than the run's: {plugin.get('name')} from {path}")
    if event.get("memory_paths"):
        problems.append(f"a memory path: {event.get('memory_paths')}")
    return problems


@dataclass
class Outcome:
    exit: int | None = None
    text: str = ""  # the tester's last message
    cost: float = 0.0
    turns: int | None = None
    model: str = ""
    skills: list[str] = field(default_factory=list)
    stopped: str = ""  # why the script ended the session, if it did
    kit_hung: bool = False
    seconds: float = 0.0
    in_flight: dict[str, str] = field(default_factory=dict)  # the tool calls sent and not yet answered, by id


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
) -> Outcome:
    """Run one tester, keep its stream in the transcript, and read what it did: its model, skill loads, cost and last
    message. Stop it at once on a bad init event, after `limit` seconds, or when the watch says Kit hangs."""
    outcome = Outcome()
    started = clock()
    proc = subprocess.Popen(  # noqa: S603 - an argument list the script builds itself; nothing goes through a shell
        list(cmd),
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        start_new_session=os.name != "nt",
    )
    lines: queue.Queue[str | None] = queue.Queue()

    def pump() -> None:
        if proc.stdout is not None:
            with proc.stdout:
                for line in proc.stdout:
                    lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    last_text = ""
    exited_at: float | None = None
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
                last_text = _read_event(line, outcome, plugin_dir) or last_text
            reason = ""
            if outcome.stopped:
                reason = outcome.stopped
            elif clock() - started > limit:
                reason = outcome.stopped = f"stopped at the session's limit, {limit:.0f} s"
            elif watch is not None and (hung := watch.check()):
                calls = sorted({f"`{n.removeprefix(f'mcp__{SERVER}__')}`" for n in outcome.in_flight.values()})
                held = f", while {', '.join(calls)} ran" if calls else ""
                reason = outcome.stopped = f"{hung}{held}: a script holding Kit's main thread, or a hang inside Kit"
                outcome.kit_hung = True
            if reason and proc.poll() is None:
                end_tree(proc)
    outcome.exit = proc.wait()
    outcome.text = outcome.text or last_text
    outcome.seconds = clock() - started
    return outcome


def _read_event(line: str, outcome: Outcome, plugin_dir: Path) -> str:
    """Note what one stream event says in the outcome; the assistant's text, if it holds some."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return ""
    kind = event.get("type")
    if kind == "system" and event.get("subtype") == "init":
        outcome.model = str(event.get("model", ""))
        problems = init_problems(event, plugin_dir)
        if problems:
            outcome.stopped = "the session's init event: " + "; ".join(problems)
    elif kind == "assistant":
        texts = []
        for part in (event.get("message") or {}).get("content") or []:
            if part.get("type") == "tool_use":
                outcome.in_flight[str(part.get("id", ""))] = str(part.get("name", ""))
                if part.get("name") == "Skill":
                    outcome.skills.append(str((part.get("input") or {}).get("skill", "")))
            elif part.get("type") == "text":
                texts.append(str(part.get("text", "")))
        return "\n".join(texts)
    elif kind == "user":
        content = (event.get("message") or {}).get("content")
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and part.get("type") == "tool_result":
                outcome.in_flight.pop(str(part.get("tool_use_id", "")), None)
    elif kind == "result":
        outcome.cost = float(event.get("total_cost_usd") or 0.0)
        outcome.turns = event.get("num_turns")
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
    exit: int | None = None
    cost: float = 0.0
    turns: int | None = None
    model: str = ""
    seconds: float = 0.0
    skills: list[str] = field(default_factory=list)
    stopped: str = ""


Launch = Callable[[Session, str, float | None], Outcome]


def run_sessions(
    suite: Suite,
    sessions: Sequence[Session],
    run_dir: Path,
    port: int,
    launch: Launch,
    settle: Callable[[], None],
    budget: float | None = None,
) -> tuple[list[SessionRecord], list[Row]]:
    """Run the sessions in order, each told its needed scenarios' status so far; stop starting them once Kit hangs or
    the budget is spent. Each session's last message becomes its phase file, and its table its rows."""
    statuses: dict[str, str] = {}
    records: list[SessionRecord] = []
    rows: list[Row] = []
    spent = 0.0
    halt = ""
    for session in sessions:
        record = SessionRecord(session.label, session.kind, session.phase, list(session.ids), session.new_stage)
        records.append(record)
        left = None if budget is None else budget - spent
        if not halt and left is not None and left <= 0:
            halt = f"the budget of ${budget:.2f} is spent"
        if not halt:
            try:
                settle()
            except (OSError, BridgeError) as e:
                halt = f"Kit didn't answer between sessions: {e}"
        if halt:
            record.stopped = f"not run: {halt}"
            found: dict[str, Row] = {}
        else:
            outcome = launch(session, prompt(suite, session, statuses, run_dir, port), left)
            spent += outcome.cost
            record.exit, record.cost, record.turns = outcome.exit, outcome.cost, outcome.turns
            record.model, record.seconds, record.skills = outcome.model, outcome.seconds, outcome.skills
            record.stopped = outcome.stopped
            if outcome.kit_hung:
                halt = outcome.stopped
            heading = f"# {session.label}: {', '.join(session.ids)}"
            (run_dir / f"{session.label}.md").write_text(f"{heading}\n\n{outcome.text}\n", encoding="utf-8")
            found = rows_from(outcome.text, session.ids)
        for sid in session.ids:
            scenario = suite.scenario(sid)
            row = found.get(sid) or Row(
                sid, scenario.title if scenario else "", NOT_RUN, record.stopped or "no row came"
            )
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
        ("Took", f"{record.get('seconds', 0) / 60:.0f} min, ${record.get('cost', 0):.2f}"),
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
    issues = [r for r in rows if r["status"] in ("FAIL", "WARN", NOT_RUN)]
    out += ["", "## Issues", ""]
    out += [f"- **{r['status']} {r['id']}** {r['test']}: {r['notes']}" for r in issues] or ["None."]
    return "\n".join(out) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _id_key(sid: str) -> tuple[int, int]:
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
    ran = [s for s in newest.get("sessions") or [] if not str(s.get("stopped", "")).startswith("not run")]
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


def claude_executable() -> str:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("Claude Code (`claude`) isn't on PATH: the tester is a headless Claude Code session")
    if os.name == "nt" and Path(claude).suffix.lower() in (".cmd", ".bat"):
        # cmd.exe would read the prompts' | and < as its own; the native install is an .exe.
        raise SystemExit(f"{claude} is a cmd.exe shim: install Claude Code's native build, claude.exe")
    return claude


def cmd_run(args: argparse.Namespace) -> int:
    suite = parse(SCENARIOS.read_text(encoding="utf-8"))
    problems = suite_problems(suite)
    if problems:
        print("\n".join(problems))
        return 2
    try:
        asked = phases_asked(args.phases, suite)
    except ValueError as e:
        print(e)
        return 2
    sessions = plan(suite, asked)
    rules = TESTER_RULES.read_text(encoding="utf-8")
    runs = runs_root()
    if args.dry_run:
        run_dir = runs / "<stamp>"
        for session in sessions:
            print(f"=== {session.label}: {', '.join(session.ids)}{' (new stage)' if session.new_stage else ''}")
            print(prompt(suite, session, {}, run_dir, args.port))
        cmd = tester_command(
            "claude", "<prompt>", Path("<config>"), "<test_project/AGENTS.md>", args.budget, args.model
        )
        print("=== each session runs, with CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 and in test_project/:")
        print(subprocess.list2cmdline(cmd))
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
    (run_dir / "kit").mkdir(parents=True)
    (run_dir / "mcp_output").mkdir()
    lock = lock_path(runs, args.port)
    try:
        with lock.open("x", encoding="utf-8") as f:
            f.write(f"run {name}, started {datetime.now().isoformat(timespec='seconds')}\n")
    except FileExistsError:
        print(f"refused: {lock} appeared: another run took port {args.port}")
        return 1
    version = gate.run([claude, "--version"]).stdout.strip()
    record: dict[str, Any] = {
        "name": name,
        "started": datetime.now().isoformat(timespec="seconds"),
        **_git_facts(),
        "port": args.port,
        "kit": asdict(kit),
        "client": f"Claude Code {version}",
        "phases": args.phases or "all",
        "budget": args.budget,
    }
    began = time.monotonic()
    watch = HealthWatch(health_probe(args.port))

    def settle() -> None:
        """Stop the timeline and any recording a stopped session left running."""
        client = connect(args.port)
        try:
            answer(client.sim_control("stop"))
            if answer(client.sim_state()).get("recording_active"):
                answer(client.recording_stop())
        finally:
            client.close()

    def launch(session: Session, text: str, left: float | None) -> Outcome:
        config = Path(tempfile.mkdtemp(prefix="ovmcp-scenarios-"))
        try:
            write_config(config, args.port, session_output(run_dir, session))
            cmd = tester_command(claude, text, config, rules, left, args.model)
            print(f"{session.label}: {', '.join(session.ids)}", flush=True)
            outcome = run_session(
                cmd, run_dir / f"transcript-{session.label}.jsonl", config / "plugin", watch, env=tester_env()
            )
        finally:
            shutil.rmtree(config, ignore_errors=True)
        skills = ", ".join(outcome.skills) or "none"
        print(f"  ${outcome.cost:.2f}, {outcome.seconds:.0f} s, skills {skills} {outcome.stopped}".rstrip(), flush=True)
        return outcome

    try:
        records, rows = run_sessions(suite, sessions, run_dir, args.port, launch, settle, args.budget)
    finally:
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
    run.add_argument("--phases", help="15, 15-16 or 18-21,24; every phase when left out")
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
