"""What start_recording accepts, when a recording takes its frames and how its render product leaves the stage:
core/recording.py, on usd-core, without Kit (#25, #69)."""

import itertools

import pytest
from pxr import Sdf, Usd, UsdGeom

from ovmcp.core.recording import (
    DEFAULT_SIZE,
    MAX_IN_FLIGHT,
    RENDER_SETTINGS_PRODUCTS,
    FrameClock,
    RecordingArgs,
    camera_error,
    delete_render_product,
    recording_args,
)

BODY = {"output_dir": "C:/out/recordings"}


def test_a_request_with_only_its_folder_takes_the_defaults():
    assert recording_args(BODY) == RecordingArgs("C:/out/recordings", 5, *DEFAULT_SIZE, "", [], None)


def test_a_request_keeps_what_it_was_given():
    body = {
        **BODY,
        "fps": 30,
        "width": 4096,
        "height": 16,
        "camera_path": "/World/RecCam",
        "track_prims": ["/World/G1"],
        "property_filter": ["joint"],
    }
    assert recording_args(body) == RecordingArgs(
        "C:/out/recordings", 30, 4096, 16, "/World/RecCam", ["/World/G1"], ["joint"]
    )


@pytest.mark.parametrize(
    ("change", "says"),
    [
        ({"output_dir": ""}, "output_dir is required"),
        ({"output_dir": None}, "output_dir is required"),
        ({"fps": 0}, "fps must be a whole number of at least 1"),
        ({"fps": True}, "fps must be a whole number of at least 1"),
        ({"fps": 2.5}, "fps must be a whole number of at least 1"),
        ({"width": 4097}, "width must be a whole number of pixels from 1 to 4096"),
        ({"height": 0}, "height must be a whole number of pixels from 1 to 4096"),
        ({"camera_path": 3}, "camera_path must be a prim path"),
        ({"track_prims": "/World/G1"}, "track_prims must be a list of strings"),
        ({"property_filter": [1]}, "property_filter must be a list of strings"),
    ],
)
def test_a_bad_request_is_refused_saying_what_is_wrong(change, says):
    with pytest.raises(ValueError, match=says):
        recording_args({**BODY, **change})


@pytest.fixture
def stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Camera.Define(stage, "/World/RecCam")
    UsdGeom.Cube.Define(stage, "/World/RedCube")
    return stage


def test_a_camera_can_be_recorded_from(stage):
    assert camera_error(stage, "/World/RecCam") is None


@pytest.mark.parametrize(
    ("path", "says"),
    [
        ("/World/Nothing", "No prim at /World/Nothing"),
        ("/World/RedCube", "/World/RedCube is a Cube prim, not a Camera"),
        ("/World", "/World is a Xform prim, not a Camera"),
        ("World/RecCam", "must be an absolute prim path"),
        ("/World/Rec Cam", "must be an absolute prim path"),
        ("", "must be an absolute prim path"),
    ],
)
def test_anything_but_a_camera_is_refused_saying_why(stage, path, says):
    error = camera_error(stage, path)
    assert error is not None
    assert says in error


class Updates:
    """A Kit's updates as the clock sees them: the timeline's state and time and the wall clock, moved by hand. Each
    update ticks the clock with them, then moves them on by the steps given."""

    def __init__(self, clock: FrameClock) -> None:
        self.clock = clock
        self.update = 0
        self.playing = False
        self.sim = 0.0
        self.now = 0.0
        # Each frame taken: the update it came on, its number, and the clock's seconds of each kind then.
        self.frames: list[tuple[int, int, float, float]] = []

    def run(
        self,
        count: int,
        sim_step: float = 1 / 60,
        wall_step: float = 1 / 120,
        render_pending: bool = False,
        written: bool = True,
    ) -> list[int | None]:
        """`count` updates, each moving the simulation by `sim_step` while it plays and the clock by `wall_step`;
        `written` marks each frame's file written at once, so none stays in flight."""
        taken = []
        for _ in range(count):
            number = self.clock.tick(self.playing, self.sim, self.now, render_pending)
            if number is not None:
                self.frames.append((self.update, number, self.clock.simulated, self.clock.idle))
                if written:
                    self.clock.done()
            taken.append(number)
            self.update += 1
            self.sim += sim_step if self.playing else 0.0
            self.now += wall_step
        return taken

    def at(self) -> list[int]:
        """The updates frames came on."""
        return [update for update, _number, _simulated, _idle in self.frames]


