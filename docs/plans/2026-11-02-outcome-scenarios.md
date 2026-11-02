---
title: Add outcome scenarios to the AI suite, each asked in a user's words and judged by a read-only tester
issue: "#146"
status: draft
approved_by:
approved_at:
---

# Add outcome scenarios to the AI suite, each asked in a user's words and judged by a read-only tester

The AI scenario suite spells out every call, so it tests an agent following a script. This change adds outcome
scenarios: a request in a user's words ("put a red cube on the ground and show me"), given to a fresh agent that
chooses its own tools and skills, then judged by a second, read-only tester against Verify lines the agent never saw.
The runner also counts the agent's calls, and a scenario's `Calls:` line can hold it to a path, such as no
`execute_script`.

## Goal

When this is done:

- **Outcomes run with the suite:** `test_project/outcomes.md` holds six outcome scenarios, `O1` to `O6`. A full
  `uv run tools/scenarios.py run` runs them after the scripted phases and before the cleanup, one row each, which
  `compare` sets against earlier runs as it does a phase's rows.
- **The agent sees only the request:** each outcome's agent gets the request and a short brief, on a new stage the
  runner prepared; no Verify line, no call to make, no tester's rules.
- **A judge that cannot change the scene:** a fresh tester with only the read-only tools reads the request, the Verify
  lines, the agent's calls and answers and its captures, checks Kit's state, and gives the row.
- **The path is measured:** `results.md` lists each outcome's skills and calls; a `Calls:` line caps the row at WARN
  when the agent broke it.
- **16.9 leaves the suite:** it only names pytest's `test_16_09`, so a full run reports one SKIP fewer.

Why, from #146 and the scenario-skill plan's Q9: the tool descriptions and the plugin's skills exist to lead an agent
to the right tool, and nothing measures whether they do. pytest can't; the scripted phases name the tool.

| In scope | Out of scope |
|---|---|
| `test_project/outcomes.md`, `test_project/assistant.md` (the agent's brief), a judge section in `test_project/AGENTS.md` | Rewriting the scripted phases as outcomes |
| `tools/scenarios.py`: parsing, the `--outcomes` option, preparing a stage, the agent and judge sessions, the `Calls:` check, `results.md`, `compare`'s skill counts; its unit tests | `compare` reporting changes in calls or skills between runs: the record keeps them for later |
| 16.9 out of `scenarios.md` | Codex as the agent or judge |
| `run-scenarios`, `docs/releasing.md`, `CONTRIBUTING.md`, `AGENTS.md`'s `test_project/` row | Outcomes that need Isaac Sim's assets (robots from Nucleus) |

## What the code says

Read at `4576d87`.

| # | Finding | Where |
|---|---|---|
| F1 | `parse` reads `## Phase N:` and `### N.M` headings; the last phase is the cleanup (`Suite.cleanup`), and `plan` appends it to every run. Phases from 18 on start on a new stage (`SECOND_HALF`) | `tools/scenarios.py:96-164`, `:236-268` |
| F2 | `prompt` gives the tester the header and its scenarios whole, Verify lines included; `test_project/AGENTS.md` is appended to every tester's system prompt | `tools/scenarios.py:289-316`, `:420-465`, `:1209` |
| F3 | A tester runs with `--strict-mcp-config`, `--setting-sources ""`, `--tools Read,Grep,Glob,Skill`, `--permission-mode dontAsk`, the run's server and the plugin's skills allowed, `--no-session-persistence`; its working folder is its own `mcp_output/<label>/`, which is also its server's output folder | `tools/scenarios.py:420-470`, `:1247-1264` |
| F4 | `_read_event` already sees every `tool_use` (its name and input) and `tool_result`, keeping in-flight calls and skill loads; the transcript keeps the whole stream | `tools/scenarios.py:834-883` |
| F5 | Between sessions `settle` stops the timeline and a recording through `BridgeClient`; `BridgeClient` has `new_scene()` and `execute(code)` | `tools/scenarios.py:1186-1194`; `src/omniverse_mcp/client.py:296`, `:399` |
| F6 | `new_scene` makes a Y-up stage with `/World` as its default prim, and no light or ground: Kit 105.1+ has no default light, so a capture is black until something lights it (AGENTS.md, Traps) | `handlers/scene.py:601-616` |
| F7 | 10 of the 38 tools are read-only: `capture_viewport`, `get_logs`, `get_mesh_stats`, `get_prim_bounds`, `get_prim_properties`, `get_recording_frame`, `get_robot_info`, `get_scene_tree`, `get_sim_state`, `raycast` | `tests/fixtures/mcp-tools.json` (`readOnlyHint`) |
| F8 | `compare` counts skill loads over every session that ran, and keys rows by ID; `results_md` and `_id_key` sort `N.M` IDs and put any other at `(0, 0)` | `tools/scenarios.py:1037-1117` |
| F9 | 16.9 tells the tester to SKIP and call nothing: switching to `omni.debugdraw` needs `choose_backend`, an `ovmcp.*` import the rules forbid, and `test_16_09` covers it | `test_project/scenarios.md:590-594` |
| F10 | Claude Code 2.1.316 has `--add-dir`, `--allowedTools`, `--disallowedTools`, `--session-id` and `--resume` (which needs session persistence) | `claude --help` |
| F11 | The scenario-skill plan's step 9 saw two testers judge the same answers differently (15.1 to 15.3) | `docs/plans/2026-11-01-scenario-skill.md`, step 9 |

## Design

### `test_project/outcomes.md`

A header for people and the judge, then one section an outcome:

````markdown
## O1: A Red Cube on the Ground, Shown

Given: none

Ask: Put a red cube, 50 cm on a side, on a ground plane, and show me a picture of it.

Verify:
- A cube whose box is 0.5 m on each side, in the stage's units (`get_sim_state`'s `meters_per_unit`)
- Its colour reads red: the diffuse colour's red at least 0.5, green and blue at most 0.3
- A ground plane under it, the cube's bottom within 1 cm of the ground's top
- A capture in the answer shows the red cube on the ground, lit: not black

