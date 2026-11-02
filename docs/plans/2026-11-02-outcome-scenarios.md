---
title: Add outcome scenarios to the AI suite, each asked in a user's words and judged by a read-only tester
issue: "#146"
status: approved
approved_by: serionist
approved_at: 2026-11-02
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
| F12 | `--restricted` confines the file tools to the working folders, `--add-dir` ones included; a bare `Read` allow otherwise reaches any path, `outcomes.md` among them | `claude --help` |
| F13 | An answer over 1,000 characters goes to a file in the server's output folder, and a capture is a file unless `include_image` | `src/omniverse_mcp/server.py:46`, `:144-157`; `handlers/camera.py:148-150` |
| F14 | The viewport's lighting mode is a Kit setting, not the stage's; `new_scene()` leaves it as it was | `handlers/camera.py:164`, `:180` |
| F15 | `run_sessions` calls `settle` before every session; `sim_control("stop")` is `timeline.stop()`, and the suite relies on a stop putting a body back where play found it, where a pause keeps it; `sim_control` is not read-only | `tools/scenarios.py:948-950`; `handlers/simulation.py:65-71`; `scenarios.md:182`, `:198`; `tests/test_scenarios.py:1927`; `mcp-tools.json` |

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

Play: none
````

- **Given:** `none`, or a fenced `python` block the runner sends through `/execute` after `new_scene()`, to build what
  the request starts from (a scene with a fault, meshes with known counts). The agent never sees it. The parser
  compiles it with `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`, as the bridge runs it, so an `await` in it is no error.
- **Ask:** the request, one paragraph, in a user's words: what they want, never which tool.
- **Verify:** what the judge checks, each a fact about the stage or the answer, never a prim path the agent chose.
- **Calls:** `any`, or `no execute_script`. The runner checks it (below). A call limit waits for an outcome that
  needs one.
- **Play:** `none`, or `<n> s`: after the agent, the runner plays the simulation that long and pauses, so the judge
  reads where physics put things (Q2). The judge can't play: `sim_control` isn't read-only, and a stopped stage has
  every body back where play found it (F15).

The six (Q6):

