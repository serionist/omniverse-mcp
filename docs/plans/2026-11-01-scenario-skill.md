---
title: Run the AI scenario suite as a skill
issue: "#102"
status: draft
approved_by:
approved_at:
---

# Run the AI scenario suite as a skill

A maintainer says "run the scenarios" and gets each scenario's status, compared with the last run. A repo skill,
`run-scenarios`, calls a script, `tools/scenarios.py`, which checks the Kit app (port 8212 unless told otherwise),
starts a headless Claude Code tester for each phase of `test_project/scenarios.md` with only this checkout's server and
the plugin's skills, collects the rows in a run folder outside git, and compares them by scenario ID. The session that
runs the skill holds only the summary.

## Goal

When this is done:

- **One request runs it:** `run-scenarios` ("run the scenarios", "run phase 15 on 8212", "the scenario run before the
  release") runs every phase, one phase or a range on a Kit app of its own, and reports PASS, FAIL, WARN and SKIP per
  scenario ID, with what changed since the last run.
- **The tester sees what a plugin user sees:** the server's tools and instructions, and the plugin's skills found by
  their descriptions, all from this checkout.
- **Results stay out of git:** one folder per run under the main checkout's `test_project/results/runs/`, which
  `.gitignore` already covers.
- **A release runs it:** `docs/releasing.md` gains the step.

Why, from #102: the pytest live suites check what the bridge does; the scenario suite checks what an agent gets from
the tools' descriptions, the skills and the answers. It runs rarely because starting it takes setup.

| In scope | Out of scope |
|---|---|
| The skill, `tools/scenarios.py` and its unit tests | Codex as the tester (Q4): its own issue |
| `test_project/`: the tester's rules move from `CLAUDE.md` to `AGENTS.md`; `scenarios.md` gains `Needs:` lines, run-folder paths and a header line (Q6, Q9, Q10) | Starting Kit from the script (Q3) |
| `AGENTS.md`, `CONTRIBUTING.md`, `docs/releasing.md`, `finish-work` (Q11), `write-skill` step 5, `.claude/settings.json` (Q13) | Rewriting the scenarios as tasks rather than calls (Q9): its own issue |
| | A plugin skill for users (Q1); changing `tests/test_scenarios.py`; a Kit app on another machine (loopback only); CI, which never runs Kit |

## What the code says

Read at `67a5069`.

| # | Finding | Where |
|---|---|---|
| F1 | The tester's rules: `CLAUDE.md` makes the client a tester, imports `docs/AI_GUIDE.md` and four plugin skills with `@` lines (Codex follows none), says to run in order, and writes `results/test_results.md`, with a retest flow that edits earlier notes in place | `test_project/CLAUDE.md:3-9`, `:21`, `:53-113` |
| F2 | pytest writes the same file: `TestScenarios.tearDownClass` overwrites `test_project/results/test_results.md` with its own table, and its recordings and dumps go to `results/` too. The file there now is pytest's: 121 test names | `tests/test_scenarios.py:226-236`, `:334`, `:842` |
| F3 | `test_project/results/`, `mcp_output/`, `test_project/.mcp.json` and `test_project/.claude/` are git-ignored | `.gitignore` |
| F4 | Seven calls give relative paths (`results/mcp_test_scene.usd`, `results/test_flatten_*`, `results/exported_cube*.usdc`). Kit exports to the path as given, so they land in Kit's own working folder, not in `test_project/results/`. 17.7 saves to `<a temp .usda>` and leaves the stage tied to it, as `test_17_07` does with a temp copy its cleanup deletes | `scenarios.md:540`, `:576`, `:619-637`; `handlers/scene.py:541`; `tests/test_scenarios.py:1902-1906` |
| F5 | The pytest twin covers phases 1 to 17 and 22 to 26 (its docstring). Its names have drifted from the IDs: `test_02_03_delete_prim` is 2.4, `test_10_03_invalid_robot` 10.4, `test_15_04_apply_force` 15.5. Read by title, 2.3, 2.7, 8.4, 8.5, 9.2, 10.3, 13.6 and 15.3 have no test inside the covered phases | `tests/test_scenarios.py:3`, `:419`, `:1026`, `:1375` |
| F6 | 144 headings `### N.M`, one of them `6.4 to 6.9`, in 27 phases `## Phase N:`. What a phase needs from earlier ones is only in prose (the header, Phase 18's note) | `scenarios.md:7-8`, `:586` |
| F7 | `/health` answers `stage_path` (the root layer's file, or `(unsaved)`) and `extension_version`; the token is per port, `bridge-<port>.token` | `handlers/misc.py:25-41`; `bridge_token.py:27-37` |
| F8 | The server reads `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT` and `OMNIVERSE_MCP_OUTPUT_DIR` (without it, `mcp_output/` in its working folder), and `OMNIVERSE_MCP_TOKEN` before the port's token file; an empty one counts as unset | `config.py:38-61`; `bridge_token.py:31-37` |
| F9 | A hung Kit ends a live run: a call that times out counts only when `/health` gives no answer in 20 s either (#54) | `tests/conftest.py:76-147` |
| F10 | Repo skills: `name` and `description` only, no Claude-only syntax, a Codex link written by `setup.py link`, named in `AGENTS.md`; gate quick checks each. A skill's scripts are standard library only (`write-skill` step 5). Plugin skills: `allowed-tools` names read-only tools only, and `plugin/` holds no file but its manifests and `SKILL.md`s | `write-skill`; `tools/gate.py:339-371`, `:428-455`, `:668-685` |
| F11 | `AGENTS.md` has 150 lines, the gate's cap. `.claude/settings.json`'s allows name whole commands, which a test holds them to | `tools/gate.py:287-290`; `tests/test_gate.py:1083-1089` |
| F12 | Claude Code 2.1.316 here has `-p`, `--mcp-config`, `--strict-mcp-config`, `--plugin-dir`, `--tools`, `--allowedTools`, `--permission-mode dontAsk`, `--setting-sources`, `--output-format stream-json`, `--max-budget-usd`, `--append-system-prompt`; `--bare` takes only an API key, not a claude.ai sign-in. It loads the `CLAUDE.md` of the working folder and of every parent at launch | `claude --help`; Context7, Claude Code's memory docs |
| F13 | Codex is not installed here. `codex exec` takes `-c mcp_servers.<name>...` overrides, `--ignore-user-config`, `--json` and `-o` | Context7, `openai/codex` |
| F14 | Live runs so far: the maintainer's Isaac Sim GUI on 8211, never touched; a headless Isaac Sim 6.2 on 8212, started by a command the maintainer approved, loading a copy of the branch's bridge; the plugin checked with `claude -p --plugin-dir` on a copy of `plugin/` whose `.mcp.json` runs the wheel | `docs/reviews/2026-10-28-s7b-tool-contract-code.md:58`; `docs/plans/2026-10-31-merge-overlapping-tools.md`, step 7; `docs/releasing.md`, step 2 |
| F15 | Each worktree has its own `test_project/results/`, removed with the worktree | `git worktree` |
| F16 | The main checkout's own `test_project/.mcp.json` (git-ignored) starts `isaac_sim_mcp` from a conda environment, a module this repo no longer has | local file |

## Design

### Where it lives (Q1)

A repo skill and a script, the tester in a process of its own.

| Part | What |
|---|---|
| `.claude/skills/run-scenarios/SKILL.md` | The recipe: scope, check, run, compare, report. Its steps are commands, so Claude Code and Codex agents both follow it |
| `tools/scenarios.py` | The deterministic part: `check`, `run` (with `--dry-run`), `compare`. It imports the server's client, as `tools/golden.py` does, so it needs `uv sync`; `write-skill` step 5 gains that exception for a script that drives the server or the bridge |

| Option | How the tester gets the tools | Context cost | Permissions | Codex |
|---|---|---|---|---|
| **A repo skill and a headless tester** (recommended) | `--plugin-dir` and `--mcp-config`, in a `claude -p` of its own | This session holds the summary; each tester holds one phase (Q7) | Pre-approved inside the tester alone, which has no shell | The skill is commands; the tester is Claude Code (Q4) |
| The server added to this session | `claude mcp add` or a `.mcp.json` entry, then a restart: Claude Code and Codex both read MCP servers at start | 38 tools' definitions in every later turn, and some 500 calls and answers in the session or a subagent; `scenarios.md` alone is 37 KB | Each edit asks, or `execute_script` is pre-approved in project settings for every session | Codex has no subagent with an MCP server of its own |
| A plugin skill | The plugin's server, at the released version, not the checkout | As above | `allowed-tools` read-only only (F10), so every edit asks | `plugin/` can't carry `scenarios.md` (F10), and the suite wipes the user's open stage |

### The Kit app (Q2, Q3)

`check` runs before every run, and `run` runs it again. It reaches Kit at `127.0.0.1` with the port's token file,
ignoring the shell's `OMNIVERSE_MCP_HOST` and `OMNIVERSE_MCP_TOKEN` (F8), as the tester's server does. It refuses unless
each rule holds, in this order:

| Rule | Why | Override |
|---|---|---|
| Port 8212 unless `--port` says otherwise; 8211 refused before any request or token read | 8211 is every Kit app's default and the maintainer's GUI | `--port 8211 --allow-port-8211`, only when the maintainer named the port |
| `/health` answers with that port's token | No Kit, no run | none |
| The stage is `(unsaved)`, a file under the runs folder, or a local path under the system temp folder that no longer exists | The suite wipes the stage (`new_scene`, deletes); any other stage, a URL's included, is someone's scene. The live suites leave the stage tied to a deleted `ovmcp-open-*` temp copy (F4) | `--any-stage`, on the maintainer's word |
| The bridge Kit loaded has this checkout's files: each file `git ls-files extension/ovmcp.bridge` lists, hashed by its relative path, against the same file in the folder Kit reports for `ovmcp.bridge` (one read-only `/execute`); caches ignored, an extra `.py` there named | A run tests this checkout's server and bridge together; a copy elsewhere is fine when equal (F14); Kit writes its own `__pycache__` | `--any-bridge` |
| No other run holds the port's lock, `runs/.lock-<port>` with its pid | Two runs on one stage | `run` alone takes over a lock whose pid is gone; `check` only reads it (I4 would drop the takeover) |

It prints the Kit app's name and version, the bridge's version and folder, the stage and its prim count.

**No Kit answering (Q3):** `check` prints what a Kit app for the run needs (started without its window, the bridge's
folder and `--enable ovmcp.bridge`, `--/exts/ovmcp.bridge/port=<port>`: `docs/SETUP.md`, Headless Kit and Ports) and
stops. The skill asks the maintainer, who starts Kit or tells the session to run the command they approved for it. The
skill never sets `OMNI_KIT_ACCEPT_EULA` (`AGENTS.md`, Build and test).

**A Kit that hangs mid-run:** `run` reads `/health` every 30 s with conftest's 20 s probe (F9). Only when no answer has
come for 140 s, counted from the start of the first probe that got none, longer than the server's 120 s call limit
plus one probe, does it stop the tester and the run, and `results.md` says "Kit stopped answering (#54)": a long
handler holds `/health` back too, so a shorter silence can be a call at work.

### Scope (Q6)

`--phases` takes `15`, `15-16` or `18-21,24`; every phase when left out. Phase 27, the cleanup, ends every run, at the
end of the last half asked: `--phases 15` runs no second half for it. 27.1 becomes stop, `new_scene()` and a check of
the tree, so its status doesn't depend on which phases ran, and the next run's stage rule passes.

- **`Needs:` lines.** Each phase in `scenarios.md` gets one line under its heading naming the scenario IDs whose prims
  or state it uses, or `Needs: none`. The IDs point back only. A draft, confirmed in step 3 as each phase is read again:

  | Phases | Needs |
  |---|---|
  | 1, 2, 9, 11, 17, 18, 24, 25, 27 | none |
  | 3, 4, 12, 13 | 2.1 |
  | 5, 6, 7, 8, 10, 16 | 2.1, 4.5 |
  | 14, 15 | 2.1, 4.5, 10.1 |
  | 19, 21, 23 | 18.2 |
  | 20, 22 | 18.1, 18.2 |
  | 26 | 23.2 |

- **Two halves.** A run splits where Phase 17 makes a new stage: phases 1 to 17, then 18 to 27. Each half asked starts
  with `new_scene()`, then runs its setup and its phases; no `Needs:` line crosses the split. So a Franka from 18.1
  never stands in Phase 15's way, and no prim from before 17 reaches Phase 23.
- **Resolution.** In each half the script adds each needed ID, and what that ID's phase needs in turn, when the run
  lacks it. Setup IDs and asked phases then run together in ID order, each group of setup IDs in a session of its own
  just before the first asked phase after them; their rows say `setup` in Notes. `--phases 2,5` runs `new_scene()`,
  Phase 2, setup 4.5, Phase 5, Phase 27. `--phases 15,20` runs `new_scene()`, setup 2.1, 4.5, 10.1, Phase 15; then
  `new_scene()`, setup 18.1, 18.2, Phase 20, Phase 27.

### The tester (Q4, Q5, Q7)

One headless Claude Code session per phase, and one per group of setup IDs, each in `test_project/` so its
`CLAUDE.md` (an import of `AGENTS.md`, Q10) loads. The command `run` builds, each flag to be confirmed in step 2; the
parts marked I1 go if the maintainer takes I1 (Plan review):

```
claude -p "<prompt>"
  --plugin-dir <config>/plugin
  --strict-mcp-config --mcp-config <config>/mcp.json
  --setting-sources project,local
  --tools Read,Grep,Glob,Skill,Write,Edit                       # Write,Edit: I1
  --permission-mode dontAsk
  --allowedTools mcp__plugin_omniverse-mcp_omniverse Read Grep Glob
                 "Skill(omniverse-mcp:<name>)", one for each of the plugin's five skills
                 "Write(<run>/phase-NN.md)" "Edit(<run>/phase-NN.md)"   # I1
                 [mcp__context7]                                 # Q12
  --output-format stream-json --verbose
  [--model <model>] [--max-budget-usd <amount>]
```

| Part | What it gives |
|---|---|
| `<config>` | A folder the script writes afresh for each session in the system's temp folder, outside the runs folder, and deletes after: nothing a tester writes reaches the next session's plugin, hooks or servers |
| `<config>/plugin` (Q5) | A copy of `plugin/` whose `.mcp.json` runs `uv run --no-sync --project <checkout> omniverse-mcp` with `OMNIVERSE_MCP_HOST=127.0.0.1`, `OMNIVERSE_MCP_PORT=<port>`, `OMNIVERSE_MCP_TOKEN=""` (the port's token file then), `OMNIVERSE_MCP_OUTPUT_DIR=<run>/mcp_output` and an empty `PYTHONPATH` (F8). Tool names as plugin users see them, the skills found by their descriptions, the server's instructions, as `docs/releasing.md` step 2 already checks the plugin |
| `--strict-mcp-config`, `<config>/mcp.json` | Only the run's servers: Context7 if Q12 keeps it, else none. If step 2 finds the strict flag drops a plugin's server too, the server moves into `mcp.json` and the copy keeps only the skills |
| `--setting-sources project,local` | No user settings: no user plugins (an installed omniverse-mcp at another version among them), hooks or user `CLAUDE.md` |
| `--tools`, `--permission-mode dontAsk`, `--allowedTools` | No shell and no web. Every omniverse tool, reading, and loading one of the plugin's five skills by name run without asking (`Skill(omniverse-mcp:<name>)`, in the form step 2 confirms); anything else is refused, never asked: another skill the session can see (Claude Code's own, one in the git-ignored `test_project/.claude/skills/`, a user's) could pre-approve its own tools, while the plugin's name only read-only ones (F10) |
| Rows (I1) | The tester writes its rows to `<run>/phase-NN.md`, the one file it may write. If I1 is taken, `Write` and `Edit` go, the prompt asks for the rows as a table in the session's last message, and the script writes `phase-NN.md` from it |
| `--output-format stream-json --verbose` | The transcript, `transcript-NN.jsonl`: every call the tester made and each answer |

- **Isolation, checked.** The stream's first event (`system`, `init`) lists the session's tools and MCP servers with
  their status. `run` stops the tester at once if a server other than the plugin's (and Context7, Q12) is there, if
  `omniverse` isn't connected, or if a tool outside the command's list is. The maintainer's own MCP servers (mail,
  chat) never reach a session whose tools are pre-approved.
- **Skill loads, counted.** The script reads each session's skill loads from its stream into `run.json`, and
  `results.md` and `compare` print them per session, "none" included: a run in which no tester loaded a skill shows
  as such, not as a clean PASS.
- **The prompt,** the same text for any client: the phase's text cut from `scenarios.md`; its `Needs:` line, with each
  needed ID's status so far in this run, so the tester can SKIP on a failed one; the run folder's absolute path, and
  `<run>/kit/` for the files Kit writes; the port; `new_scene()` first in a half's first session; and "write each row
  to `<run>/phase-NN.md` as soon as it is judged" (I1: "end with the rows as a table").
- **Limits.** Each session has 45 minutes, a constant set from the first full run's times (step 9); `--max-budget-usd`
  passes to each session, and `--budget` caps the run's total, summed from each session's `result` event.
- **The model:** the client's default, or `--model`. `run.json` records it, and `compare` names both when two runs
  differ.

### Results (Q8)

Runs live in the main checkout's `test_project/results/runs/` (the first entry of `git worktree list --porcelain`), so
every worktree's runs sit together and outlive the worktree (F15). One folder per run, `<YYYYMMDD-HHMMSS>`:

| File | Written by | Holds |
|---|---|---|
| `run.json` | the script | Commit, branch, whether the tree was clean, port, Kit app and version, bridge version and folder, the stage at the start, client and version, model, phases asked, IDs with setup, each session's start, end, exit, tokens, cost and skill loads |
| `phase-NN.md` | the tester (the script, under I1) | Its rows, `\| ID \| Test \| Status \| Notes \|`, and its issues; a FAIL or WARN names its capture under `mcp_output/` |
| `results.md` | the script | Run Info from `run.json`, the skill loads per session, every asked ID in order, `NOT RUN` where no row came, then the issues |
| `transcript-NN.jsonl` | the client | Each session's stream |
| `mcp_output/` | the server | Captures, recordings, dumps |
| `kit/` | Kit | The eight files the scenarios save or export (F4), at the `<run>/kit/...` paths the prompt gives |

Statuses: PASS, FAIL, WARN, SKIP from the tester (F1's meanings); NOT RUN from the script.

`uv run tools/scenarios.py compare [<run>] [--against <run>]` compares the newest run by default, each ID against the
newest earlier run with a tester status for it, or against `--against`. It lists regressions first (PASS or WARN to
FAIL, PASS to WARN), then fixes, other changes, new IDs and NOT RUN, each changed row with both notes and the earlier
run's folder, then the counts. It exits 1 on a regression.

```
Run 20261102-141000 (Phases 1-27, 144 IDs; main 67a5069; Isaac Sim 6.2.0 on 8212)
Regressions (1)
  6.3  PASS -> FAIL  "frames 160x120, no red: camera aimed past the cube"  (was PASS in 20261101-093000)
Fixed (0)   Other changes (0)   New (0)   Not run (2): 15.11, 15.14
Counts: 136 PASS, 4 WARN, 1 FAIL, 1 SKIP, 2 NOT RUN
Skills loaded: scene 9, simulate 6, script 4, geometry 2; none in 12 of 27 sessions
```

**Nothing of a run goes into git.** A PR that ran it quotes `compare`'s output in its testing section. The old flow's
ISS numbers, retest plan and in-place history (F1) go: `compare` keeps the history, and a retest is a run of the phases
concerned.

### Duplication with pytest (Q9)

Every phase runs by default. The tester judges what pytest's asserts can't: whether the image shows what the answer
says (3.2's aim, 12.8's colour, 22.5's isolation, 26's captures), whether an answer reads clearly, whether the skills
lead to the call. `scenarios.md` gains no per-scenario marks: the pytest names have drifted from the IDs (F5), so
marks would be kept by hand and drift too. One header line names the phases with no pytest twin, 18 to 21 and 27, which
`--phases 18-21` runs alone.

The scenarios spell out each call, so today's suite tests an agent following a script more than one choosing its
calls. A follow-up issue proposes scenarios written as outcomes ("put the cube on the ground and show it"), where the
suite measures what pytest can't.

### `test_project/` (Q10)

It stays where it is, and slims:

| File | Change |
|---|---|
| `AGENTS.md` (new) | The tester's rules, for any client: the role; the statuses and what a row's notes hold; SKIP when a needed scenario's status, which the prompt gives, isn't PASS or WARN; every file a scenario saves or exports under `<run>/kit/`; the repo's rules for changing code, which load from the root too, don't apply to a tester. No `@` imports: the skills come from the plugin (Q5) |
| `CLAUDE.md` | `@AGENTS.md`, as the repo's own `.claude/CLAUDE.md` does |
| `scenarios.md` | `Needs:` lines; the eight file paths (the seven `results/` ones and 17.7's temp file) become `<run>/kit/...`; 27.1 becomes stop, `new_scene()` and a check of the tree; the header says how phases depend and which have no pytest twin, and drops the line on phases 24 to 26 "added after" |
| `.mcp.json.example` | Stays, for opening `test_project/` by hand in any client (`CONTRIBUTING.md` names it); such a run writes to a folder of its own under `results/runs/` |
| `results/` | Unchanged; pytest's files stay there (F2), and no tester writes `test_results.md` again |

Moving it to `tests/scenarios/` would change the paths in `.gitignore`, `pyproject.toml`, `tests/test_gate.py` and
`tests/test_scenarios.py` for nothing a run gains; inside the skill's folder, the tester's working folder would be
under `.claude/`, whose settings and skills are the developers'.

### The skill

`.claude/skills/run-scenarios/SKILL.md`, written with `write-skill`:

1. **Scope** from the request: phases, port (8212 unless the maintainer named one), model, budget.
2. **Check:** `uv run tools/scenarios.py check`, bare for 8212; `--port <port>` only for a port the maintainer named.
   A refusal is reported, and overridden only on the maintainer's word; no Kit, Q3's question.
3. **Run:** `uv run tools/scenarios.py run --phases <phases>` (and `--port`, as in step 2). A full run takes hours: run
   it in the background where the client can, else give the maintainer the command for a terminal of their own.
4. **Compare:** `uv run tools/scenarios.py compare`, bare for the newest run.
5. **Report:** the counts; each regression, FAIL and WARN with its note and evidence; for each FAIL, what the
   transcript shows the tester called. An issue for one only on the maintainer's word.

Done means `results.md` exists and the maintainer has `compare`'s summary. Never: port 8211 unless the maintainer named
it; start Kit or set `OMNI_KIT_ACCEPT_EULA` on its own; run beside the live suites or another session on the same Kit;
commit anything under `results/`; edit a finished run's files.

Whether `.claude/settings.json` allows the bare `check` and `compare` is Q13: an allow widens a permission
(`REVIEW.md`, The harness). With or without it, a form with flags and every `run` ask, as `run` drives Kit and spends
tokens.

### Where a run fits (Q11)

- **`docs/releasing.md`, step 2:** a full run on the release's checkout, on the Kit app the live suites used, compared
  with the previous release's run (`--against`); each regression fixed or explained in the release PR.
- **`finish-work`, step 3:** one sentence. A change to a tool's description, the server's instructions or a plugin
  skill runs the phases that use them, when a Kit app runs on 8212, and the PR says whether it did.

### `AGENTS.md` within 150 lines

Four edits in place, no line added (F11):

| Line | Becomes |
|---|---|
| `test_project/` row | `an MCP client project for the AI scenario suite: AGENTS.md (the tester's rules), scenarios.md; runs land in results/runs/` |
| `tools/` row | adds `scenarios.py` (the AI scenario runs: `check`, `run`, `compare`; imports the server, as `golden.py` does) |
| live suites row, Build and test | adds `; the AI scenarios: uv run tools/scenarios.py run (run-scenarios)` |
| the skills sentence, How a change lands | `... finish-work (5); write-skill writes or fixes a skill, run-scenarios runs the AI scenarios.`, rewrapped within its two lines |

## Compatibility

None of the one-way doors (`AGENTS.md`): no tool, no console script flag, no new `OMNIVERSE_MCP_*` variable (the
script sets the server's existing two for the tester's server), no extension setting, no protocol change; the
tester's server writes the usual output layout under the run folder.

- **Maintainers:** `test_project/CLAUDE.md` becomes an import of `AGENTS.md`, and a run by hand writes to its own
  folder under `results/runs/`, no longer `results/test_results.md`, which stays pytest's. The main checkout's own
  `test_project/.mcp.json` (F16) is ignored by the strict run and can go.
- **Users:** nothing changes; no CHANGELOG line.

## Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Where the skill lives: a repo skill whose script runs a headless tester; the server added to this session; or a plugin skill for users? | The repo skill and a headless tester: the session's context holds only the summary, the tester's pre-approvals stay inside it, and the steps are commands any agent can follow. The second needs a restart and fills the session; the third tests the released server, can't carry the scenarios and would wipe users' stages | open |
| Q2 | The Kit app: 8212 by default with 8211 refused unless the maintainer names it, plus the stage and bridge rules; 8211 never; or the port rule alone? | 8212, 8211 behind `--allow-port-8211`, and the stage and bridge rules: the port is a convention, while an unsaved stage and the checkout's bridge files are facts `check` can read | open |
| Q3 | Starting Kit: the skill asks, and runs the maintainer's approved command on their word; a `kit` subcommand that starts a headless Isaac Sim with a copy of the bridge; or the skill starts Kit when the EULA variable is set? | Ask: Kit's launchers differ (the pip `isaacsim`, `isaac-sim.bat`, `python.sh` with `SimulationApp`), the maintainer already has an approved command, and the EULA is theirs. A `kit` subcommand is its own issue if starting Kit becomes the slow part | open |
| Q4 | The tester's client: Claude Code now and Codex in its own issue; both now; or whichever client runs the skill? | Claude Code now: Codex isn't installed here, so its path can't be proven live, and its MCP approvals in `exec` and its skill discovery (the repo's `.agents/skills`, the developers' skills) need their own look. The skill itself stays usable from Codex, which then starts a Claude tester | open |
| Q5 | What the tester is given: a run copy of `plugin/` on this checkout's server; today's `@` imports of `AI_GUIDE.md` and four skills with the server from `--mcp-config`; or both as two kinds of run? | The plugin copy: #102's question is whether the descriptions and skills lead an agent to the right calls, which needs the skills found by description as users find them. The imports put 20 KB of skills in every session up front and never test a skill's description | open |
| Q6 | Scope: phases with `Needs:` lines the script resolves; a range that always starts at phase 1 (or at 18 or 24); or every phase only? | `Needs:` lines: phase 15 alone costs three setup scenarios, not fourteen phases, and a unit test keeps every line pointing at real, earlier IDs | open |
| Q7 | Sessions: one per phase; one per run, the client's compaction keeping it going; or one per block between stage resets (1-17, 18-23, 24-27)? | One per phase: the state lives in Kit, so a new session loses nothing a scenario needs; each context holds one phase; a stopped session ends one phase; a transcript per phase. The fixed prompt repeats 27 times, mostly a cache read when sessions follow each other. One session would hold some 500 calls, compacted several times | open |
| Q8 | Results: in the main checkout's `test_project/results/runs/`, in the running checkout's, or in the user's data folder; and nothing in git, or a dated record per release in `docs/reviews/`? | The main checkout's, nothing in git: runs from every worktree compare with each other and outlive the worktree; a run holds machine paths, images and transcripts that don't belong on `main`; a PR quotes `compare` | open |
| Q9 | Duplication with pytest: run all by default, one header line naming the phases with no twin, a follow-up issue for scenarios written as outcomes; mark each covered scenario and run the rest by default; or drop the covered scenarios? | Run all, the header line, the follow-up: the tester judges images and answers, which pytest can't; per-scenario marks would drift as the names already have (F5) | open |
| Q10 | `test_project/`: stays and slims (`AGENTS.md`, `CLAUDE.md` an import, `Needs:` lines); moves to `tests/scenarios/`; or moves into the skill's folder? | Stays and slims: four files name its paths, and the tester's working folder must not be under `.claude/` | open |
| Q11 | Where a run fits: every release (`docs/releasing.md` step 2) with an optional line in `finish-work`; releases only; or required in `finish-work` for a change to a description or a skill? | Every release, optional in `finish-work`: a release is when users meet the descriptions and skills; making it required needs a Kit app for every such PR, and hosted CI never runs one | open |
| Q12 | Context7 in the tester (round 1, P9): drop it; or keep it and accept by name that text from outside the repo can become code `execute_script` runs in Kit without asking, with the user's rights? The tester writes its own Kit code for 6.3, 15.6 to 15.8, 15.14, 15.15 and 17.4. Keeping it without pre-approving `execute_script` isn't an option: `dontAsk` would refuse it, and with it 27 scenarios: phases 4 and 25 whole, 6.3, 11.3, 16.6 to 16.9, 17.3, 17.4, 24.6 and the scripted setups of 15.6 to 15.8, 15.14 and 15.15 | Drop it: the run is unattended with code execution pre-approved, where outside text matters most, and a plugin user has no Context7 either (`plugin/.mcp.json` starts only `omniverse`). The cost: the script skill's "look the API up" can't be followed, so a guessed API may FAIL a scripted scenario, which its transcript shows | open |
| Q13 | `.claude/settings.json` (round 1, P10): allow the bare `uv run tools/scenarios.py check` and `uv run tools/scenarios.py compare`, named whole; allow `compare` only; or allow neither? | Allow both: each is fixed and read-only, `check` reaching only 8212 with one read-only `/execute` of the script's own code and only reading the lock (`run` alone takes a stale one over, unless I4 drops that), `compare` only reading run folders; every form with flags, and every `run`, still asks, so 8211 and the overrides never pass unseen | open |

## Steps

Each step passes `uv run tools/gate.py full`. The skill, `finish-work` and `write-skill` change through `write-skill`.

| Step | What | Proven by |
|---|---|---|
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | The CLI checked by hand, phase 1 on 8212 with a small budget: `--strict-mcp-config` with `--plugin-dir` (does the plugin's server load), `--setting-sources` (user plugins and `CLAUDE.md` gone, the repo's root `.claude/CLAUDE.md` loaded or not), `--tools` with `dontAsk`, the `init` event's fields, the skills the session lists (user skills gone or not), and a plugin skill loading under these exact flags: a prompt that needs one, and the allow form that names it. With I1 not taken, also `Write(<run>/phase-NN.md)` on Windows. The findings go into this plan's Design before any code | The findings table, in this plan; a transcript that shows the skill load |
| 3 | `scenarios.md`: `Needs:` lines, the `<run>/kit/` paths, 27.1's stop, `new_scene()` and tree check, the header. `tools/scenarios.py`: parsing, the halves and resolution, the run folder, the per-session config folder, the prompts with their `Needs:` statuses and command lines, and `run --dry-run`, which prints them without starting a tester | `tests/test_scenario_runs.py`: the real `scenarios.md` parses to 144 IDs in 27 phases; every `Needs:` ID exists, points back and stays in its half; `--phases 2,5` and `--phases 15,20` resolve to the examples under Scope |
| 4 | `check`: the port rule first, with no I/O; host and token pinned; the stage and bridge rules; the overrides, the lock, the printout | The same file, against `tests/mock_bridge.py`: each refusal and its override; no request and no token read for a refused 8211; the hash ignores `__pycache__` and names an extra `.py` |
| 5 | `run`: sessions in order, a fresh config folder for each, the `init` check, skill loads counted, the `/health` watch at 140 s, the limits, `run.json`, the merge into `results.md`. With I1 taken, the script also writes `phase-NN.md` from each session's last message | The same file, with a stub client (a Python script writing stream-json events, and a phase file unless I1): a foreign MCP server stops it; 140 s from the first unanswered probe ends the run, and a 120 s call that starts just before a probe doesn't; skill loads land in `run.json`; a phase with no rows gives NOT RUN; the budget stops the next session |
| 6 | `compare` | The same file, over fixture runs: regressions first, `--against`, the skill loads, exit 1 |
| 7 | `test_project/AGENTS.md`, `CLAUDE.md` as an import | Step 9's run reads them |
| 8 | The skill: `SKILL.md`, `uv run tools/setup.py link run-scenarios`, `AGENTS.md` in place, `write-skill` step 5's exception, `finish-work`, `docs/releasing.md`, `CONTRIBUTING.md`, and `.claude/settings.json` as Q13 says | `uv run tools/gate.py quick`: frontmatter, link, listing, 150 lines; `tests/test_gate.py` for the settings |
| 9 | Live, on Isaac Sim 6.2 headless on 8212 with this branch's bridge: `check` refusing a stage saved outside the runs folder and a bridge copy that differs (8211 is proven by step 4's unit test alone, never live); phase 1 alone; `--phases 15,20`; every phase; `compare` twice. The run's time and cost go into the skill, the per-session limit is set from them | The run folders, read by the session; skill loads above none; ten rows checked against their transcripts (Tests) |
| 10 | `finish-work` | The PR, with the full run's `compare` output |

## Tests

- **Unit, in CI:** `tests/test_scenario_runs.py`, as `tests/test_release.py` tests `tools/release.py`: parsing the real
  `scenarios.md`; the halves and resolution; `check` against the mock bridge, with no request for a refused port; the
  bridge hash; the command line `run` builds; the `init` check; skill loads; the health watch; the budget; NOT RUN; the
  merge; `compare`. `tools/` is outside the coverage floor's source, as the gate and `release.py` are.
- **Live, by hand:** step 9. `test_integration.py` and `test_scenarios.py` are unchanged; neither touches what this
  adds.
- **What neither shows:** whether the tester judges right. The session reads ten rows against their transcripts and
  evidence: every FAIL and WARN, and the PASS rows of 3.2, 12.8 and 22.5, which rest on an image. Whether a skill
  loads when it should, not only that some load: the counts show a run with none, not a wrong choice. Codex as the
  tester (Q4), and the path rules on Linux and macOS (gone with I1), stay untested.

## Docs

| File | Change |
|---|---|
| `AGENTS.md` | Four lines in place (Design) |
| `CONTRIBUTING.md` | The live suites section: one sentence naming `run-scenarios` and `test_project/AGENTS.md` |
| `docs/releasing.md` | Step 2's bullet (Q11) |
| `.claude/skills/finish-work/SKILL.md` | Step 3's sentence (Q11) |
| `.claude/skills/write-skill/SKILL.md` | Step 5: a script that drives the server or the bridge imports the server's package and needs `uv sync`, as `tools/scenarios.py` does |
| `.claude/settings.json` | Q13's allows, if any |
| `test_project/AGENTS.md`, `CLAUDE.md`, `scenarios.md` | Q10 |
| `CHANGELOG.md`, `README.md`, `docs/TOOLS.md`, `docs/ARCHITECTURE.md` | None: no user, tool, route or protocol change |

## Risks

| Risk | Status |
|---|---|
| The CLI's flags act otherwise than read: the strict flag and plugin servers, setting sources, a skill load, path rules on Windows | Resolved before code: step 2, its findings in this plan |
| No tester loads a skill, and a run still reports PASS (round 1, P1) | Resolved: step 2 proves a load under the run's flags; `run.json`, `results.md` and `compare` count loads per session |
| The maintainer's own MCP servers or plugins reach a tester whose tools are pre-approved | Resolved: strict MCP config, setting sources, and the `init` check that stops the tester |
| A tester rewrites the next session's plugin, servers or hooks, or an earlier phase's rows (P12) | Resolved: each session's config is written afresh outside the runs folder, and a tester may write only its own phase file (nothing at all under I1); only the plugin's skills load, and theirs pre-approve read-only tools alone |
| A run wipes a stage someone cares about | Resolved: port, stage and bridge rules; the override needs the maintainer's word |
| `execute_script` is pre-approved in the tester and runs Python in Kit with the user's rights, so "no shell" doesn't fence the machine. The tester writes its own code for 6.3, 15.6 to 15.8, 15.14, 15.15 and 17.4, so the code isn't only the repo's | Q12: with Context7 dropped, accepted as the live suites' code is, on the test Kit; with it kept, text from outside the repo can shape that code, accepted by name |
| The repo's developer rules load into the tester (the root's `.claude/CLAUDE.md` through parent discovery, if step 2 shows it does) | Accepted: the tester's `AGENTS.md` says they don't apply to it |
| The tester marks PASS without looking, or calls more than the scenario asks | Accepted, watched: one phase per session, transcripts kept, ten rows spot-checked in step 9 and the report naming the calls behind each FAIL |
| Time and cost unknown | Accepted: `run.json` records both, the skill states them after step 9, `--budget` caps a run |
| Kit hangs mid-run (#54) | Resolved: the `/health` watch ends the run 140 s after the first unanswered probe, longer than any call may take |
| The live suites, another session or two runs drive the same Kit | Partly: the lock stops two runs; the skill's Never covers the rest |
| `Needs:` lines drift from the scenarios | Partly: the unit test reads the real file, so each ID exists, points back and stays in its half; it can't see a scenario that starts using a prim its line doesn't name, which shows as a FAIL or SKIP in a partial run |
| The plugin copy's skills link to GitHub's `main`, not the branch | Accepted: the skills' text is the branch's; only their links lead to `main` |
| Two runs on different models compare as if alike | Accepted: `compare` names both models |

## Plan review

### Round 1

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `61dd1b0`. Not applied: the bridge-security, kit-main-thread
and tool-contract lenses, as none of those changes.

**Verdict:** `needs-fixes`: one major, twelve minors.

**Now:** all thirteen fixed in this plan, its design and scope kept. P9's call and P10's allow are Q12 and Q13. I1 to I8
wait on the maintainer; the parts I1 removes are marked I1, so taking it deletes them.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | Nothing proves a tester can load a plugin skill, so a release run could PASS with none loaded | fixed: `Skill` joins `--tools`, `--allowedTools` and the `init` list; step 2 proves a load under the run's flags; `run.json`, `results.md` and `compare` count loads per session |
| P2 | minor | The tester can't apply its SKIP rule: the prompt lacks the needed IDs' statuses | fixed: the prompt carries the phase's `Needs:` line with each needed ID's status so far; the tester SKIPs on one not PASS or WARN |
| P3 | minor | The stage rule refuses the stage the live suites leave, and 17.7's own file | fixed: a stage file that no longer exists passes; 17.7's file joins the seven under `<run>/kit/`; 27.1 ends with `new_scene()` |
| P4 | minor | The bridge hash doesn't say which files it covers; Kit's `__pycache__` would never match | fixed: the files `git ls-files extension/ovmcp.bridge` lists, by relative path, caches ignored, an extra `.py` named |
| P5 | minor | All setup ran first in one session, across 17's new stage: a Franka from 18.1 broke 15.16 and 16.1 | fixed: a run splits at 17 into two halves, each with `new_scene()`, its own setup and its phases; no `Needs:` line crosses the split |
| P6 | minor | The tester's server inherits `OMNIVERSE_MCP_HOST` and `OMNIVERSE_MCP_TOKEN` | fixed: the copy's server and `check` pin `127.0.0.1` and an empty token; F8 names both |
| P7 | minor | Step 9 aimed `check` at the maintainer's GUI | fixed: the port rule comes first with no I/O, step 4's unit test holds it, and step 9 no longer tries 8211 |
| P8 | minor | The `Needs:` risk claimed more than its test proves | fixed: Partly, with what the test can't see |
| P9 | minor | The `execute_script` risk was accepted for a reason that isn't true | fixed: the row names the scenarios whose code the tester writes; Context7 in the tester is Q12 |
| P10 | minor | The planned allows never match `check --port <port>` | fixed: the skill runs `check` and `compare` bare; the allow is Q13 |
| P11 | minor | `tools/scenarios.py` breaks `write-skill`'s standard-library rule | fixed: `write-skill` step 5 gains the exception (F10, Design, step 8, Docs) |
| P12 | minor | A tester could rewrite the next session's configuration, or earlier rows | fixed: each session's config is written afresh in a temp folder outside the runs folder; a tester may write only its own `phase-NN.md`, and nothing under I1 |
| P13 | minor | The hang watch could fire during a legitimate call | fixed: a run stops only after 140 s with no `/health` answer; step 5's test holds 100 s as not enough |

**Refuted:**

- The facts the plan cites hold: pytest's overwrite, the seven relative paths, the three name mismatches, 144
  scenarios in 27 phases. F5's no-test list also missed 2.3 and 13.6, now added.
- `AGENTS.md` has room: three edits are single rows, and the skills sentence fits its two lines.
- The plan ends with `review-code`: step 10 is `finish-work`, whose step 6 runs it.
- Other servers' tools can't be reached: `dontAsk` refuses tools not in `--allowedTools`, and the `init` check is a
  second layer.
- A fresh worktree has its environment: `uv run tools/scenarios.py` syncs it before the tester's server starts.
- The writing rules are kept.

**Improvements:**

| # | Improvement | Recommendation | Answer |
|---|---|---|---|
| I1 | Drop `Write` and `Edit` from the tester: the script writes `phase-NN.md` from the rows in each session's last message; captures land in `mcp_output/`, saves and exports are Kit's own writes | Take: it cuts the tester's writes, the Windows path-rule question and what is left of P12 together. The parts marked I1 go (the command, the Rows row, step 2's path check) and step 5's script writes the phase files | pending the maintainer |
| I2 | `--setting-sources project`, without `local`: `settings.local.json` may hold hooks or hand-granted allows | Take | pending the maintainer |
| I3 | One budget flag, `--budget`, for the run's total; each session gets what remains as its `--max-budget-usd`, a hard cap | Take, as long as it stays one flag | pending the maintainer |
| I4 | A simpler lock: refuse while the lock file exists and say how to clear it, with no pid check; `os.kill(pid, 0)` on Windows sends `CTRL_C_EVENT` | Take | pending the maintainer |
| I5 | `compare` exits non-zero when IDs are NOT RUN; `--against` takes a tag, the newest run at that commit | Take | pending the maintainer |
| I6 | Step 2 runs from inside a Claude Code session's shell, as the skill will, and the `init` check refuses claude.ai connectors (`claude_ai_*` servers) | Take | pending the maintainer |
| I7 | Before each session the script stops the timeline and any recording, which a killed session can leave running | Take | pending the maintainer |
| I8 | `scenarios.md` line 3 still points at `results/test_results.md` and `CLAUDE.md`'s format: rewrite it, and send the header with its axis rule in every phase's prompt | Take | pending the maintainer |

### Round 2

**How:** one fresh reviewer, Claude Opus, 2026-11-01, on `f1eb45f`.

**Verdict:** `approved`, with the owner calls Q1 to Q13 and I1 to I9 pending. P1 to P13 are closed. Five new minors,
all fixed in this plan; Q12 and Q13 restated.

| # | Sev | Finding | Status |
|---|---|---|---|
| P14 | minor | A half's setup ran before the asked phases it depends on: `--phases 2,5` ran 4.5 on an empty stage, and Phase 5 SKIPped | fixed: setup IDs and asked phases run together in ID order, each setup group just before the first asked phase after it; step 3 tests `--phases 2,5` |
| P15 | minor | The 140 s ran from the last answer, not from when Kit went quiet | fixed: counted from the start of the first unanswered probe; step 5 tests a 120 s call that starts just before a probe |
| P16 | minor | "A file that no longer exists" also passed a stage opened from a URL | fixed: a missing file passes only as a local path under the system temp folder; anything else needs `--any-stage` |
| P17 | minor | A bare `Skill` pre-approved every skill the tester can see, whose `allowed-tools` could open writes | fixed: the allow names the plugin's five skills; step 2 records which skills the session lists |
| P18 | minor | 27.1's fixed delete list made its status depend on which phases ran | fixed: 27.1 becomes stop, `new_scene()` and a check of the tree; 27 runs at the end of the last half asked, with no second half of its own |

Q12 now counts the 27 scenarios `dontAsk` would refuse, and says a plugin user has no Context7 either. Q13 says `run`
alone takes over a stale lock and `check` only reads it.

**Refuted:**

- A plugin skill running hooks or `!` commands: the gate allows plugin skills only `name`, `description` and read-only
  `allowed-tools` (`tools/gate.py:67`, `:373-386`).
- The temp config folder on Windows: it holds no secret (the empty token reads the port's file), its name is new each
  session, and a failed delete leaves a stray folder, not a wrong run.
- Writes through `execute_script`, `save_scene` or `flatten_usd`: Q12's risk already.
- The halves against the `Needs:` lines: every row stays in its half.
- 140 s against the 45-minute session limit and the budget: no conflict.
- Q13's allow shape: an exact rule passes `test_every_allow_is_exact_or_a_swept_command`.

**Improvement:**

| # | Improvement | Recommendation | Answer |
|---|---|---|---|
| I9 | On Windows, stop a tester by ending its whole process tree (`taskkill /T /F` or a job object), and wait for it before deleting its config folder (ignoring delete errors) and starting the next session: `Popen.kill` ends only `claude.exe`, and its server's call in Kit can run up to 120 s into the next phase | Take | pending the maintainer |
