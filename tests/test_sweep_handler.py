"""The capture sweep's handler against a fake Kit (#157): /jobs/sweep checks the whole sweep and starts it as a job on
#158's board; each shot shows its own selections, time and camera; every layer and the timeline are as they were after
a sweep, a cancel, an error or the shutdown, and a new stage is left alone; the manifest, the files and the last line
say what was taken.

handlers/sweep.py is loaded from its file with Kit's modules and its sibling handlers faked in sys.modules, as
tests/test_recording_handler.py loads its handler. The stage is a real usd-core one, two prims referencing an area's
file with variant sets; the core, the job board and the viewport lock are the real ones.
"""

import asyncio
import importlib.util
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pxr import Sdf, Tf, Usd, UsdGeom

from ovmcp.core import capture, exposure, sweep
from ovmcp.core.jobs import CANCELLED, COMPLETED, FAILED, WORKING, Job, JobBoard
from ovmcp.core.serial import LazyLock
from ovmcp.core.usd import select

from .conftest import HANDLERS
from .test_exposure import rtx_writes
from .test_sweep import FakeTimeline

OPENED, CLOSING = "OPENED", "CLOSING"
CAMERA_OPS = ["xformOp:orient", "xformOp:translate", "xformOpOrder"]
PNG = b"\x89PNG\r\n\x1a\nshot"
A, B = "/World/A", "/World/B"

# An area whose state set brings in a wall, or a camera with a lens of its own, and whose lod set is empty.
AREA_USDA = """#usda 1.0
(
    defaultPrim = "Area"
)

def Xform "Area" (
    variants = {
        string state = "closed"
    }
    prepend variantSets = ["state", "lod"]
)
{
    variantSet "state" = {
        "closed" {
            def Cube "Wall"
            {
            }
        }
        "open" {
            def Camera "Cam"
            {
                float2 clippingRange = (0.05, 200)
                float focalLength = 7.337
                float horizontalAperture = 20.955
                float verticalAperture = 15.2908
                double3 xformOp:translate = (1, 2, 0.65)
                uniform token[] xformOpOrder = ["xformOp:translate"]
            }
        }
    }
    variantSet "lod" = {
        "high" {
        }
        "low" {
        }
    }
}
"""


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


def _stage(folder: Path) -> Usd.Stage:
    """A Z-up metres stage whose /World/A and /World/B reference the area, B's lod selected high in the session layer
    before the sweep, as an earlier set_variant_selection leaves it."""
    area = folder / "area.usda"
    layer = Sdf.Layer.CreateAnonymous(".usda")
    layer.ImportFromString(AREA_USDA)
    assert layer.Export(str(area))
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    stage.DefinePrim("/World", "Xform")
    for path in (A, B):
        stage.DefinePrim(path).GetReferences().AddReference(str(area))
    select(Sdf.CreatePrimInLayer(stage.GetSessionLayer(), Sdf.Path(B)), "lod", "high")
    return stage


def settled(kit: "FakeKit", stage: Usd.Stage) -> dict[str, str]:
    """layers(stage) once the kept feed's render product is gone, as the live test reads them after release_kept: RTX's
    writes onto the cameras rendered through stay until then (#177)."""
    kit.release()
    return layers(stage)


def layers(stage: Usd.Stage) -> dict[str, str]:
    """Every layer the stage uses, the session layer and the area's file among them, as text."""
    found = [*stage.GetLayerStack(includeSessionLayers=True), *stage.GetUsedLayers()]
    return {layer.identifier: layer.ExportToString() for layer in found}


class FakeFeed:
    """The lent camera feed as a sweep uses it, with #177's marks as CameraFeed takes them: each camera noted before the
    feed first renders through it, on creation and on aim, and put back when its render product is deleted. Its renders
    write what Kit 110's RTX writes onto a bare camera, at the edit target."""

    def __init__(self, kit: "FakeKit", camera_path: str, width: int, height: int) -> None:
        self.kit = kit
        self.camera_path, self.width, self.height = camera_path, width, height
        self.render_product_path = "/Render/OmniverseKit/HydraTextures/ovmcp_feed_0"
        self.frames = 0
        self.dropped = False
        self.aimed: list[str] = []
        self.marks: list[Any] = []
        self._note(camera_path)

    def _note(self, camera_path: str) -> None:
        key = exposure.MARKS.take(self.kit.get_stage(), camera_path)
        if key is None:
            return
        if key in self.marks:
            exposure.MARKS.let_go(key, [])
            return
        self.marks.append(key)

    def aim(self, camera_path: str, width: int, height: int) -> None:
        assert (width, height) == (self.width, self.height)
        if camera_path != self.camera_path:
            self._note(camera_path)
            self.camera_path = camera_path
        self.aimed.append(camera_path)

    def drop(self) -> None:
        self.dropped = True

    def remove_render_product(self, stage: Usd.Stage) -> None:
        layers = list(stage.GetLayerStack(includeSessionLayers=True))
        marks, self.marks = self.marks, []
        for key in marks:
            exposure.MARKS.let_go(key, layers)

    def render(self) -> None:
        """One render through the feed's camera: RTX's exposure written onto it when it lacks it."""
        stage = self.kit.get_stage()
        prim = stage.GetPrimAtPath(self.camera_path)
        if prim.IsValid() and not prim.IsInstanceProxy() and exposure.bare(prim):
            rtx_writes(stage, self.camera_path)

    async def first_frame(self, seconds: float) -> None:
        assert seconds == capture.FRAME_SECONDS
        await self.kit.next_update()
        if self.kit.first_frame_gate is not None:
            await self.kit.first_frame_gate
        if self.kit.first_frame_fails:
            raise capture.NoFrameError(f"The camera {self.camera_path} rendered no frame in 30 s")
        self.frames += 1

    async def wait_frames(self, count: int, budget: capture.Budget | None = None) -> None:
        assert count == 20
        assert budget is not None
        await self.kit.next_update()
        self.render()
        if self.kit.frames_move:
            self.frames += count


