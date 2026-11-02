---
subject: "Move the bridge's update subscriptions to Kit's Events 2.0 update event (#122)"
base: main (6b7d051)
head: 8fdfc6b
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; one minor, so no second round"
verdict: clean
---

# Review: Move the bridge's update subscriptions to Kit's Events 2.0 update event

Read from the branch's diff against `main` at `6b7d051` by one fresh reviewer, read only, with every lens. It checked
Kit's update event and `carb.eventdispatcher` in Isaac Sim 6.2's (Kit 110) and 5.1's (Kit 107) installed sources, and
ran the CI guard's scan offline against the base and the head. One minor, fixed after `8fdfc6b`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/TOOLS.md`, `get_logs`' "What an entry shows" | The example showed the bridge logging Kit's `get_update_event_stream` notice, matched in `camera_feed.py`'s `add`, which after this change it can't, against the CHANGELOG's line that Kit's log holds no more of the bridge's notices | fixed in `c9942de`: the example is another extension's `get_stage_event_stream` notice |

**Refuted,** each from the code or Kit's sources:
- **Each observer dropped where its subscription was:** only the three creation lines changed. Every drop is
  untouched (`camera_feed.py`, `recording.py`, `debug_draw.py`), and shutdown's teardown drops the watch it may make.
- **An observer dropping itself or another during dispatch:** `ObserverGuard.reset`'s documented contract is the same in
  Kit 110 and 107, and probe P3 measured it. The fake checks registration before each call too.
- **An observer made at order 100 running in the same update:** `observe_event` doesn't call a new observer for the
  event being dispatched, and the extension makes no nested update.
- **The order against the old stream:**
  - Probe P1 measured order 0 in the stream's place on Kit 110, and Kit 107's `KitUpdateOrder.h` is the same file.
  - The recorder still reads simulation time after physics and before Hydra's render, so #111's clock doesn't move.
- **Kit 107's API:** `GLOBAL_EVENT_UPDATE`, `UPDATE_ORDER_UNSPECIFIED` and the keyword call form are all there, as Kit's
  own `async_engine.py` uses them.
- **Others:** an observer that raises (as before, probe P4); the recorder's reference cycle (as before, broken at its
  end); the CI guard (it fails on the base's three files and passes on the head, scanning every non-cache file);
  `test_17_08` (it fails on main for the bridge's notices and passes on the branch, with its own marker against a log
  that drops Info lines); no executor anywhere.

**Improvements,** both taken in `c9942de`:
- The three comments that still said "subscription" now say "observer".
- `test_17_08` checks that the render product the open carried over is gone, so the update observer that deletes it is
  shown to have run.

## Live run

My own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows 11, RTX 5090, port 8212, each extension on a Kit started fresh,
with another session's apps on the same GPU. `105-stage.py` set the stage's up axis.

| Step | Extension | Stage | What ran | Result |
|---|---|---|---|---|
| 1 | main `6b7d051` | Z-up | `test_17_08` | failed, as it should: the bridge's notices from `recording.py` and `debug_draw.py` |
| 2 | main `6b7d051` | Z-up | both live suites whole | 202 passed, `test_17_08` failing. Kit's log held 44 Events 2.0 notices, 40 of them naming the bridge: `recording.py` 31, `debug_draw.py` 22, `camera_feed.py` 8 (a notice can name more than one) |
| 3 | `8fdfc6b` | Z-up | `test_17_08` | passed |
| 4 | `8fdfc6b` | Z-up | both live suites whole | 203 passed. Kit's log held 4 Events 2.0 notices, Kit's own (`omni.usd.schema.physx`, `omni.graph.visualization.nodes`, `omni.ext`), none naming the bridge (Q6 B) |
| 5 | `8fdfc6b`, test at `c9942de` | Z-up, Y-up | `test_17_08`, with the render product check | passed on each |

Not shown: Isaac Sim 5.x (Kit 107's API read from its sources only; the plan's `122-probe.py` on Isaac Sim 5.1 is left
for later), Linux, USD Composer.
