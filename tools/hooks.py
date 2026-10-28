"""The git hooks behind the `.githooks/` shims, which `uv run tools/setup.py` turns on.

Usage (from a shim): uv run --no-sync tools/hooks.py commit-msg|pre-push|post-checkout|post-merge [git's arguments]

- commit-msg refuses a message with tool attribution: a co-author that is a tool, a "Generated with" line, a tool's
  session trailer or link (AGENTS.md, Commits and PRs).
- pre-push runs the gate's quick lane on what the push sends: the commits' checks on each pushed range, and the
  working tree's checks only when the push sends HEAD and the tree has nothing else in it.
- post-checkout and post-merge name the AI setup files that changed, so an agent re-reads them. They only inform:
  git makes post-checkout's exit status the checkout's.

Standard library only: in a new worktree the shims' `uv run --no-sync` environment is empty.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import gate

# The line above the diff `git commit -v` adds, behind whatever comment character is set; git drops it and all
# below it. Everything above, comment lines included, is the message: with -m git keeps comment lines.
SCISSORS = re.compile(r"^\S+ -{24} >8 -{24}\s*$")
ZERO_SHA = re.compile(r"^0+$")
# What an agent reads as its rules when a session starts (REVIEW.md, The harness).
AGENT_SETUP_PREFIXES = (".claude/", ".agents/")
AGENT_SETUP_FILES = frozenset({"REVIEW.md", ".mcp.json"})
AGENT_SETUP_NAMES = frozenset({"AGENTS.md", "CLAUDE.md"})


def say(hook: str, text: str) -> None:
    print(f"{hook}: {text}", file=sys.stderr)


def message_text(raw: str) -> str:
    """The message git may record: everything above the scissors line, comment lines included."""
    kept = []
    for line in raw.splitlines():
        if SCISSORS.match(line):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def commit_msg(path: str) -> int:
    """Refuse a message with tool attribution; 1 refuses the commit."""
    found = gate.attribution_lines(message_text(Path(path).read_text(encoding="utf-8", errors="replace")))
    for line in found:
        say("commit-msg", f"refused: tool attribution: {line}")
    if found:
        say("commit-msg", "take those lines out and commit again (AGENTS.md, Commits and PRs)")
        return 1
    return 0


def push_ranges(lines: list[str], base: str, known: Callable[[str], bool]) -> list[tuple[str, str]]:
    """(range, local sha) for each ref a push updates, from the lines git gives pre-push on stdin:
    `<local ref> <local sha> <remote ref> <remote sha>`. A deletion sends nothing and is left out. A new branch, or a
    remote commit this clone never fetched, is compared with base."""
    pushed = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4 or ZERO_SHA.match(parts[1]):
            continue
        local, remote = parts[1], parts[3]
        since = remote if not ZERO_SHA.match(remote) and known(remote) else base
        pushed.append((f"{since}..{local}", local))
    return pushed


def tree_skip_reason(pushed: list[str], head: str, dirty: bool) -> str | None:
    """Why the working tree can't stand for what a push sends, or None when it can: every pushed commit is HEAD, and
    nothing is changed or untracked. pushed and head are commit ids."""
    other = [sha for sha in pushed if sha != head]
    if other:
        return f"the push sends {other[0][:10]}, not HEAD"
    if dirty:
        return "it has changes or untracked files that are not pushed"
    return None


def pre_push(lines: list[str]) -> int:
    """The gate's quick lane on what the push sends."""

    def known(sha: str) -> bool:
        return gate.git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0

    pushed = push_ranges(lines, gate.BASE, known)
    if not pushed:
        say("pre-push", "the push only deletes, so there is nothing to check")
        return 0
    commits = [gate.git("rev-parse", f"{sha}^{{commit}}").stdout.strip() for _, sha in pushed]
    head = gate.git("rev-parse", "HEAD").stdout.strip()
    dirty = bool(gate.git("status", "--porcelain").stdout.strip())
    scope = gate.Scope.of([rev for rev, _ in pushed], tree_skip_reason(commits, head, dirty))
    if scope.tree_skipped:
        scope.tree_skipped += "; run uv run tools/gate.py quick on the pushed commit to check it"
    return gate.run_lane("quick", scope)


def is_agent_setup(path: str) -> bool:
    """True for an agent's rules: AGENTS.md and CLAUDE.md anywhere, REVIEW.md, .claude/, .agents/, .mcp.json."""
    shown = path.replace("\\", "/").removeprefix("./")
    return (
        shown.startswith(AGENT_SETUP_PREFIXES)
        or shown in AGENT_SETUP_FILES
        or PurePosixPath(shown).name in AGENT_SETUP_NAMES
    )


def setup_changed(hook: str, *revs: str) -> int:
    """Name the AI setup files that differ between revs: an agent read the old ones when its session started."""
    names = gate.git("diff", "--name-only", *revs).stdout.splitlines()
    changed = [name for name in names if is_agent_setup(name)]
    if changed:
        say(hook, "the AI setup changed; an agent re-reads those it already read, or starts a new session:")
        for name in changed:
            say(hook, f"  {name}")
    return 0


def rebasing() -> bool:
    """True while a rebase runs: its checkout goes from the branch's tip to the commit it rebases onto."""
    for name in ("rebase-merge", "rebase-apply"):
        if Path(gate.git("rev-parse", "--git-path", name).stdout.strip()).exists():
            return True
    return False


def post_checkout(old: str = "", new: str = "", branch: str = "0") -> int:
    """After a branch switch. A file checkout, the same commit and a new worktree (old is the null id) say nothing."""
    if branch != "1" or old == new or not old.strip("0"):
        return 0
    # A rebase compares only what the new base changed, not the branch's own commits it is about to replay.
    return setup_changed("post-checkout", *([f"{old}...{new}"] if rebasing() else [old, new]))


def post_merge() -> int:
    """After a merge or a pull: ORIG_HEAD is the commit before it."""
    old = gate.git("rev-parse", "-q", "--verify", "ORIG_HEAD").stdout.strip()
    return setup_changed("post-merge", old, "HEAD") if old else 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    gate.utf8_streams()
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    hook, rest = args[0], args[1:]
    if hook == "commit-msg" and rest:
        return commit_msg(rest[0])
    if hook == "pre-push":
        return pre_push(sys.stdin.read().splitlines())
    if hook == "post-checkout":
        return post_checkout(*rest[:3])
    if hook == "post-merge":
        return post_merge()
    print(f"unknown hook or missing argument: {' '.join(args)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
