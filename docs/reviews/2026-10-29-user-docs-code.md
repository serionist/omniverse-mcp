---
subject: "Rework the README and the user docs for a first setup (PR #44)"
base: main (2b5a367)
head: f384156
date: 2026-10-29
round: 1
tier: standard (one fresh reviewer; every claim checked against the code, outside facts against the checked list)
verdict: clean
---

# Review: the docs rework

Read from the diff and each touched file in full, against `src/omniverse_mcp/`, `extension/ovmcp.bridge/` and the
outside facts checked for this change (each client's config, Claude Code's plugin commands, uvx, Kit's flags,
`SimulationApp`, image costs). Eight minors, all fixed in `89cc7e5`; five improvements taken.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | minor | `docs/SETUP.md`, Kit on another machine | `OMNIVERSE_MCP_STATE_DIR` offered for Kit running as another user: the token folder is made `0o700` and the file `0o600`, so the other user can't read it; on Windows a folder both can reach exposes the token to every local user | fixed: the same user only, a folder only they can read; another user sets the token |
| F2 | minor, security | `docs/SETUP.md`, the token on Kit's command line | Visible to the machine's other users (`ps`, `/proc/<pid>/cmdline`). Not a regression: the edited `extension.toml` it replaces was world-readable too | fixed: said |
| F3 | minor | `docs/SETUP.md` (Uninstalling, Troubleshooting), the extension's README | A bare `omniverse-mcp extension path`, which isn't on PATH for a uvx user | fixed: `uvx omniverse-mcp extension path` |
| F4 | minor | `docs/SETUP.md`, Headless Kit | `python.sh my_script.py --enable ovmcp.bridge` without `--ext-folder`, so Kit can't find the bridge | fixed |
| F5 | minor | `docs/TOOLS.md`, `new_scene` | `SetStageUpAxis(stage, ...)`: `execute_script`'s namespace has `omni`, no `stage` (`handlers/misc.py`) | fixed: `omni.usd.get_context().get_stage()` |
| F6 | minor | `docs/TOOLS.md`, `create_robot` | The parameter table still offered a USD path (#40) | fixed |
| F7 | minor | `docs/TOOLS.md`, Where answers go | Scene dumps "to their own folders": a dump is `mcp_output/scene_dump.txt`, replaced by the next | fixed |
| F8 | minor | `CONTRIBUTING.md`, the clone | "`test_project/.mcp.json.example` is the same form", which had no empty `PYTHONPATH` | fixed: the example has it |

Refuted, each from the code:

- **The PyPI anchor substitution double-rewrites:** the relative-link pattern skips `#`, and `release.py`'s check allows
  `](#user-content-...)` through the same exclusion.
- **The find-a-tool table trips `test_contract.py`:** its hint-row regex needs three columns and a hint label.
- **A released anchor or path broke:** `#install`, `#configuration`, `#the-bridge-token` in the README and in
  ARCHITECTURE exist, as does every file PyPI's 0.2.0 page links to; every relative link and anchor resolves.
- **A quoted message differs from the code:** each matches (`http.py`, `extension.py`, `kit_extension.py`,
  `_bridge.py`, `client.py`, `tools/simulation.py`).
- **The SSH tunnel fails the loopback Host check:** `host_name()` drops the port.

Improvements:

- **The setup skill's token link** goes to `docs/SETUP.md#kit-on-another-machine`, where the steps are: taken.
- **The setup skill, a refused connection with the bridge installed:** start Kit first, and add the search path only
  when it isn't listed: taken.
- **SETUP.md, Kit on another machine:** the bridge of the server's release on the Kit machine first, with the server
  pinned: taken.
- **README, Install:** which of the two printed folders Kit needs: taken.
- **AI_GUIDE.md:** "much the same context", since the server's instructions differ in wording: taken.
- **`tools/release.py` checks each `#user-content-` anchor against a heading:** left: the substitution covers every
  heading the README links; worth it once a rename breaks one.
- **`get_sim_state`'s `fps` is time codes per second** (`handlers/simulation.py`), outside the diff: TOOLS.md now says
  so; renaming the field is a contract change.

Not covered: the Kit main-thread, tool-contract, bridge-security code and test lenses, with no code in the change.

## Checks

`uv run tools/gate.py full` passed on `f384156` and on `89cc7e5`: 690 tests, 93.34%.
