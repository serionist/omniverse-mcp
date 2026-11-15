---
title: Capture a depth image beside the viewport image, on request
issue: "#203"
status: draft
approved_by:
approved_at:
---

# Capture a depth image beside the viewport image, on request

## Goal

`capture_viewport` writes three files: the image, the 2D boxes and the instance segmentation. An agent that asks
"what is in front of what, and how far" answers with several `raycast` or `get_prim_bounds` calls. Every output goes
to a file, so a depth image costs render time and risk, not context.

When this is done, `capture_viewport(include_depth=True)` also writes:
- a depth image the agent can read: distance to the camera as a grey PNG, nearer brighter, with nothing hit (sky)
  black;
- the raw distances as a `.npy` file (float32, height x width) for scripts.

The answer gives the near and far distances in stage units, and the share of the image that hits nothing. Without
`include_depth` a capture costs exactly what it does today.

In scope: `capture_viewport`. Out of scope: `capture_sweep` and `inspect_prim` (a later issue, once the depth path has
run live; the sweep's shots go through their own handler), normals and other annotators (the issue says only when
someone asks), and colour maps beyond grey.

## Design

- **The sensor:** `omni.syntheticdata`'s `DistanceToCamera`, read through `syn.sensors.get_distance_to_camera(feed)`
  (`omni.syntheticdata` 0.6.17's `scripts/sensors.py`, Isaac Sim 6.2), the same sensors API and the same feed the
  capture's segmentation uses (`camera_feed.enable_segmentation`, `camera._segmentation`). Radial distance, as the
  issue asks ("distance to the camera"), not `DistanceToImagePlane`'s Z-depth: a distance an agent compares with
  `raycast`'s and `get_prim_bounds`' without the camera's angle.
- **The feed's sensors, generalised:** `CameraFeed` holds the set of sensor types it turned on, in place of
  `segmented` and `sensor_on`. `enable_segmentation` and a new `enable_depth` add theirs; turning off between calls
  and at release disables each one on; freeing the graphs already pops every graph under the feed's render product
  (`_free_segmentation_graphs`, by prefix), so depth's go with segmentation's. A kept feed's depth is off between
  calls, as its segmentation is (#114's S1).
- **The wait:** depth, like segmentation, gives data only after a frame renders with the sensor on. The poll that
  `_segmentation` runs (each update for `SEGMENTATION_SECONDS`, bounded by the call's budget, a shorter retry where it
  failed before, data only at the feed's size) is drawn out into one function both reads use, taking the read.
- **The image:** a Kit-free core module, `ovmcp/core/depth.py`: `depth_image(distances) -> Depth` (the PNG bytes
  through `core/png.encode_png`, `near`, `far`, `nothing_hit`). Finite positive distances map linearly from far
  (grey 40) to near (white), so the farthest hit stays visible against black; non-finite, zero or negative ones
  (nothing hit) are black. `near` and `far` are the finite minimum and maximum. A frame with nothing hit at all gives
  an all-black image and no range.
- **The raw file:** `np.save` to bytes in the extension, base64 in the answer, written by the server as
  `viewport_<n>_depth.npy` beside `viewport_<n>_depth.png`; the server needs no numpy.
- **The answer:** `Depth: <png> (near <n>, far <f> stage units; brighter is nearer, black is nothing hit, <p>% of the
  image); raw distances: <npy>`, or `Depth: ERROR <why>` as segmentation's error line. The description names the
  option and the two files.
- **Alternatives:** Replicator's `distance_to_camera` annotator on the render product, rejected: a second mechanism
  beside the sensors API the feed already turns on, tears down and keeps (#51's E16, #114). A colour map (turbo),
  rejected for now: grey reads unambiguously as near and far, and the range is in the text.

## Compatibility

The tool contract gains `capture_viewport`'s `include_depth` (default false), additive; `golden.py` rewrites the
fixture, under CHANGELOG's Added. The wire protocol: `/sim/capture` takes `include_depth` and may answer
`depth_base64`, `depth_npy_base64`, `depth_near`, `depth_far`, `depth_nothing_hit` or `depth_error`; an older
extension ignores the key and sends none, and the server then says the extension is older and gave no depth, as
`start_recording` says of parameters an older extension ignores. The output folder gains two file names under
`captures/`, a layout it already has. No one-way door changes.

## Steps

1. **Measure on Kit** (Isaac Sim 6.2, by hand): `get_distance_to_camera` on a feed after a frame, a cube 5 units from
   the camera: its centre pixel's value (stage units or metres on a stage of `metersPerUnit` 0.01), the sky's value
   (inf, 0 or a large number), and that release frees depth's graphs with no log errors after, as #51's E16 measured
   for segmentation. The results go in this plan's Progress.
2. **Core:** `ovmcp/core/depth.py`, `tests/test_depth.py`: the grey mapping, nothing hit, all nothing, one distance.
3. **Extension:** the feed's sensor set, `enable_depth`, the shared poll, `include_depth` in `handle_capture`;
   `tests/test_camera_feed.py` and `tests/test_camera_handler.py`.
4. **Server:** `client.capture_viewport`'s `include_depth`, the tool's parameter, files and line;
   `tests/test_tools_camera.py` (the two files, the line, the error line, an older extension's silence);
   `uv run tools/golden.py`.
5. **Live:** in `test_integration.py`, a cube at a known distance captured with depth: the centre pixel within 2 % of
   the distance `get_prim_bounds` and the camera give, the corners nothing hit on a stage without a floor, and a
   capture without depth after it as fast as before (the sensor off). Isaac Sim 6.2, Z-up.
6. **Docs:** below.

## Tests

- Unit (CI): `tests/test_depth.py`, `tests/test_camera_feed.py`, `tests/test_camera_handler.py`,
  `tests/test_tools_camera.py`, `tests/test_client.py`, `tests/test_contract.py` through the fixture.
- Live: Step 5 on Isaac Sim 6.2; the integration suite's captures, unchanged, as the check that depth off costs
  nothing.
- Neither shows: Isaac Sim 5.1 (Kit 107)'s `omni.syntheticdata`, unless the dev server's container runs it; USD
  Composer.

## Docs

`docs/TOOLS.md` (`capture_viewport`: the option, the two files, the line), `plugin/skills/scene/SKILL.md` (when depth
helps: what is in front, how far), `docs/AI_GUIDE.md` where it lists the capture's files, `CHANGELOG.md` (Added).

## Risks

- **#162's hang** sits in the segmentation path's usdrt population after a physics run. Depth takes the same sensors
  API, so it may meet it; it is opt-in, so a plain capture can't. Accepted; the live run includes a capture with depth
  after a physics run.
- **The value's unit** may be metres, not stage units, on a stage of another `metersPerUnit`: Step 1 measures it, and
  the answer converts if it must. Open until Step 1.
- **The sky's value** may be 0, inf or a large finite number: `depth.py` treats non-finite and non-positive as nothing
  hit; a large finite one would stretch the range, so Step 1 checks it. Open until Step 1.

## Plan review

None yet.
