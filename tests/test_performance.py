"""get_performance's numbers (ovmcp/core/performance.py, #156), without Kit: the request's bounds, the frame times'
statistics, the two halves and the "not settled" note, the physics step and the simulated-to-real ratio, Hydra's GPU
times and memory as Kit's bindings give them, the stage's counts on usd-core stages, the eco-mode note, and the
answer with each number missing in turn."""

from typing import Any, NamedTuple

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdRender

from ovmcp.core.performance import (
    PerformanceArgs,
    StepTally,
    answer,
    eco_note,
    gpu_frame_ms,
    gpu_memory,
    gpu_render,
    halves,
    performance_args,
    physics,
    ratio,
    settled,
    still_loading,
    summarise,
    survey,
)

# ---- the request ----


def test_frames_and_warmup_default_to_120_and_30():
    assert performance_args({}) == PerformanceArgs(120, 30)


@pytest.mark.parametrize("body", [{"frames": 2, "warmup": 0}, {"frames": 2000, "warmup": 600}])
def test_the_bounds_themselves_are_taken(body):
    assert performance_args(body) == PerformanceArgs(body["frames"], body["warmup"])


@pytest.mark.parametrize(
    ("body", "says"),
    [
        # One frame leaves no interval once the first is dropped (round 1, P5).
        ({"frames": 1}, "frames must be a whole number from 2 to 2000, got 1"),
        ({"frames": 2001}, "frames must be a whole number from 2 to 2000, got 2001"),
        ({"frames": 2.5}, "frames must be a whole number from 2 to 2000, got 2.5"),
        ({"frames": True}, "frames must be a whole number from 2 to 2000, got True"),
        ({"warmup": -1}, "warmup must be a whole number from 0 to 600, got -1"),
        ({"warmup": 601}, "warmup must be a whole number from 0 to 600, got 601"),
        ({"warmup": "30"}, "warmup must be a whole number from 0 to 600, got '30'"),
    ],
)
def test_a_value_out_of_bounds_is_refused_by_name(body, says):
    with pytest.raises(ValueError, match=says):
        performance_args(body)


# ---- the frame times ----


def test_the_statistics_of_a_list_of_frame_times():
    samples = [float(ms) for ms in range(1, 101)]  # 1 to 100 ms
    stats = summarise(samples)
    assert stats is not None
    assert stats.mean_ms == pytest.approx(50.5)
    assert stats.fps == pytest.approx(1000 / 50.5)
    # The nearest rank: the 50th and the 95th of 100.
    assert (stats.p50_ms, stats.p95_ms, stats.worst_ms) == (50.0, 95.0, 100.0)


def test_the_statistics_of_two_frames_and_of_none():
    stats = summarise([10.0, 30.0])
    assert stats is not None
    assert (stats.mean_ms, stats.p50_ms, stats.p95_ms, stats.worst_ms, stats.fps) == (20.0, 10.0, 30.0, 30.0, 50.0)
    assert summarise([]) is None


def test_the_halves_are_the_first_and_second_halfs_means():
    assert halves([10.0, 12.0, 20.0, 22.0]) == (11.0, 21.0)
    # An odd count gives the middle frame to the second half.
    assert halves([10.0, 20.0, 30.0]) == (10.0, 25.0)
    assert halves([10.0]) is None


@pytest.mark.parametrize(
    ("first", "second", "steady"), [(40.0, 44.0, True), (44.0, 40.0, True), (40.0, 44.1, False), (44.1, 40.0, False)]
)
def test_halves_more_than_10_percent_apart_are_not_settled(first, second, steady):
    assert settled(first, second) is steady


def test_the_ratio_of_simulated_to_real_time():
    assert ratio(4.0, 5.0) == pytest.approx(0.8)
    assert ratio(4.0, 0.0) is None


@pytest.mark.parametrize(
    ("status", "loading"),
    [(("Loading", 3, 12), True), (("", 0, 0), False), (("Done", 12, 0), False), (None, False), ((), False)],
)
def test_the_stage_still_loads_while_kit_counts_files_to_load(status, loading):
    # omni.usd's get_stage_loading_status: (message, loaded, total), as Isaac Sim's is_stage_loading reads it.
    assert still_loading(status) is loading


# ---- the GPU ----


def _node(duration: float, indent: int = 0) -> dict[str, Any]:
    return {"name": "pass", "duration": duration, "indent": indent}


def test_a_frames_gpu_time_sums_the_top_level_passes_and_averages_the_devices():
    # As Isaac Sim's gpu_frametime recorder reads HydraEngineStats().get_gpu_profiler_result(): the nested passes are
    # inside their parent's time.
    one = (_node(5.0), _node(3.0, indent=1), _node(2.0))
    two = (_node(9.0),)
    assert gpu_frame_ms([one]) == 7.0
    assert gpu_frame_ms([one, two]) == 8.0
    assert gpu_frame_ms([]) == 0.0


