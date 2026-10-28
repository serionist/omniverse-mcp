"""Set up a clone once, and link skills for Codex. Safe to run again.

Usage:
  uv run tools/setup.py                 turn on the hooks, make `git blame` skip reformats, check out the skill
                                        links as symlinks where this machine can make them, and check the tools
  uv run tools/setup.py link [skill]    write .agents/skills/<skill> into git's index as a link to
                                        .claude/skills/<skill>; every skill when none is named

Every setting is this repo's own (`git config --local`), shared by its worktrees; nothing global changes.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import gate
from gate import LINK_MODE, ROOT, SKILL_LINKS_DIR, SKILLS_DIR

CONFIG = (
    ("core.hooksPath", ".githooks", "the hooks in .githooks/: commit-msg, pre-push, post-checkout, post-merge"),
    ("blame.ignoreRevsFile", ".git-blame-ignore-revs", "git blame skips the reformat commits listed there"),
)
TOOLS = (
    ("uv", True, "runs the hooks and the gate: https://docs.astral.sh/uv/getting-started/installation/"),
    ("gitleaks", False, "the gate's secret scan, skipped without it: https://github.com/gitleaks/gitleaks"),
    ("gh", False, "the skills' issues and PRs: https://cli.github.com, then gh auth login"),
)


def set_config(root: Path, key: str, value: str) -> str:
    """Set a value in this repo's git config; say whether it changed."""
    if gate.git("config", "--local", "--get", key, cwd=root).stdout.strip() == value:
        return f"{key}={value} (already set)"
    done = gate.git("config", "--local", key, value, cwd=root)
    if done.returncode != 0:
        return f"TO DO: git config --local {key} {value} failed: {done.stderr.strip()}"
    return f"{key}={value} (set)"


def make_hooks_executable(root: Path) -> list[str]:
    """On Linux and macOS git skips a hook without the executable bit; git stores them as 100755, but a copy or an
    unzip may drop it."""
    if os.name == "nt":
        return []
    done = []
    for hook in sorted((root / ".githooks").glob("*")):
        mode = hook.stat().st_mode
        if hook.is_file() and not mode & stat.S_IXUSR:
            hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            done.append(f"made {hook.relative_to(root).as_posix()} executable")
    return done


def symlinks_work() -> bool:
    """True when this machine lets this user make a symlink; on Windows that takes Developer Mode."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "target").mkdir()
        try:
            (Path(tmp) / "link").symlink_to("target", target_is_directory=True)
        except (OSError, NotImplementedError):
            return False
    return True


def changed_links(root: Path) -> list[str]:
    """Paths under .agents/skills that differ on disk from git's index, or that git doesn't track. A link only
    staged, as `link` leaves it, is no change: checking it out writes what the index holds."""
    status = gate.git("status", "--porcelain", "--", SKILL_LINKS_DIR, cwd=root).stdout
    # Each line is "XY path": Y is the working tree's side, " " when the file on disk is what the index holds.
    return [line[3:] for line in status.splitlines() if len(line) > 3 and line[1] != " "]


def checkout_links(root: Path, can_symlink: Callable[[], bool]) -> list[str]:
    """Where symlinks work, have git check the skill links out as real symlinks, which Codex follows. Elsewhere they
    stay plain files holding their target: git's index still has them as links, so every commit keeps them."""
    if not can_symlink():
        return [
            f"this machine can't make symlinks (Windows without Developer Mode), so {SKILL_LINKS_DIR} holds plain "
            "files and Codex finds no skills there; AGENTS.md names them, and each is a SKILL.md to read"
        ]
    # A checkout overwrites what differs on disk from git's index, so a changed link is left for the developer to look
    # at. Checked before core.symlinks changes: with it false, a plain file holding the target is no change.
    changed = changed_links(root)
    if changed:
        return [
            f"warning: {SKILL_LINKS_DIR} has local changes, so it was not checked out again: "
            f"{', '.join(changed)}; see git status -- {SKILL_LINKS_DIR}, then run this again"
        ]
    lines = [set_config(root, "core.symlinks", "true")]
    if not gate.git("ls-files", "--", SKILL_LINKS_DIR, cwd=root).stdout.strip():
        return lines
    done = gate.git("checkout", "--", SKILL_LINKS_DIR, cwd=root)
    if done.returncode != 0:
        return [*lines, f"TO DO: git checkout -- {SKILL_LINKS_DIR} failed: {done.stderr.strip()}"]
    return [*lines, f"{SKILL_LINKS_DIR} checked out as symlinks"]


