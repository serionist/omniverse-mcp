"""The get_performance handler against a fake Kit (#156): its bounds refused before anything changes, frames + 1
updates timed with the first interval dropped, the wait for the stage to load and its bound, the kept capture feed
released under the viewport lock, a running recording named, PhysX's benchmarks interface from omni.physics.core and
else omni.physx, the frame-rate limiter put back after an answer, an error, the time limit and a cancelled request,
and every subscription dropped.

handlers/performance.py is loaded from its file with Kit's modules, its _utils, its camera feed and its recording
faked in sys.modules, as tests/test_recording_handler.py loads its handler; its update observer is the real
handlers/_updates.py on conftest's FakeUpdates. The core is the real one. The handler's clock is the fake Kit's, which
each update moves on.
"""

import asyncio
import contextlib
import importlib.util
import sys
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Usd, UsdGeom

from ovmcp.core import performance as core

from .conftest import EXTENSION_ROOT, FakeUpdates, load_updates

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "performance.py"
LIMIT = "/app/runLoops/main/rateLimitEnabled"


class FakeSettings:
    """carb.settings as the handler uses it: what each path holds, and each set, in the Kit's log."""

    def __init__(self, kit: "FakeKit") -> None:
        self.kit = kit
        self.values: dict[str, Any] = {
            LIMIT: True,
            "/app/runLoops/main/rateLimitFrequency": 60,
            "/renderer/active": "rtx",
            "/rtx/rendermode": "RaytracedLighting",
            "/app/window/enabled": False,
            "/app/player/useFixedTimeStepping": True,
            "/app/asyncRendering": False,
            "/rtx/ecoMode/enabled": False,
            "/app/renderer/sleepMsOnFocus": 0,
            "/app/renderer/sleepMsOutOfFocus": 0,
        }

    def get(self, path: str) -> Any:
        return self.values.get(path)

    def set(self, path: str, value: Any) -> None:
        self.kit.log.append(("set", path, value))
        self.values[path] = value


class FakeSubscription:
    """A carb subscription: PhysX stops calling back once it is dropped."""

    def __init__(self, benchmarks: "FakeBenchmarks", callback: Any) -> None:
        self.benchmarks = benchmarks
        benchmarks.callbacks.append(callback)
        self.callback = callback

    def __del__(self) -> None:
        self.benchmarks.callbacks.remove(self.callback)


class FakeBenchmarks:
    """PhysX's benchmarks interface: the profile stats it sends with each step's fetch."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.callbacks: list[Any] = []
        self.subscribed = 0

    def subscribe_profile_stats_events(self, callback: Any) -> FakeSubscription:
        self.subscribed += 1
        return FakeSubscription(self, callback)

    def step(self, ms: float) -> None:
        stats = [SimpleNamespace(zone_name="Simulation", ms=ms / 2), SimpleNamespace(zone_name="PhysX Update", ms=ms)]
        for callback in list(self.callbacks):
            callback(stats)


class FakeHydra:
    """omni.hydra.engine.stats: one device, its profiler's top-level pass the GPU time the Kit gives this update."""

    def __init__(self, kit: "FakeKit") -> None:
        self.kit = kit

    def engine_stats(self) -> Any:
        """HydraEngineStats(), whose profiler gives the update's GPU time."""
        return SimpleNamespace(
            get_gpu_profiler_result=lambda: [[{"name": "frame", "indent": 0, "duration": self.kit.gpu_ms}]]
        )

    def get_device_info(self) -> list[dict[str, Any]]:
        return [{"description": "Invented GPU", "usage": 2 << 30, "budget": 16 << 30}]


