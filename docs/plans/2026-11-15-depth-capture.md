---
title: Capture a depth image beside the viewport image, on request
issue: "#203"
status: approved
approved_by: serionist
approved_at: 2026-11-15
---

# Capture a depth image beside the viewport image, on request

## Goal

`capture_viewport` writes three files: the image, the 2D boxes and the instance segmentation. An agent that asks
"what is in front of what, and how far" answers with several `raycast` or `get_prim_bounds` calls. Every output goes
to a file, so a depth image costs render time and risk, not context.

When this is done, `capture_viewport(include_depth=True)` also writes:
- a depth image the agent can read: distance to the camera as a grey PNG, nearer brighter, nothing hit (sky) black;
- the raw distances as a `.npy` file (float32, height x width, stage units) for scripts;
- each prim's nearest distance in the segmentation legend, beside its colour.

The answer gives the near and far distances in stage units, and the share of the image that hits nothing. Without
`include_depth` a capture costs exactly what it does today.

Two departures from the issue (fit I1): grey, not a coloured map, since grey reads unambiguously as near and far and
the numbers are in the text; and stage units, not metres, since `raycast`, `get_prim_bounds` and every other tool
speak stage units, so a distance compares with theirs as it stands. The issue also says to keep depth clear of #162's
hang: it can't be, since it shares the segmentation path every capture takes, so the live run captures depth after a
physics run (round 1, P6).

In scope: `capture_viewport`. Out of scope: `capture_sweep` and `inspect_prim`, later: #208 (the sweep's shots go
through their own handler, and `inspect_prim`'s angles would multiply the raw files by up to 14); normals and other
annotators (the issue: only when someone asks).

## Design

