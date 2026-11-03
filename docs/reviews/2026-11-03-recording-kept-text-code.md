---
subject: "Say when a recording's render isn't kept after its stop, in start_recording's answer (#193)"
base: main (99dfc7f)
head: c4f7bc1
date: 2026-11-03
round: 1
tier: "one fresh reviewer on Claude Opus, every lens that applies. Four minors, so no second round"
verdict: clean
---

# Review: when a recording's render is kept

Read from the branch's diff against `main` at `99dfc7f` (4 files) by one fresh reviewer, read only, against issue
#193 and its comment, and the bridge's `camera_feed.py` (`lend`, `hand_back`, `put_back`, `kept_feed`), the stop in
`recording.py` and `sweep.py`. A trivial change: text only, no plan. The answer's new text held in every case; four
places around it didn't. All fixed in the next commit.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/TOOLS.md`, the kept-render box | "leaves the kept one, which stays kept after the stop while the recording's own goes" is wrong after a recording longer than the capture's 30 s: the capture's render goes on its clock and the recording's is kept (the run that found #193 shows it, `rec_1793718107`); "`stop_recording` keeps it again" fails when a capture during a borrowing recording keeps a render of its own. The line was also 180 columns | fixed: the stop keeps the recording's render when no other is kept then; a capture's render still kept stays instead |
| F2 | minor | `docs/TOOLS.md`, `capture_sweep`'s render | "kept again after it" makes the same promise; `hand_back` keeps a sweep's render the same way, and a capture during a sweep runs between shots | fixed |
| F3 | minor | `test_project/scenarios.md`, 6.4 to 6.9 | Its Verify line still says the recording's render is the kept feed after the stop, which is what gave the WARN; 6.3 ends with a capture, so the next run could WARN again | fixed: unless a capture's render was still kept at the stop |
| F4 | minor | `src/omniverse_mcp/tools/recording.py`, `start_recording`'s description | "up to 30 s after, kept for the next capture or recording", read before the call, makes the promise the issue counted false | fixed |

**Refuted:** the cases the answer leaves out (a changed stage, a failed frame: the stop's `Note:` says so; a call
holding the lock at that moment: rare, and the `stop_recording` section lists them); "by then" missing a render
kept before the recording (it covers it); README, ARCHITECTURE.md and the scene skill (they promise nothing, or
state the condition); the writing rules.

**Improvements:**

| # | Improvement | Answer |
|---|---|---|
| I1 | The answer: "unless a capture's render, from before the recording or during it, is still kept then, which stays instead (it goes 30 s after its capture)", which says the outcome depends on timing | taken |
| I2 | `stop_recording`'s description: "by then" points at nothing; "still kept at the stop" | taken |
| I3 | The comment's "but for one case" and "at another size" are too narrow | taken |
| I4 | `stop_recording`'s section: any holder of the render's lock, not only a capture | taken |

**Not covered:** the gate (passed at `c4f7bc1` and on the fixes); CI, before the PR.

**Live suites:** not run. The change is the server's text, its descriptions and docs; the bridge is unchanged, and
`tests/test_tools.py` pins the answer.
