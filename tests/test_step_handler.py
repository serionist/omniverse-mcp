"""/sim/step's handler against tests/test_force_handler.py's fake Kit (#198): exact steps of the scene's dt through
PhysX's manual loop, Fabric updated after each, the timeline paused from playing and loaded from stopped, a second step
refused while one runs, and each observed prim read back."""

import asyncio
import math
from typing import Any

import pytest
from pxr import Sdf, UsdGeom, UsdPhysics

from .test_force_handler import BOX, COM, TRANSFORM, FakeKit, load_simulation


@pytest.fixture
def kit() -> FakeKit:
    kit = FakeKit()
    kit.paused = True
    kit.velocities[BOX] = [0.0, 0.0, -9.81, 0.0, 0.0, math.pi]
    return kit


@pytest.fixture
def simulation(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_simulation(kit, monkeypatch)


def _step(simulation: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(simulation.handle_sim_step(body))


def test_steps_exactly_the_count_asked_at_the_scene_s_dt(simulation, kit):
    kit.scene_attr("timeStepsPerSecond", Sdf.ValueTypeNames.Float, 120.0)
    r = _step(simulation, steps=30)
    assert r["status"] == "success", r
    result = r["result"]
    assert (result["asked"], result["steps"], result["was"], result["current_state"]) == (30, 30, "paused", "paused")
    assert result["dt"] == pytest.approx(1 / 120)
    assert len(kit.simulated) == kit.fetched == len(kit.fabric_updates) == 30
    # Each step's time follows the last, from the timeline's time, and Fabric is told the same.
    assert [t for _, t in kit.simulated] == pytest.approx([i / 120 for i in range(30)])
    assert kit.fabric_updates == kit.simulated
    assert result["fabric"] is True
    assert result["stopped_early"] is None


def test_zero_steps_reads_without_stepping(simulation, kit):
    r = _step(simulation, steps=0, observe=[BOX])
    assert r["result"]["steps"] == 0
    assert kit.simulated == []
    (box,) = r["result"]["observed"]
    assert box["position"] == pytest.approx(TRANSFORM[:3])
    # The tensor row's (x, y, z, w) comes w first, and rad/s comes as deg/s.
    assert box["rotation"] == pytest.approx([TRANSFORM[6], *TRANSFORM[3:6]])
    assert box["linear_velocity"] == pytest.approx([0.0, 0.0, -9.81])
    assert box["angular_velocity"] == pytest.approx([0.0, 0.0, 180.0])


def test_a_playing_timeline_is_paused_first(simulation, kit):
    kit.paused = False
    r = _step(simulation, steps=2)
    assert r["result"]["was"] == "playing"
    assert kit.timeline_calls[:2] == ["pause", "commit"]
    assert r["result"]["current_state"] == "paused"


def test_a_stopped_timeline_is_loaded_with_both_changes_committed_and_says_its_steps(kit, monkeypatch):
    kit.paused, kit.stopped = False, True
    kit.engine, kit.load_steps = "physx", 2
    r = _step(load_simulation(kit, monkeypatch), steps=5)
    assert kit.timeline_calls[:4] == ["play", "commit", "pause", "commit"]
    assert (r["result"]["was"], r["result"]["load_steps"], r["result"]["steps"]) == ("stopped", 2, 5)


def test_newton_is_refused_before_anything_moves(kit, monkeypatch):
    kit.engine = "newton"
    r = _step(load_simulation(kit, monkeypatch), steps=5)
    assert r["status"] == "error"
    assert "The active physics engine is newton" in r["error"]
    assert kit.simulated == [] and kit.timeline_calls == []


def test_without_omni_physx_fabric_physx_alone_steps(kit, monkeypatch):
    kit.fabric = False
    simulation = load_simulation(kit, monkeypatch)
    r = _step(simulation, steps=3)
    assert len(kit.simulated) == 3
    assert kit.fabric_updates == []
    assert r["result"]["fabric"] is False


def test_a_second_step_while_one_runs_is_refused(simulation, kit):
    async def both():
        first = asyncio.ensure_future(simulation.handle_sim_step({"steps": 1}))
        await asyncio.sleep(0)  # the first is inside, awaiting its update
        second = await simulation.handle_sim_step({"steps": 1})
        return await first, second

    first, second = asyncio.run(both())
    assert first["status"] == "success"
    assert second == {"status": "error", "error": "A step is running: wait for its answer, then step again"}
    # And the lock is let go after it.
    assert _step(simulation, steps=1)["status"] == "success"


def test_a_bad_request_is_refused_before_the_lock(simulation, kit):
    r = _step(simulation, steps=-1)
    assert r["status"] == "error"
    assert "steps must be a whole number from 0 to 1000" in r["error"]
    assert _step(simulation, steps=1)["status"] == "success"


def test_stepping_stops_when_the_timeline_changes_under_it(kit, monkeypatch):
    # Every step overruns the yield, so Kit's loop runs before each; it plays before the third.
    clock = iter(range(1000))

    def simulate(dt: float, current: float) -> None:
        kit.simulated.append((dt, current))
        if len(kit.simulated) == 2:
            kit.paused = False

    monkeypatch.setattr(kit, "simulate", simulate)
    simulation = load_simulation(kit, monkeypatch)
    monkeypatch.setattr(simulation, "_clock", lambda: next(clock) * 0.06)
    r = _step(simulation, steps=10)
    assert r["result"]["steps"] == 2
    assert r["result"]["stopped_early"] == "the timeline or the stage changed while stepping"


def test_stepping_stops_at_its_time_limit(simulation, kit, monkeypatch):
    clock = iter(range(1000))
    monkeypatch.setattr(simulation, "_clock", lambda: next(clock) * 0.04)
    monkeypatch.setattr(simulation, "STEP_SECONDS", 0.1)
    r = _step(simulation, steps=50)
    assert 0 < r["result"]["steps"] < 50
    assert r["result"]["stopped_early"] == "the call reached its 0 s limit: ask for fewer steps"


def test_each_observed_prim_gets_its_own_block(simulation, kit):
    stage = kit.stage
    # A robot whose root is also a rigid body, as a G1's pelvis is; a light; a body PhysX doesn't hold; a missing path.
    pelvis = UsdGeom.Xform.Define(stage, "/World/G1/pelvis").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(pelvis)
    UsdPhysics.ArticulationRootAPI.Apply(pelvis)
    kit.tensor_bodies["/World/G1/pelvis"] = (TRANSFORM, COM)
    UsdGeom.Xform.Define(stage, "/World/Light")
    kit.add_body("/World/Loose")
    r = _step(simulation, steps=1, observe=["/World/G1/pelvis", "/World/Light", "/World/Loose", "/World/Gone"])
    pelvis_block, light, loose, gone = r["result"]["observed"]
    assert "position" in pelvis_block
    assert pelvis_block["joints"] == {"root": "/World/G1/pelvis", **kit.joint_states}
    assert light["error"].startswith("/World/Light is neither a rigid body nor an articulation")
    assert loose["body_error"].startswith("PhysX holds no rigid body at /World/Loose")
    assert gone["error"] == "Prim not found: /World/Gone"


def test_a_step_count_reset_by_the_play_gives_no_load_count(kit, monkeypatch):
    # Isaac Sim's counter, if a play resets it, reads fewer steps after the load than before: no number to trust.
    kit.paused, kit.stopped = False, True
    kit.engine, kit.physics_steps, kit.load_steps = "physx", 50, -50
    r = _step(load_simulation(kit, monkeypatch), steps=1)
    assert r["result"]["load_steps"] is None


def test_the_time_limit_counts_the_load_from_stopped(kit, monkeypatch):
    # The load's update takes the whole limit: no step is left to take.
    kit.paused, kit.stopped = False, True
    simulation = load_simulation(kit, monkeypatch)
    clock = iter([0.0, *[100.0 + i for i in range(100)]])
    monkeypatch.setattr(simulation, "_clock", lambda: next(clock))
    r = _step(simulation, steps=5)
    assert r["result"]["steps"] == 0
    assert r["result"]["stopped_early"] == "the call reached its 90 s limit: ask for fewer steps"