class FakeKit:
    """Kit as the sweep sees it: the stage and its state, the timeline, the loading status, the updates, the feed lent
    and handed back, and each capture, which records what the shot showed and may fail, come out black or wait for the
    test."""

    def __init__(self, stage: Usd.Stage) -> None:
        self.stage: Usd.Stage | None = stage
        self.stage_id = 1
        self.stage_state = OPENED
        self.timeline = FakeTimeline("stopped", 0.0)
        # The loading statuses to give in turn, then none loading.
        self.loading: list[tuple[str, int, int]] = []
        self.always_loading = False
        self.updates = 0
        self.lock = LazyLock()
        self.feeds: list[FakeFeed] = []
        self.handed_back: list[tuple[FakeFeed, object, bool]] = []
        self.torn_down: list[FakeFeed] = []
        self.refreshed: list[list[str]] = []
        self.seen: list[dict[str, Any]] = []
        self.order: list[str] = []
        # By capture number, from 1: "black", or an exception to raise.
        self.rules: dict[int, Any] = {}
        # Called at each capture with its number, before it gives its image.
        self.on_capture: Callable[[int], Awaitable[None]] | None = None
        self.frames_move = True
        self.first_frame_fails = False
        self.first_frame_gate: asyncio.Future[None] | None = None
        # Called at each refresh, and as hand_back runs, which then awaits an update.
        self.on_refresh: Callable[[], None] | None = None
        self.on_hand_back: Callable[[], None] | None = None

    def get_stage(self) -> Usd.Stage:
        if self.stage is None:
            raise RuntimeError("No USD stage is open")
        return self.stage

    def loading_status(self) -> tuple[str, int, int]:
        if self.always_loading:
            return ("Loading textures", 2, 7)
        return self.loading.pop(0) if self.loading else ("", 0, 0)

    async def next_update(self) -> None:
        self.updates += 1
        await asyncio.sleep(0)

    async def lend(self, camera_path: str, width: int, height: int) -> FakeFeed:
        assert self.get_stage().GetPrimAtPath(camera_path).IsValid(), "the camera is made before the feed renders it"
        self.feeds.append(FakeFeed(self, camera_path, width, height))
        return self.feeds[-1]

    async def hand_back(self, feed: FakeFeed, stage_id: object, healthy: bool) -> None:
        self.handed_back.append((feed, stage_id, healthy))
        if self.on_hand_back is not None:
            self.on_hand_back()
            await self.next_update()

    def let_go_now(self, feed: FakeFeed) -> None:
        # As camera_feed's: dropped, its render product deleted at once while a stage is open.
        feed.drop()
        if self.stage is not None:
            feed.remove_render_product(self.stage)
        self.torn_down.append(feed)

    def release(self) -> None:
        """Every feed's render product deleted, as release_kept does with the kept feed: what RTX wrote onto the cameras
        they rendered through comes back with it."""
        for feed in self.feeds:
            feed.remove_render_product(self.get_stage())

    async def refresh(self, _stage: Usd.Stage, paths: list[Sdf.Path]) -> None:
        self.refreshed.append(sorted(str(p) for p in paths))
        if self.on_refresh is not None:
            self.on_refresh()
        await self.next_update()

    async def capture(self, feed: FakeFeed, budget: capture.Budget | None = None) -> tuple[bytes, bool]:
        assert budget is not None
        assert self.lock.get().locked(), "a shot holds the viewport lock"
        number = len(self.seen) + 1
        self.seen.append(self.view(feed))
        self.order.append(f"shot {number}")
        if self.on_capture is not None:
            await self.on_capture(number)
        rule = self.rules.get(number)
        if isinstance(rule, BaseException):
            raise rule
        return PNG + bytes([number]), rule == "black"

    def view(self, feed: FakeFeed) -> dict[str, Any]:
        """What a shot renders: its camera and lens, the two prims' selections, and the timeline."""
        stage = self.get_stage()
        camera = UsdGeom.Camera(stage.GetPrimAtPath(feed.camera_path))
        session = stage.GetSessionLayer()
        own = session.GetPrimAtPath(sweep.CAMERA_PATH)
        in_root = stage.GetRootLayer().GetPrimAtPath(sweep.CAMERA_PATH)
        return {
            "camera": feed.camera_path,
            "focal_length": round(camera.GetFocalLengthAttr().Get(), 4),
            "a": stage.GetPrimAtPath(A).GetVariantSet("state").GetVariantSelection(),
            "b": stage.GetPrimAtPath(B).GetVariantSet("lod").GetVariantSelection(),
            "time": self.timeline.time,
            "timeline": self.timeline.state,
            # What the root layer holds of the sweep's camera beside RTX's exposure.
            "camera_in_root": sorted(
                name for name in (in_root.properties.keys() if in_root else []) if not name.startswith("exposure:")
            ),
            "camera_ops": sorted(n for n in (own.attributes.keys() if own else []) if n.startswith("xformOp")),
            "clipping": tuple(
                round(v, 6) for v in UsdGeom.Camera(stage.GetPrimAtPath(sweep.CAMERA_PATH)).GetClippingRangeAttr().Get()
            ),
        }


