"""
/sim/performance: get_performance's measurement of the app loop, the GPU and physics (#156).

It times Kit's updates as Isaac Sim's own benchmark recorders do (isaacsim.benchmark.services), without depending on
them: frames + 1 updates through the bridge's one update observer, the first interval dropped; Hydra's GPU time on each
of those updates; and, while the timeline plays, each physics step's time from PhysX's benchmarks interface. Kit's
frame-rate limiter is lifted for the measurement and put back after, whatever happens (the maintainer's call, #156's
Q1), and the capture feed kept between captures is released first and the viewport lock held throughout, so a kept
feed's render doesn't count and no capture starts meanwhile. The numbers and the answer are core/performance.py's.

Everything runs on Kit's main thread, as every handler does, awaiting updates and never blocking them: Kit renders on
while it measures.
"""

import asyncio
import time
from typing import Any

import carb
import omni.timeline
import omni.usd

from ovmcp.core import capture
from ovmcp.core import performance as core
from ovmcp.core.force import scene_step
from ovmcp.core.performance import (
    PerformanceArgs,
    StepTally,
    answer,
    gpu_frame_ms,
    gpu_memory,
    performance_args,
    physics,
    still_loading,
    survey,
)
from ovmcp.core.protocol import kit_app

from ._updates import on_update
from ._utils import _get_stage
from .camera_feed import without_kept_feed
from .recording import recording_active

# Kit's frame-rate limiter, the setting Isaac Sim's own benchmarks turn off: on, the loop sleeps at the end of each
# update to hold the rate at rateLimitFrequency, and a light stage would read the cap, not its speed.
RATE_LIMIT = "/app/runLoops/main/rateLimitEnabled"
RATE_LIMIT_FREQUENCY = "/app/runLoops/main/rateLimitFrequency"

# What Kit's bindings raise when a reading fails, so that reading reads "not available" and the rest still come.
_KIT_ERRORS = (RuntimeError, ValueError, AttributeError, KeyError, TypeError, IndexError)

# The measurement's clock: a name of its own, so the tests can move it and leave asyncio's.
_clock = time.perf_counter


class _Measurement:
    """One measurement on Kit's updates, in phases: waiting for the viewport lock until its first update, the stage
    loading, the warm-up, then the timed frames. The update that ends the warm-up starts the clock; each of the next
    frames + 1 updates gives an interval, the GPU's time and, from the second, the physics steps it carried, so the
    first, which Isaac Sim's recorder drops, can be dropped with all it carried."""

    def __init__(self, args: PerformanceArgs) -> None:
        self.args = args
        # The call's time starts before the viewport lock is taken, which a capture, a save or another measurement may
        # hold: until the first update the measurement observes, its time goes to that wait.
        self.phase = "waiting"
        self.warmed = 0
        self.last = 0.0
        self.samples: list[float] = []
        self.gpu: list[float] = []
        self.gpu_stats: Any = None
        self.gpu_missing: str | None = None
        self.tally = StepTally()
        self.physics: Any = None
        self.guard: Any = None
        self.done: asyncio.Future[None] = asyncio.get_running_loop().create_future()

    def subscribe_physics(self) -> str | None:
        """Takes each physics step's profile stats from here on; why it can't, or None. The callback only adds numbers
        up: no USD, no logging, whatever thread PhysX calls it on (#5)."""
        interface, missing = _physics_benchmarks()
        if interface is None:
            return missing
        try:
            self.physics = interface.subscribe_profile_stats_events(self.tally.add)
        except _KIT_ERRORS as e:
            return f"not available: PhysX's benchmarks interface wouldn't subscribe: {e}"
        return None

    def start(self) -> None:
        self.guard = on_update("performance", self._tick)

    def stop(self) -> None:
        """Drops the update observer and the physics subscription; safe twice."""
        self.guard = None
        self.physics = None
        self.tally.counting = False

    def _finish(self, error: BaseException | None = None) -> None:
        self.phase = "done"
        self.stop()
        if not self.done.done():
            if error is None:
                self.done.set_result(None)
            else:
                self.done.set_exception(RuntimeError(f"The measurement failed on an update: {error}"))

    def _tick(self) -> None:
        # A callback that raises is Kit's to log, every update after: a failure ends the measurement instead.
        try:
            self._step(_clock())
        except _KIT_ERRORS as e:
            self._finish(e)

    def _step(self, now: float) -> None:
        if self.phase == "waiting":
            self.phase = "loading"
        if self.phase == "loading":
            if still_loading(omni.usd.get_context().get_stage_loading_status()):
                return
            self.phase = "warming"
        if self.phase == "warming":
            if self.warmed < self.args.warmup:
                self.warmed += 1
                return
            self.phase = "timing"
            self.last = now
            return
        if self.phase != "timing":
            return
        self.samples.append((now - self.last) * 1000.0)
        self.last = now
        self._sample_gpu()
        # Physics steps run before this observer in an update, so those counted from here on are the next updates':
        # the first interval's are left out with it.
        self.tally.counting = len(self.samples) <= self.args.frames
        if len(self.samples) > self.args.frames:
            self._finish()

    def _sample_gpu(self) -> None:
        if self.gpu_stats is None:
            return
        try:
            self.gpu.append(gpu_frame_ms(self.gpu_stats.get_gpu_profiler_result()))
        except _KIT_ERRORS as e:
            self.gpu_stats = None
            self.gpu_missing = f"not available: Hydra's GPU profiler failed: {e}"


