---
subject: "List ovmcp.bridge in Kit's community extension registry (#101)"
base: main (677849c)
head: 1599df8
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus, read only; the coordinator answered the findings and the improvements"
verdict: needs-fixes
---

# Review: List ovmcp.bridge in Kit's community extension registry

Read from the branch's diff against `main`, 32 files and about 1,380 added lines, most of them the plan. The reviewer
checked the release pipeline, the one-way door, the `install_advice()` texts and the Kit target against the code and
found them sound. Five minors and no blocker or major, so no second round. Four minors fixed in `5db61a8` and the PR
draft; one left.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/SETUP.md`, From Kit's community registry, the Headless Kit bullet; the PR's line | It said turning the extension on "doesn't download it from a registry": E1 saw only a running Kit's `set_extension_enabled_immediate` not download it. A start with `--enable` may download, since Kit's start-up solver fetches from registries (`kit-core.json`, `registryEnabled`), and nobody tried it | fixed in `5db61a8`: SETUP and `docs/ARCHITECTURE.md` say turning it on in a running Kit doesn't download it, and a start with `--enable` wasn't tried; the PR's line the same. Prose: no test fits |
| F2 | minor | `CHANGELOG.md`, Unreleased, Added | A relative link, `docs/SETUP.md#...`: `release.py notes` copies the section onto the GitHub release's page, where it resolves under `/releases/tag/` and leads nowhere | fixed in `5db61a8`: the absolute URL; and `changelog_problems` now refuses a relative link in a release's section (improvement 9), `test_a_release_s_notes_link_only_absolute_urls` |
| F3 | minor | `CHANGELOG.md`, Added | Q7 was approved with "that release's CHANGELOG line says so", and the line didn't say the zips' names now stay: someone scripting their download isn't told | fixed in `5db61a8`: from this release on, the zips' names and their `ovmcp.bridge/` layout stay, and no release's zips are deleted. Prose: no test fits |
| F4 | minor | `README.md`, `docs/SETUP.md` | They say the bridge "is listed", while nothing is until the next release, the topic and a nightly crawl: a reader of `main` in between finds nothing | wontfix: `main` documents the next release, and the listing appears the day after it. SETUP's section now says, in one clause, that the listing starts with the release after 0.3.0 and the crawl after it (`5db61a8`) |
| F5 | minor | `.local/pr-101.md`, Tested by, E4's row | It said "INSTALL, ENABLED and AUTOLOAD worked"; the record had ENABLED on after INSTALL, no record of AUTOLOAD set, and no record of the install warning | fixed: the row says what E4 recorded, INSTALL, then ENABLED on and AUTOLOAD checked by the maintainer, the warning not reported. The plan's E4 row now records AUTOLOAD too (`5db61a8`) |

Refuted, each from the code or the files:

- **The release:** CI's check can't pass while the release's zips differ, since the release builds and checks its
  own at the tag's version in `verify`, which `publish` needs, and `release.py check` ties `extension.toml` to the
  tag. The release attaches only its zips: `folder_problems` refuses any other and names a missing one. The tag is
  quoted and must be `vX.Y.Z`. Both workflows run `release/` from the repo's root.
- **The checks:** every case of `archive_problems` has a test, and PNG goes by suffix, as Kit's window checks.
- **The target:** no version read breaks. `extension_version` and `plugin_versions` read `package.version`, and the
  ext id drops the `+` (K3, E1); steps 2 and 10 answered with no note.
- **The tool contract:** only answer strings changed, `mcp-tools.json` is untouched, and every text uses
  `install_advice()`.
- **Others:**
  - `test_scenario_runs.py`'s CRLF change converts only what git would and still catches a changed file;
  - Isaac Sim 5.1 lists `kit/community`, and its window (1.4.27) shows only PNG remotely;
  - nothing claims a Windows 5.1 run;
  - the one-way door matches Q7: line 114 at 110 characters, AGENTS.md at 150 lines, and the title names the door;
  - the modernization plan's edit is disclosed;
  - the writing rules are kept, and every commit is the maintainer's, ending `Refs #101`.

