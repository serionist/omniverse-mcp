---
subject: "Keep flatten_usd and export_prim_as_file off the open stage's layers (#81)"
base: main (9d9ef2a)
head: 2250d27
date: 2026-10-30
round: 1
tier: standard (one fresh reviewer on Claude; findings checked against the code by the author)
verdict: needs-fixes
---

# Review: flatten_usd and export_prim_as_file keep off the open stage's layers

Read from the branch's diff, `ovmcp/core/layers.py` and its tests, the two handlers, the tool descriptions, TOOLS.md
and the geometry skill. No blocker or major; two minors, both fixed, so no second round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/layers.py`, `_same_file` | A link to the open stage's file under another name got past `write_refusal`: the file-name filter ran before any disk check. On Linux, with `/proj/shot/v003.usda` open and `/proj/shot/latest.usda` a symlink to it, `export_prim_as_file("/World/Robot", "/proj/shot/latest.usda")` wasn't refused: `Find` resolves the link's path without following it, the names differ, so `samefile` was never tried, and Export wrote through the link onto the scene's file. A Windows short name (`SCENE~1.USD`) and a `file:` URL, whose `samefile` raised and read as no match, the same. A hard link was safe (the writer renames a temp file over that entry) | fixed in `3f1af9f`: `write_refusal` compares every used layer's file with the output's, whatever its name, one stat each when the output exists, a `file:` URL taken as its path first (with `url2pathname`, then, after the merge with `main`, with `open_scene`'s `path_of` in `1563b1c`, which keeps a UNC host); the pass over held layers outside the stage keeps the name filter, where a miss only leaves one stale. `test_a_symlink_to_a_file_of_the_open_stage_is_refused_whatever_its_name` (skipped only where the account can't make a symlink; it ran on Windows here and runs on CI's Linux), `test_a_file_url_of_the_open_stages_file_is_refused`, `test_a_layer_whose_file_is_gone_doesnt_stop_the_check`. The docstring and TOOLS.md promise only what the check does |
| F2 | minor | `plugin/skills/geometry/SKILL.md`, its trap | The trap taught `Reload()` where the code needs `Reload(force=True)`: without force, USD compares the file's time with the load's, to the second on Windows, so an Export and a Reload in the same second leave the layer as it was | fixed in `10e4bdd`: `Reload(force=True)`, and why |

Refuted, each from the code:

- **The input's reload drops unsaved edits:** `refresh` skips a layer with unsaved edits (`has_unsaved_edits`).
- **A referenced or payload layer of the open stage is read again:** `refresh` skips any layer the open stage uses.
- **An anonymous layer is read again, which empties it:** skipped by `IsAnonymousLayerIdentifier`, and the file check
  needs a `realPath`.
- **The reload after writing:** it runs only after Export returned true, with the same exclusions.
- **An unloaded payload goes stale:** its layer, which Kit may still hold, isn't one the open stage uses, so it is
  read again after a write like any other held layer outside the stage.
- **Refusing a held layer with unsaved edits outside the stage:** correct; writing it and reading it again would drop
  them, and not reading it again would leave it stale.
- **USD off the main thread:** none; the handlers call the core module where they ran before.
- **Spellings by case, slash, relative path or `..`:** `Find`, the case-folded name and the file system's identity
  cover them, unit-tested.
- **The tool contract:** `tests/fixtures/mcp-tools.json` is unchanged; only prose moved.
- **The live tests would pass on `main`:** all three fail there.
- **The live tests could flake:** the reload is forced, and nothing waits on time.
- **The stage left open in a deleted folder:** no later test saves without a path.
- **Usd's stage cache handing back Kit's own stage:** only inside a bound `StageCacheContext`, which nothing here
  makes.
- **The export's output differs from CreateNew's:** the format comes from the extension, and the root's metadata is
  kept.
- **`_same_file` raising:** `OSError` and `ValueError` are caught.

Improvements:

| Improvement | Answer |
|---|---|
| `refresh` looks the used layers up in a list, O(n²) on Kit's main thread: a set | taken in `3f1af9f` |
| TOOLS.md: name muted sublayers beside the unloaded payload, as `layers.py`'s docstring does | taken in `3f1af9f`. Refusing them with `GetMutedLayers()`: left; a muted layer, like an unloaded payload, is a file the caller asked to overwrite, and the stage reads it from disk when it is unmuted |
| A live `.usdc` case in the held-layer test: `export_prim_as_file`'s default, and on Windows a held crate layer keeps its file mapped, which the old `Clear()` let go of before the write | taken in `3f1af9f`; on usd-core 26.11 on Windows, an Export over a held, mapped `.usdc` and a forced reload worked |
| A live case with another spelling of the open stage's file, since Kit resolves through its own resolver | taken in `3f1af9f`: forward slashes, and the name in capitals where the file system ignores case |
| The handler's `if not src_stage` never ran: `Usd.Stage.Open` raises `Tf.ErrorException`, so a missing input reached the agent as a 500 with a traceback | taken in `3f1af9f`: `open_to_flatten` gives no stage, and the handler answers "Could not open <path>: no file there, or none USD reads"; `test_an_input_usd_cant_open_gives_no_stage`, and live `test_an_input_usd_cant_open_is_an_error` |
| `save_scene(file_path=...)` exports the root layer with no guard, so it can overwrite a sublayer's or a referenced file of the open stage | later: #85 |

Not covered, unverified on Kit: how Kit's resolver takes `Find` for a `file:` URL or a relative path, a write through a
symlink, and replacing a held `.usdc` on Windows. The live cases added in `3f1af9f` cover the last.

## Live run

Isaac Sim 6.2.0 headless, a fresh Kit at 8212 with the bridge at `2250d27`, through `build-81-live.sh`:

- **Both live suites,** `tests/test_integration.py` and `tests/test_scenarios.py`: 166 passed and 5 subtests passed
  in 140.20 s.
- **`TestFlattenAndExportKeepTheOpenStage` again,** on the stage the suites left: 3 passed and 5 subtests passed.
- Each run printed:
  - "A file Kit held was written twice and read again each time; with unsaved edits, it was refused";
  - "Flattened IntTestScene.usda: the open stage kept /World/IntTestFlatCube and its unsaved /World/IntTestUnsaved";
  - "export_prim_as_file and flatten_usd refused the open stage's own file; the stage is intact".

The fixes' live run, of `TestFlattenAndExportKeepTheOpenStage` after the merge with `main` (`dfda34a`), at `1563b1c`: pending.

Not shown: other Kit apps, such as USD Composer, the Isaac Sim GUI, and output paths on Nucleus (`omniverse://`).

## Checks

- **The gate:** `uv run tools/gate.py full` passed on `10e4bdd`: 15 checks, 1196 passed and 169 skipped, coverage
  95.93%; `ovmcp/core/layers.py` at 100%. After the merge with `main`, on `1563b1c`: 15 checks, 1268 passed and 176 skipped, coverage 96.18%.
- **Each guard has a test that fails without it:** run by hand on `ac71c67` and again on the fixes, removing one
  guard at a time (the reload of held inputs, the used and unsaved-edits exclusions, the anonymous one, `Find`, the
  file system's identity, the any-name pass, the `file:` URL).