def test_the_gpu_render_line_and_a_profiler_that_gave_nothing():
    times = gpu_render([10.0, 20.0, 30.0])
    assert times == {"mean_ms": 20.0, "p95_ms": 30.0}
    # Hydra's profiler is off in some apps, and every frame then reads 0.
    assert gpu_render([0.0, 0.0]) == {"missing": "Hydra's GPU profiler gave no times: it may be off in this app"}
    # No frame timed is no fault of the profiler's.
    assert gpu_render([]) == {"missing": "no frame was timed"}


def test_gpu_memory_is_hydras_usage_of_the_devices_dedicated_memory_for_device_0():
    # The keys of omni.hydra.engine.stats' get_device_info() on Isaac Sim 6.2.
    devices = [
        {
            "description": "NVIDIA RTX 6000 Pro",
            "dedicated_video_memory": 48 << 30,
            "dedicated_system_memory": 0,
            "shared_system_memory": 32 << 30,
            "budget": 47 << 30,
            "usage": 3 << 30,
        },
        {"description": "another", "usage": 1, "budget": 2},
    ]
    assert gpu_memory(devices) == {
        "device": "NVIDIA RTX 6000 Pro",
        "used_bytes": 3 << 30,
        "total_bytes": 48 << 30,
        "total_kind": "dedicated",
    }


def test_gpu_memory_falls_back_on_hydras_budget_and_says_so():
    budget_only = gpu_memory([{"description": "x", "usage": 1 << 30, "budget": 8 << 30}])
    assert budget_only == {"device": "x", "used_bytes": 1 << 30, "total_bytes": 8 << 30, "total_kind": "budget"}
    assert gpu_memory([{"description": "x"}]) == {
        "device": "x",
        "used_bytes": None,
        "total_bytes": None,
        "total_kind": None,
    }
    assert "missing" in gpu_memory([])


# ---- physics ----


class _Stat(NamedTuple):
    """A profiling zone as omni.physics.core's PhysicsProfileStats gives it."""

    zone_name: str
    ms: float


def _stats(*zones: tuple[str, float]) -> list[_Stat]:
    return [_Stat(name, ms) for name, ms in zones]


def test_the_tally_counts_each_steps_physx_update_while_it_counts():
    tally = StepTally()
    tally.add(_stats(("PhysX Update", 9.0)))  # before the measured frames
    tally.counting = True
    tally.add(_stats(("PhysX Update", 6.0), ("Simulation", 5.0)))
    tally.add(_stats(("PhysX Update", 4.0)))
    tally.counting = False
    tally.add(_stats(("PhysX Update", 9.0)))
    assert tally.step_ms == [6.0, 4.0]


def test_simulated_time_is_the_steps_counted_each_of_the_scenes_step():
    # 30 steps at 1/120 s: 0.25 s simulated over 10 frames that took 0.5 s (round 1, I8).
    numbers = physics([2.0] * 30, frames=10, wall_seconds=0.5, step_seconds=1 / 120)
    assert numbers["steps_per_second"] == pytest.approx(120.0)
    assert numbers["steps"] == 30
    assert numbers["steps_per_frame"] == pytest.approx(3.0)
    assert numbers["step_ms"] == pytest.approx(2.0)
    assert numbers["frame_ms"] == pytest.approx(6.0)
    assert numbers["simulated_seconds"] == pytest.approx(0.25)
    assert numbers["wall_seconds"] == pytest.approx(0.5)
    assert numbers["ratio"] == pytest.approx(0.5)


def test_no_step_in_the_measured_frames_is_said():
    assert physics([], frames=10, wall_seconds=0.5, step_seconds=1 / 60) == {
        "missing": "no physics step came in the measured frames"
    }


# ---- the stage ----


def test_the_survey_counts_prims_meshes_instances_and_point_instances():
    stage = Usd.Stage.CreateInMemory()
    # The prototypes' sources, outside /World: traversed, with their meshes, as any prim is.
    UsdGeom.Mesh.Define(stage, "/Crate/Box")
    UsdGeom.Mesh.Define(stage, "/Pallet/Board")
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Mesh.Define(stage, "/World/Ground")
    for i in range(3):
        crate = UsdGeom.Xform.Define(stage, f"/World/Crate{i}").GetPrim()
        crate.GetReferences().AddInternalReference("/Crate")
        crate.SetInstanceable(True)
    pallet = UsdGeom.Xform.Define(stage, "/World/Pallet").GetPrim()
    pallet.GetReferences().AddInternalReference("/Pallet")
    pallet.SetInstanceable(True)
    pile = UsdGeom.PointInstancer.Define(stage, "/World/Pile")
    pile.CreateProtoIndicesAttr([0] * 500)

    found = survey(stage)
    counts = found.counts
    assert found.scene is None
    # /Crate, its Box, /Pallet, its Board, /World, Ground, 3 crates, the pallet, the pile: an instance's inside isn't
    # traversed, and the prototypes the 4 instances share are 2.
    assert counts == {
        "prims": 11,
        "meshes": 3,
        "instances": 4,
        "prototypes": 2,
        "point_instancers": 1,
        "point_instances": 500,
    }


