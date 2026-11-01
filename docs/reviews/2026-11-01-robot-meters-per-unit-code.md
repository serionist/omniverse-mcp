---
subject: "Scale a robot file of other units to the stage, and convert its physics values (#112)"
base: main (84acfa5)
head: de975c8
date: 2026-11-01
round: 1
tier: "two fresh reviewers on Claude Opus, the lenses split; no blocker or major, so no refuter"
verdict: needs-fixes
---

# Review: Scale a robot file of other units to the stage, and convert its physics values

Read from the branch's diff against `main` at `84acfa5`, after the branch was rebased onto it, by two fresh reviewers,
read only, each with its own lenses:

| Reviewer | Lenses |
|---|---|
| (a) | implementation, kit-main-thread, bridge-security, compatibility, simplicity, on the extension |
| (b) | plan-and-intent, tool-contract, tests, docs-freshness, harness-integrity |

The extension's reviewer checked edge cases with scratch scripts on usd-core 26.11; the tests' reviewer checked that
`test_27c`'s check of Kit's assembler could fail. Nothing ran in Kit. Four minors and no blocker or major, so no second
round. The fixes are on the branch after `de975c8`.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `core/robot.py` `_writes` | A converted default written into the stage's layer hid samples that weren't written. A metre file on a centimetre stage, a drive's `targetPosition` with a default of 0.02 and samples of 0 at 0 and 10: the samples didn't change, so they were skipped, and the default, 2, went into the stage's layer, where a stronger layer's default beats the file's samples at every time. The target read 0 at 0, 5 and 10 before and 2 at all three after. The same when the samples' layer is in the stage's units and the default's isn't | fixed in `6a2d370`: a default written takes the samples beside it, changed or not; `tests/test_robot.py` `test_a_default_written_takes_the_samples_beside_it_changed_or_not`, which fails before it |
| F2 | minor | `core/robot.py` `convert_units`, `_value_units` | A value reached through an inherits or specializes arc was converted twice when the stage's root layer authors no `metersPerUnit`, which USD reads as centimetres. `/Bot/Arm` specializes `/Bot/Base`, whose `physics:upperLimit` is 0.5: Base is converted first and gets 50 in the stage's layer; USD implies the arc into the stage's layer stack, so Arm resolves 50 through a node that isn't the root, whose layers say no units, falls back to the robot file's metres, and ends at 5000. Rare | fixed in `6a2d370`: every write comes after every read (I1), and a value of the stage's own layer stack, through any arc, is in the stage's units; `tests/test_robot.py` `test_a_value_reached_through_a_specializes_arc_is_converted_once`, which fails before it |
| F3 | minor | `tests/test_robot_handler.py`, the `table` fixture | Two inline `# type: ignore[attr-defined]`, the first in the repo. AGENTS.md allows no new ignore, and the gate doesn't catch an inline one | fixed in `54c4c33`: the fake modules are built with `tests/test_scene_handler.py`'s `_module`, as every other handler test builds them |
| F4 | minor | `tests/test_integration.py` `_kit_leaves_the_force_arm`, `_RESOLVE_UNITS` | `test_27c`'s check that Kit's assembler doesn't convert a value again couldn't fail: Kit's resolve layer goes in as the root layer's first sublayer, weaker than the root layer, which holds the converted values, so a second conversion never changes what is read. The plan's Risks row said `test_27c` checks it | fixed in `ebf63d3`: the script lists the values Kit wrote into its layer, and the test asserts none of the converted ones is among them; the op checks and the printed acceleration stiffness stay. Live only |

**Refuted,** each from the code or a scratch check:
- **The extension:** the scale before an inverse op departs from Kit (Kit's own test asserts the last op is the
  inverse one after a resolve). The angular acceleration departure is wrong: right physically, since PhysX scales
  acceleration gains by the joint's inertia, and the table contradicts itself (its `physxForce:torque` acceleration
  entry and its linear acceleration gains drop distance); applied by full match to the eight angular gain names only,
  with `units.py`'s own test of the drive's type. Each factor: inertia, density, the drives, max forces, limits, with
  degrees and seconds untouched. Per-value units, each right with the stage's units authored: variants, sublayers,
  references inside variants, payloads, inherits and specializes, a reference with a layer offset, a value in the
  stage's own layer. Value clips left and listed; instance proxies listed only when they would change. The cleanup
  leaves only the parent spec that was there before. Kit converting the force arm again: Kit resolves only from its
  own reference commands and the stage's record on open, and `create_robot` uses neither. Kit 107 has every USD call
  the core makes, and the same `units.py`. The main thread: synchronous on Kit's loop, 0.58 s on usd-core for 12,000
  prims, and only when the units differ. `functools.cache` across tests: each test loads the module afresh.
