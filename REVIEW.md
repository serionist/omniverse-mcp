# Review

What every review of a change to this repo checks, whoever does it: the maintainer, an AI agent (`review-plan`,
`review-code`) or another tool. Same rules for all.

## What a finding is

Not a bug hunt. A finding is a real problem with a scenario you can reproduce: the input or state, what happens, and
why it matters to a user, their Kit app or the next change.

- No scenario, no finding. Style is ruff's; taste is the author's, at most an improvement (below).
- Refute each finding before you report it: quote the line that proves or kills it. A refuted one stays in the
  record, with its reason.

| Severity | What it is |
|---|---|
| blocker | a way past the bridge's token, `Origin` or `Host` checks; a token or secret leaked; a one-way door broken; Kit crashed or hung in normal use; a check loosened |
| major | a real user hits it in normal use: a wrong result, a tool that errors, a broken install on Windows, Linux or a supported Kit, new behaviour without a test |
| minor | everything else that is real: an edge case few meet, a missing doc line, a clumsy error message |

- Most findings are minor. An edge case that needs several unlikely things at once is a minor at most.
- Another round only after a blocker or a major. Minors are fixed in the same round, or recorded with a reason, and
  the review ends.

## Improvements

Apart from findings, a review lists only the improvements worth more than the edit they cost: a reuse it missed, a
simpler approach, a clearer name, a step a person must remember that a check could do.

- Not improvements: rewording or reshuffling for taste, options for cases nobody hits, "while you're here" extras.
- No severity, no scenario. Never counted, never a reason for another round.
- The author answers each: `taken`, `left: <why>` or `later: <issue>`. "left: not worth it" is a normal answer.

## The questions

Each is a yes or no; a "no" is a finding.

1. Did `uv run tools/gate.py full` pass on the reviewed commit, and CI on the PR's head?
2. Does the change do what its issue and plan say, and nothing nobody asked for?
3. Does new behaviour have a test that fails without it, and a fix a test that reproduced the bug? Do tests use
   invented data and clean up what they create?
4. For a change to the extension, the client or a tool: does the PR say whether the live suites ran
   (`OMNIVERSE_MCP_SIM=1`), on which Kit app, and what they could not show?
5. Does USD and Kit work stay on Kit's main thread, and does each handler run as its own task (`AGENTS.md`, Traps)?
6. Does every route still need the token, refuse an `Origin` and, on loopback, a foreign `Host`? No token, key or
   password in code, tests, logs, docs, commits or the PR?
7. Do tool names, parameters, annotations and results stay as they were, or does the change name what moved, in
   `docs/TOOLS.md` and `CHANGELOG.md`?
8. Do paths, encodings, line endings and processes work on Windows and Linux, and on every Kit the repo supports
   (Kit 107+, Isaac Sim 5.x and up)?
9. Does it leave the one-way doors in `AGENTS.md` alone, or name the one it changes and link the maintainer's
   agreement?
10. Did the docs move with it (`docs/TOOLS.md`, `docs/ARCHITECTURE.md`, the READMEs, `CHANGELOG.md`, `AGENTS.md`),
    written the way `AGENTS.md` asks?
11. Is each new package needed, under a licence compatible with MIT, pinned in `uv.lock`, and free of known advisories?
12. Is the PR title a plain imperative sentence, does the body say `Closes #<n>` or `Refs #<n>`, and is there no tool
    attribution anywhere?

## The harness

These decide how every other change is checked:

- `AGENTS.md`, `REVIEW.md`, `.claude/` (`CLAUDE.md`, the settings, the skills), `.agents/`, `.mcp.json`;
- `tools/`, `.githooks/`, `.gitleaks.toml`, `.github/`;
- `pyproject.toml`'s tool settings (ruff, basedpyright, pytest, coverage), `.basedpyright/baseline.json`.

Rules:

- A change that loosens a check is a blocker unless the maintainer agrees in the PR.
- That includes a gate step dropped or made a warning, a lint rule or a test skipped, an ignore or a baseline entry
  added, a question or a lens removed, attribution let through, a permission widened.
- A change that only makes a check stricter needs no more than a normal review.
- The `Read` denies in `.claude/settings.json` don't cover every Bash command: one that can print any file (a
  `git diff --no-index`, `git blame --contents` or `-S`) can get around them. An allow names its whole command; a
  ` *` is only for a git command `tests/test_gate.py` sweeps, or a gh command that only reads from GitHub. Claude Code
  runs git's read-only forms without any allow, so the usual spellings of what can read a file outside the repo get
  an `ask`; text rules can't catch every spelling. Bash rules don't reach PowerShell: each ask and deny has a
  `PowerShell(...)` twin.
