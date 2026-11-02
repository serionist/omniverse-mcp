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

- `run_script_job(code)` starts the script as a job and answers its id at once;
- `get_job(job_id)` gives its state (running, done, failed, cancelled), elapsed time, its progress lines, and, once it
  ends, its result, stdout and error, as `execute_script` gives them;
- `cancel_job(job_id)` cancels it at its next `await`;
- one job at a time: a second start is refused, naming the one running;
- a script that never awaits is refused before it starts, since it would block Kit whatever runs it.

In scope: three tools, their routes, a Kit-free job registry the sweep can reuse, docs, the `script` skill.
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

The refusal reads the compiled code: a script that compiles as plain Python, or whose async form contains no `await`,
is refused with the reason and the fix (`await omni.kit.app.get_app().next_update_async()` in its loop). A script that
awaits only once and then loops without awaiting still blocks; the description and the `script` skill say so, and a
watchdog notes it in `get_job`: the job's last progress line and the time since Kit's last update.

### The extension

- **`ovmcp/core/jobs.py`** (Kit-free): `Job` (id, label, state, started, ended, progress lines kept to the last 200
  with a count of all, result, error); `JobBoard` with `start(label, coroutine_factory)` refusing a second running job,
  `get(id)`, `cancel(id)`, and the finished jobs kept until the next start, so an answer is read once a job ends
  however late. A job's coroutine is given `progress(text)`; it is generic, so #157's sweep starts its own coroutine
  through the same board.
- **`handlers/jobs.py`:** `handle_job_start(body)` (`/script/job/start`) compiles the code as `/execute` does, refuses
  it as above, builds the same namespace (`omni`, `carb`, the `pxr` modules, `mcp`) plus `progress`, and starts it on
  the board with `asyncio.ensure_future`, so the job outlives the HTTP request. `handle_job_get` (`/script/job/get`)
  and `handle_job_cancel` (`/script/job/cancel`).
- **Output:** `print` inside a job writes to the job's own buffer, not to `sys.stdout`: the bridge swaps
  `sys.stdout` for one `/execute` call, and a job that held the swap across its awaits would take every other
  request's output. A context variable routes writes to the running task's buffer; anything else goes to Kit's
  stdout as before.
- **The result:** `result` as `/execute` reads it, JSON or its `str`; a large one is written to a file by the server,
  as long text is today.
- **Stage changes:** a `new_scene` or `open_scene` while a job runs cancels it, with the reason in its error, since its
  prims are gone.
- **Shutdown:** the extension's `on_shutdown` cancels a running job.

### The server

- **`client.job_start(code)`, `job_get(id)`, `job_cancel(id)`;** `tools/misc.py`:
  - `run_script_job(code)`: `RUNS`, as `execute_script`;
  - `get_job(job_id)`: `READS`;
  - `cancel_job(job_id)`: `EDITS`.
- **Answers:** `run_script_job`: `Job j3 started; read it with get_job("j3")`. `get_job`: `state = running`,
  `elapsed = 4m 12s`, `progress = 37 of 150 stacks settled` (the last line, and the last 20 with a count), then the
  result, stdout and error once it ends, through `text_response` so a long one goes to a file.
- **`execute_script`'s description** names `run_script_job` for anything that may outlast 120 s.

### Alternatives

- **MCP's own tasks** (the 2025-11-25 specification: a task-augmented `tools/call`, then `tasks/get`, `tasks/result`,
  `tasks/cancel`; `mcp_types` in the pinned SDK carries them): left for now. The client decides to make a call a task,
  and the clients this server serves don't yet; three tools work in every client. A later issue can add task support
  once Claude Code makes such calls.
- **`execute_script(..., background=True)`:** one tool fewer, but its answer would mean two things, and reading and
  cancelling still need tools of their own.
- **A separate headless Isaac Sim for each job:** the issue's alternative; about 90 s to start and a second GPU
  process.
- **Run plain loops by stepping them ourselves:** no; nothing outside a script can interleave its loop with Kit's
  updates.

## Compatibility

**One-way door: the tool contract.** Three new tools and three new routes: additive; `execute_script` keeps its
parameters, only its description changes. The maintainer agreed in #158's thread (posted from the maintainer's chat
decisions, 2026-11-02, before the PR). An older extension answers the unknown routes with the install advice.

The bridge's security is unchanged: the routes need the token, refuse an `Origin` and a foreign `Host`, as `/execute`
does, and run nothing `/execute` can't.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `ovmcp/core/jobs.py`, tests first | `tests/test_jobs.py`: start, one at a time, progress kept to 200 with the count, cancel, a failure's error, a finished job read late, the refusal of code without `await` |
| 2 | `handlers/jobs.py`, the routes, the per-task output, the stage-change and shutdown cancels | `tests/test_jobs_handler.py` with the Kit fakes: a job's prints in its buffer while an `/execute` call's go to its own; a new stage cancels |
| 3 | The client, the three tools, `execute_script`'s description; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | Docs, the `script` skill | review |
| 5 | Live: a job that plays the timeline and steps a falling box for 150 s of updates while `get_prim_bounds` and `capture_viewport` answer; its progress read twice; its result the box's final pose; a second job cancelled mid-way; a plain-loop script refused | `tests/test_integration.py`, on Isaac Sim 6.2 at 8212 |
| 6 | `uv run tools/gate.py full`, `review-code`, the PR | the review record |

## Tests

- Unit (CI): steps 1 to 3.
- Live: step 5, with the suites on a Z-up and a Y-up stage; a 10-minute job by hand once, as the issue's Done when
  asks, its progress and result read, and Kit answering throughout.
- What neither shows: bechtel-mvp's own bake, which isn't written; USD Composer, where the loop is the same Kit loop.

## Docs

`docs/TOOLS.md` (the three tools, `execute_script`'s pointer), `docs/ARCHITECTURE.md` (the routes; jobs on Kit's loop,
the per-task output), the `script` skill (when to use a job, awaiting each step, progress), `README.md`'s list and
count, `CHANGELOG.md` (Added).

## Risks

- **A job that awaits once then loops** freezes Kit as `execute_script` would: accepted, named in the description and
  the skill; the watchdog line tells an agent what happened.
- **A job and a tool call change the stage at once** (a capture while the bake moves prims): accepted; Kit serialises
  them on its loop, and the skill says to let a job run alone, as its author's case does.
- **The finished job's result is lost when the next job starts:** accepted and documented; `get_job` reads it until
  then.

## Plan review

None yet.
