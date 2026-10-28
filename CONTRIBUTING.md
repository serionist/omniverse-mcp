# Contributing

Thanks for helping. This is the short path for a first contribution; [AGENTS.md](AGENTS.md) has the full rules, for
people and agents alike, and [REVIEW.md](REVIEW.md) what a review checks.

## Before you start

- **Open an issue** for every change, a typo included, with the bug or feature form, and say there that you want to work on
  it.
- **Write a plan first** for a non-trivial change: a new tool, a change to the bridge's security or its protocol, work
  on the server and the extension together. Use the template in [docs/plans/README.md](docs/plans/README.md) and open
  it as a draft PR. The maintainer approves it before any code.
- **Leave the one-way doors alone** unless the maintainer agrees in the issue first: the names and flags, the tools'
  contract, the extension's id and settings, the wire protocol, the output folder's layout (AGENTS.md, One-way doors).
- **Use invented data.** Tests, examples and logs in a PR never hold a real token, key or password.
- **Report security issues privately**, never in an issue: see [SECURITY.md](SECURITY.md).
- **Your contribution is MIT licensed.** Opening a pull request means you agree to license it under the repository's
  [MIT licence](LICENSE).

## Build and test

You need [uv](https://docs.astral.sh/uv/) (it brings Python), git and [gitleaks](https://github.com/gitleaks/gitleaks).

```
uv sync
uv run tools/setup.py
uv run tools/gate.py full
```

- `uv run tools/setup.py` sets up the clone once: the git hooks (`commit-msg` refuses tool attribution, `pre-push`
  runs the gate's quick lane), `git blame` past the reformat, the skill links. It is safe to run again.
- `gate full` runs the lock check, ruff, ruff format, basedpyright, import-linter's contracts, the coverage floor,
  the harness checks, the attribution check and gitleaks, then the unit tests under coverage, which must reach the
  floor. Without gitleaks it skips the secret scan with a warning; CI runs it.

### The live suites

`tests/test_integration.py` and `tests/test_scenarios.py` drive a real Kit app: Kit 107 or newer (Isaac Sim 5.x and
up) with the extension on. Add the repo's `extension/` folder to Kit's extension search paths (**Window > Extensions >
Settings**), turn on `ovmcp.bridge`, then:

```
OMNIVERSE_MCP_SIM=1 uv run pytest tests/test_integration.py tests/test_scenarios.py
```

In PowerShell, `$env:OMNIVERSE_MCP_SIM = "1"`, then `uv run pytest ...`. Without the variable they skip, even with
a Kit app running, so `uv run pytest` never touches your stage; with it, they run, and fail when no Kit answers.
They find the bridge where the server does, at `OMNIVERSE_MCP_HOST` and `OMNIVERSE_MCP_PORT` (127.0.0.1:8211 by
default), so a second Kit app can run them on another port beside your own. CI never runs them, so a PR that changes the extension, the client or a tool says whether
they ran and on which Kit app. Without a Kit app, say so in the PR.

### Adding a tool

A tool touches these places today. Step S7 of the [plan](docs/plans/2026-10-28-modernization.md) rewrites the tool
layer (MCP SDK v2, annotations, errors as error results), so check its progress log first.

| Where | What |
|---|---|
| `extension/ovmcp.bridge/ovmcp/bridge/handlers/<area>.py` | the handler, `async def handle_<name>(body: dict) -> dict`, exported from `handlers/__init__.py`; USD and Kit work stays on Kit's main thread (AGENTS.md, Traps) |
| `extension/ovmcp.bridge/ovmcp/bridge/extension.py` | its path in the `routes` table; the token, `Origin` and `Host` checks cover every route |
| `src/omniverse_mcp/client.py` | the client method, which calls `self.request("/<path>", {...})` |
| `src/omniverse_mcp/tools/<area>.py` | the `@mcp.tool()` function in the area's `register()`; its docstring is what the assistant reads |
| `docs/TOOLS.md`, `docs/ARCHITECTURE.md`, `CHANGELOG.md` | the tool's heading, the route, a line under Unreleased |
| `tests/` | unit tests against the mock bridge (`test_client.py`) or a canned answer (`test_tools_camera.py`), and a case in the live suite, `test_integration.py` |

## Open the pull request

1. Fork, and branch from `main` as `<issue>-<slug>`, such as `42-capture-timeout`.
2. Make the change with its tests and docs: `docs/TOOLS.md` for a tool, `docs/ARCHITECTURE.md` for a route, the
   protocol or the token, the READMEs, a line in [CHANGELOG.md](CHANGELOG.md) when users notice it, AGENTS.md when a
   path, a command or a rule changes.
3. Commit with a plain imperative subject that says what changed, and a body that says why. No AI co-author
   trailers, "Generated with" lines or session links: `commit-msg` refuses them.
4. Open the PR with [the template](.github/pull_request_template.md) filled in, ending `Closes #<issue>`, or
   `Refs #<issue>` for one step of it. Its title becomes the commit on `main`.

CI runs the gate's quick lane on Linux and the tests on Linux, Windows and macOS, CodeQL scans the code, and a check
reads the PR's title and description whenever they change: no attribution, and a line that names the issue. The maintainer reviews a PR from outside by
reading it: they never check it out, build or run it on their machine, where it would run next to their credentials
and their Kit app. Your PR is ready for review when CI is green. The maintainer squash-merges it.
