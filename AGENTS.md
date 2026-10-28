# omniverse-mcp

The rules for anyone who changes this repo, person or agent. Claude Code reads this file through `.claude/CLAUDE.md`,
Codex reads it directly; the gate caps it at 150 lines. What the tools do for those who use them is in `README.md`.

## What this is

An MCP server that lets AI assistants drive NVIDIA Omniverse Kit apps (Isaac Sim, USD Composer), and the Kit
extension it talks to.

- **The server** (`src/omniverse_mcp/`): `omniverse-mcp`, a stdio MCP server on Python 3.11+. Its tools call the
  bridge over HTTP and write images and long text to an output folder.
- **The bridge** (`extension/ovmcp.bridge/`): the Kit extension `ovmcp.bridge`, for Kit 107+ (Isaac Sim 5.x and up).
  `ovmcp/bridge` is Kit-bound (`omni`, `carb`); `ovmcp/core` imports no Kit and is unit-tested without it.
- **The link:** `/execute` runs Python inside Kit, so the bridge answers only requests with its token
  (`Authorization: Bearer`), refuses any `Origin`, and on loopback any foreign `Host`.
- **Where the work stands:** `docs/plans/2026-10-28-modernization.md` takes the repo to `0.2.0` on PyPI; read its
  progress log first.

## Where things are