Improvements, with the coordinator's answers:

1. **`build_archives` resolves its folder,** since git's `-o` runs from the repo's root and Python from the working
   folder: taken in `5db61a8`, `test_the_zips_land_in_the_folder_named_from_any_working_folder`.
2. **`release/` ignored,** where a local run of CI's command leaves its zips: taken in `5db61a8`, as `/release/` at the
   root (checked with `git check-ignore`).
3. **A unit test of the release's own call,** `release.main(["archives", dir, "vX.Y.Z"])`, whose tag path otherwise
   runs first on release day: taken in `5db61a8`, `test_the_release_s_own_call_zips_and_checks_head`.
4. **A stray `assert release.main(["release"]) == 2`** in the registry notes test, moved back to
   `test_the_notes_are_the_section`: taken in `5db61a8`.
5. **"Kit warns first"** in place of "may warn": the window's code shows the popup for every unverified entry (5.1's
   `common.py` 567-589, K5 on 6.2). Taken in `5db61a8`: SETUP, the extension's README, the plan.
6. **The plan's "same bytes"**: `git archive` of a tree stamps the time it runs, so only the files inside match.
   Taken in `5db61a8`: the claim corrected, with no `--mtime`.
7. **The README's pin** counted any pin, so `ovmcp.bridge-X.Y.Z` alone passed while naming no server: taken in
   `5db61a8`, `omniverse-mcp==` alone counts; the gate test case "extension README with only the extension's pin".
8. **A comment on #101 pointing at Q7,** for AGENTS.md's "after the maintainer agrees in its issue": the
   coordinator's, at PR time.
9. **`changelog_problems` refuses a relative link** in a release's section, which would have caught F2: taken in
   `5db61a8`, `test_a_release_s_notes_link_only_absolute_urls`.

## Live run

Each run by the main session, with the maintainer's yes, at port 8212. The plan's Tests section has the detail.

| Run | Kit app | Commit | Result |
|---|---|---|---|
| E1 | Isaac Sim 6.2 headless (Kit 110.4.0), Windows | `67a5069`'s zip, target 107.0 written in | Installed from a local registry shaped as the crawler's; `get_sim_state` 0.3.0 and 0.3.0, no note |
| E3, E3b | the same | targets 999.0, then none | 999.0 offered no version and the solver refused it; no target loaded as E1 |
| E4 | Isaac Sim 6.2 with its window, the maintainer, `--portable-root` | `5953208`'s zip | The listing under THIRD PARTY, *Community - Unverified*; INSTALL, then ENABLED on and AUTOLOAD checked; no note. Found the JPEG preview's placeholder and the missing ☰, both fixed |
| Q9's probe | Isaac Sim 6.2 headless | | Kit's client read the registry's `+105.1` metadata file |
| Step 2 | Isaac Sim 6.2 headless, Windows | `5953208` | Folder install with the target: both live suites, 188 passed, 16 subtests |
| Step 10 | Isaac Sim 6.2 headless, Windows, RTX 5090 | `883f4ee` | Both live suites, 188 passed, 16 subtests; no note |
| Step 10 | Isaac Sim 5.1 (Kit 107.3) in NVIDIA's container, Ubuntu 26.04, driver 580 | `9a22dd0`'s tree | No note; both live suites 187 passed, 1 failed: `test_10_01_spawn_g1` timed out loading the G1 from NVIDIA's asset server. `test_scenarios.py` again on the same Kit: 122 passed. G1 passed in every earlier 5.1 run |

Not shown: the crawler itself, which lists the first release with the zips the day after the topic is set. The
review's fixes changed no code under `extension/`: `5db61a8` changes one sentence of its README.

## Checks

- `uv run tools/gate.py full` on `5db61a8`: 15 checks, 1673 passed, 206 skipped, coverage 96.85%.
- `release.py archives` on the repo, without a tag and with `v0.3.0`: the three zips, checked.
- The wheel, built locally: `check-wheel-contents` and `release.py wheel` pass, the two images inside.
