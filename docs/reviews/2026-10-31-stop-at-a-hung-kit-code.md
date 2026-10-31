---
subject: "End a live run at Kit's first timeout when /health gets no answer either (#54)"
base: main (a94ef03)
head: 1667205
date: 2026-10-31
round: 1
tier: standard (one fresh reviewer on Claude Sonnet; findings checked against the code by the author)
verdict: clean
---

# Review: the live suites' guard against a hung Kit

Read from the branch's diff: `tests/conftest.py`'s `HungKit`, `health_answers`, the session fixture and the two
hooks, `tests/test_hung_kit.py` and CONTRIBUTING.md, against `BridgeClient`, the live suites' clients and cleanups,
`TestColdCook`'s own `pytest.exit` and pytest's runner. No blocker or major; two minors, fixed, so no second round.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `tests/conftest.py`, the session fixture and the two hooks | Only `HungKit` and `health_answers` were tested: a renamed hook or a dropped patch would leave every test green and bring back the hour-long hang | fixed in `c6cab5f`: `test_the_session_guards_every_bridge_client` (the patch is in place and a live call fails at once once Kit counts as hung), `test_a_live_test_switches_the_guard_on_for_its_run_only` (the protocol hook, for `sim`, `scenario` and neither) and `test_a_hung_kit_stops_the_session_after_the_test` (the makereport hook sets `shouldstop`). Writing them stopped this session once: a test that leaves the session's guard set is read by the hooks after it, so each puts it back inside the test |
| F2 | minor | `tests/test_hung_kit.py`, the two `health_answers` tests | They passed `BridgeClient.request`, which in the session is already the guard, so they didn't use the unwrapped call the fixture gives the probe | fixed in `c6cab5f`: `UNGUARDED`, the client's own `request` from before the patch, for the fixture and the tests |

Refuted, each from the code:

- **A non-live test changed:** the guard probes or fails a call only while `live`, which only the `sim` and `scenario`
  markers set; `tests/test_client.py`'s timeouts against its mock server re-raise as before.
- **`setUpClass` and `tearDownClass` outside the marked item's protocol:** they run as class-scoped fixtures in its
  setup and teardown, and pytest takes `nextitem = None` once `shouldstop` is set, so the class is torn down inside it.
- **`live` left set by a hook that raised:** a hookwrapper's code after `yield` runs with the outcome either way.
- **Recursion through the probe:** `health_answers` gets the unwrapped call, which goes to `_exchange`, not `request`.
- **`shouldstop` skipping teardown, or exiting 0:** teardown runs; the session ends Interrupted, exit code 2.
- **`TestColdCook`:** the guard records the hang and re-raises; its own `pytest.exit` then ends the run with its #5
  message.
- **The client's lock:** the probe runs on its own client after `request` released the lock.
- **The harness lens:** the change only adds a stop; no test, skip, ignore or baseline loosened.

Improvements:

| Improvement | Answer |
|---|---|
| A handler that runs long on Kit's loop also holds `/health` back, so a slow, healthy Kit could be judged hung | taken: the probe waits 20 s, not 10; a stopped run is never a false pass, and a rerun settles it |
| A refused token during the probe means Kit answered, yet counted as hung | taken: `BridgeError` counts as an answer; only an `OSError` means hung. `test_a_refused_token_is_an_answer` |

Not covered: the reviewer ran nothing; no Kit was needed, as no bridge or tool code changed.

## Checks

- **The gate:** `uv run tools/gate.py full` passed on `1667205` (1453 passed) and after the fixes (1459 passed).
- **A Kit that never answers,** a socket on 127.0.0.1:8299 that takes connections and sends nothing: both live suites
  pointed at it stopped after their first test, in 40.24 s with a 10 s probe and 50.14 s with 20 s, the message naming
  the port, #54 and the thread-dump command. Without the guard each of the suites' tests and cleanups waits out its
  own timeout.
- **The probe's two ways to fail,** unit-tested: a port that takes the connection and never answers times out at the
  probe's limit (0.32 s with it set to 0.3 s), and a port nothing listens on is refused.
