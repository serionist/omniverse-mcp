---
title: Run a long script as a job that Kit keeps rendering through, read and cancelled by id, a change to the tool contract
issue: "#158"
status: draft
approved_by:
approved_at:
---

# Run a long script as a job that Kit keeps rendering through, read and cancelled by id, a change to the tool contract

## Goal

An agent starts a long job in the Kit app that already has the scene open, watches its progress, reads its result, and
cancels it if needed, while Kit keeps rendering and other tools answer. Today `execute_script`'s answer stops at the
client's 120 s (`client.py:41`), and the script runs on with nobody to read what it returns, so a job that needs
minutes is cut into calls with its state kept somewhere between.

The case (#158 and its author, 2026-11-02): a construction site's 100 to 150 stacks of pipes, drums and timber are
each dropped under physics for 2 to 3 s of simulated time, in turn, and their settled poses baked into the scene: minutes
to tens of minutes. The bake script (bechtel-mvp's `bake.py`, not yet written) will await
`omni.kit.app.get_app().next_update_async()` each step while the timeline plays; other callers may write plain loops
or `world.step()`. Nothing else needs tools while it runs; progress lines and the poses at the end are enough. #157's
capture sweeps are the second user: a sweep of 400 shots runs as a job too.

When this is done:

- `run_script_job(code="", file="")` starts a script, given as text or as a file on Kit's machine (the issue's
  `code | file`, so a long bake script needn't pass through the agent's context), as a job, and answers its id at once
  (fit I7);
- `get_job(job_id="", wait=0)` gives its state (`working`, `cancelling`, `completed`, `failed`, `cancelled`, the MCP
  task's states), elapsed time, its last lines with a count of all, and, once it ends, its result in its kind's form;
  with no id, the running or the last job, so an agent whose context was compacted finds it again; `wait` up to 100 s
  returns early on a new line or the job's end, so an agent needn't poll back to back (fit I8, I9);
- `cancel_job(job_id)` cancels it at its next `await`, and the job counts as running until its own cleanup has
  finished (fit I3);
- one job at a time: a second start is refused, naming the one running; `get_sim_state` names a running job, as it
  names a recording (fit I9);
- a script that never awaits is refused before it starts, since it would block Kit whatever runs it.

In scope: three tools, their routes, a Kit-free job board the sweep reuses, a Kit-free script compiler that
`/execute` shares, docs, the `script` skill, an outcome scenario.
Out of scope: several jobs at once; a job that survives Kit's restart; running a script on another thread (USD off the
main thread crashes Kit, `AGENTS.md` Traps); #157's sweep itself.

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02) |

### Where it runs, and why only awaiting code

Kit runs Python on its main thread, one update at a time; the bridge's handlers are tasks on Kit's asyncio loop, each
its own task (`AGENTS.md`, Traps). A job is one more task on that loop: between its `await`s Kit renders, physics
steps and other requests are served. A script with no `await` runs from start to end inside one update, holding the
main thread, and no runner can change that; so the job runner refuses it, where `execute_script` would have run it and
frozen Kit.

