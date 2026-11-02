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

- **Live, `tests/test_scenarios.py`:** phases 22 to 26 read the up axis as phases 1 to 16 have since #6,
  `_along_up(self._up_axis(), ...)`, in place of their five Y literals (`:2698`, `:2707`, `:2785`, `:2919`, `:2945`)
  and 26.2's side check that ran only on Y (`:2950`); the comment at `:2778` goes (fit I1). The order of phase 17's
  `new_scene` calls then can't break them. `test_17_02_new_scene` checks the default frame (Z, 1.0) and an asked one
  (Y, 0.01) with `sim_state`; phase 17's last `new_scene` (17.6, `:2473`) passes `up_axis="Y"`, so a second run of the
  suites starts on a Y-up stage and a first on Isaac Sim's own Z-up one, today's rhythm without a step to remember.
  `tests/physics_checks.py:90`'s comment follows.
- **Outcomes, `tools/scenarios.py` and `test_project/outcomes.md`** (fit I2): the runner's `prepare_stage` calls
  `new_scene()` with no arguments, so each outcome starts on the frame a user's agent now gets; the Givens of O2, O4
  and O5 swap their Y and Z values and drop their `SetStageMetersPerUnit` lines, and lines 22 and 23 say Z-up in
  metres. The Verify lines name no axis. Outcomes landed today, so no earlier run is lost to compare against.
- **AI scenarios, `scenarios.md`:** a session that starts a new stage is told to call `new_scene(up_axis="Y")`, so its
  vectors, written for Y-up, keep their meaning and earlier runs stay comparable; 17.2 checks the default frame.
- **`test_project/AGENTS.md`** names the call a new-stage session makes.

### Alternatives

- **Keep Y-up as the default and add the parameters:** no (Q1); the robotics frame is what this repo's users start
  from.
- **The Kit app's own setting** (`/persistent/app/stage/upAxis`) as the default: no; Z in Isaac Sim and Y in USD
  Composer would make one call give two frames, and a test can't pin it.
- **Move `scenarios.md` to Z-up:** no; its vectors and testers' lines are written for Y, and comparing runs across the
  change would mix two frames. A later issue can move them. The outcomes move (fit I2): they are a user's requests,
  and their Verify lines name no axis.

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
| 4 | The suites: phases 22 to 26 read the axis, `test_17_02` and 17.6, `tools/scenarios.py`'s prompt line and `prepare_stage`, `scenarios.md` 17.2, `outcomes.md`'s header and O2, O4, O5, `test_project/AGENTS.md`, the comments | `tests/test_scenario_runs.py` (the prompt line, the call `prepare_stage` makes); the live run |
| 5 | Docs, `uv run tools/gate.py full`, the live suites on Z and Y, an AI run of phase 17 and O4, `review-code`, the PR | the review record |

## Tests

- Unit (CI): the steps' tests above; each fails on today's code.
- Live (by hand, Isaac Sim 6.2 at 8212): the suites twice in a row on one Kit, the first on Isaac Sim's own Z-up
  stage, the second on the Y-up stage 17.6 leaves; `test_17_02` reads back the default (Z, 1.0) and an asked frame (Y,
  0.01) with `sim_state`; phases 22 to 26 pass on both axes.
- AI: phase 17 and O2, O4 and O5, whose Givens move to Z (`--phases 17 --outcomes O2,O4,O5`).
- What neither shows: USD Composer, whose own default is Y-up: the tool sets the frame whatever the app's setting.

## Docs

`docs/TOOLS.md` (`new_scene`'s section: parameters, the answer, the default), `CHANGELOG.md` (Breaking), the `scene`
skill if it names the frame, `docs/images/README.md`'s recipe (its `execute_script` for a Z-up stage goes),
`test_project` files above. `README.md` names the tool only.

## Risks

- **An agent's saved workflow expects Y-up from `new_scene()`:** accepted; 0.x, under Breaking, and the answer names
  the frame.
- **Kit's cameras and light rig after `set_frame`** (fit I3), from Kit's own code: Kit turns its implicit cameras when
  the up axis changes (`omni.kit.widget.viewport`, `impl/utility.py:509`, `class StageAxis`), as its own "Set up axis"
  menu relies on; a light rig is turned to the axis only when it is set (`omni.kit.viewport.menubar.lighting`,
  `actions.py:51-52`), and `viewport_light` sets it after the frame. Resolved for the axis. Units are the open part:
  Kit places its implicit cameras for the stage's units only when it builds them (`utility.py:121-123`), so a
  `meters_per_unit` other than the app's default leaves the viewport camera placed for the old one, 100 times off in a
  centimetre app such as USD Composer under the new 1.0 default. On Isaac Sim the default changes nothing Kit built:
  its new stage is Z-up in metres already (`apps/isaacsim.exp.base.kit:258`, `:273`). Accepted: the answer names the
  units, `set_camera` places the camera, and the live run covers 0.01 on Isaac Sim.

## Plan review

### Fit

The plan at `ba7feda`, by a fresh general-purpose agent on Claude Opus 5.5, 2026-11-02, with this repo's `fit-plan`
from branch `160-fit-plan`. The change's own question: with Z-up in metres the default, does any path stay wrong or
untested (the robot and file turns, gravity, the viewport camera, the light rig, the AI suites, phases 22 to 26)?
Answers by the author, 2026-11-02, on the maintainer's delegation.

| # | Improvement | Answer |
|---|---|---|
| I1 | Phases 22 to 26 read the up axis with `_along_up`, as phases 1 to 16 do, so the order of phase 17's `new_scene` calls can't break them, and phase 17's last call passes `up_axis="Y"` for a Y-up second run | taken: The suites, Tests |
| I2 | Run the outcomes on the new default: `prepare_stage` calls `new_scene()`, O2, O4 and O5's Givens swap Y and Z; they are a user's requests, their Verify lines name no axis, and no earlier run is lost | taken: The suites, Alternatives |
| I3 | Replace the camera risk with what Kit's code does: implicit cameras follow the axis, a rig is turned when set, but units are read only when the cameras are built, 100 times off in a centimetre app | taken: Risks |

Noticed on the way, for Round 1: 17.3, 17.5 and 17.6 call `new_scene()` after 17.2, so phases 22 to 26 would run on Z
and 26.2's side check be skipped (The suites; I1 answers it); the comment the plan cites is at `:2778`, not `:2718`
(The suites); "a cube's tallest side along Z" proves nothing for a cube (Tests); #159 has no agreement comment yet
(Compatibility).
