---
subject: "Let apply_force push articulation links again, and refuse a body fixed to the world (#58)"
base: main (765d51c)
head: 5912b5e
date: 2026-10-30
round: 1
tier: standard (one fresh reviewer, Claude; findings checked against the code by the main session, F1 and F2 measured on Isaac Sim 6.2 by its probe)
verdict: clean
---

# Review: Let apply_force push articulation links again, and refuse a body fixed to the world (#58)

Read from the diff of `5912b5e` against `765d51c`, the touched files in full, the plan
(`docs/plans/2026-10-30-articulation-link-force.md`) and its Findings. No blocker or major. Three minors, all fixed;
F1 and F2 were settled by a live probe (Checks), which kept F1's missing-prim half and refuted its Scope half. Two
improvements, both taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/force.py`, `Joints.__init__`, `_body_of` | A fixed joint whose target prim doesn't exist counted as a world anchor: `_body_of` gave None for the missing prim, so the other end went into `_anchored`. Scenario: `delete_prim` on a pallet leaves a crate's fixed joint dangling; PhysX frees the crate, and `apply_force` refused it as held to the world. The reviewer read UsdPhysics's parser as dropping such a joint, and one to a prim that isn't Xformable | fixed in `f00f01c`: a joint whose target doesn't exist joins and holds nothing; `test_a_fixed_joint_to_a_deleted_prim_holds_nothing_and_one_to_a_scope_holds`. The probe measured PhysX: a cube fixed to a missing prim moved as the free one did, and one fixed to a Scope didn't move, so a Scope end stays a world anchor. usd-core 26.11's parser reads both ends as the world (`""`) and drops neither. The quoted message ("joint will not be parsed") is in USD's validators, Kit's `usd_usdPhysicsValidators.dll`, not in its parser `usd_usdPhysics.dll`. So the case stays out of the parser cross-checks, and the comment in `Joints.__init__` says why |
| F2 | minor | `core/force.py`, `Joints` | An end in a kinematic body wasn't an anchor. A base fixed to a kinematic mount answered success and moved nothing, against the plan's Risks row ("errs towards a refusal") | fixed in `ac7f05e`: `held_to_world` counts a kinematic end as ground. `articulation_holding` doesn't: it keeps the parser's reading, which lists the mount among the articulated bodies. `test_a_kinematic_mount_holds_what_is_fixed_to_it`; the probe measured a cube fixed to a kinematic mount, unmoved by 10 N s |
| F3 | minor | `tools/simulation.py`, `docs/TOOLS.md`, `plugin/skills/simulate/SKILL.md`, `CHANGELOG.md` | "Moves as a whole: its speed changes by the impulse over the robot's mass" holds only for a floating robot touching nothing. A fixed-base arm's link turns about its joints, and on the ground friction takes some of the push (the plan's E10: 98.3 of 100 N s within the step) | fixed in `ac7f05e` (TOOLS.md) and `b574bd4` (the rest): a floating robot touching nothing changes speed by the impulse over its whole mass; a fixed robot's link turns about its joints, and on the ground friction takes some of the push |

Refuted, each from the code, the stubs or the plan's measurements:

- **The setting's read:** `carb.settings.get_settings().get_as_bool(path)` is in Kit 107.3's and 110.4's
  `carb/settings/_settings.pyi` (line 93), read in the handler on Kit's main thread; an unset path gives false.
- **The push's window:** a push while paused lands at the next step (the plan's E4 and E11), and the live measure
  plays from a pause, so its window begins with the push's step.
- **The timeline's time against physics time:** one update steps physics once here (the plan's s1: 10 updates,
  0.1667 s), and s9 matched the tensor API's momentum to 1e-5 over the same kind of window.
- **A pass with the bug:** on `main`'s bridge, `test_15_11` and `test_15_14` get the link refusal, and `test_15_15`
  and `test_15_16` the old message, so each fails there.
- **A link still refused:** `refusal` has no articulation case left, and `fixed_refusal` runs only when
  `held_to_world` names a base.
- **The main thread:** the handler reads USD and calls PhysX in its own task on Kit's main thread, with nothing
  awaited between the pose and the push; `Joints` reads the stage there too.
- **The refusal order:** stopped, the Direct GPU API, disabled, kinematic, not held by PhysX, then the joints; a unit
  test pins each step.
- **A one-way door:** only the description moved; `tests/fixtures/mcp-tools.json` is unchanged and
  `tests/test_contract.py` passes; the route, request and answer keys stay.
- **AGENTS.md's cap:** 149 lines. The Traps row came in with two lines of the live suites' bullet joined into one of
  119 characters.
- **The Franka's hand:** `test_15_16` checks only that the push on `panda_hand` succeeds. That the link beside a fixed
  base moves is checked exactly on the fixed pair (`test_15_15`), and the plan's E6 measured the hand.

| Improvement | Answer |
|---|---|
| The Direct GPU API's refusal names the setting and how to turn it off: a stage opened after a GPU device can keep it on with a CPU scene, where the refusal told someone already on the CPU to move there | taken in `ac7f05e`, as a message change only: a push with the setting on stays refused, since it is unmeasured there |
| Build `Joints` only after the cheap refusals pass | taken in `ac7f05e`: `fixed_refusal` is asked after `refusal` lets the push by |

**Not covered:**

- the live suites on the fixes: pending, the main session re-runs them on the fixed bridge;
- the bridge's security: no route, token or HTTP change;
- Isaac Sim 5.x, which can't run on this machine;
- the Direct GPU API live: its refusal is unit-tested only, since toggling `/physics/suppressReadback` changes how
  PhysX runs for the whole Kit.

## Live run

On `5912b5e`, before the fixes: Isaac Sim 6.2.0 headless, a fresh Kit at port 8212 with the branch's extension, both
suites in full: 149 passed in 111.24 s.

| Test | Measured |
|---|---|
| `test_15_11` | 100 N s on the G1's pelvis, 34.24 kg: 2.9260 units/s along X against 2.9209 expected, 0.17% off |
| `test_15_14` | 10 N s on one cube of a 10.0 kg pair: 1.0000 units/s (1.0000) |
| `test_15_15` | in 30 steps the fixed base moved 0.00e+00, the link it holds 0.074 |
| `test_15_16` | passed: the Franka's `panda_link0` refused as held to the world, its `panda_hand` pushed |
| `test_15_06` | 10 N s on 5 kg: 2.000 units/s; 10 N: 0.0333 for one step, as before |

## Checks

- **The probe for F1 and F2** (`e58/s12_dangling.py`, outside the repo), on Isaac Sim 6.2.0 headless at port 8212.
  It pushed four lone 5 kg cubes, gravity off, with today's `IPhysxSimulation` call: 10 N s along X at the centre of
  mass, then 10 frames. PhysX held every cube (`ret_val` true).

  | Cube | Momentum | Travel |
  |---|---|---|
  | fixed to a missing prim | 0 to 10.0 | 0.333 |
  | fixed to a Scope | 0 to 0 | 0 |
  | fixed to a kinematic mount | 0 to 0 | 0 |
  | free | 0 to 10.0 | 0.333 |

- **UsdPhysics's parser in usd-core 26.11:** a fixed joint whose body0 is a missing prim, and one whose body0 is a
  Scope, both parse with `body0` `""`, are listed among their articulation's joints, and print no warning.
- **The gate** on `12f71df`: `uv run tools/gate.py full` passed, 15 checks, 1004 tests, coverage 95.49%.
