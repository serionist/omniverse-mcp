---
title: Merge the four pairs of tools that do one job, a tool contract change from 42 tools to 38
issue: "#77"
status: draft
approved_by:
approved_at:
---

# Merge the four pairs of tools that do one job, a tool contract change from 42 tools to 38

#77 asked for fewer, clearer tools; the maintainer's comment of 2026-10-31 narrowed it to the four pairs that do the
same job. Each pair becomes one tool under one of its two names, on the server alone: the merged tools call the bridge
routes they call today, so the Kit extension, the wire protocol and the live suites' calls stay as they are. Tool
names, schemas and annotations are a one-way door (`AGENTS.md`): the PR names the change in its title, CHANGELOG's
Breaking changes says it, and it ships as 0.3.0.

## Goal

When this is done the server lists 38 tools, and an agent has one tool for each of these questions:

| Today | Merged into | The caller chooses by |
|---|---|---|
| `set_camera`, `look_at_prim` | `set_camera`: aims at a point or a prim | `position` for a point, `prim_path` for a prim |
| `get_robot_info`, `get_joint_states` | `get_robot_info`: the joints' structure, and their positions while physics runs | nothing: one answer holds both |
| `get_mesh_stats`, `get_prim_face_count_tree` | `get_mesh_stats`: totals, then the faces per subtree | `max_depth`, how far the tree goes |
| `get_scene_tree`, `dump_scene` | `get_scene_tree`: the tree returned, or written by Kit with properties | `include_properties` or a filter writes the file |

