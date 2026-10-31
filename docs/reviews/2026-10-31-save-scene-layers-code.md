---
subject: "Refuse a save_scene file_path that names another layer of the open stage (#85)"
base: main (f26642c)
head: 1aa5052
date: 2026-10-31
round: 1
tier: standard (one fresh reviewer on Claude; findings checked against the code by the author)
verdict: clean
---

# Review: save_scene keeps off the open stage's other layers

Read from the branch's diff: `ovmcp/core/layers.py` and its tests, the `save_scene` handler and its new handler test,
the live class, the tool description, TOOLS.md, the scene skill and the changelog. No blocker or major; one minor,
fixed, so no second round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/layers.py`, `write_refusal`, the `saving` branch | The refusal told a stage never saved to save to its own file, which it hasn't got. After `new_scene()` (an anonymous root), `create_prim(..., usd_path="C:/assets/table.usda")` or `create_robot` with a file makes that file a used layer; `save_scene(file_path="C:/assets/table.usda")` is rightly refused, but the error offered "call save_scene without a file_path to save the open stage to its own file", and that call fails with "No file path set. Provide file_path for save-as." (`handle_save_scene`, `if not current_path`) | fixed in `58e569d`: the clause comes only when the root layer has a file (`Sdf.Layer.IsAnonymousLayerIdentifier`, as `refresh` reads it); otherwise the error ends "Save to another path.". A test with an in-memory root over a referenced file pins the wording and fails without the check; since `a47fe8e` it is `test_a_stage_never_saved_is_offered_no_save_to_its_own_file`, which covers `flatten_usd` and `export_prim_as_file` too (Improvements). CHANGELOG says the same |

Refuted, each from the code:

- **The `saving` keyword or the narrower unsaved-edits check changes `flatten_usd` or `export_prim_as_file`:** with
  `saving=False`, the earlier `if used: return` has already returned for every layer the new filter could drop.
- **The root allowed only by its exact spelling:** `_layers_at(..., any_name=True)` matches it by `find_layer` or by
  the file system's identity, then the root filter drops it.
- **A layer other than the root slips through:** only the root is filtered.
- **An anonymous root:** nothing matches it as the root, and the export goes ahead as it should.
- **A root opened from a `file:` URL:** excluded by identity, not by name.
- **The root's file being a sublayer elsewhere in the stage:** Sdf gives one layer per identifier, so it is the root
  itself.
- **A failed Export reported as success:** an exception becomes an error, and a `False` returns before
  `refresh_written`.
- **A gap between the check and the write:** there is no await between them.
- **An unloaded payload or a muted sublayer:** by design, the same scope as #81.
- **A hard link to the root under another name:** the file at `file_path` gets what was asked, and nothing is lost.
  The docstring's "the open scene and its file agree after it" was loose for a hard link: cut in `58e569d`, a
  one-line change.
- **A save onto the stage's own file leaves the unsaved-edits flag set:** taste; it is USD's Export, and Kit's own
  flag doesn't clear on a save either.
- **The live test breaks the suite's stage:** cleanups run last in, first out, so the stage as it was is opened again
  before its folder goes.
- **The live test passes on `main`:** two of its three tests fail there (below).
- **The tool contract moves:** only a description changed; `tests/fixtures/mcp-tools.json` is as it was.

Improvements:

| Improvement | Answer |
|---|---|
| `test_a_save_over_the_stages_own_file_by_another_spelling_writes_it` used `scene.as_posix()`, the same spelling as the layer's on Linux and macOS, so CI never took the "another spelling" path | taken in `58e569d`: a relative path under `monkeypatch.chdir`, as `test_layers.py` does; it fails without the root filter |
| Found by the author while fixing F1, the same class in #81's message: `flatten_usd` and `export_prim_as_file`'s refusal of a file the open stage has loaded told a stage never saved to "use save_scene" to save to its own file, which then fails with "No file path set" | taken in `a47fe8e`: the hint comes only when the root layer has a file, as in F1; otherwise the error ends "Write to another path.". `test_a_stage_never_saved_is_offered_no_save_to_its_own_file` runs both callers and fails without the check; CHANGELOG says so under #85 |

Not covered: the reviewer ran nothing. Sdf's internals (when Export marks a layer clean, `TfSafeOutputFile`'s rename)
were read from memory; no verdict depends on them.

## Live run

Isaac Sim 6.2.0 headless, a fresh Kit at 8212 each time.

- **Before the fix,** with `origin/main`'s (`f26642c`) extension, through `85-live.sh class`:
  - the sublayer test failed in all 3 spellings ("'success' != 'error'");
  - the held-file test failed at "the held layer wasn't read again";
  - the own-file test passed, as designed.
- **On `1aa5052`,** with the branch's extension, through `85-live.sh`:
  - step 1, the new class alone: 3 passed and 5 subtests passed;
  - step 2, both live suites: 177 passed and 16 subtests passed in 143.72 s;
  - step 3, the new class again, on the stage the suites left: 3 passed.
  - It printed "save_scene refused the sublayer's file, 3 spellings; the stage and files are intact", "save_scene
    wrote the open stage's own file by two spellings, and without a file_path" and "A file Kit held was saved over and
    read again; with an unsaved edit, refused".
- **F1's fix and the flatten and export wording, on `935025e`,** re-run with `85-live-class.sh`, which runs
  `TestFlattenAndExportKeepTheOpenStage` and `TestSaveSceneKeepsTheOpenStagesLayers`: 7 passed and 16 subtests
  passed in 3.87 s. #86's refusals still name `save_scene`, since the stage there has a file of its own; the new
  wording for a stage never saved is unit-tested only.

Not shown: other Kit apps, such as USD Composer, the Isaac Sim GUI, and paths on Nucleus (`omniverse://`).

## Checks

- **The gate:** `uv run tools/gate.py full` passed on `1aa5052`: 15 checks, 1279 passed and 179 skipped, coverage
  96.16%. On `58e569d`: 15 checks, 1280 passed and 179 skipped, coverage 96.19%. On `a47fe8e`: 15 checks, 1281
  passed and 179 skipped, coverage 96.20%.
- **Each guard has a test that fails without it,** run by hand by removing one guard at a time: the root filter (2
  tests in `test_layers.py` and the handler's own-file test), the used-layer exclusion from the unsaved-edits check (1
  test in each file), the anonymous-root check (1 test for each caller). Against `origin/main`'s `handlers/scene.py`, 3
  of the 5 handler tests fail: the sublayer refusal, the read-again and the held layer with unsaved edits.
- **CI on `87e62cb`:** one leg failed, Windows with Python 3.14. The handler's own-file test raised Boost.Python's
  `ArgumentError` reading `realPath` of an expired `Sdf.Layer`. `GetLoadedLayers()` gives weak handles, and the
  garbage collector freed an earlier test's stage during the walk. Kit can meet the same in all three tools,
  `flatten_usd` and `export_prim_as_file` since #81. Fixed in `adfdf75`: each read of a held layer is guarded, and
  a layer gone since it was listed is passed over, never refused. Two deterministic tests feed expired handles into
  the walk; the first fails with CI's error against the old `layers.py`. The gate passed on `adfdf75`: 1283 passed,
  and the whole suite on Python 3.14 too.
