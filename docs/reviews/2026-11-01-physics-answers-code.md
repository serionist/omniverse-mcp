---
subject: "Say what set_physics_properties and apply_force did in their answers (#104)"
base: main (876caca)
head: 5fcc0ed
date: 2026-11-01
round: 1
tier: "one fresh reviewer on Claude Opus"
verdict: clean
---

# Review: Say what set_physics_properties and apply_force did in their answers

Read from the branch's diff against `main`, 6 files and +186/-20, server-only: the extension has always sent back the
values and the path, and the server didn't show them. The reviewer also read both releases' handlers
(`handlers/simulation.py` at `v0.2.0` and now), `core/force.py` and the tool contract. No confirmed findings.

Refuted, each from the code:
- **An older extension sends no values, so the answer would say "Nothing set":** `v0.2.0` and `v0.3.0` both send
  `mass`, `density`, `friction` and `restitution` back. Anything older has no handshake and is refused.
- **Values that differ from what Kit set:** the handler stores `float(x)` and sends back `x`, and the server prints
  `float(x)`. The checks are `is not None`, so a friction or restitution of 0 shows. A mass or density of 0 reads as
  unset, as USD Physics treats 0.
- **"friction=X (static and dynamic)":** the handler sets both.
- **The applied APIs:** `RigidBodyAPI` and `CollisionAPI` are named only when the call adds them, and `MassAPI` and
  `PhysicsMaterial` whenever their values are set, as TOOLS.md says.
- **`method` for some path:** `physx` and `tensor` come from the handler. A 0.2.0 extension keeps `(method:
  velocity)`, which a test checks.
- **"Nothing set" ought to be an error:** a call with no values is valid and changes nothing. A missing prim is still
  an error first, and the plain text matches `set_prim_transform`'s answer when it changes nothing.
- **The tool contract:** only docstrings changed, which `golden.py` strips. The fixture is untouched.
- **15.1's Verify line:** Phase 15 needs 4.5, which already made RedCube a rigid body, so the answer says
  `applied MassAPI` alone.
- **Made-up answer shapes in the tests:** they use the handler's real `PhysicsMaterial` name and its echoed values,
  and each new test fails on the old code.

Improvements, all taken in the commit after `5fcc0ed`:
- **I1:** TOOLS.md's generic "applies the required APIs" line went; the bullets and the Returns paragraph say it
  precisely.
- **I2:** TOOLS.md's `apply_force` example line is rewrapped at 120.
- **I3:** a test comment over 120 characters is rewrapped.
- **I4:** CHANGELOG ties `method: tensor` to `/physics/suppressReadback`, as the handler does, not to the GPU API
  itself.
- **I5:** 15.3's "the mass still wins" is a note, not a Verify line, since the answer can't show it.

Outside this change, moved to #105:
- `set_physics_properties` with only `restitution`, on a prim with no physics material, binds a new material whose
  friction is never written.
- USD's fallback for unwritten friction is 0, so the body loses PhysX's default friction.
- This predates #104, and the handler is untouched here.

## Live run

On `7590221`, before a rebase that changed only CHANGELOG, on Isaac Sim 6.2 headless (Windows, RTX 5090):
- both live suites passed: 188 tests and 16 subtests;
- the AI scenario run of phase 15 (`20261101-111623`) passed 20 of 20. 15.1 to 15.3 and 15.5 went from FAIL or WARN
  to PASS on the answers alone.

The tensor path's answer is checked by its unit test only; the GPU module didn't run.