The refusal reads the compiled code (fit I5): `ovmcp/core/script.py` compiles a script with
`ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`, as the standard library's asyncio REPL does, and `code.co_flags &
inspect.CO_COROUTINE` says exactly whether it awaits. One without is refused with the reason and the fix (`await
omni.kit.app.get_app().next_update_async()` in its loop). A script that awaits once and then loops, or calls
`world.step()` (Isaac Sim's `step(render=True)` "is not intended to be used in the Isaac Sim's Extensions workflow",
`simulation_context.py:707-708`; Kit 6.2's async engine defers every asyncio task while it runs), still blocks the
bridge: `get_job` runs on the same loop, so nothing can read the job meanwhile. The description and the `script`
skill say so plainly; no watchdog is promised, since none could answer.

### The extension

- **`ovmcp/core/script.py`** (Kit-free, fit I5): `compile_script(code)` gives the code object and whether it awaits;
  `/execute` uses it too, in place of its `textwrap.indent` wrapper, which changed multi-line strings' contents and
  shifted traceback lines by one.
- **`ovmcp/core/output.py`** (Kit-free, fit I6): one context-variable router installed as `sys.stdout` and
  `sys.stderr` once, writing to the current task's buffer, or to Kit's stream when the task has none. `/execute` drops
  its `sys.stdout` swap, which a job holding across its awaits would otherwise share, so an `/execute` call's output
  and a job's never mix. A job's printed lines are its progress: no `progress()` to learn.
- **`ovmcp/core/jobs.py`** (Kit-free): `Job` (id, `kind` (`script` now, `sweep` for #157), state, status message,
  started, ended, lines kept to the last 200 with a count of all, `result` as a dict in its kind's shape, error);
  `JobBoard` with `start(kind, label, coroutine_factory, watch_stage=False)` refusing a second job while one is
  working or cancelling, `get(id)` (`""` for the running or last), `cancel(id, reason)` passing the reason through
  `task.cancel(msg)`, so a job's cleanup can tell a user's cancel from a stage change, and the finished jobs kept until
  the next start. A job holds the slot until its own `finally` has returned, so a sweep that puts the stage back after
  a cancel finishes first (fit I2, I3).
- **`handlers/jobs.py`:** `handle_job_script(body)` (`/jobs/script`) reads `code` or `file` (one of them), compiles and
  refuses as above, builds `/execute`'s namespace (`omni`, `carb`, the `pxr` modules, `mcp`) and starts it on the
  board with `asyncio.ensure_future`, so the job outlives the HTTP request. `handle_job_get` (`/jobs/get`, with
  `wait`) and `handle_job_cancel` (`/jobs/cancel`) serve every kind: the routes are generic, since paths are a
  one-way door and a sweep is read through them too (fit I1).
- **The result:** a script's is `{"return_value", "stdout", "stderr"}` as `/execute` gives them; the server formats it
  by kind, and a large one goes to a file, as long text does today.
- **Stage changes,** opt-in per job (fit I4): a job started with `watch_stage` is cancelled, with the reason, when the
  stage's id changes on an update, as `recording.py`'s `_why_frames_stop` watches it, which also catches a stage opened
  from Kit's menu or a script. A script job doesn't watch, since a bake may open stages itself; a sweep does.
- **Shutdown:** each job gives the board a synchronous teardown, as `recording.shut_down` does, since `on_shutdown`
  can't await; the board calls it and cancels the task.

### The server

- **`client.job_script(code, file)`, `job_get(id, wait)`, `job_cancel(id)`;** `tools/misc.py`:
  - `run_script_job(code="", file="")`: `RUNS`, as `execute_script`;
  - `get_job(job_id="", wait=0)`: `READS`, `wait` 0 to 100 s, under the server's 120 s;
  - `cancel_job(job_id)`: `EDITS`.
- **Answers:** `run_script_job`: `Job j3 started (script); read it with get_job("j3")`. `get_job`:
  `state = working`, `elapsed = 4m 12s`, `last = 37 of 150 stacks settled` and the last 20 lines with the count, then
  the result in its kind's form once it ends (a script's: return value, stdout, stderr; a sweep's later: its
  manifest), through `text_response` so a long one goes to a file.
- **`get_sim_state`** adds `job = j3 (script, working, 4m 12s)` while one runs (fit I9).
- **`execute_script`'s description** names `run_script_job` for anything that may outlast 120 s.

### Alternatives

- **MCP's own tasks:** the 2025-11-25 specification's task-augmented `tools/call` with `tasks/get`, `tasks/result`
  and `tasks/cancel` left the core specification on 2026-07-28 and continues as an extension; SDK 2.3.0 carries their
  types only, "never dispatched" (`mcp_types/_types.py:610-612`). Left for now: the client decides to make a call a
  task, and the clients this server serves don't. The job's fields mirror a task's (`working`, `completed`, `failed`,
  `cancelled`, a status message), so a later `mcp.server.extension.Extension` binding `tasks/get` (`MethodBinding`)
  maps one onto the other (fit I8).
- **`execute_script(..., background=True)`:** one tool fewer, but its answer would mean two things, and reading and
  cancelling still need tools of their own.
- **A separate headless Isaac Sim for each job:** the issue's alternative; about 90 s to start and a second GPU
  process.
- **Run plain loops by stepping them ourselves:** no; nothing outside a script can interleave its loop with Kit's
  updates.

## Compatibility

**One-way doors: the tool contract and the wire protocol's paths.** Three new tools and three new routes,
`/jobs/script`, `/jobs/get` and `/jobs/cancel`, named for every kind of job since a path can't be renamed later:
additive; `execute_script` keeps its parameters, its description changes, and its output and traceback lines come
through the shared compiler and router, the same text but for a traceback's line numbers, which now match the script.
`get_sim_state` adds a `job` line. The maintainer agreed in #158's thread (posted from the maintainer's chat
decisions, 2026-11-02, before the PR). An older extension answers the unknown routes with the install advice.

The bridge's security is unchanged: the routes need the token, refuse an `Origin` and a foreign `Host`, as `/execute`
does, and run nothing `/execute` can't. `file` reads a path on Kit's machine, as a script given to `/execute` already
can.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/script.py` and `ovmcp/core/output.py`, tests first; `/execute` moved onto both | `tests/test_script.py`: awaiting and plain code told apart, a multi-line string kept whole, traceback lines right; `tests/test_output.py`: two tasks' writes to their own buffers, a task without one to the stream; `/execute`'s existing tests unchanged |
| 2 | `ovmcp/core/jobs.py`, tests first | `tests/test_jobs.py`: start, one at a time, a cancelling job holding the slot until its `finally` returns, the reason passed, lines kept to 200 with the count, a failure's error, a finished job read late, `get("")`, a teardown called at shutdown |
| 3 | `handlers/jobs.py`, the routes, the code-or-file start, `wait`, the stage watch, the shutdown teardown, `get_sim_state`'s line | `tests/test_jobs_handler.py` with the Kit fakes: a job's prints in its buffer while an `/execute` call's go to its own; a watching job cancelled by a stage change and a script job not; a plain script refused |
| 4 | The client, the three tools, `execute_script`'s description; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4b | An outcome in `test_project/outcomes.md` whose work outlasts 120 s, its `Calls:` expecting `run_script_job`, so the pointer in `execute_script`'s description is shown to steer agents (fit I10) | an outcome run |
| 4c | Docs, the `script` skill | review |
| 5 | Live: a job that plays the timeline and steps a falling box for 150 s of updates while `get_prim_bounds` and `capture_viewport` answer; its progress read twice; its result the box's final pose; a second job cancelled mid-way; a plain-loop script refused | `tests/test_integration.py`, on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 4.
- Live: step 5, with the suites on a Z-up and a Y-up stage; a 10-minute job by hand once, as the issue's Done when
  asks, its progress and result read, and Kit answering throughout.
