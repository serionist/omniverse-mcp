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
| D8 | Python 3.11 and up; Kit 107 and up | 3.10 reaches end of life this month; `usd-core` needs 3.11. The extension supports Kit 107+ apps (Isaac Sim 5.x), which embed 3.11; Kit 105 and 106 apps are not supported (Q1, 2026-10-28). Development on 3.12. CI on 3.11-3.14, plus macOS (Q4). |
| D9 | The extension ships in the wheel | `omniverse-mcp extension install` copies it to one per-user folder that Kit's search path points at once. Server and extension then come from the same release. (Recommended.) |
| D10 | A Kit-free extension core | HTTP, auth, formatting, geometry maths and the PNG writer move to a core that imports no `omni`, `carb` or `isaacsim`, enforced by import-linter and tested on `usd-core` in CI. (Recommended.) |
| D11 | Live-sim tests stay off hosted CI | `sim` and `scenario` markers; skipped unless `OMNIVERSE_MCP_SIM=1`, and failing instead of skipping when it is set and Kit is not reachable. A PR that touches the extension says whether they ran. (Recommended.) |
| D12 | Ratchets | The coverage floor only rises; ruff's per-file ignores only shrink. (Recommended.) |
| D13 | The March work | `wip/2026-03-08-camera-lighting` (inspect_prim auto-fit and isolate, viewport_light modes). Kept and fixed: it lands as S1b, right after S1, with the fixes of its [review](../reviews/2026-10-28-wip-camera-lighting-code.md). |
| D14 | How the work lands | One issue for this plan, one PR per step, squash-merged by the maintainer. (Recommended.) |
| D15 | basedpyright with a baseline | pyright has no baseline, and 277 of its errors at `standard` sit in code S7 rewrites. basedpyright is pyright with a baseline file: today's errors live in `.basedpyright/baseline.json`, may only shrink, and new code is checked in full, the same ratchet as ruff's (D12). `types-usd` gives `pxr` its types. Taken in S3b, 2026-10-28, under the maintainer's go-ahead for the plan's steps. |
| D16 | Dependabot merges its minor and patch updates | Once `CI` and `PR text` pass, through GitHub's auto-merge, which `dependabot-auto-merge.yml` turns on; a major waits for the maintainer, since CI never runs the live Kit suites (D11). The squash commit gets the PR's title and one line naming what moved, not the release notes. To hold one, the maintainer converts its PR to draft. A merge made this way starts no push run, since the workflow's token turned auto-merge on: `ci.yml` runs daily on `main` too, and CodeQL weekly, so `main` is tested within a day; @serionist agreed to that gap on 2026-10-28, over a GitHub App token. Asked for by @serionist on 2026-10-28, who chose minor and patch and had the repo's merge settings applied (For the maintainers). |

## Design

### Names (D2)

