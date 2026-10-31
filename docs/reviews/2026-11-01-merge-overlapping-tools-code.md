---
subject: "Merge the four pairs of tools that do one job, a tool contract change from 42 tools to 38 (#77)"
base: main (fd3fabf)
head: 360689f
date: 2026-11-01
round: 1
tier: "split (two fresh reviewers on Claude Opus: the camera and robot merges; the mesh and scene merges, the harness and the docs)"
verdict: needs-fixes
---

# Review: Merge the four pairs of tools that do one job, a tool contract change from 42 tools to 38

Read from the branch's diff against `main`, 36 files and +1838/-644 with the plan, split in two: the camera and
robot merges (`set_camera`, `get_robot_info`, `_bridge.py`'s `bridge_answer`, `Helpers.fits` and `write_response`,
their tests, and step 6's extension text); the mesh and scene merges, `call_tool` and the live tests, `REMOVED`, and
every doc and skill the plan names. The first half was clean; the second found one minor, fixed by the author. No
second round follows, as none is a blocker or a major.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `test_project/scenarios.md`, 18.1 | 18.1's Verify still asked for "meshes array populated", the per-mesh list the merge drops from `get_mesh_stats`. An AI tester running the scenarios (`test_project/CLAUDE.md`) finds no such list in the merged answer and marks 18.1 failed, or warns, against a tool that answers as designed | fixed in `cffe3f2`: it checks the totals (`mesh_count`, `total_faces` and `total_vertices` above 0), then the tree under `/World/Franka` with `subtree_faces` above its meshes, and says a `max_depth` that reaches the meshes lists each one with its counts |

Refuted, each from the code:

- **The camera and the robot:** an angle of 0, which counts as given, since each check is `is not None`, and goes to
  the route as 0 (tested); a distance of 0, which the schema's `exclusiveMinimum` refuses before the tool runs; each
  mixed form, whose error names what to drop or give, so the call that follows it is one of the two forms; no request
  on a refusal, as every check comes before the first bridge call (`calls == []` in each refusal's test); the answer
  texts, as the plan's Design gives them; `prim_path: null`, which the schema refuses as not a string, not a call
  taken for a point; a stopped robot, which gets its structure and the `not read` line (tested, and live in
  `test_14_05`); the two requests' errors, `/robot/info`'s the tool's own with no second request, `/robot/joint_states`'
  a line, and a Kit that can't be reached failing the call on either (`bridge_answer`); the `not read` line carrying
  the route's `error` without its traceback, which would turn one line into several; the units, radians named in the
  block's header as Q5 approved; the inline-or-file split, which counts the header and the joint states and not the
  `Wrote ...` line, so an inline answer can pass 1,000 characters by that line, about 100, as the plan's rule
  allows; an `Articulation` made per call, stopped too, as `get_joint_states` made one (C6); the other tools,
  unchanged in the contract; the contract at 38 tools, regenerated in each step; `REMOVED`, holding the four names;
  step 6's text and its handler test; the live tests `test_12h` and `test_14_05`.
- **The mesh, the scene, the harness and the docs:** `_without_total` on an empty tree, whose one line, `""`, doesn't
  start `# total:`, so it is kept, with no index error; only a last `# total:` line dropped, one mid-tree kept
  (tested); a root of `/` at `max_depth` 0, left as Q12 decided; 2 levels by default, as Q6 decided; a mesh without
  face data, in the tree with 0 faces and not in the totals, as `docs/TOOLS.md` says (C7); the output files,
  `mesh_stats_NNNN.txt` and `robot_info_NNNN.txt` in `responses/`, the labels `face_count_tree` and `joint_states` no
  longer written, as Compatibility says; an empty `filter_types` or `property_filter`, which gives the list (the
  plan's I2, tested); the depth bounds, 0 up with no maximum, -1 refused before the bridge (`tests/test_server.py`);
  `property_filter` alone, which sends `include_properties` true (tested); `scene_dump.txt`'s place, the server's
  output folder, written by Kit as before; Q15's lost form, named in `docs/TOOLS.md` and the CHANGELOG; `call_tool`,
  which builds the server as production does, `create_server` on a `BridgeClient` with the server's 120 s timeout;
  Kit on the test's machine, which the live tests need to read Kit's `scene_dump.txt`, as the live suites already
  assume; the response counters, which restart with each `call_tool`'s server, so `test_14_05` reads each file right
  after its call; `REMOVED` and the CHANGELOG, whose Breaking changes and #82's lines (Q13) name the removed tools and
  which the test doesn't read; the skills' `allowed-tools`, read-only tools of the 38 only, as the gate's plugin check
  holds; the plugin's window between the merge and 0.3.0, as Compatibility and Q14 say; the writing rules.

Improvements:

| Improvement | Answer |
|---|---|
| I1 (both reviewers): `test_a_removed_tool_is_neither_listed_nor_named` reads each tool's parameter descriptions too, which a client shows the model beside the tool's, and `docs/AI_GUIDE.md`, which agents without the plugin read | taken in `e86c700`: `_naming_removed` reads both, nothing names a removed tool there today, and `test_a_removed_tool_named_in_a_parameter_or_a_file_is_found` plants one in each and finds it. Planted by hand in `get_scene_tree`'s `root` description and in `docs/AI_GUIDE.md`, one at a time, each failed the check, naming where |
| I2: `call_tool` and `tests/test_tools.py`'s `_call` share one harness | left: a refactor outside the merge |
| I3: `docs/TOOLS.md`'s "Where answers go", `docs/ARCHITECTURE.md`'s "Long text" and `server.py`'s module docstring say a long answer goes to `responses/` whole | taken in `6169635`: each says `get_mesh_stats` and `get_robot_info` write only their long part, the tree, or the Joints list and the joint states that don't fit, and keep the rest inline |
| The `simulate` skill's trap row, "`get_robot_info` says `Joint states: not read`": play or pause, where the same line comes without an articulation or without Isaac Sim, and playing doesn't help | taken in `0e58367`, by `write-skill`'s rules: the line gives the reason; stopped, play or pause; no articulation at or under the path, or no Isaac Sim, give the robot's root or read the joints in Isaac Sim |

Not covered: the reviewers had no Kit and ran nothing live. USD Composer, Kit 107 and Isaac Sim 5.1 are untried, so
the `not read` line without Isaac Sim was read in the code and its handler test, not seen in a Kit app.

## Live run

On `360689f`, Isaac Sim 6.2 headless at 8212 with the branch's extension, a fresh Kit for each run:

- **The new tests,** `77-live.sh new` (`test_03c`, `test_12h` and `test_23b`, and `test_14_05` with scenarios 2.1, 4.5
  and 10.1, which it stands on): 7 passed in 4.50 s, printing "Listed to depth 1, dumped 4 prims to scene_dump.txt,
  listed to depth 20", "At a point, around /World/IntTestServerAim at [1.0, 2.0, 0.5], and the mix refused with the
  camera where it was", "/World/IntTestServerMesh: the totals, then its tree of 2 prims" and "Paused: 43 DOF read
  through the server; stopped: the structure, and why there are no states".
- **Both suites whole,** `77-live.sh all`, on another fresh Kit: 188 passed and 16 subtests in 146.78 s.

The fixes' re-run: not needed. They change docs, a skill, a scenario and a contract test (`cffe3f2` to `0e58367`), and
no tool's code or the extension, so the run on `360689f` stands for the head.

## Checks

- **The gate,** `uv run tools/gate.py full`, before each of the branch's commits, and again on each of steps 2 to 7
  as they stand after a fixup rebase (`331fcfe` to `360689f`), each checked out in turn: 15 checks passed on each,
  coverage from 96.66% to 96.87%; on `360689f`, 1569 passed and 206 skipped.
- **The gate on each fix,** `cffe3f2`, `e86c700`, `6169635` and `0e58367`, checked out in turn: 15 checks passed on
  each; 1571 passed and 206 skipped from `e86c700` on, with I1's two new tests, coverage 96.85% to 96.87%.
- **`call_tool` and the live tests' parsing,** before the live run, against the mock bridge: `set_camera`'s two forms
  and a mix, and `get_scene_tree`'s file; `test_14_05`'s and `test_23b`'s parsing on answers the real tools build
  from G1-sized and mesh-sized route answers, paused with 43 and with 3 DOF, and stopped.
