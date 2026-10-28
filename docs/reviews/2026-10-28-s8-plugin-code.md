---
subject: "S8, the plugin: the Claude Code plugin, its skills and the README rewrite (PR #29)"
base: main (803b9da)
head: cd49e97
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; the major sent to its own fresh refuter)
verdict: clean (round 2)
---

# Review: S8, the plugin

Read from the pack (the scope diff), the touched files in full, the tool contract, the tool modules and handlers
behind every claim a skill makes, `kit_extension.py`, the server's instructions and the old `docs/AI_GUIDE.md`, with
CI's results on the head. One major, confirmed by a fresh refuter that reproduced it against the mock bridge, and nine
minors; all but F6 fixed in `eda5d3f`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `plugin/skills/setup/SKILL.md`, step 1 | The skill stopped as soon as `get_sim_state` answered. After a plugin update that kept the bridge protocol (the usual case), Kit still ran the old extension, the handshake doesn't refuse another release on the same protocol (plan Q2), and `get_sim_state` showed no version: setup said "done", while both READMEs told users that setup updates the extension. | Fixed: the client keeps the extension's version from each handshake; `get_sim_state` reports `extension_version` and `server_version`, and a `note` with the install command when they differ; setup's step 1 goes on to the install when they differ. `test_tools.py`'s `get_sim_state` case (a 1.0.0 extension) and `test_get_sim_state_says_nothing_more_when_the_extension_is_this_release`. |
| F2 | minor | setup step 4 | `ovmcp.bridge-0.1.0`, the version Kit prints, was not a pin the gate read, so a release bump would leave it stale. | Fixed: the gate's pin check reads `ovmcp.bridge-X.Y.Z` too; `test_the_plugin_check_finds[extension pin]`. |
| F3 | minor | `script` step 2; `setup` step 1; `scene` Traps | Skills said `get_sim_state` reports the Isaac Sim version, the stage, an `anon:` stage and when loading is done; it reports none of them. | Fixed: the app's version from the user or `isaacsim.core.version.get_version()`; setup reports the up axis, units and prim count; the two traps say what to do without a tool that doesn't exist. |
| F4 | minor | setup step 4; README Troubleshooting | "Cannot connect" is no message the tools give; a failed connection says "Kit app connection failed". | Fixed in both. |
| F5 | minor | setup | No path for a plugin server that never started (no `uv`, or a version not on PyPI): `get_sim_state` doesn't exist then. | Fixed: step 1's last case, `/mcp` for the error, `uv`'s install and a restart of Claude Code. |
| F6 | minor | the plan's R9; the marketplace on `main` | A pending trusted publisher doesn't reserve a name on PyPI; only the first upload does. From this merge the marketplace starts `uvx omniverse-mcp==0.1.0`, a version never published, and a squatter's upload would run for anyone who installed the plugin early. | Open, the maintainer's call: claim the name before 0.2.0, or accept the window until S9. R9 now says what does and doesn't reserve the name. |
| F7 | minor | README, Other MCP clients | It said copying `AI_GUIDE.md` gives the workflows and traps; the guide now holds the context and links to them. | Fixed: it says to copy the skills a project needs too. |
| F8 | minor | `plugin/README.md`; write-skill | "every tool that ... writes a file ... still asks you": `capture_viewport` and `dump_scene` are pre-approved and write under `mcp_output/`. | Fixed: "saves or exports a file", and the read-only tools' own output under `mcp_output/` said. |
| F9 | minor | write-skill, Plugin skills | "Gate quick checks all of it" while the gate checked neither full-URL links nor the AI guide's table. | Fixed: the gate checks both (`test_the_plugin_check_finds[relative link]`, `[AI guide]`), and write-skill names what it checks. |
| F10 | minor | `tools/gate.py`, `check_plugin` | The README listing, an unreadable manifest and the pass after Claude Code's validation had no test that failed without them. | Fixed: `test_the_plugin_check_finds[README]`, `[unreadable]`, `test_a_plugin_claude_validates_passes`. |

