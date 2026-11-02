---
subject: "Record through the kept capture feed, so a recording sets up no new RTX view (#141)"
base: main (8a20cbc)
head: cda9822
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; three minors, so no second round"
verdict: clean
---

# Review: Record through the kept capture feed, so a recording sets up no new RTX view

Read from the branch's diff against `main` at `8a20cbc` (17 files, about 1,040 lines with the plan) by one fresh
reviewer, read only, with every lens, against the approved plan `docs/plans/2026-11-02-recording-kept-feed.md`. It
found the code as planned, with one departure (F3), and the start line's "kept up to 30 s" for the plan's "kept 30 s",
the more exact wording. Three minors, fixed after `cda9822`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_scenarios.py`, `test_17_08` | With one name for every feed, `_kept_feeds()` also lists the feed the recording borrowed, so `(kept,) = self._kept_feeds()` after a capture made during the recording raised `ValueError` on a real Kit; the first live run showed it too | fixed: the kept feed is the one that isn't the recording's render product; `_kept_feeds`' docstring says it lists every feed. `test_17_08` passed live after |
| F2 | minor | `tests/test_recording_handler.py`, `test_a_forced_start_ends_the_running_recording_first` | Its comment and plan step 2 say the old feed is handed back before the new one borrows, but the fake logged lend and hand-back in separate lists, so a `_start` that lent before the forced end, setting up a view at the same size, still passed | fixed: the fake logs both in one ordered list, and the test asserts lent, handed back, lent |
| F3 | minor | `camera_feed.py`, `hand_back` | `_kept.closed` was read only before `async with lock`, which waits behind a capture already queued as the lock frees: a shutdown during that capture let the stop keep the feed and observe the stage again for an unloaded module, round 1 P2's case through a narrower window | fixed: `kept` reads `closed` again under the lock, and a stop after shutdown tears down with `let_go_now`, not `release`. `test_a_stop_queued_behind_a_capture_during_which_the_extension_shuts_down_keeps_nothing` queues a capture, shuts down inside it, and fails without the fix |

**Refuted,** each from the code or #114's measurements:
- **A lent, segmented feed's graphs freed at a stage change trip omni.syntheticdata:** omni.syntheticdata resets its
  registry at `CLOSING` (#114's S6), so `_free_segmentation_graphs` pops nothing, as `discard` did.
- **`hand_back` deadlocks on `_viewport`:** it waits only behind a capture already queued, bounded by that capture's
  call limit, as the plan says; nothing holding the lock calls `lend` or `hand_back`.
- **`test_26_06` counts no view when a 320x240 feed is kept already:** `_kept_scene` releases any kept feed first.
- **`test_26_06`'s two recordings at one size share a folder:** frame 0 would then be the second's, of the same camera
  at the same size through the kept feed straight after a capture of another camera, so the check stands.
- **`test_06_09` lends nothing, the sizes differing:** the client's capture and recording both default to 640x480.
- **The idle timer takes a lent feed:** `lend`'s `let_go` moves the generation on, which `_release_idle` checks; a unit
  test with a 0.01 s idle time would fail without it.
- **A stop during an idle release, which holds the lock, releases a feed the slot is about to free:** one view more, in a
  two-update window; the plan's Risks row accepts it.
- **Phase 6's Verify line ("after `stop_recording()` it is the kept feed"):** 6.4 records at the 640x480 that 6.3's
  capture keeps, or nothing is kept; either way the stop keeps the recording's feed.
- **`_kept.closed` stays set after the extension is turned off and on:** as `recording._state.closed` has since #75; a
  re-enabled extension loads a fresh module.
- **Writing rules and one-way doors:** none broken; AGENTS.md's trap row only says more of its guard.

**Improvements,** all three taken:
- `hand_back`'s docstring and ARCHITECTURE.md name the queued capture a stop waits for.
- `test_17_08` reads Kit's log for `Py_Graph` lines, as `test_06_09` does: the one live test where a lent, segmented
  feed goes at a stage change.
- TOOLS.md's `stop_recording` names a capture running at the stop among the reasons the render is deleted at once.

**Not covered:** the gate and CI, and the PR's text, which the reviewer, reading only, didn't run or see; the gate passed
on `cda9822` (2,091 tests, coverage 97.50 %) and runs again on the fixes.

## Live run

My own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, with the branch's extension at
`cda9822` and the test fixes:

- **The new and changed tests:** `test_26_06` passed: a capture, a recording, a capture and a recording at 320x240 set up
  one `createViewport` in all, every render product the same `ovmcp_feed_`; a recording at 160x120 one more, the kept
  feed left; frame 0 of the recording through the kept feed against a fresh feed's capture of its camera, a mean of
  0.08 of 255 and a 99th percentile of 3, where the camera switch itself is 13.1 and 111. `test_06_06`, `test_06_09`
  (its segmented, lent feed torn down with no `Py_Graph` line), `test_26_03` and `test_26_05` passed; `test_17_08`
  failed on F1, then passed.
- **Both suites whole:** on a Z-up stage, 204 passed; on a Y-up stage, 204 passed.