- What neither shows: bechtel-mvp's own bake, which isn't written; USD Composer, where the loop is the same Kit loop.

## Docs

`docs/TOOLS.md` (the three tools, `execute_script`'s pointer, `get_sim_state`'s `job` line), `docs/ARCHITECTURE.md`
(the routes; jobs on Kit's loop, the per-task output), the `script` skill (when to use a job, awaiting each step, what
blocks), `README.md`'s list and count, `test_project/outcomes.md` (the new outcome), `CHANGELOG.md` (Added).

## Risks

- **A job that awaits once then loops, or calls `world.step()`,** freezes the bridge as `execute_script` would, and no
  tool can read it meanwhile, since `get_job` runs on the same loop: accepted, named plainly in the description and
  the skill; once it ends, `get_job` gives its result as usual.
- **A job and a tool call change the stage at once** (a capture while the bake moves prims): accepted; Kit serialises
  them on its loop, and the skill says to let a job run alone, as its author's case does.
- **The finished job's result is lost when the next job starts:** accepted and documented; `get_job` reads it until
  then.

## Plan review

### Fit

The plan at `3d91ca2`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, with this repo's `fit-plan`
from branch `160-fit-plan`. The change's own question: does the job board serve #157's sweep, the bridge's own
coroutine with its manifest and a cancel that puts the stage back, as well as a user's script, without a second
mechanism later? Answers by the author, 2026-11-02, on the maintainer's delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | Generic routes, `/jobs/script`, `/jobs/get`, `/jobs/cancel`: paths are a one-way door, and a sweep is read through them too | taken |
| I2 | A `kind` on each job and its result a dict in its kind's shape, formatted by kind, so #157 needs no `get_sweep` | taken |
| I3 | A `cancelling` state holding the slot until the job's `finally` returns, the reason passed through `task.cancel`, and a synchronous teardown for shutdown, as `recording.shut_down` has | taken |
| I4 | Watch the stage's id on each update, as recordings do, instead of hooking two handlers, and make it opt-in per job | taken |
| I5 | A Kit-free `ovmcp/core/script.py` compiling with `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT`, telling awaiting code by `CO_COROUTINE`, shared with `/execute` in place of its indent wrapper | taken |
| I6 | One context-variable output router for `/execute` and jobs; a job's printed lines are its progress | taken |
| I7 | Take the issue's `file` parameter, so a bake script needn't pass through the agent's context | taken |
| I8 | MCP tasks left the core specification and SDK 2.3.0 has their types only; mirror a task's states so a later extension maps onto them | taken |
| I9 | `get_job(job_id="", wait=0..100)`, and `get_sim_state` naming a running job | taken |
| I10 | An outcome whose work outlasts 120 s, its `Calls:` expecting `run_script_job` | taken: step 4b |

Noticed on the way, for Round 1: the watchdog can't be read while a job blocks, and `world.step()` defers every asyncio
task in Kit 6.2 (Where it runs; the watchdog is dropped); `/execute` kept its `sys.stdout` swap (Output; I6 answers
it); the refusal was tested in `core/jobs.py` but designed in the handler (Steps; now in `core/script.py`); #158 has
no agreement comment yet (Compatibility).