def link(root: Path, name: str) -> tuple[bool, str]:
    """Write `.agents/skills/<name>` into git's index as a symlink (mode 120000) to the skill, then check it out.

    git puts a symlink on disk where it can, and otherwise a plain file holding the target; either way the commit has
    the link. Git Bash's `ln -s` copies the folder instead, which is why this writes the index directly.
    """
    if not (root / SKILLS_DIR / name / "SKILL.md").is_file():
        return False, f"no skill {name}: {SKILLS_DIR}/{name}/SKILL.md doesn't exist"
    path = f"{SKILL_LINKS_DIR}/{name}"
    on_disk = root / path
    if on_disk.is_dir() and not on_disk.is_symlink():
        return False, f"{path} is a folder (a copy, as Git Bash's ln -s makes): delete it, then run this again"
    target = f"../../{SKILLS_DIR}/{name}"
    blob = gate.git("hash-object", "-w", "--stdin", cwd=root, stdin=target)
    if blob.returncode != 0:
        return False, f"linking {path} failed: {blob.stderr.strip()}"
    sha = blob.stdout.strip()
    listed = gate.git("ls-files", "-s", "--", path, cwd=root).stdout.split()
    if listed[:2] == [LINK_MODE, sha] and (on_disk.is_symlink() or on_disk.is_file()):
        return True, f"{path} -> {target} (already linked)"
    added = gate.git("update-index", "--add", "--cacheinfo", f"{LINK_MODE},{sha},{path}", cwd=root)
    if added.returncode != 0:
        return False, f"linking {path} failed: {added.stderr.strip()}"
    done = gate.git("checkout", "--", path, cwd=root)
    if done.returncode != 0:
        return False, f"{path} is staged as a link, but git couldn't check it out: {done.stderr.strip()}"
    kind = "a symlink" if on_disk.is_symlink() else "a plain file holding the target (git makes no symlinks here)"
    return True, f"{path} -> {target} (linked in git's index; on disk {kind}). Commit it with the skill."


def link_all(root: Path, names: list[str]) -> int:
    """Link each named skill, or every skill in .claude/skills; 1 when one failed."""
    names = names or list(gate.skill_folders(root))
    failed = 0
    for name in names:
        ok, line = link(root, name)
        print(line)
        failed += not ok
    return 1 if failed else 0


def run(
    root: Path, which: Callable[[str], str | None] = shutil.which, can_symlink: Callable[[], bool] = symlinks_work
) -> int:
    """Configure the repo at root and print what was done; 1 when something is left for you to do."""
    if gate.git("rev-parse", "--git-dir", cwd=root).returncode != 0:
        print(f"not a git repository: {root}")
        return 1
    done = []
    for title, lines in (
        ("git config (this repo only)", [f"{set_config(root, k, v)}: {why}" for k, v, why in CONFIG]),
        ("hooks", make_hooks_executable(root) or ["executable as stored"]),
        ("skill links", checkout_links(root, can_symlink)),
    ):
        print(f"{title}:")
        for line in lines:
            print(f"  {line}")
        done += lines
    todo = sum(line.startswith("TO DO") for line in done)
    print("tools:")
    for name, needed, why in TOOLS:
        if which(name):
            print(f"  {name}: found")
        elif needed:
            todo += 1
            print(f"  TO DO: {name} is missing; the hooks skip themselves without it. Install: {why}")
        else:
            print(f"  {name}: missing (optional: {why})")
    print("done." if not todo else f"done, with {todo} thing(s) to do above.")
    return 1 if todo else 0


def main(argv: list[str] | None = None) -> int:
    gate.utf8_streams()
    parser = argparse.ArgumentParser(description="Set up this clone: hooks, git blame, skill links, tools.")
    commands = parser.add_subparsers(dest="command")
    link_parser = commands.add_parser("link", help=f"link {SKILLS_DIR}/<skill> into {SKILL_LINKS_DIR} for Codex")
    link_parser.add_argument("skill", nargs="*", help="the skills to link; every skill when none is named")
    args = parser.parse_args(argv)
    if args.command == "link":
        return link_all(ROOT, args.skill)
    return run(ROOT)


if __name__ == "__main__":
    sys.exit(main())