| Path | What |
|---|---|
| `src/omniverse_mcp/` | the server: `server.py` (MCP server, output files, resources), `config.py` (flags, `OMNIVERSE_MCP_*`), `client.py` (the bridge's HTTP client), `bridge_token.py`, `tools/` (the tools by area) |
| `extension/ovmcp.bridge/` | the extension: `config/extension.toml` (id, version, settings), `ovmcp/bridge/` (`extension.py` with the routes, `handlers/`), `ovmcp/core/` (HTTP, token, framing, isolation, bounds, the formatter, PNG, logs; `usd.py` types what the pxr stubs get wrong), `docs/README.md` |
| `tests/` | pytest; `test_integration.py` and `test_scenarios.py` are the live suites (markers `sim`, `scenario`), which need Kit |
| `test_project/` | an MCP client project for AI-driven scenario runs: `scenarios.md`, `CLAUDE.md`, `.mcp.json.example` |
| `docs/` | `ARCHITECTURE.md` (routes, protocol, token, threading), `TOOLS.md` (a heading per tool), `AI_GUIDE.md` (for agents using the tools) |
| `docs/plans/`, `docs/reviews/` | plans of non-trivial changes, with the template; review records. Dated records, never current truth |
| `tools/` | `gate.py` (the gate), `hooks.py` (behind `.githooks/`), `setup.py` (once per clone; `link` for skills); standard library only |
| `.githooks/` | `commit-msg` refuses attribution, `pre-push` runs gate quick on what the push sends, `post-checkout` and `post-merge` name changed AI setup files |
| `.github/` | `workflows/`: `ci.yml` (gate quick on Linux; the tests on Linux 3.11-3.14, Windows 3.11 and 3.14, macOS 3.14; its `CI` job), `pr-text.yml` (gate text on a PR's title and description; its `PR text` job), `codeql.yml`, `dependabot-auto-merge.yml` (turns on auto-merge for Dependabot's minor and patch updates); `CI` and `PR text` are the required checks; `dependabot.yml`, the issue forms, the PR template, `CODEOWNERS` |
| `.claude/` | `CLAUDE.md` (imports this file), `settings.json` (no attribution; allows the repo's own checks and read-only git and gh, each named whole unless `tests/test_gate.py` sweeps it; asks before `git blame` and a `git diff` out of the repo; asks and denies twinned for PowerShell), `skills/` (below) |
| `.agents/skills/` | links to `.claude/skills/<name>` for Codex, written into git's index by `uv run tools/setup.py link` |
| `AGENTS.md`, `REVIEW.md` | this file; what a review finding is, and the questions every review answers |
| `.mcp.json` | Context7 over HTTP; `.claude/settings.local.json.example` turns it on |
| `pyproject.toml`, `uv.lock`, `.python-version` | the build (hatchling; the wheel carries the extension), the settings of ruff, basedpyright, pytest, coverage and import-linter, dev tools pinned exactly; the lock; Python 3.12 for development |
| `.basedpyright/baseline.json` | the type errors of before basedpyright, which only shrink |
| `.gitleaks.toml` | the secret scan: gitleaks' own rules, and any exception with its reason |
| `.editorconfig`, `.gitattributes`, `.gitignore`, `.git-blame-ignore-revs` | UTF-8 and LF everywhere; what git ignores; the reformat commits `git blame` skips |
| `README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE` | for users; what changed, under Unreleased; a first contribution's short path; how to report a vulnerability, and what counts; MIT |

A new top-level file or folder adds its row in the same change.

## Build and test

You need uv (it brings Python), git, and gitleaks for the secret scan. Every command is the same in bash and
PowerShell unless a PowerShell form stands beside it.

| What | Command |
|---|---|
| once per clone | `uv sync`, then `uv run tools/setup.py` (hooks, `git blame`, skill links) |
| tests | `uv run pytest`; with coverage, `uv run coverage run -m pytest`, then `uv run coverage report` |
| lint, format, types, imports | `uv run ruff check .`, `uv run ruff format --check .`, `uv run basedpyright`, `uv run lint-imports` |
| the gate | `uv run tools/gate.py quick` (lock, lint, format, types, imports, the coverage floor, AGENTS.md, skills, attribution, secrets); `full` adds pytest under coverage, and the floor; `text --file -` checks a PR's title and description: no attribution, and the issue named |
| live suites | `OMNIVERSE_MCP_SIM=1 uv run pytest tests/test_integration.py tests/test_scenarios.py`; PowerShell: `$env:OMNIVERSE_MCP_SIM = "1"`, then `uv run pytest ...` |

- **Live suites** need a Kit app running `ovmcp.bridge` (Kit's extension search path pointed at `extension/`), at
  `OMNIVERSE_MCP_HOST` and `OMNIVERSE_MCP_PORT` (127.0.0.1:8211 by default), as the server finds it.
  Without `OMNIVERSE_MCP_SIM=1` they skip, even with a Kit app running; with it they run, and fail when no Kit
  answers.
- **A headless Isaac Sim** needs `OMNI_KIT_ACCEPT_EULA=YES` (PowerShell: `$env:OMNI_KIT_ACCEPT_EULA = "YES"`), set
  by the person who accepts NVIDIA's EULA. An agent never sets it on its own.
- **Hosted CI never runs Kit:** a change to the extension, the client or a tool says in its PR whether the live
  suites ran, on which Kit app, and what they could not show.
- **Ratchets:** ruff's per-file ignores and `.basedpyright/baseline.json` only shrink, and the coverage floor
  (`fail_under`) only rises; the gate refuses a lower one. Fix the code; never add to them.

## How a change lands

1. **An issue** for every change, a typo included: the PR names it, and `PR text` checks that.
2. **A plan** in `docs/plans/` for non-trivial work (`docs/plans/README.md` says when), reviewed with `review-plan`
   until approved, then approved by the maintainer.
3. **A branch** `<issue>-<slug>` from `origin/main`, the plan its first commit.
4. **The code,** with its tests and docs in the same change.
5. **finish-work:** `uv run tools/gate.py full`, `review-code` until clean, a PR.
6. **The maintainer,** @serionist, squash-merges; merging is the approval. `main` takes PRs only.

The skills in `.claude/skills/` run this loop: `start-work` (1 to 3), `review-plan`, `review-code`, `finish-work`
(5), and `write-skill` for writing or fixing a skill.

## Writing

- A lead line, then a table or short bullets. Conclusion first; name the file, the command, the number.
- Plain words. No "ensure", "robust", "comprehensive", "leverage" or "seamless"; spaced hyphens, never em dashes;
  British spelling (behaviour, licence).
- A comment says why, not what the next line does, and says it in its own words, not only as a plan or review id.
- Docs move in the same change: `docs/TOOLS.md` for a tool, `docs/ARCHITECTURE.md` for a route, the protocol or the
  token, the READMEs, `CHANGELOG.md` when users notice, this file for a changed path, command or rule.

## Commits and PRs

- A plain imperative subject that says what changed; a body that says why, ending `Refs #<n>`, `Closes #<n>` or `Fixes #<n>`.
- PRs are squash-merged: the PR title becomes the subject on `main`, its description the body.
- A Dependabot PR's squash message keeps only its title and a line naming what moved: its description quotes other
  projects' release notes, which `pr-text.yml` doesn't check. A minor or patch update merges itself once `CI` and
  `PR text` pass, unless its PR is a draft, and `dependabot-auto-merge.yml` writes that line; a major waits for the
  maintainer, who cuts the message at merge.
- No tool attribution anywhere: no AI co-author trailers, no "Generated with" lines, no session links, no tool as a
  commit's author or committer, in commits, PR titles or PR bodies. `commit-msg` refuses them, and the gate checks
  every commit on the branch.

## One-way doors

Users depend on these from `0.2.0`. Change one only in a PR that names it in its title, after the maintainer agrees
in its issue; in `0.x` a minor may break the tool contract, under CHANGELOG's Breaking.

- the PyPI name `omniverse-mcp`;
- the console script, its flags and its environment variables (`OMNIVERSE_MCP_*`);
- the plugin's and the server key's names;
- tool names, schemas and annotations;
- the Kit extension id `ovmcp.bridge` and its settings;
- the wire protocol: paths, the auth header, the token file's place;
- the output folder's layout.

## Traps

What this repo's history already paid for:

| What broke | When | The guard |
|---|---|---|
| A handler awaited inside the connection task: "Cannot enter into task", which broke Kit's property widgets and viewport | `ceb6dd9` | Handlers run as their own task (`ensure_future`) |
| An `isaacsim/__init__.py` of ours shadowed NVIDIA's namespace package | `c6454e6` | A namespace of our own, `ovmcp` |
| Instance segmentation was empty until a frame had rendered | `d688f31` | Sensor made at startup, one retry |
| Kit 105.1+ has no default light, so captures came back black | README | `is_black` check, `viewport_light` |
| The log buffer's dict changed during a filtered query: `KeyError` | `8d684d6` | Copy before filtering |
| USD called off the main thread crashes Kit | `misc.py` | Never `run_in_executor` for USD work |

## Look up APIs before coding against them

Kit, Isaac Sim, USD (`pxr`) and the MCP SDK: look the API up with Context7 (`.mcp.json`) first, for the versions this
repo supports. SDKs move faster than any model's memory, and Kit's change between releases.

## Never

- Push to `main`, or merge with a failing gate.
- Weaken a test, a check, a hook or CI to make a change pass: no skip, no new ignore, no `--no-verify`.
- Check out, build or run code from outside the maintainers (a contributor's PR or branch) on your machine: read
  it, and let CI run it. It would run with every credential there, Kit included.
- Add tool attribution: commits, PR titles, PR bodies.
- Commit secrets: keys, passwords, a bridge token. Tests use invented ones.
- Change a one-way door without the maintainer's agreement.
