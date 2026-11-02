---
title: Run a long script as a job that Kit keeps rendering through, read and cancelled by id, a change to the tool contract
issue: "#158"
status: approved
approved_by: serionist (delegated to the author, 2026-11-02)
approved_at: 2026-11-02
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
  returns early only when the job ends or changes state, so a bake printing a line per stack doesn't bring an agent
  back every few seconds (fit I8, I9; round 1, P3); each read gives the lines since that job's last read (round 1,
  I12);
- `cancel_job(job_id)` cancels it at its next `await`, and the job counts as running until its own cleanup has
  finished (fit I3); a second `cancel_job` cancels again, for a script whose bare `except:` swallowed the first, and
  `get_job` says how long a job has been cancelling (round 1, P7);
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

- **`ovmcp/core/script.py`** (Kit-free, fit I5): `compile_script(code, filename)` gives the code object and whether
  it awaits; `run(code, namespace)` runs it as `types.FunctionType(code, namespace)()`, as the asyncio REPL does,
  awaiting it when it is a coroutine, so no new file calls `exec` (ruff's S102, which the ratchet forbids adding;
  `misc.py`'s entry can go; round 1, I11). `/execute` uses both, in place of its `textwrap.indent` wrapper, which
  changed multi-line strings' contents and shifted traceback lines by one. A script with a top-level `return`, which
  the wrapper ran and `PyCF_ALLOW_TOP_LEVEL_AWAIT` refuses, still runs: that one `SyntaxError` falls back to the
  wrapper, so no `execute_script` call changes (round 1, P2). A `file` is read as bytes and compiled with its own path
  as the file name, so its encoding follows Python's source rules and tracebacks show its lines (round 1, I13).
- **`ovmcp/core/output.py`** (Kit-free, fit I6): one context-variable router installed as `sys.stdout` and
  `sys.stderr`, writing to the current task's buffer, or to the stream beneath when the task has none, and passing
  everything else (`isatty`, `fileno`, `encoding`) to that stream, as Kit's own `StreamInterceptor` does. A buffer
  closes when its call or job ends, so a task an `/execute` script left behind writes to Kit's stream, as today, not
  into a buffer nobody reads. `on_shutdown` puts the stream beneath back while the router is still on top, so Kit's
  own restore at exit, and turning the bridge off and on, find what they expect (round 1, P1). `/execute` drops its
  `sys.stdout` swap, so an `/execute` call's output and a job's never mix. A job's printed lines are its progress: no
  `progress()` to learn.
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
  can't await; the board calls it, cancels the task, and refuses any start after it, as recording's `_state.closed`
  does, so a start in flight during a reload can't leave a job no route can reach (round 1, I16).

### The server

- **`client.job_script(code, file)`, `job_get(id, wait)`, `job_cancel(id)`;** `tools/misc.py`:
  - `run_script_job(code="", file="")`: `RUNS`, as `execute_script`;
  - `get_job(job_id="", wait=0)`: `READS`, `wait` 0 to 100 s, under the server's 120 s;
  - `cancel_job(job_id)`: `EDITS`.
- **Answers:** `run_script_job`: `Job j3 started (script); read it with get_job("j3")`. `get_job`:
  `state = working`, `elapsed = 4m 12s`, `last = 37 of 150 stacks settled` and the lines since the last read with the
  count of all, then the result in its kind's form once it ends (a script's: return value, stdout, stderr, saying when
  the stdout kept is the last 200 lines; a sweep's later: its manifest), through `text_response` so a long one goes to
  a file.
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
additive; `execute_script` keeps its parameters and every script it ran, a top-level `return` included; its
description changes, and its output and traceback lines come through the shared compiler and router, the same text
but for a traceback's line numbers, which now match the script.
`get_sim_state` adds a `job` line. The maintainer agreed in #158's thread (posted from the maintainer's chat
decisions, 2026-11-02, before the PR). An older extension answers the unknown routes with the install advice.

