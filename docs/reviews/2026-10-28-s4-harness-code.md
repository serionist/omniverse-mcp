---
subject: "S4, the agent harness (PR #12)"
base: main (a77c892)
head: 1168908
date: 2026-10-28
round: 1
tier: medium (one fresh reviewer; findings checked against the code by the main session)
verdict: needs-fixes
---

# Review: S4, the agent harness

Read only. Fixed in `8612e2e`; each fix has a test in `tests/test_gate.py` that runs without the network, except
where the row says otherwise.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tools/hooks.py` pre-push | The hook ignored the refs git passes on stdin and checked `origin/main..HEAD` and the working tree. `git push origin other-branch`, or a push with uncommitted edits, was judged by the wrong commits and the wrong files: attribution or a secret in the pushed commits could pass, and a push could fail on an edit it did not carry. | Fixed: each `<local ref> <local sha> <remote ref> <remote sha>` line is read. The commits' checks run on `<remote sha>..<local sha>`, or on `origin/main..<local sha>` for a new branch or a remote commit never fetched here; deletions send nothing and are left out. The working tree's checks run only when every pushed commit is HEAD and `git status --porcelain` is empty; otherwise each is marked skip, with the reason above the table. `gate.py --head` does the same for a person. Tests: `push_ranges`, `tree_skip_reason`. By hand: a dirty tree, a commit other than HEAD, a deletion. |
| F2 | major | `tools/gate.py` `_CO_AUTHOR` | Any co-author whose line held a tool's name was refused, so `Claude Martin <claude.martin@example.fr>` or `Devin Smith <devin@example.org>` could not commit. | Fixed: refused only when the address is a tool's (`noreply@anthropic.com`, OpenAI's, Cursor's and aider's noreply addresses, Copilot's noreply address, any `[bot]@users.noreply.github.com`) or the name is a tool's alone or with a model and a version (`Claude`, `Claude Opus 4.6`, `GitHub Copilot`, `aider (gpt-4o)`). Tests both ways. |
| F3 | minor | `tools/hooks.py` `message_text` | The hook dropped every comment line, as git does only when it opens an editor, and knew only `#`. With `-m`, git keeps a `# Generated with Claude Code` line, and it passed. | Fixed: everything above the scissors line (`^\S+ -{24} >8 -{24}$`, any comment character) is read, comment lines included. Tests: git's own template passes with `#` and `;`; a commented attribution line is refused; a `-v` diff of the tests' `REFUSED` list below the scissors passes. |
| F4 | minor | `tools/gate.py` `branch_commits` | `--no-merges` left merge messages unchecked, and gitleaks reported "no commits" for a branch of merges only. | Fixed: merges are listed and checked. Found while fixing: `git log -p` shows a merge no diff, so gitleaks never saw a secret a merge's resolution added; `--diff-merges=first-parent` in its log options shows it (by hand, gitleaks 8.30.1: missed without it, found with it). Test: a merge with attribution in its message is listed once and refused. |
| F5 | minor | `.claude/settings.json` | `uv run ruff *` allowed `--fix` and `ruff format`, which write files, and `uv run pytest *` runs code, under an allowlist the docs called read-only. | Fixed: `uv run ruff check`, `uv run ruff check .` and `uv run ruff format --check*` only, and denies for ruff's `--fix` and `--unsafe-fixes` and basedpyright's `--writebaseline`, which would grow the baseline. pytest stays: it runs the repo's own tests. AGENTS.md and the plan's log say "read-only git and gh, plus the repo's own checks". |
| F6 | refuted | `.mcp.json` | An empty `CONTEXT7_API_KEY` header could make Context7 refuse a user without a key. | Refuted: the main session sent an MCP `initialize` to `https://mcp.context7.com/mcp` with an empty `CONTEXT7_API_KEY:` header and got 200, the same as with no header. No change. |
| F7 | minor | `tools/setup.py` `checkout_links` | `git checkout -- .agents/skills` ran whatever was changed there, so a hand edit was overwritten without a word. | Fixed: a path that differs on disk from git's index, or is untracked, skips the checkout with a warning naming it; a link only staged, as `link` leaves it, is still checked out. Checked before `core.symlinks` changes, while a plain file holding the target is no change. Tests for both. |
| F8 | minor | `tools/gate.py` `skill_problems` | The plain-YAML check of a description missed a trailing colon and a colon before a tab. | Fixed: a colon before any whitespace or at the end, or a `#` after whitespace. Tests for each. |
| F9 | improvement | `tools/gate.py` | The branch's commits were listed by each check that needed them, and each tool synced through its own `uv run --frozen`. | Taken: `Scope` lists them once per run; one `uv sync --frozen`, then each tool with `--no-sync`. |
| F10 | improvement | `tools/setup.py`, `tools/hooks.py` | `setup.py` re-implemented `gate.skill_folders()`, and the console's UTF-8 setup was copied three times. | Taken: both come from `gate.py`, `skill_folders(root)` and `utf8_streams()`. |

No round 2: both majors were fixed with tests, and what is left is minor.

## Checks

- **Gate:** `uv run tools/gate.py full` on `8612e2e` passed all 11 checks; pytest 337 passed, 124 skipped (the live
  suites, with no Kit running).
- **commit-msg:** through `tools/hooks.py` and through `git commit`, a message with
  `Co-Authored-By: Claude <noreply@anthropic.com>` is refused and a clean one passes.
- **pre-push:** with a dirty tree, the working tree's checks are skipped and the pushed range's 4 commits are
  checked; a commit other than HEAD on a new branch is checked against `origin/main`; a push that only deletes checks
  nothing.

## Round 2

The main session read round 1's fixes (`8612e2e`), after a fresh reviewer could not open the repo (folder ownership). It checked:
- pre-push's range per pushed ref;
- the fallback to the base for new branches and unfetched remotes;
- deletes skipped;
- tree checks only on a clean, pushed HEAD;
- co-authors refused only for a tool's address or name.

Verdict: clean.

Live use: this branch's own push ran pre-push (gate quick on the 2 commits sent, 10 checks pass), and a real `git commit` with `Co-Authored-By: Claude <noreply@anthropic.com>` was refused with HEAD unmoved.
