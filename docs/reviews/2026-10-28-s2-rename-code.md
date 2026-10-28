---
subject: S2, rename and layout (PR #8)
base: main (1bbbcae)
head: 69af0c0
date: 2026-10-28
round: 1
tier: high (one fresh reviewer; findings checked against the code by the fork that fixed them)
verdict: needs-fixes
---

# Review: S2, the rename and the new layout

Fixed in `ff3739b` (code and tests) and `b1bc7cd` (docs).

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| F1 | major | `server.py` | `parse_known_args()` dropped unknown flags, so an `.mcp.json` from before the rename (`--isaac-port 9000`) started a server that quietly talked to 127.0.0.1:8211. | Fixed: unknown flags are an error; `--isaac-host`/`--isaac-port` stop with "was renamed --host/--port". Parsing moved to `omniverse_mcp/config.py` (`parse_args(argv, environ)`). Tests in `test_config.py`. |
| F2 | major | `server.py` | An empty `OMNIVERSE_MCP_PORT` (an unset `${VAR}` in an MCP client's config) failed `int("")`; an empty host became the host. | Fixed: an empty variable counts as unset; a non-empty bad port says "OMNIVERSE_MCP_PORT must be a port number". Tests. |
| F3 | minor | `pyproject.toml` | The wheel might take `__pycache__`/`.pyc` from `extension/ovmcp.bridge` once Kit has run from the checkout. | Checked, not reproduced: with Kit's `__pycache__` folders on disk, `uv build`'s wheel and sdist hold no `.pyc` (hatchling skips them under `force-include` too). No change; S9's `check-wheel-contents` guards it at release. |
| F4 | minor | README | The rename note tied `isaacsim.mcp.bridge` to "until 0.2.0" while the extension ships 0.1.0. | Fixed: "before the rename (#8)". |
| F5 | minor | README | The pip `.mcp.json` dropped `"env": {"PYTHONPATH": ""}`, which troubleshooting still relies on (Kit's setup scripts leak one). | Fixed: restored. |
| F6 | minor | CHANGELOG | An existing `pip install -e .` still points `omniverse-mcp` at the deleted `isaac_sim_mcp`. | Fixed: reinstall with `pip uninstall omniverse-mcp` then `pip install .` (or `-e .`), or `uv sync`. |
| F7 | improvement | `extension.py` | Three settings paths spelled the extension name out. | Taken: built from `EXTENSION_NAME`. |
| F8 | minor | tests | Nothing kept `extension.toml`'s module name, settings keys and folder on `EXTENSION_NAME`. | Fixed: `test_extension_toml_uses_the_extension_name_everywhere`. |
| F9 | minor | server, client, tools | The instructions still said "NVIDIA Isaac Sim 5.1", the resources' and connection errors "Isaac Sim", and the client was `IsaacSimClient`. | Fixed: they say Kit app (Isaac Sim, USD Composer, ...), the Context7 hint stays; the class is `BridgeClient` in src and tests. Tool descriptions that are about Isaac Sim itself (its robot library) keep the name. |
| F10 | minor | README, `test_project/.mcp.json.example` | `uv run --project` syncs at every MCP start and can hold the client's handshake on a download. | Fixed: `uv sync` once, then `uv run --no-sync --project <REPO_PATH> omniverse-mcp`; checked with uv 0.12.1 that `--no-sync` and `--project` work together and keep the client's working folder. |

## Checks

- **Tests:** `uv run pytest -q -p no:cacheprovider` gives 209 passed, 123 skipped.
- **Wheel:** `uv build` holds `omniverse_mcp/_extension/ovmcp.bridge/config/extension.toml` and `omniverse_mcp/config.py`, and no `.pyc`.
- **Old flag:** `uv run --no-sync --project <wt> omniverse-mcp --isaac-port 9000` stops with "--isaac-port was renamed --port".

## Round 2

The main session read round 1's fixes, `69af0c0..4fcdfc0`, after a fresh reviewer could not open the repo (folder ownership). Verdict: clean.

| # | Sev | Where | Finding | Status |
|---|---|---|---|---|
| R1 | minor | `server.py` | The server parses `sys.argv` when it is imported, and an unknown argument is now an error. Anything that imports the module under its own argv (`mcp dev`, a test runner) would exit. Nothing does today. | Later: S7 moves the parsing into `main()` ("no work at import"). |

Live after the fixes, on Isaac Sim 6.2:
- integration 27/27;
- `/bridge` reports `0.1.0`;
- the wheel and sdist hold no `.pyc`, although Kit's `__pycache__` is on disk.