@pytest.fixture
def kit(tmp_path: Path) -> FakeKit:
    folder = tmp_path / "scene"
    folder.mkdir()
    return FakeKit(_stage(folder))


@pytest.fixture
def env(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    board = JobBoard(watch=lambda _job: None)
    # This test's own, so no mark outlives it.
    monkeypatch.setattr(exposure, "MARKS", exposure.Marks())

    def stop_for_stage(job: Job, stage_id: object) -> bool:
        # handlers/jobs.py's, on the fake Kit's stage: the watch's reasons, at once.
        reason = "the stage changed" if kit.stage_id != stage_id else None
        reason = reason or ("the stage began to close" if kit.stage_state != OPENED else None)
        if reason is None or job.state != WORKING:
            return False
        board.cancel(job.id, reason)
        return True

    context = SimpleNamespace(
        get_stage=lambda: kit.stage,
        get_stage_id=lambda: kit.stage_id,
        get_stage_state=lambda: kit.stage_state,
        get_stage_loading_status=kit.loading_status,
    )
    settings = SimpleNamespace(get={"/rtx/rendermode": "RaytracedLighting"}.get)
    carb_settings = _module("carb.settings", get_settings=lambda: settings)
    usd = _module("omni.usd", get_context=lambda: context, StageState=SimpleNamespace(OPENED=OPENED, CLOSING=CLOSING))
    timeline = _module("omni.timeline", get_timeline_interface=lambda: kit.timeline)
    fakes = {
        "carb": _module("carb", settings=carb_settings, log_warn=lambda _m: None, log_info=lambda _m: None),
        "carb.settings": carb_settings,
        "omni": _module("omni", usd=usd, timeline=timeline),
        "omni.usd": usd,
        "omni.timeline": timeline,
        # What the start checks the app has, before anything is made; the feed itself is faked below.
        "omni.kit.hydra_texture": _module("omni.kit.hydra_texture"),
        "omni.kit.widget.viewport.capture": _module("omni.kit.widget.viewport.capture"),
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils",
            CAMERA_SETTLE_FRAMES=20,
            _get_active_camera_path=lambda: "/OmniverseKit_Persp",
            _get_stage=kit.get_stage,
            _next_update=kit.next_update,
            _settle_frames=lambda: 0,
        ),
        "handlers_under_test.camera": _module(
            "handlers_under_test.camera", _capture_frame=kit.capture, _get_current_lighting_mode=lambda: "stage"
        ),
        "handlers_under_test.camera_feed": _module(
            "handlers_under_test.camera_feed",
            _viewport=kit.lock,
            hand_back=kit.hand_back,
            lend=kit.lend,
            let_go_now=kit.let_go_now,
        ),
        "handlers_under_test.jobs": _module(
            "handlers_under_test.jobs", start_job=board.start, stop_for_stage=stop_for_stage
        ),
        "handlers_under_test.variants": _module("handlers_under_test.variants", refresh=kit.refresh),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("handlers_under_test.sweep", HANDLERS / "sweep.py")
    assert spec is not None
    assert spec.loader is not None
    handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(handler)
    return SimpleNamespace(handler=handler, board=board)


def _body(tmp_path: Path, shots: Any, name: str = "site_a", **extra: Any) -> dict[str, Any]:
    return {"output_dir": str(tmp_path / "sweeps"), "name": name, "shots": shots, "width": 1280, "height": 720, **extra}


async def _until_ended(job: Job) -> None:
    for _ in range(100_000):
        if job.ended is not None:
            return
        await asyncio.sleep(0)
    raise AssertionError("the sweep never ended")


def _run(env: SimpleNamespace, body: dict[str, Any]) -> tuple[dict[str, Any], Job]:
    async def main() -> tuple[dict[str, Any], Job]:
        started = await env.handler.handle_sweep_start(body)
        assert started["status"] == "success", started
        job = env.board.get(started["result"]["id"])
        await _until_ended(job)
        return started, job

    return asyncio.run(main())


def _manifest(tmp_path: Path, name: str = "site_a") -> dict[str, Any]:
    return json.loads((tmp_path / "sweeps" / name / "manifest.json").read_text(encoding="utf-8"))


def _pose(**extra: Any) -> dict[str, Any]:
    return {"position": [0, -5, 0.65], "yaw": 90, **extra}


# Four shots: A opened; B lowered at a time; neither, which shows what was there before the sweep; both.
FOUR = [
    _pose(name="a open", selections={A: {"state": "open"}}),
    {
        "position": [0, -5, 0.65],
        "target": [0, 0, 0],
        "selections": {B: {"lod": "low"}},
        "time": 2,
        # The case's front camera.
        "focal_length": 7.337,
        "horizontal_aperture": 20.955,
        "vertical_aperture": 11.787,
    },
    _pose(),
    _pose(selections={A: {"state": "open"}, B: {"lod": "low"}}),
]


# ----- a sweep -----


def test_each_shot_shows_its_own_state_and_every_layer_and_the_timeline_come_back(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)

    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == COMPLETED, job.error
    assert [(s["a"], s["b"], s["time"], s["timeline"]) for s in kit.seen] == [
        ("open", "high", 0.0, "stopped"),
        ("closed", "low", 2.0, "stopped"),
        # Neither named: the file's closed for A, and B's high, which the session layer held before the sweep (P1).
        ("closed", "high", 0.0, "stopped"),
        ("open", "low", 0.0, "stopped"),
    ]
    assert [s["focal_length"] for s in kit.seen] == [
        round(sweep.FOCAL_LENGTH, 4),
        7.337,
        round(sweep.FOCAL_LENGTH, 4),
        round(sweep.FOCAL_LENGTH, 4),
    ]
    assert kit.refreshed == [[A], [A, B], [B], [A, B]]
    assert settled(kit, stage) == before
    assert (kit.timeline.state, kit.timeline.time) == ("stopped", 0.0)
    assert not stage.GetPrimAtPath(sweep.CAMERA_PATH).IsValid()
    folder = tmp_path / "sweeps" / "site_a"
    assert sorted(p.name for p in folder.iterdir()) == [
        "0001_a_open.png",
        "0002.png",
        "0003.png",
        "0004.png",
        "manifest.json",
    ]
    assert job.result is not None
    assert job.result["summary"] == f"4 shots in {folder}/ (manifest.json)"
    assert job.lines.last == job.result["summary"]


def test_the_sweep_s_camera_and_its_ops_are_in_the_session_layer_alone_with_isaac_sim_s_clipping(env, kit, tmp_path):
    _run(env, _body(tmp_path, FOUR[:1]))

    (seen,) = kit.seen
    assert seen["camera"] == sweep.CAMERA_PATH
    assert seen["camera_in_root"] == []
    assert seen["camera_ops"] == CAMERA_OPS
    assert seen["clipping"] == (0.01, 1e7)


def test_a_shot_s_lens_and_clipping_are_its_own_never_the_last_shot_s(env, kit, tmp_path):
    # A shot read back from a manifest names the clipping range it rendered with; the next shot gets the default again.
    shots = [_pose(clipping_range=[0.1, 500], focal_length=7.337), _pose()]

    _run(env, _body(tmp_path, shots))

    assert [(s["clipping"], s["focal_length"]) for s in kit.seen] == [
        ((0.1, 500.0), 7.337),
        ((0.01, 1e7), round(sweep.FOCAL_LENGTH, 4)),
    ]


def test_the_feed_is_lent_at_the_sweep_s_size_and_handed_back_healthy_off_its_camera(env, kit, tmp_path):
    _run(env, _body(tmp_path, FOUR[:2]))

    (feed,) = kit.feeds
    assert (feed.width, feed.height) == (1280, 720)
    assert kit.handed_back == [(feed, 1, True)]
    # Pointed off the camera about to be deleted, at the viewport's.
    assert feed.aimed[-1] == "/OmniverseKit_Persp"


def test_the_manifest_matches_the_files_and_reads_back_as_the_same_shots(env, kit, tmp_path):
    _run(env, _body(tmp_path, FOUR))

    manifest = _manifest(tmp_path)
    folder = tmp_path / "sweeps" / "site_a"
    assert (manifest["width"], manifest["height"], manifest["up_axis"], manifest["ended"]) == (
        1280,
        720,
        "Z",
        "completed",
    )
    assert (manifest["shots_asked"], manifest["shots_done"], manifest["render_mode"]) == (4, 4, "RaytracedLighting")
    assert [e["clipping_range"] for e in manifest["shots"]] == [[0.01, 1e7]] * 4
    for entry in manifest["shots"]:
        assert (folder / entry["file"]).read_bytes() == PNG + bytes([entry["index"]])
        assert entry["is_black"] is False
    assert manifest["shots"][1]["timeline_time"] == 2.0
    # The same shots, with the clipping range each rendered with, which a rerun's camera takes too.
    asked = [replace(shot, clipping=(0.01, 1e7)) for shot in sweep.read_shots(FOUR, 1280, 720)]
    assert sweep.read_shots(manifest, 1280, 720) == asked


def test_a_black_shot_is_counted_in_the_result(env, kit, tmp_path):
    kit.rules[2] = "black"

    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.result is not None
    assert job.result["black"] == [2]
    assert _manifest(tmp_path)["shots"][1]["is_black"] is True


# ----- the timeline -----


def test_a_playing_timeline_pauses_for_a_timed_shot_and_plays_again_after(env, kit, tmp_path):
    kit.timeline = FakeTimeline("playing", 1.0)
    shots = [_pose(time=3), _pose(), _pose(time=4)]

    _run(env, _body(tmp_path, shots))

    assert [(s["timeline"], s["time"]) for s in kit.seen] == [("paused", 3.0), ("playing", 1.0), ("paused", 4.0)]
    assert (kit.timeline.state, kit.timeline.time) == ("playing", 1.0)


# ----- shots that fail -----


def test_a_camera_path_shot_renders_its_camera_unwritten_checked_after_its_switch(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)
    cam = f"{A}/Cam"
    shots = [{"camera_path": cam, "selections": {A: {"state": "open"}}}, {"camera_path": cam}, _pose()]

    _, job = _run(env, _body(tmp_path, shots))

    assert job.state == COMPLETED
    assert [s["camera"] for s in kit.seen] == [cam, sweep.CAMERA_PATH]
    assert kit.seen[0]["focal_length"] == 7.337
    assert settled(kit, stage) == before
    entries = _manifest(tmp_path)["shots"]
    assert entries[0]["camera_path"] == cam
    assert entries[0]["position"] == [1.0, 2.0, 0.65]
    assert (entries[0]["yaw"], entries[0]["pitch"]) == (0.0, -90.0)
    # Its own horizontal aperture, the vertical as Kit renders it: matched to the image.
    assert (entries[0]["horizontal_aperture"], entries[0]["vertical_aperture"]) == pytest.approx((20.955, 11.7871875))
    assert entries[0]["clipping_range"] == pytest.approx([0.05, 200])
    # The closed state took the camera away: shot 2 fails with why, and the sweep goes on. RTX's over at the edit target
    # stays there until the feed's render product goes (#177), so the camera reads typeless, not missing.
    assert entries[1]["error"] == f"{cam} is a typeless prim, not a Camera: camera_path must name a camera"
    assert "file" not in entries[1]
    assert job.result is not None
    assert job.result["failed"] == [2]
    assert f"shot 2 of 3 failed: {cam} is a typeless prim" in job.lines.kept()["stdout"]
    # Read back, shot 1 takes the view its camera rendered without the camera (round 2, P15).
    back = sweep.read_shots(_manifest(tmp_path), 1280, 720)
    assert (back[0].camera_path, back[0].position, back[0].pitch) == ("", (1.0, 2.0, 0.65), -90.0)


def test_a_selection_refused_at_its_shot_fails_that_shot_and_the_next_writes_what_it_needs(env, kit, tmp_path):
    # /World/Later isn't on the stage at the start, so only its shot can refuse it.
    shots = [
        _pose(selections={A: {"state": "open"}, "/World/Later": {"state": "x"}}),
        _pose(selections={A: {"state": "open"}}),
    ]

    _, job = _run(env, _body(tmp_path, shots))

    entries = _manifest(tmp_path)["shots"]
    assert entries[0]["error"].startswith("its selections were refused: Prim not found: /World/Later")
    # Nothing of shot 1 was written, so shot 2 writes A's open itself (round 2, P13).
    assert [s["a"] for s in kit.seen] == ["open"]
    assert job.result is not None
    assert (job.result["failed"], job.result["taken"]) == ([1], 1)


def test_a_failed_capture_is_recorded_and_its_feed_released_at_the_end(env, kit, tmp_path):
    kit.rules[2] = capture.OutOfTimeError("The 30 s this call may take ran out")

    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == COMPLETED
    assert _manifest(tmp_path)["shots"][1]["error"] == "not captured: The 30 s this call may take ran out"
    assert kit.handed_back[0][2] is False


def test_a_feed_that_renders_nothing_stops_the_sweep(env, kit, tmp_path):
    kit.frames_move = False
    kit.rules[1] = capture.OutOfTimeError("The 30 s this call may take ran out")

    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == FAILED
    assert job.error.startswith("The camera feed rendered no frame for shot 1 in 30 s")
    assert len(kit.seen) == 1
    assert job.lines.last.startswith("1 of 4 shots in ")


def test_a_switch_that_loads_files_waits_for_them_and_one_past_its_bound_is_taken_anyway(
    env, kit, tmp_path, monkeypatch
):
    kit.loading = [("Loading", 1, 3), ("Loading", 2, 3)]
    _run(env, _body(tmp_path, FOUR[:1], name="waits"))
    entry = _manifest(tmp_path, "waits")["shots"][0]
    assert "loading" not in entry
    assert entry["loading_seconds"] >= 0

    monkeypatch.setattr(sweep, "LOADING_SECONDS", 0.01)
    kit.always_loading = True
    _, job = _run(env, _body(tmp_path, FOUR[:1], name="late"))
    entry = _manifest(tmp_path, "late")["shots"][0]
    assert entry["loading"].startswith("taken still loading, 2 of 7 files, after ")
    assert "file" in entry
    assert job.result is not None
    assert job.result["loading"] == [1]


# ----- the end -----


def test_a_cancel_mid_sweep_puts_everything_back_and_the_manifest_says_what_it_took(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)

    async def cancel(number: int) -> None:
        if number == 2:
            env.board.cancel("j1", "cancel_job was called")
            await asyncio.sleep(0)

    kit.on_capture = cancel
    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == CANCELLED
    assert settled(kit, stage) == before
    assert (kit.timeline.state, kit.timeline.time) == ("stopped", 0.0)
    manifest = _manifest(tmp_path)
    assert (manifest["shots_done"], manifest["ended"]) == (1, "cancelled: cancel_job was called")
    folder = tmp_path / "sweeps" / "site_a"
    assert job.lines.last == f"1 of 4 shots in {folder}/ (manifest.json); cancelled: cancel_job was called"
    assert kit.handed_back[0][1:] == (1, True)


def test_a_stage_change_cancels_the_sweep_and_leaves_the_new_stage_alone(env, kit, tmp_path):
    new = Usd.Stage.CreateInMemory()
    new.DefinePrim("/World/Else")
    new_before = layers(new)
    calls: list[str] = []

    async def change(number: int) -> None:
        if number == 2:
            kit.stage, kit.stage_id = new, 2
            kit.timeline = FakeTimeline("paused", 9.0)
            env.board.cancel("j1", "the stage changed")
            calls.extend(kit.timeline.calls)
            await asyncio.sleep(0)

    kit.on_capture = change
    _, job = _run(env, _body(tmp_path, FOUR))

    assert (job.state, job.message) == (CANCELLED, "the stage changed")
    assert layers(new) == new_before
    assert kit.timeline.calls == calls
    assert (kit.timeline.state, kit.timeline.time) == ("paused", 9.0)
    # Handed back as the old stage's: hand_back releases a feed whose stage went.
    assert kit.handed_back[0][1] == 1
    assert _manifest(tmp_path)["ended"] == "cancelled: the stage changed"


def test_an_error_mid_sweep_fails_the_job_and_still_puts_everything_back(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)
    kit.rules[3] = TypeError("a fault no shot expects")

    _, job = _run(env, _body(tmp_path, FOUR))

    assert (job.state, job.error) == (FAILED, "a fault no shot expects")
    assert settled(kit, stage) == before
    assert _manifest(tmp_path)["ended"] == "failed: a fault no shot expects"
    folder = tmp_path / "sweeps" / "site_a"
    assert job.lines.last == f"2 of 4 shots in {folder}/ (manifest.json); failed: a fault no shot expects"


def test_an_error_without_a_message_is_named_by_its_type(env, kit, tmp_path):
    kit.rules[1] = KeyError()

    _run(env, _body(tmp_path, FOUR))

    assert _manifest(tmp_path)["ended"] == "failed: KeyError"


def test_the_shutdown_puts_everything_back_at_once_and_lets_the_feed_go(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)

    async def shut(number: int) -> None:
        if number == 2:
            env.board.shut_down()
            # Kit's loop may never run the job's own cleanup now: everything is back already.
            assert layers(stage) == before
            await asyncio.sleep(0)

    kit.on_capture = shut
    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == CANCELLED
    assert kit.torn_down == kit.feeds
    assert kit.handed_back == []
    assert _manifest(tmp_path)["ended"] == "cancelled: the extension shut down"


def test_the_manifest_is_rewritten_every_25_shots(env, kit, tmp_path):
    read: list[dict[str, Any]] = []

    async def look(number: int) -> None:
        if number == 26:
            read.append(_manifest(tmp_path))

    kit.on_capture = look
    _, job = _run(env, _body(tmp_path, [_pose()] * 26))

    assert (read[0]["shots_done"], read[0]["ended"]) == (25, "working")
    assert "shot 25 of 26: 25 taken" in job.lines.kept()["stdout"]
    assert _manifest(tmp_path)["shots_done"] == 26


def test_the_viewport_lock_is_taken_per_shot_so_a_capture_runs_between_shots(env, kit, tmp_path):
    others: list[asyncio.Task[None]] = []

    async def other_capture() -> None:
        async with kit.lock.get():
            kit.order.append("capture_viewport")

    async def queue(number: int) -> None:
        if number == 1:
            others.append(asyncio.ensure_future(other_capture()))
            await asyncio.sleep(0)

    kit.on_capture = queue
    _run(env, _body(tmp_path, FOUR[:3]))

    assert kit.order == ["shot 1", "capture_viewport", "shot 2", "shot 3"]


# ----- round 1 of the code review -----


def test_a_feed_whose_first_frame_never_came_is_released_not_kept(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)
    kit.first_frame_fails = True

    _, job = _run(env, _body(tmp_path, FOUR))

    assert (job.state, job.error) == (FAILED, "The camera /OmniverseKit_Sweep rendered no frame in 30 s")
    assert [healthy for _, _, healthy in kit.handed_back] == [False]
    assert settled(kit, stage) == before


def test_a_cancel_while_the_first_frame_comes_leaves_the_feed_healthy(env, kit, tmp_path):
    async def main() -> Job:
        kit.first_frame_gate = asyncio.get_running_loop().create_future()
        started = await env.handler.handle_sweep_start(_body(tmp_path, FOUR))
        job = env.board.get(started["result"]["id"])
        for _ in range(20):
            await asyncio.sleep(0)
        assert kit.feeds, "the feed is lent and waits for its first frame"
        env.board.cancel(job.id, "cancel_job was called")
        await _until_ended(job)
        return job

    job = asyncio.run(main())

    assert job.state == CANCELLED
    assert [healthy for _, _, healthy in kit.handed_back] == [True]


def _new_stage(kit: FakeKit) -> Usd.Stage:
    """A stage opened in place of the sweep's, with an A and a B of its own a shot could switch."""
    area = Path(kit.get_stage().GetPrimAtPath(A).GetPrimStack()[-1].layer.realPath)
    new = Usd.Stage.CreateInMemory()
    for path in (A, B):
        new.DefinePrim(path).GetReferences().AddReference(str(area))
    return new


def test_a_stage_opened_at_a_shot_s_start_gets_none_of_its_writes(env, kit, tmp_path):
    new = _new_stage(kit)
    new_before = layers(new)

    async def swap(number: int) -> None:
        # Opened between shot 1 and shot 2, before the watch's next update: nothing cancelled the sweep yet.
        if number == 1:
            kit.stage, kit.stage_id = new, 2

    kit.on_capture = swap
    _, job = _run(env, _body(tmp_path, FOUR))

    assert (job.state, job.message) == (CANCELLED, "the stage changed")
    assert layers(new) == new_before
    assert len(kit.seen) == 1
    assert _manifest(tmp_path)["ended"] == "cancelled: the stage changed"


def test_a_stage_opened_while_a_shot_waits_for_its_switch_gets_none_of_its_writes(env, kit, tmp_path):
    new = _new_stage(kit)
    new_before = layers(new)
    new_timeline = FakeTimeline("paused", 9.0)

    def swap() -> None:
        kit.stage, kit.stage_id, kit.timeline = new, 2, new_timeline

    kit.on_refresh = swap
    _, job = _run(env, _body(tmp_path, [_pose(selections={A: {"state": "open"}}, time=2)]))

    assert (job.state, job.message) == (CANCELLED, "the stage changed")
    assert layers(new) == new_before
    assert new_timeline.calls == []
    assert kit.seen == []


def test_a_second_cancel_while_the_feed_is_handed_back_still_leaves_the_manifest_and_the_last_line(env, kit, tmp_path):
    stage = kit.get_stage()
    before = layers(stage)

    async def cancel(number: int) -> None:
        if number == 2:
            env.board.cancel("j1", "cancel_job was called")
            await asyncio.sleep(0)

    kit.on_capture = cancel
    kit.on_hand_back = lambda: env.board.cancel("j1", "cancel_job was called")
    _, job = _run(env, _body(tmp_path, FOUR))

    assert job.state == CANCELLED
    assert settled(kit, stage) == before
    assert _manifest(tmp_path)["ended"] == "cancelled: cancel_job was called"
    folder = tmp_path / "sweeps" / "site_a"
    assert job.lines.last == f"1 of 4 shots in {folder}/ (manifest.json); cancelled: cancel_job was called"


def test_every_selection_comes_back_in_one_change(env, kit, tmp_path):
    stage = kit.get_stage()
    changed: list[int] = []
    listeners: list[Any] = []

    async def listen(number: int) -> None:
        if number == 30:
            listeners.append(Tf.Notice.Register(Usd.Notice.ObjectsChanged, lambda *_: changed.append(1), stage))

    kit.on_capture = listen
    shots = [
        _pose(selections={A: {"state": ("open", "closed")[i % 2]}, B: {"lod": ("low", "high")[i % 2]}})
        for i in range(30)
    ]
    _run(env, _body(tmp_path, shots))

    # The selections and the camera deleted: one change each, where a block per snapshot made one per shot's switch
    # (code review, F2).
    assert len(changed) <= 4, len(changed)


def test_what_rtx_writes_onto_the_cameras_rendered_through_comes_back_with_the_feed_s_render_product(
    env, kit, tmp_path
):
    # A scene camera without exposure, under a prim a later shot switches.
    stage = kit.get_stage()
    UsdGeom.Camera.Define(stage, f"{A}/Lens").GetFocalLengthAttr().Set(10.0)
    before = layers(stage)
    shots = [{"camera_path": f"{A}/Lens"}, _pose(selections={A: {"state": "open"}})]

    _, job = _run(env, _body(tmp_path, shots))

    assert job.state == COMPLETED
    assert [s["camera"] for s in kit.seen] == [f"{A}/Lens", sweep.CAMERA_PATH]
    root = stage.GetRootLayer()
    # Kept with the feed: RTX's writes onto both cameras, the sweep's an over once its camera is deleted.
    assert "exposure:fStop" in root.GetPrimAtPath(f"{A}/Lens").attributes
    assert "exposure:fStop" in root.GetPrimAtPath(sweep.CAMERA_PATH).attributes
    assert not stage.GetPrimAtPath(sweep.CAMERA_PATH).IsDefined()
    # Which the next sweep's start ignores, and whose camera it marks again.
    _, again = _run(env, _body(tmp_path, FOUR[:1], name="again"))
    assert again.state == COMPLETED, again.error
    assert settled(kit, stage) == before


def test_an_empty_over_left_at_the_sweep_s_camera_blocks_nothing_and_stays(env, kit, tmp_path):
    # RTX's in the root layer, as a kept feed leaves it until its render product goes (#177), and one in the session
    # layer with something in it.
    stage = kit.get_stage()
    Sdf.CreatePrimInLayer(stage.GetRootLayer(), Sdf.Path(sweep.CAMERA_PATH))
    held = Sdf.CreatePrimInLayer(stage.GetSessionLayer(), Sdf.Path(sweep.CAMERA_PATH))
    Sdf.AttributeSpec(held, "exposure:time", Sdf.ValueTypeNames.Float).default = 0.5
    before = layers(stage)

    _, job = _run(env, _body(tmp_path, FOUR[:1]))

    assert job.state == COMPLETED, job.error
    assert settled(kit, stage) == before


# ----- the start -----


def test_the_start_answers_at_once_with_the_job_and_the_folder(env, kit, tmp_path):
    async def main() -> dict[str, Any]:
        return await env.handler.handle_sweep_start(_body(tmp_path, FOUR))

    started = asyncio.run(main())

    folder = tmp_path / "sweeps" / "site_a"
    assert started == {
        "status": "success",
        "result": {
            "id": "j1",
            "kind": "sweep",
            "label": "4 shots at 1280x720: site_a",
            "folder": str(folder),
            "manifest": str(folder / "manifest.json"),
            "shots": 4,
            "width": 1280,
            "height": 720,
        },
    }


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"name": "../site_a"}, "name must be one plain folder name"),
        ({"output_dir": ""}, "output_dir is required"),
        ({"width": 0}, "width must be a whole number of pixels from 1 to 4096"),
        ({"shots": [{"position": [0, 0, 1]}]}, "shot 1: position needs yaw"),
        ({"shots": [_pose(selections={A: {"state": "ajar"}})]}, "/World/A's variant set 'state' has no variant 'ajar'"),
    ],
)
def test_a_bad_start_is_refused_before_anything_is_made(env, kit, tmp_path, change, says):
    before = layers(kit.get_stage())

    refused = asyncio.run(env.handler.handle_sweep_start({**_body(tmp_path, FOUR), **change}))

    assert refused["status"] == "error"
    assert says in refused["error"]
    assert not (tmp_path / "sweeps").exists()
    assert not (tmp_path / "site_a").exists()
    assert layers(kit.get_stage()) == before
    assert env.board.running() is None


