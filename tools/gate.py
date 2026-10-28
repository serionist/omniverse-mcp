"""The gate: the checks a change passes before it lands. People run it, the pre-push hook runs its quick lane.

Usage: uv run tools/gate.py quick|full [--base <ref>] [--head <ref>]
       uv run tools/gate.py text --file <path>|-

Two kinds of check:
- the working tree's: the lock file, ruff check, ruff format, basedpyright, AGENTS.md within 150 lines, each skill's
  frontmatter and its Codex link, the hooks stored as executable; full adds pytest. They run when the head is the
  checked-out commit, and are skipped, with the reason, when the tree is not what is checked;
- the commits': no tool attribution in any message, and gitleaks, on base..head (merges included).

It prints a table of the checks and exits 1 when any failed; a warning or a skip never fails it. Without gitleaks the
secret scan is skipped with a warning, unless GATE_REQUIRE_GITLEAKS=1 (as CI sets it), which makes that a failure.

The text lane checks a PR's title and description, which a squash merge makes the commit on main: no tool attribution,
as commit-msg checks a message, and a `Refs #<n>`, `Closes #<n>` or `Fixes #<n>` line. `-` reads standard input.
pr-text.yml runs it whenever they change.

Standard library only: the hooks import it from an environment uv has not synced. Before the first tool it runs
(ruff, basedpyright, pytest) it syncs the environment once from uv.lock, `uv sync --frozen`, so it never re-locks.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "origin/main"
AGENTS_MAX_LINES = 150
SKILLS_DIR = ".claude/skills"
SKILL_LINKS_DIR = ".agents/skills"
LINK_MODE = "120000"
HOOKS_DIR = ".githooks"
HOOK_MODE = "100755"
SKILL_KEYS = ("name", "description")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKILL_NAME_MAX = 64
DESCRIPTION_MAX = 1024
GITLEAKS_CONFIG = ".gitleaks.toml"
GITLEAKS_IGNORE = ".gitleaksignore"
# The git log options every scan starts with. gitleaks reads `git log -p` as git prints it, and a developer's git
# config can reshape that: colour codes leave it reading no commit, a short commit id or a missing path prefix loses
# each finding's commit or path, a textconv driver shows converted text. Options on the command line outrank every
# setting. Without --diff-merges git shows a merge commit no diff at all, so what a merge's resolution adds would
# never be scanned; against its first parent, it is.
GITLEAKS_PLAIN_LOG = (
    "--no-color --no-textconv --no-show-signature --pretty=medium --date=default --no-abbrev-commit "
    "--src-prefix=a/ --dst-prefix=b/ --text --diff-merges=first-parent"
)
OUTPUT_TAIL = 40

# Tool attribution: lines a tool adds to say it wrote a change. Nothing on `main` carries them (AGENTS.md, Commits
# and PRs). Each pattern matches the line a tool adds, so a sentence about Claude, or a person named Claude, passes.
# A line may sit behind symbols ("🤖 ", "- ", a comment character): git keeps comment lines in a message given with
# -m, so the hook reads them too.
_TOOLS = (
    r"claude|anthropic|codex|openai|chatgpt|gpt-?\d\w*|copilot|gemini|devin|aider|windsurf|cursor\s*(?:agent|ai|ide)|"
    r"cursoragent|cursor\.com"
)
_CO_AUTHOR = re.compile(r"^[^\w]*co-authored-by\s*:\s*(?P<who>.*?)\s*$", re.IGNORECASE)
_WHO = re.compile(r"^(?P<name>[^<>]*?)\s*(?:<(?P<email>[^<>]*)>)?$")
# A co-author is a tool when its address is a tool's, or its name is a tool's alone or with a model and a version
# ("Claude", "Claude Opus 4.6", "GitHub Copilot", "aider (gpt-4o)"); "Claude Martin" is a person.
_TOOL_EMAIL = re.compile(
    r"^(?:noreply@anthropic\.com|no-?reply@openai\.com|cursoragent@cursor\.com|noreply@aider\.chat"
    r"|\d+\+copilot@users\.noreply\.github\.com)$",
    re.IGNORECASE,
)
# A GitHub bot is a tool unless it is one of the bots GitHub names a co-author when a person pushes onto their PR. An
# allowlist, matched exactly: a new AI bot is refused without anyone adding it here (S5 review, round 2, F10).
_BOT_EMAIL = re.compile(r"^(?:\d+\+)?(?P<login>[^@\s\[\]]+)\[bot\]@users\.noreply\.github\.com$", re.IGNORECASE)
_NON_AI_BOTS = frozenset({"dependabot", "github-actions", "renovate"})
# The line a PR's description names its issue with; a squash merge keeps it in the commit on main (AGENTS.md, Commits
# and PRs). A bare one is the PR template's last line left unfilled.
_ISSUE_REF = re.compile(r"^[^\w]*(?:refs|closes|fixes)\s+#\d+\b", re.IGNORECASE | re.MULTILINE)
_BARE_ISSUE_REF = re.compile(r"^[^\w]*(?:refs|closes|fixes)\s+#\s*$", re.IGNORECASE | re.MULTILINE)
_TOOL_NAME = re.compile(
    r"^(?:claude(?:\s+code)?|anthropic|(?:openai\s+)?codex|chatgpt|gpt-?\d[\w.]*|(?:github\s+)?copilot"
    r"|gemini(?:\s+code\s+assist)?|cursor(?:\s+agent)?|devin(?:\s+ai)?|aider|windsurf)"
    r"(?:\s+(?:opus|sonnet|haiku|code|cli|pro|flash|ultra|nano|mini|turbo|max|agent|ai|assist|preview|latest"
    r"|thinking|v?\d[\w.]*|\([^()]*\)))*$",
    re.IGNORECASE,
)
_GENERATED = re.compile(
    rf"^[^\w]*(?:generated|created|written|authored|produced|assisted)\s+(?:with|by|using|via|in)\b.*?\b(?:{_TOOLS})\b",
    re.IGNORECASE,
)
_SESSION_LINK = re.compile(
    r"(?:https?://)?(?:www\.)?(?:claude\.ai/(?:code|chat|share)\b|chatgpt\.com/(?:codex|share|c)/)", re.IGNORECASE
)
_TOOL_TRAILER = re.compile(
    r"^[^\w]*(?:claude|anthropic|codex|openai|chatgpt|copilot|gemini|cursor)-[\w-]+\s*:", re.IGNORECASE
)
_PLAIN_YAML_BREAKERS = re.compile(r":(?:\s|$)|\s#")
_FULL_SHA = re.compile(r"\b([0-9a-f]{10})[0-9a-f]{30}\b")
_KEY_LINE = re.compile(r"^([A-Za-z][\w-]*):(?:[ \t]+(.*))?$")
_BLOCK_STYLES = (">", ">-", ">+", "|", "|-", "|+")


@dataclass
class Result:
    """One check's outcome: pass, FAIL, warn or skip, a short detail for the table, and output shown on a FAIL."""

    name: str
    status: str
    detail: str = ""
    seconds: float | None = None
    output: str = ""


