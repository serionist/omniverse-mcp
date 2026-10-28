"""The git hooks behind the `.githooks/` shims, which `uv run tools/setup.py` turns on.

Usage (from a shim): uv run --no-sync tools/hooks.py commit-msg|pre-push|post-checkout|post-merge [git's arguments]

- commit-msg refuses a message with tool attribution: an AI co-author trailer, a "Generated with" line, a tool's
  session trailer or link (AGENTS.md, Commits and PRs).
- pre-push runs the gate's quick lane.
- post-checkout and post-merge name the AI setup files that changed, so an agent re-reads them. They only inform:
  git makes post-checkout's exit status the checkout's.

Standard library only: in a new worktree the shims' `uv run --no-sync` environment is empty.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import gate

SCISSORS = "------------------------ >8 ------------------------"
# What an agent reads as its rules when a session starts (REVIEW.md, The harness).
AGENT_SETUP_PREFIXES = (".claude/", ".agents/")
AGENT_SETUP_FILES = frozenset({"REVIEW.md", ".mcp.json"})
AGENT_SETUP_NAMES = frozenset({"AGENTS.md", "CLAUDE.md"})


def say(hook: str, text: str) -> None:
    print(f"{hook}: {text}", file=sys.stderr)


def comment_char() -> str:
    """git's comment character, which starts the lines it drops from a message."""
    char = gate.git("config", "core.commentChar").stdout.strip()
    return char if len(char) == 1 else "#"


def message_text(raw: str, char: str = "#") -> str:
    """The message as git records it: without comment lines and without the diff `git commit -v` adds below the
    scissors line."""
    kept = []
    for line in raw.splitlines():
        if line.startswith(char) and line[1:].strip() == SCISSORS:
            break
        if not line.startswith(char):
            kept.append(line)
    return "\n".join(kept).strip()


def commit_msg(path: str, char: str | None = None) -> int:
    """Refuse a message with tool attribution; 1 refuses the commit."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    found = gate.attribution_lines(message_text(raw, char or comment_char()))
    for line in found:
        say("commit-msg", f"refused: tool attribution: {line}")
    if found:
        say("commit-msg", "take those lines out and commit again (AGENTS.md, Commits and PRs)")
        return 1
    return 0


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
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    hook, rest = args[0], args[1:]
    if hook == "commit-msg" and rest:
        return commit_msg(rest[0])
    if hook == "pre-push":
        return gate.main(["quick"])
    if hook == "post-checkout":
        return post_checkout(*rest[:3])
    if hook == "post-merge":
        return post_merge()
    print(f"unknown hook or missing argument: {' '.join(args)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