The bridge's security is unchanged: the routes need the token, refuse an `Origin` and a foreign `Host`, as `/execute`
does, and run nothing `/execute` can't. `file` reads a path on Kit's machine, as a script given to `/execute` already
can.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/script.py` and `ovmcp/core/output.py`, tests first; `/execute` moved onto both | `tests/test_script.py`: awaiting and plain code told apart, a multi-line string kept whole, traceback lines right, a top-level `return` still run, a file's encoding and line numbers; `tests/test_output.py`: two tasks' writes to their own buffers, a task without one to the stream, a closed buffer's later writes to the stream, attributes passed through, the stream put back; `tests/test_misc_handler.py`, new for `/execute` (round 1, P6): a plain and an awaiting script, `result`, stdout and stderr, an error's traceback line, written first against today's handler so the move keeps them |
| 2 | `ovmcp/core/jobs.py`, tests first | `tests/test_jobs.py`: start, one at a time, a cancelling job holding the slot until its `finally` returns, the reason passed, lines kept to 200 with the count, a failure's error, a finished job read late, `get("")`, a teardown called at shutdown |
| 3 | `handlers/jobs.py`, the routes, the code-or-file start, `wait`, the stage watch, the shutdown teardown, `get_sim_state`'s line | `tests/test_jobs_handler.py` with the Kit fakes: a job's prints in its buffer while an `/execute` call's go to its own; a watching job cancelled by a stage change and a script job not; a plain script refused |
| 4 | The client, the three tools, `execute_script`'s description; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4b | An outcome in `test_project/outcomes.md` whose work outlasts 120 s, `Calls: no execute_script`, with `run_script_job` named in the header's expected tool paths, so the pointer in `execute_script`'s description is shown to steer agents (fit I10); `test_project/assistant.md`, whose brief rules out code that waits on Kit, says a job awaiting each update is the way to run long work (round 1, P5) | an outcome run |
| 4c | Docs, the `script` skill | review |
| 5 | Live: a job that plays the timeline and steps a falling box for a few seconds of updates while `get_prim_bounds` and `capture_viewport` answer, since the route answers at once and seconds prove the job runs apart from the call (round 1, I15); its progress read twice; its result the box's final pose; a second job cancelled mid-way; a plain-loop script refused | `tests/test_integration.py`, on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 4.
- Live: step 5, with the suites on a Z-up and a Y-up stage; a 10-minute job by hand once, as the issue's Done when
  asks, its progress and result read, and Kit answering throughout.
- What neither shows: bechtel-mvp's own bake, which isn't written; USD Composer, where the loop is the same Kit loop;
  Isaac Sim 5.x (Kit 107), whose kernel's stream handling isn't on this machine, and Linux (round 1, I14).

## Docs

`docs/TOOLS.md` (the three tools, `execute_script`'s pointer, `get_sim_state`'s `job` line), `docs/ARCHITECTURE.md`
(the routes; jobs on Kit's loop, the per-task output; its lines 289 and 341 on the wrapper and the `StringIO` swap this
removes), `AGENTS.md`'s `ovmcp/core` row (script, output, jobs), the code-running tools to keep asking before in
`docs/SETUP.md:67`, `README.md`'s Security section and `SECURITY.md:27`, which now name `run_script_job` beside
`execute_script` (round 1, P4), the `script` skill (when to use a job, awaiting each step, what blocks, a swallowed
cancel), `README.md`'s list and count, `test_project/outcomes.md` (the new outcome) and `assistant.md`, `CHANGELOG.md`
(Added).

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

### Round 1

**How:** one fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, read only, every lens, at `66585d2`, with
`task.cancel(msg)` and `PyCF_ALLOW_TOP_LEVEL_AWAIT` checked on Python 3.11 and 3.12. **Verdict:** approved. **Now:**
every finding fixed, I11 to I16 taken, and the plan approved on the maintainer's delegation.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | The router, installed once, never came off: Kit's own restore at exit checks for its `StreamInterceptor` and skipped, a reload stacked a second router, and a task an `/execute` script left behind printed into a buffer nobody read | fixed: attributes passed through, buffers closed at their call's end, the stream put back at shutdown; tests for each |
| P2 | minor | A top-level `return`, which the wrapper ran, is a `SyntaxError` under `PyCF_ALLOW_TOP_LEVEL_AWAIT`, against Compatibility's "the same text" | fixed: that one error falls back to the wrapper; tested |
| P3 | minor | `wait` returned on any new line, so a bake printing per stack brought an agent back every few seconds | fixed: early only on the job's end or a state change |
| P4 | minor | The security docs name `execute_script` as the code-running tool to keep asking before; `run_script_job` runs code too | fixed: `docs/SETUP.md`, the README's Security, `SECURITY.md`, `AGENTS.md`'s core row and `ARCHITECTURE.md`'s two lines in Docs |
| P5 | minor | The outcome agent's brief rules out code that waits on Kit, so the new outcome would measure the brief, not the pointer | fixed: `assistant.md` names a job for long work; `Calls:` stays `no execute_script` with the tool in the header's paths |
| P6 | minor | `/execute` has no CI test, so "its existing tests unchanged" proved nothing | fixed: `tests/test_misc_handler.py` for `/execute`, written against today's handler first |
| P7 | minor | A bare `except:` swallowing the cancel keeps the job cancelling and the only slot held | fixed: a second cancel cancels again; `get_job` gives the time spent cancelling; the skill says so |

**Refuted:**
- **A way past the token, `Origin` or `Host` checks:** `refusal()` runs before the route lookup for every path, and
  the routes join the same table.
- **`file` widens access:** `/execute` already runs any code; the token is the boundary.
- **A blocking job is a new hang:** `execute_script` does the same today; Risks names it.
- **`task.cancel(msg)` deprecated or its message lost:** run on 3.11 and 3.12 with `-W error`, it reaches the job's
  `except` with no warning.
- **A job's and a tool's captures interleave on the kept feed:** `camera_feed.py`'s viewport lock runs them in turn.
- **`cancel_job` should be `DESTROYS`:** `stop_recording` and `sim_control` are `EDITS`.
- **`get_job(wait=100)` blocks other calls:** it delays them through the client's lock, and the case makes one call at
  a time.
- **Noticed on the way:** the watchdog (answered in "Where it runs"), the `sys.stdout` swap (fit I6 and P1), the
  refusal's tests (now `core/script.py`'s), the agreement (posted before the PR).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I11 | Run the code as `types.FunctionType(code, namespace)()`, as the asyncio REPL does, so no new file calls `exec` and `misc.py`'s S102 entry can go | taken |
| I12 | Each `get_job` read gives the lines since that job's last read, and says when a script's stdout is capped at 200 lines | taken |
| I13 | Read `file` as bytes and compile it with its own path, for its encoding and its traceback lines | taken |
| I14 | Name Isaac Sim 5.x and Linux in what neither shows | taken |
| I15 | Shorten step 5's job to seconds: the route answers at once, and the 10-minute run by hand covers length | taken |
| I16 | The board refuses a start after shutdown, as recording's `_state.closed` does | taken |

**Not covered:** P1's shutdown effect is read from Kit 110's kernel source, not seen in a running Kit; Kit 107's kernel
isn't on this machine.
