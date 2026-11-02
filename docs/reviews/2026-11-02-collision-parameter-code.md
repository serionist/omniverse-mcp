---
subject: "Add set_physics_properties' collision parameter to the tool contract (#150)"
base: main (6a6982c)
head: 9565c5d
date: 2026-11-02
round: 1
tier: "one fresh reviewer on Claude Opus, every lens; one minor, so no second round"
verdict: clean
---

# Review: Add set_physics_properties' collision parameter to the tool contract

Read from the branch's diff against `main` at `6a6982c` by one fresh reviewer, read only, with every lens, against the
approved plan `docs/plans/2026-11-02-collision-parameter.md`. The code does what the plan says: mass and density first,
then friction and restitution, then `collision`; every refusal before any write; the contract fixture changes only by
the new property. One minor, fixed in `52f670c`, `15ce3cc` after the rebase onto `0cb889c`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `ovmcp/core/collision.py`, `collision_refusal` | the refusal never learnt the call's direction, so `collision=False` got advice for `True`: an Xform root was told to make its shapes colliders one by one, and an inactive prim to be activated first, which would make a prim the user had turned off render and collide | fixed: `collision_refusal(prim, on=)`; for off, an Xform's shapes are named to turn off one by one, and an inactive prim has no collision to turn off; `test_collision.py` tests each wording |

**Refuted:**
- **The older-extension warning fires on a new extension's "had no collider":** `set_collision` always echoes
  `collision`, and the tool warns only when it is missing; the tool test for off without a collider pins the text.
- **A Mesh given a mass and `collision=True` misses its hull:** collision runs last;
  `test_a_mesh_given_mass_and_collision_in_one_call_gets_its_hull` checks the order and `convexHull`.
- **`collision=False` with a friction ends up colliding:** friction applies the API, then `set_collision` turns it
  off; a test covers it.
- **A partial write before a refusal:** the refusal comes before the mass path; the Xform handler test compares the
  root layer's export before and after.
- **An instanceable gprim is refused:** measured, a Cube that is an instance gets no refusal and `applied
  ['CollisionAPI']`.
- **The kinematic exception, and a session layer's `collisionEnabled = false` read back:** both as planned, each with
  its test.
- **`Capsule_1` and `Cylinder_1` refused:** omni.physics' docs (Context7) list Sphere, Box, Capsule, Cylinder and Cone
  as primitive colliders, with no evidence PhysX makes a shape for the `_1` forms.
- **The older-extension warning says "so the prim collides" where `collisionEnabled` is authored false:** needs an
  outdated extension and an authored false at once, and its first sentence still tells the agent what to do.
- **The local `refusal` shadows `force.refusal`; `test_15_02b` passes friction by name; TOOLS.md's "their count":**
  no change in behaviour, each checked against the code.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Name `collision=True` where agents look: the raycast description, and `create_prim`'s line on meshes under an Xform | taken |
| I2 | Stop the instance search in `collision_refusal` at its first hit, so a refused root with many instances under it doesn't walk them all on Kit's main thread | taken: `next()` |
| I3 | Show the collision clauses in `docs/TOOLS.md`'s Returns, with the older-extension WARNING | taken |

**Not covered:** the gate and CI (the reviewer ran neither; gate full passed on the head); the live suites, run below.

## Live run

On my headless Isaac Sim 6.2.0 (Kit 110.4.0) at 8212, with this branch's extension, each suite run on a fresh Kit:

- `test_15_02d_a_floor_made_a_collider_by_name_holds_a_box_until_its_collision_goes_off` passed: the box's bottom on
  the floor at 0.000; with collision off it fell to -13.56.
- Both live suites: 206 passed on a Z-up stage, 206 on a Y-up stage.
- O4 (`--phases none --outcomes O4`, run `20261102-174127`): PASS, with 8 calls and no `execute_script`, where earlier
  runs made one or two. The agent loaded `simulate`, read the floor's `api_schemas = []`, and called
  `set_physics_properties` with `collision`. The judge found `/World/Floor` a collider with no rigid body and the box
  resting on it after the runner's play.

**A Kit hang, not this change's.** Kit stopped answering in `test_15d_inspect_says_why_segmentation_is_missing` (the
main thread inside `usdrt.population.plugin`) whenever one pytest ran `test_02_01`, `test_04_05` and `test_15_02d`
before the integration suite: 3 times in 3. The rest of the order matters too: the suites' own order, the pre-run
without `test_15_02d`, and `test_15_02d` alone all passed. On `main`'s extension, the same order with `test_15_02d`'s
collider made and turned off by `execute_script` hung the same way. The handler makes the same USD calls (the
Collision API, `collisionEnabled`) with no frame waits, so the hang is in what the scene does, not in this parameter,
and `main` reaches it already. It takes all of: `test_04_05`'s physics on the stage (a physics scene, a ground
collider, a rigid cube), `test_15_02d`'s floor collider turned off between two plays, its prims deleted, a new stage,
then a capture with segmentation. A playing stage alone doesn't do it: on `main`, `test_02_01`, `test_04_05` and
`test_05_01` before the integration suite passed 74 of 74. Thread dump kept for an issue, on the maintainer's word.