Refuted, each from the code:

- **`allowed-tools` can be fooled:** any entry but an exact read-only tool name fails `entry.removeprefix(prefix) in
  reads`; a `Bash(...)` rule with spaces is one entry (`_ALLOWED_ENTRY`); a YAML list fails rather than passes.
- **The frontmatter parser misreads an indented key:** it folds it into the block above, as YAML would, or refuses it.
- **`_PIN` matches a placeholder:** `<version>` starts no digit; a trailing `.` is excluded.
- **A skill pre-approves too much:** all 26 entries are `readOnlyHint` tools; none is `execute_script` or a shell
  command; `get_recording_frame` reads only its own frame and metadata files.
- **CI's new steps:** `setup-node` is pinned by SHA to v7.1.0, the workflow keeps `contents: read` and
  `persist-credentials: false`, Claude Code is pinned to 2.1.285, whose `--strict` passed in the Checks job.
- **The skills' other claims about tools:** `apply_force`'s default point, the overwrite refusals, `compare_prims`
  restoring the selection, the script-side `mcp` methods, a script error's last traceback lines, the install's
  refusal text, the README anchors and the `claude plugin` commands all match the code.
- **The harness is loosened:** repo skills still refuse `allowed-tools`; validation moved from full to quick, stricter.
- **A one-way door changes:** the plugin, the marketplace and the server key are D2's names, and the gate now holds
  them.

Not covered: kit-main-thread and bridge-security had nothing in scope. The reviewer ran no Claude Code session with
the plugin; the author's end-to-end runs stand in (below).

Improvements, all taken:

- **What the gate doesn't check could carry what it forbids** (commands, agents, hooks, more `plugin.json` keys): only
  `plugin.json`, `.mcp.json`, `README.md` and `skills/<name>/SKILL.md` may be under `plugin/`, and `plugin.json` only
  its listed keys; `test_the_plugin_check_finds[a hooks file]`, `[a manifest key]`.
- **`PLUGIN_DIR_NAME` named a plugin, not a folder:** `PLUGIN_NAME`, with the pin comment above `_PIN`.
- **`(#7)` in a skill:** a full URL, since the plugin is installed without the repo.
- **A shell's `PYTHONPATH` (Isaac Sim's conda setup sets one) would reach uvx's Python:** the plugin's server runs
  with `PYTHONPATH` empty, as the old README told conda users to set it. Not reproduced; harmless in the end-to-end run.
- **write-skill's Done means asked every skill for a Codex link:** a repo skill's, and a plugin skill's listings.

Also from the old guide: the last resort for a dark scene, a `DistantLight` or `DomeLight` made with `create_prim`,
is back in the `scene` skill.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for these runs from the extension `extension install` put in a
scratch data folder; the maintainer's own Isaac Sim on 8211 was not touched.

