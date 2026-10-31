# Changelog

What changed for people who use omniverse-mcp, newest first. A change users notice adds its line under Unreleased in
the same PR. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Breaking changes

- **Four pairs of tools that did one job are one tool each, 42 tools to 38,** so an agent no longer chooses between
  two tools for one question. A call to a removed tool's name is an error, `Unknown tool`. The merged tools send the
  Kit extension the requests the old ones sent, so they work with any 0.2.x extension, joint states with 0.2.1's or
  later (#77).
  - **`look_at_prim` is `set_camera` with `prim_path`,** with the same `distance`, `azimuth` and `elevation`.
    `set_camera`'s `position` is needed only without `prim_path`. A `prim_path` with a `position` or `target`, or
    `distance`, `azimuth` or `elevation` without one, is an error that says which to drop. Without a `target`,
    `set_camera` still looks at the world origin, and its answer now says so.

### Fixed

- **`delete_prim` refuses a prim it can't remove, where it answered "Deleted" and the prim stayed:** one another layer
  defines too, or one a reference or payload on a prim above brings, such as a part of a referenced robot. The error
  says which, nothing changes, and `set_visibility` hides such a prim. The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit. Until then, `delete_prim`'s answer says to check with
  `get_scene_tree` (#82).
- **`set_camera`, `look_at_prim` and `inspect_prim` aim the camera in every Kit app.** Without Isaac Sim's
  `isaacsim.core.utils.viewports` they wrote the camera's transform into the stage's root layer, which Kit's own
  viewport camera, held in the session layer, ignores: `set_camera` and `look_at_prim` failed with a USD error,
  `inspect_prim` took every angle from where the camera stood, and each left an override of the camera in the root
  layer. A scene camera moved without turning, and `look_at_prim` reset its rotation. They now aim the camera in the
  layer that holds it, as Kit does. In Isaac Sim, a camera looking straight down a Y-up stage's up axis, which Isaac's
  call left at the origin, is aimed too. The fix is in the Kit extension (#82).
- **`set_camera` refuses a `position` equal to the point it looks at,** its `target` or the world origin when none
  is given, where it answered success with nothing to look at (#82).
- **`set_material` makes a material opaque again with `opacity=1`:** it wrote the opacity only below 1, so a material
  made see-through stayed so. A call that leaves `opacity` out now makes the material opaque, as one that leaves out
  `roughness` or `metallic` sets theirs, and the answer gives the opacity every time. The fix is in the Kit extension
  (#82).
- **`dump_scene` counts the prims it wrote,** where "Dumped N prims" counted the whole stage and the file's
  `prim_count` the whole subtree, past `max_depth` and `filter_types`. The fix is in the Kit extension (#82).
- **A second `start_recording` says to call `stop_recording`,** where it said to pass `force=True`, which the tool
  doesn't take. The fix is in the Kit extension (#82).
- **`set_prim_transform` keeps a prim's other xform ops:** it rewrote them as translate, rotate and scale and dropped
  the rest, so a pivot went, a pivot could be read as the position, and a prim placed by a matrix (`xformOp:transform`),
  as imported assets often are, lost that placement. The position, rotation and scale now go into the prim's own ops,
  the rotation in its op's kind, and a matrix is changed in place; `create_prim` and `create_robot` place a prim the
  same way. The fix is in the Kit extension (#82).
- **`clone_prim` with `offset` keeps each copy's placement,** moving copy n by n times the offset from the source:
  copies of a source placed by a matrix or about a pivot lost that placement, and a single copy had its ops rewritten.
  The fix is in the Kit extension (#82).
- **`get_recording_frame` reads the folder `start_recording` and `stop_recording` print,** relative to the server's
  working folder, where Kit read a relative `session_dir` from its own folder and answered "Frame not found" (#82).
- **`raycast` takes a `direction` of any length but zero,** where its description asked for a unit vector and said
  PhysX takes it as given: Isaac Sim 6.2's PhysX scales it itself, and the server now does so before sending it, for
  any other. A zero direction is an error (#82).
- **`get_scene_tree` stops at `max_depth`, and a prim there says how many children it has,** where the text listed the
  next level's prims that had children and left out the rest, so a childless prim there looked absent. The fix is in
  the Kit extension (#82).
- **`look_at_prim`, `inspect_prim` and `raycast` give distances in stage units,** where they printed `m`: on a stage in
  centimetres, centimetres labelled metres (#82).
- **`save_scene` with a `file_path` no longer writes over another file the open stage has loaded:** it wrote the root
  layer over any file, so a `file_path` naming a sublayer, a referenced or a payload file replaced that file on disk
  while Kit kept the layer as it was, and the scene and its files no longer agreed. Such a path is now refused before
  anything is written, as `flatten_usd` and `export_prim_as_file` refuse it, with an error that says to name another
  path, or to call `save_scene` without one when the stage has a file of its own; the stage's own file, by any name,
  is still saved. A file Kit holds outside the open stage with unsaved edits is refused too; one without is read again
  after the write, so the next open gets the new file. The refusals of `flatten_usd` and `export_prim_as_file` no
  longer tell a stage never saved, such as `new_scene`'s, to use `save_scene` to save to its own file, which it hasn't
  got. The fix is in the Kit extension: run `uvx omniverse-mcp extension install`, then restart Kit (#85).
- **`capture_viewport`'s boxes leave out a prim behind the camera,** where it got a box mirrored onto the image, near
  its middle, though the image couldn't show it. A prim across the camera's plane is boxed by its part in front. The
  fix is in the Kit extension (#90).
- **`apply_force` pushes under PhysX's Direct GPU API,** which Isaac Sim turns on for a GPU device
  (`SimulationManager.set_device("cuda:0")`), where it was refused: PhysX's own push moves nothing there, so whenever
  `/physics/suppressReadback` is on the call goes through PhysX's tensor API, with the same refusals, and its answer
  says `method: tensor`. That takes in a scene on the CPU with the setting on, which was refused too. Under the Direct
  GPU API a second push on a body before the next physics step replaces the first, so push once per body per step,
  combining pushes into one; pushes on different bodies each land. The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install`, then restart Kit (#68).

### Changed

- **The Kit extension no longer turns on the viewport's instance segmentation at startup,** which copied the
  viewport's instance ids to the host every frame for nothing: since 0.2.3 each capture segments through a camera
  feed of its own (#76).
- **`set_prim_transform`, `create_prim` and `create_robot` refuse what they can't show:** a rotation that isn't 3 or 4
  numbers, which they ignored; a zero quaternion; an xform op with animation, whose value they set where the animation
  hid it or froze it; ops a stronger layer holds, such as Kit's viewport camera's, where they failed with a USD error;
  and a rotation or scale on a matrix that can't be factored, which lost the rotation. `create_prim` and
  `create_robot` refuse before making the prim. The fix is in the Kit extension (#82).

## 0.2.3 (2026-10-30)

A new tool, `open_scene`. Captures, recording, `apply_force`, `flatten_usd` and `export_prim_as_file` are fixed, and
every tool's description is rewritten. Most of it is in the Kit extension: run
`uvx omniverse-mcp==0.2.3 extension install` (the plugin's `/omniverse-mcp:setup` does it) and restart Kit.

### Added

- **`open_scene` opens a USD file as the stage,** the counterpart of `save_scene`: a path on Kit's machine (a
  relative one read from the folder Kit was started in), an `omniverse://`, `https://` or `file:///` URL, or a path
  in Isaac Sim's asset library such as `/Isaac/Environments/Simple_Room/simple_room.usd`. The open stage goes without
  a prompt, unsaved changes included, as with `new_scene`; the simulation is stopped first. A file that isn't there,
  can't be reached, isn't USD, or a call while Kit opens another stage, is refused with the open stage kept. The
  answer gives the stage's up axis, metres per unit, default prim and prim count, with a note when the file leaves
  the axis or units to USD's fallbacks, Y and centimetres. It needs this release's Kit extension:
  `uvx omniverse-mcp extension install`, then restart Kit; an older extension's error says so (#79).

### Fixed

- **`capture_viewport` and `inspect_prim` show what was done just before the call:** Kit captured a frame its
  renderer had made about 3 updates earlier, so a drawing or another change made just before could be missing from
  the image, `draw_debug`'s lines in Kit apps without `isaacsim.util.debug_draw` most often. A capture now renders
  its camera in a render of its own, made for the call, whose first frame holds what was done before it (#51), as
  recording's frames come from a render of their own (#25). The fix is in the Kit extension: run
  `uvx omniverse-mcp extension install` and restart Kit (#57).
- **`capture_viewport` and `inspect_prim` render at the `width` and `height` asked for,** 640x480 by default, where the
  image came at the viewport's size (1280x720 headless, or the window's) and the boxes were scaled to the size asked
  for, so the two disagreed. The image, its segmentation and its boxes now come from one frame of the camera at that
  size, in a render of its own; the viewport the user sees keeps its camera and size. With a `camera_path`, the boxes
  are that camera's, and the viewport no longer switches to it (#70). `inspect_prim` frames each angle for the size
  asked for. A side over 4096 is refused. While a capture runs, the extra render takes some of the app's updates,
  and its render product in the stage leaves Kit's unsaved-edits flag set, where only a capture with a `camera_path`
  did before. With an older extension, `capture_viewport` warns that its boxes don't match the image and names
  `uvx omniverse-mcp extension install`: run it, then restart Kit (#51).
- **`start_recording` records from `camera_path` at `width` x `height`,** where it recorded the active viewport at its
  own size and warned that it ignored them. It renders the camera in a texture of its own, so the viewport, its
  camera and its size stay as they are; a side over 4096 is refused. While a recording runs, the extra render takes
  some of the app's updates: a third at 640x480, headless. Frames stop, and `stop_recording` and `get_sim_state` say
  why, if the stage changes or the camera is deleted. The fix is in the Kit extension: `uvx omniverse-mcp extension
  install`, then restart Kit; with an older extension the warning stays, now naming that command (#25).
- **A call with no size now records 640x480 from the active camera,** the defaults the tool has always listed, where
  it recorded the viewport's own size (1280x720 headless): pass the size you want (#25).
- **Recording frames no longer overwrite each other** when they come faster than a frame is written, as at `fps=30`:
  each frame gets its own number when it is taken, and its tracked state is read then too. The fix is in the Kit
  extension (#69).
- **`apply_force` pushes an articulation's links again,** such as a robot's: 0.2.1 refused them on a misread
  measurement, and PhysX's push reaches them. A push on a link moves the robot through its joints: a floating robot
  touching nothing changes speed by the impulse over its whole mass. A body a fixed joint holds to the world is now
  refused, since no force moves it: a robot's fixed base, a link welded to one, or a lone body, which answered
  success and moved nothing. So is every push under PhysX's Direct GPU API, where none moves anything (#68). The fix
  is in the Kit extension: run `uvx omniverse-mcp extension install`, then restart Kit (#58).
- **`flatten_usd` no longer empties the open scene, and neither it nor `export_prim_as_file` writes over a file the
  open stage has loaded:** both cleared the layer Kit held for their paths, so flattening the open stage's own file,
  or writing to it, a sublayer or a referenced file, emptied that layer in the open scene. A file the open stage has
  loaded is now flattened as Kit holds it, unsaved edits too, and the open stage is left as it is; as an output, it is
  refused before anything is written, with an error that says to name another path or use `save_scene`. So is a file
  Kit holds outside the open stage with unsaved edits; one without is read again after the write, so the next open
  gets the new file. `export_prim_as_file` no longer fails with "A layer already exists" on a file Kit holds. The fix
  is in the Kit extension: run `uvx omniverse-mcp extension install`, then restart Kit (#81).

### Changed

- **`capture_viewport` refuses a `camera_path` that isn't a camera,** or names no prim, where it captured the viewport
  anyway: name a `Camera` prim, or leave it empty for the viewport's camera (#51).
- **A capture's size is checked as a recording's is:** through `execute_script`'s `mcp.capture_viewport` and
  `mcp.inspect`, or the extension's HTTP routes, a `width` or `height` that isn't a whole number from 1 to 4096, such
  as `"1280"` or `720.0`, or a request with one of the two alone, is refused, where it was converted or defaulted. The
  tools always send both as whole numbers (#51).
- **Every tool's description says when to use it rather than its neighbours,** what a parameter left out does, and how
  it fails, so a client picks and calls the right one; `docs/TOOLS.md` says the same. Some said less than the tools do:
  `update_material_paths` rewrites any relationship or asset path that starts with the prefix, not only materials',
  `sim_control("step")` plays two app updates, and `set_camera` and `look_at_prim` aim the camera only in Isaac Sim.
  On Python 3.11 and 3.12 a description no longer reaches the client with its source's indentation (#78).

## 0.2.2 (2026-10-29)

The server joins the official MCP registry, and PyPI's page gets working in-page links. The tools and the Kit
extension work as in 0.2.1, but the extension's version moves with the server's: run
`uvx omniverse-mcp==0.2.2 extension install` (the plugin's `/omniverse-mcp:setup` does it) and restart Kit, so
`get_sim_state` reports the two in step.

### Added

- **The official MCP registry lists the server,** as `io.github.serionist/omniverse-mcp`, from this release on, for
  clients and directories that look servers up there. Each GitHub release's notes end with the install lines (#64).

### Fixed

- **The README's in-page links work on PyPI's page,** where 0.2.1's pointed nowhere: the build gave them the
  `user-content-` prefix that PyPI adds itself (#62).

## 0.2.1 (2026-10-29)

Fixes from the first week on PyPI. A robot's first play no longer hangs Kit, captures can't wait past the
client's timeout, and `draw_debug`, `apply_force`, `get_joint_states` and `create_robot` do what they say. The
fixes are in the Kit extension too: after updating, run `uvx omniverse-mcp==0.2.1 extension install` (the plugin's
`/omniverse-mcp:setup` does it) and restart Kit.

### Fixed

- **`start_recording` warns when it is given a `camera_path`, or a size other than 640x480,** which it ignores: it
  records the active viewport, from its camera at its own size, and used to report the values back as if it had
  used them. Its description says so too (#25).
- **`draw_debug` works headless, on every Isaac Sim, and a drawing stays `duration` seconds,** where it lasted a
  frame. It used `omni.debugdraw`, which only the GUI app turns on; it now draws with `isaacsim.util.debug_draw`,
  turned on at the first call, and other Kit apps with `omni.debugdraw`. When a drawing expires, other lines drawn
  with `isaacsim.util.debug_draw` go too, since its clear takes every line. An unknown shape or a vector that isn't
  three numbers is an error, where it drew nothing and reported success. The fix is in the Kit extension:
  `uvx omniverse-mcp extension install`, then restart Kit (#7, #25).
- **Kit no longer stops answering when physics first plays with a robot on the stage** (#5). The bridge listened
  to Kit's log through a Python callback, which Kit runs on whichever thread logs. While Isaac Sim cooked the
  robot's collision meshes, a worker that logged waited for Python's lock, held by Kit's main thread, which waited
  for the worker. Seen on Isaac Sim 6.2 with the G1. The bridge now hands Kit's logging no callback at all, and
  `get_logs` reads Kit's log file.
- **`get_joint_states` reads joint states** (#50), where it always failed on Isaac Sim 5.1 and 6.x: it used an
  articulation class neither has. It reads through `isaacsim.core.experimental.prims.Articulation` while physics
  plays or is paused, in radians and metres, and says to play first while the simulation is stopped. Tested
  live on Isaac Sim 6.2; 5.1 ships the same class, untested live.
- **The server makes `mcp_output/` with the first file written there,** not when it starts, so a client that only
  starts it, such as a health check, leaves no empty folder behind (#43).
- **A file outside the server's working folder is given by its absolute path,** not by a `../` path that only a
  reader in that folder could open, as with an `--output-dir` elsewhere (#41). A relative `--output-dir` is now read
  against the server's working folder for Kit's files too: `dump_scene` and recordings went to Kit's.
- **`create_robot` loads a robot from its USD file,** given as `robot_type`: a path on the Kit app's machine or a
  URL as given, with its case, and a path in Isaac Sim's asset library under the library's root. Without
  `prim_path`, the prim is named after the file. A file that can't be opened is an error, where it used to leave an
  empty prim reported as created, and so is a prim already at `prim_path`, where a second robot used to compose
  into it. Before, the path was lowercased and put under the asset root, so it never loaded (#40).
- **Captures fail in time, and say why.** A capture whose frame named nothing captured fails at once, where it
  waited ten seconds for a file that could not come; a viewport that renders nothing fails after 30 s, where
  `inspect_prim`, `capture_viewport`, `set_camera`, `look_at_prim` and `viewport_light` hung. `inspect_prim` and
  `capture_viewport` answer within about 90 s, under the server's 120 s: `inspect_prim` returns the angles it
  captured, and `Not captured` for the rest once the viewport gave no frame or the time ran out (#35).
- **Instance segmentation that comes late is waited for,** up to 5 s after the bridge enables its sensor, which Kit
  drops on every stage open; it was dropped without a word after 10 app updates. A capture without segmentation now
  says why: `inspect_prim` on the angle's line (`seg: ERROR`), `capture_viewport` as `Segmentation: ERROR` (#27).
- **`apply_force` pushes through PhysX,** so mass counts, at `position` or, when it is left out, at the body's centre
  of mass. Before, the PhysX call it made didn't exist, so every call added `force / 100` (all of it for an
  impulse) to `physics:velocity`, ignoring mass and point. It is now refused while the simulation is stopped, for a
  disabled or kinematic body and for a prim PhysX holds no body for, where it reported success; a PhysX failure is
  an error. An articulation's link, such as a robot's, is refused too, since PhysX's push doesn't reach it yet
  (#58).
  `impulse` says what PhysX does: a force lasts one physics step, so a sustained push is an impulse of force times
  seconds (#25). The fix is in the Kit extension: run `uvx omniverse-mcp extension install`, then restart Kit.

### Changed

- **`get_logs` reads Kit's log file,** from where it ended when the extension started, so it holds what the
  file holds: Info and above by default, and verbose lines only with both `--/log/level=verbose` and
  `--/log/fileLogLevel=verbose`. In an entry, `timestamp` is the line's text, such as
  `2026-01-01T00:00:00Z [1,234ms]`; `module`, `source` and `func` are empty; a message's further lines, such as a
  traceback, are part of `msg`; and the bridge token is `<redacted>`. `total_captured` counts the entries read,
  at most the newest 1 MB of the file per call. When Kit has written lines in a format other than its default
  and none reads as an entry, the answer says so. The same goes for `mcp.get_logs` in `execute_script`.
- **The README is reworked for a first setup:** requirements, then install by client, a check that it works,
  examples that work today, configuration, troubleshooting and the known issues, with PyPI's and uv's badges. Client
  configs keep `PYTHONPATH` empty, as the plugin does, so Isaac Sim's environment stays out of the server's Python.
- **`docs/SETUP.md`** is new: each MCP client's config, headless Kit, ports, Kit on another machine, and
  uninstalling. Working on a clone moved to `CONTRIBUTING.md`.
- **Corrected in the docs:** the bridge's settings go on Kit's command line, since `extension install` replaces an
  edited `extension.toml`; the MCP resources are read on demand; an inline capture costs about as much context as opening its file.

## 0.2.0 (2026-10-29)

The first release on PyPI: `uvx omniverse-mcp`, or the Claude Code plugin. The breaking changes below concern a clone
of this repo from before it.

### Security

- **The bridge answers only the MCP server that holds its token.** Before this, any program on the machine, and any
  web page open in a browser, could send `/execute` to the extension and run Python inside the Kit app. The extension
  now writes a new random token to a file only your user can read, every request must carry it, and requests from web
  pages are refused.

### Breaking changes

- **Update the MCP server and the Kit extension together.** A new server refuses an old extension, and an old server
  gets 401 from a new one. `git pull` in your checkout updates both; then restart Kit and your MCP client.
- **A remote Kit app needs the token by hand:** set the extension's `token` setting and the server's
  `OMNIVERSE_MCP_TOKEN` to the same value.
- **`inspect_prim` no longer takes `distance`.** It fits the distance itself; use `zoom_offset` to move closer or
  further.
- **`viewport_light("get")` reports `lighting_mode`** and the available modes, in place of `camera_light_on`.
- **The Python package is `omniverse_mcp`.** In `.mcp.json`, `python -m isaac_sim_mcp` becomes the `omniverse-mcp`
  command (or `uv run --no-sync --project <clone> omniverse-mcp`; the README shows both). An install from before
  the rename still points `omniverse-mcp` at the deleted `isaac_sim_mcp`: reinstall it with
  `pip uninstall omniverse-mcp` then `pip install .` (or `pip install -e .`), or switch to `uv sync`.
- **The Kit extension is `ovmcp.bridge`, in `extension/ovmcp.bridge/`.** It was `isaacsim.mcp.bridge`, in a folder
  named with its version. To move over:
  1. In Kit's Extension Manager, turn `isaacsim.mcp.bridge` off and its autoload off.
  2. Remove its search path if it pointed inside `extension/isaacsim.mcp.bridge-1.0.0`; the repo's `extension/` folder
     stays the search path.
  3. Turn on `ovmcp.bridge` with autoload.
  4. Move a custom port or token from `exts."isaacsim.mcp.bridge"` to `exts."ovmcp.bridge"`. The
     `scene_tree_max_depth` setting is gone; nothing read it.
- **The server's flags are `--host` and `--port`,** in place of `--isaac-host` and `--isaac-port`, which now stop
  the server with a message naming the new flag; any other unknown flag is an error too. `--host`, `--port` and
  `--output-dir` default to `OMNIVERSE_MCP_HOST`, `OMNIVERSE_MCP_PORT` and `OMNIVERSE_MCP_OUTPUT_DIR`; an empty
  variable counts as unset.
- **The MCP resources are `omniverse://scene/tree` and `omniverse://sim/state`,** and the server calls itself
  `omniverse`. Scene dumps and recording state files start with `# Omniverse MCP`, and their `# format` line
  reads `omniverse-mcp-v1`.
- **Python 3.11 or newer** for the server.
- **A tool that fails returns an error result, not `ERROR:` text.** The MCP result has `isError` set, with the
  bridge's message and the last lines of its traceback, or why the Kit app couldn't be reached; its text no
  longer starts `ERROR:`. A script that looked for `ERROR:` in a tool's text reads `isError` instead, or it
  takes every failure for a success. A failed resource read is a resource error.
- **A tool refuses a value out of its range, or not one of its choices,** before it reaches Kit: a width, height,
  count or `fps` below 1; a negative `max_depth`, `frame_index`, mass, density or friction; a distance, duration,
  radius or point size not above 0; a `zoom_offset` of -1 or less; an opacity, roughness, metallic or restitution
  outside 0 to 1; a `max_depth` above 15 in `get_scene_tree`, which used to cut it to 15 quietly. `sim_control`,
  `viewport_light`, `manage_extensions` and `draw_debug` take only their listed actions and shapes, in lower case
  (`"Play"` used to work), and `get_logs` only `verbose`, `info`, `warn`, `error`, `fatal` or `""` as `min_level`,
  where an unknown level used to filter nothing.
- **`clone_prim` refuses a target path that already holds a prim,** and `create_prim` one that holds a prim of
  another type. Both used to overwrite it: a clone replaced the prim there and its children, and a create turned a
  Cube into an Xform.

### Fixed

- **A capture shows the view it was asked for.** Every capture went through one temporary file, which Kit 110
  writes after it reports the capture done, so a capture could return the previous one's image: each of
  `inspect_prim`'s angles showed the angle before it, its first the view from before the call, and `capture_viewport`
  and recording frames could be a step behind too. On Kit apps that wrote the file in time this didn't show.
- **`set_material`'s colours show.** Its OmniPBR shader named only an id, which some Kit apps don't resolve
  (Isaac Sim 6.2 headless among them): every material rendered as Kit's red error material, while the tool reported
  success. The shader now names its MDL source, `OmniPBR.mdl`, and a material made before this gets it the next time
  `set_material` uses it.
- **`draw_debug`'s `size` defaults to 0.05, what it draws,** where its schema said 5.0; asking for 5.0 drew 0.05.
- **`get_logs` names Kit's log levels right, and `min_level` keeps the right ones.** A warning was labelled
  `verbose` and an error `info`, and `min_level="warn"` kept only fatal messages.

### Changed

- **The server runs on MCP SDK v2** (`mcp` 2.3.0), and its tools reach Kit one request at a time.
- **A black capture is no longer relit behind your back.** The bridge used to turn the camera light on and capture
  again; now the capture comes back as it is, with a warning that says how to light the scene (`viewport_light`).
- **`inspect_prim` refuses what it cannot do instead of guessing:** an unknown angle name (it used to be skipped),
  a non-numeric `width`, `height` or `zoom_offset`, and an orthographic viewport camera, where distance frames
  nothing.

### Added

- **A Claude Code plugin,** with this repo as its marketplace: `/plugin marketplace add serionist/omniverse-mcp`,
  then `/plugin install omniverse-mcp@omniverse-mcp`. It starts the server of its release with `uvx`, and brings
  skills: `/omniverse-mcp:setup` installs the Kit extension and checks the connection; `scene`, `geometry`,
  `simulate` and `script` hold the workflows and traps `docs/AI_GUIDE.md` used to. A skill pre-approves read-only
  tools only.
- **`get_sim_state` reports the Kit extension's release beside the server's,** and when they differ, the command
  that installs the server's extension. A different release on the same bridge protocol works, so nothing else would
  show that Kit still runs the old extension after an update.
- **`docs/AI_GUIDE.md` is short:** the context every client needs, and links to the skills for the workflows.
- **`omniverse-mcp extension install`** copies the Kit extension of the server's own release to your user data
  folder, in place of an older one, and prints the folder Kit's extension search paths need; `omniverse-mcp extension
  path` prints it again. When the server and the extension speak different bridge protocols, the server's message
  names the command for its release, `uvx omniverse-mcp==X.Y.Z extension install` (from a checkout,
  `uv run --project <checkout> omniverse-mcp extension install`), and says which side is older.
- **Each tool says what it does to the Kit app,** as MCP annotations a client may use to ask before it runs one:
  read-only (queries and captures), not destructive (edits), destructive (deletes and overwrites, prims or files), or
  destructive and open world (`execute_script`, `manage_extensions`). `docs/TOOLS.md` lists them. They are hints,
  never security.
- **Every parameter is described in the tool's schema,** with its range or choices, so a client shows them without
  the docs.
- **`inspect_prim` frames the prim for you.** The camera stands where the prim's bounding sphere fills the captured
  frame with a small margin; `zoom_offset` moves it closer (`-0.3`) or further (`0.5`). `isolate=True` hides everything
  but the prim while it captures, keeps the scene's lights on, and puts every prim's visibility back exactly as it was;
  what it cannot hide (inside an instance, or with time-sampled visibility) it names in `isolate_warnings`.
- **`viewport_light(action="set", mode=...)` switches the lighting mode:** `"off"`, `"camera"`, `"stage"`, or a light
  rig such as `"Default"`, the quickest fix for black captures. It returns an error when the mode did not change, for
  example a light rig in a Kit app without the viewport's lighting menu.
