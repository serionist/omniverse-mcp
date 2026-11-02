---
title: Give new_scene an up axis and units, Z-up in metres by default, a change to the tool contract
issue: "#159"
status: draft
approved_by:
approved_at:
---

# Give new_scene an up axis and units, Z-up in metres by default, a change to the tool contract

## Goal

`new_scene` makes the frame an agent asks for, and says which it made. Today it forces a Y-up stage
(`handlers/scene.py:615`) and leaves the units to Kit's settings, so an agent starting a robotics scene gets the wrong
frame without being told: Isaac Sim's robots, SimReady assets and most robotics scenes are Z-up in metres, and Isaac
Sim's own File > New is Z-up in metres (its app config: `app.stage.upAxis = "Z"`, `simulation.defaultMetersPerUnit =
1.0`). `create_prim` turns a referenced file to the stage's frame (#119), but a script, a payload or physics don't.

When this is done:

- `new_scene(up_axis="Z", meters_per_unit=1.0)`: both parameters optional, Z-up in metres by default (the maintainer's
  call, 2026-11-02);
- the answer gives the stage's `up_axis` and `meters_per_unit` as read back, as `open_scene`'s does;
- with an extension older than the server, which ignores both, the answer warns that the stage is Y-up.

In scope: the tool, its client call, the handler, the tool contract, the docs, the live and AI suites that assumed a
Y-up `new_scene`.
Out of scope: `open_scene` (a file keeps its own frame); converting an open stage's content when its frame changes;
`create_robot` and `create_prim`'s turns (#105, #119), which read whatever frame the stage has.

## Design

### The maintainer's calls

| # | Call | Answer |
|---|---|---|
| Q1 | The default: Z-up in metres, not today's Y-up with Kit's units | Z-up in metres (maintainer, 2026-11-02) |
| Q2 | The plan is approved, and its improvements answered, by the author on the maintainer's delegation | yes (maintainer, 2026-11-02: "take improvements, accept plans") |

### The server (`src/omniverse_mcp/tools/scene.py`, `client.py`)

```python
@tool(mcp, DESTROYS)
def new_scene(
    up_axis: Annotated[Literal["Z", "Y"], Field(description="The stage's up axis: Z, as Isaac Sim's robots and stages are, or Y")] = "Z",
    meters_per_unit: Annotated[float, Field(gt=0, description="The stage's metres per unit: 1.0 for metres, 0.01 for centimetres")] = 1.0,
) -> str:
```

- `client.new_scene(up_axis="Z", meters_per_unit=1.0)` sends both, always.
- The answer: `New scene created with /World root prim`, then `up_axis = Z` and `meters_per_unit = 1.0` read back from
  the stage, the lines `open_scene` gives.
- An older extension answers no `up_axis`: the tool adds `WARNING: this Kit extension, older than the server, made a
  Y-up stage in Kit's units; run uvx omniverse-mcp extension install, then restart Kit`, as #149's and #150's tools
  warn.
- The description drops today's advice to set the axis by `execute_script` and says the default and why.

### The extension (`handlers/scene.py`, `ovmcp/core/stage_open.py`)

- `handle_new_scene` reads `up_axis` and `meters_per_unit` from the body; an unknown axis or a value not above zero is
  an error before the stage is replaced, so a bad call discards nothing.
- After `new_stage_async` and `/World`, a Kit-free function in `ovmcp/core/stage_open.py`,
  `set_frame(stage, up_axis, meters_per_unit)`, writes both with `UsdGeom.SetStageUpAxis` and
  `UsdGeom.SetStageMetersPerUnit`; the answer adds `describe(stage)`'s `up_axis` and `meters_per_unit`.
- A body without the keys (a server older than the extension) gets today's stage: Y-up, units left to Kit, so an older
  server's "(Y-up)" stays true.

### The suites

- **Live, `tests/test_scenarios.py`:** `test_17_02_new_scene` checks the default (Z, 1.0, read back with
  `sim_state`), then calls `new_scene(up_axis="Y", meters_per_unit=1.0)`, which leaves phases 22 to 26 the Y-up stage
  their heights are written for; its comment at line 2718 says so. `tests/physics_checks.py:90`'s comment follows.
