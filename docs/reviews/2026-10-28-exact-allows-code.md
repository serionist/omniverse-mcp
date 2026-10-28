---
subject: "Name each allowed command whole, and ask before what can read a file outside the repo (PR #20)"
base: main (31ebffe)
head: 8b9f015
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer, who probed in throwaway repos with invented secrets)
verdict: needs-fixes
---

# Review: name each allowed command whole, and ask before what can read a file outside the repo

Read from the pack (scope diff, issue #19, the author's probes); the reviewer matched the rules with `fnmatchcase`, a
trailing ` *` rule and lower-casing for PowerShell, and ran git 2.47.0 in throwaway repos. Every finding is on the
harness. Fixed in `abab351`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `.claude/settings.json`, the `git diff` asks | The asks needed a space before an outside path, so a path out of the repository as the first argument matched none: `git diff /c/.../secret.txt a.txt`, `git diff ~/secret.txt a.txt`, `git diff $HOME/... a.txt`, `git diff . ..`, `git diff .. .`, and in PowerShell a rooted `\Users\...` path or `$env:USERPROFILE\...`. Each printed the invented secret, and a command no rule matches falls to Claude Code's read-only set and runs. Not a regression (main asked for none), but the PR said a leading `/` or `~` asks. | Fixed: asks for `git diff /*`, `~*`, `*$*`, `*..`, `*.. *`, and a leading `\`; each rule with a `\` written both ways, as whether the matcher reads `\*` as an escape isn't documented. Tests: the outside path in first place for each spelling. The docs and the test say these are the usual spellings, not every one: a quoted `".."/x` or `.\./x` still gets past. |
| F2 | blocker | `.claude/settings.json`, `Bash(uv run lint-imports)` | A new allow: nothing on main matched the command, and the PR said nothing loosened (REVIEW.md, The harness: a permission widened). Exact and harmless, but unsaid. | Fixed: removed; the gate runs lint-imports itself. |
| F3 | minor | `AGENTS.md`, `REVIEW.md` | Both said every ` *` allow is swept; the five gh allows aren't, and "what can read a file outside the repo gets an ask" overclaimed given F1. | Fixed: the git ` *` allows are swept, gh's only read from GitHub, and the usual spellings of a path out ask. |
| F4 | minor | the PR | The sweep is 24 hand-picked read probes, not issue #19's generated sweep of every option, abbreviation, bundle and position, reads and writes, yet the PR closed #19. | Fixed: the PR says `Refs #19`, and #19 stays open for the generated sweep. |

Refuted, each from a probe:

- **`--output` prefixes:** `git log --outp=` and `git show --outp=` get past the deny text, but git refuses them as
  ambiguous; only blame takes such prefixes, and blame asks.
- **gh:** none of the six allowed gh commands' flags (gh 2.93) reads or writes a local file.
- **A symlink in the repo pointing out:** git treats `link/secret.txt` as a pathspec and prints nothing; only
  `--no-index` prints it, and that is denied.
- **Other read options:** `ls-files -X` reads the file and prints none of it; `rev-parse --resolve-git-dir` reports an
  invalid gitfile without printing it; `git diff a.txt ..` prints nothing.
- **The skills' redirects:** `git diff ... > scope.diff` is read-only either way, and the target is checked against
  Edit rules separately; no skill or AGENTS.md command newly prompts but `uv run pytest <file>` and
  `gate.py --base`, which the PR names.
- **The tests:** each fails on main (no `ask`, no PowerShell twins, glued `*` allows); the sweep tests git itself, as
  its name says.
- **PowerShell's case-insensitivity:** `PowerShell(git blame *-S*)` also denies `-s`, `--since` and `--show-stats`,
  which Bash only asks about: stricter, not a finding.

Not settled: whether Claude Code reads `\*` in a rule as an escaped `*` (both spellings are in, so one matches a real
backslash either way); whether PowerShell rules match the parsed command or its text, which decides whether backtick
escapes (`` .`./x ``) get past.

Improvements:

- Claude Code's changelog says its Bash `Read()` denies now cover option values and `git diff` file operands, and that
  `permissions.blockReadsOutsideWorkingDirectories` blocks reads outside the working directories for read-only
  commands: left: a per-user setting (with `additionalDirectories` for scratch folders), which the maintainer was
  told; REVIEW.md now says the denies don't cover every Bash command, rather than none.

## Round 2

**Where:** PR #20 at `abab351`; a fresh reviewer read the fixes (`8b9f015..abab351`) and probed in throwaway repos
with an invented secret, matching the rules with `\` read both ways. **Verdict:** needs-fixes, minors only, so no
round 3; fixed in `10e63ee`, checked in this session.

Round 1's F1 to F3 confirmed: every round 1 spelling still prints the secret and now matches an ask under both
readings of `\`, and every allow on the branch is covered by one of main's. F4 was still open at `abab351`: the PR's
description still closed #19 and described the asks as covering every path out; it now says `Refs #19` and "the usual
spellings".

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| N1 | minor | `.claude/settings.json`, the `git diff` asks | A quoted path out of the repository matched no ask: `git diff "/c/.../secret.txt" a.txt`, the path second or single-quoted, `"/home/me/x"` on Linux, and `git diff "." ".."`, which diffs the repository against its parent and prints every file under it; the same in PowerShell with `"\Users\..."`. Quotes stay in the text a rule is matched against (the permissions page: `git 'push'` isn't matched by `git push *`). | Fixed: asks for a quote right before `/`, `\` (both ways), `~` or `..`, double or single. Tests: the quoted cases. The test's comment names what still gets past: `.\./x`, a brace `{.,..}`, a command substitution, PowerShell's backtick escapes, and `git --no-pager diff` or `git -C . diff`. |

Over-asks, friction only: `git diff HEAD~3..`, `origin/main...`, `@{u}..`, `HEAD -- ':/*.py'` and anything with
`$(...)` now ask. None of review-code's own commands does.

Refuted: the doubled-backslash rules widen nothing under either reading; `%USERPROFILE%/x`, `'~'/x`, `.[.]/x`,
PowerShell `'..'\x`, `--stat {.,..}` and `git diff a.txt ..` print nothing; an outside path followed by `--stat`
prints nothing, and `-- a.txt ../x` is caught by `*../*`.

Improvement: review-code's own `git diff ... > file` commands in the let-through test, so a later, wider ask can't make
every review prompt: taken.

## Checks

- **The probes,** before the change on main: `git diff origin/main...HEAD/../../../outside/secret.txt
  ../outside/empty.txt` printed the invented secret through the `git diff origin/main...HEAD*` allow.
- **Mutations, by hand:** a glued `*` put back on an allow fails `test_every_allow_is_exact_or_a_swept_command`; a
  missing PowerShell twin fails `test_powershell_has_every_bash_ask_and_deny`.
- **Gate:** `uv run tools/gate.py full` passed all 14 checks on `8b9f015` (526 passed) and on `abab351`.
- **The live suites:** not run; nothing in the extension, the client or a tool changed.