Calls: no execute_script
````

- **Given:** `none`, or a fenced `python` block the runner sends through `/execute` after `new_scene()`, to build what
  the request starts from (a scene with a fault, meshes with known counts). The agent never sees it.
- **Ask:** the request, one paragraph, in a user's words: what they want, never which tool.
- **Verify:** what the judge checks, each a fact about the stage or the answer, never a prim path the agent chose.
- **Calls:** `any`, or `no execute_script`, `at most <n>`, or both, comma-separated. The runner checks it (below).

The six (Q6):

| ID | Ask, in short | What it measures |
|---|---|---|
| O1 | a red 50 cm cube on a ground plane, and a picture | `create_prim`, `set_material`, placing on a ground, and lighting a stage that has none (F6) before the capture |
| O2 | make the ball fall onto the ground and say how long it takes to land (Given: a 0.2 m sphere 2 m up and a ground, no physics) | `set_physics_properties`, then timing by a tracked recording or steps; Verify: about 0.62 s, within 0.1 s, and the ball resting on the ground |
| O3 | which part under `/World/Machine` has the most triangles, and how many the machine has (Given: meshes of known counts in three groups) | `get_mesh_stats` over the tree; Verify: the right part and the exact total |
| O4 | my cube falls through the floor when I press play: find out why and fix it (Given: a floor without a collider, a cube with one and a rigid body) | reading physics properties, then `set_physics_properties`; Verify: the floor collides, the cube rests on it after 2 s of play, the answer names the missing collider |
| O5 | show me `/World/Table` from above and from the side (Given: a table of boxes, lit) | `inspect_prim` or `set_camera` with captures; Verify: two captures, one looking down, one from the side, the table centred in each |
| O6 | did anything report an error in the last minute, and what (Given: a `carb.log_error` line and a warning) | `get_logs`; Verify: the answer quotes the error and doesn't call the warning an error |

Every `Calls:` line is `no execute_script` except O2's, `any`: timing a fall without code is possible through a
tracked recording, but a user's agent that steps with code isn't wrong.

### The run

`--outcomes all|none|O1,O3` picks them. A run without `--phases` runs every outcome unless `--outcomes none`; a run
with `--phases` runs none unless `--outcomes` names them (Q4). `--phases none` runs outcomes alone. They come after
the scripted halves and before the cleanup, which `plan` keeps last.

Each outcome is three steps:

1. **Prepare,** by the runner through `BridgeClient`, after `settle`: `new_scene()`, then the Given code with
   `execute`. A refusal or an error makes the row NOT RUN with what Kit said, and no session starts.
2. **The agent,** session `outcome-O1`: the tester's command line (F3), with `test_project/assistant.md` appended in
   place of the tester's rules, and the Ask as its prompt, alone. Its skill loads and every `mcp__omniverse__` call,
   name, input and answer, are read from its stream as today (F4).
3. **The judge,** session `judge-O1`, on the stage the agent left: `test_project/AGENTS.md` as today, its new judging
   section included; built-in tools `Read,Grep,Glob` (no `Skill`); `--allowedTools` the ten read-only tools (F7),
   read from `tests/fixtures/mcp-tools.json` so a new read-only tool joins on its own; `--disallowedTools` the rest,
   so it can't call them even by mistake. Its working folder is the agent's `mcp_output/outcome-O1/`, so `Read`
   reaches the agent's captures; its own server writes to `mcp_output/judge-O1/`. Its prompt: the Ask, the Verify
   lines, the agent's calls in order, each with its input and the first 600 characters of its answer, the agent's last
   message, and the capture files the agent's server wrote. It answers the usual one-row table.

**The `Calls:` check:** the runner counts the agent's calls. Over a limit, or `execute_script` where the line says
none, caps the judge's PASS at WARN, and the notes gain `Calls: execute_script 2, where the line says none`. A FAIL
stays a FAIL (Q3).

**The brief, `test_project/assistant.md`:** you help a user with their Kit app through the Omniverse MCP; nobody
answers questions, so decide, act and say what you assumed; the request follows. It keeps the tester's code rules for
`execute_script` (one short job a call, no waits, no `ovmcp.*` imports), since a script that holds Kit's main thread
ends the run for every later session, and the file rules. It says nothing about tests, Verify lines or tools.

