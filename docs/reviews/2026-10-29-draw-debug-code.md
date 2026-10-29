---
subject: "Make draw_debug work headless and keep each drawing its duration (PR 1 of the plan, #7)"
base: main (b818449)
head: 0c3d517
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer on Claude Opus 5.5, claude-opus-5-5; findings checked against the code by the main session)
verdict: clean
---

# Review: draw_debug on isaacsim.util.debug_draw

Read from the diff against `main`, the touched files in full, the plan
(`docs/plans/2026-10-29-debug-draw-and-ignored-parameters.md`), and the extensions as installed in Isaac Sim 5.1
(Kit 107.3) and 6.2 (Kit 110.4). The round found two minors, `needs-fixes`; both are fixed in `5daf884`, so the
branch is clean.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `handlers/debug_draw.py`, `_IsaacSimDraw.__init__`, `_OmniDebugDraw.__init__`, `_drop_if_turned_off` | Each backend kept the interface it acquired when chosen, and the check only asked whether its extension was on now. An extension turned off and on again through `manage_extensions`, whose `on_shutdown` calls `release_debug_draw_interface`, left the next `draw_debug` drawing through the interface it had released. | Fixed in `5daf884`: `isaacsim.util.debug_draw`'s interface is acquired at each use (`added`, `show`, `forget`), and `omni.debugdraw`'s is the one its module's `get_debug_draw_interface()` holds at each update, None while it is off; the check, now `_drop_if_off`, only forgets a backend whose extension is off. `tests/test_debug_draw_handler.py` runs the handler against a fake Kit, and its off-and-on tests fail on `0c3d517`. |
| F2 | minor | `docs/TOOLS.md`, `draw_debug` | "Drawings show in `capture_viewport`'s image, headless too" spoke for every Isaac Sim, while only 6.2 ran live: Isaac Sim 5.1 crashes in its own `SimulationApp` start on the machine that runs the live suites, before any bridge loads. | Fixed in `5daf884`: the line says Isaac Sim 6.x, checked live on 6.2, and that 5.x is untested live. |

Refuted, each from the code or Kit's source:

- **Kit calls the update callback from a worker thread:** the update event stream's pop subscription runs on Kit's
  main thread, as recording's does; the handler runs as its own task on the same loop. No callback is given to Kit
  that a worker thread could call.
- **Dropping the subscription inside its own callback:** carb's `IEvents.h`, on Kit 107 and 110, lets a subscriber
  unsubscribe while the stream dispatches to it, and NVIDIA's own extensions drop update subscriptions from their
  callbacks.
- **A clear while the stage closes:** `DebugBook.tick` only returns true on an update with the stage `OPENED`; a
  clear owed meanwhile waits, the handler refuses to draw while the stage opens or closes, and shutdown clears
  nothing.
- **The APIs:** `from isaacsim.util.debug_draw import _debug_draw`, `draw_lines`, `clear_lines` and `get_num_lines`
  in 3.1.0 (Kit 107) and 3.2.8 (Kit 110); `omni.debugdraw` 0.1.4's `draw_lines(list)` of `SimplexPoint` and its
  module's `get_debug_draw_interface()` on both; `get_extensions()` entries named by `name`;
  `set_extension_enabled_immediate` returning success; `UsdContext.get_stage_state()` and `get_stage_id()`.
- **Colour clamping:** `rgba` clamps each channel to 0-1 and `argb` clamps again before packing, so a channel above
  1 can't spill into the next; the unit tests pack 2.0 and -1.0.
- **Duration:** real seconds from the call by `time.monotonic()`, whether the simulation plays or not; a finite
  number above 0, or an error.
- **The tool contract:** only descriptions changed, which `tools/golden.py` strips; `tests/fixtures/mcp-tools.json`
  is unchanged and `test_contract.py` passes.
- **The live tests:** `test_16_03` to `test_16_09` and `test_17_03` fail on `main`, where every `draw_debug` fails
  headless; each waits for its lines to go, and `test_16_09` puts the default backend back and turns
  `omni.debugdraw` off again when it found it off.

Improvement, left: `get_update_event_stream` is deprecated on Kit 107 and 110 in favour of Events 2.0; recording
subscribes the same way, so both move together, later.

## Live run

Isaac Sim 6.2.0 (pip, headless), by the main session, on `0c3d517` with Kit started on it:

- **All 124 live tests passed,** `test_integration.py` and `test_scenarios.py`.
- **`test_16_08`:** 0 strongly red pixels in the view before the zigzag, 3364 with it, so drawings reach a headless
  capture (the plan's R1, for `isaacsim.util.debug_draw`).
- **`test_16_09`:** with `omni.debugdraw`, 4160 strongly red pixels while the drawing lasted, 0 after it.

Not shown: Isaac Sim 5.1, which crashes in its own `SimulationApp` start on this machine before any bridge loads,
so `isaacsim.util.debug_draw` 3.1.0 and a new stage with lines live on Kit 107 are untested live. A person watching
drawings come and go in a GUI viewport, which the headless run counts in lines and pixels instead.

## Checks

`uv run tools/gate.py full` passed on `0c3d517` (790 tests, 94.40%) and on `5daf884` (802 tests, 94.40%).
