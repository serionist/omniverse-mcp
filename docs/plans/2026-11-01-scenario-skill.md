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
| `AGENTS.md`, `CONTRIBUTING.md`, `docs/releasing.md`, `finish-work`, `.claude/settings.json` (Q11) | Rewriting the scenarios as tasks rather than calls (Q9): its own issue |
| | A plugin skill for users (Q1); changing `tests/test_scenarios.py`; a Kit app on another machine (loopback only); CI, which never runs Kit |

## What the code says

Read at `67a5069`.

| # | Finding | Where |
|---|---|---|
| F1 | The tester's rules: `CLAUDE.md` makes the client a tester, imports `docs/AI_GUIDE.md` and four plugin skills with `@` lines (Codex follows none), says to run in order, and writes `results/test_results.md`, with a retest flow that edits earlier notes in place | `test_project/CLAUDE.md:3-9`, `:21`, `:53-113` |
| F2 | pytest writes the same file: `TestScenarios.tearDownClass` overwrites `test_project/results/test_results.md` with its own table, and its recordings and dumps go to `results/` too. The file there now is pytest's: 121 test names | `tests/test_scenarios.py:226-236`, `:334`, `:842` |
| F3 | `test_project/results/`, `mcp_output/`, `test_project/.mcp.json` and `test_project/.claude/` are git-ignored | `.gitignore` |
| F4 | Seven calls give relative paths (`results/mcp_test_scene.usd`, `results/test_flatten_*`, `results/exported_cube*.usdc`). Kit exports to the path as given, so they land in Kit's own working folder, not in `test_project/results/` | `scenarios.md:540`, `:619-637`; `handlers/scene.py:541` |
| F5 | The pytest twin covers phases 1 to 17 and 22 to 26 (its docstring). Its names have drifted from the IDs: `test_02_03_delete_prim` is 2.4, `test_10_03_invalid_robot` 10.4, `test_15_04_apply_force` 15.5. Read by title, 2.7, 8.4, 8.5, 9.2, 10.3 and 15.3 have no test inside the covered phases | `tests/test_scenarios.py:3`, `:419`, `:1026`, `:1375` |
| F6 | 144 headings `### N.M`, one of them `6.4 to 6.9`, in 27 phases `## Phase N:`. What a phase needs from earlier ones is only in prose (the header, Phase 18's note) | `scenarios.md:7-8`, `:586` |
| F7 | `/health` answers `stage_path` (the root layer's file, or `(unsaved)`) and `extension_version`; the token is per port, `bridge-<port>.token` | `handlers/misc.py:25-41`; `bridge_token.py:27-37` |
| F8 | The server reads `OMNIVERSE_MCP_PORT` and `OMNIVERSE_MCP_OUTPUT_DIR`; without the second it writes `mcp_output/` in its working folder | `config.py:38-61` |
| F9 | A hung Kit ends a live run: a call that times out counts only when `/health` gives no answer in 20 s either (#54) | `tests/conftest.py:76-147` |
| F10 | Repo skills: `name` and `description` only, no Claude-only syntax, a Codex link written by `setup.py link`, named in `AGENTS.md`; gate quick checks each. Plugin skills: `allowed-tools` names read-only tools only, and `plugin/` holds no file but its manifests and `SKILL.md`s | `write-skill`; `tools/gate.py:339-371`, `:428-455`, `:668-685` |
| F11 | `AGENTS.md` has 150 lines, the gate's cap | `tools/gate.py:287-290` |
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
| `tools/scenarios.py` | The deterministic part: `check`, `run` (with `--dry-run`), `compare`. It imports the server's client, as `tools/golden.py` does, so it needs `uv sync` |

| Option | How the tester gets the tools | Context cost | Permissions | Codex |
|---|---|---|---|---|
| **A repo skill and a headless tester** (recommended) | `--plugin-dir` and `--mcp-config`, in a `claude -p` of its own | This session holds the summary; each tester holds one phase (Q7) | Pre-approved inside the tester alone, which has no shell | The skill is commands; the tester is Claude Code (Q4) |
| The server added to this session | `claude mcp add` or a `.mcp.json` entry, then a restart: Claude Code and Codex both read MCP servers at start | 38 tools' definitions in every later turn, and some 500 calls and answers in the session or a subagent; `scenarios.md` alone is 37 KB | Each edit asks, or `execute_script` is pre-approved in project settings for every session | Codex has no subagent with an MCP server of its own |
| A plugin skill | The plugin's server, at the released version, not the checkout | As above | `allowed-tools` read-only only (F10), so every edit asks | `plugin/` can't carry `scenarios.md` (F10), and the suite wipes the user's open stage |

### The Kit app (Q2, Q3)

`check` runs before every run, and `run` runs it again. It refuses unless each rule holds:

| Rule | Why | Override |
|---|---|---|
| Port 8212 unless `--port` says otherwise; 8211 refused | 8211 is every Kit app's default and the maintainer's GUI | `--port 8211 --allow-port-8211`, only when the maintainer named the port |
| `/health` answers with that port's token | No Kit, no run | none |
| The stage is `(unsaved)`, or a file under the runs folder | The suite wipes the stage (`new_scene`, deletes); a saved stage elsewhere is someone's scene | `--any-stage`, on the maintainer's word |
| The bridge Kit loaded has this checkout's files: the folder Kit reports for `ovmcp.bridge` (one read-only `/execute`) hashed against `extension/ovmcp.bridge/` | A run tests this checkout's server and bridge together; a copy elsewhere is fine when equal (F14) | `--any-bridge` |
| No other run holds the port's lock, `runs/.lock-<port>` with its pid | Two runs on one stage | A lock whose pid is gone is taken over |

It prints the Kit app's name and version, the bridge's version and folder, the stage and its prim count.

**No Kit answering (Q3):** `check` prints what a Kit app for the run needs (started without its window, the bridge's
folder and `--enable ovmcp.bridge`, `--/exts/ovmcp.bridge/port=<port>`: `docs/SETUP.md`, Headless Kit and Ports) and
stops. The skill asks the maintainer, who starts Kit or tells the session to run the command they approved for it. The
skill never sets `OMNI_KIT_ACCEPT_EULA` (`AGENTS.md`, Build and test).

**A Kit that hangs mid-run:** `run` reads `/health` every 30 s; three misses in a row at conftest's 20 s probe (F9) stop
the tester and the run, and `results.md` says "Kit stopped answering (#54)".

### Scope (Q6)

`--phases` takes `15`, `15-16` or `18-21,24`; every phase when left out. Phase 27, the cleanup, ends every run.

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

- **Resolution.** The script adds each needed ID, and what that ID's phase needs in turn, when the run lacks it, and
  runs them first in ID order as a setup session; their rows say `setup` in Notes. `--phases 15` runs 2.1, 4.5 and
  10.1, then Phase 15, then 27.
- **A new stage first.** The first session of a run starts with `new_scene()`, as `CLAUDE.md` says today; that is why
  Phase 18 needs nothing.

### The tester (Q4, Q5, Q7)

One headless Claude Code session per phase, plus one for setup, each in `test_project/` so its `CLAUDE.md` (an import
of `AGENTS.md`, Q10) loads. The command `run` builds, each flag to be confirmed in step 2:

```
claude -p "<prompt>"
  --plugin-dir <run>/plugin
  --strict-mcp-config --mcp-config <run>/mcp.json
  --setting-sources project,local
  --tools Read,Grep,Glob,Write,Edit
  --permission-mode dontAsk
  --allowedTools mcp__plugin_omniverse-mcp_omniverse mcp__context7 Read Grep Glob "Write(<run>/**)" "Edit(<run>/**)"
  --output-format stream-json --verbose
  [--model <model>] [--max-budget-usd <amount>]
```

| Part | What it gives |
|---|---|
| `<run>/plugin` (Q5) | A copy of `plugin/` whose `.mcp.json` runs `uv run --no-sync --project <checkout> omniverse-mcp` with `OMNIVERSE_MCP_PORT=<port>`, `OMNIVERSE_MCP_OUTPUT_DIR=<run>/mcp_output` and an empty `PYTHONPATH`. Tool names as plugin users see them, the skills found by their descriptions, the server's instructions, as `docs/releasing.md` step 2 already checks the plugin |
| `--strict-mcp-config`, `<run>/mcp.json` | Only the run's servers: the repo's Context7 entry, which the script skill points at. If step 2 finds the strict flag drops a plugin's server too, the server moves into `mcp.json` and the copy keeps only the skills |
| `--setting-sources project,local` | No user settings: no user plugins (an installed omniverse-mcp at another version among them), hooks or user `CLAUDE.md` |
| `--tools`, `--permission-mode dontAsk`, `--allowedTools` | No shell and no web; every omniverse tool and file writes inside the run folder run without asking; anything else is refused, never asked |
| `--output-format stream-json --verbose` | The transcript, `transcript-NN.jsonl`: every call the tester made and each answer |

- **Isolation, checked.** The stream's first event (`system`, `init`) lists the session's tools and MCP servers with
  their status. `run` stops the tester at once if a server other than the plugin's and Context7 is there, if
  `omniverse` isn't connected, or if a tool outside the list is. The maintainer's own MCP servers (mail, chat) never
  reach a session whose tools are pre-approved.
- **The prompt,** the same text for any client: the phase's text cut from `scenarios.md`, the run folder's absolute
  path, the port, `new_scene()` first for the first session, and "write each row to `<run>/phase-NN.md` as soon as it
  is judged".
- **Limits.** Each session has 45 minutes, a constant set from the first full run's times (step 9); `--max-budget-usd`
  passes to each session, and `--budget` caps the run's total, summed from each session's `result` event.
- **The model:** the client's default, or `--model`. `run.json` records it, and `compare` names both when two runs
  differ.

### Results (Q8)

Runs live in the main checkout's `test_project/results/runs/` (the first entry of `git worktree list --porcelain`), so
every worktree's runs sit together and outlive the worktree (F15). One folder per run, `<YYYYMMDD-HHMMSS>`:

| File | Written by | Holds |
|---|---|---|
| `run.json` | the script | Commit, branch, whether the tree was clean, port, Kit app and version, bridge version and folder, the stage at the start, client and version, model, phases asked, IDs with setup, each session's start, end, exit, tokens and cost |
| `phase-NN.md` | the tester | Its rows, `\| ID \| Test \| Status \| Notes \|`, and its issues |
| `results.md` | the script | Run Info from `run.json`, every asked ID in order, `NOT RUN` where no tester wrote a row, then the issues |
| `transcript-NN.jsonl` | the client | Each session's stream |
| `mcp_output/` | the server | Captures, recordings, dumps |
| evidence | the tester | Saved scenes and exports (F4), captures for each FAIL or WARN (`fail_18_1_mesh_stats.png`) |

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
| `AGENTS.md` (new) | The tester's rules, for any client: the role; the statuses and what a row's notes hold; SKIP when a needed scenario failed; every file a scenario writes, and the evidence, under the run folder the prompt names; no file outside it; the repo's rules for changing code, which load from the root too, don't apply to a tester. No `@` imports: the skills come from the plugin (Q5) |
| `CLAUDE.md` | `@AGENTS.md`, as the repo's own `.claude/CLAUDE.md` does |
| `scenarios.md` | `Needs:` lines; the seven `results/` paths become `<run>/...`; the header says how phases depend and which have no pytest twin, and drops the line on phases 24 to 26 "added after" |
| `.mcp.json.example` | Stays, for opening `test_project/` by hand in any client (`CONTRIBUTING.md` names it); such a run writes to a folder of its own under `results/runs/` |
| `results/` | Unchanged; pytest's files stay there (F2), and no tester writes `test_results.md` again |

Moving it to `tests/scenarios/` would change the paths in `.gitignore`, `pyproject.toml`, `tests/test_gate.py` and
`tests/test_scenarios.py` for nothing a run gains; inside the skill's folder, the tester's working folder would be
under `.claude/`, whose settings and skills are the developers'.

### The skill

`.claude/skills/run-scenarios/SKILL.md`, written with `write-skill`:

1. **Scope** from the request: phases, port (8212 unless the maintainer named one), model, budget.
2. **Check:** `uv run tools/scenarios.py check --port <port>`. A refusal is reported, and overridden only on the
   maintainer's word; no Kit, Q3's question.
3. **Run:** `uv run tools/scenarios.py run --port <port> --phases <phases>`. A full run takes hours: run it in the
   background where the client can, else give the maintainer the command for a terminal of their own.
4. **Compare:** `uv run tools/scenarios.py compare`.
5. **Report:** the counts; each regression, FAIL and WARN with its note and evidence; for each FAIL, what the
   transcript shows the tester called. An issue for one only on the maintainer's word.

Done means `results.md` exists and the maintainer has `compare`'s summary. Never: port 8211 unless the maintainer named
it; start Kit or set `OMNI_KIT_ACCEPT_EULA` on its own; run beside the live suites or another session on the same Kit;
commit anything under `results/`; edit a finished run's files.

`.claude/settings.json` allows `uv run tools/scenarios.py check` and `uv run tools/scenarios.py compare`, each named
whole; `run` asks, as it drives Kit and spends tokens.

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

## Steps

Each step passes `uv run tools/gate.py full`. The skill and `finish-work` change through `write-skill`.

| Step | What | Proven by |
|---|---|---|
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | The CLI checked by hand, phase 1 on 8212 with a small budget: `--strict-mcp-config` with `--plugin-dir` (does the plugin's server load), `--setting-sources` (user plugins and `CLAUDE.md` gone, the repo's root `.claude/CLAUDE.md` loaded or not), `--tools` with `dontAsk` and `Write(<run>/**)` on Windows, the `init` event's fields. The findings go into this plan's Design before any code | The findings table, in this plan |
| 3 | `scenarios.md`: `Needs:` lines, `<run>` paths, the header. `tools/scenarios.py`: parsing, resolution, the run folder, the plugin copy, `mcp.json`, the prompts and command lines, and `run --dry-run`, which prints them without starting a tester | `tests/test_scenario_runs.py`: the real `scenarios.md` parses to 144 IDs in 27 phases, every `Needs:` ID exists and points back, `--phases 15` resolves to 2.1, 4.5, 10.1, Phase 15, 27 |
| 4 | `check`: the five rules, their overrides, the lock, the printout | The same file, against `tests/mock_bridge.py`: each refusal and its override |
| 5 | `run`: sessions in order, the `init` check, the `/health` watch, the limits, `run.json`, the merge into `results.md` | The same file, with a stub client (a Python script writing stream-json events and a phase file): a foreign MCP server stops it, a silent `/health` ends the run, a phase that writes nothing gives NOT RUN, the budget stops the next session |
| 6 | `compare` | The same file, over fixture runs: regressions first, `--against`, exit 1 |
| 7 | `test_project/AGENTS.md`, `CLAUDE.md` as an import | Step 9's run reads them |
| 8 | The skill: `SKILL.md`, `uv run tools/setup.py link run-scenarios`, `AGENTS.md` in place, `finish-work`, `docs/releasing.md`, `CONTRIBUTING.md`, `.claude/settings.json` | `uv run tools/gate.py quick`: frontmatter, link, listing, 150 lines |
| 9 | Live, on Isaac Sim 6.2 headless on 8212 with this branch's bridge: `check` refusing 8211, a stage saved outside the runs folder, a bridge copy that differs; phase 1 alone; phase 15 alone; every phase; `compare` twice. The run's time and cost go into the skill, the per-session limit is set from them | The run folders, read by the session; ten rows checked against their transcripts (Tests) |
| 10 | `finish-work` | The PR, with the full run's `compare` output |

## Tests

- **Unit, in CI:** `tests/test_scenario_runs.py`, as `tests/test_release.py` tests `tools/release.py`: parsing the real
  `scenarios.md`; resolution; `check` against the mock bridge; the command line `run` builds; the `init` check; the
  health watch; the budget; NOT RUN; the merge; `compare`. `tools/` is outside the coverage floor's source, as the gate
  and `release.py` are.
- **Live, by hand:** step 9. `test_integration.py` and `test_scenarios.py` are unchanged; neither touches what this
  adds.
- **What neither shows:** whether the tester judges right. The session reads ten rows against their transcripts and
  evidence: every FAIL and WARN, and the PASS rows of 3.2, 12.8 and 22.5, which rest on an image. Codex as the tester
  (Q4), and the path rules on Linux and macOS, stay untested.

## Docs

| File | Change |
|---|---|
| `AGENTS.md` | Four lines in place (Design) |
| `CONTRIBUTING.md` | The live suites section: one sentence naming `run-scenarios` and `test_project/AGENTS.md` |
| `docs/releasing.md` | Step 2's bullet (Q11) |
| `.claude/skills/finish-work/SKILL.md` | Step 3's sentence (Q11) |
| `test_project/AGENTS.md`, `CLAUDE.md`, `scenarios.md` | Q10 |
| `CHANGELOG.md`, `README.md`, `docs/TOOLS.md`, `docs/ARCHITECTURE.md` | None: no user, tool, route or protocol change |

## Risks

| Risk | Status |
|---|---|
| The CLI's flags act otherwise than read: the strict flag and plugin servers, setting sources, path rules on Windows | Resolved before code: step 2, its findings in this plan |
| The maintainer's own MCP servers or plugins reach a tester whose tools are pre-approved | Resolved: strict MCP config, setting sources, and the `init` check that stops the tester |
| A run wipes a stage someone cares about | Resolved: port, stage and bridge rules; the override needs the maintainer's word |
| `execute_script` is pre-approved in the tester and runs Python in Kit with the user's rights, so "no shell" doesn't fence the machine | Accepted: the code comes from the repo's own scenarios and runs on the test Kit, as the live suites' code does |
| The repo's developer rules load into the tester (the root's `.claude/CLAUDE.md` through parent discovery, if step 2 shows it does) | Accepted: the tester's `AGENTS.md` says they don't apply to it |
| The tester marks PASS without looking, or calls more than the scenario asks | Accepted, watched: one phase per session, transcripts kept, ten rows spot-checked in step 9 and the report naming the calls behind each FAIL |
| Time and cost unknown | Accepted: `run.json` records both, the skill states them after step 9, `--budget` caps a run |
| Kit hangs mid-run (#54) | Resolved: the `/health` watch ends the run |
| The live suites, another session or two runs drive the same Kit | Partly: the lock stops two runs; the skill's Never covers the rest |
| `Needs:` lines drift from the scenarios | Resolved: the unit test reads the real file |
| The plugin copy's skills link to GitHub's `main`, not the branch | Accepted: the skills' text is the branch's; only their links lead to `main` |
| Two runs on different models compare as if alike | Accepted: `compare` names both models |

## Plan review

Not yet reviewed.
