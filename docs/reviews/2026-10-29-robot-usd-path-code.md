---
subject: "Load create_robot's USD file as given, and name its prim after it (#40)"
base: main (b26dd58)
head: 4a49c25
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer)
verdict: clean
---

# Review: create_robot with a USD file

Read from the diff and each touched file, the handler against `main`'s, and `tools/golden.py` for what the contract
keeps. Six minors, fixed in the round's commit; one improvement taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `CHANGELOG.md` | Unreleased's Changed still said `create_robot` "doesn't load a USD file path yet", against its own Fixed | fixed |
| F2 | minor | the handler; TOOLS.md, CHANGELOG | "A path found nowhere is an error" held only for paths the handler can stat: an `omniverse://` URL or a library path that doesn't answer left an empty prim, reported as created | fixed: the layer is opened (`Sdf.Layer.FindOrOpen`) before the reference, and a file that won't open is an error; live `test_29` |
| F3 | minor | `core/robot.py` | A relative path was checked against Kit's working folder, while a reference reads it against the stage's own folder: a found file could load from elsewhere, or not at all | fixed: a file found here is made whole; the unit tests check it |
| F4 | minor | the handler | Two files with one stem, or a stem like a prim of the scene, composed into one prim, both reported as created; on `main` too for a named robot twice | fixed: a taken `prim_path` is refused, as `create_prim` does; live `test_30` |
| F5 | minor | `tests/test_integration.py` | `test_27`'s temp folder stayed behind | fixed: `addCleanup(shutil.rmtree, ...)` |
| F6 | minor | `CONTRIBUTING.md` | `test_27` needs Kit on this machine, which only its comment said; `test_scenarios` reads a file Kit writes too | fixed: CONTRIBUTING says the live suites expect Kit on this machine |

Refuted, each from the code:

- **Named robots changed:** the same URL (the root joined as before), the same `/World/Franka`, the same lowercase
  `robot_type`; the asset root is looked up only for a library path.
- **`C:/x.usd` read as a URL:** the pattern needs `://`.
- **`os.path.isfile` holds Kit's main thread:** a local stat, no longer than the open `AddReference` does next.
- **An invalid prim from an odd stem:** `Tf.MakeValidIdentifier` never gives an empty name.
- **The golden file is stale:** `tools/golden.py` strips descriptions.

Improvement taken: a USD file loads in any Kit app, not only Isaac Sim; TOOLS.md, ARCHITECTURE.md, the tool's
description and the `simulate` skill say so.

Not covered: bridge security, with no route, token or setting touched.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, started for these runs; the maintainer's Isaac Sim on 8211 was not
touched.

- **On `4a49c25`,** the live suites (`-k "not test_10_ and not test_14_"`, #5) from a cold start: 112 passed, with
  #6's two (first run) and #7's three failing, as on `main`. `test_27` loaded a file it wrote into
  `/World/IntTestRobot`, its child read back; `test_28` refused a missing file. `create_robot("Franka")` still loads
  from the library root at `/World/Franka`, with 11 joints.
- **On the fixes,** with Kit restarted on them: see the PR.

## Checks

`uv run tools/gate.py full` passed on `4a49c25`.
