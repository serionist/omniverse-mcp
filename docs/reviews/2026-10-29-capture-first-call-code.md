---
subject: "Bound the capture waits, and wait for segmentation by time after a stage opens (#27, #35)"
base: main (b818449)
head: 76a1649
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer on Claude Opus 5.5, read only; findings checked against the code by the author)
verdict: clean
---

# Review: bounded capture waits and segmentation after a stage opens

Read from the diff, each touched file, the plan, and Kit's installed sources (Isaac Sim 6.2, Kit 110; Isaac Sim 5.1,
Kit 107). No blocker or major; four minors, fixed in `d879791` after the branch was rebased onto `main` (`7afa9e4`,
#52), where `76a1649` became `ba3dc90`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/TOOLS.md` | `inspect_prim` "takes at most 80 s", but with `isolate=True` the restore's settle adds up to `CLEANUP_SECONDS` (10 s), so a slow renderer's call takes about 90 s; CHANGELOG and ARCHITECTURE.md already said so | fixed in `d879791`: "about 90 s at most: 80 s for the angles, then up to 10 s to restore `isolate`" |
| F2 | minor | `handlers/camera.py`, `plugin/skills/scene/SKILL.md` | The segmentation errors pointed at `get_logs(search="syntheticdata")`, but `search` matches only the message (`core/logs.py`): `omni.syntheticdata`'s own lines (channel `omni.syntheticdata.plugin`) and the bridge's "Instance segmentation gave no data" line lack the word, so an assistant following the advice sees nothing | fixed in `d879791`: the errors and the skill point at `get_logs(channel="syntheticdata")`; the skill and ARCHITECTURE.md add `search="segmentation"` and `search="capture"` for the bridge's own lines |
| F3 | minor | `tests/test_integration.py`, `_SHORTEN` | The 60 s self-heal undid a limit by its value, not by whose change it was: run `-k test_15f` four times within a minute and the first run's timer puts `FRAME_SECONDS` back to 30 inside the fourth, which then times out for no real reason | fixed in `d879791`: a token, as `_UPDATES_OFF` has; the cleanup puts the default back and clears the token |
| F4 | minor | `tests/test_capture.py`, `test_frames_without_a_budget_share_one_of_frame_seconds` | Timed real sleeps with a 0.1 s margin across two 0.2 s sleeps: a stall on a busy runner fails the required `CI` check | fixed in `d879791`: `frames()` takes a `clock` for its shared budget, and the test runs on a fake one; only the frame that never comes waits in real time |

Refuted, or real only as a risk, each from the code:

- **A Python callback Kit could call from a worker thread** (#5's shape): not a failure on Isaac Sim, which sets
  `asyncRendering = false` (`apps/isaacsim.exp.base.kit`; `--/app/asyncRendering=0` in its app setup), and
  `omni.syntheticdata` switches async rendering off when it loads (`SyntheticData.disable_async_rendering`); `main`'s
  `_reset_renderer` already waited the same way, and the live suites passed. A risk: every settle now observes
  `NEW_FRAME` through omni.usd's `_next_frame_async` as an immediate observer, which Kit 110's
  `rtx_settings_window.py` says fires on the renderer thread, so the branch widens that exposure from
  `viewport_light` to every settle. A Kit app with async rendering on and without `omni.syntheticdata` is not shown;
  recorded in ARCHITECTURE.md's Threading Model and the plan's Risks (improvement 2).
- **Cancelling Kit's futures:** safe; each is set only if not done (`Capture._set_completed`, Kit 107 and 110;
  `_next_frame_async`; `next_update_async`).
- **An unbounded wait left:** after `Call` is made, each wait runs under its budget; before it, only synchronous work
  and one update. `wait_for_rendered_frames` appears only in a comment and the docs; no thread, no executor.
- **The total against the client's timeout:** 80 s plus 10 s, with `tests/test_capture.py` pinning 110 s within
  `BridgeClient`'s default 120 s.
- **#27's fix on a new stage:** `SyntheticData.reset()` clears `_activatedNodePaths` (0.6.17 and 0.6.13), so enabling
  the sensor again takes; `get_stage_id` exists on Kit 107.
- **Failing at once on an empty result hits normal captures on Kit 107:** it doesn't; `RenderCapture` gives a list of
  what it captured, and the file capture asks for `["LdrColor"]`.
- **Eco Mode or isolate left changed:** both are put back on every path (`_reset_renderer`'s `finally`;
  `handle_camera_inspect`'s `finally`, including after a `NoFrameError` in the settle after hiding, where the restore
  skips its settle).
- **`Call`, "Not captured" and `SegmentationWaits` against the plan:** only `NoFrameError` and `OutOfTimeError` stop a
  call; the message is kept, not the exception; keyed by stage id and render product; a poll cut short by the call's
  time records no failure.
- **A new live test that passes on `main`:** each fails there (15c: four reads, segmentation dropped; 15d: no
  `segmentation_error`; 15e: 4 x 10 s, past the client's 30 s; 15f: `main` has no `ovmcp.core.capture`, so nothing is
  patched, and `set_camera` hangs).
- **The tool contract:** unchanged; `mcp-tools.json` untouched, `segmentation_error` optional. CHANGELOG, README,
  AGENTS.md's Traps (147 lines) and the writing rules hold; `RUF013` left `_utils.py`'s per-file ignores, which only
  tightens.

Improvements:

| Improvement | Answer |
|---|---|
| Give `test_15f` an `isolate=True` inspect, and check the hidden prims come back: the path where the settle after hiding gives no frame and the restore skips its settle had no test | taken in `d879791`: with updates off, both angles are "Not captured" within `FRAME_SECONDS` plus 5 s, and every prim under `/World` renders as it did before |
| Record the immediate `NEW_FRAME` observer's thread in the plan's Risks and in ARCHITECTURE.md's Threading Model; in the PR, name a Kit app with async rendering on and without `omni.syntheticdata` (USD Composer) among what the live runs couldn't show | taken in `d879791` for the plan and ARCHITECTURE.md; the PR's part is the main session's, with the live runs |

Not covered: bridge security, with no route, token or setting touched; the harness only through `pyproject.toml`,
whose one change (`RUF013` out of `_utils.py`'s ignores) is stricter. The reviewer ran neither the gate nor the live
suites, and read no PR text.

Isaac Sim 5.x is untested live: 5.1 crashed in its own start on the test machine, before any extension loaded, so
Q6's run on it could not happen. Kit 107's sources were read instead; ARCHITECTURE.md's Viewport Capture says so.

## Live run

Isaac Sim 6.2.0 (pip, headless, Windows, RTX 5090) on port 8212, started for these runs; the maintainer's Isaac Sim on
8211 was not touched. `-k "not test_10_ and not test_14_"`: this branch doesn't carry #5's fix.

- **Three cold starts on `c96fb3f`, each a fresh Kit, the live suites first:** 121 passed in each; the only failures
  were #7's three `draw_debug` scenarios, which #53 fixed on `main` since. `test_13`, `test_17_03` (now `test_17_04`, renumbered after #53 added a `test_17_03` of its own) and `test_22_01`
  passed every time; `test_15c` waited for segmentation through 16 reads.
- **Kit's log, each run:** segmentation's first data came 14 updates (0.08 to 0.11 s) after it was enabled at
  startup, and 2 updates (0.03 s) after `test_17_02`'s new stage, so the reset after a stage opens was real but short
  here. The other `[MCP Bridge]` capture lines were the tests' own patched failures: `test_15d`'s segmentation that
  never comes (no data in 652 to 1,006 updates, 5 s), `test_15e`'s empty results (`wait_for_result gave []`, failing at
  once) and its missing file (no whole image in 2 s). No other capture failed, and no first frame was slow enough to
  log, so `FRAME_SECONDS` stays at 30 (Q1).
- **The new tests against `main`'s extension** (`dde08e4`): `test_15c`, `test_15d`, `test_15e` and `test_15f` each
  failed (`test_15f` past the client's 30 s); `test_17_03` failed too, though run alone it lacked `test_17_02`'s new
  stage, so that failure isn't its bug.
- **Rebased on `main` with #53 (`2ebfef0`), with nothing excluded but the robot phases:** two full runs on one fresh
  Kit, with the drawing tests twice between them: 129 passed in each, none failed. An earlier session on the same
  build had one `test_16_09` miss (no zigzag in the capture) and then hung at `test_16_02` in its second full run, inside
  RTX's settings lock, not in the bridge; the same sequence ran clean afterwards on `main`'s bridge and on this one, so
  it is recorded as #54.
- **Not shown:** Isaac Sim 5.x (5.1 crashes in its own start on this machine, before any bridge loads); a Kit app with
  async rendering on and without `omni.syntheticdata`, such as USD Composer; the 14-angle `inspect_prim` timing on
  `main` against the branch.

## Checks

- `uv run tools/gate.py full` passed on `76a1649` (732 tests, 93.96%) and on `d879791` (740 tests, 94.13%).
- The bridge's capture handlers, against stub Kit modules and usd-core's `pxr`, by hand: late segmentation is waited
  for; segmentation that never comes gives its error, then "as before"; an empty result fails each angle at once;
  Kit 110's missing file fails after the file wait; with no frames, `set_camera`, `look_at_prim` and `viewport_light`
  answer, `inspect_prim` stops after its first angle, and isolate's prims come back after one frame wait; a spent call
  budget makes the rest "Not captured".