| Thing | Now | After |
|---|---|---|
| PyPI distribution | `omniverse-mcp` (never published) | `omniverse-mcp` |
| Import package | `isaac_sim_mcp` | `omniverse_mcp`, in `src/omniverse_mcp/` |
| Console script | `omniverse-mcp` | `omniverse-mcp` (serves stdio), `omniverse-mcp extension install\|path` |
| MCP server name | `Isaac Sim` | `omniverse` |
| Server flags | `--isaac-host`, `--isaac-port`, `--output-dir` | `--host`, `--port`, `--output-dir` |
| MCP resources | `isaac://scene/tree`, `isaac://sim/state` | `omniverse://scene/tree`, `omniverse://sim/state` |
| Output file headers | `# Isaac Sim MCP ...` | `# Omniverse MCP ...` |
| Plugin and marketplace | none | `omniverse-mcp`, both |
| Plugin server key | none | `omniverse`, so tools are `mcp__plugin_omniverse-mcp_omniverse__<tool>` |
| Kit extension id | `isaacsim.mcp.bridge` (NVIDIA's namespace) | `ovmcp.bridge` |
| Extension folder | `extension/isaacsim.mcp.bridge-1.0.0/` | `extension/ovmcp.bridge/` (R1) |
| Kit settings | `/exts/isaacsim.mcp.bridge/*` | `/exts/ovmcp.bridge/*`; the unused `scene_tree_max_depth` goes |
| Kit python modules | `isaacsim.mcp.bridge` (the core under it, behind an import guard) | `ovmcp.bridge` (Kit-bound) and `ovmcp.core` (Kit-free), so the core imports without running the Kit module |
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
- **Host:** when the bridge is bound to loopback, the `Host` header must name a loopback address or `localhost`;
  else 403 (DNS rebinding). Off loopback the Host is not checked, so a remote server can use any name; the token
  guards it.
- **The server** takes `OMNIVERSE_MCP_TOKEN`, else the token file for its port, and reads the file again after a 401,
  since a Kit restart makes a new token. Each refusal says what to do.
- **Kit-free:** parsing, auth and routing move to `bridge/core/http.py`, tested with plain asyncio in CI. Until S2
  the core sits under the Kit module, whose `__init__` imports the extension only when `omni` is there.
- **Refusals close the connection** before the body is read, so a refused body is never parsed as the next request.
- **The extension's version** comes from the `ext_id` Kit hands `on_startup`, so it holds wherever the extension's
  folder sits.
- **Handshake:** every new connection starts with `GET /bridge`, answered by the core whatever Kit's state; a stale
  token is refused there, on a request without a body (S1 review round 1).
- **Idle connections** close after 5 minutes, slow headers after 10 seconds; only authenticated requests hold one of
  the 20 handler slots.

Not chosen:

| Option | Why not |
|---|---|
| Origin and Host checks only | Any local process still runs code. |
| A Unix socket or named pipe | No remote Kit; two code paths for Windows and Linux. |
| mTLS | Certificates to manage for a loopback link. |

### Versions and the handshake (D7)

- `/health` returns `extension_version` and `protocol`. `protocol` is an integer constant on each side; a test keeps
  them equal. It changes only when a request or response changes shape.
- The server checks once per connection, with `GET /bridge` (S1). An extension without `/bridge`, or with another
  `protocol`, is refused with a message that says which side to update. A different `extension_version` alone is not refused (Q2). From S8
  the message gives the command that works for the user's install: `uvx omniverse-mcp==X.Y.Z extension install`.
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
  `capture_viewport(include_image=True)` keeps returning the image inline as well.
- **Concurrency:** SDK v2 runs synchronous tools on worker threads, several at once (`func_metadata.py:162-164`,
  `jsonrpc_dispatcher.py:622-623` in `mcp` 2.3.0); v1 ran them one at a time on the event loop. A lock around the
  client's requests keeps calls serial: one socket, and no two USD edits in Kit at once. The output-file counters
  become thread-safe. A test sends two calls at once to the mock bridge.

### Testability (S6)

- **pytest:** `--import-mode=importlib -ra --strict-markers`, `xfail_strict`, `filterwarnings = ["error"]`. Markers
  `sim` and `scenario` (D11).
- **Live tests:** `test_integration.py` and `test_scenarios.py` get `pytestmark`. Results go to `test_project/results/`
  as today (ignored).
- **Extension core:** `extension/ovmcp.bridge/ovmcp/core/`, beside the Kit-bound `ovmcp/bridge/`: HTTP and auth,
  formatter, bounding-box corner and clamp maths, the PNG writer, the log filters. It imports the standard library,
  `pxr` and `numpy` (Kit ships it; dev dependencies add it). Projection through `omni.syntheticdata` stays Kit-bound.
  The handlers stay in the Kit-bound modules and call into it. Tests put `extension/ovmcp.bridge` on the path.
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
  - The one reformat is its own PR, so its squash commit is the reformat alone; a follow-up PR lists that commit's
    `main` SHA in `.git-blame-ignore-revs`. What S3 cannot fix by machine goes into per-file ignores that only shrink.
- **pyright:** `standard` from S3; `strict` on `src/omniverse_mcp` from S7, which rewrites the server anyway, and on the
  extension core from S6. The Kit-bound modules are excluded: there are no stubs for `omni` and `carb`.
- **Gate:** `tools/gate.py`, standard library only, run as `uv run tools/gate.py quick|full`.

  | Lane | Runs |
  |---|---|
  | quick | lock check, ruff check, ruff format check, pyright, AGENTS.md within 150 lines, skills' name equals folder and each has a description, gitleaks on the branch, no attribution in the branch's messages; later steps add their own checks: import-linter (S6), versions agree and marketplace and manifest agree (S8) |
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
- **`ci.yml`** on PRs, `main` and daily (D16):
  - checks: gate quick on Linux, with gitleaks installed against its sha256, and Claude Code pinned for
    `plugin validate`;
  - tests: Linux on 3.11, 3.12, 3.13 and 3.14, Windows on 3.11 and 3.14, macOS on 3.14 (Q4: the server can drive a
    remote Kit from a Mac); coverage and the floor on one leg.
- **`pr-text.yml`:** checks the PR title and body for attribution on every edit, since the squash commit is built from
  them (D1); the repo's squash message is set to the PR title and description.
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
     which also attests.
  4. **github-release:**
     - notes are the CHANGELOG section;
     - the wheel, the sdist and a zip of the extension are attached.
- **No release candidates on an index.** The release PR's CI uploads its wheel; before merge it is tried with
  `uvx --from <that wheel>` and the sim suite. TestPyPI is never added as an index, which would let a name like `mcp`
  resolve there.
- **`docs/releasing.md`:** date the CHANGELOG and bump the four versions in one PR; try its wheel; merge; tag at once;
  approve the deployment. The marketplace serves `main` (Q3), so the time between merge and publish is the time
  plugin users can get a pin PyPI does not have yet (R10).

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
  `<user data dir>/omniverse-mcp/exts/` and prints the folder to add to Kit's search paths once. It copies to a
  temporary folder and swaps it in, so no stale module survives an upgrade. `extension path` prints the folder. In a
  checkout (an editable install, where the wheel's copy is absent) it takes `<repo>/extension/ovmcp.bridge`; a test
  covers both. A git checkout can still point Kit at `extension/`.
- **Turning it on in Kit:** the setup skill walks the user through the Extension Manager (search path, enable,
  autoload), or Kit's `--ext-folder <path>` launch flag. It never edits Kit's `user.config.json` while Kit runs: Kit
  rewrites it on exit.

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
| S1 | Bridge token, Origin and Host checks, `protocol` in `/health` and the client's check; HTTP layer Kit-free; live tests fail instead of skipping when `OMNIVERSE_MCP_SIM=1` | Unit tests: no token gets 401, an `Origin` gets 403, a foreign `Host` gets 403, a wrong token gets 401, the client finds a new token after a Kit restart and refuses another protocol; the sim suite with `OMNIVERSE_MCP_SIM=1` and none skipped |
| S1b | The March work (D13) with its review's fixes | Its tests, plus its review record |
| S2 | Rename and layout (D2, every row of Names), hatchling, uv and `uv.lock`, Python 3.11 and up for the server; `ovmcp.bridge` starts at the server's version, so the four versions agree from here; README, CONTRIBUTING and a committed `test_project/.mcp.json.example` move with the names | Unit tests; the wheel holds the extension; the sim suite on Isaac Sim 5.1 |
| S3a | ruff and ruff format config, the reformat alone | `ruff check` and `ruff format --check` clean |
| S3b | `.git-blame-ignore-revs` with S3a's `main` SHA; pyright `standard`; `.editorconfig`, `.gitattributes` | `pyright` clean |
| S4 | AGENTS.md, REVIEW.md, `.claude/`, skills, plan and review READMEs, gate, hooks, `setup.py`, `.gitleaks.toml` | Gate quick passes; a test that `commit-msg` refuses each attribution form |
| S5 | `ci.yml` (tests without a floor yet), `pr-text.yml`, CodeQL, Dependabot, issue forms, PR template, CODEOWNERS, SECURITY, CONTRIBUTING | CI green on the PR itself |
| S6 | Markers, the Kit-free core in `ovmcp/core`, the import-linter contract, `usd-core` tests, the coverage floor in CI and the gate | Core tests run in CI; the floor is set |
| S7 | SDK v2, annotations, `ToolError`, the request lock, the golden file (tools and resources), docs drift tests, no work at import, pyright strict on the server | The golden test; one in-memory client test per tool against the mock bridge; two calls at once stay serial |
| S8 | The plugin, skills, `extension install`, the README rewrite | `claude plugin validate --strict` in CI; `extension install` into a temp folder; the setup skill on a clean machine, by hand |
| S8b | Presentation: a logo and a social preview image (the maintainer uploads the preview; GitHub takes it only in the web settings), the README hero with badges, and screenshots or a GIF captured from a live Isaac Sim (a viewport capture beside its segmentation, an inspect orbit) | The README renders on GitHub in light and dark; every image is a real capture |
| S9 | `release.yml`, `docs/releasing.md`, then the `0.2.0` release PR and tag | The release PR's wheel runs with `uvx --from` and passes the sim suite; `uvx omniverse-mcp==0.2.0` works after publish |
| S10 | Announce, after `0.2.0` is on PyPI: a `server.json` in the official MCP registry, a line in the main awesome-mcp lists, the plugin install snippet on the release | The registry entry resolves to the PyPI package |

## Tests

| Suite | Runs where | New or changed |
|---|---|---|
| Unit (`tests/`) | CI, every PR | Auth, HTTP and the protocol check (S1), golden and docs drift (S7), in-memory client per tool and serial calls (S7), `extension install` from a wheel and from a checkout (S8), hook tests (S4) |
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
| R1 | Kit may need the `-<version>` suffix on the extension folder (`c6454e6` added it) | Resolved in S2: Isaac Sim 6.2 loads `extension/ovmcp.bridge` as `ovmcp.bridge-0.1.0`, and `on_startup` gets that id |
| R2 | How Claude Code starts a plugin's stdio server: working folder, environment, `${VAR}` in `args` | Resolved in S8 with a probe plugin (`claude --plugin-dir`, Claude Code 2.1.312): the project folder, the user's environment, `${CLAUDE_PLUGIN_ROOT}` and `${VAR:-default}` expanded in `args` |
| R3 | SDK v2 runs synchronous tools on worker threads, several at once, over the client's one socket | Resolved in plan review round 1: S7's request lock (Design / SDK v2) |
| R4 | The two forks keep the old commits, trailers included | Accepted; they cannot be changed from here |
| R5 | The force push breaks clones that track `main` | Accepted; the issue and CHANGELOG say how to move over |
| R6 | Live-sim tests never run in CI | Accepted (D11); the PR template asks whether they ran |
| R7 | `usd-core` is not the USD that Kit ships | Accepted; the core uses plain `pxr` APIs, and the sim suite runs before each release |
| R8 | Remote Kit and shared machines need the token by hand | `OMNIVERSE_MCP_TOKEN` and the `token` setting; a non-loopback bind still warns |
| R9 | Someone takes `omniverse-mcp` on PyPI first | Accepted: a pending trusted publisher doesn't reserve the name (PyPI's docs: only its first use to publish does), so the name is free until the first upload. From S8 the marketplace on `main` starts `uvx omniverse-mcp==0.1.0`, a version never published: a squatter's 0.1.0 would run for anyone who installed the plugin before 0.2.0. Accepted by the maintainer on 2026-10-29: the first upload, 0.2.0, claims the name, and the pending publisher was registered that day |
| R10 | The marketplace serves `main`, so between a release PR's merge and its publish (or after a failed publish) the plugin pins a version PyPI does not have, and the server does not start | Accepted (Q3): tag right after merge; a failed publish is fixed forward or the bump reverted at once |

## Plan review

### Round 1

- **How:** standard tier, one fresh agent with docket's review-plan method and lenses (review-plan arrives here in S4),
  on 2026-10-28.
- **Verdict:** needs-fixes, with 4 majors and 10 minors.
- **Now:** all applied except the owner calls, which wait on the maintainer.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | The core under `ovmcp/bridge/` cannot be imported without running the Kit module's `__init__` | Fixed: `ovmcp/core/` from S2; an import guard until then (S1) |
| P2 | major | A Host check against the bound address refuses every remote request | Fixed: Host checked only on loopback binds (as built in S1) |
| P3 | major | SDK v2 runs sync tools concurrently on threads sharing one socket; capture counters race | Fixed: S7's request lock and thread-safe counters; R3 resolved |
| P4 | major | The marketplace serves `main`, whose uvx pin can name a version not on PyPI (release window, failed release, rc) | Q3: serve `main`, accepted as R10; no rc tags |
| P5 | minor | Kit 105/106 apps run Python 3.10; `tomllib` in the core would break the extension there | Q1: Kit 107+ only; the version comes from `ext_id` anyway |
| P6 | minor | The handshake could refuse on version or on protocol; the message's command fails for plugin users | Fixed: refuse on protocol (Q2), S8's message gives the uvx command |
| P7 | minor | Proofs that depend on later steps: S3 on the gate, the gate on S8's files, CI on S6's floor, versions unequal from the start | Fixed: each check lands with its files; versions agree from S2 |
| P8 | minor | Live tests turn a 401 into a skip, so S1's proof passes with every test skipped | Fixed in S1: `OMNIVERSE_MCP_SIM=1` makes them fail |
| P9 | minor | The rename misses the flags, resources, output headers and a dead setting | Fixed: rows added to Names; resources go into the golden file |
| P10 | minor | `extension install` finds no extension in an editable checkout | Fixed: falls back to the repo's folder; tested both ways |
| P11 | minor | How the setup skill turns the extension on is unspecified | Fixed: Extension Manager or `--ext-folder`; never `user.config.json` while Kit runs |
| P12 | minor | A squash merge drops the reformat commit's SHA | Fixed: S3a alone, S3b lists its `main` SHA |
| P13 | minor | Attribution in a PR body reaches `main` through the squash message | Fixed: `pr-text.yml` and the squash-message setting (S5) |
| P14 | minor | The PNG writer and bbox maths use numpy; projection uses Kit | Fixed: the core may use numpy; projection stays Kit-bound |

Owner calls:

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Which Kit apps does the extension support? | Kit 105.1 and up (Python 3.10), enforced by ruff's per-path target | Kit 107+ / Isaac Sim 5.x (2026-10-28) |
| Q2 | Refuse on a protocol mismatch only, or on any version difference? | Protocol only; warn on versions | Protocol only (2026-10-28) |
| Q3 | How does the marketplace pin the plugin to a released version? | A `git-subdir` source pinned to the release tag, moved in a PR after PyPI has it | Serve `main` (2026-10-28); R10 |
| Q4 | macOS for the server? | One macOS unit-test leg, or say it is unsupported | A macOS test leg (2026-10-28) |

Improvements taken:
- the extension's version from `ext_id`;
- auth before the body is read, and refusals close the connection;
- pyright strict in S7;
- an atomic `extension install`;
- the rc tried from its wheel;
- `test_project/.mcp.json.example`;
- docs moving with the rename in S2.

## Progress log

| Date | Step | What happened |
|---|---|---|
| 2026-10-28 | S0 | Local: unpushed `154d567` rebased onto `origin/main` (PR #1's pin), then all 12 commits rewritten without attribution, every tree unchanged. The March work is on `wip/2026-03-08-camera-lighting`. Backups: `backup/main-before-rewrite`, `backup/origin-main-before-rewrite`. Not pushed. |
| 2026-10-28 | S0 | The March work reviewed: needs-fixes, 6 majors and 4 minors ([record](../reviews/2026-10-28-wip-camera-lighting-code.md)); 3 rest on Kit behaviour and need a live Isaac Sim. |
| 2026-10-28 | S0 | The maintainer approved the force push, the plan and keeping the March work (D13). `main` pushed with `--force-with-lease` (`b3cd7c5` → `ceb6dd9`); no attribution left on the remote. Issue #2 opened. S0 done. |
| 2026-10-28 | S1 | Built on `2-s1-bridge-token`: the core server with the token, Origin and Host checks; the client's token lookup, re-read and protocol check; live tests that fail under `OMNIVERSE_MCP_SIM=1`. 99 unit tests pass; the extension's wiring checked with Kit mocked. Plan review round 1 applied (above). Not yet run against a live Kit. |
| 2026-10-28 | S1 | Draft PR #3. The maintainer answered Q1-Q4. review-code round 1 ([record](../reviews/2026-10-28-s1-bridge-token-code.md)): needs-fixes, 3 majors and 6 minors, all fixed; the protocol check became a `GET /bridge` handshake on every new connection. 107 unit tests pass; a second Kit on the same port checked with Kit mocked. |
| 2026-10-28 | S1 | review-code round 2: 3 majors (a disabled bridge still served open connections, a timed-out script was resent, unlimited connections without the token) and 5 minors, fixed in `7199b96`; 114 unit tests pass. Live on Isaac Sim 6.2 (`D:\isaac`, headless; the maintainer accepted the Omniverse EULA for these runs): integration 10/10. The scenario suite matches `main`'s baseline. Its failures are Isaac Sim 6.2 problems that predate S1: a hang in the G1 robot's physics, Y-up gravity tests on a Z-up stage, and `draw_debug`. Details in the review record. |
| 2026-10-28 | S1b | Built on `2-s1b-camera-lighting`, stacked on S1: the March work plus every fix of its [review](../reviews/2026-10-28-wip-camera-lighting-code.md). Framing maths in `core/framing.py`, isolation in `core/isolation.py` (tested on usd-core, session layer restored byte for byte). The lighting fallback was checked with Kit mocked. F1, F3 and F6 wait on the sim suite. Not pushed. |
| 2026-10-28 | S2 | Built on `2-s2-rename-layout`, stacked on S1b: `src/omniverse_mcp/`, `extension/ovmcp.bridge/` with `ovmcp/bridge` (Kit-bound) and `ovmcp/core` (Kit-free, no import guard), hatchling with the extension force-included into the wheel, `uv.lock`, `.python-version` 3.12, Python 3.11+, flags `--host`/`--port` with `OMNIVERSE_MCP_*` defaults, `omniverse://` resources, `# Omniverse MCP` headers, extension and server both `0.1.0` (a test keeps them equal). README, CONTRIBUTING and docs moved with the names; `test_project/.mcp.json.example` committed. 200 unit tests pass under `uv run pytest`. Not yet run against a live Kit: the folder without a version suffix (R1), the `ext_id` Kit passes, the settings path. |
| 2026-10-28 | S1, S1b | PR #3 squash-merged as `937956a` and PR #4 as `1bbbcae`, both by the maintainer's word. The Isaac Sim 6.2 problems the live runs found are issues #5 (the G1 robot hangs Kit), #6 (Y-up gravity tests) and #7 (`draw_debug` needs `isaacsim.util.debug_draw`). The repo's description and 12 topics are set; Claude no longer shows among the contributors (the API lists serionist and tfoldi). |
| 2026-10-28 | S2 | Rebased onto `main` after #4. Live on Isaac Sim 6.2: Kit loads `ovmcp.bridge-0.1.0` from the folder without a version suffix (R1 resolved), settings are read from `/exts/ovmcp.bridge/*`, the token file is written and removed, `/bridge` reports `0.1.0`, integration 27/27 (one cold first capture over the timeout on the first run, as in S1). The maintainer added S8b (presentation) and S10 (announce). |
| 2026-10-28 | S3a | ruff 0.17.1 (the newest at least a week old) pinned in the dev group; the plan's rule set at line length 120 and Python 3.11, with a reason on every ignore. `ruff format` over the tree, then `ruff check --fix`: 94 fixed by the tool. The other 256 findings went into per-file ignores, 102 file-rule pairs in 30 files, as a baseline that only shrinks. `ruff check` and `ruff format --check` are clean; 209 tests pass. |
| 2026-10-28 | S3a, fix | #9 (S3a) merged as `dde3738`. The live scenario suite then showed phase 22, from #4, inspecting a `/World/Franka` no test creates; #10 gives it its own prim (merged as `8a8f9a0`): 83 pass, the rest are #6 and #7. |
| 2026-10-28 | S3b | basedpyright 1.40.2 at `standard` with a baseline of 277 errors (D15), `types-usd`; `.gitattributes` (LF everywhere; renormalizing changed nothing), `.editorconfig`, `.git-blame-ignore-revs` with #9's commit. |
| 2026-10-28 | S4 | Built on `2-s4-harness`: AGENTS.md (133 lines), REVIEW.md, `.claude/` (`CLAUDE.md`; settings with attribution off, an allowlist of read-only git and gh plus the repo's own checks, and Read denies), `.mcp.json` with Context7 over HTTP, the five skills, `.agents/skills` links written into git's index by `tools/setup.py link`, the plans and reviews READMEs, `tools/gate.py`, `tools/hooks.py` behind `.githooks/` (stored as 100755), `tools/setup.py`, `.gitleaks.toml`. Beyond the Harness section: review-code adds an `implementation` lens to the nine, for the ordinary bugs none of them looks for; the gate also checks that the hooks are stored as executable, that a description starts "Use when", and that AGENTS.md names each skill. gate full passes: 292 unit tests, 83 of them the harness's; gitleaks 8.30.1 finds nothing in the history or the tree, so `.gitleaks.toml` has no exception. The commit-msg hook refused a real commit with a `Co-Authored-By: Claude` trailer. A clone with `core.symlinks=false` gets the links as plain files, and the gate still reads them as links. Not pushed. |
| 2026-10-28 | S4 | Draft PR #12. review-code round 1, medium tier ([record](../reviews/2026-10-28-s4-harness-code.md)): needs-fixes, 2 majors (pre-push checked `origin/main..HEAD` and the working tree, not what the push sends; a person named like a tool could not be a co-author) and 5 minors, all fixed in `8612e2e` with tests; an empty Context7 key header refuted by a probe. Merge commits are now checked too, and gitleaks reads a merge's diff against its first parent, without which a secret added in a merge went unseen. gate full passes with 337 unit tests. Not pushed. |
| 2026-10-28 | S5 | Built on `2-s5-ci`. `ci.yml`: `Checks (Linux)` runs gate quick on the commits since the PR's base, or since the push's previous `main`, with gitleaks 8.30.1 checked against its sha256; `Tests (...)` on Linux on 3.11-3.14, Windows on 3.11 and 3.14, macOS on 3.14; `CI` needs both, and is one of the two required checks with `pr-text.yml`'s `PR text`. `pr-text.yml` runs the gate's new `text` lane on the title and description, read from the event file. `codeql.yml` (python, actions, security-extended), `dependabot.yml` (uv and github-actions, Mondays, a 7-day cooldown, minor and patch grouped, `mcp` majors ignored), the issue forms, the PR template, CODEOWNERS, SECURITY.md, CONTRIBUTING.md as a short path to AGENTS.md, the README's badges. Every action pinned to the SHA docket and WriteableFileProviders pin. `usd-core` 26.11 has a wheel for every leg. Left for later steps: Claude Code for `plugin validate` (S8, with the plugin) and the coverage floor (S6). gate full passes with 342 unit tests; the tests pass on Windows on 3.11 and 3.14, and in Docker on Linux on 3.11-3.14, where gate quick also passed on a PR's merge commit and on a squash push with gitleaks installed by the workflow's own step. Linux shows one warning from `tests/test_client.py`'s mock bridge (a writer closed after its event loop), which S6's `filterwarnings = ["error"]` will turn into a failure. The workflows and forms parse; actionlint is not installed here, and shellcheck finds nothing in the run steps. Not pushed: CI first runs on the PR. |
| 2026-10-28 | S5 | Draft PR #13; its first Actions run passed every job, and CodeQL found nothing. review-code round 1, medium ([record](../reviews/2026-10-28-s5-ci-code.md)): needs-fixes, 2 majors (a push whose `before` is gone turned CI red on a good commit; Dependabot's co-author line and quoted release notes failed the attribution rules), 5 minors and 2 improvements, all taken in `da95e00`, `f096ac0` and `580ac43`. The text lane now also requires a `Refs`, `Closes` or `Fixes` line with an issue number; `PR text` skips Dependabot's PRs; each CI job syncs once; CodeQL's jobs are `Analyse (...)`. gate full passes with 367 unit tests. Not pushed. |
| 2026-10-28 | S5, D16 | #13 (S5) merged as `1019117` after six review-code rounds, the last clean (record `docs/reviews/2026-10-28-s5-ci-code.md`). The repo's merge settings and the `main` ruleset were applied; auto-merge enabled after the checks had finished never fired, so #13 was merged directly. Dependabot's auto-merge for minor and patch updates (D16) added. |
| 2026-10-28 | S6 | Built on `2-s6-testability`. pytest in `[tool.pytest]`: importlib mode, strict config, markers, parametrize ids and xfail, every warning an error (the client tests' mock bridge leaked its loop, now closed). The live suites carry `sim` and `scenario` and run only with `OMNIVERSE_MCP_SIM=1`, as D11 says; before, they ran against any Kit that answered. The formatter, world bounds, screen outline, PNG writer and log ring moved into `ovmcp/core`, typed in strict mode with `core/usd.py` for the pxr stubs' gaps (isolation's 11 baseline entries gone); the formatter's text is unchanged. import-linter 2.15: the core imports no Kit, the server nothing of the extension. coverage 7.16.2 over the server and the core: 59.51% of lines and branches, floor 59; S7's tool contract raises it. numpy 2.4.6 (the newest for 3.11) in the dev group. |
| 2026-10-28 | S6, harness | #16 (S6) merged as `90bc49c`: its review split across two reviewers, five minors fixed, the live suites passing on Isaac Sim 6.2 beside the maintainer's own on another port. Two harness fixes from another session's review of a port of the gate, each reproduced here first: #18 (`7398a7e`; #17) closed five ways attribution or a secret got past the gate, the hooks and the settings, and #20 (`7f49d0d`; #19 stays open for a generated sweep) named each allowed command whole and asked before reads outside the repo. |
| 2026-10-28 | S7a | Built on `2-s7a-sdk-v2`; S7 lands in two PRs, as S3 did: S7a moves the server to `mcp` 2.3.0 (`MCPServer`, `create_server()`, nothing at import, one `bridge_call()` raising `ToolError`, the client's request lock, thread-safe output counters, `ResourceError`), S7b pins the tool contract (annotations, parameter descriptions and bounds, instructions, the golden file, docs drift, a test per tool, pyright strict on the server). The shared helper's typed result cleared 248 of the baseline's 266 entries. |
| 2026-10-28 | S7a, S7b | #22 (S7a) merged as `42610a5`. S7 splits once more: S7b (`2-s7b-tool-contract`) pins the contract: all 41 tools annotated with `READS`, `EDITS`, `DESTROYS` or `RUNS`; every parameter described, with bounds (`ge`, `gt`, `le`) and `Literal` choices; a before-and-after dump of the input schemas shows only added bounds and enums, no renames and no changed defaults. The instructions are terse bullets. `tools/golden.py` writes `tests/fixtures/mcp-tools.json` (tools, output schemas, annotations and resources, without prose), and `tests/test_contract.py` checks it, the hints, the descriptions and `docs/TOOLS.md`'s headings. The README and ARCHITECTURE stop stating a count. S7c is next: one in-memory test per tool against the mock bridge, and basedpyright strict on `src/omniverse_mcp`. Draft PR #24; review-code round 1 ([record](../reviews/2026-10-28-s7b-tool-contract-code.md)): clean, five minors fixed in `c085cdf`: zeros the handlers gave meaning to are allowed again, `draw_debug` takes `"lines"`, the bridge refuses a clone or create that would overwrite a prim (so `EDITS` stays true), and descriptions name what the bridge ignores (#25). The live suites pass on Isaac Sim 6.2 but for #6 and #7. |
| 2026-10-28 | S7b, S7c | #24 (S7b) merged as `cb71551`; #25 opened for the parameters the bridge ignores. S7c (`2-s7c-tool-tests`) finishes S7: basedpyright strict on `src/omniverse_mcp` (544 errors, nearly all bare `dict` answers and the untyped `register(mcp, client, h)`; the client now passes its socket instead of re-reading an Optional), `py.typed`, and `tests/test_tools.py`: each of the 41 tools once through the in-memory MCP client against the mock bridge, its route, body and text checked, and a test that no tool lacks a case. Coverage 79.01% to 92.50% (gate full, Windows), floor 92; the baseline 18 to 14 entries, all in tests. Draft PR #26; review-code round 1 ([record](../reviews/2026-10-28-s7c-tool-tests-code.md)): clean, two minors fixed in `7cb8343` (three cases left loose, two coverage figures), and the client's retry rule now has tests. #27 opened: `test_22_01` fails on the first live run after Kit starts. S7 is done. |
| 2026-10-28 | S8 | S8 lands in two PRs: the extension's delivery first, then the plugin, its skills and the README rewrite, which use it. `2-s8-extension-install`: `omniverse-mcp extension install` copies the extension the wheel carries (a checkout's `extension/ovmcp.bridge` in an editable install) to `exts/ovmcp.bridge` in the user's data folder, made in the data folder outside `exts` and swapped in by renaming, the old one put back when the swap fails; `extension path` prints the folder. `extension` is routed by the first word, not as an argparse subcommand, which read a mistyped flag's value as an unknown command. The handshake's refusals name `uvx omniverse-mcp==X.Y.Z extension install` (from a checkout, `uv run --project <checkout> ...`) and say which side is older; a `protocol` that is not a number is an unexpected answer. Tests: from a checkout, from a wheel built by `uv build`, a replaced install, a failed swap. Coverage 92.82% to 93.29% (gate full, Windows), floor 93. Draft PR #28; review-code round 1 ([record](../reviews/2026-10-28-s8-extension-install-code.md)): clean, six minors fixed (a failed restore deleted the old copy, a checkout told to use uvx, an unquoted path, tests against git's index, a build that needed the network, a restart claim unverified on Linux); the install folder joins the one-way doors. Live on Isaac Sim 6.2 from the installed copy: as on `main`; on Windows a running Kit holds the folder, and the install says to quit it. Plan R2 settled with a probe plugin under `claude --plugin-dir`: Claude Code starts a plugin's stdio server in the project folder, with the user's environment, and expands `${CLAUDE_PLUGIN_ROOT}` and `${VAR:-default}` in its `args`. |
| 2026-10-28 | S8 | #28 (extension install) merged as `11a4667`. `2-s8-plugin`, the second half: `.claude-plugin/marketplace.json` lists one plugin from `./plugin`; `plugin/.claude-plugin/plugin.json`; `plugin/.mcp.json` starts `uvx omniverse-mcp==0.1.0` under the key `omniverse`; five skills, `setup` and the workflows of the old AI guide split as `scene`, `geometry`, `simulate` and `script`, every pitfall moved into one, each pre-approving read-only tools only. The gate's new `plugin` check (quick): the manifests agree, one version in `pyproject.toml`, `extension.toml`, `plugin.json` and every `omniverse-mcp==` pin under `plugin/`, each skill's frontmatter and `allowed-tools` against the tool contract's `readOnlyHint`, each skill listed in `plugin/README.md`, then `claude plugin validate --strict` on the plugin and the marketplace (it reads no skill frontmatter, so the gate does); CI's `Checks (Linux)` installs Claude Code 2.1.285 and sets `GATE_REQUIRE_CLAUDE=1`. write-skill covers plugin skills. `docs/AI_GUIDE.md` is the context for other clients and links to the skills; the README puts the plugin first, then `uvx`, then a clone. End to end with `claude -p --plugin-dir` on a copy whose server came from the branch's wheel, against Isaac Sim 6.2 on port 8212: `/omniverse-mcp:setup` started the server through uvx, called `get_sim_state` without a prompt and reported the stage; without the skill the same call waited for a grant. Draft PR #29; review-code ([record](../reviews/2026-10-28-s8-plugin-code.md)) round 1: needs-fixes, one major (setup stopped as soon as `get_sim_state` answered, so after an update on the same protocol Kit kept the old extension) and nine minors; `get_sim_state` now reports the extension's release and a `note` when it differs from the one the server carries, and setup reads it. Round 2: clean, six minors fixed. #6, #7 and #27's family as on `main` live. |
| 2026-10-29 | S8b | #29 (the plugin) merged as `1df5b71`. Capturing the README's images on Isaac Sim 6.2 found two bugs, each fixed in its own PR first: `set_material`'s OmniPBR shader named no MDL source and rendered Kit's red error material (#30, #31 merged as `c0c2957`), and every capture could return the previous capture's image, since Kit 110 writes the file after it says the capture is done (#32, PR #33). Playing physics with the Franka hung Kit, as #5 says of the G1, so the arm stays in its default pose. `2-s8b-presentation`: the README's hero (the logo, a `capture_viewport` frame beside its segmentation, an `inspect_prim` orbit of the workcell), `docs/images/` with a README saying how each image was made, the plugin's icon (the gate allows it), and `docs/images/social-preview.png` for the maintainer to upload. Every capture is the tool's own output, cropped only. For S9: PyPI renders the README too, where its relative images and links break. |
| 2026-10-29 | S9 | #34 (S8b) merged as `44d55fa`; the maintainer uploaded the social preview and registered the pending trusted publisher. S9 lands in two PRs, the release machinery, then the `0.2.0` release PR and its tag. `2-s9-release-workflow`: `release.yml` (on a `v*` tag: the tag on `main`, `tools/release.py check` for the tag, every version and a dated changelog section, the build checked with twine, check-wheel-contents and `release.py wheel`, a green `ci.yml` run on the tagged commit, then the `pypi` environment's approval, trusted publishing with attestations, and the GitHub release with the changelog section, the wheel, the sdist and a zip of the extension); `ci.yml`'s `Package (Linux)` builds and checks the same on every PR and keeps the wheel; `docs/releasing.md`; and #36, PyPI's README with absolute images and links through hatch-fancy-pypi-readme. R9 accepted by the maintainer. |
| 2026-10-29 | S9 | #37 (the release machinery) merged as `9ddbfdd`, closing #36. `2-release-0.2.0`, the release PR: `0.2.0` in `pyproject.toml`, `extension.toml`, `plugin.json` and every pin under `plugin/`, `uv.lock`, CHANGELOG's Unreleased dated `## 0.2.0 (2026-10-29)` under a new empty Unreleased, and the README's lines true only before 0.2.0 dropped, so PyPI's description doesn't keep them. `release.py check v0.2.0` passes. |
| 2026-10-29 | S9 | #38 (the release PR) merged, and `v0.2.0` tagged. GitHub showed two authors on the merge: the branches were committed as `serio <serio@SERIONIST-PC>`, an identity no account claims, so every squash merge since #14 carried a `Co-authored-by` trailer for it. Before anything was published, on the maintainer's word: the release run cancelled, `main`'s 16 commits from #14 rewritten without the trailer (every tree, author and date unchanged), `main` force-pushed by the maintainer (`8ae5a56` to `44fbffe`) and `v0.2.0` moved onto it. The commit IDs in this plan and the review records are the new ones. Branches now commit as `serionist`. The second release run: CI green on `44fbffe`, the maintainer's approval, `omniverse-mcp 0.2.0` on PyPI with attestations naming `44fbffe`, and the GitHub release with the notes, the wheel, the sdist and `ovmcp.bridge-0.2.0.zip`. `uvx omniverse-mcp==0.2.0` runs from PyPI, and PyPI's page shows the README's images and badges. S9 is done. |
| 2026-10-29 | after S9 | The maintainer asked for every open bug fixed before announcing, in parallel worktrees. Merged: #44 (#39, the README and user docs), #46 (#45, a macOS-flaky test), #47 (#41, #43, the output folder), #48 (#40, `create_robot` with a USD file), #49 (#6, the scenario suite's up axis), #52 and #59 (#25: `start_recording`'s warning; `apply_force` through PhysX), #53 (#7, `draw_debug` headless), #55 (#27, #35, bounded capture waits), #56 (#5, #50: a robot's first play deadlocked Kit through the bridge's own `omni.log` consumer, proven live with a thread dump; `get_logs` reads Kit's log file). Three plans, each approved after two or three review-plan rounds. Isaac Sim 5.1 can't start on this machine, so 5.x stays untested live. Open: #51, #54, #57, #58, and #25's recording camera and size. `60-release-0.2.1`, the release PR. |
| 2026-10-29 | S10 | 0.2.1 published; #62 (PyPI's page doubled the README's in-page anchors) fixed in #63. #64 starts S10: `server.json` names the server `io.github.serionist/omniverse-mcp` in the official MCP registry, and the README's `mcp-name:` comment lets the registry trust the PyPI package; the gate and `release.py check` hold `server.json`'s versions to the release's, `release.py wheel` refuses a README without the marker, `ci.yml`'s package job runs `mcp-publisher validate` (v1.8.1, its Sigstore bundle verified), and `release.yml` publishes after PyPI through GitHub's OIDC, with no token. `release.py notes` ends each release's notes with the install lines. 0.2.1's README on PyPI has no marker, so the first entry comes with 0.2.2; the awesome-mcp lists follow it. |
| 2026-10-29 | S10 | #65 merged as `aa23436`. #66, the 0.2.2 release PR: `0.2.2` in every place the gate names, `server.json`'s two among them, `uv.lock`, and CHANGELOG's Unreleased dated `## 0.2.2 (2026-10-29)`. Its tag's `registry` job publishes the first entry; then the awesome-mcp lists. |
| 2026-10-30 | S10 | 0.2.2 published, and the official MCP registry lists it. Listings: mcpservers.org approved; Glama approved and claimed (#72 adds `glama.json` and the badges); punkpeye's awesome-mcp-servers PR #18049 waits for its maintainers; appcypher's list is archived. Every open bug fixed, each with a plan or a review and a live run: #73 (#57), #74 (#58), #75 (#25), #80 (#51). Glama's per-tool critiques led to #83 (#78, every description rewritten) and #84 (#79, `open_scene`); the rewrite found #81, fixed in #86. #87, the 0.2.3 release PR. Open: #82 (six smaller bugs, for 0.2.4), #85, #76, #77 (tool consolidation, for 0.3.0), #54, #68. |
| 2026-11-01 | S10 | 0.2.3 published (#88). Since: #89 (#85, `save_scene` keeps off the stage's other files), #91 (#82, twelve tools do what their answers say), #92 (#90, no box behind the camera), #93 (#76, no viewport sensor at startup), #94 (#54, a hung Kit ends the live run, #54 left open for NVIDIA's hangs), #95 (#68, `apply_force` under the Direct GPU API), #96 (#77, four pairs of tools merged, 42 to 38: the tool contract's first change, so 0.3.0). #97, the 0.3.0 release PR. The maintainer: no backward compatibility with older extensions is needed yet. Open: #64 (listings), #54. |

## For the maintainers

- **S0, git:**
  - approve the force push of `main`;
  - open the issue;
  - on this machine, `git config --global --add safe.directory D:/workspaces/omniverse-mcp` (the folder belongs to the
    `Work` account).
- **S5, PyPI:** a pending trusted publisher for `omniverse-mcp` (this repo, `release.yml`, environment `pypi`), so
  the first release can publish. It doesn't reserve the name: only the first upload does (R9).
- **S5, the merge rules:** applied by the main session through the GitHub API on 2026-10-28, on the maintainer's
  "apply all" (D16):
  - the ruleset `main` (id 26045633) on `main`: no deletion, no force push, PRs only with squash, and two required
    checks: `CI` (`ci.yml`'s last job, which fails when `Checks (Linux)` or any `Tests (...)` leg failed) and
    `PR text` (`pr-text.yml`, skipped as passed on Dependabot's PRs); the repo's admins may bypass it;
  - squash merges only, with the commit message set to the PR title and description; a Dependabot PR's message is
    cut to its title and a line naming what moved, by `dependabot-auto-merge.yml` for a minor or patch, by the
    maintainer at merge for a major;
  - auto-merge allowed, and merged branches deleted;
  - CodeQL's default setup stays off: `codeql.yml` is the advanced setup, and the two would conflict. Its jobs,
    `Analyse (python)` and `Analyse (actions)`, annotate the PR without being required.
- **For S9, any time before it:**
  - the `pypi` environment, with you as required reviewer;
  - a ruleset on `v*` tags.
- **S5, GitHub security settings:**
  - private vulnerability reporting, which `SECURITY.md` and the issue forms link to: until it is on, nobody outside
    can report through that link;
  - secret scanning with push protection: already on;
  - Dependabot alerts and security updates (version updates come from `dependabot.yml`, with no setting): still off,
    with private vulnerability reporting, until the maintainer says.
- **S5, the repo page:** a description and topics, done during S1 and S1b.
- **S9:** approve the `pypi` deployment of each release: done for `0.2.0`.

## Later

- NVIDIA's extension registry.
- Inline images for the other image tools (`inspect_prim`, `get_recording_frame`); `capture_viewport` has them.
- Live-sim runs on a self-hosted GPU runner.
- The AI scenario suite as a skill.
- `1.0.0` once the tool contract has held for a few releases.
