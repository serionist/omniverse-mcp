---
subject: "A bridge HTTP test fails when a slow runner reaches its deadline mid-send (#45)"
base: main (27c78bb)
head: ad5e83c
date: 2026-10-29
round: 1
tier: light (one fresh reviewer on a one-test change)
verdict: clean
---

# Review: the blank-lines test on a slow runner

Read from the diff, the bridge's header deadline in `ovmcp/core/http.py` and the test's helpers. No findings; three
nits, all taken.

- **Weaker?** No. A bridge that closes at the first blank line now fails both paths: a send error before the deadline
  fails the lower bound, and the path without one is unchanged. A bridge that never closes, or lets blank lines push
  the deadline, still times out in `_is_closed`. The old test had no lower bound at all.
- **`except ConnectionError`:** covers a broken pipe (Linux, macOS), a reset, and Windows' aborted connection; a
  timeout is not one, and still fails the test.
- **The lower bound's margin (nit, taken):** the clock started after `create_connection` returned, while the bridge's
  deadline starts when it accepts, so the two could be close to 0.1 s apart. The clock now starts before connecting.
- **Wording (nits, taken):** the bound names the deadline instead of a bare 0.9, and the comment says what closed.

Accepted gap: on the send-error path the test doesn't read the close from the socket, so a send error after the
deadline that the bridge didn't cause would pass. Nothing else on a loopback socket raises one.

Checked by slowing the sends to 0.2 s, past the deadline: the old test can't pass that way (1.6 s against its 1.5 s
bound), and the new one passes through the send-error path.

## Checks

`uv run tools/gate.py full` passed on the branch.