**The record:** `SessionRecord` gains `calls`, the agent's tool names in order. `results.md` gains an `## Outcomes`
table, `| ID | Skills loaded | Calls | Status |`, the calls as `create_prim, set_material x2, ... (9 calls, 0
execute_script)`. `compare` leaves judge sessions out of its skill counts, which measure what an agent reaches for;
`_id_key` sorts `O<n>` after every phase.

### 16.9

Its heading goes; one sentence joins Phase 16's note before 16.3: `omni.debugdraw`, the other drawing backend, is
pytest's `test_16_09`, since no tool switches to it (Q5). `compare` reports nothing for an ID a new run lacks, so no
regression appears.

### Alternatives

| Alternative | Taken? | Why |
|---|---|---|
| Outcomes as phases in `scenarios.md` | No | The tester gets a phase whole, Verify lines included (F2); the cleanup is the last phase (F1); and an outcome needs its own stage, prompt and rules |
| The agent judges itself, its session resumed with the Verify lines | No | `--resume` needs session persistence, which the runner turns off so run folders don't become projects (F3, F10); and an agent grades its own path kindly |
| The runner checks each outcome in Python | Only the `Calls:` line | A capture that "shows a red cube, lit" needs eyes; Python asserts in every outcome would make it a pytest suite |
| The judge with every tool | No | It could fix what it judges; the read-only hint already marks what is safe (F7) |

## Compatibility

None for users: test tooling only, no one-way door. A run folder made before this change has no outcome rows and no
`calls`, which `compare` and `results_md` read as absent.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | Parse `outcomes.md`: `Outcome(id, title, given, ask, verify, calls)`; problems named: a missing Ask or Verify, an unknown `Calls:` word, Given code that doesn't compile | `test_scenario_runs.py`: the real file parses with no problem; each malformed form named |
| 3 | `--outcomes` and `plan`: outcome sessions after the halves, before the cleanup; `--phases` alone runs none; `--phases none` | `test_scenario_runs.py`: the session lists |
| 4 | Prepare, the agent's prompt and command, the judge's prompt and command | tests: the agent's prompt holds the Ask and nothing of Verify, Calls or Given; the judge's command allows exactly the read-only tools and no `Skill`; its working folder is the agent's |
| 5 | The calls record and the `Calls:` check; a failed Given | tests on recorded streams: counts, the cap at WARN, FAIL kept; a Given error gives NOT RUN and starts no session |
| 6 | `results.md`'s Outcomes table; `compare` without judge skill loads; `_id_key` | tests |
| 7 | `outcomes.md`, `assistant.md`, the judge section; 16.9 out | the real-file test of step 2; the dry run prints both prompts |
| 8 | Live: `--phases none --outcomes all` twice on my Kit at 8212, then `--phases 16` once; each Given checked to build what its Verify lines assume | the runs' `results.md`, quoted in the PR with both runs' statuses side by side |
| 9 | Docs, then `finish-work`: the gate in full, `review-code` | the review record |

## Tests

- **Unit (CI):** `tests/test_scenario_runs.py`, steps 2 to 7: parsing, planning, both prompts and command lines, the
  calls record and check, a failed Given, `results.md`, `compare`. The real `outcomes.md` parses with no problem.
- **Live, by hand:** step 8, on a headless Isaac Sim 6.2 at 8212 with this branch's bridge (unchanged from `main`).
  Two runs of the outcomes show how often the agent and the judge agree with themselves; the PR says.
- **What neither shows:** whether six outcomes are the right six. The record keeps calls and skills, so later runs
  can show what a description change did.

## Docs

- `test_project/outcomes.md` and `test_project/assistant.md` (new); `test_project/AGENTS.md`'s judging section.
- `.claude/skills/run-scenarios/SKILL.md`: `--outcomes` in Scope, their cost, and the Report step's outcome rows with
  their calls.
- `docs/releasing.md` step 2: every phase and every outcome.
- `CONTRIBUTING.md`'s paragraph on the suite; `AGENTS.md`'s `test_project/` row, in place (the file is at its cap).
- No CHANGELOG line: users don't see the suite.

## Risks

| Risk | What then |
|---|---|
| A judge's verdict moves between runs, as a tester's did (F11) | Accepted: step 8's two runs measure it, and `run-scenarios` already says to read both answers before calling a change a regression |
| The brief's code rules steer the agent away from scripts, so the suite measures a little less than a free agent | Accepted: a script that holds Kit's main thread ends the run for every later session; the rules forbid only waiting, not scripts |
| An agent asks the user a question and stops | The brief says nobody answers; a session that ends without acting gets a FAIL from its judge, with the question in the notes |
| Given code hangs Kit | It is ours, short, and reviewed; `settle`'s and `execute`'s timeouts end the run there, as a hung session does |
| Cost: twelve more sessions in a full run | Measured in step 8 and written into `run-scenarios`; `--outcomes none` leaves them out |
| The judge's prompt grows with long answers | Each answer is cut to 600 characters; the transcript keeps them whole |

## Plan review

Not reviewed yet.