- **The live suites** on the fixes (the client and `get_sim_state` changed), `-k "not test_10_ and not test_14_"`
  (#5): the first run after Kit started, 109 passed with #6's two and #7's three failing; the second, 111 passed with
  #7's three failing. As on `main`.
- **The plugin end to end,** `claude -p --plugin-dir` on a copy of `plugin/` whose server came from the branch's wheel
  (`uvx --refresh --from <wheel> omniverse-mcp`, with the plugin's empty `PYTHONPATH`), from an empty project folder,
  with `OMNIVERSE_MCP_PORT=8212`: on `cd49e97`, `/omniverse-mcp:setup` started the server, called `get_sim_state`
  without a prompt and reported the stage, while without the skill the same call waited for a grant; on the fixes,
  it reported the extension's 0.1.0 equal to the server's and stopped as done.
- **Not shown:** the skill's update path against an older extension (the unit tests cover the text it reads), a
  machine that never had the extension, and the plugin installed from the marketplace on GitHub.

## Checks

`uv run tools/gate.py full` passed on `cd49e97` (647 tests, 93.34%) and on `eda5d3f` (656 tests, 93.32%), the
`plugin` check validated by Claude Code 2.1.312; CI's Checks job validated it with 2.1.285.

## Round 2

- **Where:** the fixes, `cd49e97..eda5d3f`, with round 1's findings; one fresh reviewer, on 2026-10-28.
- **Verdict:** clean. Every round-1 fix holds, each with its test (F3 to F5, F7 and F8 are prose). Six new minors,
  fixed in `9fa1ee6`, and checked in this session: no round 3 for minors.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F11 | minor | `plugin/skills/setup/SKILL.md` | Round 1's fix let the skill skip step 3 "when the folder is already on Kit's search path (an update)", a condition it can't see: a user whose Kit loads a clone's copy would install, skip step 3 (the only place that says to turn the old copy off), and loop. | Fixed: step 3 is skipped only when the install printed "in place of <version>"; step 4 sends a Kit that still loads another copy to step 3. Checked end to end. |
| F12 | minor | `tools/simulation.py`, `get_sim_state` | In a clone started with `--no-sync`, as the README configures, the package metadata keeps the last sync's version: after a pull across a release, `get_sim_state` reported a mismatch, and an install into a folder that Kit doesn't search. | Fixed: it compares Kit's version with the extension this server carries (`kit_extension.carried_version()`, the same string Kit reports); `server_version` stays for display. `test_get_sim_state_says_nothing_more_when_the_extension_is_this_release`. |
| F13 | minor | `tests/test_gate.py`, `test_the_plugin_check_finds` | The `extension pin` case named `0.1.0`, so the release bump would break it; with `GATE_REQUIRE_CLAUDE=1` exported its baseline failed. | Fixed: the case takes the release's version; the test clears the variable. |
| F14 | minor | `tools/gate.py`, `manifest_problems`, `check_plugin` | The marketplace's plugin entry may add hooks, commands or servers, and `.mcp.json`'s server was checked only for its key and a pin anywhere: `"hooks"` in the entry, or `"--from", "git+https://..."` in the args, passed. | Fixed: the entry holds only `name`, `source` and `description`, and the server is exactly `uvx omniverse-mcp==<version>` with `PYTHONPATH` empty; `[a marketplace key]`, `[a server argument]`, `[a server variable]`. |
| F15 | minor | the plan, For the maintainers | It still said the pending publisher keeps the name from being taken, against R9. | Fixed. |
| F16 | minor | write-skill | Step 4 lets a skill keep a file beside `SKILL.md`; the gate refuses any under `plugin/`. | Fixed: a plugin skill is `SKILL.md` alone, and write-skill says why. |

Refuted: `extension_version` stale across reconnects or Kit restarts (each new connection handshakes, a refusal
closes the connection); `PYTHONPATH` empty breaking anything (CPython ignores it; the end-to-end runs went through
it); a symlinked folder past the allowlist (`rglob` doesn't follow it, Claude Code refuses one leading out); S8b's icon
refused (by design: S8b adds its path and key); `_PIN` matching a non-version; the docs disagreeing with the code.

Improvements:

- **A client test for the refresh:** taken, `test_the_extension_version_follows_each_handshake`.
- **"Kit app connection failed" starts every failure,** a token or protocol refusal too: taken; setup step 4 says
  so and keys its last case on a refused or timed-out connection, as the README does.
- **List `plugin/` from git, so a stray `.DS_Store` doesn't fail the gate:** left: a tree outside git (the tests')
  would need a second path, and the message names the file to delete.

### Live run

On `9fa1ee6`, Isaac Sim 6.2.0 on port 8212 started again from the installed extension: the live suites' first run
after the start, 108 passed, with #6's two, #7's three and `test_13_camera_inspect_auto_fit` failing (a capture right
after Kit starts, as #27); the second, 111 passed with #7's three failing. `/omniverse-mcp:setup` end to end on a
fresh wheel: no `note`, so done, with the versions it read.

### Checks

`uv run tools/gate.py full` passed on `9fa1ee6`: 660 tests, 93.30%.
