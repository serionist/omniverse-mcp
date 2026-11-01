---
subject: "Flatten without Kit's session layer (#118)"
base: main (f5a27ed)
head: 98d1ab0
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only; cut short by a machine restart, its open points checked by the main session"
verdict: clean
---

# Review: Flatten without Kit's session layer

Read from the branch's diff against `main`: `ovmcp/core/layers.py` (`without_session`), `ovmcp/core/usd.py`
(`anonymous_layer`), `handlers/usd_advanced.py` (`flatten_usd` and `export_prim`), the new and changed tests, and the
docs. The reviewer also read #118, `docs/plans/README.md` and #117's plan (K1 to K4, round 1's P2). A machine restart
stopped it before its usd-core checks; it reported no finding, and the main session settled its four open points.
No plan: an extension-only bug fix with no contract, door, security or protocol change.

No finding.

Open points, settled by the main session:
- **O1, the live test's mode restore** (`addCleanup(self.client.viewport_light, "set", mode=found)`) doesn't check the
  answer's status. A failed restore would leave Default for later classes; the next class's `setUp` opens a new stage
  and the suites' lighting tests set their own mode. Left as it is.
- **O2, `delete_prim(lamp)` and Default's session-layer `visibility` over** on the lamp's Sun: at most an undefined
  `over` on the open stage until the next `setUp` opens a new one. Harmless.
- **O3, TOOLS.md's "an extension of 0.3.0 or older"**: 0.3.0 is the released extension (`extension.toml`), and the fix
  sits under CHANGELOG's Unreleased, so the line is right.
- **O4, `layer_count`** now counts the second stage's empty anonymous session layer in place of Kit's session layer
  and the rig's file, so it reads lower on an open-stage flatten in a rig mode. Not in the tool contract; the TOOLS.md
  bullet says what is left out.

Refuted, each from the code:
- **The open stage changed or written:** `without_session` builds a new stage on `stage.GetRootLayer()` with
  `anonymous_layer()`; `MuteLayer` and `SetLoadRules` act on the new stage.
  `test_without_session_changes_nothing_of_the_open_stage` compares the session layer, the root layer, the dirty
  flag, the load rules and the muted layers before and after.
- **Resolver context, mask, muted layers and load rules:** all four are carried (`layers.py:178-187`), and
  `test_without_session_carries_the_muted_layers_load_rules_mask_and_resolver_context` checks each.
- **A stage never saved:** `test_without_session_of_a_stage_never_saved`.
- **Unsaved edits on the root and sublayers:** the layers come from Sdf's registry, the same objects, and the
  fixture's dirty `/World/Unsaved` reaches the file.
- **The second stage held after the call:** `src_stage` and `source` are the handler's locals; `refresh_written` only
  reloads layers the open stage doesn't use, and skips the anonymous session layer.
- **Capture isolation during an export:** a concurrent capture's session-layer hiding was baked in before; it stays
  out now.
- **A prim only in the session layer:** `if not prim or (open_prim.IsDefined() and not prim.IsDefined())` refuses the
  rig, its DomeLight, Kit's camera and the rig's bare `over`; the tests cover all four.
- **Session opinions over root content:** dropped, as Kit's Save Flattened As does.
- **`input_path`:** unchanged; `open_to_flatten` is untouched and opens its own empty session layer.
- **The live test can't catch a regression:** a rig in the file, the Sun's `visibility` in the export, or the rig's
  export succeeding each fails an assertion.
- **The tool contract and one-way doors:** no schema, name or annotation changed; `tests/fixtures/mcp-tools.json` is
  not in the diff.
- **Writing:** no em dashes or banned words; CHANGELOG has the line under Fixed.

Improvements:
- The PR names the second composition's cost: a flatten of the open stage composes the scene a second time on Kit's
  main thread, as Kit's own Save Flattened As does. taken (the PR).
- One TOOLS.md clause that an edit made while the session layer was Kit's edit target stays out too, as with Kit's own
  command. taken.

Not covered: the reviewer's usd-core checks of a sublayer edit target and of muting a session-layer sublayer; Kit's
`file_window.py:727-748`, which the author read; `bridge-security` and `harness-integrity`, which don't apply.

## Live run

Run by the session on its own headless Isaac Sim 6.2.0 (Kit 110.4.0), Windows, RTX 5090, at port 8212, with the
branch's extension from `cfd4631`.

| What ran | Result |
|---|---|
| `TestFlattenAndExportKeepTheOpenStage`, at `cfd4631` | 5 passed, 12 subtests; 1 subtest failed: `flatten_usd` in mode Default, on `assertNotIn("OmniverseKit_Persp", text)` |
| a read-only check of the open stage (`118-where-camera.py`) | Kit defines `/OmniverseKit_Persp` in the session layer, and the class's saved `IntTestScene.usda` holds an `over "OmniverseKit_Persp"` and `/Render`'s `rel camera = </OmniverseKit_Persp>`: the scene's own content, which a flatten without the session layer rightly keeps, as Kit's Save Flattened As does. The test was wrong, not the bridge |
| the class again, the check now "no `def` of Kit's camera in the file" | 5 passed, 13 subtests |
| both live suites whole, from a Z-up stage | 194 passed |
| `118-probe-flatten.py` (a lamp, mode Default, both flattens and three exports) | the files hold no rig and no hiding; exports of `/OmniverseKit_Persp` and `/OmniKit_Viewport_LightRig` erred and wrote nothing; the open stage was unchanged; a flatten of the 18-prim stage took 0.002 s either way |

What it couldn't show: Isaac Sim 5.x, Linux, USD Composer, and the cost of the second composition on a large stage.