def test_a_kit_app_that_can_t_render_a_camera_into_a_texture_is_refused(env, kit, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "omni.kit.hydra_texture", None)

    refused = asyncio.run(env.handler.handle_sweep_start(_body(tmp_path, FOUR)))

    assert refused["error"] == "This Kit app can't capture from a camera: it has no omni.kit.hydra_texture"
    assert not (tmp_path / "sweeps").exists()


def test_a_folder_that_holds_a_manifest_is_refused_naming_it(env, kit, tmp_path):
    folder = tmp_path / "sweeps" / "site_a"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}", encoding="utf-8")

    refused = asyncio.run(env.handler.handle_sweep_start(_body(tmp_path, FOUR)))

    assert refused["error"].startswith(f"{folder} holds a sweep's manifest.json already")


def test_a_camera_left_by_an_earlier_sweep_is_refused(env, kit, tmp_path):
    UsdGeom.Camera.Define(kit.get_stage(), sweep.CAMERA_PATH)

    refused = asyncio.run(env.handler.handle_sweep_start(_body(tmp_path, FOUR)))

    assert refused["error"].startswith("/OmniverseKit_Sweep is on the stage already")


def test_a_busy_board_is_refused_and_the_folder_made_for_it_removed(env, kit, tmp_path):
    async def main() -> dict[str, Any]:
        async def forever(_job: Job) -> dict[str, Any]:
            await asyncio.get_running_loop().create_future()
            return {}

        env.board.start("script", "bake", forever)
        refused = await env.handler.handle_sweep_start(_body(tmp_path, FOUR))
        env.board.cancel("j1", "done")
        await asyncio.sleep(0)
        return refused

    refused = asyncio.run(main())

    assert refused["error"].startswith("Job j1 (script) is working: one job runs at a time")
    assert not (tmp_path / "sweeps" / "site_a").exists()
