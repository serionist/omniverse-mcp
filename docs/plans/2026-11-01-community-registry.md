---
title: List ovmcp.bridge in Kit's community extension registry
issue: "#101"
status: draft
approved_by:
approved_at:
---

# List ovmcp.bridge in Kit's community extension registry

## Goal

A Kit app's Extensions window finds *Omniverse MCP Bridge* in Kit's community registry and installs the release's own
archive of it, and the docs say how to run the server of the same release beside it. Today the bridge reaches Kit only
through `extension install` (the plugin's setup runs it) or the release's zip unpacked by hand.

- **In scope:**
  - each release attaches the extension under the two names the registry's crawler reads, and `tools/release.py`
    builds and checks them, on every pull request too;
  - `extension.toml` gains what the listing shows (`repository`, `keywords`, `icon`, `preview_image`) and the Kit
    floor the README states, Kit 107 (Q2, Q3);
  - the GitHub topic `omniverse-kit-extension`, a one-time setting for the maintainer (Q4);
  - what users read about pairing the server with a bridge from the registry: the docs, the extension's own README
    (Kit's Overview shows it), and the server's mismatch messages (Q6);
  - a Kit experiment on a local registry before any code, and the release-day check after.
- **Out of scope:**
  - NVIDIA's "Community - Verified" or Partner status (`exchange`, K5): NVIDIA's to give, not ours to set (Q3);
  - the plugin's setup moving to the registry (Q8);
  - the server, which still comes from PyPI only;
  - the listings of releases before this one: the crawler indexes them from GitHub's source zipball once the topic is
    set (R4, R11), and nothing of ours changes that;
  - GitHub's immutable releases, which would lock the archives the registry points at (Risks): an issue of its own.

## What the registry, Kit and the code say

Read on 2026-11-01. The registry's files were downloaded into a scratch folder and parsed as data; nothing from them
was run.

### The crawler and its index

| # | Fact | Evidence |
|---|---|---|
| R1 | The registry is a public S3 bucket behind CloudFront that lists its keys. Under `exts/kit/community/` is one folder, `3/`: `index.zip` (48 KB, one `index.json`), `archives/` (866 JSON files of per-package metadata, no zips), `resources/` (icons and previews named by their MD5), `bak/` (1,978 dated copies of the index). There is no `v2/registry.gz` or `summaries.gz`: one index for every Kit version | `https://dw290v42wisod.cloudfront.net/?list-type=2&prefix=exts/kit/community/`, 3,080 keys |
| R2 | `index.json`: 670 entries keyed by package id, plus `#meta`; 208 extension names from 155 repos. Each entry is Kit's dictionary of the extension's `extension.toml` with the crawler's fields: `archivePath`, `archiveSubdir`, `githubRelease`, `repository` (rewritten to `tree/<tag>`), `authors` (the owner's GitHub URL put first), `publish.kitVersion` (`106.4.0+release...` on 478), `trusted: 0`, `icon_remote` and `preview_image_remote` (copied to `resources/`), and the readme and changelog inlined as text | `3/index.zip`; meshy's `3/archives/ai.meshy.bridge/ai.meshy.bridge-0.1.0.json` |
| R3 | Two sources: 139 entries point at a release asset, every one named `<owner>-<repo>-<linux\|windows>-x86_64-<tag>.zip`; 531 at GitHub's source zipball of the tag (`/archive/refs/tags/<tag>.zip`). A tag gets one or the other: of the 7 repos with both kinds, no tag has both (stereolabs/zed-isaac-sim: v4.2.1 from its asset, v4.3.0 from the zipball) | the index |
| R4 | A release without the named assets falls back to its source zipball: meshy's v0.1.0 attaches `ai.meshy.bridge-0.1.0.zip`, and its entry reads `archive/refs/tags/v0.1.0.zip` with `archiveSubdir` `meshy-omniverse-bridge-0.1.0/exts/ai.meshy.bridge` | meshy's release; the index |
| R5 | The crawler builds the asset's URL from the pattern: MPCDI's asset is `momentfactory-omniverse-mpcdi-converter-windows-x86_64-v1.1.1.zip`, its entry's `archivePath` `MomentFactory-Omniverse-MPCDI-converter-windows-x86_64-v1.1.1.zip` | MPCDI's release; the index |
| R6 | It walks an archive for `config/extension.toml`. Zipball subdirs include `exts/`, `source/`, `source/extensions/`, `src/`, `ext/`, `extensions/`, `extension/exts/` and template folders deep in a repo; asset subdirs are a folder at the archive's root (117), `exts/<name>` (18) or one deeper (1) | the index |
| R7 | An extension takes its folder's name. Three asset archives with `config/extension.toml` at their root were indexed as `tmpqmqaxgtn-0.1.1+106.4.0` (telekinesis v0.1.1, whose toml says `name = "telekinesis.isaacsim.bridge"`), `tmp9mscnagj-2.0.0...` and `tmpgbub0aod-3.0.0...` (isaac-audio-sensors): the crawler's temp folder. Telekinesis v0.2.0 put it under `telekinesis.isaacsim.bridge-0.2.0/` and got its name; so did MPCDI's `mf.ov.mpcdi_converter/` and Cesium's `cesium.omniverse/` | the three archives, listed with `zipfile`; the index |
| R8 | One archive may hold several extensions (Cesium's: `cesium.omniverse` and `cesium.usd.plugins`); NVIDIA's test archive is a whole `repo package` build, `exts/omni.community.release.test/` among `apps/` and `dev/` | the index; `jshrake-nvidia/kit-community-release-test` v0.0.2 |
| R9 | A Python-only extension needs one archive: telekinesis, MPCDI and runnitai attach Windows only, VicOne and isaac-audio-sensors Linux only, and their entries have no platform target, so Kit offers them on both. Where a repo attaches both and one extension in them has no platform target (railOmniverse-Demo v0.12.2's `omni.usd.schema.rail.core`), the index has one entry for it, from the Linux archive: it is keyed by package id | the releases; the index |
| R10 | Kit versions: 325 entries have no `target` and Kit offers them to every version. An explicit `[package.target] kit` in the archive is kept: MPCDI's `["105.1"]`, stereolabs' `["107.3"]` and `["110.1.2"]`, isaac-audio-sensors' `["110.1"]`, all indexed by the 106.4.0 crawler. `writeTarget.kit = true` without a target gets the crawler's own Kit, `106.4.0` (telekinesis, khemoo, gangelia). A target becomes the id's build metadata: `mf.ov.mpcdi_converter-1.1.1+105.1` | the index; MPCDI's and telekinesis' archives |
| R11 | The crawler indexes earlier releases too: isaac-audio-sensors' v1.0.0, released 2026-05-25, was indexed 2026-09-15; MPCDI's releases of 2023 and 2024 carry 2026-05-26, when 352 entries were indexed again by Kit 106.4.0. The newest entries are of 2026-10-28 | `publish.date` against the releases' dates |
| R12 | `exchange` is set on 1 entry of 670 (`forge.domain_randomization`), `support_level` on 2 | the index |
| R13 | Ours: v0.2.0 to v0.3.0 attach `ovmcp.bridge-<v>.zip` only (124 KB for 0.3.0); the repo has 12 topics, not `omniverse-kit-extension`; v0.3.0's source zipball is 1.3 MB, the extension at `omniverse-mcp-0.3.0/extension/ovmcp.bridge`, the only `config/extension.toml` in every tag | `gh api repos/serionist/omniverse-mcp/releases`; the zipball |

NVIDIA's pages say little more: the topic, a GitHub release, the two archive names, "within ~24 hours", `repository`
required, names starting `omni` skipped ([community registry][community], [C++ template, publishing][template]).

[community]: https://docs.omniverse.nvidia.com/kit/docs/kit-registry-reference/latest/community/extensions.html
[template]: https://docs.omniverse.nvidia.com/kit/docs/kit-extension-template-cpp/latest/index.html

### Kit

Read from the files of an Isaac Sim 5.1 install (Kit 107.3) and a 6.2 pip install (Kit 110), and the Kit manual's
[Extensions (advanced)](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/guide/extensions_advanced.html).

| # | Fact | Where |
|---|---|---|
| K1 | `omni.kit.registry.nucleus` reads a registry from http(s) (read only), a local folder or Nucleus. It tries the v2 layout (`registry.gz`, `summaries.gz`, `packages/`) first, then v1 at `<url>/<registryVersion>/` as `index.zip`, `index.json` or `index.toml`; `/app/extensions/registryVersion` is `"3"` in both Kits | `index_v1/index.py` 76-86, `index_v1/index_operations.py` 36, `docs/Architecture.md`, `kernel/config/kit-core.json` |
| K2 | To install, Kit downloads `archivePath`, resolved against the index file (so a relative path works), unpacks `archiveSubdir` into its cache, and names the cache folder by the package id | `registry_provider.py` 400-418, 698-794 |
| K3 | An ext id drops the build metadata: the cache folder `isaacsim.anim.robot.schema-0.1.1+110.4.0` starts as `[ext: isaacsim.anim.robot.schema-0.1.1] startup`, and no startup line of a 6.2 log carries a `+`. So `version_from_ext_id` would read `0.4.0`, not `0.4.0+107.0` | a 6.2 log; `ovmcp/core/protocol.py` |
| K4 | Isaac Sim 5.1's apps list `kit/community` (`isaacsim.exp.full.kit` line 183, `isaacsim.exp.base.kit` 284). 6.2's apps list no registries, and its `kit-core.json` only `kit/prod/default` and `kit/prod/sdk`: a 6.2 user adds the registry under **Window > Extensions**, the menu, **Settings**, **Extension Registries**, kept in `/persistent/exts/omni.kit.registry.nucleus/userRegistries` | the app files; `exts_properties_widget.py` 120, `common.py` 44 |
| K5 | The Extensions window: `exchange = true` labels an entry "Community - Verified", or Partner; `trusted` false, as the crawler writes it, "Community - Unverified", and **Install** first asks: "ATTENTION: UNVERIFIED COMMUNITY EXTENSION. This extension will be installed directly from the repository ... It is not verified by NVIDIA and may contain bugs or malicious code" | `omni.kit.window.extensions` 1.7.0 `common.py` 323-349, 572-600 |
| K6 | Autoload records the full id, version included, and turns the extension's other versions off | `ext_controller.py` 59-76 |
| K7 | "Kit target is special, it compares the current Kit version is greater or equal to the one written in target.kit": Kit 105.1.1 takes `104.0` and `105.1.1`, not `105.1.2` or `106.0.0`; the default is `["*"]`. `writeTarget.kit = true` writes the publishing Kit's version. A python target is written at publish only for an extension with `[native]` and `[python]` | Kit manual |
| K8 | `icon`: shown in the Extensions window, 256 by 256 recommended. `preview_image`: shown in the Overview. `repository`: "used for display in the UI". `keywords`: "helpful when searching for it in an Extension registry". `changelog`: a file in the extension's folder, which the UI shows | Kit manual |

### The code, at `67a5069`

| # | What | Where |
|---|---|---|
| C1 | The release zips the extension with `git archive --format=zip --prefix=ovmcp.bridge/` into `ovmcp.bridge-X.Y.Z.zip`, and attaches `release/*.zip`; nothing checks the zip, and CI never builds it | `release.yml` 56-61, 166 |
| C2 | `extension.toml` has `version`, `category`, `title`, `description`, `authors`, `readme`; no `repository`, `keywords`, `icon`, `preview_image` or target | `extension/ovmcp.bridge/config/extension.toml` |
| C3 | Five texts tell the user to install the server's extension with `install_command()`: `get_sim_state`'s note, the unknown-route error, and three handshake errors | `tools/simulation.py` 85-89, `tools/_bridge.py` 39-43, `client.py` 104-123 |
| C4 | The gate's version check reads `omniverse-mcp==X.Y.Z` and `ovmcp.bridge-X.Y.Z` pins under `plugin/` only | `tools/gate.py` 85-87, 636-653 |
| C5 | AGENTS.md is at its cap, 150 lines | `wc -l AGENTS.md` |

## Design

### The archives (Q1)

`tools/release.py archives <dir> [vX.Y.Z]` builds what a release attaches, from `HEAD`, and checks it; the version is
the tag's, or pyproject.toml's when no tag is given:

1. `git archive --format=zip --prefix=ovmcp.bridge/ -o <dir>/ovmcp.bridge-X.Y.Z.zip HEAD:extension/ovmcp.bridge`,
   as today;
2. the same bytes copied to `<dir>/serionist-omniverse-mcp-linux-x86_64-vX.Y.Z.zip` and
   `<dir>/serionist-omniverse-mcp-windows-x86_64-vX.Y.Z.zip`, the names the crawler builds from the repository and
   the tag (R3, R5); a constant `REPOSITORY = "serionist/omniverse-mcp"` gives the prefix;
3. `archive_problems` on each, which names:
   - an entry outside `ovmcp.bridge/`: Kit names the extension by its folder, and a toml at the root is indexed under
     the crawler's temp folder (R7);
   - no `ovmcp.bridge/config/extension.toml`, or a `package.version` other than X.Y.Z;
   - no `repository`, or no `[package.target] kit` (Q2);
   - a file the toml names (`readme`, `icon`, `preview_image`) missing from the zip;
   - a `__pycache__` folder or a `.pyc` file;
   - the three files not byte for byte equal.

`release.yml`'s verify job runs `uv run --no-project tools/release.py archives release "$GITHUB_REF_NAME"` in place of
its `git archive` step, and the github-release job attaches `release/*.zip` as today, now three files. `ci.yml`'s
package job runs `tools/release.py archives release` on every pull request, so a change that moves the folder, drops
the icon or breaks the layout fails before a tag, and keeps `release/` as the `extension` artifact for 14 days, so a
release PR's archive can be tried in a local registry (Tests, E4).

| Alternative | Why not |
|---|---|
| Attach nothing new: the crawler falls back to the source zipball (R4) | Kit would fetch the whole repo, 1.3 MB against 124 KB (R13); the crawler would have to find `extension/ovmcp.bridge`, a folder name no entry has yet (R6); nothing to check before a release |
| One platform's name only | Works (R9), but the documented pair costs only a copy, and the index keeps one entry per id |
| Kit's `repo package` | A build toolchain for a Python-only folder that `git archive` already zips in the right layout |
| `git archive` and `cp` in the two workflows | The names and the checks in two YAML files; `release.py` keeps them in one place, under unit tests |

### The extension.toml (Q2, Q3)

```toml
[package]
version = "0.3.0"
category = "Simulation"
title = "Omniverse MCP Bridge"
description = "HTTP bridge enabling AI assistants to control Omniverse applications via the Model Context Protocol"
authors = ["Soma Osvay"]
repository = "https://github.com/serionist/omniverse-mcp"
keywords = ["mcp", "model context protocol", "ai", "agent", "assistant", "llm", "claude", "isaac sim", "automation"]
readme = "docs/README.md"
icon = "data/icon.png"
preview_image = "data/preview.jpg"

# Kit 107 or later, as the README says. Kit takes a target as "this version or later", so neither the Extensions
# window nor a folder on Kit's search path offers this release to an older Kit.
[package.target]
kit = ["107.0"]
```

Left out, each for a reason:

- `writeTarget.kit`: the crawler's Kit would write its own `106.4.0` (R10, K7);
- `name`: the folder names the extension (R7);
- `exchange`: it labels the listing "Community - Verified" and drops Kit's warning (K5), a claim NVIDIA hasn't made
  (Q3);
- `changelog`: Kit wants a file in the extension's folder (K8); `CHANGELOG.md` is the repo's, the server's too, and a
  copy would drift (Q3). The extension's README links it.

The listing shows the description, the readme, the keywords and the repository. Its `repository` is rewritten by the
crawler to the tag's tree (R2) but required by NVIDIA's page.

### The images (Q3)

| File | What | Size |
|---|---|---|
| `extension/ovmcp.bridge/data/icon.png` | `plugin/.claude-plugin/icon.png`, the logo on a dark square, scaled to 256 pixels (K8) | about 10 KB |
| `extension/ovmcp.bridge/data/preview.jpg` | `docs/images/hero-viewport.jpg`: the Franka workcell as `capture_viewport` returns it, 640 pixels square | 36 KB |

The wheel carries both (the extension is force-included), about 50 KB more. `docs/images/README.md` says how each was
made.

### What a user sees

- **Isaac Sim 5.1** lists the registry already (K4); **6.2** and other Kit apps add it once, in **Extension
  Registries**: name `kit/community`, URL `https://dw290v42wisod.cloudfront.net/exts/kit/community`.
- The Extensions window lists *Omniverse MCP Bridge* under **THIRD PARTY**, labelled "Community - Unverified", with
  the icon, the readme as its Overview, the preview and the repository link. **Install** warns first (K5); then the
  user turns it on with **Autoload**, as for a folder install. E4 confirms the clicks before the docs name them.
- The listing appears the day after the release (R11). Every version stays listed, and the window offers the newest
  that matches the Kit (K7).

### The topic (Q4)

The maintainer adds `omniverse-kit-extension` once, after the first release with the archives: the repo page's
**About** gear, **Topics**, or `gh repo edit serionist/omniverse-mcp --add-topic omniverse-kit-extension`.
`docs/releasing.md`'s **Once** table gets the row.

### Pairing the server with a bridge from the registry (Q6, Q8)

The registry serves the bridge; the server still comes from PyPI, and the two must be one release. A user reads it in
four places:

1. **The extension's README, Kit's Overview:** this is the Kit half; the MCP server is `omniverse-mcp` from PyPI, at
   this release, `uvx omniverse-mcp==X.Y.Z` in the client's config (the project's README, Install). The gate's
   version check reads this file too (`plugin_versions` scans `extension/ovmcp.bridge/docs/README.md`), so the release
   PR bumps the pin with the others.
2. **`docs/SETUP.md`, a section "From Kit's community registry":** adding the registry on 6.2; installing past the
   warning; pinning the server to the version Kit shows; one source at a time, since a registry copy and an
   `extension install` copy are two versions of one extension and Autoload picks one (K6); updating both together;
   the day's lag after a release; uninstalling in the Extensions window.
3. **The server's texts (C3):** today each says to run `extension install`, which a registry user's Kit never sees
   (its folder isn't on their search path). One helper in `kit_extension.py`, `install_advice()`, gives the five
   texts one ending: `install the server's, <install_command()>, then restart Kit; with the extension from Kit's
   community registry, install <carried_version()> in Kit's Extensions window instead`. Answer text only: no tool's
   name, schema or hints change (Q6).
4. **The plugin's setup skill (Q8):** stays on `extension install`, pinned and immediate. Its step 3's last paragraph,
   on another copy of the extension, names a copy from the community registry too: turn it off, or uninstall it.

`release.py`'s `INSTALL`, under each release's notes, gains a line for Kit's community registry, with the server pinned
to the release.

## Compatibility

| What | Change |
|---|---|
| The extension id `ovmcp.bridge` and its settings | None |
| A new one-way door | The archives' names and layout, and the releases they hang on (Q7) |
| Kit apps | Kit 107 and later load it as today. Kit 106 and older no longer offer this release from a folder or the registry; the README has said 107 or later since 0.2.0. Releases before this one may still be offered to them (R4, R11), as they were released |
| `extension install` users, the plugin's included | None: the target matches their Kit 107.3 or 110 (E1, E2, the live suites) |
| The tool contract | None: Q6 changes answer text, not names, schemas or hints |
| The GitHub release | Two more files; `ovmcp.bridge-X.Y.Z.zip` stays (Q1) |
| The wheel | About 50 KB more, the two images |

## Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | The release's files: (a) add the two crawler names beside `ovmcp.bridge-X.Y.Z.zip`, three identical zips; (b) replace `ovmcp.bridge-X.Y.Z.zip` with the two; (c) add nothing and let the crawler take the source zipball | (a): the documented name stays for people and scripts that fetch it (SETUP's "A Kit machine without uv"), the crawler gets its own; (c) serves the whole repo, 10 times the size, from a folder the crawler hasn't been seen to find | Open |
| Q2 | The Kit floor: (a) `[package.target] kit = ["107.0"]`; (b) no target, as meshy and 324 others; (c) `writeTarget.kit = true` | (a), once E1 to E3 hold: the listing then matches the README's Kit 107 or later. (b) offers the release to Kit 106 apps it was never tested on; (c) writes the crawler's 106.4.0 (R10) | Open |
| Q3 | The listing's fields: `repository`, `keywords`, `icon`, `preview_image` as designed; `changelog` or not; `exchange` or not; the icon as a 256 px PNG of the plugin's icon, or the logo's SVG | The four fields; no `changelog` (a copy of the repo's would drift, and the README links it); never `exchange`, which claims a verification NVIDIA hasn't made (K5); the PNG, the size Kit recommends | Open |
| Q4 | The topic: (a) after the first release with the archives; (b) now | (a): the first listing is then this design's, with the docs that explain it; (b) would list 0.2.0 to 0.3.0 now from source zipballs, without the Kit floor, and the crawler indexes them either way (R11) | Open |
| Q5 | Testing before a release: (a) the local-registry experiment once, its scripts in this plan, and CI building and checking the archives on every PR; (b) keep the registry builder in `tools/release.py` for every release; (c) a public test repo of the maintainer's | (a): Kit's side is proven once (E1 to E4) and the archive's layout is what can regress, which CI checks; (b) is code kept for a format the crawler, not Kit, defines; (c) leaves a test entry in the public registry for good and waits a day each try | Open |
| Q6 | The server's texts: (a) docs only; (b) the five texts (C3) also name the registry's fix, through one helper | (b): a registry user who follows today's text installs a copy their Kit never loads, and reads the same note again. The clause costs a line, and a plugin or uvx user skips it | Open |
| Q7 | A one-way door: add "the release archives' names and their `ovmcp.bridge/` layout, and no release or archive deleted" to AGENTS.md's list, inside the extension id's line (AGENTS.md is at its 150 lines) | Yes: the crawler builds the names (R5) and Kit downloads every listed version from its release (K2); a rename stops the listing, a deleted asset breaks its installs | Open |
| Q8 | The plugin's setup: keep `extension install`, or offer the registry? | Keep it: pinned to the plugin's release and there at once, where the registry lags a day and needs a registry added on 6.2. It names a registry copy as another copy to turn off | Open |

## Steps

1. **The experiment, E1 to E3,** before any code: the main session runs the appendix's scripts on its own headless
   Kit at port 8212, on Isaac Sim 6.2 and 5.1 (Tests). Each result is written here as E1 to E3; they answer whether
   Q2's target holds.
2. **`extension.toml` and `data/`** (Q2, Q3): the fields, the target, the two images. Test: the live suites from the
   folder install on 6.2 and 5.1 (the target doesn't hide it from Kit 107.3 or 110); `tests/test_kit_extension.py`'s
   install copies `data/`.
3. **`tools/release.py archives`** and `archive_problems`. Tests in `tests/test_release.py`: a good archive passes; a
   toml at the root, a second top folder, another version, no `repository` or target, a named icon or preview
   missing, a `.pyc`, three unequal files and a wrong name are each named; `archives` builds the three from a
   throwaway git repository in `tmp_path`; the repo's own extension passes.
4. **The workflows:** `release.yml`'s verify job and `ci.yml`'s package job call `archives`; the package job keeps the
   `extension` artifact. Test: the PR's own `Package (Linux)` run builds and checks them.
5. **The server's texts** (Q6): `install_advice()` in `kit_extension.py`, used by the five texts. Tests: the existing
   ones in `tests/test_tools.py` and `tests/test_client.py` that read these texts, now with the clause.
6. **The gate** (Q6): `plugin_versions` reads the extension README's `omniverse-mcp==` pin. Test: `tests/test_gate.py`
   names the README when its pin is out of step.
7. **`release.py`'s notes:** the `INSTALL` line for the registry. Test: `tests/test_release.py`'s notes test.
8. **The docs** (Docs, below).
9. **E4,** on the branch, by the maintainer with a window: the listing in the Extensions window from the local
   registry built from CI's `extension` artifact.
10. **finish-work:** the gate, the live suites on 6.2 and 5.1, `review-code`, the PR.
11. **After the release** (`docs/releasing.md`): the topic, once (Q4); the next day, the release-day check finds
    `ovmcp.bridge-X.Y.Z+107.0` in the index.

## Tests

| Suite | What it proves |
|---|---|
| Unit, CI | `tests/test_release.py` (archives and their checks, the notes), `tests/test_gate.py` (the README's pin), `tests/test_tools.py` and `tests/test_client.py` (the texts), `tests/test_kit_extension.py` (`data/` installed) |
| `Package (Linux)`, CI | The real archives, built from the PR's `HEAD` and checked, on every pull request |
| Live, by hand | `test_integration.py` and `test_scenarios.py` on Isaac Sim 6.2 and 5.1 from the folder install, with the target in the toml |
| The experiment | Kit takes the archive from a registry entry shaped as the crawler writes it, and the target means what K7 says |

**The experiment.** The appendix's `local_registry.py` builds a one-extension registry in a folder: `3/index.zip`
with one entry shaped as R2's (the crawler's fields, `trusted: 0`, the readme inlined), the archive as step 3 builds
it under `3/archives/`, and the images under `3/resources/`. `probe.py` runs inside Kit with `--exec` and prints, each
line starting `OVMCP-PROBE`, the registries Kit uses, the bridge enabled at start and its path, every version Kit
sees, and the solver's answer.

Before step 2 the tree has no target, so `--target-kit` writes one into the archive's copy of the toml. Three
registries are built already, from `67a5069`, in the planning session's scratch folder: `registry-107`
(`ovmcp.bridge-0.3.0+107.0`), `registry-999` (`ovmcp.bridge-0.3.0+999.0`) and `registry-none` (`ovmcp.bridge-0.3.0`).

The main session's usual headless start, with:

- **removed:** every `--ext-folder` that holds `ovmcp.bridge` and its `--enable` from a folder, and a search path to
  the `exts` folder in Kit's user config, if it holds one, so no local copy competes;
- **added:**

  ```
  --/exts/omni.kit.registry.nucleus/registries/2/name=ovmcp-test
  --/exts/omni.kit.registry.nucleus/registries/2/url=<the registry folder, forward slashes>
  --/exts/omni.kit.registry.nucleus/cachePath=<scratchpad>/101/extcache
  --/exts/ovmcp.bridge/port=8212
  --enable ovmcp.bridge
  --exec <scratchpad>/101/scripts/probe.py
  ```

  On 5.1, index 2 is the app's `kit/community`, which this replaces for the run. On 6.2 it adds a third registry to
  `kit-core.json`'s two; if the probe's registries line lacks `ovmcp-test`, use index 0 instead. `cachePath` keeps the
  download out of Kit's own cache; nothing is persistent, so Kit's user config is untouched.

| # | Run | Passes when |
|---|---|---|
| E1 | 6.2, `registry-107` | Kit's log shows `downloading: '.../3/archives/serionist-omniverse-mcp-linux-x86_64-v0.3.0.zip'` and `[ext: ovmcp.bridge-0.3.0] startup`; the probe's path is under `extcache`; `get_sim_state` with `OMNIVERSE_MCP_PORT=8212` answers `extension_version = 0.3.0` and no `note` (K3) |
| E2 | 5.1, `registry-107` | As E1, on Kit 107.3 |
| E3 | 6.2, `registry-999` | The probe lists `0.3.0+999.0` and the solver refuses it; the bridge doesn't start. `registry-none` then loads as E1 (the old releases' case) |
| E4 | after step 4, the maintainer, 6.2 with its window, a registry built from CI's `extension` artifact (the real archive, no `--target-kit`) | The listing under THIRD PARTY, "Community - Unverified", with the icon, the preview and the readme; Install shows K5's warning; Autoload; the clicks the docs name |

If `--enable` doesn't fetch from a registry headless, the probe still shows what Kit sees, and E1 to E3 run with the
window's **Install** instead, by the maintainer. Afterwards, delete `<scratchpad>/101/extcache` and any
`ovmcp.bridge-0.3.0+...` link the log names under Kit's folders.

**What neither shows:** the crawler itself. Its first entry for us is read the day after the first release with the
archives (step 11); R1 to R13 stand in for it until then.

## Docs

| File | Change |
|---|---|
| `README.md` | Install, Other MCP clients, step 1: the registry as the other way to get the bridge, in three lines, pointing at SETUP; Updating: a registry bullet; the two-parts list: the bridge is listed in Kit's community registry too |
| `docs/SETUP.md` | A section "From Kit's community registry" (Design); Updating and Uninstalling: the registry's way; Troubleshooting: "`get_sim_state` has a `note`" names a registry copy; "A Kit machine without uv": either archive of the release |
| `extension/ovmcp.bridge/docs/README.md` | Kit's Overview: the Kit half, the server at this release with its pin (Q6), both ways to install, the changelog's link |
| `plugin/skills/setup/SKILL.md` | Step 3's last paragraph and step 4: a copy from the community registry (Q8) |
| `docs/releasing.md` | Once: the topic. Step 5: the release has the three zips; the next day, `curl -sI "https://dw290v42wisod.cloudfront.net/exts/kit/community/3/archives/ovmcp.bridge/ovmcp.bridge-X.Y.Z%2B107.0.json"` answers 200 (the `+` as `%2B`; with `+` it is a 404). With Q5 (b), step 2 would also try CI's `extension` artifact in a local registry |
| `docs/images/README.md` | The icon's and the preview's rows |
| `CHANGELOG.md` | Unreleased, Added: the bridge in Kit's community registry, the release's two archives, the listing's fields; Changed: the extension declares Kit 107 or later, and the mismatch texts name the registry's fix |
| `AGENTS.md` | The extension's row: `data/`; the `.github/` row: `release.yml` attaches the archives Kit's community registry reads; the `tools/` row: `release.py` builds them; One-way doors: Q7's line, within the 150 |
| `docs/ARCHITECTURE.md`, `docs/TOOLS.md` | None: no route, protocol, token or tool changes |

## Risks

| Risk | Status |
|---|---|
| The crawler is documented only by its names and could change | Accepted: R1 to R13 are today's behaviour; the release-day check (step 11) catches a change on the next release |
| The crawler finds `extension/ovmcp.bridge` in the old tags' zipballs and lists 0.2.0 to 0.3.0 without a target; 0.2.0's bridge hangs Kit (#5) | Accepted: they are real releases, the window offers the newest by default, and nothing of ours can unlist them. If the crawler doesn't find the folder, nothing is listed for them |
| Kit 106 offered 0.3.0 from its zipball | Accepted: the README has said Kit 107 or later since 0.2.0 |
| A registry copy and an `extension install` copy in one Kit | SETUP's one-source rule, the setup skill (Q8), the texts (Q6); Autoload picks one version (K6) |
| The day's lag: unpinned `uvx` moves at PyPI's pace, the registry's listing the next day | Accepted: SETUP says to pin the server to the version Kit shows; Q6's text names the fix |
| A release's archive replaced after the release: GitHub lets a maintainer delete and re-upload an asset, and the index holds no hash | Accepted, as for today's zip: only the maintainer can; GitHub's immutable releases would lock the assets, an issue of its own |
| The archive's layout regresses (a toml at the root, R7) | Resolved: `archive_problems` on every PR and every tag |
| `target.kit` means something else in practice, or hides a folder install | Open until E1 to E3 run, before any code (step 1); Q2 waits for them |
| `exchange` set by mistake | Resolved: Q3 leaves it out, and the design says why |
| AGENTS.md is at 150 lines | Resolved: Q7 edits a line, the rows edit theirs |

## Plan review

Not reviewed yet: drafted 2026-11-01 for `review-plan`.

## Appendix: the experiment's scripts

Standard library only. `local_registry.py` reads the extension folder and writes only under the registry folder; run
it with `python -I` from the folder that holds it. `probe.py` only reads Kit's state and prints it.

`local_registry.py`:

```python
"""Build a one-extension Kit registry in a folder, shaped as the community registry's crawler writes it (#101).

Usage: python -I local_registry.py <extension folder> <registry folder> [--target-kit 107.0] [--repo owner/name]
"""

import argparse
import hashlib
import io
import json
import shutil
import time
import tomllib
import zipfile
from pathlib import Path

NAME = "ovmcp.bridge"
CRAWLER_KIT = "106.4.0+release.156974.9321c814.gl"  # what the crawler's entries record today

parser = argparse.ArgumentParser()
parser.add_argument("extension", type=Path)
parser.add_argument("registry", type=Path)
parser.add_argument("--target-kit")
parser.add_argument("--repo", default="serionist/omniverse-mcp")
args = parser.parse_args()

toml_text = (args.extension / "config" / "extension.toml").read_text(encoding="utf-8")
if args.target_kit:
    if "[package.target]" in toml_text:
        raise SystemExit("extension.toml has [package.target] already: drop --target-kit")
    toml_text += f'\n[package.target]\nkit = ["{args.target_kit}"]\n'
config = tomllib.loads(toml_text)
package = dict(config["package"])
version = package["version"]
kit = (package.get("target") or {}).get("kit")
package_id = f"{NAME}-{version}" + (f"+{kit[0]}" if kit else "")
owner, repo = args.repo.split("/")
archive_name = f"{owner}-{repo}-linux-x86_64-v{version}.zip"

root = args.registry / "3"
if root.exists():
    shutil.rmtree(root)
(root / "archives").mkdir(parents=True)
(root / "resources").mkdir()

# The release's archive: every file of the extension under ovmcp.bridge/, as `git archive --prefix=ovmcp.bridge/`.
with zipfile.ZipFile(root / "archives" / archive_name, "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(args.extension.rglob("*")):
        rel = path.relative_to(args.extension).as_posix()
        if path.is_file() and "__pycache__" not in rel and not rel.endswith(".pyc"):
            data = toml_text.encode() if rel == "config/extension.toml" else path.read_bytes()
            z.writestr(f"{NAME}/{rel}", data)

# The entry, as the crawler writes one: the toml's package, the readme inlined, and its own fields.
for key in ("readme", "changelog"):
    if key in package and (args.extension / package[key]).is_file():
        package[key] = (args.extension / package[key]).read_text(encoding="utf-8")
for key in ("icon", "preview_image"):
    if key in package and (args.extension / package[key]).is_file():
        data = (args.extension / package[key]).read_bytes()
        remote = f"{hashlib.md5(data).hexdigest()}{Path(package[key]).suffix}"
        (root / "resources" / remote).write_bytes(data)
        package[f"{key}_remote"] = f"./resources/{remote}"
package.update(
    id=package_id,
    packageId=package_id,
    name=NAME,
    metadata="",
    archivePath=f"archives/{archive_name}",
    archiveSubdir=NAME,
    authors=[f"https://github.com/{owner}", *package.get("authors", [])],
    githubRelease=f"https://github.com/{args.repo}/releases/tag/v{version}",
    publish={"kitVersion": CRAWLER_KIT, "date": int(time.time()), "buildNumber": f"v{version}"},
    repository=f"https://github.com/{args.repo}/tree/v{version}",
    trusted=0,
)
entry = {
    "dependencies": config.get("dependencies", {}),
    "python": config.get("python", {}),
    "settings": config.get("settings", {}),
    "isInCache": False,
    "isUser": False,
    "isKitFile": False,
    "isCore": False,
    "package": package,
}
index = {"#meta": {"read_version": 1, "write_version": 1, "package": {}, "locking_enabled": False}, package_id: entry}
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("index.json", json.dumps(index, indent=1))
(root / "index.zip").write_bytes(buffer.getvalue())
print(f"{package_id}: {root / 'index.zip'}, {root / 'archives' / archive_name}")
print(f"registry url for Kit: {args.registry.resolve().as_posix()}")
```

`probe.py`, which Kit runs with `--exec`:

```python
"""Kit runs this with --exec (#101): what Kit sees of ovmcp.bridge in its registries, and where the enabled copy is."""

import json

import carb.settings
import omni.kit.app

manager = omni.kit.app.get_app().get_extension_manager()
registries = carb.settings.get_settings().get("/exts/omni.kit.registry.nucleus/registries")
print("OVMCP-PROBE registries:", json.dumps(registries, default=str))
enabled = manager.get_enabled_extension_id("ovmcp.bridge")
print("OVMCP-PROBE enabled at start:", enabled, manager.get_extension_path(enabled) if enabled else None)
manager.sync_registry()
for found in manager.fetch_extension_versions("ovmcp.bridge"):
    print("OVMCP-PROBE version:", json.dumps(found, default=str))
print("OVMCP-PROBE solve:", manager.solve_extensions(["ovmcp.bridge"], add_enabled=False, return_only_disabled=False))
```
