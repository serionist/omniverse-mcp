---
subject: "Close five ways attribution or secrets got past the gate, the hooks and the settings (PR #18)"
base: main (90bc49c)
head: fa967c6
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer, who probed in throwaway repos; both majors reproduced by the main session)
verdict: needs-fixes
---

# Review: close five ways attribution or secrets got past the gate, the hooks and the settings

Read from the pack (scope diff, issue #17, the reproduction scripts); the reviewer ran its probes in throwaway repos
with invented values and touched no real repo. Every finding is on the harness. The main session reproduced both
majors before fixing them. Fixed in `ff3185e`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `tools/hooks.py`, `message_text`, `commit_msg` | Hole 3 stayed open with git's default `#`: with `git commit -F` or `-m`, git keeps even its own comment character's scissors line and the `Co-Authored-By: Claude` trailer below it (git 2.47: both stored), but commit-msg cut there and passed. git cuts only in a message it opened an editor for. | Fixed: git hands a hook `GIT_EDITOR=:` when it opened no editor (seen for `-F`, `-m` and `--amend` without an editor); `editor_ran()` reads that, and commit-msg cuts only after an editor. Test: `test_without_an_editor_a_scissors_line_hides_nothing`. |
| F2 | major | `tools/gate.py`, `gitleaks_problems`, `check_gitleaks` | The rule "no commit scanned while the gate listed some" failed clean work: gitleaks counts only commits that add a line, so a deletion, a rename, a mode change (as `check_hooks` asks for), an empty commit, or a merge of such a PR scanned 0 and failed pre-push and CI, which an agent can't skip now that `--no-verify` is denied. Reproduced: a deletion-only commit gave `0 commits scanned`, exit 0, no `ERR`. No test drove `check_gitleaks` itself. | Fixed: only an `ERR` line fails a run that exited 0; the count is no sign either way. `check_gitleaks` takes the repo as `root`. Tests: `test_gitleaks_problems` (a deletion's clean log passes), `test_check_gitleaks_reads_what_gitleaks_logged_when_it_exits_0` (gitleaks stood in: an `ERR` fails, a clean log passes, and it is handed full ids). By hand with gitleaks 8.30.1: a deletion-only range passes; the blobless clone still fails with gitleaks' own `ERR` line. |
| F3 | minor | `.claude/settings.json` | Bundled short flags (`git commit -an -m x`, `-sn`) skip commit-msg and match no deny. | wontfix: no glob catches short options run together, as with blame's `-wS`; `git commit` is not on the allow list, so it asks first. The PR's table says so. |
| F4 | minor | `tests/test_gate.py`, `test_comment_chars_come_from_git` | It read the developer's global and system git config: with `core.commentChar=auto` in `~/.gitconfig`, the empty case returned the auto set. | Fixed: `GIT_CONFIG_GLOBAL` points at an empty file and `GIT_CONFIG_NOSYSTEM=1`. |
| F5 | minor | `tools/hooks.py`, `comment_chars` | git reads `core.commentChar` and `core.commentString` as one setting, the last one read winning, and "auto" in any case; the hook preferred commentString wherever it was set, and matched "auto" exactly. | Fixed: the last line of `git config --get-regexp '^core\.comment(char|string)$'`, compared lower-cased. Tests: the cases with both names, and "AUTO". |
| F6 | minor | `tools/gate.py`, `identity_problems`; `tools/hooks.py`, `commit_msg` | A person whose `user.name` is just a tool's name ("Claude", "Devin") with their own address is refused as author, with a hint that will puzzle them. | wontfix: the same rule as a co-author trailer, which the S5 review settled; a bare tool name is what a tool sets, and a person's full name passes. |
| F7 | minor | `CONTRIBUTING.md` step 3, `.githooks/commit-msg` | Both still named only attribution in the message. | Fixed: both name the author and committer too. |

Refuted, each from a probe or the code:

- **Resolving each end with `rev-parse` breaks ranges:** pre-push builds `<sha or origin/main>..<sha>` and CI
  `<sha or HEAD~1>..HEAD`; all resolve, and an unknown end fails earlier, in `list_commits`.
- **`gitleaks_problems` can be fooled:** a changed log format or no output gives no `ERR`, which is the old behaviour;
  an `ERR` inside another line can only fail a clean run, never pass a bad one.