def test_the_survey_names_each_render_product_with_its_kind_and_size():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Camera.Define(stage, "/World/Cam")
    stage.DefinePrim("/World/Lidar", "OmniLidar")
    sensor = UsdGeom.Camera.Define(stage, "/World/OldLidar").GetPrim()
    sensor.CreateAttribute("cameraSensorType", Sdf.ValueTypeNames.Token).Set("lidar")
    for name, camera, size in (("Cam", "/World/Cam", (1280, 720)), ("Lidar", "/World/Lidar", None)):
        product = UsdRender.Product.Define(stage, f"/Render/{name}")
        product.CreateCameraRel().SetTargets([camera])
        if size:
            product.CreateResolutionAttr(Gf.Vec2i(*size))
    old = UsdRender.Product.Define(stage, "/Render/Old")
    old.CreateCameraRel().SetTargets(["/World/OldLidar"])
    UsdRender.Product.Define(stage, "/Render/Bare")
    # A blocked resolution reads none, not even the schema's fallback.
    UsdRender.Product.Define(stage, "/Render/Blocked").CreateResolutionAttr().Block()

    products = survey(stage).products
    assert products == [
        {"path": "/Render/Cam", "kind": "camera", "resolution": [1280, 720]},
        {"path": "/Render/Lidar", "kind": "lidar", "resolution": [2048, 1080]},
        {"path": "/Render/Old", "kind": "lidar", "resolution": [2048, 1080]},
        {"path": "/Render/Bare", "kind": "render product", "resolution": [2048, 1080]},
        {"path": "/Render/Blocked", "kind": "render product", "resolution": None},
    ]


def test_the_survey_notes_the_first_physics_scene_so_the_stage_is_walked_once():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdPhysics.Scene.Define(stage, "/World/Second")
    scene = survey(stage).scene
    assert scene is not None
    assert scene.GetPath() == "/World/PhysicsScene"


# ---- the notes and the answer ----


def test_eco_mode_on_a_still_timeline_gets_a_note():
    # Isaac Sim's throttling turns eco mode on at stop and pause, and RTX may then skip a still stage (round 1, P4).
    note = eco_note(True, "stopped")
    assert note is not None
    assert "measure while it plays" in note
    assert eco_note(True, "paused") == note
    assert eco_note(True, "playing") is None
    assert eco_note(False, "stopped") is None
    assert eco_note(None, "stopped") is None


CONDITIONS = {
    "gpu": "NVIDIA RTX 6000 Pro",
    "kit_app_name": "Isaac-Sim Python",
    "kit_app_version": "6.2.0",
    "kit_version": "110.4.0",
    "renderer": "rtx",
    "render_mode": "RaytracedLighting",
    "timeline": "playing",
    "headless": True,
    "fixed_time_stepping": True,
    "time_codes_per_second": 60.0,
    "rate_limit": True,
    "rate_limit_frequency": 60,
    "rate_limit_lifted": True,
    "async_rendering": False,
    "eco_mode": False,
    "sleep_ms_on_focus": 0,
    "sleep_ms_out_of_focus": 0,
}


def _answer(**changes: Any) -> dict[str, Any]:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Mesh.Define(stage, "/World/Ground")
    given: dict[str, Any] = {
        "args": PerformanceArgs(4, 30),
        "samples_ms": [40.0, 42.0, 41.0, 43.0],
        "gpu_ms": [30.0, 31.0, 32.0, 33.0],
        "gpu_missing": None,
        "physics": physics([5.0] * 8, frames=4, wall_seconds=0.166, step_seconds=1 / 120),
        "memory": gpu_memory([{"description": "NVIDIA RTX 6000 Pro", "usage": 1 << 30, "budget": 4 << 30}]),
        "survey": survey(stage),
        "conditions": dict(CONDITIONS),
        "ran_out": None,
        "recording": False,
    }
    given.update(changes)
    return answer(**given)