- **The tests:** the fake table's 18 entries equal NVIDIA's; the 22 probe values equal the probe's; 12 converted is
  P5's 13 less the slide's lower limit of 0. `test_27c` passing with both stages in metres, arms that don't sag, or
  the scale alone. The table's ×10^4 on the twin would fail it. The cleanup order and the stages' up axis. The tool
  contract unchanged; an older extension prints nothing. Harness, docs and writing: clean.

**Improvements,** all taken:

| # | What | Answer |
|---|---|---|
| I1 | `convert_units` computes every write before making any, which fixes F2 and the same trap for any arc | taken, `6a2d370` |
| I2 | Without the PhysX schema's table, the answer names only camera distances and Kit's camera rules; the line of values left names splines and types that don't multiply too | taken, `2bf31b7`; `tests/test_tools.py` |
| I3 | `docs/TOOLS.md`'s "Left as they are" names value clips | taken, `2bf31b7`, with splines |
| I4 | Test comments cite files outside the repo: point them at the plan's P1 and P2 | taken, `6a2d370`, `54c4c33` |
| I5 | Edge-case tests: a held op that isn't uniform, a value from value clips, a blocked sample | taken, `6a2d370`, `2bf31b7` |

## Live run

Run by the session on its own headless Isaac Sim 6.2.0 (Kit 110.4.0+feature.386251.187cf21b.gl), Windows, at port
8212. Outputs in the session's scratchpad, `112/`:

| Step | Stage | Extension | What ran | Result | File |
|---|---|---|---|---|---|
| 1 | Z-up | `de975c8` | `test_27`, `test_27b`, `test_27c`, `test_30` | 3 passed, 1 failed (`test_27c`) | `112-live-Z.txt` |
| 2 | Y-up | `de975c8` | the same | 3 passed, 1 failed (`test_27c`) | `112-live-Y.txt` |
| 3 | Z-up, a new stage made for it | `de975c8` | both live suites whole | 194 passed, 1 failed (`test_27c`) | `112-live-suites.txt` |
| 4 | its own, metres and centimetres | `2bf31b7` | `112-accel-probe.py`: test_27c's robot and three variants, PhysX's values read once settled | exit 0 | `112-accel-probe.out.txt` |

A first run of the probe, at `7e09826`, failed in its own reader, which floated `xformOpOrder`'s tokens; it changed
nothing in Kit.

- **The force arm** matched across the stages to 7 digits, 0.168476 rad on both, on either suite axis: its scale,
  its density over a scaled collider and its force drive's converted gains behave as the metre robot's.
- **The acceleration arm** sagged 0.16905 rad on the metre stage and 0.26172 on the centimetre one, 1.55 times, and
  failed `test_27c`'s 2%. Kit's assembler, run after, converted its stiffness by its table, 1.5 to 15,000.
- **The probe** (the plan's A1 to A5): PhysX holds the same acceleration gains on both stages, 85.94 and 17.19 per
  radian, and the arm's inertia and joint-space inertia 10^4 times on the centimetre one, as they should be; an arm
  with a collider sags the same; with the gains times 10^4, as the table would make them, the arm is held rigid on
  both. From each settled angle, PhysX scales the drive by 0.996 and 1.20 times the joint-space inertia on the metre
  stage (the gains as authored, and times 100), 0.630 and 0.669 on the centimetre one: a dependence on the stage's
  units inside PhysX, with every input the same in stage terms.
- **The outcome,** in `24abe97`: the gains stay as they are. `test_27c` checks what PhysX holds instead of the
  acceleration arm's sag (the same gains, 10^4 times the joint-space inertia, a sag of more than 0.02 rad on both)
  and prints its sags; the force arm's must still match within 2%. `docs/TOOLS.md` and CHANGELOG say an angular
  acceleration drive in a file of other units isn't shown to behave as in the stage's units. The plan records it.
- **Not yet run live:** the round's fixes and the reworked `test_27c`; the session reruns `test_27c` and both suites
  with the extension from `24abe97`.
- **What it couldn't show:** Isaac Sim 5.x (Kit 107), whose table and physics rules are 6.2's (the plan's K13);
  Linux; USD Composer, which isn't on this machine, so `test_27c` writes its own centimetre stage; a mimic joint's
  gearing, which no test robot has.

## Checks

- `uv run tools/gate.py full` at `24abe97`: 15 checks passed, 1848 tests passed, coverage 97.32%.