- **`git var` misses the real identity:** it matches what git records for `--author`, `--amend` (the old author),
  `--reset-author`, `-c user.name` and `GIT_COMMITTER_*`; commit-msg never runs in CI, and the gate reads `git log`.
- **The identity check refuses main's history:** all 23 commits pass; so do `github-actions[bot]`, `renovate[bot]`
  and `GitHub <noreply@github.com>`.
- **Everyday commands denied:** `--no-edit`, `-m Fix` and `push -n` are not. A message that mentions ` -n` or `--no-v`
  is, which costs writing it to a file for `-F`.
- **Dropping the `git blame *` allow:** right; `-L` forms can carry `-wS`, and a safe allow is a form nobody types.
- **The tests:** each new test fails without its fix; the settings tests fail on main's settings.

Not settled: whether Claude Code's rule matcher treats quoted arguments as `fnmatchcase` does; the settings tests rest
on that.

Improvements:

- The hint offered `git commit --amend --reset-author`, which fixes only the last commit: taken; it also names
  `git rebase -r <base> --exec "git commit --amend --no-edit --reset-author"` for the commits before it.

## Round 2

**Where:** PR #18 at `ff3185e`; a fresh reviewer read the fixes (`fa967c6..ff3185e`) and probed in throwaway repos
(git 2.47.0, gitleaks 8.30.1). **Verdict:** needs-fixes, minors only, so no round 3; fixed in
`75bea24`, checked in this session.

Round 1's findings: F2, F4, F6 and F7 confirmed, each with its test; F3 agreed as wontfix. F1's fix held for its
scenario but rested on a wrong rule (N1), and its replacement makes F5's code unnecessary: both are superseded below.
The rebase hint was tried, and kept a range's merge.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| N1 | minor | `tools/hooks.py`, `editor_ran`, `commit_msg` | git drops what is below a scissors line only for `-v`, `commit.verbose` or `--cleanup=scissors`, not whenever an editor runs. `git commit -e -m x`, or an editor without `-v`, kept a `#` scissors line and the trailer below it while the hook cut there; with `GIT_EDITOR=:` inherited from the environment, `git commit --amend -v` was refused on a diff line git drops. | Fixed: below a scissors line, behind any character, every line a diff can't hold (`+`, `-`, a space, `@@`, the diff headers, `\ No newline`) is read; `editor_ran`, `comment_chars` and the auto set are gone. Tests: `test_a_trailer_below_a_scissors_line_is_read` (`#`, `;`, `@`), `test_a_diff_below_a_scissors_line_is_not_read`, and the template-and-diff scissors test. |
| N2 | minor | `tests/test_gate.py` | With the hook made never to cut, every hook test still passed: the `-v` diff the cut exists for could have regressed unseen. | Fixed: `test_a_diff_below_a_scissors_line_is_not_read`. Mutations, by hand: reading the diff fails it; dropping all below the line, as `main` did, fails the three trailer tests. |
| N3 | minor | `tools/gate.py` docstring; PR #18's description | Both still described the dropped count rule, and the description left out the editor condition, the new tests and the latest count. | Fixed: the docstring names only the `ERR` rule; the description was rewritten for the final change. |

Refuted: environment-passed `git -c` reaching the comment-character test (only under `git -c`, which no run here
uses); `--get-regexp` misreading a value with spaces (Git Bash rewrote a leading `//`); the rebase hint losing merges
(`-r` keeps them); an unread range passing now that the count rule is gone (log decoration, `core.quotePath` and an
external diff driver still read the commits and fail on the secret).

Out of scope, found meanwhile by the other session and reproduced here: an allow with `*` glued to its last word
(`git diff origin/main...HEAD*`) lets git diff a file outside the repository in no-index mode, around the `Read`
denies; and the denies don't reach the PowerShell tool. Filed as #19.

## Checks

- **The reproductions,** in throwaway repos with invented values, before and after: hole 2's blobless clone passes
  `main`'s `check_gitleaks` and fails this branch's with gitleaks' `ERR` line; hole 3's `;` scissors trailer is found;
  hole 4's commit authored by `Claude <noreply@anthropic.com>` passes `main`'s gate and fails this branch's.
- **Gate:** `uv run tools/gate.py full` passed all 14 checks on `fa967c6` (488 passed) and on `ff3185e` (490 passed,
  124 skipped: the live suites, without `OMNIVERSE_MCP_SIM=1`).
- **The live suites:** not run; nothing in the extension, the client or a tool changed.
