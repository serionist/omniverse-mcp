---
subject: "Make the output folder with its first file, and give a path outside the working folder whole (#41, #43)"
base: main (b26dd58)
head: 0db7e8e
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer)
verdict: clean
---

# Review: the output folder and the paths the tools give

Read from the diff, every caller of `Helpers` in `tools/`, and the Kit handlers that write into a path the server
passes. Three minors, fixed in `637bd3b`; four improvements taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `server.py`, `Helpers.rel` | With the working folder at a drive's root (`/`, where Claude Desktop on macOS can start servers) every file is under it, so the short form came back: #41's problem, and against SETUP.md's "absolute paths" | fixed: a root working folder gives absolute paths; `test_a_working_folder_at_a_drive_s_root_gives_absolute_paths` |
| F2 | minor | `server.py`, `Helpers.rel` | `Path.resolve` can raise (Windows errors outside its list, such as an unreachable share; a symlink loop on 3.11 and 3.12), and `write`'s error message calls `rel`, so the model would get only the tool's name | fixed: the path made whole without resolving; `test_a_path_that_cant_be_resolved_is_given_whole` |
| F3 | minor | `server.py`, the module and `save_png` docstrings | Still said "a relative path" | fixed |

Refuted, each from the code:

- **A tool fails on a fresh start for want of the folder:** the server writes through `Helpers.write`, which makes the
  parents; Kit's `handle_scene_dump` and recording start make theirs (`scene.py`, `recording.py`), back to the first
  commit, so every bridge of this protocol does. The comment `main()` dropped ("doesn't make the folder") was wrong.
- **Symlinks, 8.3 names, another drive, UNC, a recording's folder from a remote Kit:** both sides resolve alike; another
  drive and UNC come back absolute; a path missing here resolves leniently.
- **The camera legend with an absolute `seg_path`:** joined only when relative.
- **The new tests prove nothing:** the start and outside-path tests fail on `main`.

Improvements:

- **#43's test runs the real `create_server`,** with only `MCPServer.run` stubbed: taken.
- **The legend's path from the segmentation file's own name,** not `.replace(".png", ...)` over the whole path, which
  would also rename a folder with `.png` in it (`_legend_beside`): taken, with a test that the legend lands beside the
  segmentation outside the working folder.
- **A relative `--output-dir` made whole at start,** since Kit read it against its own working folder for
  `dump_scene` and recordings: taken; `test_a_relative_output_folder_is_made_whole_at_start`.

Not covered: the Kit main-thread, bridge-security and harness lenses, with nothing in scope.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for this run with #40's branch's bridge (this change touches
the server only); the maintainer's Isaac Sim on 8211 was not touched.

- **The live suites** from this branch (`-k "not test_10_ and not test_14_"`, #5): 112 passed, with #7's three
  `draw_debug` scenarios failing, as on `main`.
- **The tools themselves,** through an in-memory MCP client, with an output folder outside the working folder that
  didn't exist: none at start; `dump_scene` wrote `scene_dump.txt` into the folder Kit made; `capture_viewport` wrote
  the image, the segmentation and its legend beside it; every path came back absolute.

## Checks

`uv run tools/gate.py full` passed on `0db7e8e` and on `637bd3b`.
