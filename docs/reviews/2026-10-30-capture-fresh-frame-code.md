---
subject: "Make a capture wait out the renderer's trail, so what was drawn just before shows (#57)"
base: main (765d51c)
head: 880a9f3
date: 2026-10-30
round: 1
tier: standard (one fresh reviewer on Claude, read only; findings checked against the code by the author)
verdict: clean
---

# Review: fresh frames before a capture

Read from the diff, each touched file, the approved plan `docs/plans/2026-10-30-capture-a-fresh-frame.md`, and Kit's
installed sources. No blocker or major; three minors, each fixed after the round, on top of `93cf057` (a test-only
change after the reviewed head, from the async live run below).

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_scenarios.py`, `_a_capture_at_once_holds_the_drawing` | The black-view refusal could never fire in `test_16_08`: it draws its zigzag for 5 s over HTTP, and the check's capture came about 0.5 s later with the zigzag still in view, so a black stage would pass the check and the renderer reset after a black capture would hide the trail | fixed in `b6d6f1a`: the check runs inside `DRAWN_THEN_CAPTURED`, after the last drawing has left the book and 10 frames have rendered, and the helper asserts it before any capture counts |
| F2 | minor | `README.md`, Known issues | The README, which is also PyPI's page, still listed #57's missed capture as a known issue | fixed in `bebe4f9`: the bullet is gone |
| F3 | minor | `docs/ARCHITECTURE.md`, Viewport Capture, "Fails at once" | No longer true for a viewport with no render texture yet: the fresh frames come first, and such a viewport delivers none, so `capture_viewport` and `inspect_prim` wait `FRAME_SECONDS` and fail as rendering no frame | fixed in `bebe4f9`: the bullet says they reach that check only after their fresh frames, and that recording still fails at once |

Refuted, each from the code:

- **Recording's opt-out:** `_record_tick` passes `fresh=False`, so its ticks keep their length and don't overlap
  more than they did; the opt-out has a source guard since (`9e59732`, improvement 1).
- **The bounded waits:** the fresh frames go through `capture.frames`, each frame bounded by `FRAME_SECONDS` and the
  call's budget, so the change adds no unbounded wait; `test_a_viewport_that_renders_nothing_schedules_no_capture`.
- **The budget check's order:** it moved after the frames, so frames that spend the budget start no capture whose
  file would come after the call; `test_the_budget_caps_the_fresh_frames` covers both a budget cut short mid-frames
  and one spent exactly.
- **`FRESH_FRAMES` leaking out of a live test:** the helper's own script puts it back in a `finally`, before the call
  answers, with `SET_LIMIT`'s token and 60 s undo behind it.
- **The `SET_LIMIT` move:** `test_integration.py`'s `_SHORTEN` and `_RESTORE` moved to `conftest.py` unchanged but
  for `seconds` renamed `value` and an `undo = None` default; `_shorten` uses them as before.
- **The new checks pass without the fix:** they don't; the as-shipped half failed in all 5 runs on `765d51c`'s bridge
  (Live run).
- **Eco Mode's mechanism:** a viewport Eco Mode has paused delivers no frame, and then the fresh frames fail after
  `FRAME_SECONDS` as the capture's own frame wait did before; the plan's run 4 saw no pause past 500 static frames.
- **Kit 107's API:** `next_viewport_frame_async` is in Isaac Sim 5.1's `omni.kit.viewport.utility` 1.1.2, as the
  settles have used it since #55.
- **The warning once:** `_next_frame`'s fallback to an app update warns once a session, where `_viewport_frames`
  warned on each call; the fallback itself still runs on every frame.

Improvements:

| Improvement | Answer |
|---|---|
| A source guard that recording's capture passes `fresh=False`, as `tests/test_logs.py` guards log hooks | taken in `9e59732`: `test_recording_captures_without_fresh_frames` reads `recording.py` and fails when a call to `capture_viewport_png` there doesn't pass `fresh=False`; checked to fail with it taken out |
| Print each capture's seconds beside its red pixels in `_a_capture_at_once_holds_the_drawing` | taken in `b6d6f1a` |

Not covered: bridge security, with no route, token or setting touched; Isaac Sim's GUI; Isaac Sim 5.x. The reviewer
ran neither the gate nor the live suites.

## Live run

Isaac Sim 6.2.0 (pip, headless, Windows) on port 8212, started by the coordinating session; the maintainer's Isaac Sim
on 8211 was not touched. `-k "test_02_01 or test_16_08 or test_16_09"` for the draw checks: `test_02_01` lights the
stage they need.

- **Before, `765d51c`'s bridge with the new tests, 5 runs on one Kit:** `test_16_08` and `test_16_09` failed in all 5,
  each on "a capture made just after the drawing doesn't hold it"; every capture held 0 red pixels, with and without
  the fresh-frame setting, which that bridge doesn't read.
- **After, warm, this branch's bridge (`880a9f3`'s tests), 3 runs:** 3 passed each time; no fresh frames 0 red pixels
  in every capture, as shipped 3364 (`isaacsim.util.debug_draw`) and 4160 (`omni.debugdraw`) in every capture.
- **Async rendering on** (`/app/asyncRendering` and its low-latency twin, through `execute_script`, as
  `isaacsim.core.throttling` does), 3 runs:
  - on `880a9f3`'s tests: run 1 passed, runs 2 and 3 failed on the no-wait half's own check, "every capture with no
    fresh frames held the drawing", where the renderer had kept up (it held the drawing in 3, 5, 3 and 5 captures of
    5); the as-shipped half held all 5 in every run that reached it. `93cf057` records those misses instead of
    requiring one;
  - on `93cf057`'s tests: 3 of 3 passed; as shipped, all 5 held in every run; no fresh frames missed 3 and 3, 1 and
    4, 0 and 4 of 5 (`isaacsim.util.debug_draw`, then `omni.debugdraw`).
- **Three cold starts, a fresh Kit each, both suites in full on `93cf057`'s tests:** 146 passed each time, in 124.0,
  129.7 and 119.3 s. With no fresh frames every capture missed (5 of 5, each extension); as shipped every capture held
  the drawing. `test_16_08` took 15.8, 16.3 and 15.7 s and `test_16_09` 15.1, 15.9 and 14.8 s; without them the suites
  took 93.1, 97.4 and 88.7 s, against 0.2.2's full runs of about 99 s, which included both tests' earlier forms.
- **Kit's log, each cold start:** four "Capture failed after 0.0 s: Kit captured nothing (wait_for_result gave [])"
  and three "Capture failed after 2.0 s: Kit wrote no whole image in 2 s after capturing ['LdrColor']". Both are
  `test_15e`'s forced failures: its first inspect of 4 angles through a fake capture whose result names nothing, then
  3 angles through one that names `LdrColor` but writes no file, with `FILE_SECONDS` set to 2. No slow-capture line.
- **Not shown:** Isaac Sim's GUI (async rendering there was run headless instead); Isaac Sim 5.x, which crashes in
  its own start on the test machine; a Kit app with only `omni.debugdraw`, such as USD Composer.