Why: overlapping tools make an agent pick wrongly, and Glama's coherence score marks the count and the overlap
(#77's body). A merge is worth it only where it makes the tools clearer for agents, so no merged tool takes a mode
switch: each form is chosen by the parameters its job needs, and a mix that means nothing is an error that says
what to drop.

| In scope | Out of scope |
|---|---|
| The four merges: the server's tools, their descriptions, the tool contract, `docs/TOOLS.md`, the READMEs, the plugin's skills, `test_project/scenarios.md`, CHANGELOG's Breaking changes | The renames (`sim_control`, `viewport_light`, `raycast`, `manage_extensions`) and `create_variant_structure` with `set_variant_selection` (the maintainer, 2026-10-31) |
| `set_camera`'s answer without a target, which #82 left to this merge (Q2) | Going down to 25 tools: multi-mode tools |
| The extension's one error text that names a removed tool, and comments that do (Q11) | Merging the routes (Q9); the `mcp` helper inside `execute_script`, which calls the handlers and keeps its names |
| The face count tree's depth for a root of `/`, found reading the code (Q12) | Joint positions in degrees (Q5): its own issue |
| | The release: 0.3.0's release PR follows this one (`docs/releasing.md`, Q14) |

## What the code says

### Both ends of the eight tools, at `fd3fabf`

Server paths are under `src/omniverse_mcp/`, `extension.py` and `handlers/` under
`extension/ovmcp.bridge/ovmcp/bridge/`, `core/` under `extension/ovmcp.bridge/ovmcp/`.

| Tool | The server's tool | Client | Route | Handler |
|---|---|---|---|---|
| `set_camera` | `tools/camera.py:200-225` | `camera_set`, `client.py:396-400` | `/camera/set`, `extension.py:125` | `handle_camera_set`, `handlers/camera.py:494-522` |
| `look_at_prim` | `tools/camera.py:227-255` | `camera_look_at`, `client.py:402-408` | `/camera/look_at`, `extension.py:126` | `handle_camera_look_at`, `handlers/camera.py:525-584` |
| `get_robot_info` | `tools/robot.py:48-80` | `get_robot_info`, `client.py:366-367` | `/robot/info`, `extension.py:115` | `handle_get_robot_info`, `handlers/robot.py:134-204` |
| `get_joint_states` | `tools/robot.py:82-103` | `get_joint_states`, `client.py:369-370` | `/robot/joint_states`, `extension.py:116` | `handle_get_joint_states`, `handlers/robot.py:212-280`; `articulation_root`, `core/robot.py:28-35` |
| `get_mesh_stats` | `tools/usd_advanced.py:18-44` | `mesh_stats`, `client.py:523-524` | `/scene/mesh_stats`, `extension.py:133` | `handle_mesh_stats`, `handlers/scene.py:581-596`; `_compute_mesh_stats`, `handlers/_utils.py:261-297` |
| `get_prim_face_count_tree` | `tools/usd_advanced.py:46-60` | `face_count_tree`, `client.py:526-527` | `/scene/face_count_tree`, `extension.py:134` | `handle_face_count_tree`, `handlers/scene.py:604-678` |
| `get_scene_tree` | `tools/scene.py:39-61` | `scene_tree`, `client.py:244-250` | `/scene/tree`, `extension.py:101` | `handle_scene_tree`, `handlers/scene.py:37-89`; `format_scene_tree`, `core/formatter.py:207-246` |
| `dump_scene` | `tools/scene.py:63-94` | `scene_dump`, `client.py:252-271` | `/scene/dump`, `extension.py:102` | `handle_scene_dump`, `handlers/scene.py:97-140`; `format_scene_dump`, `core/formatter.py:148-204` |

Shared by all: `tools/_annotations.py:15-17` (`READS`, `EDITS`), `tools/_params.py:7` (`PrimPath`),
`tools/_bridge.py:17-39` (`bridge_call`), `server.py:44` and `:128-135` (`FILE_THRESHOLD`, `text_response`),
`server.py:47-60` (`INSTRUCTIONS`, whose line 51 names `dump_scene`), `tests/fixtures/mcp-tools.json` (42 tools),
written by `tools/golden.py`.

### What the code does

| # | What | Where |
|---|---|---|
| C1 | Each pair has the same hints: `set_camera` and `look_at_prim` are `EDITS`, the other six `READS`. Only `max_depth`'s bounds differ: `get_scene_tree` 0 to 15, 5 by default; `dump_scene` 0 up, 15; `get_prim_face_count_tree` 0 up, 10 | `tests/fixtures/mcp-tools.json`; `tools/scene.py:42-49`, `:66`; `tools/usd_advanced.py:49` |
| C2 | `set_camera` without a target: the handler aims at the world origin and answers `target: None`, and the server prints "looking at" only for a target given, so the answer doesn't say where the camera looks. #82 left it for this merge | `handlers/camera.py:505`, `:521`; `tools/camera.py:221-225` |
| C3 | `look_at_prim`: the prim's world box, a distance of 2.5 times its largest side when none is given, a point on a sphere around the box's centre by azimuth and elevation for the stage's up axis, aimed at that centre | `handlers/camera.py:536-567` |
| C4 | `/robot/info` reads USD only, in any state of the simulation; its joints come in the order `set_joint_targets`' list follows | `handlers/robot.py:134-204`; `tools/robot.py:110-114` |
| C5 | `/robot/joint_states` reads the first articulation root at or under `prim_path`, and errs with no articulation there, without Isaac Sim (a message that names `get_joint_states`), stopped ("play or step the simulation first"), or on a failure in Isaac's API | `handlers/robot.py:229-269`; `core/robot.py:28-35` |
| C6 | That route makes a new Isaac Sim `Articulation` on each call, stopped too, as today's `get_joint_states` does. Isaac Sim 6.2 registers its callbacks through `weakref.proxy`, drops them when the object is collected, and sets up its physics view only when a simulation view already exists (`_physics_sim_view__warp`), never loading one itself | Isaac Sim 6.2's `isaacsim.core.experimental.prims`, `impl/prim.py:85-96`, `:297-300`, `impl/articulation.py:173-188`; `isaacsim.core.simulation_manager`, `impl/simulation_manager.py:1163-1260` |
| C7 | `/scene/mesh_stats` skips a mesh without `faceVertexCounts`; `/scene/face_count_tree` counts it with 0 faces, and its last line, `# total:`, counts only the meshes within `max_depth` | `handlers/_utils.py:280-281`; `handlers/scene.py:619`, `:651-652`, `:675` |
| C8 | `/scene/face_count_tree` with a root of `/` lists one level fewer than asked, and nothing at `max_depth` 0: the pseudo-root counts as depth 1 (E1) | `handlers/scene.py:644-652` |
| C9 | `/scene/tree`'s text holds each prim's path, type and position, and `children = N (truncated)` at `max_depth`; the server writes an answer over 1,000 characters to `responses/scene_tree_NNNN.txt` | `handlers/scene.py:48-51`; `core/formatter.py:207-246`; `server.py:128-135` |
| C10 | `/scene/dump`: Kit writes `<output_dir>/scene_dump.txt`, each block with rotation, world box, physics flags and the attributes; `property_filter` applies only with `include_properties`; `filter_types` still walks the other prims' children | `handlers/scene.py:97-140`; `core/formatter.py:129-133`, `:170-174` |
| C11 | `get_scene_tree`'s cap of 15 was the old server's quiet clamp, which #24 made a bound | `CHANGELOG.md:291` |
| C12 | `execute_script`'s `mcp` helper calls the handlers: `mcp.set_camera`, `mcp.look_at`, `mcp.scene_tree` | `handlers/_mcp_bridge.py:29`, `:38`, `:73` |
| C13 | The live suites call the routes through `BridgeClient`, never the server's tools | `tests/test_integration.py:315`; `tests/test_scenarios.py` |
| C14 | `tests/test_tools.py`'s `_check` holds one route per tool call | `tests/test_tools.py:554` |
| C15 | The gate's plugin check refuses a skill whose `allowed-tools` names a tool that isn't a read-only tool of the contract | `tools/gate.py:373-390`, `:710` |

### The SDK, and a probe

Read in the MCP Python SDK 2.3.0 (Context7, and the installed package), and probed with the repo's own server on no
Kit (`probe_sdk.py` and `probe_root.py` in the session's scratchpad, not kept):

| # | What | Where |
|---|---|---|
| S1 | A call to a name the server doesn't list is an error result, `Unknown tool: <name>`, not a protocol error | SDK docs, "Calling a tool"; probe |
| S2 | An argument a tool doesn't take is dropped without a word; a required one left out is a validation error | `mcp/server/mcpserver/utilities/func_metadata.py:112`, no `extra="forbid"`; probe: `get_mesh_stats(prim_path, root)` reached the bridge, `get_mesh_stats(root)` was refused for `prim_path` |
| E1 | `handle_face_count_tree`'s depth rule on usd-core: root `/` lists nothing at `max_depth` 0, and `/` with `/World` at 1; root `/World` lists itself at 0, and `/World/M` too at 1 | `probe_root.py` |

## Design

### The camera: `set_camera` takes `look_at_prim`'s job (Q1 to Q3)

`set_camera` keeps its name: it is the general one (a camera set by a point or by a prim), and the name
`capture_viewport`'s description, `docs/TOOLS.md`'s `inspect_prim` section ("as `set_camera` does") and the `mcp`
helper already use for aiming. `look_at_prim`'s parameters join it under their own names, so its callers change only
the tool's name.

| Parameter | Type and default | Says |
|---|---|---|
| `position` | `list[float] \| None`, `None` | `[x, y, z]` where the camera stands, in world space: for a point |
| `target` | `list[float] \| None`, `None` | `[x, y, z]` the world point it looks at, the world origin when left out: for a point |
| `prim_path` | `str`, `""` | a prim to frame instead: the camera aims at the centre of its world box |
| `distance` | `float \| None`, above 0, `None` | from the prim's centre in stage units; 2.5 times its largest side when left out |
| `azimuth` | `float \| None`, `None` | degrees around the prim: 0 the front (+Y on a Z-up stage, +Z on a Y-up one), 90 the right (+X), 180 the back, 270 the left; 45 when left out |
| `elevation` | `float \| None`, `None` | degrees above the horizontal; 30 when left out |

`azimuth` and `elevation` default to `None`, where `look_at_prim` showed 45 and 30, so the server can tell one given
without a prim from one left out: given alone, it would be dropped without a word, as #25 found three tools doing.

**The server decides before any request,** in this order:

| The call | What happens |
|---|---|
| `prim_path` with `position` or `target` | Error: `prim_path frames the prim from distance, azimuth and elevation: leave position and target out, or leave prim_path out to aim from a position (get_prim_bounds gives a prim's centre)` (Q3) |
| `distance`, `azimuth` or `elevation` without `prim_path` | Error: `distance, azimuth and elevation place the camera around prim_path: give prim_path, or position and target` |
| neither `position` nor `prim_path` | Error: `give position, where the camera stands, with target, the point it looks at; or prim_path, a prim to frame` |
| `position`, equal to the point it looks at | Error, as #82 made it: `position [0, 0, 0] is the world origin, which it looks at without a target: ...` |
| `position` | `/camera/set` with `position` and `target`, as `set_camera` sends them today |
| `prim_path` | `/camera/look_at` with `prim_path`, `distance`, and the angles, 45 and 30 for those left out, as `look_at_prim` sends them today |

**The answer:**

| The call | Answer |
|---|---|
| a point with a target | `Camera at [5, 3, 5] looking at [0, 0, 0]`, as today |
| a point without a target (Q2) | `Camera at [5, 3, 5] looking at [0, 0, 0], the world origin: no target was given` |
| a prim | `Camera at [3.0619, 3.0619, 3.0] looking at the centre of /World/Cube, [0.0, 0.0, 0.5]`, then `Distance: 5.0 stage units, Azimuth: 45.0deg, Elevation: 30.0deg`, as `look_at_prim`'s second line |

The handler answers the point it aimed at for a prim (`target`), so the prim's path is the server's own, from the
call. Q2's line is the server's too: it sent no target, so the extension aimed at the origin, in every release.

**The description** says the two forms first, then what it moves: "Move the viewport's camera and aim it, at a world
point or at a prim. For a point, `position` is where the camera stands and `target` what it looks at, the world origin
when left out. For a prim, `prim_path`, and the camera goes around the prim's centre at `distance`, `azimuth` and
`elevation`, without `position` or `target`." Then today's sentences: it moves whichever camera the viewport looks
through, a scene camera included, and the user sees the move; `inspect_prim` captures a prim from up to 14 sides,
`capture_viewport`'s `camera_path` captures from another camera without moving the viewport; the errors.

**Elsewhere:** `CAMERA_LIGHT_ON_ADVICE` (`tools/camera.py:83-87`) says "move the camera with `set_camera`'s
`prim_path`"; `capture_viewport`'s and `set_prim_transform`'s descriptions name `set_camera` alone.

| Alternative | Why not |
|---|---|
| `look_at_prim` as the name | Names one of the two jobs; `set_camera` is the name the docs, the other tools' descriptions and the `mcp` helper use for aiming |
| `target` as a point or a prim path (`list[float] \| str`) | One parameter fewer, but a type agents fill wrongly, and `distance`, `azimuth` and `elevation` still need a prim |
| A `mode` parameter, `"point"` or `"prim"` | A switch an agent can set against its other arguments; the parameters already say which job |
| A prim with a position: aim from there at the prim's centre (Q3) | A third form, and a bounds request before the aim; the refusal names `get_prim_bounds`, and nobody has asked for it |

### The robot read: `get_robot_info` takes `get_joint_states`' job (Q4, Q5)

`get_robot_info` keeps its name: its answer is the robot, the joints' state now part of it, and `create_robot` and
`set_joint_targets` already point at it. It keeps its one parameter, `prim_path`, which `get_joint_states` took too.

**Two requests, every call, no switch:**

1. `/robot/info`, as today. An error, such as a prim that isn't there, is the tool's error, and nothing more is asked.
2. `/robot/joint_states`. Its answer is a block of the text; an error answer from the route is a line that says why,
   not the tool's error. A connection failure fails the call, as for every tool.

**The answer,** the first part as today, the second new:

```text
Robot: /World/Franka
Articulation: True
DOF: 9
Links: 11
Joints (12):
  panda_joint1 (PhysicsRevoluteJoint [-166.0, 166.0] drive=angular)
  ...
Joint states (9 DOF, from physics: radians for revolute joints, stage units for prismatic ones, velocities per
second; set_joint_targets takes degrees):
  panda_joint1: pos=0.0000 vel=0.0000
  ...
```

Stopped, without Isaac Sim, or with no articulation: `Joint states: not read: <the route's error>`, such as
`No physics view of /World/Franka: play or step the simulation first; ...`. Long answers go to
`responses/robot_info_NNNN.txt`, as today's `get_robot_info` does.

The two lists stay apart: the Joints list is in the order `set_joint_targets`' list follows, fixed joints included,
and the states in physics' own order of degrees of freedom. Lines joined per joint would need each DOF matched to a
USD joint by name, and would hide which order a list follows.

**Safe to ask while stopped:** the route makes an Isaac Sim `Articulation` per call, stopped too, as `get_joint_states`
does today when called stopped (scenario `14_04`); its callbacks go when it is collected, and it loads no physics then
(C6).

**The description:** "Read a robot: from USD, at any time, whether it is an articulation, its link and DOF counts, and
each joint's name, type, limits and drive; from physics, while the simulation plays or is paused, each joint's
position and velocity." Then the units and the two orders, and that a stopped simulation or a Kit app without Isaac
Sim gives the structure with a line saying why there are no joint states.

| Alternative | Why not |
|---|---|
| `get_joint_states` as the name | Names the smaller part: the structure needs no physics and is what a caller reads first |
| A `joint_states: bool` parameter | An agent that wants where the joints are leaves it out and reads no positions; the second request costs one Kit update |
| Fail when stopped, as `get_joint_states` did | Loses the structure for a reason that isn't about it |
| One line per joint, structure and state | Needs DOF names matched to USD joints, which can repeat across a robot's subtrees, and mixes the two orders |

### The face count: `get_mesh_stats` takes `get_prim_face_count_tree`'s job (Q6)

`get_mesh_stats` keeps its name, the shorter one, which covers totals and their breakdown, and its parameter
`prim_path`, still required: a call of today's `get_mesh_stats` stays valid. It gains `max_depth` (`int`, 0 up, 2 by
default): how many levels of the tree to list.

**Two requests:** `/scene/mesh_stats` for the totals, then `/scene/face_count_tree` with `prim_path` as its `root`.

**The answer:** the totals, inline always, then the tree, inline when the whole answer is 1,000 characters or less,
otherwise written to `responses/mesh_stats_NNNN.txt` with its path in the answer:

```text
[/World/Franka]
meshes = 25
total_faces = 120000
total_vertices = 60000
total_triangles = 240000

# face_count_tree root=/World/Franka
[/World/Franka]
type = Xform
subtree_faces = 120000
...
```

- **Dropped:** today's per-mesh list for 20 meshes or fewer, since the tree lists each mesh with the same three
  counts; and the tree's last line, `# total: N faces in M meshes`, which counts only the meshes within `max_depth`,
  and a mesh without face data that the totals skip (C7), so it would contradict the totals above it. The server
  drops a last line that starts `# total:`; a tree without one is left whole.
- **2 by default,** where the tree took 10: the root, its children and theirs, each with `subtree_faces`, which reads
  inline and says where the faces are; the route walks the whole subtree at any depth (C7), so a deeper call costs
  only text. A heavy subtree is the next call's `prim_path`.

**The description:** "Count the faces, vertices and triangles of every mesh at or under a prim: the totals, then the
prims under it to `max_depth`, each mesh with its counts and each prim above meshes with `subtree_faces`." Then: use it
for a geometry budget, what a simplification saved, or the heavy subtrees; `compare_prims` for two; only
`UsdGeom.Mesh` counts, inside instances too; prims below `max_depth` aren't listed but count in the totals and their
ancestors' `subtree_faces`.

| Alternative | Why not |
|---|---|
| `get_prim_face_count_tree` as the name | Long, and names only the tree |
| `prim_path` with `/World` as default, as the tree had | Not every stage has `/World`; a required path keeps today's `get_mesh_stats` calls valid |
| 10 levels by default, as the tree had | A robot's tree at 10 levels runs to a file nearly always, where the question is usually the top levels |
| Totals from the tree's text, one request | The tree has no vertex or triangle totals, and its face total stops at `max_depth` |
| The tree's route answering totals too | A wire change, with a fallback for older extensions, to save one request |

### The scene tree: `get_scene_tree` takes `dump_scene`'s job (Q7, Q8)

`get_scene_tree` keeps its name: the lightest look at a scene is the common call, and the server's instructions, the
`omniverse://scene/tree` resource and the skills lead with it. It gains `dump_scene`'s parameters under their names.

| Parameter | Type and default | Says |
|---|---|---|
| `root` | `str`, `"/"` | as both tools had it |
| `max_depth` | `int \| None`, 0 up, `None` | levels below `root`: 5 when left out, or 15 with properties or a filter (Q8); no upper bound, where the list stopped at 15 (C11) |
| `include_properties` | `bool`, `False` | each prim's rotation, world box and attribute values, written by Kit to `mcp_output/scene_dump.txt` |
| `filter_types` | `list[str] \| None`, `None` | only prims of these types, written to the file; the others' children are still walked |
| `property_filter` | `list[str] \| None`, `None` | only properties whose names hold one of these, written to the file; it takes the properties with it |

**Which route:**

| The call | Route | Answer |
|---|---|---|
| none of `include_properties`, `filter_types`, `property_filter` | `/scene/tree`, text, as today | The blocks, inline, or in `responses/scene_tree_NNNN.txt` when over 1,000 characters, as today |
| any of them | `/scene/dump`, with `include_properties` true when it or `property_filter` is given | `Dumped 120 prims under /World, to depth 15 (48,213 bytes) -> mcp_output/scene_dump.txt` |

The depth is new in the file's answer: the dump's blocks don't mark a prim whose children were left out, so the
answer says how deep it went. `include_properties` is false when left out, where `dump_scene` took true: the light list
stays the default, and `dump_scene(root)` becomes `get_scene_tree(root, include_properties=True)`.

**The description:** "List the stage's prims under `root` as prim blocks: each one's path, type and world position,
to `max_depth`." Then today's sentences on `children = N (truncated)` and instances (`get_mesh_stats` looks inside),
and: "With `include_properties`, `filter_types` or `property_filter`, Kit writes the blocks, with each prim's rotation,
world box and attribute values, to `mcp_output/scene_dump.txt`, replacing the last, and the answer gives its path and
how many prims it holds: grep it, or read it in parts. Kit writes that file itself, so with Kit on another machine it
lands there." `get_prim_properties` reads one prim inline.

| Alternative | Why not |
|---|---|
| `dump_scene` as the name | Names the heavier form; agents look for a tree first |
| A `to_file` or `output` parameter | A switch beside the parameters that already say what is wanted; the list already goes to a file when long |
| One route for both, the dump | Kit writes the file on its own machine, which a remote client can't read, and the list's `children = N (truncated)` goes |
| One `max_depth` default, 5 or 15 | 5 cuts a properties dump short without a mark where `dump_scene` went to 15; 15 makes the lightest look heavy |

### Server only, routes unchanged (Q9)

The merged tools call the eight routes as they are, through the client's methods as they are.

- **No wire change:** paths, bodies and answers stay; `PROTOCOL` stays 1.
- **Any extension of 0.2.x** answers the four merged tools: every route they call is in 0.2.0's extension.
- **The `mcp` helper** in `execute_script` (`mcp.set_camera`, `mcp.look_at`, `mcp.scene_tree`) calls the handlers and
  keeps its names (C12), so the script skill's trap row stays true.
- **The live suites** call the routes (C13) and stay; new live tests go through the server (Tests).
- **The cost:** two requests for `get_robot_info` and `get_mesh_stats`, each a read; the client holds one request at
  a time, so another tool's edit can land between the two (Risks).

Merging the routes would add an extension change, a fallback for older extensions, and new route tests, and give an
agent nothing the server-side merge doesn't.

### A removed tool's name (Q10)

Gone. The server no longer lists it, and a call to it is an error result, `Unknown tool: look_at_prim` (S1): MCP has
no aliases, and a stub registered under the old name would be listed beside the merged tool, the overlap this removes.
Every argument of a removed tool's call is a parameter of its merged tool under the same name, but
`get_prim_face_count_tree`'s `root`, which the SDK would drop (S2): `get_mesh_stats` requires `prim_path`, so such a
call is refused for it, not run on the wrong prim.

Moved with this change, so nothing in the repo but its dated plans and reviews names a removed tool as a tool: the
plugin's skills (their `allowed-tools`, which the gate checks against the contract, C15, and their text),
`test_project/scenarios.md`, the server's instructions, every description, doc and code comment that names one, and
the docstrings of the route tests (Docs). The route tests' own names, such as `test_03_03_look_at_prim`, stay: they
follow the scenarios' numbering and test routes that stay. Users' own prompts and notes move by CHANGELOG's Breaking
changes, which maps each.

### The extension's text, and the tree's root (Q11, Q12)

Nothing the merge needs, but the merged tools show them:

- **`handlers/robot.py:241`:** `get_joint_states needs Isaac Sim's isaacsim.core.experimental.prims extension: ...`
  becomes `Joint states need Isaac Sim's ...`, since `get_robot_info` now shows it as its line. Comments and a log
  label that name a removed tool: `core/formatter.py:14`, `core/robot.py:1`, `core/xform.py:451`, and
  `handlers/camera.py:572`'s `_settle_or_log("look_at_prim")`, which Kit's log shows, as `set_camera`.
- **`handlers/scene.py:644-652`:** the depth is `p.GetPath().pathElementCount - root.GetPath().pathElementCount`, so
  a root of `/` lists `/` at 0 and `/World` at 1 (E1). `get_mesh_stats` takes any `prim_path`, `/` the likeliest for
  the whole stage, where the tree's default was `/World`.

Both need this release's extension; an older one keeps the old text and depth, and the merged tools work on it.

## Compatibility

The tool contract is a one-way door (`AGENTS.md`). The maintainer agreed to the merge in #77's comment of 2026-10-31;
the PR names it in its title; it ships in 0.3.0, a minor that may break the contract in `0.x`, under Breaking changes.

| Door | Effect |
|---|---|
| Tool names | `look_at_prim`, `get_joint_states`, `get_prim_face_count_tree` and `dump_scene` go: 42 tools to 38 |
| Schemas | `set_camera`: `position` no longer required; `prim_path`, `distance`, `azimuth` and `elevation` added. `get_mesh_stats`: `max_depth` added. `get_scene_tree`: `max_depth` `None` by default with no maximum; `include_properties`, `filter_types` and `property_filter` added. `get_robot_info`: unchanged |
| Annotations | Unchanged: each pair had the same hints (C1) |
| Resources | Unchanged: `omniverse://scene/tree` reads `/scene/tree` to depth 5 as before (`server.py:151-154`) |
| The output folder | The same folders and fixed names: `scene_dump.txt`, written by Kit, now for `get_scene_tree` with properties or a filter; `responses/<label>_NNNN.txt`, where the labels `joint_states` and `face_count_tree` are no longer written, their answers being part of `robot_info` and `mesh_stats` |
| Wire protocol | Unchanged: same routes, bodies and answers; `PROTOCOL` stays 1 |
| The extension's id and settings | Unchanged; one error text (Q11) |
| The console script, its flags and variables; the plugin's, the server key's and the registry's names; where `extension install` puts the extension | Unchanged |

What users notice:

| Before | After |
|---|---|
| `look_at_prim(prim_path, distance, azimuth, elevation)` | `set_camera(prim_path=..., distance=..., azimuth=..., elevation=...)` |
| `set_camera` needed `position` | `position` for a point, or `prim_path` for a prim; both, or neither, is an error saying what to drop |
| `set_camera(position)` looked at the origin, and the answer didn't say | The answer says it looks at the world origin, no target having been given |
| `get_joint_states(prim_path)`, an error while stopped | `get_robot_info(prim_path)`: the structure always, the joint states while the simulation plays or is paused, and why not otherwise |
| `get_prim_face_count_tree(root, max_depth=10)` | `get_mesh_stats(prim_path=root, max_depth=...)`: the totals, then the tree, 2 levels by default |
| `get_mesh_stats` listed each mesh when there were 20 or fewer | The tree lists the meshes within `max_depth` |
| `dump_scene(root, ...)`, properties included by default | `get_scene_tree(root, include_properties=True, ...)`: the same file, 15 levels by default |
| `get_scene_tree` refused a `max_depth` over 15 | Any depth |
| A call to a removed tool | `Unknown tool: <name>` |

- **Mixed releases:** a 0.3.0 server on any 0.2.x extension runs the four merged tools, since 0.2.0's extension has
  every route they call; Q11's text and Q12's depth need the new extension, as #82's fixes do, and the other tools
  are as before. A 0.2.x server on the 0.3.0 extension runs its 42 tools: the routes and `PROTOCOL` are the same.
- **The plugin:** its skills and its pinned server move together at the release. The marketplace serves `main`, so
  between this merge and 0.3.0 a plugin user gets the new skills over a 0.2.3 server, whose `set_camera` has no
  `prim_path` (Q14).
- **Kit apps:** the routes are unchanged, so nothing changes per Kit app. The live tests run on Isaac Sim 6.2.

## Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | The camera: keep `set_camera`, with `look_at_prim`'s parameters under their names, `prim_path` choosing the prim form and `position` no longer required? | Yes: the general name, and the one the other tools' descriptions and the docs already give for aiming; `look_at_prim`'s callers change only the tool's name; no mode switch | |
| Q2 | `set_camera` without a target (#82's open question): aim at the world origin and say so in the answer; keep the camera's direction and only move it; or require a target? | Aim at the origin and say so: the description has said so since #83, every extension does it, and the server alone can say it. Keeping the direction needs an extension change, and a new server on an old extension would turn the camera anyway; requiring a target breaks a documented default for nothing | |
| Q3 | `set_camera` with `prim_path` and a `position` or `target`: refuse, naming what to drop and `get_prim_bounds`; or aim from the position at the prim's centre? | Refuse: the merge maps each of the two jobs to one form; aiming from a point at a prim is a third, a bounds request first, which nobody has asked for. Its own issue if agents reach for it | |
| Q4 | The robot: keep `get_robot_info`, always ask both routes, and turn the joint states route's error (stopped, no Isaac Sim, no articulation) into a line under the structure? | Yes: no switch an agent can leave out; the structure never fails for a reason that isn't about it; the second request is a read, as `get_joint_states` made it | |
| Q5 | The joint states' units: radians, as the route gives them, named in the block's header; or revolute positions in degrees, to match the limits and `set_joint_targets`? | Radians, named in the header: degrees need each DOF's type, from the extension (Isaac's `dof_types`) or matched by name to USD's joints, and change what the numbers mean. Its own issue | |
| Q6 | The face count: keep `get_mesh_stats`, `prim_path` required, `max_depth` 2 by default, the totals inline always and the tree inline or in a file, the per-mesh list and the tree's `# total:` line dropped? | Yes: today's `get_mesh_stats` calls stay valid; 2 levels read inline and say where the faces are, at the same cost in Kit as 10; the dropped lines repeat the tree or contradict the totals | |
| Q7 | The scene: keep `get_scene_tree`; `include_properties`, `filter_types` or `property_filter` write Kit's `scene_dump.txt`, `property_filter` taking the properties with it; `include_properties` false by default? | Yes: the parameters that ask for values choose the file, where a `to_file` switch could disagree with them; the light list stays the default call | |
| Q8 | The scene's `max_depth`: left out, 5 for the list and 15 with properties or a filter, and no upper bound; or one default? | Two defaults by form, no bound: each old tool's calls keep their depth, and the file's answer says the depth it used. One default of 5 cuts dumps short without a mark; 15 makes the lightest look heavy | |
| Q9 | Server only, the merged tools calling today's routes; or merge the routes too? | Server only: no wire change, every 0.2.x extension works, the `mcp` helper and the live suites stay; merged routes would give agents nothing more | |
| Q10 | A removed tool's name: gone, `Unknown tool`; or a stub that errs with a pointer to the merged tool? | Gone: a stub is listed beside the merged tool, the overlap this removes, and every listing client already shows the merged tool | |
| Q11 | The extension's `get_joint_states needs Isaac Sim's ...`, which `get_robot_info` now shows, and the comments and log label naming removed tools: reword in this PR? | Yes: a line naming a tool that isn't there sends an agent after it; a few lines, with a handler test for the message | |
| Q12 | The face count tree with a root of `/` lists one level fewer, and nothing at depth 0 (C8, E1), which `get_mesh_stats("/")` now reaches: fix in this PR, or its own issue? | In this PR: one line in the handler, with a handler test, and the merge makes `/` a likely `prim_path` | |
| Q13 | CHANGELOG's Unreleased lines from #82 that name `look_at_prim` and `dump_scene`: leave them, or reword them to the merged tools? | Leave them: they say what 0.2.3's tools did, by the names 0.2.3's users know, and Breaking changes, first in the release, says where each went | |
| Q14 | The release: 0.3.0's release PR right after this merges, since `main`'s skills reach plugin users whose server stays 0.2.3 until then? | Yes, the next PR after this one: the window is skills ahead of their server, as for any change to the skills, but here `set_camera`'s `prim_path` errors on 0.2.3 | |

## Steps

Each step builds and passes `uv run tools/gate.py full`: a step that removes a tool regenerates the contract
(`uv run tools/golden.py`), and moves in the same commit everything that names that tool, since
`tests/test_contract.py` checks `docs/TOOLS.md`'s headings and hints rows and the gate checks the skills'
`allowed-tools` (C15). Skills change through `write-skill`.

| Step | What | Proven by |
|---|---|---|
| 1 | This plan, the branch's first commit | `review-plan`, then the maintainer |
| 2 | `set_camera` takes `look_at_prim`'s job (Q1 to Q3): `tools/camera.py`, `CAMERA_LIGHT_ON_ADVICE`, `capture_viewport`'s and `set_prim_transform`'s descriptions; the contract; `docs/TOOLS.md`; `README.md`'s Camera row; `docs/ARCHITECTURE.md`'s module table and `:474`; the scene skill's step 3; `test_project/scenarios.md` 3.2, 3.3, 3.4, 12.8, 17.6, 26.2; CHANGELOG's Breaking changes, its first line and the camera's | `tests/test_tools.py`, `tests/test_tools_camera.py`, `tests/test_contract.py` |
| 3 | `get_robot_info` takes `get_joint_states`' job (Q4, Q5): `tools/robot.py` (with `create_robot`'s and `set_joint_targets`' descriptions), `sim_control`'s description in `tools/simulation.py`; `Case` takes further routes (Tests); the contract; `docs/TOOLS.md`; `README.md`'s Robots row and `:255`; `docs/ARCHITECTURE.md`'s Robot System and core list; the simulate skill's `allowed-tools`, steps 3 and 6 and trap row; scenarios 14.4; CHANGELOG | `tests/test_tools.py`, `tests/test_contract.py` |
| 4 | `get_mesh_stats` takes `get_prim_face_count_tree`'s job (Q6): `tools/usd_advanced.py`, `get_scene_tree`'s description; the contract; `docs/TOOLS.md`; `README.md`'s Geometry row; `docs/ARCHITECTURE.md`'s module table; the geometry skill's `allowed-tools` and step 1; scenarios 18.4, 18.5; CHANGELOG | `tests/test_tools.py`, `tests/test_contract.py` |
| 5 | `get_scene_tree` takes `dump_scene`'s job (Q7, Q8): `tools/scene.py` (with `get_prim_properties`' description), `server.py`'s instructions and comment; the contract; `docs/TOOLS.md`, its "Where answers go" too; `README.md`'s Scene row; `docs/AI_GUIDE.md`; `docs/ARCHITECTURE.md`; `docs/SETUP.md`; the scene skill's `allowed-tools` and step 2; scenarios 8.1 to 8.4; CHANGELOG | `tests/test_tools.py`, `tests/test_server.py`, `tests/test_contract.py` |
| 6 | The extension (Q11, Q12): the joint states' message, the log label, the comments; `handle_face_count_tree`'s depth; `docs/TOOLS.md`'s line for an older extension's depth; CHANGELOG's Fixed line for Q12 | `tests/test_robot_handler.py`, `tests/test_scene_handler.py` |
| 7 | The live tests below: `call_tool` in `tests/conftest.py`, the through-the-server tests | Run by the session on Isaac Sim 6.2 headless at port 8212 with the branch's extension: the new tests alone, then both suites whole |
| 8 | `finish-work`: the docs, the gate in full, both live suites in full, `review-code`, the PR, titled as this plan | No live failure beyond `main`'s on the same Kit |

## Tests

Each merged tool's new behaviour has a test that fails at `fd3fabf`.

**Unit (CI):**

| File | What |
|---|---|
| `tests/test_tools.py` | `Case` gains `more`, the routes a tool calls after its first, each with its answer, and `_check` holds the routes in order (C14). Cases: `set_camera` with a target (`/camera/set`), without one (the answer names the world origin), and with `prim_path` (`/camera/look_at`, 45 and 30 sent for the angles left out, the answer naming the prim); `get_robot_info` (`/robot/info` then `/robot/joint_states`, both blocks); `get_mesh_stats` (the totals, then the tree, its `# total:` line gone, `max_depth` 2 sent); `get_scene_tree` (`/scene/tree`, 5 sent) and with `include_properties` (`/scene/dump`, 15 sent, the answer's depth). `test_every_tool_has_a_case` holds 38. New tests: `set_camera`'s three refusals send no request; `get_robot_info` with the states route erring gives the structure and the line, no tool error; with `/robot/info` erring, a tool error and no second request; `get_mesh_stats`' tree over 1,000 characters goes to `responses/` with the totals inline; `get_scene_tree` with `filter_types` alone sends `include_properties` false, with `property_filter` alone true, and `max_depth` 20 is accepted |
| `tests/test_tools_camera.py` | `:145-157`: the black-capture advice names `set_camera`'s `prim_path`, not `look_at_prim` |
| `tests/test_server.py` | `:93-101`: the bound refused before the bridge is `max_depth` -1, since 16 is now accepted |
| `tests/test_contract.py` | Unchanged code; the golden file holds 38 tools, `docs/TOOLS.md` a heading and a hints entry for each |
| `tests/test_robot_handler.py` | Without `isaacsim`, as in CI, `handle_get_joint_states` on an articulation root errs with `Joint states need Isaac Sim's`, and no tool's name (Q11) |
| `tests/test_scene_handler.py` | `handle_face_count_tree` with a root of `/`: `/` alone at depth 0, `/World` too at 1 (Q12, E1) |
| The route tests | Unchanged: `tests/test_client.py`, `tests/test_camera_handler.py`, `tests/test_formatter.py` and the rest test routes, which stay |

**Live,** on Isaac Sim 6.2 headless at port 8212, run by the session. The live suites drive routes (C13), so the
merged tools need tests that go through the server: `call_tool(tool, args, output_dir)` in `tests/conftest.py` builds
the server on a `BridgeClient` at `live_bridge()` and calls the tool through the SDK's in-memory client, as
`tests/test_tools.py` does against the mock.

| Test | What |
|---|---|
| `test_integration.py` `test_12h_set_camera_aims_at_a_point_or_a_prim_through_the_server` | A point without a target: the answer names the world origin, and `CAMERA_AIM` reads the camera within 0.5 degrees of it; a prim: the answer names the prim, and the camera aims at its centre; `prim_path` with `position`: an error, the camera unmoved |
| `test_03c_scene_tree_lists_or_dumps_through_the_server` | Its own prims: the list inline with `children = N (truncated)`; `include_properties=True` writes `scene_dump.txt` in the test's output folder, its block count the answer's; `max_depth` 20 accepted |
| `test_23b_mesh_stats_gives_totals_and_the_tree_through_the_server` | A `UsdGeom.Mesh` made by `execute_script` under an Xform: the totals inline, the tree with the mesh's counts and its parent's `subtree_faces`, no `# total:` line; `prim_path` `/` with `max_depth` 1 lists `/World` (with this branch's extension) |
| `test_scenarios.py` `test_14_05_get_robot_info_reads_the_joint_states_through_the_server` | After `14_04`, the G1 paused: the Joints list and a joint states block with `dof_count` lines; stopped: the structure and `Joint states: not read: ... play or step the simulation first` |

**What neither shows:** USD Composer, which isn't on this machine, where `get_robot_info`'s line names Isaac Sim;
Kit 107, since Isaac Sim 5.1 doesn't start here (#25); a real MCP client listing 38 tools with the plugin's skills on
them, which the release PR tries with `claude --plugin-dir` (`docs/releasing.md`, step 2); whether agents pick better,
which nothing here measures.

## Docs

| File | What changes |
|---|---|
| `docs/TOOLS.md` | "Where answers go": the dump is `get_scene_tree`'s with properties or a filter. "Find a tool": four rows name the merged tools. The hints table loses the four names. The contents' counts: Scene 11, Geometry 2, Robot 3, Camera 4. The sections of `look_at_prim`, `get_joint_states`, `get_prim_face_count_tree` and `dump_scene` go; those of `set_camera`, `get_robot_info`, `get_mesh_stats` and `get_scene_tree` say the Design's parameters, forms and answers. Lines that name a removed tool: `get_prim_properties`, `set_prim_transform`, `set_joint_targets`, `capture_viewport`, `sim_control`. `get_mesh_stats`' section says an extension of 0.2.3 or older lists one level fewer under `/` (Q12). The `mcp` helper's table stays |
| The tools' descriptions | As the Design says, in `src/omniverse_mcp/tools/` |
| `src/omniverse_mcp/server.py` | `INSTRUCTIONS`: "get_scene_tree for what is there"; the comment at `:169`: "Kit (get_scene_tree's dump, recordings)" |
| `README.md` | The tool table's Scene, Camera, Robots and Geometry rows; `:255`: "`get_robot_info` reads joint positions while physics plays or is paused" |
| `docs/AI_GUIDE.md` | `:36`: "`get_scene_tree` for what is there, with `include_properties` for many prims' values" |
| `docs/ARCHITECTURE.md` | The module table (`:55-61`); the core list's `robot.py` (`:118`); the formatter's functions (`:262-265`), `format_scene_dump()` as `get_scene_tree`'s dump; Robot System (`:405-410`): `get_robot_info` reads `/robot/info`, then `/robot/joint_states`; `:474`: `set_camera` and `viewport_light` |
| `docs/SETUP.md` | `:136`: "`get_scene_tree`'s dump and recordings are written by Kit itself" |
| `docs/images/README.md` | None: its `set_camera(position, target)` call stands |
| `plugin/skills/` | Through `write-skill`. `scene`: `allowed-tools` loses `dump_scene`; step 2, `get_scene_tree`, with `include_properties` or a filter for a file to grep; step 3, `set_camera` with a point or `prim_path`. `simulate`: `allowed-tools` loses `get_joint_states`; steps 3 and 6 and the trap row say `get_robot_info`'s joint states. `geometry`: `allowed-tools` loses `get_prim_face_count_tree`; step 1, `get_mesh_stats` with `max_depth`. `script`: none, its `mcp.set_camera` and `mcp.look_at` are the helper's |
| `test_project/scenarios.md` | 3.3, 3.4, 12.8, 17.6, 26.2: `set_camera(prim_path=...)`; 3.2: a call without a target, whose answer names the origin; 8.1 to 8.4: `get_scene_tree` with properties or filters; 14.4: `get_robot_info`, paused then stopped; 18.4, 18.5: `get_mesh_stats` with `max_depth` |
| The extension | `core/formatter.py:14`, `core/robot.py:1`, `core/xform.py:451`, `handlers/camera.py:572`, `handlers/robot.py:241` (Q11) |
| Test docstrings and comments | `tests/test_camera_handler.py:5`, `tests/test_integration.py:708`, `tests/test_formatter.py:1`, `tests/test_robot.py:1`, `tests/test_scene_handler.py:364`, `tests/test_server.py:213`: the merged tool, or the route, where they name a removed tool; each in the step of its pair |
| `AGENTS.md` | None: it names no tool |
| `CHANGELOG.md` | Under Unreleased, below; #82's lines stay as written (Q13) |

```markdown
### Breaking changes

- **Four pairs of tools that did one job are one tool each, 42 tools to 38,** so an agent no longer chooses between
  two tools for one question. A call to a removed tool's name is an error, `Unknown tool`. The merged tools send the
  Kit extension the requests the old ones sent, so they work with any 0.2.x extension (#77).
  - **`look_at_prim` is `set_camera` with `prim_path`,** with the same `distance`, `azimuth` and `elevation`.
    `set_camera`'s `position` is needed only without `prim_path`. A `prim_path` with a `position` or `target`, or
    `distance`, `azimuth` or `elevation` without one, is an error that says which to drop. Without a `target`,
    `set_camera` still looks at the world origin, and its answer now says so.
  - **`get_joint_states` is `get_robot_info`,** which reads each joint's position and velocity from physics with the
    robot's structure. Stopped, or in a Kit app without Isaac Sim, the answer gives the structure and says why there
    are no positions, where `get_joint_states` failed.
  - **`get_prim_face_count_tree(root, max_depth)` is `get_mesh_stats(prim_path, max_depth)`:** the totals of every
    mesh under the prim, then the prims to `max_depth`, 2 when left out where the tree took 10, each mesh with its
    counts and each prim above meshes with `subtree_faces`. `get_mesh_stats`' list of each mesh, for 20 or fewer, is
    now that tree.
  - **`dump_scene` is `get_scene_tree` with `include_properties`, `filter_types` or `property_filter`:** Kit writes
    `mcp_output/scene_dump.txt` as before. `include_properties` is false when left out, where `dump_scene` took true,
    so `dump_scene(root)` is `get_scene_tree(root, include_properties=True)`. `max_depth` left out is 5 for the list
    and 15 for the file, as before, and has no upper bound, where `get_scene_tree` refused more than 15.
```

Under Fixed:

```markdown
- **`get_mesh_stats` on `/` lists the levels asked for,** where the tree of a root of `/` listed one level fewer, and
  nothing at `max_depth` 0. The fix is in the Kit extension: run `uvx omniverse-mcp extension install`, then restart
  Kit (#77).
```

## Risks

| Risk | Status |
|---|---|
| An agent mixes the camera's forms, `prim_path` with `position`, or orbit angles with a point | Resolved: each mix is an error before any request, naming what to drop; unit tests for each |
| An old call's argument is dropped without a word (S2) and the call runs on the wrong thing | Resolved: every removed tool's arguments are its merged tool's parameters by the same names, but `root`, whose absence fails on the required `prim_path` |
| Two requests per call: another tool's edit lands between `get_robot_info`'s or `get_mesh_stats`' two reads | Accepted: both are reads of a stage that can change between any two calls; the client holds one request at a time |
| The joint states read a robot's first articulation while the Joints list is the whole subtree, so a `prim_path` above two robots gives one robot's states | Accepted, as today's two tools did; the description asks for the robot's root, as both did |
| `get_robot_info` makes an Isaac Sim `Articulation` on every call, stopped too | Resolved by C6: today's `get_joint_states` does so when called stopped; its callbacks go with it, and it loads no physics then |
| The server drops the tree's `# total:` line by its text; a later extension writes another | Accepted: only a last line starting `# total:` goes; anything else stays, and a unit test pins it |
| Degrees for limits beside radians for positions in one answer | Accepted (Q5): the block's header names the units and that `set_joint_targets` takes degrees |
| Plugin users get the new skills before the 0.3.0 server (Q14) | Accepted, short: the release PR follows this one |
| Users' own prompts and scripts name a removed tool | Accepted: `Unknown tool`, and Breaking changes maps each to its merged tool |

## Plan review

