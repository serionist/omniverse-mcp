---
subject: "Put back what RTX writes onto a camera a capture renders through, out of the stage's file (#177)"
base: main (2359c1d)
head: 740ee22
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; a live A/B for the hang; a second round after the approach changed"
verdict: needs-fixes
---

# Review: Keep RTX's exposure writes out of the stage's file

Read from the branch's diff against `main` at `2359c1d` (10 files, about 450 lines) by one fresh reviewer, read only,
against issue #177. There is no plan: the fix is one Kit-free helper and its hooks in `camera_feed.py`. The reviewer
reproduced each finding on usd-core.

Round 1's code authored RTX's two exposure schemas and three `exposure:` attributes in Kit's session layer before a
feed rendered through a camera, which a live probe showed keeps RTX from writing them at the edit target, and lifted
them after.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `exposure.shield`, `camera_feed._lift` | A second feed on a camera (a capture during a recording through it) got no shield, since the first's was there, and the first feed's lift then left it rendering the camera bare | fixed in `9eb1493`: one mark a camera, counted per feed, put back by the last; `test_the_last_feed_through_a_camera_puts_it_back_and_not_before`, `test_a_camera_two_feeds_render_through_is_put_back_by_the_last` |
| F2 | minor | `Shield.lift`, `attribute._session_way_out` | A user's write to one of the three attributes while a shield stood was refused with a wrong reason, or, in the session layer, deleted by the lift | moot in `9eb1493`, which writes nothing; its successor is round 2's M3 |
| F3 | minor | `Shield.lift` | Two shields under one parent the session layer lacked left `over "World" {}` in one order | moot in `9eb1493`; its successor is round 2's M2 |
| F4 | minor | `CameraFeed.__init__` | A constructor that raised after the shield (Kit's texture call raising, `_subscribe`) leaked it | fixed in `9eb1493`: the marks go back when the feed never comes; `test_a_feed_that_never_came_leaves_no_mark` (both cases) |
| F5 | minor | `exposure.ATTRIBUTES` | The three values look like Kit's tonemap settings (`/rtx/post/tonemap/*`), not constants, so a shield could expose a capture differently on other settings | moot in `9eb1493`: values are noted and put back, never authored |
| F6 | minor | the PR text | It should say what the live run couldn't show: Kit 107, two feeds on one camera, the `aim` path | fixed: the PR's Tested by; `test_12dd` now aims the kept feed from the viewport's camera to the scene camera |
| F7 | minor | `tests/test_integration.py` | The new constant sat under `_AIMED_CAMERA`'s comment | fixed in `9eb1493` |

**Refuted:** a lift on a closing stage (`_lift` returns unless the stage is open); a lift on a replaced stage (the
session layer compared); USD off the main thread (`_shield` and `_lift` run from `__init__`, `aim` and `drop` only);
an await between a lift and the next shield (`aim` is synchronous); a double lift; a refused camera; composed
`apiSchemas` list ops; saves and flatten; `delete_prim` on a shielded camera; `hand_back` keeping a feed.

**Improvements:** start the list op from the spec's copy (taken, then moot); one registry for F1 to F3 (taken, as
`Marks`); the shield in `camera_feed.py`'s and `docs/ARCHITECTURE.md`'s descriptions (taken).

**Not covered:** live behaviour, Kit 107, the gate.

## The live A/B, and the change of approach

The live suites on a Z-up stage (Isaac Sim 6.2.0, Kit 110.4.0, port 8212), each run on a fresh Kit, with dumps on a hang:

| Run | Extension | Result |
|---|---|---|
| 1 | `740ee22` | Kit stopped answering at `test_14_04`; main thread in `omni.usd`'s `LayersLegacy::resolvePrimPathsReferencesStatic` under `UsdContext::removeHydraSceneDelegate`, from Kit's update, no bridge code on the stack |
| 2 | `740ee22` | stopped answering at `test_15_07`; `omni.usd`'s `LayersLegacy::resolvePrimPathsReferencesStatic` again |
| 3 | `main` (`2359c1d`) | 217 passed |
| 4 | `740ee22` | 218 passed |

