---
subject: "Name set_material's OmniPBR shader by its MDL source (PR #31, #30)"
base: main (1df5b71)
head: 6445734
date: 2026-10-28
round: 1
tier: standard (one fresh reviewer; findings checked against the code by the main session)
verdict: clean
---

# Review: set_material's MDL source

Read from the pack (the scope diff), the touched files in full, `handle_set_material` and `handle_update_material_paths`,
`ovmcp/core/usd.py`, NVIDIA's guide to MDL materials in Python USD and OpenUSD's UsdShadeNodeDefAPI and Material
references, with CI's results on the head (every leg passed). One minor; fixed in the commit this record follows.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `extension/ovmcp.bridge/ovmcp/core/__init__.py`, the docstring | It names the core modules that import pxr, which the tests get from usd-core: bounds, formatter, isolation and usd. The new `material.py` imports pxr too, so the list was no longer complete. | Fixed: material is in the list. |

Refuted, each from the code or the docs:

- **The source-asset form might not resolve on Kit 107 or Isaac Sim 5.x:** NVIDIA's "Create an MDL Material" guide
  uses this exact form (`SetSourceAsset("OmniPBR.mdl", "mdl")`, `SetSourceAssetSubIdentifier("OmniPBR", "mdl")`), as
  does Kit's `CreateMdlMaterialPrim`; nothing in it is new to 6.2. Not shown live on 5.x, as the PR says.
- **The universal `outputs:surface` might not suit RTX's `mdl` context:** `ComputeSurfaceSource` falls back to the
  universal output when no context-specific one exists; the wiring is unchanged from `main`, and the colours render.
- **An upgraded shader keeps `info:id`, which Kit might still read:** `GetShaderId` reads it only while
  `info:implementationSource` is `id`, and `SetSourceAsset` authors `sourceAsset`; the usd-core test pins that, and
  the live test checks an upgraded material in Kit.
- **Upgrading a material from another layer:** the attributes go to the edit target as overs, as `set_material`'s
  inputs already did; an instance proxy fails the same way it did on `main`.
- **The upgrade changes a user's own shader:** the guard takes only an `id` shader whose id is `OmniPBR`;
  `test_the_users_own_shader_is_left_alone`.
- **Inputs that no longer match:** `diffuse_color_constant` and the rest are OmniPBR.mdl's own parameters, the same
  MDL either way.
- **`update_material_paths` rewriting `@OmniPBR.mdl@`:** only for a prefix such as "Omni", which no real call uses.
- **Kit's main thread:** `ensure_material` still runs in the handler after `await _next_update()`, with no executor.
- **The live test passes without the fix:** on `main`, `GetSourceAsset('mdl')` is None, so the script fails.

Not covered: bridge-security had nothing in scope. The reviewer ran nothing; CI and the author's runs stand in.

Improvements, both taken:

- **The live test proved only the authored attributes, which usd-core already proves:** it now also upgrades an
  id-only material made as `main` made them, renders a frame, and asserts Kit logged no "SdrShaderNode" error since
  `set_material` ran, #30's own symptom.
- **A failed script showed as a bare `KeyError`:** the test asserts the script's status, with the response, first.

## Live run

Isaac Sim 6.2.0 (pip, headless) on port 8212, with the extension installed from this branch; the maintainer's own
Isaac Sim on 8211 was not touched.

- **On `6445734`:** the live suites, `-k "not test_10_ and not test_14_"` (#5): the first run after the start, 108
  passed with #6's two, #7's three and #27's `test_22_01` failing; the second, 111 passed with #7's three failing.
  Kit's log held no `SdrShaderNode` error. A scene built through the tools rendered the colours `set_material` set,
  where every one of those prims was red before.
- **On the fixes:** three runs of the live suites; `test_19_set_material` passed in each, its id-only material
  upgraded and no `SdrShaderNode` error logged after the frame. The first run failed #6's two and #7's three, the
  second #7's three and #27's `test_22_01` (on a second run, so not only a first one), the third #7's three.
- **Not shown:** a Kit app where the id resolved; Isaac Sim 5.x.

## Checks

`uv run tools/gate.py full` passed on `6445734` (664 tests, 93.33%) and on the fixes (664 tests, 93.29%).
