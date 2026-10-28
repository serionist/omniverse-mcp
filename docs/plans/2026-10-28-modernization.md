---
title: Modernize omniverse-mcp and publish 0.2.0 to PyPI
issue: "#2"
status: approved
approved_by: serionist
approved_at: 2026-10-28
---

# Modernize omniverse-mcp and publish 0.2.0 to PyPI

This plan is the record of the modernization. It holds the decisions, the design, the order of work and a progress
log. Read it first when picking the work up, and update its progress log at the end of every step.

It brings the repo in line with the maintainer's other projects (docket, WriteableFileProviders, bechtel-mvp): one rule
file for every agent, a review contract, a gate that hooks and CI both run, CI with pinned actions, a plugin, and a
release that publishes from a tag.

Approval: @serionist signed the plan off on 2026-10-28, with the recommended rows (D7-D14) as written, before plan
review round 1 had finished. That round's findings are applied as they come in; any that changes a decision goes back
to the maintainer as a question.

## Goal

When this is done, `0.2.0` is on PyPI and a Claude Code user installs it in two commands:

- **Safe to run:** the bridge only answers the MCP server that holds its token.
- **Installable:** `/plugin marketplace add serionist/omniverse-mcp`, `/plugin install omniverse-mcp@omniverse-mcp`,
  then the `setup` skill installs the Kit extension. Other MCP clients run `uvx omniverse-mcp`.
- **Checked:** ruff, pyright, unit tests with a coverage floor, the tool contract and the docs, on every PR, on Linux
  and Windows.
- **Worked on the same way as the other repos:** AGENTS.md, REVIEW.md, the skills, plans and review records.

**In scope:**
- **History:** AI attribution stripped from every commit on `main`.
- **Security:** the bridge token, Origin and Host checks.
- **Names and layout:** the rename (D2), `src/` layout, uv, hatchling.
- **Strictness:** ruff, ruff format, pyright, pytest config, a coverage floor.
- **Harness:** AGENTS.md, REVIEW.md, `.claude/`, skills, the gate, git hooks.
- **GitHub:** CI, CodeQL, Dependabot, issue forms, PR template, SECURITY, CHANGELOG, CONTRIBUTING.
- **The MCP server on SDK v2:** annotations, `ToolError`, the golden tool contract.
- **Tests:** a Kit-free extension core tested in CI on `usd-core`; live tests behind markers.
- **Distribution:** the plugin, the extension inside the wheel, the release workflow, `0.2.0`.

**Out of scope** (under Later): new tools, NVIDIA's extension registry, inline image results, hosted live-sim runs,
`1.0.0`.

## Decisions

Taken by @serionist on 2026-10-28 unless the row says otherwise.

| # | Decision | Detail |
|---|----------|--------|
| D1 | No tool attribution on `main` | No AI co-author trailers, no "Generated with" lines, no session links, in commits or PR bodies. The 9 commits that carry `Co-Authored-By: Claude` are rewritten (S0); a `commit-msg` hook refuses new ones (S4). |
| D2 | Rename while it is cheap | The names in Design / Names. They become one-way doors at `0.2.0`. |
| D3 | PyPI from the first release | `omniverse-mcp` on PyPI through trusted publishing. The repo is its own plugin marketplace; the plugin starts `uvx omniverse-mcp==X.Y.Z`. |
| D4 | The full loop | start-work, review-plan, review-code, finish-work and write-skill, as in the other repos. Plans in `docs/plans/`, review records in `docs/reviews/`. |
| D5 | Security first | S1 lands before anything else, on today's names, so a clone of `main` is safe as early as possible. |
| D6 | MCP SDK v2, pinned exactly | `mcp==2.3.0`, as docket. Majors move by hand; Dependabot ignores them. |
| D7 | One version | SemVer. One literal version in `pyproject.toml`, `extension.toml`, `plugin.json` and the plugin's uvx pin; the gate fails when they differ, the release fails when the tag differs. First release `0.2.0`. In `0.x` a minor may break the tool contract, under CHANGELOG's Breaking. (Recommended.) |
| D8 | Python 3.11 and up | 3.10 reaches end of life this month; Isaac Sim 5.x ships 3.11; `usd-core` needs 3.11. Development on 3.12. CI on 3.11-3.14. (Recommended.) |
| D9 | The extension ships in the wheel | `omniverse-mcp extension install` copies it to one per-user folder that Kit's search path points at once. Server and extension then come from the same release. (Recommended.) |
| D10 | A Kit-free extension core | HTTP, auth, formatting, geometry maths and the PNG writer move to a core that imports no `omni`, `carb` or `isaacsim`, enforced by import-linter and tested on `usd-core` in CI. (Recommended.) |
| D11 | Live-sim tests stay off hosted CI | `sim` and `scenario` markers; skipped unless `OMNIVERSE_MCP_SIM=1`, and failing instead of skipping when it is set and Kit is not reachable. A PR that touches the extension says whether they ran. (Recommended.) |
| D12 | Ratchets | The coverage floor only rises; ruff's per-file ignores only shrink. (Recommended.) |
| D13 | The March work | `wip/2026-03-08-camera-lighting` (inspect_prim auto-fit and isolate, viewport_light modes). Kept and fixed: it lands as S1b, right after S1, with the fixes of its [review](../reviews/2026-10-28-wip-camera-lighting-code.md). |
| D14 | How the work lands | One issue for this plan, one PR per step, squash-merged by the maintainer. (Recommended.) |