@dataclass
class Scope:
    """What one run checks: the commits in its ranges, listed once, and whether the working tree is what they hold."""

    ranges: list[str]
    tree_skipped: str | None = None  # why the working tree's checks don't run; None when they do
    commits: list[tuple[str, str]] = field(default_factory=list)
    problem: str | None = None  # why the commits could not be listed
    synced: subprocess.CompletedProcess[str] | None = None  # the one `uv sync --frozen`, once a tool needs it

    @classmethod
    def of(cls, ranges: list[str], tree_skipped: str | None = None, cwd: Path = ROOT) -> Scope:
        commits, problem = list_commits(ranges, cwd)
        return cls(ranges, tree_skipped, commits, problem)


def run(cmd: list[str], cwd: Path = ROOT, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command with a fixed argument list, no shell, and capture its output as UTF-8 text."""
    return subprocess.run(  # noqa: S603 - argument lists the gate builds itself; nothing goes through a shell
        cmd, cwd=cwd, input=stdin, capture_output=True, encoding="utf-8", errors="replace", check=False
    )


def git(*args: str, cwd: Path = ROOT, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run git in cwd; the caller reads returncode, stdout and stderr."""
    exe = shutil.which("git") or "git"
    return run([exe, *args], cwd=cwd, stdin=stdin)


def utf8_streams() -> None:
    """Print UTF-8 whatever the console's code page: a tool's output may hold any character, and a Windows console
    would otherwise stop the report with UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


# Pure checks: tested in tests/test_gate.py


def tool_co_author(who: str) -> bool:
    """True when a Co-authored-by trailer's `Name <email>` is a tool, by its address or by its name."""
    match = _WHO.match(who.strip())
    if not match:
        return False
    email = (match.group("email") or "").strip()
    bot = _BOT_EMAIL.match(email)
    if bot and bot.group("login").lower() not in _NON_AI_BOTS:
        return True
    return bool(_TOOL_EMAIL.match(email)) or bool(_TOOL_NAME.match(match.group("name").strip()))


def attribution_lines(message: str) -> list[str]:
    """The lines of a commit message, PR title or body that carry tool attribution: a co-author that is a tool, a
    "Generated with" line, a tool's own trailer (`Claude-Session:`), a session link."""
    found = []
    for line in message.splitlines():
        co_author = _CO_AUTHOR.match(line)
        if (
            (co_author and tool_co_author(co_author.group("who")))
            or _GENERATED.search(line)
            or _TOOL_TRAILER.search(line)
            or _SESSION_LINK.search(line)
        ):
            found.append(line.strip())
    return found


def issue_ref_problems(text: str) -> list[str]:
    """What is wrong with how a PR's description names its issue: it needs a `Refs #<n>`, `Closes #<n>` or
    `Fixes #<n>` line."""
    if _ISSUE_REF.search(text):
        return []
    if _BARE_ISSUE_REF.search(text):
        return ["a `Refs #` or `Closes #` line has no issue number: write `Closes #<n>`, or `Refs #<n>` for one step"]
    return ["no line names the issue: end the description with `Closes #<n>`, or `Refs #<n>` for one step of it"]


def commit_problems(commits: list[tuple[str, str]]) -> list[str]:
    """One line per attribution line in each (sha, message)."""
    return [f"{sha[:10]}: {line}" for sha, message in commits for line in attribution_lines(message)]


def parse_log(output: str) -> list[tuple[str, str]]:
    """(sha, message) pairs from `git log --format=%H%x00%B%x01`."""
    commits = []
    for record in output.split("\x01"):
        sha, sep, message = record.strip("\r\n").partition("\x00")
        if sep:
            commits.append((sha.strip(), message.strip()))
    return commits


def agents_md_problems(text: str, limit: int = AGENTS_MAX_LINES) -> list[str]:
    """AGENTS.md stays within its line limit: every agent reads all of it at the start of each session."""
    lines = len(text.splitlines())
    return [f"AGENTS.md has {lines} lines; keep it within {limit}"] if lines > limit else []


def frontmatter(text: str) -> dict[str, tuple[str, bool]]:
    """The `key: value` pairs between a file's opening `---` and the next, each value with whether it is a plain
    scalar (`True`) or quoted or a block (`>-`, `|`). Block and continuation lines are joined with spaces.

    Enough YAML for a skill's frontmatter, which holds two keys; raises ValueError on anything else."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        raise ValueError("it does not start with a --- line")
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        raise ValueError("its frontmatter has no closing --- line")
    fields: dict[str, tuple[str, bool]] = {}
    key: str | None = None
    parts: list[str] = []
    plain = True

    def close() -> None:
        if key is not None:
            fields[key] = (" ".join(part for part in parts if part), plain)

    for line in lines[1:end]:
        if key is not None and (not line.strip() or line[:1] in (" ", "\t")):
            parts.append(line.strip())
            continue
        close()
        key, parts, plain = None, [], True
        if not line.strip() or line.startswith("#"):
            continue
        match = _KEY_LINE.match(line)
        if not match:
            raise ValueError(f"the line {line.strip()!r} is not `key: value`")
        key, value = match.group(1), (match.group(2) or "").strip()
        if key in fields:
            raise ValueError(f"{key} is set twice")
        if value in _BLOCK_STYLES:
            plain = False
        elif value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"{key}'s quoted value does not end with its quote on the same line")
            parts, plain = [value[1:-1]], False
        else:
            parts = [value]
    close()
    return fields


def skill_problems(folder: str, text: str) -> list[str]:
    """What is wrong with `.claude/skills/<folder>/SKILL.md` for Claude Code and Codex: the frontmatter holds only
    `name` (equal to the folder) and `description` ("Use when ...", within 1,024 characters, valid YAML)."""
    where = f"{SKILLS_DIR}/{folder}/SKILL.md"
    try:
        fields = frontmatter(text)
    except ValueError as exc:
        return [f"{where}: {exc}"]
    problems = [
        f"{where}: frontmatter key {key!r}: a skill's frontmatter holds only name and description (write-skill)"
        for key in fields
        if key not in SKILL_KEYS
    ]
    name = fields.get("name", ("", True))[0]
    if name != folder:
        problems.append(f"{where}: name is {name!r}; it must equal the folder name {folder!r}")
    if not SKILL_NAME.match(folder) or len(folder) > SKILL_NAME_MAX:
        problems.append(f"{where}: the folder name takes lowercase letters, digits and hyphens, at most 64")
    description, plain = fields.get("description", ("", True))
    if not description:
        problems.append(f"{where}: description is missing; agents pick a skill by it")
        return problems
    if not description.startswith("Use when"):
        problems.append(f'{where}: description starts with its trigger, "Use when ..."')
    if len(description) > DESCRIPTION_MAX:
        problems.append(f"{where}: description has {len(description)} characters; keep it within {DESCRIPTION_MAX}")
    if plain and _PLAIN_YAML_BREAKERS.search(description):
        problems.append(f"{where}: description: plain YAML can't hold a colon or a #: write it as a >- block")
    return problems


def link_problems(entries: list[tuple[str, str, str]], skills: set[str]) -> list[str]:
    """Each skill has one link `.agents/skills/<name>`, a symlink in git's index (mode 120000) whose target is
    `../../.claude/skills/<name>`, and each link leads to a skill. entries: (mode, path, the blob's text)."""
    problems = []
    linked = set()
    fix = "uv run tools/setup.py link"
    for mode, path, target in entries:
        name, _, inside = path[len(SKILL_LINKS_DIR) + 1 :].partition("/")
        if inside:
            if name not in linked:
                problems.append(
                    f"{SKILL_LINKS_DIR}/{name} holds files; it must be one link: delete it, then {fix} {name}"
                )
            linked.add(name)
            continue
        linked.add(name)
        if name not in skills:
            problems.append(f"{path} leads to no skill in {SKILLS_DIR}: delete it")
        elif mode != LINK_MODE:
            problems.append(f"{path} is a plain file in git (mode {mode}), not a link: {fix} {name}")
        elif target.strip() != f"../../{SKILLS_DIR}/{name}":
            problems.append(f"{path} points to {target.strip()!r}, not ../../{SKILLS_DIR}/{name}: {fix} {name}")
    problems += [
        f"{SKILL_LINKS_DIR}/{name} is missing, so Codex can't see the skill: {fix} {name}"
        for name in sorted(skills - linked)
    ]
    return problems


def hook_problems(entries: list[tuple[str, str]]) -> list[str]:
    """Each file in .githooks/ is stored as executable (mode 100755): Linux and macOS skip a hook without the bit,
    and a hook added from Windows gets 100644. entries: (mode, path)."""
    return [
        f"{path} is stored as mode {mode}, so Linux and macOS skip it: git update-index --chmod=+x {path}"
        for mode, path in entries
        if mode != HOOK_MODE
    ]


def truthy(value: str | None) -> bool:
    """True for an environment value such as 1, true or yes."""
    return (value or "").strip().lower() not in ("", "0", "false", "no", "off")


def last_line(text: str) -> str:
    """The last non-empty line of a tool's output, without pytest's ===== framing: the table's detail."""
    lines = [line.strip().strip("=").strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


# Reading the repo


def list_commits(ranges: list[str], cwd: Path = ROOT) -> tuple[list[tuple[str, str]], str | None]:
    """(sha, message) of every commit in the ranges, merges included, each once; and why they could not be listed."""
    seen: set[str] = set()
    commits = []
    for rev in ranges:
        done = git("log", "--format=%H%x00%B%x01", rev, cwd=cwd)
        if done.returncode != 0:
            reason = (done.stderr.strip().splitlines() or ["git log failed"])[0]
            return [], f"can't list {rev} ({reason}): git fetch origin, then run it again"
        for sha, message in parse_log(done.stdout):
            if sha not in seen:
                seen.add(sha)
                commits.append((sha, message))
    return commits, None


def skill_folders(root: Path = ROOT) -> dict[str, Path]:
    """Each folder under .claude/skills that holds a SKILL.md, by name."""
    return {path.parent.name: path for path in sorted((root / SKILLS_DIR).glob("*/SKILL.md"))}


def index_entries(pathspec: str) -> list[tuple[str, str, str]]:
    """(mode, blob sha, path) of each entry in git's index under pathspec."""
    listed = git("ls-files", "-s", "--", pathspec)
    if listed.returncode != 0:
        raise OSError(listed.stderr.strip() or f"git ls-files failed for {pathspec}")
    entries = []
    for line in listed.stdout.splitlines():
        meta, _, path = line.partition("\t")
        mode, sha = meta.split()[:2]
        entries.append((mode, sha, path))
    return entries


# The working tree's checks


def check_lock(_scope: Scope) -> Result:
    uv = shutil.which("uv")
    if not uv:
        return Result("lock", "FAIL", "uv not found: https://docs.astral.sh/uv/")
    done = run([uv, "lock", "--check"])
    output = (done.stdout + done.stderr).strip()
    return Result("lock", "pass" if done.returncode == 0 else "FAIL", last_line(output), output=output)


def tool(name: str, args: list[str]) -> Callable[[Scope], Result]:
    """A check that runs a dev tool from the environment uv.lock describes, synced once per run."""

    def check(scope: Scope) -> Result:
        uv = shutil.which("uv")
        if not uv:
            return Result(name, "FAIL", "uv not found: https://docs.astral.sh/uv/")
        if scope.synced is None:
            scope.synced = run([uv, "sync", "--frozen", "--quiet"])
        if scope.synced.returncode != 0:
            output = (scope.synced.stdout + scope.synced.stderr).strip()
            return Result(name, "FAIL", "uv sync --frozen failed", output=output)
        done = run([uv, "run", "--no-sync", "--quiet", *args])
        output = (done.stdout + done.stderr).strip()
        return Result(name, "pass" if done.returncode == 0 else "FAIL", last_line(output), output=output)

    return check


def check_agents_md(_scope: Scope) -> Result:
    path = ROOT / "AGENTS.md"
    if not path.is_file():
        return Result("AGENTS.md", "FAIL", "AGENTS.md is missing")
    text = path.read_text(encoding="utf-8")
    problems = agents_md_problems(text)
    detail = f"{len(text.splitlines())} lines"
    return Result("AGENTS.md", "FAIL" if problems else "pass", problems[0] if problems else detail)


def check_skills(_scope: Scope) -> Result:
    skills = skill_folders()
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8") if (ROOT / "AGENTS.md").is_file() else ""
    problems = []
    for name, path in skills.items():
        problems += skill_problems(name, path.read_text(encoding="utf-8"))
        if f"`{name}`" not in agents:
            problems.append(f"AGENTS.md does not name the skill `{name}` (write-skill)")
    return outcome("skills", problems, f"{len(skills)} skills")


def check_skill_links(_scope: Scope) -> Result:
    """Read from git's index, not the disk: where git makes no symlinks (Windows without Developer Mode) a link is a
    plain file holding its target, and only the index says it is a link."""
    entries = [
        (mode, path, git("cat-file", "blob", sha).stdout if mode == LINK_MODE else "")
        for mode, sha, path in index_entries(SKILL_LINKS_DIR)
    ]
    links = sum(1 for _, path, _ in entries if "/" not in path[len(SKILL_LINKS_DIR) + 1 :])
    return outcome("skill links", link_problems(entries, set(skill_folders())), f"{links} links")


def check_hooks(_scope: Scope) -> Result:
    entries = [(mode, path) for mode, _, path in index_entries(HOOKS_DIR)]
    if not entries:
        return Result("hooks", "FAIL", f"nothing in {HOOKS_DIR} is in git's index")
    return outcome("hooks", hook_problems(entries), f"{len(entries)} executable")


# The commits' checks


def check_attribution(scope: Scope) -> Result:
    if scope.problem:
        return Result("attribution", "FAIL", scope.problem)
    found = commit_problems(scope.commits)
    if found:
        return Result(
            "attribution",
            "FAIL",
            f"tool attribution in {len(found)} line(s)",
            output="\n".join(found) + "\nReword each commit without it (git rebase -i, reword).",
        )
    return Result("attribution", "pass", f"{len(scope.commits)} commits")


def check_gitleaks(scope: Scope) -> Result:
    exe = shutil.which("gitleaks")
    if not exe:
        if truthy(os.environ.get("GATE_REQUIRE_GITLEAKS")):
            return Result("gitleaks", "FAIL", "not installed, and GATE_REQUIRE_GITLEAKS=1 requires it")
        return Result("gitleaks", "warn", "not installed, so not scanned; https://github.com/gitleaks/gitleaks")
    if (ROOT / GITLEAKS_IGNORE).exists():
        return Result(
            "gitleaks",
            "FAIL",
            f"{GITLEAKS_IGNORE} skips findings without a reason",
            output=f"Delete {GITLEAKS_IGNORE}; allow each exception in {GITLEAKS_CONFIG} with its reason.",
        )
    if scope.problem:
        return Result("gitleaks", "FAIL", scope.problem)
    if not scope.commits:
        return Result("gitleaks", "pass", "no commits to scan")
    for rev in scope.ranges:
        cmd = [exe, "git", "--config", str(ROOT / GITLEAKS_CONFIG), "--log-opts", f"{GITLEAKS_PLAIN_LOG} {rev}"]
        cmd += ["--redact", "--no-banner", "--ignore-gitleaks-allow", "--exit-code", "1", "-v", str(ROOT)]
        done = run(cmd)
        if done.returncode != 0:
            output = (done.stdout + done.stderr).strip()
            return Result("gitleaks", "FAIL", f"secrets found in {rev}, or the scan failed", output=output)
    return Result("gitleaks", "pass", f"{len(scope.commits)} commits")


def outcome(name: str, problems: list[str], detail: str) -> Result:
    if problems:
        return Result(
            name, "FAIL", problems[0] if len(problems) == 1 else f"{len(problems)} problems", output="\n".join(problems)
        )
    return Result(name, "pass", detail)


Check = Callable[[Scope], Result]
TREE: list[tuple[str, Check]] = [
    ("lock", check_lock),
    ("ruff check", tool("ruff check", ["ruff", "check", "."])),
    ("ruff format", tool("ruff format", ["ruff", "format", "--check", "."])),
    ("basedpyright", tool("basedpyright", ["basedpyright"])),
    ("AGENTS.md", check_agents_md),
    ("skills", check_skills),
    ("skill links", check_skill_links),
    ("hooks", check_hooks),
]
COMMITS: list[tuple[str, Check]] = [("attribution", check_attribution), ("gitleaks", check_gitleaks)]
FULL_ONLY: list[tuple[str, Check]] = [("pytest", tool("pytest", ["pytest", "-q"]))]


def lane_checks(lane: str) -> list[tuple[str, Check, bool]]:
    """(name, check, whether it reads the working tree) for each check of the lane, in the order they run."""
    checks = [(name, check, True) for name, check in TREE] + [(name, check, False) for name, check in COMMITS]
    if lane == "full":
        checks += [(name, check, True) for name, check in FULL_ONLY]
    return checks


# Output


def say(text: str = "") -> None:
    print(text, flush=True)


def row(name: str, status: str, seconds: str, detail: str, width: int) -> str:
    return f"  {name:<{width}}  {status:<6}  {seconds:>6}  {detail}".rstrip()


def run_lane(lane: str, scope: Scope) -> int:
    """Run the lane's checks on the scope, print the table, and return the exit code: 1 when any failed."""
    checks = lane_checks(lane)
    width = max(len(name) for name, _, _ in checks)
    ranges = _FULL_SHA.sub(r"\1", ", ".join(scope.ranges)) or "(none)"
    say(f"gate {lane}, commits {ranges}")
    if scope.tree_skipped:
        say(f"the working tree's checks are skipped: {scope.tree_skipped}")
    say()
    say(row("check", "result", "time", "detail", width))
    results = []
    for name, check, reads_tree in checks:
        if reads_tree and scope.tree_skipped:
            result = Result(name, "skip", "the working tree is not what is checked")
        else:
            started = time.monotonic()
            try:
                result = check(scope)
            except (OSError, ValueError) as exc:
                result = Result(name, "FAIL", f"{type(exc).__name__}: {exc}")
            result.seconds = time.monotonic() - started
        results.append(result)
        seconds = "" if result.seconds is None else f"{result.seconds:.1f}s"
        say(row(name, result.status, seconds, result.detail, width))
    failed = [result for result in results if result.status == "FAIL"]
    for result in failed:
        if result.output:
            say()
            say(f"--- {result.name} ---")
            say("\n".join(result.output.splitlines()[-OUTPUT_TAIL:]))
    warned = sum(1 for result in results if result.status == "warn")
    skipped = sum(1 for result in results if result.status == "skip")
    extra = (f", {warned} warning(s)" if warned else "") + (f", {skipped} skipped" if skipped else "")
    say()
    if failed:
        say(f"gate {lane} FAILED: {', '.join(result.name for result in failed)}")
        return 1
    say(f"gate {lane} passed: {len(results) - warned - skipped} checks{extra}")
    return 0


def read_text(file: str) -> str:
    """The text in file, or on standard input for `-`, read as UTF-8 whatever the console's code page."""
    if file == "-":
        return sys.stdin.buffer.read().decode("utf-8", errors="replace")
    return Path(file).read_text(encoding="utf-8", errors="replace")


def report_attribution(text: str, who: str, hint: str, more: list[str] | None = None) -> int:
    """The commit-msg hook's check and the text lane's. On stderr, `<who>: refused: ...` for each line of text that
    carries tool attribution and each of the caller's other problems, then the hint; 1 when there is any."""
    problems = [f"tool attribution: {line}" for line in attribution_lines(text)] + (more or [])
    for problem in problems:
        print(f"{who}: refused: {problem}", file=sys.stderr, flush=True)
    if problems:
        print(f"{who}: {hint}", file=sys.stderr, flush=True)
    return 1 if problems else 0


def text_lane(text: str) -> int:
    """The text lane: 1 when a PR's title and description carry tool attribution or name no issue."""
    hint = "fix the PR's title and description (AGENTS.md, Commits and PRs)"
    if report_attribution(text, "gate text", hint, issue_ref_problems(text)):
        say("gate text FAILED")
        return 1
    say(f"gate text passed: no tool attribution in {len(text.splitlines())} lines, and the issue is named")
    return 0


def cli_scope(base: str, head: str) -> Scope:
    """base..head; the working tree's checks run when head is the checked-out commit."""
    head_sha = git("rev-parse", "--verify", "--quiet", f"{head}^{{commit}}").stdout.strip()
    checked_out = git("rev-parse", "--verify", "--quiet", "HEAD^{commit}").stdout.strip()
    skipped = None if head_sha and head_sha == checked_out else f"{head} is not the checked-out commit"
    return Scope.of([f"{base}..{head}"], skipped)


def main(argv: list[str] | None = None) -> int:
    utf8_streams()
    parser = argparse.ArgumentParser(description="The checks a change passes before it lands.")
    parser.add_argument("lane", choices=["quick", "full", "text"])
    parser.add_argument("--base", help=f"quick and full: the commits checked start after this ref (default {BASE})")
    parser.add_argument("--head", help="quick and full: and end at this one (default HEAD)")
    parser.add_argument("--file", help="text: the file to check, or - for standard input")
    args = parser.parse_args(argv)
    # A flag the lane doesn't read is refused, so a mistyped command never passes having checked something else.
    if args.lane == "text":
        if args.base is not None or args.head is not None:
            parser.error("text checks one text: --base and --head are for quick and full")
        if args.file is None:
            parser.error("text needs --file <path>, or --file - to read standard input")
        return text_lane(read_text(args.file))
    if args.file is not None:
        parser.error(f"{args.lane} checks the branch, not a file: --file is for text")
    return run_lane(args.lane, cli_scope(args.base or BASE, args.head or "HEAD"))


if __name__ == "__main__":
    sys.exit(main())