def test_while_playing_a_frame_comes_every_0_2_s_of_simulation_whatever_the_update_rate():
    # 150 updates a second by the clock, each 1/60 s of simulation, as on the probe's Kit (#111's P1).
    updates = Updates(FrameClock(5))
    updates.playing = True
    updates.run(120, wall_step=1 / 150)
    assert updates.at() == list(range(0, 120, 12))
    assert [number for _update, number, _s, _i in updates.frames] == list(range(10))
    assert updates.clock.taken == 10


def test_an_fps_that_doesnt_divide_the_time_codes_keeps_its_rate_while_playing():
    # Counting updates took one every 8 at fps=7, 75 frames in 10 s of simulation.
    updates = Updates(FrameClock(7))
    updates.playing = True
    updates.run(600)
    assert updates.clock.taken == 70


@pytest.mark.parametrize("sim", [0.0, 2.5], ids=["stopped", "paused"])
def test_while_not_playing_a_frame_comes_every_0_2_s_by_the_clock_whatever_the_update_rate(sim):
    # Counting updates took one every 12 at 60 time codes a second: 10 frames a second at 120 updates (#111's P2).
    updates = Updates(FrameClock(5))
    updates.sim = sim
    updates.run(240)
    assert updates.at() == list(range(0, 240, 24))
    assert (updates.clock.simulated, updates.clock.taken) == (0.0, 10)


def test_across_play_and_pause_each_frame_is_a_period_of_its_own_kind_after_the_last():
    updates = Updates(FrameClock(5))
    updates.run(120)  # stopped, 1 s
    updates.playing = True
    updates.run(120)  # playing, 2 s of simulation in 1 s by the clock
    updates.playing = False
    updates.run(120)  # paused, 1 s
    seconds = [simulated + idle for _update, _number, simulated, idle in updates.frames]
    gaps = [b - a for a, b in itertools.pairwise(seconds)]
    # No frame twice at a change, and none skipped: each one period of the recording's clock after the last, give or
    # take the one update whose kind changed.
    assert all(abs(gap - 0.2) < 1 / 120 + 1e-9 for gap in gaps), gaps
    assert updates.clock.taken == 20
    assert updates.clock.simulated == pytest.approx(119 / 60)
    assert updates.clock.idle == pytest.approx(240 / 120)


def test_a_timeline_that_plays_and_doesnt_move_takes_frames_by_the_clock():
    # A file with no time-code range plays over a single frame: Isaac Sim warns so, and its time never moves (#111's
    # review P2). Its updates add wall time, as stopped ones do, where adding nothing took frame 0 alone.
    updates = Updates(FrameClock(5))
    updates.playing = True
    updates.run(240, sim_step=0.0)
    assert updates.at() == list(range(0, 240, 24))
    assert updates.clock.simulated == 0.0
    assert updates.clock.idle == pytest.approx(239 / 120)


def test_a_step_back_while_playing_adds_that_update_s_wall_time():
    updates = Updates(FrameClock(5))
    updates.playing = True
    updates.run(60)
    simulated, idle = updates.clock.simulated, updates.clock.idle
    updates.sim = 0.0  # a loop at the end time, or a time set back by hand
    updates.run(1)
    assert updates.clock.simulated == simulated
    assert updates.clock.idle == pytest.approx(idle + 1 / 120)


def test_a_frame_held_by_a_pending_render_comes_on_the_next_update_that_can_take_it():
    updates = Updates(FrameClock(5))
    assert updates.run(24) == [0] + [None] * 23
    assert updates.run(2, render_pending=True) == [None, None]  # updates 24 and 25: frame 1 is due, its render isn't
    updates.run(60)
    # Frame 1 on update 26, and frame 2 still on its own boundary, 0.4 s at update 48: frames keep to the clock.
    assert updates.at() == [0, 26, 48, 72]