| ID | Ask, in short | What it measures |
|---|---|---|
| O1 | a red 50 cm cube on a ground plane, and a picture | `create_prim`, `set_material`, placing on a ground, and lighting a stage that has none (F6) before the capture |
| O2 | make the ball fall onto the ground and say how long it takes to land (Given: `/World/PhysicsScene`, a 0.2 m sphere 2 m up and a ground, neither with physics; Play: 2 s) | `set_physics_properties`, then timing by a tracked recording or steps; Verify: the ball has a rigid body and a collider, the ground a collider and no rigid body; after the runner's play the ball's bottom is within 1 cm of the ground's top; the answer says about 0.62 s, within 0.1 s |
| O3 | which part under `/World/Machine` has the most triangles, and how many the machine has (Given: meshes of known counts in three groups) | `get_mesh_stats` over the tree; Verify: the right part and the exact total |
| O4 | my cube falls through the floor when I press play: find out why and fix it (Given: `/World/PhysicsScene`, a floor without a collider, a cube with one and a rigid body; Play: 2 s) | reading physics properties, then `set_physics_properties`; Verify: the floor has a collider, collision on, and no rigid body; after the runner's play the cube's bottom is within 1 cm of the floor's top; the answer names the missing collider |
| O5 | show me `/World/Table` from above and from the side (Given: a table of boxes, lit) | `inspect_prim` or `set_camera` with captures; Verify: two captures, one looking down, one from the side, the table centred in each |
| O6 | what errors Kit has logged most recently, and what they say (Given: a `carb.log_error` line and a warning, each with a fixed marker the Verify line quotes; an earlier run's identical line is the same text, so nothing is lost) | `get_logs`; Verify: the answer quotes the Given's error, and doesn't call its warning an error; naming an older error as well, such as 24.6's in a full run, is no fault, since `get_logs` gives no times |

Every `Calls:` line is `no execute_script` except O2's, `any`: timing a fall without code is possible through a
tracked recording, but a user's agent that steps with code isn't wrong.

### The run

`--outcomes all|none|O1,O3` picks them. A run without `--phases` runs every outcome unless `--outcomes none`; a run
with `--phases` runs none unless `--outcomes` names them (Q4). `--phases none` runs outcomes alone. They come after
the scripted halves and before the cleanup, which `plan` keeps last.

Each outcome is three steps, four with a `Play:` line:

1. **Prepare,** by the runner through `BridgeClient`, after `settle`: `new_scene()`, the viewport's lighting set to
   `stage` with `viewport_light("set", mode="stage")` (the mode is a Kit setting, which `new_scene()` leaves as an
   earlier phase or outcome set it), then the Given code with `execute`. A refusal or an error makes the row NOT RUN
   with what Kit said, and no session starts.
2. **The agent,** session `outcome-O1`: the tester's command line (F3) with `--restricted`, which confines `Read`,
   `Grep` and `Glob` to its working folder, its own `mcp_output/outcome-O1/`: `outcomes.md`, the judging rules and
   earlier runs' judges stay out of its reach. `test_project/assistant.md` is appended in place of the tester's rules,
   and the Ask is its prompt, alone. Its skill loads and every `mcp__omniverse__` call, name, input and answer, are
   read from its stream as today (F4).
3. **Play,** with a `Play:` line, by the runner through `BridgeClient`: `settle` (a stop puts bodies back where the
   agent's own play found them, and ends a recording it left), then `sim_control("play")`, `sim_state` read until its
   `sim_time` has moved on by the line's seconds, within a wall-clock limit of four times that plus 10 s, then
   `sim_control("pause")`. The same play every run, whatever the agent did. A play that doesn't get there makes the
   row NOT RUN with what `sim_state` said, and the judge doesn't start.
   - **Kit's answers in Prepare and Play:** an error Kit answers (a Given that raises, a refused call: the client's
     `BridgeError`) makes that row NOT RUN and the run goes on; no answer at all (`OSError`, which the client's
     timeouts are) halts the run as `settle`'s does today, "Kit didn't answer", rather than reading as a run cut
     short.
4. **The judge,** session `judge-O1`. Without a `Play:` line it starts after `settle`, as every session does, on the
   stage the agent authored; with one, it starts with no `settle`, on the paused stage, and the next session's
   `settle` stops it. `test_project/AGENTS.md` as today, its new judging
   section included; built-in tools `Read,Grep,Glob` (no `Skill`); `--allowedTools` the ten read-only tools (F7),
   read from `tests/fixtures/mcp-tools.json` so a new read-only tool joins on its own; `--disallowedTools` the rest,
   so it can't call them even by mistake. Its working folder is the agent's `mcp_output/outcome-O1/`, so the paths in
   the agent's answers, relative to that folder (each server numbers its files from 1), open the agent's files; its
   own server writes to `mcp_output/judge-O1/`, outside its working folder, so its answers name its own files by
   absolute path (an answer over 1,000 characters goes to a file, F13). `--restricted` with `--add-dir` its own
   folder: `Read` reaches both and nothing else. Its prompt: the Ask, the Verify lines, the agent's calls in order,
   each with its input and the first 600 characters of its answer, the agent's last message, and the files the
   agent's server wrote, by absolute path. It answers the usual one-row table.
   - **The init check per kind:** a judge whose first event lists a tool outside `Read`, `Grep`, `Glob` and its
     allowed list is stopped, as a tester with a foreign server is today; read-only is then checked, not only asked.
     An agent whose first event lacks the run's plugin is stopped too, since `--restricted` is new to the testers.

**The `Calls:` check:** the runner counts the agent's `mcp__omniverse__` calls. `execute_script` where the line says
none caps the judge's PASS at WARN, and the notes gain `Calls: execute_script 2, where the line says none`. A FAIL
stays a FAIL (Q3).

**The brief, `test_project/assistant.md`:** you help a user with their Kit app through the Omniverse MCP; nobody
answers questions, so decide, act and say what you assumed; the request follows. It keeps the tester's code rules for
`execute_script` (one short job a call, no waits, no `ovmcp.*` imports), since a script that holds Kit's main thread
ends the run for every later session, and the file rules. It says nothing about tests, Verify lines or tools.

**The record:** `SessionRecord` gains `calls`, the agent's tool names in order. `results.md` gains an `## Outcomes`
table, `| ID | Skills loaded | Calls | Status |`, the calls as `create_prim, set_material x2, ... (9 calls, 0
execute_script)`. `compare` leaves judge sessions out of its skill counts and its "none in N of M sessions", which
measure what an agent reaches for; `_id_key` sorts `O<n>` after every phase.

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
| The judge plays the simulation itself, `sim_control` allowed by name | No (Q2) | An exception to the read-only rule, and the judge would choose when and how long to play, one more source of variance; the runner's play is the same every run |

## Compatibility

None for users: test tooling only, no one-way door. A run folder made before this change has no outcome rows and no
`calls`, which `compare` and `results_md` read as absent.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | This plan, reviewed and approved | the Plan review section |
| 2 | Parse `outcomes.md`: `Outcome(id, title, given, ask, verify, calls, play)`; problems named: a missing Ask or Verify, an unknown `Calls:` word, a `Play:` that isn't `none` or seconds, Given code that doesn't compile | `test_scenario_runs.py`: the real file parses with no problem; each malformed form named |
| 3 | `--outcomes` and `plan`: outcome sessions after the halves, before the cleanup; `--phases` alone runs none; `--phases none` | `test_scenario_runs.py`: the session lists |
| 4 | Prepare, the agent's prompt and command, the judge's prompt and command, the init check per kind | tests: Prepare's calls in order; the agent's prompt holds the Ask and nothing of Verify, Calls or Given, and its command is `--restricted` with no `--add-dir`; the judge's command allows exactly the read-only tools and no `Skill`, works in the agent's folder and adds its own; its prompt names the agent's files by absolute path; a judge init event with a tool outside its list, and an agent init event without the run's plugin, stop the session |
| 5 | The calls record and the `Calls:` check; a failed Given; Play and the judge's settle | tests on recorded streams: counts, the cap at WARN, FAIL kept; a Given error gives NOT RUN and starts no session; with a fake client, a `Play:` outcome settles, plays, waits for the time, pauses, and starts the judge with no settle, one without settles before the judge, and a play that never gets there gives NOT RUN; an error Kit answers in Prepare gives NOT RUN and the run goes on, no answer halts it |
| 6 | `results.md`'s Outcomes table; `compare` without judge skill loads; `_id_key` | tests |
| 7 | `outcomes.md`, `assistant.md`, the judge section; 16.9 out | the real-file test of step 2; the dry run prints both prompts |
| 8 | Live: each Given and Prepare checked first by hand on my Kit at 8212 (O1's stage renders a cube black, though the grid may show; O4's cube falls through; O2's ball, once given a body by hand, falls), then `--phases none --outcomes all` twice, then `--phases 16` once; the agent's transcripts show no `Read` outside its folder | the runs' `results.md`, quoted in the PR with both runs' statuses side by side |
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
| The judge's prompt grows with long answers | Each answer is cut to 600 characters; the transcript keeps them whole, and the agent's answer files are in reach of the judge's `Read` |
| The agent's working folder is inside the repo, so Claude Code's git status gives it recent commit subjects | Accepted: a subject may name this feature, never a Verify line; `--restricted` keeps the files themselves out of reach |
| `--restricted` changes something else the tester relied on, such as the plugin's skills | The init check stops an agent without the run's plugin; step 8 checks its skill loads |
| The agent reads `outcomes.md` through `execute_script`, since Kit's Python opens any file | Accepted: nothing points it at the repo, and such a call shows in its calls record |
| After the runner's play, `get_prim_bounds` reads USD, so a Kit app that doesn't write physics back to USD would show bodies where they started | Accepted: Isaac Sim 6.2 writes them back, as 5.3's gravity check shows; step 8 runs there |

## Plan review

### Round 1

**How:** one fresh reviewer on Claude Opus 5.5, every lens, 2026-11-02, at `190d2e0`; P1 went to a fresh refuter,
which confirmed it as major and proposed the fix taken. **Verdict:** needs-fixes. **Now:** every finding fixed in the
plan; a second round reads the edits.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | major | O2's and O4's Verify lines ask where a body rests after play, which a read-only judge can't see: `sim_control` isn't read-only, `run_sessions` settles before every session, and a stop puts bodies back where play found them (F15). A correct fix that the agent never played would be judged WARN or FAIL, and the row would depend on the agent's path | fixed: a `Play:` line, by which the runner settles, plays a set time and pauses after the agent; the judge then starts with no settle; O2's and O4's Verify lines restated as facts of that paused stage and of the stopped one; step 5's tests (Q2) |
| P2 | minor | The agent's bare `Read`, `Grep` and `Glob` reach any path: `outcomes.md` and earlier runs' judge transcripts are a few folders up from its working folder | fixed: the agent runs `--restricted` (F12), its file tools confined to its own folder; step 4 tests the command, step 8 the transcripts |
| P3 | minor | The judge works in the agent's folder while its own long answers and captures go to `judge-O1/`, out of its `Read`'s reach (F13) | fixed: the judge works in its own folder, `--restricted` with `--add-dir` the agent's |
| P4 | minor | O6 asked about "the last minute", which `get_logs` can't tell: no time filter, no times, and in a full run 24.6's error sits in the same buffer | fixed: O6 asks for the most recent errors; Verify names the Given's error, and an older one named too is no fault |
| P5 | minor | The lighting mode is a Kit setting that `new_scene()` leaves as it was (F14), so O1 could start lit by an earlier phase, measuring nothing | fixed: Prepare sets the mode to `stage`; step 8 checks O1's stage captures black first |

**Refuted:**
- **O4 needs `execute_script` to add a collider:** `set_physics_properties` with a friction or restitution adds the
  collision API when it's missing (`handlers/simulation.py:159-161`).
- **A ground plane needs code:** `create_prim` takes any USD type (`handlers/scene.py:174`).
- **O3 can't give per-part triangles:** each mesh block lists `triangles`, and a group's is their sum.
- **The judge can change the stage:** no `Skill`, `dontAsk` with only the read-only tools allowed, the rest
  disallowed; `capture_viewport` renders in a feed of its own.
- **The judging section reaches the agent through `CLAUDE.md`:** `--setting-sources ""` loads no instruction file.
- **16.9's removal reads as a regression:** `compare` walks only the newest run's rows.
- **Given code that hangs ends the run:** the Risks row covers it: the client's timeouts, then `settle` halts the run.

**Owner calls:**

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Outcomes in their own `test_project/outcomes.md`, IDs `O1` on, or as phases of `scenarios.md`? | Their own file: a phase's tester gets its Verify lines (F2), the cleanup must stay last (F1), and an outcome needs its own stage, prompt and rules |As recommended (2026-11-02) |
| Q2 | How a physics outcome is judged (P1): the runner plays a set time and pauses before a read-only judge; the judge may call `sim_control`; or only the stopped stage's facts and the agent's answers count? | The runner plays: the judge stays read-only, and every run plays the same |The runner plays (2026-11-02) |
| Q3 | An agent that breaks its `Calls:` line: PASS capped at WARN (FAIL kept), set to FAIL, or only shown in `results.md`? | Cap at WARN: `compare` then shows when a description change sends agents to code, without calling the outcome wrong |Cap at WARN (2026-11-02) |
| Q4 | Outcomes in every full run, and in a run with `--phases` only when `--outcomes` names them? | Yes: a release's run then measures them; partial runs stay as cheap as today |As recommended (2026-11-02) |
| Q5 | 16.9: delete its heading and put one sentence in Phase 16's note, or keep the row? | Delete: the issue asks for no standing SKIP, and `test_16_09` covers it |Delete (2026-11-02) |
| Q6 | These six outcomes (O1 to O6), as now written? | Yes |Yes (2026-11-02) |
| Q7 | The agent's brief keeps the tester's `execute_script` rules (no waits, no `ovmcp.*` imports)? | Keep: a script that holds Kit's main thread ends the run for every later session |Keep (2026-11-02) |
| Q8 | The judge on the same model as the agent (one `--model` for both)? | Yes, one flag |Yes, one flag (2026-11-02) |

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | `at most <n>` had no outcome using it | taken: `Calls:` is `any` or `no execute_script`, counting `mcp__omniverse__` calls |
| I2 | Compile Given code with `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`, as the bridge runs it | taken |
| I3 | An init check per session kind, so the judge's read-only tools are checked, not only asked for | taken: step 4 |
| I4 | `compare`'s session count without a skill load leaves judges out too | taken |

### Round 2

**How:** one fresh reviewer on Claude Opus 5.5, 2026-11-02, at `c6e5e61`, reading round 1's fixes and what they
touch. **Verdict:** approved, once the maintainer answered Q1 to Q8 as recommended (2026-11-02): P1 to P5 closed, no
blocker or major open, three minors fixed below. **Now:** every finding and improvement applied; no round 3, as only minors came.

| # | Sev | Finding | Status |
|---|---|---|---|
| R1 | minor | P3's fix put the judge in its own folder, but the agent's answers name its files relative to the agent's folder, and each server numbers from 1: the judge would open its own `captures/capture_0001.png` for the agent's and judge the wrong image | fixed: the judge works in the agent's folder with `--add-dir` its own, so its own server names its files by absolute path; its prompt names the agent's files by absolute path; step 4 tests both |
| R2 | minor | O2's and O4's Givens had no `PhysicsScene`, so a play simulates only while Kit's "create a temporary default physics scene" preference is on; off, O2's ball never falls and a correct agent FAILs | fixed: both Givens define `/World/PhysicsScene`, as 4.5 does; step 8 checks O2's ball falls |
| R3 | minor | O6's marker "of the run's own" could never appear in a fixed Verify line | fixed: a fixed marker the Verify line quotes |

**Refuted:** play's time not moving (a stop rewinds it, and 2 s is far from Isaac Sim 6.2's timeline end); a pause
hiding the result from USD (5.3 pauses and reads lower bounds); the stage unclean for the next outcome (every session
settles first, and the cleanup stays last); the judge's missing settle breaking the budget, the watch or the halt
(each is set up apart from it); `--restricted` removing `Skill` (it removes code-running tools and WebFetch unless
`--tools` names them, and the plugin's skills run no commands); `--restricted` dropping the run's server (the init
check fails closed); the judge unable to see a collider (`get_prim_properties` lists `physics:collisionEnabled`, and
the text form says `rigid_body = true`).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I5 | Name `sim_state`'s key, `sim_time`, in the Play step | taken |
| I6 | The init check stops an agent without the run's plugin, since `--restricted` is new | taken: step 4 |
| I7 | An error Kit answers in Prepare or Play gives that row NOT RUN; no answer halts the run as `settle`'s does | taken: steps 4 and 5 |
| I8 | O2 and O4 verify the ground has no rigid body: a floor made dynamic falls with the cube and still passes the 1 cm line | taken |
| I9 | Step 8's check of O1's stage looks at the cube, black, since Kit's grid may still show (#105) | taken |
