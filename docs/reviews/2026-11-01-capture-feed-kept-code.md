---
subject: "Keep the capture feed between calls, and name Kit's renderer hang when a call meets it (#114)"
base: main (bd54da7)
head: de25baf
date: 2026-11-01
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split; no blocker or major, so no refuter"
verdict: needs-fixes
---

# Review: Keep the capture feed between calls, and name Kit's renderer hang when a call meets it

Read from the branch's diff against `main` at `bd54da7` by two fresh reviewers, read only, each with its own lenses:

| Reviewer | Lenses |
|---|---|
| (a) | implementation, kit-main-thread, bridge-security, compatibility, simplicity, on the extension |
| (b) | plan-and-intent, tool-contract, tests, docs-freshness, harness-integrity |

(a) ran two offline checks with `tests/test_camera_feed.py`'s fake Kit and read Kit's own sources in Isaac Sim 5.1
(Kit 107) and 6.2 (Kit 110); (b) reproduced its F3 with a scratch socket. Six minors and no blocker or major, so no
second round; the first live run added one more (L1). The fixes are on the branch after `de25baf`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `camera_feed.py` `CameraFeed.first_frame`, `drop` | A feed let go during a call (a `SAVING` or `CLOSING` while it works) failed its waits at once only in `next_frame` and `schedule`: a fresh feed's `first_frame` polled its whole 30 s, and a capture already scheduled lost its delegate when `drop` emptied `_pending`, so `capture_png`'s `wait_for_result` waited 30 s too. ARCHITECTURE.md said it fails at once | fixed in `dfde329`: `first_frame` checks the feed as it polls, and a scheduled capture's result goes through `CameraFeed.result_of`, which checks it every 0.05 s. `test_a_feed_let_go_during_a_call_fails_its_waits_at_once`, which fails before it |
| F2 | minor | `camera_feed.py` `release` with `_on_saving` | Kit's Save during any `release` wrote the render product into the file: the caller lets the feed go first, `release` deletes the render product only after two updates, and in between `_on_saving` found no kept feed. The idle release, a failed call's and `release_kept` all took that path. Rare: a window of two updates | fixed in `dfde329`: a feed being released stays in a `_releasing` set until its render product goes, and `SAVING` deletes it at once. `test_kits_save_during_a_release_deletes_its_render_product_before_it_writes` |
| F3 | minor | `CHANGELOG.md`, `docs/TOOLS.md`, `docs/ARCHITECTURE.md` | Kit's File > Save Flattened As, leaving the session layer out, exports `Usd.Stage.Open(root, anon)` with no `SAVING` event (`omni.kit.window.file` in Kit 107 and 110), so within 30 s of a capture it writes the kept render product; the docs said no file holds it | fixed in `e411a44`: ARCHITECTURE.md names it beside the `execute_script` caveat; TOOLS.md and CHANGELOG no longer claim no file holds it |
| F4 | minor | `plugin/skills/scene/SKILL.md` | G5 said the scene skill tells what the hang looks like and what a kept feed costs; it gained only the camera-move row | fixed in `e411a44`: trap rows for "stopped answering" and the restart, and the 30 s cost |
| F5 | minor | `docs/TOOLS.md`, `execute_script` | It said "the call gives up after 120 s, and the script runs on"; a blocking script past 125 s now gets "Kit ... stopped answering" and later calls fail in 5 s until it ends (Q3's accepted cost) | fixed in `e411a44` |
| F6 | minor | `client.py` `_answers` | A refused connection counted as silence, so while a user restarted a hung Kit every call said "still silent ... restart it" in about 2 s instead of today's connection error | fixed in `c0eddb0`: a refused health check clears the mark and the connection error stands. `test_a_port_nothing_listens_on_lets_the_connection_error_stand` |
| L1 | minor | `tests/test_scenarios.py` `test_26_04` | Live, the kept capture against a fresh one measured 0.16 to 0.61 mean and p99 4 to 10 after a camera switch, 0.42 to 0.49 and 7 to 8 after a prim moved, against the test's bound of K7's 0.2 and 4, so it failed every run. A probe with the images kept (`114-moveghost.py`) found no ghost: every pixel differing by more than 8 sat at the cube's new place and none of its old place differed; the difference was edge and face noise, 0.24 straight after the move and 0.16 to 0.18 120 frames later, against 0.09 between two fresh feeds and 1.9 for the move itself. K7's bound came from a still view | fixed in `09affd9`: no pixel of the cube's old place differs by more than 8, at least 80 % of its new place shows it, mean at most 1.0 and p99 at most 12, and the kept capture within a third of the change itself; K19 in the plan. Its ghost check, first the old place's pixels differing by more than 8, failed in the suites on a grid line's noise (live step 3); since `6ca2155` it counts the cube's colour at its old place (step 4) |

**Refuted,** each from the code, Kit's sources or a scratch check:
- **`SAVING` off Kit's main thread:** NVIDIA's own `omni.kit.widget.viewport` writes USD in `SETTINGS_SAVING` on Kit 107 and
  110, omni.usd's test shows the events dispatched synchronously within `save_stage()`, and the result future is set
  on the loop's thread. Live, `test_26_05`'s Kit-save leg passed.
- **A deadlock on the lock, which isn't re-entrant:** only the five `@serial(_viewport)` handlers, `_release_idle`,
  `release_kept` and `without_kept_feed` take it, and nothing they call takes it again.
- **The timer racing a call:** `take()` and `let_go()` bump the generation, which `_release_idle` checks under the lock.
- **A feed in doubt kept:** `healthy` is set only on the try's last line; every `inspect_prim` angle error marks it.
- **#51's E16 through `discard` at `CLOSING`:** omni.syntheticdata resets its registry at `CLOSING` and `OPENED`, and
  the leftovers delete the render product only once a stage is open.
- **Kit 107's APIs, a leftover deletion dirtying the file, a resized feed's first frame, bridge security:** each checked
  and sound; the health check sends the token only to the configured host and port.
- **The changed live tests loosened:** no; the lines removed are docstrings and imports, `release_kept` runs the same
  `release`, and each still fails on a leak. **New tests that can't fail:** each fails without the change.
- **The silent mark's thread safety, a connect timeout taken for a hang, the health check resending, conftest's guard,
  the new timer and socket tests' timing, the contract (unchanged, `readOnlyHint` kept), the harness:** all sound.

**Improvements,** all taken, in `dfde329`, `c0eddb0` and `e411a44`:
- `SAVING`'s and shutdown's teardown share `release`'s steps, so one that raises can't skip the drop and deletion.
- `_release_idle` calls `_release_kept`.
- A kept feed whose `aim` raises is let go and discarded.
- `ovmcp_capture`'s prefix is asserted again.
- A client test of a timeout on a kept-alive connection.
- The still-silent message's wording.
- One number for segmentation's idle cost.
- `_assert_nothing_left`'s docstring and AGENTS.md's segmentation row follow the kept feed.

Outside this change: `test_capture.py::test_the_waits_read_their_seconds_when_called` is flaky on Windows before
Python 3.13 (#128), and `test_06_10` fails when Kit simulates slower than real time (#127); each has its own fix.

## Live run

My own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, the branch's extension copied in,
with another session's Isaac Sim apps keeping the GPU 60 to 80 % busy throughout. `105-stage.py` set the stage's up
axis before each step.

| Step | Extension | Stage | What ran | Result |
|---|---|---|---|---|
| 1 | `de25baf` | Z-up | both live suites whole | 200 passed, 2 failed: `test_26_04` (L1) and `test_06_10`, which failed on main's extension too under the same load (#127, fixed on main since) |
| 2 | `de25baf` | Z-up, Y-up | the new and changed tests by `-k` | `test_26_03` (one `createViewport`, two assignments) and `test_26_05` (the bridge's saves and Kit's own) passed on both; `test_26_04` failed (L1); `test_12d`, `13b`, `15e`, `15f` failed only because the `-k` left out the test that makes their cube, and passed in step 1 |
| 3 | `e411a44` | Z-up, Y-up | both live suites whole, `-s` | 201 passed on each, `test_26_04` failing its first ghost check: 36 and 9 of the old place's 1,694 pixels differed by more than 8 |
| 4 | `e411a44`, the test instrumented | Z-up | `test_scenarios.py` | the images: the kept capture shows no cube colour at its old place (0 of 1,694); the flagged pixels run along a grid line behind the old edge, by up to 37. The check now counts the cube's colour there (`6ca2155`) |
| 5 | `6ca2155` | Z-up, Y-up | `test_scenarios.py` | 129 passed on each: old place 1,691 px, no ghost; the switch 0.31 to 0.35 mean, the move 0.40 to 0.57, against the change's 34 and 4.4 to 4.6 |
| 6 | `6ca2155` | Y-up | the probe's `--mode inspect`, 600 real `inspect_prim` calls, 0.5 s apart | all 600 succeeded in 12 minutes, 0.72 s each; Kit's log gained one `createViewport` and one capture view assignment in all, one capture render product throughout, memory flat. Round 1 hung at call 416 on main's extension, which makes a view a call |
| 7 | `6ca2155` | Y-up | 600 `capture_viewport` calls alternating `/OmniverseKit_Persp` and `/OmniverseKit_Top` at 320x240 | all 600 succeeded in 6.3 minutes, 0.33 s each; one `createViewport`, two view assignments (the feed made, its first switch) |

Kit hung once, in an extra run of both suites with the instrumented test, in `test_16_08`, which releases the kept
feed before each read and so makes a view a capture: the same signature as every hang (the main thread busy, 9 CPU
seconds in 11.8, the log silent after a capture feed's view set-up), at view 185 of that Kit. The live run's own guard
named it with the server's new message: "Kit at 127.0.0.1:8212 stopped answering ... /health none in 5 s".

Not shown: Isaac Sim 5.x (Kit 107: its APIs read from the sources only), Linux, USD Composer, a GPU of its own, and the
AI scenario phases, which run with every phase in the release pass on the release's wheel.