class FakeKit:
    """Kit as the handler sees it: the stage and whether it still loads, the timeline, the settings, the update event,
    the clock each update moves on, PhysX's steps and Hydra's GPU time; and, in order, what changed the Kit."""

    def __init__(self) -> None:
        self.stage = Usd.Stage.CreateInMemory()
        UsdGeom.Mesh.Define(self.stage, "/World/Ground")
        self.loading_left = 0
        self.loading_raises = False
        self.playing = True
        self.now = 100.0
        self.gpu_ms = 5.0
        self.log: list[Any] = []
        self.settings = FakeSettings(self)
        self.updates = FakeUpdates()
        self.physics = FakeBenchmarks("omni.physics.core")
        self.physx = FakeBenchmarks("omni.physx")
        self.hydra = FakeHydra(self)
        self.recording = False
        self.count = 0

    def loading_status(self) -> tuple[str, int, int]:
        if self.loading_raises:
            raise RuntimeError("the stage is gone")
        return ("Loading", 1, 4) if self.loading_left > 0 else ("", 0, 0)

    def update(self, ms: float = 10.0, step_ms: float | None = 2.0, gpu_ms: float = 5.0) -> None:
        """One Kit update `ms` after the last: the physics step first, while playing, then the update's observers."""
        self.count += 1
        self.now += ms / 1000
        self.gpu_ms = gpu_ms
        if self.playing and step_ms is not None:
            self.physics.step(step_ms)
            self.physx.step(step_ms)
        self.updates.update()
        self.loading_left = max(0, self.loading_left - 1)

    @contextlib.asynccontextmanager
    async def without_kept_feed(self) -> AsyncIterator[None]:
        self.log.append("lock taken, kept feed released")
        try:
            yield
        finally:
            # As camera_feed's own: its lock is an `async with`, let go whatever ends the block.
            self.log.append("lock let go")


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def handler(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    timeline = SimpleNamespace(
        is_playing=lambda: kit.playing, is_stopped=lambda: not kit.playing, get_time_codes_per_seconds=lambda: 60.0
    )
    context = SimpleNamespace(get_stage_loading_status=kit.loading_status, get_stage=lambda: kit.stage)
    kit_app = _module("omni.kit.app", **FakeUpdates.APP)
    dispatcher = _module("carb.eventdispatcher", get_eventdispatcher=lambda: kit.updates)
    usd = _module("omni.usd", get_context=lambda: context)
    omni_timeline = _module("omni.timeline", get_timeline_interface=lambda: timeline)
    omni_kit = _module("omni.kit", app=kit_app)
    physics_core = _module("omni.physics.core", get_physics_benchmarks_interface=lambda: kit.physics)
    physx = _module("omni.physx", get_physx_benchmarks_interface=lambda: kit.physx)
    stats = _module(
        "omni.hydra.engine.stats",
        HydraEngineStats=kit.hydra.engine_stats,
        get_device_info=kit.hydra.get_device_info,
    )
    fakes = {
        "carb": _module(
            "carb",
            settings=SimpleNamespace(get_settings=lambda: kit.settings),
            eventdispatcher=dispatcher,
            log_warn=lambda _m: None,
        ),
        "carb.eventdispatcher": dispatcher,
        "omni": _module("omni", kit=omni_kit, usd=usd, timeline=omni_timeline),
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.timeline": omni_timeline,
        "omni.usd": usd,
        "omni.physics": _module("omni.physics"),
        "omni.physics.core": physics_core,
        "omni.physx": physx,
        "omni.hydra": _module("omni.hydra"),
        "omni.hydra.engine": _module("omni.hydra.engine"),
        "omni.hydra.engine.stats": stats,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module("handlers_under_test._utils", _get_stage=lambda: kit.stage),
        "handlers_under_test.camera_feed": _module(
            "handlers_under_test.camera_feed", without_kept_feed=kit.without_kept_feed
        ),
        "handlers_under_test.recording": _module(
            "handlers_under_test.recording", recording_active=lambda: kit.recording
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, "handlers_under_test._updates", load_updates())
    spec = importlib.util.spec_from_file_location("handlers_under_test.performance", HANDLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_clock", lambda: kit.now)
    return module


async def _settle() -> None:
    """Lets every task that can run, run."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _measure(handler: Any, kit: FakeKit, body: dict[str, Any], updates: list[dict[str, Any]]) -> dict[str, Any]:
    """The handler's answer to `body`, with Kit updating as `updates` says, one update each, until it answers."""
    task = asyncio.ensure_future(handler.handle_performance(body))
    await _settle()
    for update in updates:
        if task.done():
            break
        kit.update(**update)
        await _settle()
    return await asyncio.wait_for(task, 5)


def _run(handler: Any, kit: FakeKit, body: dict[str, Any], updates: list[dict[str, Any]]) -> dict[str, Any]:
    return asyncio.run(_measure(handler, kit, body, updates))


def _steady(count: int, ms: float = 10.0) -> list[dict[str, Any]]:
    return [{"ms": ms}] * count


# ---- the request ----


@pytest.mark.parametrize("body", [{"frames": 1}, {"frames": 2001}, {"warmup": -1}, {"warmup": 601}, {"frames": "120"}])
def test_bounds_are_refused_before_anything_changes(handler, kit, body):
    r = _run(handler, kit, body, _steady(5))
    assert r["status"] == "error"
    assert "must be a whole number" in r["error"]
    assert kit.log == []  # no lock taken, no setting changed
    assert kit.updates.made == 0
    assert kit.physics.subscribed == 0


# ---- the frames ----


def test_frames_and_one_updates_are_timed_and_the_first_interval_dropped(handler, kit):
    # The update that ends the warm-up starts the clock; the next one's interval is the first, and dropped, as Isaac
    # Sim's recorder drops it, with the steps and the GPU time of that update.
    updates = [
        {"ms": 10.0},  # warm-up done (warmup 0): the clock starts
        {"ms": 500.0, "step_ms": 99.0, "gpu_ms": 77.0},  # the first interval: dropped
        {"ms": 10.0, "step_ms": 3.0, "gpu_ms": 4.0},
        {"ms": 20.0, "step_ms": 3.0, "gpu_ms": 6.0},
        {"ms": 30.0, "step_ms": 3.0, "gpu_ms": 4.0},
        {"ms": 40.0, "step_ms": 3.0, "gpu_ms": 6.0},
        *_steady(10),
    ]
    r = _run(handler, kit, {"frames": 4, "warmup": 0}, updates)
    assert r["status"] == "success", r
    assert kit.count == 6  # 1 to start the clock, frames + 1 timed
    result = r["result"]
    assert result["measured_frames"] == 4
    app = result["app"]
    assert app["mean_ms"] == pytest.approx(25.0)
    assert app["worst_ms"] == pytest.approx(40.0)
    assert result["gpu_render"] == {"mean_ms": pytest.approx(5.0), "p95_ms": pytest.approx(6.0)}
    phys = result["physics"]
    assert phys["steps"] == 4
    assert phys["step_ms"] == pytest.approx(3.0)
    assert phys["wall_seconds"] == pytest.approx(0.1)
    # The stage has no physics scene: PhysX's 60 steps a second, so 4 steps simulate 1/15 s.
    assert phys["simulated_seconds"] == pytest.approx(4 / 60)
    assert result["gpu_memory"] == {"device": "Invented GPU", "used_bytes": 2 << 30, "budget_bytes": 16 << 30}
    assert result["stage"]["meshes"] == 1


def test_the_warm_up_passes_before_the_clock_starts(handler, kit):
    r = _run(handler, kit, {"frames": 2, "warmup": 5}, [*_steady(5, ms=900.0), *_steady(10)])
    assert r["status"] == "success", r
    assert kit.count == 5 + 1 + 3
    assert r["result"]["app"]["worst_ms"] == pytest.approx(10.0)


def test_the_stage_finishes_loading_before_the_warm_up_starts(handler, kit):
    kit.loading_left = 3
    r = _run(handler, kit, {"frames": 2, "warmup": 2}, [*_steady(3, ms=900.0), *_steady(20)])
    assert r["status"] == "success", r
    # 3 updates loading, the 4th ends loading and is the warm-up's first, the 5th its second, the 6th starts the clock.
    assert kit.count == 3 + 2 + 1 + 3
    assert r["result"]["app"]["worst_ms"] == pytest.approx(10.0)


def test_a_stage_that_never_finishes_loading_is_answered_at_the_time_limit(handler, kit, monkeypatch):
    monkeypatch.setattr(core, "CALL_SECONDS", 0.2)
    kit.loading_left = 10**9

    async def scenario() -> dict[str, Any]:
        task = asyncio.ensure_future(handler.handle_performance({"frames": 2, "warmup": 0}))
        while not task.done():
            kit.update()
            await asyncio.sleep(0.01)
        return await task

    r = asyncio.run(scenario())
    assert r["status"] == "success", r
    result = r["result"]
    assert result["app"] is None
    assert result["app_missing"] == "the 0.2 s this call may take ran out while the stage was still loading"
    assert result["measured_frames"] == 0
    assert kit.settings.values[LIMIT] is True
    assert kit.updates.observers == []


def test_a_measurement_cut_short_answers_the_frames_it_got(handler, kit, monkeypatch):
    monkeypatch.setattr(core, "CALL_SECONDS", 0.3)

    async def scenario() -> dict[str, Any]:
        task = asyncio.ensure_future(handler.handle_performance({"frames": 2000, "warmup": 0}))
        for _ in range(8):
            await asyncio.sleep(0.01)
            kit.update()
        return await task

    r = asyncio.run(scenario())
    assert r["status"] == "success", r
    result = r["result"]
    assert result["measured_frames"] == 6  # 8 updates: the clock's start, the first interval, then 6
    assert result["notes"][0] == "the 0.3 s this call may take ran out after 6 of 2000 frames: the numbers are of those"
    assert kit.settings.values[LIMIT] is True


# ---- the lock, the limiter and the subscriptions ----


def test_the_limiter_is_lifted_inside_the_viewport_lock_and_put_back(handler, kit):
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert kit.log == [
        "lock taken, kept feed released",
        ("set", LIMIT, False),
        ("set", LIMIT, True),
        "lock let go",
    ]
    conditions = r["result"]["conditions"]
    assert (conditions["rate_limit"], conditions["rate_limit_frequency"], conditions["rate_limit_lifted"]) == (
        True,
        60,
        True,
    )
    assert conditions["headless"] is True
    assert conditions["timeline"] == "playing"
    assert conditions["gpu"] == "Invented GPU"


def test_a_limiter_kit_doesnt_set_is_left_alone(handler, kit):
    del kit.settings.values[LIMIT]
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert [entry for entry in kit.log if isinstance(entry, tuple)] == []
    assert r["result"]["conditions"]["rate_limit_lifted"] is False


def test_the_limiter_is_put_back_after_an_error(handler, kit):
    kit.loading_raises = True
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "error"
    assert "the stage is gone" in r["error"]
    assert kit.log[-2:] == [("set", LIMIT, True), "lock let go"]
    assert kit.updates.observers == []
    assert kit.physics.callbacks == []


def test_the_limiter_is_put_back_when_the_request_is_cancelled(handler, kit):
    async def scenario() -> None:
        task = asyncio.ensure_future(handler.handle_performance({"frames": 50, "warmup": 0}))
        await _settle()
        kit.update()
        kit.update()
        await _settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert kit.settings.values[LIMIT] is True
    assert kit.log[-1] == "lock let go"
    assert kit.updates.observers == []
    assert kit.physics.callbacks == []


def test_every_subscription_is_dropped_after_the_answer(handler, kit):
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert kit.updates.made == 1
    assert kit.updates.observers == []
    assert kit.physics.subscribed == 1
    assert kit.physics.callbacks == []


# ---- PhysX, Hydra and the conditions ----


def test_physics_comes_from_omni_physx_where_omni_physics_core_doesnt_import(handler, kit, monkeypatch):
    # Isaac Sim 5.x has no omni.physics.core; its recorder reads omni.physx's interface (round 1, P3).
    monkeypatch.setitem(sys.modules, "omni.physics.core", None)
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert (kit.physics.subscribed, kit.physx.subscribed) == (0, 1)
    assert r["result"]["physics"]["steps"] == 2
    assert kit.physx.callbacks == []


def test_physics_core_is_read_first_where_both_import(handler, kit):
    _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert (kit.physics.subscribed, kit.physx.subscribed) == (1, 0)


def test_a_kit_without_physx_or_hydra_says_each_is_not_available(handler, kit, monkeypatch):
    for name in ("omni.physics.core", "omni.physx", "omni.hydra.engine.stats"):
        monkeypatch.setitem(sys.modules, name, None)
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    result = r["result"]
    assert result["physics"]["missing"].startswith("not available in this app")
    assert result["gpu_render"]["missing"].startswith("not available in this app")
    assert result["gpu_memory"]["missing"].startswith("not available in this app")
    assert result["app"]["mean_ms"] == pytest.approx(10.0)
    assert result["conditions"]["gpu"] is None


def test_a_stopped_timeline_measures_no_physics_and_says_why(handler, kit):
    kit.playing = False
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert kit.physics.subscribed == 0
    missing = r["result"]["physics"]["missing"]
    assert "the timeline is stopped" in missing
    assert "play it" in missing


def test_a_running_recording_is_named(handler, kit):
    kit.recording = True
    r = _run(handler, kit, {"frames": 2, "warmup": 0}, _steady(10))
    assert r["status"] == "success", r
    assert core.RECORDING_NOTE in r["result"]["notes"]