`main` had passed some fifteen full runs that day with one hang. Writing to the session layer while a hydra texture
renders the camera looked like the trigger, so `9eb1493` writes nothing while a feed renders: `Marks.take` notes what
the edit target holds of a camera before a feed first renders through it, RTX writes as it does, and `Marks.let_go`
puts the camera back when the feed's render product is deleted, as the bridge already deletes its render products (the
kept feed released, a recording stopped, Kit's Save, the next open stage for a leftover).

## Round 2

- **Where:** `740ee22..9eb1493`, the new approach, by a fresh reviewer, read only, with round 1's findings.
- **Verdict:** clean once its four minors were fixed or recorded; fixed in `2c3c99b` and checked in this session.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| M1 | minor | `Marks.let_go`, `CameraFeed._let_go_marks` | Put back by identifier: `open_scene` of the same file within the kept render's 30 s freed the old root layer and the new one took its identifier, so the mark was put back through a dead handle, which raised, and the feed's other marks stayed held | fixed: put back only when the mark's own layer is alive and in the stage, each mark let go on its own; `test_a_mark_on_a_file_opened_again_is_dropped_without_an_error` (fails without it) |
| M2 | minor | `Marks.take`, `Mark.restore` | Two cameras under a parent the edit target lacked (a stereo pair under a referenced head): the second mark, taken after RTX wrote the parent's over, didn't list it, so one release order left `over "Head" {}` | fixed: a mark shares the absent parents of the marks held on its layer; `test_a_parent_two_marked_cameras_share_goes_whichever_is_put_back_last` (both orders; fails without it) |
| M3 | minor | `Mark.restore` | A value the user set on the three attributes while the render was kept is taken back with it (lost on a save through `without_kept_feed`) | recorded: `docs/TOOLS.md`'s read-only row and the CHANGELOG say so; a second snapshot after the first frame was left for a case that asks |
| M4 | minor | `CHANGELOG.md` | It said the writes go "before a save", but a save during a recording keeps its camera's, as it keeps its render product | fixed: the line says so |

Round 1's F1, F4 and F7 confirmed fixed by their tests; F2, F3 and F5 moot under the new approach, with M3 and M2
their successors.

**Refuted:** each path that ends a feed puts its marks back once (`remove_render_product` swaps the list out); nothing
is put back while the stage isn't open; nothing while a counted feed still renders the camera; `restore` exact for a
camera defined in the edit target, another layer or the session layer, for an `apiSchemas` absent, prepended and
appended or explicit, for attributes absent, declared without a value or blocked, for absent ancestors, in a sublayer
edit target too; Kit's own Save and the bridge's saves put the marks back before the file is written; taking a mark
only reads.

**Improvements:** an `_on_saving` unit test (left: covered through `discard`, and live by `test_12dd`'s release);
`_tear_down_at_once`'s message for a failed put-back (taken: each put-back now logs its own warning).

**Not covered:** whether removing the specs at release can meet round 1's hang (the live runs below say not, in three
runs); whether RTX writes again onto a camera the user's viewport renders after the put-back; Kit 107. An edit target
changed between two feeds through one camera gives two marks on two layers, the first put back while the second feed
renders: accepted, as no tool changes the edit target.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, on a Z-up stage, each run on a fresh Kit:

- **The first version, `740ee22`:** three runs, Kit stopped answering in two (above); a capture through a fresh
  camera (`test_12dd`) left the root layer as it was, with the shield in the session layer.
- **The marks, `9eb1493`:** 218 passed, twice, `test_12dd` among them; #157's suites on top of it (`f6f13a1`), 221
  passed.
- **Round 2's fixes, `2c3c99b`,** with #157 on top (`16c1db3`): the integration suite passed whole, `test_12d`,
  `test_12dd`, #157's sweeps and the agents test among them; the scenario suite passed to `test_05_02`, then failed
  test after test from `test_05_03` until the run was stopped for the machine's low memory (other sessions' Isaac Sim
  apps and WSL held some 21 GB, mine 8.5 GB after the agents test's warehouse), before pytest gave a reason.

**What it couldn't show:** Kit 107; whether RTX writes again onto a camera the user's viewport renders after the
put-back.
