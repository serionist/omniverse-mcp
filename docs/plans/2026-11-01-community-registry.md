---
title: List ovmcp.bridge in Kit's community extension registry
issue: "#101"
status: approved
approved_by: serionist
approved_at: 2026-11-01
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
| C3 | Eight texts, in five files, tell the user to install the server's extension with `install_command()`, then restart Kit: `get_sim_state`'s note, the unknown-route error, three handshake errors, `capture_viewport`'s and `inspect_prim`'s size warnings, and `start_recording`'s warning. A registry user on an older bridge meets the last three as well | `tools/simulation.py` 85-89, `tools/_bridge.py` 39-43, `client.py` 104-123, `tools/camera.py` 59-60 and 72-73, `tools/recording.py` 36-39 |
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
   - a `__pycache__` folder or a `.pyc` file.

`release.yml`'s verify job runs `uv run --no-project tools/release.py archives release "$GITHUB_REF_NAME"` in place of
its `git archive` step, and the github-release job attaches `release/*.zip` as today, now three files. `ci.yml`'s
package job runs `tools/release.py archives release` on every pull request, so a change that moves the folder, drops
the icon or breaks the layout fails before a tag. The same command, run locally on a commit, makes the same bytes, which
E4 installs (Tests).

| Alternative | Why not |
|---|---|
| Attach nothing new: the crawler falls back to the source zipball (R4) | Kit would fetch the whole repo, 1.3 MB against 124 KB (R13), and nothing is checked before a release. |
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
3. **The server's texts (C3):** today each of the eight says to run `extension install`, which a registry user's Kit
   never sees (its folder isn't on their search path). One helper in `kit_extension.py`, `install_advice()`, gives
   the eight texts one ending after their own words: `<install_command()>, then restart Kit; with the extension from
   Kit's community registry, install <carried_version()> in Kit's Extensions window instead`. Answer text only: no
   tool's name, schema or hints change (Q6).
4. **The plugin's setup skill (Q8):** stays on `extension install`, pinned and immediate. Its step 3's last paragraph,
   on another copy of the extension, names a copy from the community registry too: turn it off, or uninstall it.

`release.py`'s `INSTALL`, under each release's notes, gains a line for Kit's community registry, with the server pinned
to the release.

## Compatibility

| What | Change |
|---|---|
| The extension id `ovmcp.bridge` and its settings | None |
| A new one-way door | The archives' names and layout, and the releases they hang on, from the first release that carries the archives (Q7) |
| Kit apps | Kit 107 and later load it as today. Kit 106 and older no longer offer this release from a folder or the registry; the README has said 107 or later since 0.2.0. Releases 0.2.0 to 0.3.0 will be listed from their source zipballs without a floor (R4, R11), so Kit 106 is offered those, as they were released (Q4) |
| `extension install` users, the plugin's included | None: the target matches their Kit 107.3 or 110 (step 1's runs, the live suites) |
| The tool contract | None: Q6 changes answer text, not names, schemas or hints |
| The GitHub release | Two more files; `ovmcp.bridge-X.Y.Z.zip` stays (Q1) |
| The wheel | About 50 KB more, the two images |

