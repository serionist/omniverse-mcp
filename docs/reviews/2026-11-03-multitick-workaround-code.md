---
subject: "Name NVIDIA's workaround for Kit 110's new-view hang where users and agents meet the hang (#187)"
base: main (1a538be)
head: aca528a
date: 2026-11-03
round: 1
tier: "one fresh reviewer on Claude Opus, every lens that applies. One minor, so no second round"
verdict: clean
---

# Review: NVIDIA's workaround for the new-view hang

Read from the branch's diff against `main` at `1a538be` (7 files, 37 lines added) by one fresh reviewer, read only,
against issue #187 and the measurements it names. A trivial change: no plan. One minor; fixed in `ce59f62`, with the
three improvements, and the gate passed there.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/ARCHITECTURE.md`, the client's silent-Kit paragraph | It says `tools/_bridge.py` adds what a silent Kit may be doing and when to restart it, but not the flag the error now names: a reader of the architecture doc misses the workaround | fixed in `ce59f62`: the paragraph names the flag |

**Refuted:** the anchors (`#known-issues`, `#headless-kit`, `../README.md#known-issues`) reach their headings; the
numbers match the measurements (1,000 views twice against a hang at 600; 3.190 and 3.210 against 1.14 to 1.19);
`extra_args` reaches Kit's command line (Isaac Sim 6.2's `simulation_app.py`), which overrides
`isaacsim.exp.base.kit`'s `rtx.hydra.supportMultiTickRate = true`; "avoids that hang" is labelled NVIDIA's
workaround; the CHANGELOG line's form; no other place that tells users or agents what to do about #114 was missed;
the unit test fails without the change; the writing rules and the commit's form.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | Say which figure is with the flag, and that it was measured with the timeline stopped, in the README and `docs/TOOLS.md`; TOOLS.md's "under 2" doesn't hold with the flag | taken in `ce59f62` |
| I2 | Name the flag in the walking-agents twin test's message, so a live run on a Kit started with it isn't read as a regression | taken in `ce59f62` |
| I3 | Tell Isaac Sim users with Kit's window that the Headless Kit section covers them too | taken in `ce59f62` |

**Not covered:** the gate, which the reviewer didn't run (it passed at `aca528a` and `ce59f62`); CI, before the PR.

**Live suites:** not run for this change. It changes an error's text, docs, a skill row and a test's message; the
error needs a real hang to show, which the unit test stands in for. The measurements it quotes are from the runs on
2026-11-03 named in #187.