## Design

### Names (D2)

| Thing | Now | After |
|---|---|---|
| PyPI distribution | `omniverse-mcp` (never published) | `omniverse-mcp` |
| Import package | `isaac_sim_mcp` | `omniverse_mcp`, in `src/omniverse_mcp/` |
| Console script | `omniverse-mcp` | `omniverse-mcp` (serves stdio), `omniverse-mcp extension install\|path` |
| MCP server name | `Isaac Sim` | `omniverse` |
| Plugin and marketplace | none | `omniverse-mcp`, both |
| Plugin server key | none | `omniverse`, so tools are `mcp__plugin_omniverse-mcp_omniverse__<tool>` |
| Kit extension id | `isaacsim.mcp.bridge` (NVIDIA's namespace) | `ovmcp.bridge` |
| Extension folder | `extension/isaacsim.mcp.bridge-1.0.0/` | `extension/ovmcp.bridge/` (R1) |
| Kit settings | `/exts/isaacsim.mcp.bridge/*` | `/exts/ovmcp.bridge/*` |
| Environment | none | `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT`, `OMNIVERSE_MCP_OUTPUT_DIR`, `OMNIVERSE_MCP_TOKEN` |

`ovmcp` and not `omniverse_mcp.bridge`: the extension's top-level module must not be the server's, or the core tests
cannot import both in one environment; and it must not be `mcp.*`, which shadows the SDK. A namespace of our own also
ends the `isaacsim` namespace clash that `c6454e6` worked around.

### The bridge's security (S1)

Today the bridge reads only `Content-Length`. Any local process, and any web page through a plain-text `fetch()` POST,
can call `/execute` and run Python inside Kit.

- **Token:** at startup the extension makes `secrets.token_urlsafe(32)` (or takes the `token` setting, for a fixed
  remote setup) and writes it to `<user state dir>/omniverse-mcp/bridge-<port>.token`, mode 0600 on POSIX. It deletes
  the file on shutdown.
- **Every request** carries `Authorization: Bearer <token>`, compared with `hmac.compare_digest`; else 401.
- **Origin:** any request with an `Origin` header gets 403. Browsers send one on every POST; our client never does.
- **Host:** the `Host` header must name the bound address or `localhost`; else 403 (DNS rebinding).
- **The server** takes `OMNIVERSE_MCP_TOKEN`, else the token file for its port, and reads the file again after a 401,
  since a Kit restart makes a new token. Each refusal says what to do.
- **Kit-free:** parsing, auth and routing move to `bridge/core/http.py`, tested with plain asyncio in CI.

Not chosen:

| Option | Why not |
|---|---|
| Origin and Host checks only | Any local process still runs code. |
| A Unix socket or named pipe | No remote Kit; two code paths for Windows and Linux. |
| mTLS | Certificates to manage for a loopback link. |

### Versions and the handshake (D7)

- `/health` returns `extension_version` and `protocol`. `protocol` is an integer constant on each side; a test keeps
  them equal.
- The server checks once per connection. On a mismatch every tool fails with `ToolError`: "The Kit extension is 0.1.0
  and the server is 0.2.0: run `omniverse-mcp extension install` and restart Kit."
- Literal versions, not versions from tags as in WriteableFileProviders: `plugin.json` must hold one, and Claude Code
  moves users to a new plugin version only when it changes. The release PR bumps all four.

### The MCP server on SDK v2 (S7)

- `MCPServer("omniverse", instructions=INSTRUCTIONS, version=__version__)` from `mcp.server.mcpserver`.
- **No work at import:** `main()` parses arguments (defaults from the environment) and calls
  `create_server(config)`. Tests build servers without touching `sys.argv` or the working directory.
- **One call helper** replaces the `_call` and `_check_error` copied into all 7 tool modules. It raises `ToolError`
  with the bridge's message and the last lines of its traceback, so clients see an error result, not `ERROR:` text.
- **Parameters:** every one is `Annotated[T, Field(description=..., ge=, le=)]`; choices are `Literal[...]`.
- **Annotations,** four constants:

  | Constant | Hints | For |
  |---|---|---|
  | `READS` | read-only | queries and captures |
  | `EDITS` | not destructive | create, transform, material, camera, visibility, variant selection |
  | `DESTROYS` | destructive | delete_prim, new_scene, save_scene, flatten_usd, export_prim_as_file, update_material_paths |
  | `RUNS` | destructive, open world | execute_script, manage_extensions |

  The final table for each tool is set in S7 and pinned by the golden file.
- **Instructions:** the rules every session needs (call `get_sim_state` first, look before acting, files not inline
  images, Context7 before `execute_script`), as terse bullets.
- **Golden contract:** `tests/fixtures/mcp-tools.json` holds each tool's name, schemas and annotations, with
  descriptions stripped (docket's `contract()`). Changing it is deliberate: `uv run tools/golden.py`, and a CHANGELOG
  line.
- **Docs drift:** a test checks that every tool has its heading in `docs/TOOLS.md` and the other way round. The README
  stops stating a count (it says 42 and 40 today; the code registers 41).
- **Output files** stay as they are: images and long text are written to the output folder and their paths returned.

### Testability (S6)

- **pytest:** `--import-mode=importlib -ra --strict-markers`, `xfail_strict`, `filterwarnings = ["error"]`. Markers
  `sim` and `scenario` (D11).
- **Live tests:** `test_integration.py` and `test_scenarios.py` get `pytestmark`. Results go to `test_project/results/`
  as today (ignored).
- **Extension core:** `extension/ovmcp.bridge/ovmcp/bridge/core/`: HTTP and auth, formatter, bounding-box and
  projection maths, the PNG writer, the log filters. It imports the standard library and `pxr` only. The handlers stay
  in the Kit-bound modules and call into it.
- **Coverage:** over `src/omniverse_mcp` and the core. The floor is what S6 measures, in `pyproject.toml`; the gate
  refuses a floor lower than `origin/main`'s.
- **Style:** existing unittest tests stay; new tests are plain pytest.

### Tooling and the gate (S2, S3, S4)

- **Build:** hatchling. `src/omniverse_mcp/`, plus `force-include` of `extension/ovmcp.bridge` into the wheel as
  `omniverse_mcp/_extension/`. `uv.lock` is committed; `.python-version` is 3.12; dev tools are pinned exactly in
  `[dependency-groups] dev` (ruff, pyright, pytest, coverage, import-linter, usd-core).
- **ruff:**
  - line length 120, target py311;
  - rules `E F W I UP B SIM RUF S C4 PTH PL N RET TID ASYNC BLE`;
  - every ignore carries its reason;
  - tests may use `S101`;
  - `ruff format` is enforced.
  - The one reformat is its own commit, listed in `.git-blame-ignore-revs`. What S3 cannot fix by machine goes into
    per-file ignores that only shrink.
- **pyright:** `standard`; `strict` on `src/omniverse_mcp` and the extension core. The Kit-bound modules are excluded:
  there are no stubs for `omni` and `carb`.
- **Gate:** `tools/gate.py`, standard library only, run as `uv run tools/gate.py quick|full`.

  | Lane | Runs |
  |---|---|
  | quick | lock check, ruff check, ruff format check, pyright, import-linter, versions agree (D7), AGENTS.md within 150 lines, skills' name equals folder and each has a description, marketplace and manifest agree, gitleaks on the branch, no attribution in the branch's messages |
  | full | quick, then pytest with coverage and the floor, then `claude plugin validate --strict` when the CLI is there |

- **Hooks** (`.githooks/`, turned on by `uv run tools/setup.py`):
  - `commit-msg` refuses attribution;
  - `pre-push` runs gate quick;
  - `post-checkout` and `post-merge` list the AI setup files that changed.
  - A missing uv skips them with a warning; CI runs the same gate.

### Harness (S4)

| File | What |
|---|---|
| `AGENTS.md` | The rules for every agent and person, within 150 lines: what this is, where things are, build and test, how a change lands, writing, commits and PRs, one-way doors, traps, never. |
| `.claude/CLAUDE.md` | `@../AGENTS.md` |
| `REVIEW.md` | No scenario, no finding; blocker, major, minor; yes/no questions; the harness list. |
| `.claude/settings.json` | Empty attribution, a read-only allowlist (git, gh, `uv run tools/gate.py *`, `uv run pytest *`, `uv run ruff *`), Read denies on secrets and on git flags that read files. |
| `.claude/settings.local.json.example` | Opts into the root `.mcp.json` servers. |
| `.mcp.json` | context7 over HTTP with `${CONTEXT7_API_KEY:-}` (today it runs `cmd /c npx`, which works on Windows only). |
| `.claude/skills/` | start-work, review-plan and review-code (each with `lenses.md`), finish-work, write-skill. |
| `.agents/skills/` | Links to the same skills for Codex, made by `tools/setup.py link`. |
| `docs/plans/README.md`, `docs/reviews/README.md` | The plan template; how review records are named. |

Lenses for review-code:
- plan and intent;
- tool contract;
- Kit main thread;
- bridge security;
- tests;
- docs freshness;
- simplicity;
- compatibility (Kit and Isaac Sim versions, Windows and Linux);
- harness integrity.

Traps, from this repo's own history:

| What broke | When | The guard |
|---|---|---|
| A handler awaited inside the connection task: "Cannot enter into task", which broke Kit's property widgets and viewport | `ceb6dd9` | Handlers run as their own task (`ensure_future`) |
| An `isaacsim/__init__.py` of ours shadowed NVIDIA's namespace package | `c6454e6` | A namespace of our own (D2) |
| Instance segmentation was empty until a frame had rendered | `d688f31` | Sensor made at startup, one retry |
| Kit 105.1+ has no default light, so captures came back black | README | `is_black` check, `viewport_light` |
| The log buffer's dict changed during a filtered query: `KeyError` | `8d684d6` | Copy before filtering |
| USD called off the main thread crashes Kit | `misc.py` | Never `run_in_executor` for USD work |

### CI and release (S5, S9)

- **Every workflow:**
  - actions pinned by SHA with a version comment;
  - `permissions: contents: read`, raised per job with a reason;
  - `persist-credentials: false`, `timeout-minutes`, `fail-fast: false`;
  - only PR runs are cancelled by a newer one.
- **`ci.yml`** on PRs and `main`:
  - checks: gate quick on Linux, with gitleaks installed against its sha256, and Claude Code pinned for
    `plugin validate`;
  - tests: Linux on 3.11, 3.12, 3.13 and 3.14, Windows on 3.11 and 3.14; coverage and the floor on one leg.
- **`codeql.yml`:** `python` and `actions`, `security-extended`, on PRs, `main` and weekly.
- **`dependabot.yml`:** `uv` and `github-actions`; weekly; a 7-day cooldown; minor and patch grouped.
- **`release.yml`** on `v*` tags:
  1. **verify:**
     - the tag is on `main`;
     - the four versions equal the tag;
     - CHANGELOG has a dated `## X.Y.Z (YYYY-MM-DD)` section;
     - `uv build`, then `twine check --strict` and `check-wheel-contents`;
     - the wheel holds the extension.
  2. **ci:** a green `ci.yml` run on the tagged commit.
  3. **publish:** the `pypi` environment (a required reviewer), trusted publishing with `pypa/gh-action-pypi-publish`,
     which also attests. An `-rc.N` tag goes to TestPyPI instead.
  4. **github-release:**
     - notes are the CHANGELOG section;
     - the wheel, the sdist and a zip of the extension are attached;
     - `-rc.N` marks it a prerelease.
- **`docs/releasing.md`:** date the CHANGELOG and bump the four versions in one PR; tag; approve the deployment.

### Distribution (S8)

- **Marketplace and plugin:** `.claude-plugin/marketplace.json` lists one plugin with source `./plugin`.
  `plugin/.claude-plugin/plugin.json` holds name, version, description, author, homepage, repository, licence and
  keywords.
- **`plugin/.mcp.json`:** `{"mcpServers": {"omniverse": {"command": "uvx", "args": ["omniverse-mcp==X.Y.Z"]}}}`.
  Host, port and output folder come from the environment, so nothing needs expanding in `args` (R2).
- **Plugin skills:**
  - `setup` installs the extension, points Kit at it, turns it on, checks with `get_sim_state`, and ignores
    `mcp_output/`;
  - the workflows of today's AI_GUIDE (look before acting, spatial reasoning, geometry and variants, simulate and
    record, scripting with Context7).
  - `allowed-tools` pre-approves `READS` tools only, never `execute_script`. The split is settled in S8 with write-skill.
- **`docs/AI_GUIDE.md`** stays for clients without skills and points at the skill files.
- **Extension delivery:** `omniverse-mcp extension install` copies the extension from the wheel to
  `<user data dir>/omniverse-mcp/exts/` and prints the folder to add to Kit's search paths once. Later installs
  overwrite it in place. `extension path` prints the folder. A git checkout can still point Kit at `extension/`.

Not chosen:

| Option | Why not |
|---|---|
| Clone the repo for the extension | The server from PyPI and the extension from git drift apart. |
| NVIDIA's extension registry | A second release channel; under Later. |

## Compatibility

Nothing has been released, but clones of `main` are in use (two forks, PR #1). The CHANGELOG's Breaking section gives
each item with its move-over step:

| Change | How a user moves over |
|---|---|
| History rewritten (S0) | `git fetch && git reset --hard origin/main` on a clone that tracks `main` |
| Token on the bridge (S1) | Update the server and the extension together; an old server gets a 401 that says so |
| `isaac_sim_mcp` becomes `omniverse_mcp` (S2) | In `.mcp.json`, `-m isaac_sim_mcp` becomes `omniverse-mcp`, or use the plugin |
| Extension id `ovmcp.bridge` (S2) | Turn off `isaacsim.mcp.bridge`, remove its search path, run `omniverse-mcp extension install`, turn on `ovmcp.bridge` with autoload; a custom port moves to the new setting |
| Python 3.11 and up (S2) | Recreate the environment on 3.11 or later |
| Errors become error results (S7) | None for agents; scripts that matched `ERROR:` text read `isError` |

**One-way doors from 0.2.0** (into AGENTS.md in S4):
- the PyPI name;
- the console script, its flags and its environment variables;
- the plugin and server-key names;
- tool names, schemas and annotations (the golden file);
- the Kit extension id and its settings;
- the wire protocol: paths, the auth header, the token file's place;
- the output folder's layout.

## Steps

Each step is one PR, buildable and testable on its own.

| Step | What | Proven by |
|---|---|---|
| S0 | Strip attribution from history; push `main`; open this plan's issue; decide D13 | No attribution in `git log --format=%B main`; every commit's tree equal to the one it replaces |
| S1 | Bridge token, Origin and Host checks, `protocol` in `/health`; HTTP layer Kit-free | Unit tests: no token gets 401, an `Origin` gets 403, a foreign `Host` gets 403, a wrong token gets 401; the sim suite passes with tokens |
| S1b | The March work, if kept (D13) | Its tests, plus its review record |
| S2 | Rename and layout (D2), hatchling, uv and `uv.lock`, Python 3.11 and up; no change in behaviour | Unit tests; the wheel holds the extension; the sim suite on Isaac Sim 5.1 |
| S3 | ruff, ruff format, pyright, `.editorconfig`, `.gitattributes`; the reformat commit | Gate checks clean on the branch |
| S4 | AGENTS.md, REVIEW.md, `.claude/`, skills, plan and review READMEs, gate, hooks, `setup.py`, `.gitleaks.toml` | Gate quick passes; a test that `commit-msg` refuses each attribution form |
| S5 | `ci.yml`, CodeQL, Dependabot, issue forms, PR template, CODEOWNERS, SECURITY, CHANGELOG, CONTRIBUTING | CI green on the PR itself |
| S6 | Markers, the Kit-free core, the import-linter contract, `usd-core` tests, the coverage floor | Core tests run in CI; the floor is set |
| S7 | SDK v2, annotations, `ToolError`, the golden file, docs drift tests, no work at import | The golden test; one in-memory client test per tool against the mock bridge |
| S8 | The plugin, skills, `extension install`, the README rewrite | `claude plugin validate --strict` in CI; `extension install` into a temp folder; the setup skill on a clean machine, by hand |
| S9 | `release.yml`, `docs/releasing.md`, `v0.2.0-rc.1` to TestPyPI, then `v0.2.0` | The rc installs with `uvx` from TestPyPI and passes the sim suite |

## Tests

| Suite | Runs where | New or changed |
|---|---|---|
| Unit (`tests/`) | CI, every PR | Auth and HTTP (S1), version check (S2), golden and docs drift (S7), in-memory client per tool (S7), `extension install` (S8), hook tests (S4) |
| Extension core (`usd-core`) | CI, every PR | New in S6 |
| `sim` (`test_integration.py`) | By hand, against Kit with the extension | Marker and token (S1, S6) |
| `scenario` (`test_scenarios.py`, `test_project/`) | By hand | Marker (S6) |

## Docs

- **README:** plugin install first, then `uvx`, badges, not affiliated with NVIDIA (S5, S8).
- **The repo's meta files:** AGENTS.md and REVIEW.md (S4); SECURITY.md, CHANGELOG.md and CONTRIBUTING.md (S5).
- **Reference:** `docs/ARCHITECTURE.md` gets the core, auth and handshake (S1, S6); `docs/TOOLS.md` is checked
  against the code (S7).
- **Skills:** `docs/AI_GUIDE.md` becomes the plugin's skills plus a short guide for other clients (S8).
- **Process:** `docs/plans/README.md` and `docs/reviews/README.md` (S4); `docs/releasing.md` (S9).
- **The extension's own README:** id and install (S2, S8).

## Risks

| # | Risk | Status |
|---|---|---|
| R1 | Kit may need the `-<version>` suffix on the extension folder (`c6454e6` added it) | Check on Isaac Sim 5.1 before S2 merges. If it does, the folder keeps the suffix and the release renames it |
| R2 | How Claude Code starts a plugin's stdio server: working folder, environment, `${VAR}` in `args` | Check with a probe plugin and `claude plugin validate --strict` before S8, as docket did for its HTTP entry |
| R3 | SDK v2 may run synchronous tools on the event loop, which blocks on the socket client | Check the SDK in S7; if it does, client calls go to a worker thread |
| R4 | The two forks keep the old commits, trailers included | Accepted; they cannot be changed from here |
| R5 | The force push breaks clones that track `main` | Accepted; the issue and CHANGELOG say how to move over |
| R6 | Live-sim tests never run in CI | Accepted (D11); the PR template asks whether they ran |
| R7 | `usd-core` is not the USD that Kit ships | Accepted; the core uses plain `pxr` APIs, and the sim suite runs before each release |
| R8 | Remote Kit and shared machines need the token by hand | `OMNIVERSE_MCP_TOKEN` and the `token` setting; a non-loopback bind still warns |
| R9 | Someone takes `omniverse-mcp` on PyPI first | Register a pending trusted publisher in S5 |

## Plan review

Pending. review-plan arrives in S4, so this round runs as a fresh agent with docket's plan lenses.

## Progress log

| Date | Step | What happened |
|---|---|---|
| 2026-10-28 | S0 | Local: unpushed `154d567` rebased onto `origin/main` (PR #1's pin), then all 12 commits rewritten without attribution, every tree unchanged. The March work is on `wip/2026-03-08-camera-lighting`. Backups: `backup/main-before-rewrite`, `backup/origin-main-before-rewrite`. Not pushed. |
| 2026-10-28 | S0 | The March work reviewed: needs-fixes, 6 majors and 4 minors ([record](../reviews/2026-10-28-wip-camera-lighting-code.md)); 3 rest on Kit behaviour and need a live Isaac Sim. |
| 2026-10-28 | S0 | The maintainer approved the force push, the plan and keeping the March work (D13). `main` pushed with `--force-with-lease` (`b3cd7c5` → `ceb6dd9`); no attribution left on the remote. Issue #2 opened. S0 done. |

## For the maintainers

- **S0, git:**
  - approve the force push of `main`;
  - open the issue;
  - on this machine, `git config --global --add safe.directory D:/workspaces/omniverse-mcp` (the folder belongs to the
    `Work` account).
- **S5, PyPI:** a pending trusted publisher for `omniverse-mcp` (this repo, `release.yml`, environment `pypi`).
- **S5, GitHub environments and rulesets:**
  - the `pypi` and `testpypi` environments, with you as required reviewer;
  - a ruleset on `main`: PRs only, with the required checks;
  - a ruleset on `v*` tags.
- **S5, GitHub security settings:**
  - private vulnerability reporting;
  - secret scanning with push protection;
  - Dependabot alerts.
- **S5, the repo page:** a description and topics.
- **S9:** approve the `pypi` deployment.

## Later

- NVIDIA's extension registry.
- Image results inline for clients that cannot read files.
- Live-sim runs on a self-hosted GPU runner.
- The AI scenario suite as a skill.
- `1.0.0` once the tool contract has held for a few releases.