def test_after_a_stall_of_several_periods_one_frame_comes_then_the_next_boundary_after_the_clock():
    updates = Updates(FrameClock(5))
    updates.run(24)
    updates.run(77, render_pending=True)  # updates 24 to 100: boundaries 0.2 to 0.8 pass
    updates.run(40)
    assert updates.at() == [0, 101, 120]


def test_the_clock_takes_none_while_four_frames_are_written_and_one_again_once_a_place_is_free():
    updates = Updates(FrameClock(60))
    assert updates.run(MAX_IN_FLIGHT + 2, wall_step=1 / 60, written=False) == [0, 1, 2, 3, None, None]
    updates.clock.done()
    assert updates.run(2, wall_step=1 / 60, written=False) == [4, None]
    assert updates.clock.in_flight == MAX_IN_FLIGHT


def test_no_number_is_given_twice_whatever_order_frames_end_in():
    # Today's recording numbered a frame when its capture ended, so ticks closer than a capture shared one (#69).
    clock = FrameClock(30)
    numbers = []
    for update in range(200):
        number = clock.tick(False, 0.0, update / 60)
        if number is not None:
            numbers.append(number)
        if update % 3 == 0:
            clock.done()
    assert numbers == list(range(len(numbers)))
    assert len(numbers) > 50


def test_done_never_counts_below_none_in_flight():
    clock = FrameClock(5)
    clock.done()
    assert clock.in_flight == 0


PRODUCT = "/Render/OmniverseKit/HydraTextures/ovmcp_recording_0123"
VIEWPORT = "/Render/OmniverseKit/HydraTextures/omni_kit_widget_viewport_ViewportTexture_0"


def _kit_stage() -> Usd.Stage:
    """A stage as Kit leaves it with a feed's texture alive (#25's E12, E22): the render product a `def` in the root
    layer and an `over` in the session layer, and listed in the render settings' products beside the viewport's."""
    stage = Usd.Stage.CreateInMemory()
    settings = stage.DefinePrim("/Render/OmniverseGlobalRenderSettings", "RenderSettings")
    settings.CreateRelationship("products").SetTargets([VIEWPORT, PRODUCT])
    stage.DefinePrim(VIEWPORT, "RenderProduct")
    stage.DefinePrim(PRODUCT, "RenderProduct").CreateAttribute("resolution", Sdf.ValueTypeNames.Int2)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.OverridePrim(PRODUCT).CreateAttribute("deviceIds", Sdf.ValueTypeNames.IntArray)
    return stage


def _named(stage: Usd.Stage) -> list[str]:
    return [
        name
        for name, layer in (("root", stage.GetRootLayer()), ("session", stage.GetSessionLayer()))
        if "ovmcp_recording_0123" in layer.ExportToString()
    ]


def test_deleting_a_render_product_leaves_no_trace_of_it_in_any_layer():
    stage = _kit_stage()
    assert _named(stage) == ["root", "session"]
    delete_render_product(stage, PRODUCT)
    assert not stage.GetPrimAtPath(PRODUCT)
    assert _named(stage) == []
    # The viewport's own render product, and its entry, are left as they were.
    assert stage.GetPrimAtPath(VIEWPORT)
    targets = stage.GetPrimAtPath("/Render/OmniverseGlobalRenderSettings").GetRelationship("products").GetTargets()
    assert targets == [Sdf.Path(VIEWPORT)]


def test_a_render_product_listed_by_a_prepend_goes_from_that_list_too():
    stage = Usd.Stage.CreateInMemory()
    settings = stage.DefinePrim("/Render/OmniverseGlobalRenderSettings", "RenderSettings")
    settings.CreateRelationship("products").AddTarget(PRODUCT, Usd.ListPositionFrontOfPrependList)
    stage.DefinePrim(PRODUCT, "RenderProduct")
    delete_render_product(stage, PRODUCT)
    assert _named(stage) == []
    assert stage.GetRootLayer().GetRelationshipAtPath(RENDER_SETTINGS_PRODUCTS) is not None


def test_deleting_a_render_product_twice_or_on_a_stage_without_one_does_nothing():
    stage = _kit_stage()
    delete_render_product(stage, PRODUCT)
    delete_render_product(stage, PRODUCT)
    empty = Usd.Stage.CreateInMemory()
    delete_render_product(empty, PRODUCT)
    assert not empty.GetPrimAtPath("/Render")
