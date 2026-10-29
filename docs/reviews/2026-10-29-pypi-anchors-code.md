---
subject: "Leave the README's in-page links for PyPI to prefix (#62)"
base: main (ee5bca4)
head: 7b2e2f6
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; every claim checked against the code)
verdict: clean
---

# Review: PyPI's in-page links

Read from the diff and each touched file in full, with `README.md`, `docs/releasing.md` and `ci.yml`. No findings;
three improvements taken in `a962b8e`, on which the gate passed again.

Refuted, each from the code:

- **Removing the substitution loosens a check:** it was a build-time rewrite; the change only adds a refusal.
- **The substitution could come back unseen:** `ci.yml`'s package job runs `tools/release.py wheel` on every PR, and
  `_PREFIXED` refuses `](#user-content-...)`.
- **`_RELATIVE` now flags the in-page links:** both its link forms exclude `#`.
- **Another substitution turns `](#troubleshooting)` into a GitHub URL:** the link and `href` patterns exclude `#`.
- **The new test cases pass without the change:** neither `_RELATIVE` form matches a `#` target, so both fail without
  `_PREFIXED`.
- **The links name headings that don't exist:** `## Troubleshooting` and `### The bridge` are in `README.md`.
- **`docs/releasing.md` had to move:** it never described the wheel's README check (but see the third improvement).

Improvements:

- **`tools/release.py`'s usage text** names the new refusal: taken.
- **`_PREFIXED` also catches a titled link and a reference definition,** as `_RELATIVE` does: left: nothing writes
  either now that the substitution is gone, and the README's two in-page links are plain.
- **`pyproject.toml`'s comment said PyPI prefixes links "as GitHub does":** GitHub keeps `href="#x"` and maps it on
  the way to the heading: taken, it now says `#x` lands on its heading on both.
- **`docs/releasing.md` step 5** checks that the in-page links land, which no automated check sees: taken.

Not covered: the tool-contract, Kit main-thread, bridge-security and compatibility lenses, with no code in their scope.

## Checks

`uv run tools/gate.py full` passed on `7b2e2f6`: 962 passed, 95.41%. A wheel built from it carries
`](#troubleshooting)` and `](#the-bridge)`; `tools/release.py wheel` passes it and refuses the 0.2.1 wheel.
