"""get_performance's numbers (#156): the app loop's frame times and their statistics, the two halves that say whether
they settled, the physics step and the simulated-to-real ratio, Hydra's GPU times and memory, the stage's counts and
render products, and the answer that puts them beside the conditions two measurements are compared under.

Kit-free, so unit-tested without Kit: handlers/performance.py reads Kit and passes the readings in. The numbers are
read the way Isaac Sim's own benchmark recorders read them (isaacsim.benchmark.services), without depending on them.
"""

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import NamedTuple, Protocol

from pxr import Sdf, Tf, Usd, UsdGeom, UsdRender

DEFAULT_FRAMES = 120
DEFAULT_WARMUP = 30
# Two at least: the first interval is dropped, and one frame would leave none (#156's round 1, P5).
FRAMES_RANGE = (2, 2000)
WARMUP_RANGE = (0, 600)

# The most one measurement takes, its wait for the stage to load and its warm-up included: under the server's 120 s,
# with time left to answer. Read when a call starts, so a test can shorten it.
CALL_SECONDS = 90.0

# How far apart the two halves' mean frame times may be, as a share of the smaller, before the measurement counts as
# not settled: a stage still streaming in, compiling shaders or warming caches reads slower in its first half.
SETTLED_SHARE = 0.10

# The profiling zone omni.physics.core and omni.physx report once per physics step, on its fetch, with the step's
# time: what Isaac Sim's physics_frametime recorder reads.
STEP_ZONE = "PhysX Update"


class PerformanceArgs(NamedTuple):
    frames: int
    warmup: int


def _whole(name: str, value: object, bounds: tuple[int, int]) -> int:
    low, high = bounds
    # bool is an int to Python, and True would pass as 1.
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be a whole number from {low} to {high}, got {value!r}")
    return value


def performance_args(body: Mapping[str, object]) -> PerformanceArgs:
    """The request's `frames` and `warmup`, checked before anything in Kit changes; a ValueError names the one at
    fault."""
    return PerformanceArgs(
        _whole("frames", body.get("frames", DEFAULT_FRAMES), FRAMES_RANGE),
        _whole("warmup", body.get("warmup", DEFAULT_WARMUP), WARMUP_RANGE),
    )


# ---- the frame times ----


class Summary(NamedTuple):
    """Frame times' statistics, in milliseconds, and the frames a second their mean makes."""

    fps: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    worst_ms: float


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _rank(ordered: Sequence[float], share: float) -> float:
    """The nearest-rank percentile: a value measured, never one between two."""
    return ordered[max(1, math.ceil(share * len(ordered))) - 1]


def summarise(samples_ms: Sequence[float]) -> Summary | None:
    """The mean, the 50th and 95th percentiles and the worst of `samples_ms`; None for no samples."""
    if not samples_ms:
        return None
    ordered = sorted(samples_ms)
    mean = _mean(samples_ms)
    return Summary(1000.0 / mean if mean > 0 else 0.0, mean, _rank(ordered, 0.5), _rank(ordered, 0.95), ordered[-1])


def halves(samples_ms: Sequence[float]) -> tuple[float, float] | None:
    """The mean frame times of the first and the second half, in the order measured; None under two samples."""
    if len(samples_ms) < 2:
        return None
    middle = len(samples_ms) // 2
    return _mean(samples_ms[:middle]), _mean(samples_ms[middle:])


def settled(first: float, second: float) -> bool:
    """Whether the halves' means are within SETTLED_SHARE of the smaller, either way round."""
    return max(first, second) <= (1 + SETTLED_SHARE) * min(first, second)


def ratio(simulated_seconds: float, wall_seconds: float) -> float | None:
    """Simulated seconds per real second, or None when no real time passed."""
    return simulated_seconds / wall_seconds if wall_seconds > 0 else None


def still_loading(status: Sequence[object] | None) -> bool:
    """Whether omni.usd's get_stage_loading_status, (message, files loaded, files to load), says files are still to
    load, as Isaac Sim's is_stage_loading reads it."""
    if status is None or len(status) < 3:
        return False
    total = status[2]
    return isinstance(total, int | float) and total > 0


# ---- the GPU ----


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def gpu_frame_ms(devices: Iterable[Iterable[Mapping[str, object]]]) -> float:
    """One frame's GPU time from HydraEngineStats().get_gpu_profiler_result(): per device, the durations of its
    top-level passes (indent 0), whose nested passes are inside them; averaged over the devices, as Isaac Sim's
    gpu_frametime recorder reads it. 0 when Hydra gives no device."""
    times = [
        sum(_number(node.get("duration")) or 0.0 for node in nodes if node.get("indent", 0) == 0) for nodes in devices
    ]
    return _mean(times) if times else 0.0