## Decisions for the maintainer

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | The release's files: (a) add the two crawler names beside `ovmcp.bridge-X.Y.Z.zip`, three identical zips; (b) replace `ovmcp.bridge-X.Y.Z.zip` with the two; (c) add nothing and let the crawler take the source zipball | (a): the documented name stays for people and scripts that fetch it (SETUP's "A Kit machine without uv"), the crawler gets its own; (c) serves the whole repo, 10 times the size. | (a), as recommended (2026-11-01) |
| Q2 | The Kit floor: (a) `[package.target] kit = ["107.0"]`; (b) no target, as meshy and 324 others; (c) `writeTarget.kit = true` | (a), once step 1's runs hold: the listing then matches the README's Kit 107 or later. (b) offers the release to Kit 106 apps it was never tested on; (c) writes the crawler's 106.4.0 (R10) | (a), once the experiment holds (2026-11-01); it held (E1, E3) |
| Q3 | The listing's fields: `repository`, `keywords`, `icon`, `preview_image` as designed; `changelog` or not; `exchange` or not; the icon as a 256 px PNG of the plugin's icon, or the logo's SVG | The four fields; no `changelog` (a copy of the repo's would drift, and the README links it); never `exchange`, which claims a verification NVIDIA hasn't made (K5); the PNG, the size Kit recommends | As recommended (2026-11-01) |
| Q4 | The topic: (a) after the first release with the archives; (b) now; (c) as (a), but first attach the crawler-named archive, with the 107.0 target, to the releases v0.2.0 to v0.3.0, so the crawler lists them from those assets with the floor and offers Kit 106 none (round 1's improvement 6) | (a). Either way the crawler lists 0.2.0 to 0.3.0 from their source zipballs, without the floor (R4, R11, round 1). (b) would do it now, before the docs that explain the listing. Not (c): published releases stay as they are, and the old versions' listing without a floor is harmless, since Kit 106 isn't supported | (a), not (c) (2026-11-01) |
| Q5 | Testing before a release: (a) the local-registry experiment once, its scripts in this plan, and CI building and checking the archives on every PR; (b) keep the registry builder in `tools/release.py` for every release; (c) a public test repo of the maintainer's | (a): Kit's side is proven once (E1, E3, E4) and the archive's layout is what can regress, which CI checks; (b) is code kept for a format the crawler, not Kit, defines; (c) leaves a test entry in the public registry for good and waits a day each try | (a) (2026-11-01) |
| Q6 | The server's texts: (a) docs only; (b) the eight texts (C3) also name the registry's fix, through one helper | (b): a registry user who follows today's text installs a copy their Kit never loads, and reads the same note or warning again. The clause costs a line, and a plugin or uvx user skips it | (b) (2026-11-01) |
| Q7 | A one-way door: AGENTS.md's line 114, `- the Kit extension id `ovmcp.bridge` and its settings;`, becomes `- the Kit extension id `ovmcp.bridge` and its settings; its release archives' names and layout, never deleted;` (110 characters; the file stays at 150 lines). The door starts with the first release that carries the archives, not at the list's "from `0.2.0`"; that release's CHANGELOG line says so | Yes: the crawler builds the names (R5) and Kit downloads every listed version from its release (K2); a rename stops the listing, a deleted asset breaks its installs | Yes, with the exact line (2026-11-01) |
| Q8 | The plugin's setup: keep `extension install`, or offer the registry? | Keep it: pinned to the plugin's release and there at once, where the registry lags a day and needs a registry added on 6.2. It names a registry copy as another copy to turn off | As recommended (2026-11-01) |

## Steps

1. **The experiment, E1 and E3,** before any code. The main session first shows the maintainer the Kit start command
   it will run (Tests: its usual headless start, minus the folder copy, plus the flags), and runs nothing until the
   maintainer approves it. Then it runs the appendix's scripts on its own headless Kit at port 8212, on Isaac Sim 6.2.
   Each result is written here under its number; they answer whether Q2's target holds.
2. **`extension.toml` and `data/`** (Q2, Q3): the fields, the target, the two images. Test: the live suites from the
   folder install on 6.2 (the target doesn't hide it from Kit 110), and `get_sim_state` answering without a `note`,
   which the live suites never read. `tests/test_kit_extension.py`'s install copies `data/`.
3. **`tools/release.py archives`** and `archive_problems`. Tests in `tests/test_release.py`: a good archive passes; a
   toml at the root, a second top folder, another version, no `repository` or target, a named icon or preview
   missing, a `.pyc` and a wrong name are each named; `archives` builds the three from a throwaway git repository in
   `tmp_path`; the repo's own extension passes.
4. **The workflows:** `release.yml`'s verify job and `ci.yml`'s package job call `archives`. Test: the PR's own
   `Package (Linux)` run builds and checks them.
5. **The server's texts** (Q6): `install_advice()` in `kit_extension.py`, used by the eight texts (C3). Tests, the
   existing ones that read these texts, now with the clause: `tests/test_tools.py` 796 (the recording warning),
   `tests/test_tools_camera.py` 266 and 307 (the size warnings), `tests/test_client.py` 695 (the handshake),
   `tests/test_server.py` 91 (the unknown route), and one for `get_sim_state`'s note.
6. **The gate** (Q6): `plugin_versions` reads the extension README's `omniverse-mcp==` pin. Test: `tests/test_gate.py`
   names the README when its pin is out of step.
7. **`release.py`'s notes:** the `INSTALL` line for the registry. Test: `tests/test_release.py`'s notes test.
8. **The docs** (Docs, below).
9. **E4,** on the branch, by the maintainer with a window: the listing in the Extensions window, from a local registry
   built from the zip that `tools/release.py archives` makes locally on the branch's commit, the same bytes CI and the
   release make.
10. **finish-work:** the gate; the live suites on 6.2; one 5.1 session, the folder install with the target, the live
    suites and `get_sim_state`, which needs the dev server's NVIDIA driver swapped to 580 and back (5.1's renderer
    crashes on 595, README); `review-code`; the PR.
11. **After the release** (`docs/releasing.md`): the topic, once (Q4); the next day, the release-day check finds
    `ovmcp.bridge-X.Y.Z+107.0` in the index.

## Tests

| Suite | What it proves |
|---|---|
| Unit, CI | `tests/test_release.py` (archives and their checks, the notes), `tests/test_gate.py` (the README's pin), `tests/test_tools.py`, `tests/test_tools_camera.py`, `tests/test_client.py` and `tests/test_server.py` (the texts), `tests/test_kit_extension.py` (`data/` installed) |
| `Package (Linux)`, CI | The real archives, built from the PR's `HEAD` and checked, on every pull request |
| Live, by hand | `test_integration.py` and `test_scenarios.py` from the folder install, with the target in the toml: on Isaac Sim 6.2 in step 2, and on 6.2 and 5.1 at finish-work |
| The experiment | Kit takes the release's own zip from a registry entry shaped as the crawler writes it, and the target means what K7 says |

**The experiment.** The appendix's `local_registry.py --archive <zip>` builds a one-extension registry in a folder:
`3/index.zip` with one entry shaped as R2's (the crawler's fields, `trusted: 0`, the readme inlined), the zip under
`3/archives/` with the crawler's name, and the images under `3/resources/`. Without `--target-kit` the zip is copied
unchanged; with it, only its `config/extension.toml` is rewritten, every other entry copied as it is. `probe.py` runs
inside Kit with `--exec` and prints, each line starting `OVMCP-PROBE`, the registries Kit uses, its `registryCache`,
the bridge enabled at start with its path and that path's real path, every version Kit sees, and the solver's answer.

The zips: before step 3, `git archive --format=zip --prefix=ovmcp.bridge/ -o <zip> HEAD:extension/ovmcp.bridge`,
today's `release.yml` command; from step 3, `uv run --no-project tools/release.py archives <dir>`, which makes the
same bytes for the same commit. Before step 2 the tree has no target, so E1 and E3 pass `--target-kit`. Three
registries are built already in the planning session's scratch folder, from `git archive`'s zip of `67a5069`:
`registry-107` (`ovmcp.bridge-0.3.0+107.0`), `registry-999` (`ovmcp.bridge-0.3.0+999.0`) and `registry-none`
(`ovmcp.bridge-0.3.0`, the zip byte for byte).

The main session's usual headless start, shown to the maintainer first (step 1), with:

- **removed:** every `--ext-folder` on the command line that holds `ovmcp.bridge`, and its `--enable` from a folder.
  The experiment never edits Kit's user config. If the probe's "enabled at start" line shows `ovmcp.bridge` at a real
  path outside `extcache`, a local copy competed (a search path in Kit's user config, say): the run proves nothing,
  and the main session stops and tells the maintainer;
- **added:**

  ```
  --/exts/omni.kit.registry.nucleus/registries/2/name=ovmcp-test
  --/exts/omni.kit.registry.nucleus/registries/2/url=<the registry folder, forward slashes>
  --/exts/omni.kit.registry.nucleus/cachePath=<scratchpad>/101/extcache
  --/app/extensions/registryCache=<scratchpad>/101/extinstall
  --/exts/ovmcp.bridge/port=8212
  --enable ovmcp.bridge
  --exec <scratchpad>/101/scripts/probe.py
  ```

  On 5.1, index 2 is the app's `kit/community`, which this replaces for the run. On 6.2 it adds a third registry to
  `kit-core.json`'s two; if the probe's registries line lacks `ovmcp-test`, use index 0 instead. Kit downloads a
  registry's extension into `cachePath` and installs it as a link in `registryCache` (`${data}/exts` by default) to
  that download (`cache.py` 136-148, `cacheCreateLinks`): both flags keep it in the scratch folder. None of the flags
  is persistent, so Kit's user config stays as it was.

| # | Run | Passes when |
|---|---|---|
| E1 | 6.2, `registry-107` | Kit's log shows `downloading: '.../3/archives/serionist-omniverse-mcp-linux-x86_64-v0.3.0.zip'`, `creating a link: <extinstall>/... -> <extcache>/...` and `[ext: ovmcp.bridge-0.3.0] startup`; the probe's real path is under `extcache`; `get_sim_state` with `OMNIVERSE_MCP_PORT=8212` answers `extension_version = 0.3.0` and no `note` (K3) |
| E3 | 6.2, `registry-999` | The probe lists `0.3.0+999.0` and the solver refuses it; the bridge doesn't start. `registry-none` then loads as E1 (the old releases' case) |
| E4 | after step 3, the maintainer: 6.2 with its window, the same flags without `--enable`, and a registry built with `--archive` from `release.py archives`' zip, unchanged | The listing under THIRD PARTY, "Community - Unverified", with the icon, the preview and the readme; Install shows K5's warning; the bridge turns on; the clicks the docs name |

The case on Kit 107.3 follows without a run of its own (round 1's improvement 1): the same `index_v1` code and
`registryVersion` "3" (K1), K7's greater-or-equal rule, 5.1's apps listing `kit/community` already (K4), and the 107.3
targets in the index (R10). The one 5.1 session at finish-work (step 10) then shows the target doesn't hide the folder
install.

**Results.** Run on 2026-11-01 by the main session, with the maintainer's yes, on Isaac Sim 6.2 headless (Kit
110.4.0), port 8212, from `run_registry_experiment.py` (appendix) and the scratch registries above:

| # | Result |
|---|---|
| E1 | Pass. Nothing enabled at start; `ovmcp-test` added after `kit/prod/default` and `kit/prod/sdk`; one version listed, `package_id` `ovmcp.bridge-0.3.0+107.0`, `version` `[0, 3, 0, "", "107.0"]`, and the solver took it. The log: `downloading: '.../registry-107/3/archives/serionist-omniverse-mcp-linux-x86_64-v0.3.0.zip'` into Kit's temp folder, `unpacking: ... -> <work>/extcache/v2/ovmcp.bridge-0.3.0+107.0`, `creating a link: <work>/extinstall/3/ovmcp.bridge-0.3.0+107.0 -> <work>/extcache/v2/ovmcp.bridge-0.3.0+107.0`, and `[ext: ovmcp.bridge-0.3.0] startup`, the id without `+107.0` (K3). The probe's real path was under `extcache`. `get_sim_state` on 8212: `extension_version = 0.3.0`, `server_version = 0.3.0`, no `note` |
| E3 | Pass. With `registry-999`, Kit listed no version of `ovmcp.bridge` at all, and the solver refused: "No versions of ovmcp.bridge that satisfies ... (none found)"; the enable failed and no bridge started. With `registry-none`: `package_id` `ovmcp.bridge-0.3.0`, `version` `[0, 3, 0, "", ""]`, the archive downloaded and linked as in E1, the bridge started, and `get_sim_state` answered 0.3.0 and 0.3.0, no `note` |

So Q2 (a) holds: `kit = ["107.0"]` is offered to Kit 110, and a target above the running Kit hides the package.

What the runs showed beyond the pass:

- **Enabling doesn't download.** `set_extension_enabled_immediate` answered False while the registry's version was
  listed and solvable; `pull_extension` downloaded and linked it, and the enable then held. The window's **Install**
  is that pull. A headless Kit with `--enable` at start was not run, so the docs give a headless Kit
  `extension install` only.
- **Where the install lands:** a link in `<registryCache>/3/`, the registry version's folder, to Kit's download cache.
- **A port clash:** E1's first run met an older Kit still on 8212. Its bridge logged "Failed to start server", and
  `get_sim_state` answered from the other Kit. E1 ran again on a free port; the results above are that run's. The
  launcher now refuses a taken port before it starts.

How the launcher differs from the flags above:

- Isaac Sim's `SimulationApp`, with `extra_args` for `cachePath`, `registryCache` and the port.
- The registry is added after start, as the Extensions window adds one (it writes the list and queues
  `omni.kit.registry.nucleus.REGISTRIES_CHANGED_EVENT`), on the non-persistent key, in place of the `registries/2`
  flag, which might not append to 6.2's two entries.
- The probe runs inline, in place of `--exec probe.py`.
- The bridge is enabled through the extension manager, with a pull when the enable doesn't fetch, in place of
  `--enable`: a refusal at start (E3) could have ended Kit before the probe printed.
- It checks the port is free before it starts.

**Undoing it.** The headless runs leave only their work folders, `extcache` and `extinstall`: delete them; Kit removes
its own temp download. A run with the window (E4) can leave two persistent settings behind,
each undone at the next start: a registry added under **Extension Registries** instead of by flag (K4), removed there;
and **Autoload** set on the registry's copy, which turns the folder copy's off (K6): set Autoload on the folder copy
again.

**What neither shows:** the crawler itself. Its first entry for us is read the day after the first release with the
archives (step 11); R1 to R13 stand in for it until then.

## Docs

| File | Change |
|---|---|
| `README.md` | Install, Other MCP clients, step 1: the registry as the other way to get the bridge, in three lines, pointing at SETUP; Updating: a registry bullet; the two-parts list: the bridge is listed in Kit's community registry too |
| `docs/SETUP.md` | A section "From Kit's community registry" (Design); Updating and Uninstalling: the registry's way; Troubleshooting: "`get_sim_state` has a `note`" names a registry copy; "A Kit machine without uv": either archive of the release |
| `extension/ovmcp.bridge/docs/README.md` | Kit's Overview: the Kit half, the server at this release with its pin (Q6), both ways to install, the changelog's link |
| `plugin/skills/setup/SKILL.md` | Step 3's last paragraph and step 4: a copy from the community registry (Q8) |
| `docs/releasing.md` | Once: the topic. Step 1, the places a version lives: the extension README's `omniverse-mcp==` pin joins "every `omniverse-mcp==` and `ovmcp.bridge-` under `plugin/`" (step 6). Step 5: the release has the three zips; the next day, `curl -sI "https://dw290v42wisod.cloudfront.net/exts/kit/community/3/archives/ovmcp.bridge/ovmcp.bridge-X.Y.Z%2B107.0.json"` answers 200 (the `+` as `%2B`; with `+` it is a 404). With Q5 (b), step 2 would also try the release PR's archive in a local registry |
| Comments the change makes stale | `release.yml`: its header (lines 1-5, "a zip of the Kit extension attached"), the versions its check names (42-44, the extension README's pin joins them) and the zip step's (56); `ci.yml`: the package job's (106-108), which now builds the archives; `tools/gate.py`: the pin comment (85-87) and `plugin_versions`' docstring; `tools/release.py`: its usage, with `archives` |
| `docs/images/README.md` | The icon's and the preview's rows |
| `CHANGELOG.md` | Unreleased, Added: the bridge in Kit's community registry, the release's two archives, the listing's fields; Changed: the extension declares Kit 107 or later, and the mismatch texts name the registry's fix |
| `AGENTS.md` | The extension's row: `data/`; the `.github/` row: `release.yml` attaches the archives Kit's community registry reads; the `tools/` row: `release.py` builds them; One-way doors: line 114 as Q7 gives it, 110 characters, so the file stays at 150 lines |
| `docs/ARCHITECTURE.md`, `docs/TOOLS.md` | None: no route, protocol, token or tool changes |

## Risks

| Risk | Status |
|---|---|
| The crawler is documented only by its names and could change | Accepted: R1 to R13 are today's behaviour; the release-day check (step 11) catches a change on the next release |
| The crawler finds `extension/ovmcp.bridge` in the old tags' zipballs and lists 0.2.0 to 0.3.0 without a target; 0.2.0's bridge hangs Kit (#5) | Accepted: they are real releases, the window offers the newest by default, and nothing of ours can unlist them (Q4 (c) would give them the floor). |
| Kit 106 offered 0.3.0 from its zipball | Accepted: the README has said Kit 107 or later since 0.2.0 |
| A registry copy and an `extension install` copy in one Kit | SETUP's one-source rule, the setup skill (Q8), the texts (Q6); Autoload picks one version (K6) |
| The day's lag: unpinned `uvx` moves at PyPI's pace, the registry's listing the next day | Accepted: SETUP says to pin the server to the version Kit shows; Q6's text names the fix |
| A release's archive replaced after the release: GitHub lets a maintainer delete and re-upload an asset, and the index holds no hash | Accepted, as for today's zip: only the maintainer can; GitHub's immutable releases would lock the assets, an issue of its own |
| The archive's layout regresses (a toml at the root, R7) | Resolved: `archive_problems` on every PR and every tag |
| `target.kit` means something else in practice, or hides a folder install | Resolved on Kit 110.4.0 by E1 and E3; the 5.1 session at finish-work checks the folder install on Kit 107.3 |
| The experiment changes the maintainer's Kit | Resolved: step 1 waits for the maintainer's yes to the start command; no user-config edits; non-persistent flags; Undoing it (Tests) for the window's runs |
| `exchange` set by mistake | Resolved: Q3 leaves it out, and the design says why |
| AGENTS.md is at 150 lines | Resolved: Q7 gives the exact line, 110 characters in place of line 114's 55; the rows edit theirs |

## Plan review

### Round 1

- **How:** one fresh reviewer, Claude Opus, 2026-11-01, on `6ff0f24`. It checked the index's claims against
  `index.zip` and the archives, opened with `zipfile`, and the Kit facts against an Isaac Sim 5.1 install; nothing
  was run. Lenses bridge-security, kit-main-thread and harness-integrity found nothing. Not checked: Kit's C++
  comparison of targets (the manual, K7, stands for it), and the headless `--enable` fetch and the `registries/2`
  index on 6.2, which only step 1 shows (the plan has a fallback for each).
- **Verdict:** approved once the minors are fixed or answered, with no second round: no blocker, no major, six minors.
- **Now:** P1 to P6 are fixed in this plan, and the scripts in the appendix and the scratch folder are the same. The
  reviewer's verdict is approved; the owner calls, Q1 to Q8 and improvements 1 to 6, wait for the maintainer, so
  `status` stays `draft` until the maintainer approves.
- **Approved:** serionist, 2026-11-01: Q1 to Q8 as recommended, Q2 once the experiment holds; improvements 1 to 5
  taken and applied above, 6 left.

| # | Sev | Finding | Status |
|---|---|---|---|
| P1 | minor | C3 named five texts; eight, in five files, end with `install_command()`: `capture_viewport`'s and `inspect_prim`'s size warnings and `start_recording`'s warning too, which a registry user on an older bridge meets | fixed: C3, the Design's third point, Q6 and step 5 name all eight, and step 5 their tests (`test_tools.py` 796, `test_tools_camera.py` 266 and 307, `test_client.py` 695, `test_server.py` 91) |
| P2 | minor | E1's "the probe's path is under `extcache`" fails on a working run: Kit installs a registry's extension as a link in `/app/extensions/registryCache` (`${data}/exts`) to its download (`cache.py` 136-148) | fixed: the run adds `--/app/extensions/registryCache=<scratchpad>/101/extinstall`; E1 passes on the log's `creating a link: <extinstall>/... -> <extcache>/...` line and the probe's real path, which `probe.py` now prints with `registryCache` |
| P3 | minor | The set-up could edit Kit's user config (a search path removed) and never restore it; the window's runs had no undo; step 1 didn't wait for the maintainer | fixed: the experiment never edits the user config, and a competing copy in the probe's first line stops the run; "Undoing it" lists the window's two persistent leftovers and their undo; step 1 shows the start command and waits for the maintainer's yes |
| P4 | minor | E4 needed CI's artifact before the PR exists, and the script re-zipped a folder, so Kit never installed the real archive | fixed: `local_registry.py --archive <zip>` copies the release's zip unchanged (`--target-kit` rewrites only its toml) and reads the toml, readme and images from inside it; E1 to E3 use `git archive`'s zip of `67a5069`, E4 the zip `release.py archives` makes locally; the three scratch registries are rebuilt that way |
| P5 | minor | Q7's addition made line 114 about 150 characters: wrapped, AGENTS.md has 151 lines and the gate fails, while Risks said resolved | fixed: Q7 gives the exact line, 110 characters, in place of line 114, and says the door starts with the first release that carries the archives; Compatibility, Docs and Risks follow |
| P6 | minor | `docs/releasing.md` step 1 and `release.yml`'s comment list where versions live, and miss the extension README's pin | fixed: the Docs table names releasing.md's step 1, and a row lists the comments the change makes stale: `release.yml` (1-5, 42-44, 56), `ci.yml` (106-108), `gate.py` (85-87, `plugin_versions`), `release.py`'s usage |

**Refuted:**

- Q6 changes the tool contract: no; `golden.py` strips prose, and every output schema is a string.
- The target breaks the version checks: no; the gate, `release.py wheel`, `test_bridge_token` and `extension_version`
  read `package.version`, and `version_from_ext_id` gets `<name>-<version>` (K3).
- The target is wrong or unsafe: no; `["107.0"]` is "107 or later" under K7, and the crawler keeps targets above its
  own Kit and an explicit target over `writeTarget` (R10).
- One archive isn't enough, or the extension's folder is optional: no (R9, R7).
- The crawler may not find `extension/`: no; it walks the whole tree, so 0.2.x to 0.3.0 will be listed once the topic
  is set (improvement 5 drops the hedges).
- CI can't build the archives on a pull request: it can; `git archive HEAD:<path>` works on the shallow merge
  checkout, and `release.py` is standard library under `--no-project`.
- Also checked and held: step 10 is finish-work; the `%2B` path; the writing rules; the new door is raised under
  Compatibility and in Q7.

**Improvements.** Each was marked in the plan; the taken ones are applied, their marks gone.

| # | Improvement | Recommendation | Answer |
|---|---|---|---|
| 1 | Cut E2 as a run of its own: 5.1 would run three times (E2, step 2, step 10), and its case follows from K1, K7, K4 and R10 (Tests) | Take: no separate driver swap for E2; one 5.1 session at finish-work (step 10), the folder install with the target, which needs the dev server's NVIDIA driver swapped to 580 and back. Deletes (I1) | Taken (2026-11-01) |
| 2 | Drop the "three files byte for byte equal" check: one function makes all three, so it can't fail | Take: deletes (I2) | Taken (2026-11-01) |
| 3 | Drop `ci.yml`'s `extension` artifact, now that E4 builds the zip locally (P4) | Take: deletes (I3) | Taken (2026-11-01) |
| 4 | Step 2's live check also reads `get_sim_state` without a `note`, from the folder install: the live suites never read `extension_version` | Take: keeps (I4); declining deletes it | Taken (2026-11-01) |
| 5 | Remove the hedges that the crawler may not find the folder (Q1, the Design's alternatives, Risks): the old releases will be listed | Take: deletes (I5) | Taken (2026-11-01) |
| 6 | Before the topic, attach the crawler-named archive with the 107.0 target to v0.2.0 to v0.3.0, so the crawler lists them from assets with the floor and offers Kit 106 none | Leave: published releases stay as they are, and the old versions' listing without a floor is harmless, since Kit 106 isn't supported. Put to the maintainer as Q4 (c) | Left: published releases stay as they are, and the old versions' listing without a floor is harmless, since Kit 106 isn't supported (Q4 (c) declined, 2026-11-01) |

## Appendix: the experiment's scripts

Standard library only. `local_registry.py` reads a release's zip and writes only under the registry folder; run it
with `python -I` from the folder that holds it. `probe.py` only reads Kit's state and prints it.

`local_registry.py`:

```python
"""Build a one-extension Kit registry in a folder from a release's zip, shaped as the community crawler writes it (#101).

Usage: python -I local_registry.py --archive <zip> <registry folder> [--target-kit 107.0] [--repo owner/name]

The zip is the release's: `git archive --format=zip --prefix=ovmcp.bridge/ HEAD:extension/ovmcp.bridge`, as
release.yml makes it today, or `tools/release.py archives` once it exists. It is copied unchanged to
<registry>/3/archives/<owner>-<name>-linux-x86_64-v<version>.zip; --target-kit rewrites only its
config/extension.toml, for a tree without the target, and copies every other entry as it is. The index,
<registry>/3/index.zip, holds one entry built from the toml, readme and images inside the zip, and the images go to
resources/, as the crawler does. Standard library only; it reads the zip and writes only under the registry folder.
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
TOML = f"{NAME}/config/extension.toml"
CRAWLER_KIT = "106.4.0+release.156974.9321c814.gl"  # what the crawler's entries record today

parser = argparse.ArgumentParser()
parser.add_argument("--archive", type=Path, required=True)
parser.add_argument("registry", type=Path)
parser.add_argument("--target-kit")
parser.add_argument("--repo", default="serionist/omniverse-mcp")
args = parser.parse_args()

with zipfile.ZipFile(args.archive) as source:
    outside = [n for n in source.namelist() if not n.startswith(f"{NAME}/")]
    if outside:
        raise SystemExit(f"entries outside {NAME}/, which Kit would name after a temp folder: {outside[:3]}")
    toml_text = source.read(TOML).decode("utf-8")
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
archive = root / "archives" / archive_name
if args.target_kit:
    with zipfile.ZipFile(args.archive) as source, zipfile.ZipFile(archive, "w") as copy:
        for info in source.infolist():
            copy.writestr(info, toml_text.encode("utf-8") if info.filename == TOML else source.read(info))
else:
    shutil.copyfile(args.archive, archive)
same = archive.read_bytes() == args.archive.read_bytes()

# The entry, as the crawler writes one: the toml's package, the readme inlined, and its own fields.
with zipfile.ZipFile(archive) as z:
    names = set(z.namelist())
    for key in ("readme", "changelog"):
        if key in package and f"{NAME}/{package[key]}" in names:
            package[key] = z.read(f"{NAME}/{package[key]}").decode("utf-8")
    for key in ("icon", "preview_image"):
        if key in package and f"{NAME}/{package[key]}" in names:
            data = z.read(f"{NAME}/{package[key]}")
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
print(f"{package_id}: {root / 'index.zip'}, {archive}")
print(f"the archive is {'the zip unchanged' if same else 'the zip with only its extension.toml rewritten'}")
print(f"registry url for Kit: {args.registry.resolve().as_posix()}")
```

`probe.py`, which Kit runs with `--exec`:

```python
"""Kit runs this with --exec (#101): what Kit sees of ovmcp.bridge in its registries, and where the enabled copy is."""

import json
import os

import carb.settings
import omni.kit.app

manager = omni.kit.app.get_app().get_extension_manager()
settings = carb.settings.get_settings()
print("OVMCP-PROBE registries:", json.dumps(settings.get("/exts/omni.kit.registry.nucleus/registries"), default=str))
print("OVMCP-PROBE registryCache:", settings.get("/app/extensions/registryCache"))
enabled = manager.get_enabled_extension_id("ovmcp.bridge")
path = manager.get_extension_path(enabled) if enabled else None
# A registry install is a link in registryCache to Kit's download cache: the real path says where it came from.
print("OVMCP-PROBE enabled at start:", enabled, path, os.path.realpath(path) if path else None)
manager.sync_registry()
for found in manager.fetch_extension_versions("ovmcp.bridge"):
    print("OVMCP-PROBE version:", json.dumps(found, default=str))
print("OVMCP-PROBE solve:", manager.solve_extensions(["ovmcp.bridge"], add_enabled=False, return_only_disabled=False))
```

`run_registry_experiment.py`, which ran E1 and E3 in Isaac Sim's Python (Results, above, says how it differs from
the flags):

```python
"""Step 1 of the #101 plan: Isaac Sim headless, with ovmcp.bridge only in a local registry, on a port of its own.

Usage: python run_registry_experiment.py <registry folder> <work folder> <stop file> [port]

- No extension folder is added: the bridge can come only from the registry, which local_registry.py built.
- Kit's download cache (cachePath) and the folder it links installs into (registryCache) go under <work folder>, as
  extcache/ and extinstall/, so nothing lands in Kit's own folders; delete <work folder> afterwards.
- The registry is added after start, on the non-persistent key, the way the Extensions window adds one (it writes the
  list, then queues REGISTRIES_CHANGED_EVENT), so Kit's user config isn't changed.
- Then the probe: what Kit sees of ovmcp.bridge, the solver's answer, an enable through the extension manager (the
  same solve and pull as --enable, which is not passed: a refusal at start could end Kit before the probe prints),
  and where the enabled copy really lives. Each line starts OVMCP-PROBE; the last says whether it came from the
  registry.
- RUN_ISAAC_READY once it serves; it exits when the stop file appears.
"""

import json
import os
import socket
import sys

registry, work, stop_file = (os.path.abspath(a).replace("\\", "/") for a in sys.argv[1:4])
port = int(sys.argv[4]) if len(sys.argv) > 4 else 8212
NAME = "ovmcp-test"
REGISTRIES = "exts/omni.kit.registry.nucleus/registries"
EXT = "ovmcp.bridge"

# A Kit app already on the port keeps it: this run's bridge would log "Failed to start server", and get_sim_state would
# answer from the other Kit. Refuse before starting.
try:
    with socket.create_connection(("127.0.0.1", port), timeout=1):
        sys.exit(f"port {port} is taken, by another Kit app's bridge or another program: stop it, or pass another port")
except OSError:
    pass

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp(
    {
        "headless": True,
        "width": 1280,
        "height": 720,
        "extra_args": [
            f"--/exts/omni.kit.registry.nucleus/cachePath={work}/extcache",
            f"--/app/extensions/registryCache={work}/extinstall",
            f"--/exts/{EXT}/port={port}",
        ],
    }
)

import carb.settings  # noqa: E402
import omni.kit.app  # noqa: E402
import omni.usd  # noqa: E402


def probe(label, *values):
    print(f"OVMCP-PROBE {label}:", *values, flush=True)


def plain(value):
    return json.dumps(value, default=str)


settings = carb.settings.get_settings()
manager = omni.kit.app.get_app().get_extension_manager()
probe("kit", omni.kit.app.get_app().get_kit_version())
probe("registryCache", settings.get("/app/extensions/registryCache"))
probe("cachePath", settings.get("/exts/omni.kit.registry.nucleus/cachePath"))

enabled = manager.get_enabled_extension_id(EXT)
probe("enabled at start", enabled, manager.get_extension_path(enabled) if enabled else None)
if enabled:
    probe("WARNING", "a local copy is enabled at start: this run proves nothing about the registry")

tree = settings.get_settings_dictionary("")
before = [{"name": r.get("name", ""), "url": r.get("url", "")} for r in tree.get(REGISTRIES, [])]
probe("registries before", plain(before))
tree[REGISTRIES] = [*before, {"name": NAME, "url": registry}]
omni.kit.app.queue_event("omni.kit.registry.nucleus.REGISTRIES_CHANGED_EVENT")
for _ in range(20):
    app.update()
after = [{"name": r.get("name", ""), "url": r.get("url", "")} for r in tree.get(REGISTRIES, [])]
probe("registries after", plain(after))

probe("sync_registry", manager.sync_registry())
versions = manager.fetch_extension_versions(EXT)
for found in versions:
    probe("version", plain(found))
probe("solve", plain(manager.solve_extensions([EXT], add_enabled=False, return_only_disabled=False)))

if not enabled:
    probe("enable", manager.set_extension_enabled_immediate(EXT, True))
    if not manager.get_enabled_extension_id(EXT):
        # The enable didn't fetch it: pull the registry's version by its id, then enable again.
        for found in versions:
            ext_id = found.get("id") if isinstance(found, dict) else None
            if ext_id:
                probe("pull", ext_id, manager.pull_extension(ext_id))
                probe("enable after pull", manager.set_extension_enabled_immediate(EXT, True))
                break
for _ in range(10):
    app.update()

enabled = manager.get_enabled_extension_id(EXT)
path = manager.get_extension_path(enabled) if enabled else None
real = os.path.realpath(path).replace("\\", "/") if path else None
probe("enabled now", enabled, path, real)
probe("from the registry", bool(real and real.lower().startswith(f"{work}/extcache".lower())))

omni.usd.get_context().new_stage()
for _ in range(10):
    app.update()
print("RUN_ISAAC_READY", flush=True)

while app.is_running() and not os.path.exists(stop_file):
    app.update()

print("RUN_ISAAC_STOPPING", flush=True)
if manager.get_enabled_extension_id(EXT):
    manager.set_extension_enabled_immediate(EXT, False)
for _ in range(5):
    app.update()
app.close()
```
