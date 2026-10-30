---
subject: "Add an open_scene tool that opens a USD file as the stage (#79)"
base: main (9d9ef2a)
head: 76e8bcc
date: 2026-10-30
round: 1
tier: standard (two fresh reviewers, Claude: the core and Kit side; the server and docs)
verdict: clean
---

# Review: open_scene

The plan `docs/plans/2026-10-30-open-scene.md`, built on `79-open-scene` after #80 and #83 landed. Read from the diff
of `76e8bcc` against `9d9ef2a`. No blocker or major; four minors, all fixed, with a test each where code changed. Every
check runs before Kit closes anything, and nothing awaits between the last look at the state and `start_open`. The
contract matches owner calls Q1 and Q5: 42 tools, `open_scene` the only one added. The reviewers' own ids are the
finding ids.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/test_stage_open.py` | The 20 s that the asset-root lookup and the stat share had no test: `open_stage(..., clock=...)` was never used, so a stat given a full `STAT_SECONDS` after a slow lookup would pass every test. | Fixed in `0274222`: `test_the_asset_root_and_the_stat_share_one_budget`, whose lookup moves the clock it is handed on by all but 0.05 s of `STAT_SECONDS` before a stat that hangs; the call is refused within 2 s. It fails without the shared budget |
| m1 | minor | `plugin/skills/scene/SKILL.md`, Traps; `docs/TOOLS.md`, `open_scene` | "A `.usdz` or a URL opened" and "a read-only stage, such as a URL's" overclaimed: the note fires only when Kit calls the stage read-only, which was measured for `https://` (E12), and an `omniverse://` stage can be writable. | Fixed in `838f021`: "a `.usdz`, or a stage `open_scene`'s answer calls read-only (an `https://` URL's)" in the skill, "a stage Kit calls read-only, such as an `https://` URL's" in TOOLS.md |
| m2 | minor | `docs/ARCHITECTURE.md`; `docs/TOOLS.md` | The rule for a route an older extension lacks was in CHANGELOG alone. | Fixed in `838f021`: ARCHITECTURE's handshake paragraph says such a route answers 404 `Unknown endpoint`, `bridge_call` adds the install command, and a new route leaves `PROTOCOL` alone; TOOLS.md's `open_scene` has an "extension of 0.2.2 or older" line, as the other tools have |
| m3 | minor | `core/stage_open.py`, `name_of` | `replaced`, and a failed open's "the stage open now", named a stage opened from a `file:///` URL by Kit's identifier `file:/C:/...` (E9), which `open_scene` refuses; P6 had fixed the same for `Opened`. | Fixed in `0274222`: `path_of` turns a `file:` URL, Kit's spelling or the given one, back into its path; `name_of` uses it. `test_a_stage_opened_from_a_file_url_is_named_by_its_path`, and `test_a_file_url_is_named_by_its_path_and_anything_else_as_it_is` for its forms |

Refuted, or checked and found right, on the core and Kit side:

- **No hang when Kit refuses without calling back:** `start_open` answers at once (`scene_open.py` lines 83-85),
  tested.
- **False means the open didn't start:** as NVIDIA's own `stage_manager.py` (lines 222-225) reads it, and E14.
- **A callback after the 80 s** finds the future done and is dropped (`if not future.done()`).
- **The fallback's gap is unreachable,** and the fallback is now gone (Improvements).
- **`asyncio.TimeoutError`** is the builtin `TimeoutError` on Python 3.11 and later, which the core catches.
- **`Result`'s `str`** names the member as the core compares it (E9).
- **`get_assets_root_path_async`** raises only `RuntimeError`, which the core turns into a refusal; an empty root is
  impossible (`nucleus.py` lines 687-688).
- **The timeline stopped before a second check that refuses** loses nothing (E10).
- **The busy check's `CLOSED` window** is covered by Kit's own refusal of a second open (E14).
- **The path rule's move** doesn't change `create_robot`: the same regex, the same arguments, the same error.

Refuted, or checked and found right, on the server and the docs:

- **The contract** matches Q1 and Q5: 42 tools, `open_scene` added, nothing else moved.
- **The server and the core agree** on the answer's shape.
- **Every claim in the description** holds against `_open`.
- **The older-extension hint** fires only on `http.py` line 222's "Unknown endpoint". It can't mislead for a route
  that isn't registered, since every route registers unconditionally, or for one dropped, since `PROTOCOL` refuses
  first. Every tool goes through `bridge_call`, and `install_command()` can't throw.
- **The path comparisons** in the live tests hold on Windows and Linux.
- **`test_31` and `test_36` open** despite a reference that doesn't resolve; their cleanups run last in, first out.
- **17.7's render-product check** is valid, and the phases after it aren't broken by the deleted temp file (plan R8).
- **`AGENTS.md`** stays at 150 lines.

Improvements:

| Improvement | Answer |
|---|---|
| Drop the fallback to `open_stage_async` in `_Kit.start_open` | taken in `0274222`: omni.usd's own `open_stage_async` calls `open_stage_with_callback` (F4); its test is gone, and the plan records the departure from R7 (`838f021`) |
| The Git LFS pointer test with `.usda` and `.usdz` too | taken in `0274222`: `CanRead` refuses the pointer under all four names on usd-core |
| `new_scene`'s description names `open_scene` for a Z-up stage | taken in `838f021` |
| The hint says "older than this MCP server", README Troubleshooting's words | taken in `838f021` |
| The stopped note says "was playing or paused" | taken in `838f021`, in TOOLS.md too |
| `test_32` to `test_35` check `test_31`'s cube before the call too | taken in `838f021` |

Not covered: Kit 107 live (Isaac Sim 5.1 crashes in its own start on this machine), `CanRead` for formats other
plugins add (`.obj`, `.gltf` and the like), the GUI.

## Live run

On `76e8bcc`, Isaac Sim 6.2.0 headless, a fresh Kit at port 8212 with the branch's extension, run by the main session
with `build-79-live.sh`: both live suites in full, 170 passed in 140.38 s, exit 0.

| Test | Measured |
|---|---|
| `test_31` | `IntTestOpen.usda`: 30 prims, Z up, the cube back; opened while playing, the answer's note and `get_sim_state` say stopped |
| `test_32` to `test_35` | a missing file, a `.txt`, a `file:///` URL with no file and a relative path refused, the stage kept |
| `test_36` | `simple_room.usd` from the asset root on S3 over HTTPS, 170 prims, read-only; then the suite's stage opened again |
| `test_27` to `test_30` | `create_robot` from a file, a missing file, a URL that won't open and a taken prim, after the path rule moved |
| `test_17_05` | a new stage: 8 frames, then "frames stopped after 8, at 0.00 s of simulation: the stage began to close" |
| `test_17_07` | an opened file: 9 frames, then "frames stopped after 9, at 0.00 s of simulation: the stage began to close"; the 30 s line gone, the render product off the opened stage, a capture with its segmentation |
| the rest of both suites | passed, phase 18's library robots among them |

Not shown: Kit 107, the GUI, an open past its 80 s, a file that passes the checks and fails to load, Kit's busy
refusal live, Nucleus `omniverse://`, an offline asset library, and the commits after `76e8bcc` (`0274222`,
`838f021`), which wait for the re-run of `build-79-open.sh`.