- **AI scenarios, `tools/scenarios.py`:** a session that starts a new stage is told to call
  `new_scene(up_axis="Y")`, and the runner's `prepare_stage` calls `new_scene(up_axis="Y", meters_per_unit=1.0)`, so
  `scenarios.md`'s vectors and `outcomes.md`'s Givens, written for Y-up in metres, keep their meaning and earlier
  runs stay comparable. `scenarios.md` 17.2 checks the default frame; the Givens drop their own
  `SetStageMetersPerUnit` lines, which the call now does.
- **`test_project/AGENTS.md`** names the call a new-stage session makes.

### Alternatives

- **Keep Y-up as the default and add the parameters:** no (Q1); the robotics frame is what this repo's users start
  from.
- **The Kit app's own setting** (`/persistent/app/stage/upAxis`) as the default: no; Z in Isaac Sim and Y in USD
  Composer would make one call give two frames, and a test can't pin it.
- **Move the AI suites to Z-up:** no; their vectors and judges' lines are written for Y, and comparing runs across the
  change would mix two frames. A later issue can move them.

## Compatibility

**One-way door: the tool contract** (`tests/fixtures/mcp-tools.json`). `new_scene` gains two optional parameters, and
its default stage changes from Y-up to Z-up in metres: a call with no arguments now gets a different frame. Under
`CHANGELOG.md`'s Breaking, as `AGENTS.md` allows in 0.x. The maintainer agreed in #159's thread (posted from the
maintainer's chat decision, 2026-11-02, before the PR).

- **An agent that relied on Y-up:** `new_scene(up_axis="Y")` gets it back; the answer says the frame every time.
- **An older extension with this server:** a Y-up stage, and the answer warns.
- **An older server with this extension:** today's stage, since it sends no keys.

## Steps

| # | Step | Proved by |
|---|---|---|
| 1 | `set_frame` in `ovmcp/core/stage_open.py`, tests first | `tests/test_stage_open.py`: Z and 1.0, Y and 0.01, read back by `describe` |
| 2 | `handle_new_scene` reads, checks and applies the keys; without them, today's stage | a handler test with the Kit fakes the scene handler tests use: a bad axis and a zero refused before the stage is replaced; no keys, Y-up |
| 3 | `client.new_scene`, the tool, its answer and warning; `uv run tools/golden.py` | `tests/test_client.py`, `tests/test_tools.py` (both sent, the lines, the warning), `tests/test_contract.py` |
| 4 | The suites: `test_17_02`, `tools/scenarios.py`'s prompt line and `prepare_stage`, `scenarios.md` 17.2, `outcomes.md`, `test_project/AGENTS.md`, the comments | `tests/test_scenario_runs.py` (the prompt line, the call `prepare_stage` makes) |
| 5 | Docs, `uv run tools/gate.py full`, the live suites on Z and Y, an AI run of phase 17 and O4, `review-code`, the PR | the review record |

## Tests

- Unit (CI): the steps' tests above; each fails on today's code.
- Live (by hand, Isaac Sim 6.2 at 8212): both suites on a Z-up and a Y-up stage; `test_17_02` shows the default and Y
  read back; a capture after `new_scene()` shows the cube upright (`test_17_02` adds a cube and checks its box's
  tallest side is along Z).
- AI: phase 17 and O4 run as before (`--phases 17 --outcomes O4`): the runner's call, a new-stage session's call.
- What neither shows: USD Composer, whose own default is Y-up: the tool sets the frame whatever the app's setting.

## Docs

`docs/TOOLS.md` (`new_scene`'s section: parameters, the answer, the default), `CHANGELOG.md` (Breaking), the `scene`
skill if it names the frame, `docs/images/README.md`'s recipe (its `execute_script` for a Z-up stage goes),
`test_project` files above. `README.md` names the tool only.

## Risks

- **An agent's saved workflow expects Y-up from `new_scene()`:** accepted; 0.x, under Breaking, and the answer names
  the frame.
- **Kit's viewport camera after the axis changes under it:** today the handler sets Y after Isaac Sim's Z-up new stage
  and the captures are right; the live capture check covers Z.

## Plan review

None yet.