def test_the_answer_holds_every_number_and_the_conditions():
    r = _answer()
    assert (r["frames"], r["warmup"], r["measured_frames"]) == (4, 30, 4)
    assert r["app"]["mean_ms"] == pytest.approx(41.5)
    assert r["halves"] == {"first_ms": 41.0, "second_ms": 42.0, "settled": True}
    assert r["gpu_render"]["mean_ms"] == pytest.approx(31.5)
    assert r["physics"]["steps"] == 8
    assert r["gpu_memory"]["used_bytes"] == 1 << 30
    assert r["stage"]["meshes"] == 1
    assert r["render_products"] == []
    assert r["conditions"] == CONDITIONS
    assert r["notes"] == []


def test_halves_that_drift_add_a_not_settled_note():
    r = _answer(samples_ms=[40.0, 40.0, 50.0, 50.0])
    assert r["halves"]["settled"] is False
    (note,) = r["notes"]
    assert note.startswith("not settled: the second half's mean frame time is 25% above the first's")
    assert note.endswith("measure again")


def test_the_not_settled_share_is_of_the_smaller_half_as_settled_reads_it():
    # 50.0 then 45.4 ms: 4.6 is 10.1% of 45.4, so not settled; of the first half it would read 9%, under the line.
    r = _answer(samples_ms=[50.0, 50.0, 45.4, 45.4])
    assert r["halves"]["settled"] is False
    (note,) = r["notes"]
    assert note.startswith("not settled: the second half's mean frame time is 10% below the first's")


def test_a_first_half_that_took_no_time_still_gets_its_note():
    r = _answer(samples_ms=[0.0, 0.0, 5.0, 5.0])
    (note,) = r["notes"]
    assert note.startswith("not settled: the second half's mean frame time is above the first's")


def test_zero_samples_are_answered_with_no_statistics():
    # The 90 s went to loading (round 1, P5): no division by zero, no empty numbers.
    r = _answer(samples_ms=[], gpu_ms=[], ran_out="loading", physics=physics([], 0, 0.0, 1 / 60))
    assert r["app"] is None
    assert r["app_missing"] == "the 90 s this call may take ran out while the stage was still loading"
    assert "halves" not in r
    assert r["measured_frames"] == 0
    assert r["gpu_render"] == {"missing": "no frame was timed"}


def test_time_spent_waiting_for_the_viewport_is_said():
    # A capture, a save or another measurement held the viewport lock until the call's time was gone.
    r = _answer(samples_ms=[], gpu_ms=[], ran_out="waiting")
    assert r["app_missing"] == (
        "the 90 s this call may take ran out while a capture, a save or another measurement held the viewport"
    )


def test_a_measurement_cut_short_says_how_many_frames_it_got():
    r = _answer(samples_ms=[40.0, 41.0], gpu_ms=[30.0, 31.0], ran_out="timing")
    assert r["measured_frames"] == 2
    assert r["notes"] == ["the 90 s this call may take ran out after 2 of 4 frames: the numbers are of those"]


def test_a_warm_up_cut_short_is_said():
    r = _answer(samples_ms=[], gpu_ms=[], ran_out="warming")
    assert r["app_missing"] == "the 90 s this call may take ran out during the warm-up of 30 updates"
    # Out of time on the update that started the clock, before an interval was kept.
    r = _answer(samples_ms=[], gpu_ms=[], ran_out="timing")
    assert r["app_missing"] == "the 90 s this call may take ran out before a frame was timed"


@pytest.mark.parametrize(
    ("changes", "key", "missing"),
    [
        ({"gpu_ms": None, "gpu_missing": "not available in this app"}, "gpu_render", "not available in this app"),
        ({"gpu_ms": [0.0] * 4}, "gpu_render", None),
        ({"physics": {"missing": "the timeline is stopped"}}, "physics", "the timeline is stopped"),
        ({"memory": {"missing": "not available in this app"}}, "gpu_memory", "not available in this app"),
    ],
)
def test_each_number_kit_cant_give_says_so_and_the_rest_stay(changes, key, missing):
    r = _answer(**changes)
    assert "missing" in r[key]
    if missing is not None:
        assert r[key]["missing"] == missing
    assert r["app"]["mean_ms"] == pytest.approx(41.5)
    for other in {"gpu_render", "physics", "gpu_memory"} - {key}:
        assert "missing" not in r[other]


def test_eco_mode_on_a_stopped_timeline_and_a_recording_add_their_notes():
    conditions = {**CONDITIONS, "timeline": "stopped", "eco_mode": True}
    r = _answer(conditions=conditions, recording=True, physics={"missing": "the timeline is stopped"})
    assert len(r["notes"]) == 2
    assert r["notes"][0] == eco_note(True, "stopped")
    assert r["notes"][1].startswith("a recording is running")
