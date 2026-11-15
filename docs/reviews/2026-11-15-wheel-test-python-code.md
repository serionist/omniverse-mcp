---
subject: "Build the wheel test's wheel with the tests' own Python (#206)"
base: main (e96adb3)
head: 44cb909
date: 2026-11-15
round: 1
tier: "one fresh reviewer on Claude Opus, read only; no findings"
verdict: clean
---

# Review: The wheel test's Python

Read from the branch's diff against `main` at `e96adb3` (one test, 6 lines) by one fresh reviewer, read only, with
`.github/workflows/ci.yml`, `pyproject.toml` and every other place the repo runs uv. No findings.

**Refuted:** `sys.executable` not an interpreter uv takes (under `uv run --python <leg>` it is the project venv's
Python, which `--python` accepts over `.python-version`); `--offline` failing for another reason on 3.11 or 3.14 (the
build backend and its dependencies are pure Python, cached by the editable install on the same leg); another place hit
by `.python-version` the same way (the gate's uv calls run online in the Checks job, other subprocesses call
`sys.executable`, the Package job builds online).

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | The comment says CI's runners lack 3.12; only the Linux ones do | taken |