- **The sensor:** `omni.syntheticdata`'s `DistanceToCamera`, read through `syn.sensors.get_distance_to_camera(feed)`
  (`omni.syntheticdata` 0.6.17's `scripts/sensors.py`, Isaac Sim 6.2), the same sensors API and the same feed the
  capture's segmentation uses. Radial distance, as the issue asks ("distance to the camera"), not
  `DistanceToImagePlane`'s Z-depth: a distance an agent compares with `raycast`'s without the camera's angle.
- **Units and the sky,** from omni.syntheticdata's own tests (`tests/sensors/test_distance_to_camera.py`: a cube `n`
  centimetre stage units away reads `(n - 1) / 100`, so metres; an empty stage reads over 1000, a fisheye's sky `inf`)
  (fit I5): the extension converts metres to stage units once, `metres / metersPerUnit`, as `sweep.py` reads the
  stage's, for the PNG's range, the text and the `.npy` alike. Nothing hit is a pixel whose segmentation id, read in
  the same update, is 0, since every capture takes segmentation (round 1, P2); without segmentation data, a non-finite
  value, a non-positive one, or one at or beyond the camera's far clipping distance. The `.npy` holds `inf` there, so
  a script's `min` or `mean` isn't fooled by the sky.
- **The feed's sensors, one function** (fit I3): `enable_segmentation` becomes `enable_sensors(feed, types)`, which
  keeps the registry check (`_nodeGraphs`, `_reset_node_graph`) and the "omni.syntheticdata not loaded" reason in one
  place and makes one `syn.sensors.enable_sensors(feed, [...])` call; the feed holds the set of types it turned on in
  place of `sensor_on`, and turning off (between calls, at release) is one `disable_sensors(feed, [...those])`.
  `segmented` stays, meaning graphs were made; freeing them already pops every graph under the feed's render product
  by prefix. A capture without depth passes segmentation's type alone, so its path is today's. Depth is turned on
  after segmentation, in a call and a `try` of its own: `enable_sensors` raises on any one type, and a depth that
  can't be turned on costs only `depth_error`, never the segmentation, and doesn't put the feed in doubt (round 1,
  P1).
- **The read** (fit I4): both sensors are turned on before the feed's settle frames, and segmentation is read first,
  so depth normally has data by then. Depth's read is `capture.poll(read, whole, next_update, SEGMENTATION_SECONDS,
  budget)` with the same size check, and an error line of its own; segmentation's retry state and logging stay
  segmentation's.
- **The image** (fit I6): a Kit-free core module, `ovmcp/core/depth.py`: `depth_image(distances, far_clip) -> Depth`
  with the PNG bytes, `near`, `far` and `nothing_hit`. Grey maps linearly in inverse distance, white at `1/near` and
  grey 40 at `1/far`, so a far floor doesn't squeeze the objects in front into a few grey levels; nothing hit is
  black. `core/png.encode_png` takes a 2-D array as grey, PNG colour type 0, a third of an RGB file's compression and
size (round 1, I8). A frame with nothing hit
  gives an all-black image and no range.
- **Each prim's nearest distance** (fit I7): `depth.py`'s `nearest_by_name(ids, distances, name_of)` takes the
  minimum finite distance per prim path, joined through the same `name_of` the legend's colours use, so a prim two ids
  name gets the minimum of both, from the same feed's segmentation and depth read in the same update; computed from the
`np.unique` inverse indices `colour_instances` already takes, with `np.minimum.at`, so no second pass over the pixels
(round 1, I9). It goes on the
  wire as a key of its own, `depth_nearest: {path: d}`, leaving `segmentation_legend`'s `[R, G, B]` values as they
  are; the legend file's line for a prim becomes `path = [R, G, B] distance = d` (stage units), one line per prim, so
  a grep on a path returns its distance (round 1, P3). The issue's question, "what is in front of what, and how
  far", is then a grep.
- **The raw file:** `np.save` to bytes in the extension, base64 in the answer, written by the server as
  `viewport_<n>_depth.npy` beside `viewport_<n>_depth.png`; the server needs no numpy.
- **The answer:** `Depth: <png> (near <n>, far <f> stage units; brighter is nearer, black is nothing hit, <p>% of the
  image); raw distances: <npy>`, or `Depth: ERROR <why>`. The description names the option and the files.
- **Alternatives:** Replicator's `distance_to_camera` annotator on the render product, rejected: a second mechanism
  beside the sensors API the feed already turns on, tears down and keeps (#51's E16, #114). A colour map, rejected
  for now (above). Linear grey, rejected (I6).

## Compatibility

The tool contract gains `capture_viewport`'s `include_depth` (default false), additive; `golden.py` rewrites the
fixture, under CHANGELOG's Added. The wire protocol: `/sim/capture` takes `include_depth` and may answer
`depth_base64`, `depth_npy_base64`, `depth_near`, `depth_far`, `depth_nothing_hit`, `depth_error` and
`depth_nearest`; an older extension ignores the key and sends none, and the server then says the extension is older
and gave no depth. The output folder gains two file names under `captures/`, a layout it already has. No one-way door
changes.

## Steps

1. **Confirm on Kit** (Isaac Sim 6.2, by hand): the values in metres and the sky as `inf` or past the far clip, as
   omni.syntheticdata's tests say; the far clip's value read from the camera; and that release frees depth's graphs
   with no log errors after, as #51's E16 measured for segmentation. The results go in this plan's Progress.
2. **Core:** `ovmcp/core/depth.py`, `tests/test_depth.py`: the inverse grey, nothing hit (inf, 0, past the clip), all
   nothing, one distance, the metres to stage units conversion, the nearest distance per instance.
3. **Extension:** `enable_sensors`, the feed's set of types, depth's read, `include_depth` in `handle_capture`, the
   legend's distances; `tests/test_camera_feed.py` (fit I2: after `put_back` no sensor is on, and a call without depth
   never passes `DistanceToCamera` to `enable_sensors`) and `tests/test_camera_handler.py`.
4. **Server:** `client.capture_viewport`'s `include_depth`, the tool's parameter, files, line and legend;
   `tests/test_tools_camera.py` (the two files, the line, the legend's distances, the error line, an older
   extension's silence); `uv run tools/golden.py`.
5. **Live:** in `test_integration.py`, a cube at a known distance captured with depth: the centre pixel within 0.1 m
   (`0.1 / meters_per_unit` stage units, round 1, P5) of the distance from the camera to the cube's front face, and
   the cube's legend `distance` the same; the corners nothing hit on a stage without a floor; after it,
   `execute_script` reads that the feed's depth sensor is off (fit I2); a capture with depth after a physics run (round
   1, P6, #162); and one 4096 x 4096 capture with depth, its time recorded in Progress (round 1, P4). Isaac Sim 6.2,
   Z-up.
6. **Docs:** below.

## Tests

- Unit (CI): `tests/test_depth.py`, `tests/test_camera_feed.py`, `tests/test_camera_handler.py`,
  `tests/test_tools_camera.py`, `tests/test_client.py`, `tests/test_contract.py` through the fixture.
- Live: Step 5 on Isaac Sim 6.2; the integration suite's captures, unchanged, as the check that a capture without
  depth is as it was.
- Neither shows: Isaac Sim 5.1 (Kit 107)'s `omni.syntheticdata`, unless the dev server's container runs it; USD
  Composer.

## Docs

`docs/TOOLS.md` (`capture_viewport`: the option, the two files, the line, the legend's distances),
`plugin/skills/scene/SKILL.md` (when depth helps: what is in front, how far), `docs/AI_GUIDE.md` where it lists the
capture's files, `CHANGELOG.md` (Added).

## Risks

- **#162's hang** sits in the segmentation path's usdrt population after a physics run. Depth takes the same sensors
  API on the same feed; a capture without depth is as exposed as today, and one with depth as exposed as a plain
  capture already is. Accepted; the live run includes a capture with depth after a physics run.
- **The far clip as nothing hit,** used only without segmentation data, treats a real surface right at the clip as
  sky. Accepted: the renderer doesn't draw past it either.
- **A large capture's cost:** at 4096 x 4096 the `.npy` is 64 MiB of float32, about 89 MB of base64, built and sent on
  Kit's main thread with the PNG's compression, so Kit stalls for a second or more. Accepted for a size few ask depth
  at; Step 5 measures it, and the description says depth costs most at large sizes (round 1, P4).
- **Kit 107's omni.syntheticdata** is unread here: Step 1 runs on 6.2 only. Accepted, as Tests says.

## Progress

- **Steps 1 and 5, measured live** on Isaac Sim 6.2.0 (Kit 110.4, `isaacsim.exp.base.kit`, Windows, a metre stage,
  2026-11-15), through `test_12k`: the sensor's values in metres, so the conversion holds (the cube's nearest 1.582
  against 1.581); nothing hit is `inf` exactly where the segmentation shows no prim; release left no graph and no
  error in Kit's log; a 4096 x 4096 capture with depth took 3.4 s. A centimetre stage wasn't run, so the division by
  `metersPerUnit` stands on omni.syntheticdata's own test.

## Plan review

### Fit

The plan at `1a05f1e`, by a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15, with the change's own
question: is grey with near and far in the text the most useful depth image, is leaving out the sweep and
`inspect_prim` the right cut, and is a set of sensors on the feed the simplest safe way. Answers by the maintainer,
2026-11-15.

| # | Improvement | Answer |
|---|---|---|
| I1 | Name the two departures from the issue (grey, stage units) with their reasons, and file the sweep's follow-up now | taken: Goal; #208 |
| I2 | Replace "as fast as before" with a unit test that no sensor is on after `put_back`, and a live read that depth is off | taken: Steps 3 and 5 |
| I3 | One `enable_sensors(feed, types)` in place of a sibling `enable_depth`, the registry guard in one place | taken: Design |
| I4 | Read depth with `capture.poll` directly, leaving segmentation's retry state alone | taken: Design |
| I5 | omni.syntheticdata's tests settle the unit (metres) and the sky (inf, or over 1000): convert to stage units in the extension, `.npy` included | taken: Design, Step 1, Risks |
| I6 | Grey linear in inverse distance, so a far floor doesn't squeeze the objects | taken: Design |
| I7 | Each prim's nearest distance in the segmentation legend | taken: Goal, Design |

Noticed on the way, for Round 1: Risks (#162: plain captures already take segmentation's path on every call); the
answer's size (a `.npy` at 4096 x 4096 is 64 MB of float32, about 89 MB of base64 in one answer, built on Kit's main
thread); Design (the `.npy`'s unit); Step 5 (2 % of the centre pixel is tight; NVIDIA's check uses the front face,
0.1 m); Design (`encode_png` writes RGB only).

### Round 1

**How:** a fresh general-purpose agent (Claude Opus 5.5), 2026-11-15. **Verdict:** approved, the owner calls
answered by the maintainer: six minors, all fixed in the plan, no blocker or major. **Now:** P1-P6, I8 and I9 applied.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | One `enable_sensors` call raises on any type: a depth that can't be turned on would cost the segmentation and release the feed | fixed: depth on after segmentation, in its own call and `try`; only `depth_error` |
| P2 | minor | The sky may read large and finite under the default far clip (1e7 m), so it would count as a hit and the `.npy` would hold it | fixed: nothing hit is segmentation id 0, the depth rule only without segmentation data; `inf` in the `.npy` there |
| P3 | minor | The legend's distance had no form or join: names two ids share, a file of one line per prim, `[R, G, B]` readers | fixed: minimum per path through `name_of`; `depth_nearest` on the wire; `path = [R, G, B] distance = d` in the file |
| P4 | minor | A 4096 x 4096 depth capture's size (89 MB of base64 on Kit's main thread) isn't named | fixed: a Risk, measured in Step 5, said in the description |
| P5 | minor | Step 5's 0.1 is in stage units: 1 mm on a centimetre stage | fixed: 0.1 m in stage units |
| P6 | minor | The capture after a physics run was only promised; #162's departure from the issue unsaid | fixed: in Step 5, and in Goal |

Refuted: the #162 wording (Risks already right); RGB-only encoding (the plan stacks; I8 below); the centre-pixel
tolerance (already the front face); an older server (it never sends `include_depth`); the protocol number and
ARCHITECTURE.md (same route, additive answer); Kit's main thread (no executor); security, harness, one-way doors
(none touched); depth's graphs at release (freed by prefix).

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Cap depth's size, or store float16? | neither: name and measure the cost (P4) | neither, as recommended |
| Q2 | Should a depth failure release the feed? | no: `depth_error` alone, the feed kept (P1) | no, as recommended |

| # | Improvement | Answer |
|---|---|---|
| I8 | `encode_png` takes a 2-D array as grey (colour type 0): a third of the compression and file size, no stacking | taken |
| I9 | The nearest per prim from `colour_instances`' `np.unique` inverse indices with `np.minimum.at`: no second pass over the pixels | taken |
