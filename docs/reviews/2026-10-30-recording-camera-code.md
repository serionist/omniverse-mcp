---
subject: "Record start_recording's frames from its camera at its size (#25, #69)"
base: main (765d51c)
head: 6dfce80
date: 2026-10-30
round: 1
tier: standard (two fresh reviewers, Claude: the Kit side; the core, server and docs; checked by the author)
verdict: clean
---

# Review: recording from a camera at a size

The plan `docs/plans/2026-10-30-recording-camera.md`, built on `25-recording-camera`. Read from the diff of `6dfce80`
against `765d51c`, the touched files in full, and the Kit and Isaac Sim 6.2.0 sources the plan cites. No blocker or
major; four minors, all fixed in `f6f4412`, with a test each where code changed. The reviewers' own ids are in
brackets. `69e9169`, made after the reviewed head and before the findings came, only rewords the note a recording
gives when its camera goes.

The branch was then rebased onto `785606c` (#57, PR #73): `6dfce80` became `e078dab`, `69e9169` became `7c7922b`
and `f6f4412` became `ffffd61`. `capture_file_png` carries #57's `next_frame`: the viewport's capture passes its
fresh frames, a feed's passes none. #57's `fresh=False` opt-out, which only recording used, went with recording's
viewport capture, and its guard test now checks that recording captures from its feed and that the feed's capture
waits for no viewport frame; `test_camera_feed.py` checks the same by running it. ARCHITECTURE's fresh-frames part
and #57's Traps row in `AGENTS.md` say recording waits none because it has its own feed.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 (K1) | minor | `handlers/recording.py`, `shut_down` and `_start` | A start still waiting for its first frame outlived a shutdown or a hot reload: `shut_down` acted on the session alone, so the old module's `_start` resumed after the frame, subscribed and set its session, and the recording ran where nothing could stop it ("No active recording"). | Fixed in `f6f4412`: `shut_down` sets `_state.closed`, and `_start` refuses after the wait when it is set, so the feed is discarded. `test_a_start_waiting_for_its_first_frame_fails_once_the_extension_shuts_down` |
| F2 (K2) | minor | `handlers/recording.py`, `handle_recording_start` with `force` | The forced path awaited the running recording's end before marking a start, so an ordinary start could slip in during that wait and two recordings run, one unreachable; and a bad camera ended the running recording, with no `metadata.json`, before it was refused. | Fixed in `f6f4412`: the request and the camera are checked first, the start is marked before anything is awaited, and the forced end comes after both. `test_a_forced_start_with_a_bad_camera_keeps_the_running_recording`, `test_no_start_slips_in_while_a_forced_start_ends_the_running_recording` |
| F3 (C1) | minor | `tools/recording.py`, `start_recording` | TOOLS.md said the answer names `render_product`, and `scenarios.md` 6.6 and 17.5 check it, but the tool's text never showed it. | Fixed in `f6f4412`: "Renders into <render product>, deleted at stop" for an extension that names one; text only, the contract unchanged. `test_start_recording_says_the_camera_and_size_it_records` |
| F4 (C2) | minor | `test_project/scenarios.md`, phase 6 | No step for 6.4: frames from `/World/RecCam` show the falling cube lower in the last frame than the first. | Fixed in `f6f4412`: the bullet, pausing before `stop_recording` as the live test does |

Refuted, or checked and found right, on the Kit side:

- **The update order:** `_on_update` checks the stage's state, its id and the camera before it ticks, so no frame is
  asked of a feed rendering another stage; frames are numbered by the frame clock, not by an update count.
- **The queue before the await:** `capture_feed_png` queues its delegate in `schedule`, which `capture.capture_png`
  calls before its first await, so a frame delivered on the same update reaches it, and the feed's `waiting` reads
  true from the tick on.
- **`is_async`:** `False`, as Replicator makes its render products; the feed delivered each frame on the update it
  was asked on (the plan's E17), whatever the viewport's async setting.
- **`get_event_key`:** filters Kit 110's global drawable event to this texture; Kit 107's event stream is the
  texture's own and needs none.
- **The texture's references:** the feed holds the texture until `drop`, which drops the subscription first;
  `_on_frame` returns once the texture is gone.
- **Cancelling:** a cancelled frame task runs its `finally` and writes the empty marker; one cancelled before it ever
  ran is written by `_end`'s loop over the frames still owed.
- **Two ordinary starts:** `_state.starting` is set before the first await, and a running session refuses a start
  without `force`.
- **Cancelled tasks at stop:** `asyncio.gather(..., return_exceptions=True)` takes them without raising.
- **The fakes:** `tests/test_recording_handler.py` and `tests/test_camera_feed.py` load the real files and the real
  core on usd-core; what they fake, Kit's modules and the texture, is what the live suites run.
- **The main thread:** the handlers and `_on_update` run on Kit's loop; the drawable callback ran on the main thread
  in every timeline state on Kit 110 (E16) and does no USD work and no logging.
- **Bounds:** a frame keeps the capture path's 30 s for its frame and 10 s for its file, the first frame 30 s, and
  stop awaits only frames whose own waits are bounded.
- **Eco Mode:** it pauses the viewport's rendering of a still scene; the feed delivered frames of a still scene,
  stopped and paused (E1, E3, E19).

Refuted, or checked and found right, on the core, the server and the docs:

- **The contract:** only descriptions changed, which `tools/golden.py` strips; `tests/fixtures/mcp-tools.json` is
  unchanged and `tests/test_contract.py` passes.
- **The new fields:** the start answer gains `render_product`, the stop answer `note`, `/sim/state`
  `recording_note`; the server reads each with `in` or `get`.
- **Old and new together:** a new server on an older extension warns, its answer having no `render_product`; an
  older server on the new extension reads the answer as before and warns of values no longer ignored, which the plan
  accepts.
- **Bounds:** `capture.frame_size` refuses a boolean, a fraction, text, 0 and 4097, and takes 1 and 4096; the schema
  keeps its minimum of 1.
- **`delete_render_product`:** takes the prim from each layer holding a spec and the target from explicit and
  prepended `products` lists, on usd-core and live (6.6, 6.9, 17.5).
- **6.3's aim:** `/World/RecCam` sits 8 units along X looking at the cube's column at 1.5 with an 18 mm lens, so the
  cube at 1.5 is in view, and `_aim_away` turns the viewport along +X from 20, where none of it is.
- **6.9's and 6.1's counts:** 6.1 compares the frame files with `frame_count`, each frame written once; 6.9 counts
  the files across half a second after the note.
- **Passing on `main`:** each new live test fails there: no `render_product` (6.6, 6.9, 17.5), frames at the
  viewport's size (6.1, 6.3), numbers repeated (6.8).
- **`test_integration.py`:** has no recording test, and no change needs one there.
- **`AGENTS.md` and `CHANGELOG.md`:** 149 lines, within the gate's 150; three Fixed lines under Unreleased, each with
  the extension install.
- **`pyproject.toml`:** the recording handler's ruff ignores only shrank.

Improvements:

| Improvement | Answer |
|---|---|
| `_take_frame` catches any exception, logged with the frame's number | taken in `f6f4412` |
| Check at start that the app has what a feed renders and captures with, so an app without `omni.kit.widget.viewport` fails `start_recording` clearly | taken in `f6f4412`: `omni.kit.hydra_texture` and `omni.kit.widget.viewport.capture`, before anything is made; `test_an_app_that_cannot_capture_a_camera_is_refused_before_anything_is_made` |
| `encoding="utf-8"` in `_write_state_header` and `_write_state` | taken in `f6f4412` |
| `test_06_05` and `test_06_07` end a recording that started after all | taken in `f6f4412` |
| `MAX_SIDE`'s comment and ARCHITECTURE: start_recording's, and #51's captures' once that lands | taken in `f6f4412` |
| "Within one update" of `sim_time`, not "the update before", in TOOLS.md and ARCHITECTURE.md | taken in `f6f4412` |
| `test_07_02`'s stale comment: the state is read at the tick | taken in `f6f4412` |
| `test_06_04`'s docstring: "none repeated" is not what it checks | taken in `f6f4412` |
| ARCHITECTURE's Threading Model names the feed's drawable callback: the main thread on Kit 110 (E16), unmeasured on 107, so no USD work and no logging | taken in `f6f4412` |

Not covered: the bridge's security (no route, header or token changed), the GUI (a person watching the viewport stay
put), Kit 107.

## Live run

On `6dfce80`, Isaac Sim 6.2.0 headless, a fresh Kit with the branch's extension, run by the main session with
`build-25-live.sh`:

- **The first recording after Kit started:** `start_recording` answered in 0.19 s; stopped after 1.0 s with 8
  frames, all 320x240.
- **Both live suites, nothing excluded:** 154 passed in 113.35 s, no failures.

| Test | Measured |
|---|---|
| `test_06_01` | 14 frames at 320x240 from `/OmniverseKit_Persp` |
| `test_06_03` | 11 frames at 160x120 from `/World/RecCam`, at least 445 strongly red pixels each; the viewport as it was |
| `test_06_04` | the cube from image row 67 to 157 over 13 frames |
| `test_06_06` | the render product in 2 layers while recording, in none after |
| `test_06_08` | 28 frames in 1 s at `fps=30`, numbered 0 to 27, none the same as the one before |
| `test_06_09` | 8 frames, then "the camera is gone" |
| `test_17_05` | 6 frames, then "the stage began to close" |

Not shown: Kit 107 (Isaac Sim 5.1 crashes in its own start on this machine), the GUI, and the commits after
`6dfce80` (`69e9169`, `f6f4412`), which wait for the live re-run.