def gpu_render(samples_ms: Sequence[float]) -> dict[str, object]:
    """The gpu_render numbers, or why there are none: Hydra's profiler is off in some apps, and every frame then reads
    0."""
    if not any(samples_ms):
        return {"missing": "Hydra's GPU profiler gave no times: it may be off in this app"}
    ordered = sorted(samples_ms)
    return {"mean_ms": _mean(samples_ms), "p95_ms": _rank(ordered, 0.95)}


def gpu_memory(devices: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Device 0's name, and the memory Hydra's get_device_info() says it uses and has as its budget, in bytes (None for
    one it doesn't give), as Isaac Sim's memory recorder reads it; or why there is none."""
    if not devices:
        return {"missing": "Hydra names no GPU device"}
    device = devices[0]
    used, budget = _number(device.get("usage")), _number(device.get("budget"))
    return {
        "device": str(device.get("description") or "unknown"),
        "used_bytes": int(used) if used is not None else None,
        "budget_bytes": int(budget) if budget is not None else None,
    }


# ---- physics ----


class ProfileStat(Protocol):
    """One profiling zone of a physics step, as PhysX's benchmarks interface reports it."""

    @property
    def zone_name(self) -> str: ...

    @property
    def ms(self) -> float: ...


class StepTally:
    """The physics steps of the measured frames, from the profile stats PhysX sends with each step: each step's time,
    taken only while `counting`, so steps outside the frames kept don't count."""

    def __init__(self) -> None:
        self.counting = False
        self.step_ms: list[float] = []

    def add(self, stats: Iterable[ProfileStat]) -> None:
        if not self.counting:
            return
        self.step_ms.extend(float(stat.ms) for stat in stats if stat.zone_name == STEP_ZONE)


def physics(step_ms: Sequence[float], frames: int, wall_seconds: float, step_seconds: float) -> dict[str, object]:
    """The physics numbers of `frames` frames that took `wall_seconds`: the scene's steps a simulated second, the steps
    a frame carries, the time a step and a frame, and the time simulated, each step `step_seconds` of it, against the
    real time. From the steps counted, not the timeline's time, which wraps at its end (#156's round 1, I8)."""
    steps = len(step_ms)
    if steps == 0 or frames == 0:
        return {"missing": "no physics step came in the measured frames"}
    simulated = steps * step_seconds
    return {
        "steps_per_second": 1.0 / step_seconds,
        "steps": steps,
        "steps_per_frame": steps / frames,
        "step_ms": _mean(step_ms),
        "frame_ms": sum(step_ms) / frames,
        "simulated_seconds": simulated,
        "wall_seconds": wall_seconds,
        "ratio": ratio(simulated, wall_seconds),
    }


# ---- the stage ----


class Survey(NamedTuple):
    """What the stage holds that costs frame time: its counts, and its render products, each one a camera, a lidar or
    another sensor rendering every update."""

    counts: dict[str, int]
    products: list[dict[str, object]]


def _sensor_kind(stage: Usd.Stage, product: UsdRender.Product) -> str:
    """What renders through a render product, by the prim its camera relationship targets: a lidar or a radar (an RTX
    sensor's own prim type, or a camera whose cameraSensorType says so), a camera, or that prim's type."""
    targets = product.GetCameraRel().GetTargets()
    camera = stage.GetPrimAtPath(targets[0]) if targets else None
    if camera is None or not camera.IsValid():
        return "render product"
    type_name = str(camera.GetTypeName())
    for kind in ("lidar", "radar"):
        if kind in type_name.lower():
            return kind
    sensor = camera.GetAttribute("cameraSensorType")
    value = sensor.Get() if sensor.IsValid() else None
    if isinstance(value, str) and value and value != "camera":
        return value
    return "camera" if type_name == "Camera" else type_name or "render product"


def _resolution(product: UsdRender.Product) -> list[int] | None:
    value: Sequence[int] | None = product.GetResolutionAttr().Get()
    return [int(value[0]), int(value[1])] if value is not None else None


def survey(stage: Usd.Stage) -> Survey:
    """One walk of the stage as it traverses, instance proxies left out: its prims, its meshes, its instances and the
    prototypes they share, its point instancers and their instances, which IsInstance doesn't count (#156's round 1,
    I10), and its render products."""
    counts: dict[str, int] = dict.fromkeys(
        ("prims", "meshes", "instances", "prototypes", "point_instancers", "point_instances"), 0
    )
    prototypes: set[Sdf.Path] = set()
    products: list[dict[str, object]] = []
    # Looked up once, not per prim: a site's stage holds a hundred thousand prims or more.
    mesh, instancer, render_product = (
        Tf.Type.Find(s) for s in (UsdGeom.Mesh, UsdGeom.PointInstancer, UsdRender.Product)
    )
    for prim in stage.Traverse():
        counts["prims"] += 1
        if prim.IsA(mesh):
            counts["meshes"] += 1
        elif prim.IsA(instancer):
            counts["point_instancers"] += 1
            counts["point_instances"] += int(UsdGeom.PointInstancer(prim).GetInstanceCount())
        elif prim.IsA(render_product):
            product = UsdRender.Product(prim)
            products.append(
                {"path": str(prim.GetPath()), "kind": _sensor_kind(stage, product), "resolution": _resolution(product)}
            )
        if prim.IsInstance():
            counts["instances"] += 1
            prototypes.add(prim.GetPrototype().GetPath())
    counts["prototypes"] = len(prototypes)
    return Survey(counts, products)


# ---- the notes and the answer ----

ECO_NOTE = (
    "eco mode is on and the timeline isn't playing: RTX may stop rendering a still stage, so this reads faster than "
    "the scene plays; measure while it plays"
)
RECORDING_NOTE = "a recording is running: its camera renders every update, so these numbers include it"


def eco_note(eco_mode: object, timeline: object) -> str | None:
    """The note for eco mode on while the timeline is stopped or paused, as Isaac Sim's throttling leaves it (#156's
    round 1, P4)."""
    return ECO_NOTE if eco_mode is True and timeline != "playing" else None


def _ran_out(phase: str, args: PerformanceArgs, measured: int, seconds: float) -> str:
    """Where the call's time ran out, by the phase it was in."""
    spent = f"the {seconds:g} s this call may take ran out"
    if phase == "loading":
        return f"{spent} while the stage was still loading"
    if phase == "warming":
        return f"{spent} during the warm-up of {args.warmup} updates"
    if measured == 0:
        return f"{spent} before a frame was timed"
    return f"{spent} after {measured} of {args.frames} frames: the numbers are of those"


def _not_settled(first: float, second: float) -> str:
    way = "above" if second > first else "below"
    # A share of a first half that took no time at all would be a division by zero.
    share = f"{abs(second - first) / first * 100:.0f}% " if first > 0 else ""
    return (
        f"not settled: the second half's mean frame time is {share}{way} the first's, as when a stage still loads "
        "textures, compiles shaders or warms caches; measure again"
    )


def answer(
    *,
    args: PerformanceArgs,
    samples_ms: Sequence[float],
    gpu_ms: Sequence[float] | None,
    gpu_missing: str | None,
    physics: Mapping[str, object],
    memory: Mapping[str, object],
    survey: Survey,
    conditions: Mapping[str, object],
    ran_out: str | None,
    recording: bool,
    seconds: float = CALL_SECONDS,
) -> dict[str, object]:
    """/sim/performance's result: the numbers of the frames measured (`samples_ms`, the first interval already
    dropped), each one Kit couldn't give as {"missing": why}, the stage's survey, the conditions, and the notes that
    say what could move the numbers. `ran_out` is the phase the call's time ran out in, or None when it didn't."""
    result: dict[str, object] = {"frames": args.frames, "warmup": args.warmup, "measured_frames": len(samples_ms)}
    notes: list[str] = []
    summary = summarise(samples_ms)
    stopped = _ran_out(ran_out, args, len(samples_ms), seconds) if ran_out is not None else None
    if summary is None:
        result["app"] = None
        result["app_missing"] = stopped or "no frame was timed"
    else:
        result["app"] = summary._asdict()
        if stopped is not None:
            notes.append(stopped)
    split = halves(samples_ms)
    if split is not None:
        steady = settled(*split)
        result["halves"] = {"first_ms": split[0], "second_ms": split[1], "settled": steady}
        if not steady:
            notes.append(_not_settled(*split))
    result["gpu_render"] = gpu_render(gpu_ms) if gpu_ms is not None else {"missing": gpu_missing or "not measured"}
    result["physics"] = dict(physics)
    result["gpu_memory"] = dict(memory)
    result["stage"] = dict(survey.counts)
    result["render_products"] = list(survey.products)
    result["conditions"] = dict(conditions)
    eco = eco_note(conditions.get("eco_mode"), conditions.get("timeline"))
    if eco is not None:
        notes.append(eco)
    if recording:
        notes.append(RECORDING_NOTE)
    result["notes"] = notes
    return result