def _physics_benchmarks() -> tuple[Any, str | None]:
    """PhysX's benchmarks interface: omni.physics.core's where it imports (Isaac Sim 6.x), else omni.physx's (Isaac Sim
    5.x, and 6.2 still has it), as Isaac Sim's own recorders read them; or why there is none."""
    try:
        from omni.physics.core import get_physics_benchmarks_interface as get_interface
    except ImportError:
        try:
            from omni.physx import get_physx_benchmarks_interface as get_interface
        except ImportError:
            return None, "not available in this app: it has neither omni.physics.core nor omni.physx"
    try:
        return get_interface(), None
    except _KIT_ERRORS as e:
        return None, f"not available: PhysX's benchmarks interface failed: {e}"


def _hydra() -> tuple[Any, Any, str | None]:
    """Hydra's engine stats, for the GPU's time a frame, and its get_device_info, for the GPU and its memory; or why
    not. USD Composer and other Kit apps may lack the extension."""
    try:
        from omni.hydra.engine.stats import HydraEngineStats, get_device_info
    except ImportError:
        return None, None, "not available in this app: it has no omni.hydra.engine.stats"
    try:
        return HydraEngineStats(), get_device_info, None
    except _KIT_ERRORS as e:
        return None, get_device_info, f"not available: Hydra's engine stats failed: {e}"


def _memory(get_device_info: Any) -> dict[str, object]:
    if get_device_info is None:
        return {"missing": "not available in this app: it has no omni.hydra.engine.stats"}
    try:
        return gpu_memory(list(get_device_info()))
    except _KIT_ERRORS as e:
        return {"missing": f"not available: Hydra's device info failed: {e}"}


def _timeline_state(timeline: Any) -> str:
    if timeline.is_playing():
        return "playing"
    return "stopped" if timeline.is_stopped() else "paused"


def _conditions(settings: Any, timeline: Any, state: str) -> dict[str, object]:
    """What two measurements are compared under, read before the limiter is lifted: the Kit app, the renderer, the
    timeline and its step, whether Kit has a window, the limiter, and what Isaac Sim's throttling turns on and off
    around play and stop (async rendering, eco mode, the renderer's sleeps)."""

    def read(path: str) -> Any:
        try:
            return settings.get(path)
        except _KIT_ERRORS:
            return None

    window = read("/app/window/enabled")
    limit = read(RATE_LIMIT)
    return {
        **kit_app(),
        "renderer": read("/renderer/active"),
        "render_mode": read("/rtx/rendermode"),
        "timeline": state,
        # Kit's --no-window, as Isaac Sim's headless start sets it; Kit's own file dialogs read it so.
        "headless": (window is False) if isinstance(window, bool) else None,
        "fixed_time_stepping": read("/app/player/useFixedTimeStepping"),
        "time_codes_per_second": timeline.get_time_codes_per_seconds(),
        "rate_limit": limit,
        "rate_limit_frequency": read(RATE_LIMIT_FREQUENCY),
        # Only a limiter that is on is lifted: one off, or not set, is left as it is.
        "rate_limit_lifted": limit is True,
        "async_rendering": read("/app/asyncRendering"),
        "eco_mode": read("/rtx/ecoMode/enabled"),
        "sleep_ms_on_focus": read("/app/renderer/sleepMsOnFocus"),
        "sleep_ms_out_of_focus": read("/app/renderer/sleepMsOutOfFocus"),
    }


async def handle_performance(body: dict) -> dict:
    try:
        args = performance_args(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    try:
        _get_stage()
    except RuntimeError as e:
        return {"status": "error", "error": str(e)}
    # Read when the call starts, so a test can shorten it; the wait for the lock counts, so the call stays under it.
    seconds = core.CALL_SECONDS
    budget = capture.Budget(seconds)
    try:
        async with without_kept_feed():
            return await _measure(args, budget, seconds)
    except _KIT_ERRORS as e:
        return {"status": "error", "error": str(e)}


async def _measure(args: PerformanceArgs, budget: capture.Budget, seconds: float) -> dict:
    settings = carb.settings.get_settings()
    timeline = omni.timeline.get_timeline_interface()
    state = _timeline_state(timeline)
    conditions = _conditions(settings, timeline, state)
    recording = recording_active()
    measurement = _Measurement(args)
    measurement.gpu_stats, get_device_info, measurement.gpu_missing = _hydra()
    if state == "playing":
        physics_missing = measurement.subscribe_physics()
    else:
        physics_missing = f"not measured: the timeline is {state}, so physics doesn't step; play it and measure again"
    lifted = conditions["rate_limit_lifted"] is True
    ran_out = None
    try:
        if lifted:
            settings.set(RATE_LIMIT, False)
        measurement.start()
        try:
            await capture.bounded(measurement.done, seconds, budget)
        except capture.CaptureError:
            # Out of time: answered with what was measured, and the phase it ran out in.
            ran_out = measurement.phase
    finally:
        measurement.stop()
        if lifted:
            settings.set(RATE_LIMIT, True)

    kept = measurement.samples[1:]
    wall_seconds = sum(kept) / 1000.0
    stage = _get_stage()
    found = survey(stage)
    if physics_missing is None:
        try:
            # The survey's walk found the scene, so the stage isn't walked again for it.
            numbers = physics(measurement.tally.step_ms, len(kept), wall_seconds, scene_step(found.scene).seconds)
        except ValueError as e:
            numbers = {"missing": f"not measured: the physics scene's step can't be used: {e}"}
    else:
        numbers = {"missing": physics_missing}
    memory = _memory(get_device_info)
    conditions["gpu"] = memory.get("device")
    result = answer(
        args=args,
        samples_ms=kept,
        gpu_ms=measurement.gpu[1:] if measurement.gpu_missing is None else None,
        gpu_missing=measurement.gpu_missing,
        physics=numbers,
        memory=memory,
        survey=found,
        conditions=conditions,
        ran_out=ran_out,
        recording=recording,
        seconds=seconds,
    )
    return {"status": "success", "result": result}
