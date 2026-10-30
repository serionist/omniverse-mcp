"""What start_recording accepts, when a recording takes its frames and how its render product leaves the stage:
core/recording.py, on usd-core, without Kit (#25, #69)."""

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
    steps_per_frame,
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


@pytest.mark.parametrize(("codes", "fps", "steps"), [(60, 5, 12), (60, 30, 2), (60, 60, 1), (60, 1000, 1), (24, 5, 4)])
def test_steps_per_frame(codes, fps, steps):
    assert steps_per_frame(codes, fps) == steps


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


def _ticks(clock: FrameClock, updates: int, render_pending: bool = False) -> list[int | None]:
    return [clock.tick(render_pending) for _ in range(updates)]


def test_the_clock_takes_a_frame_every_steps_updates_numbered_in_order():
    clock = FrameClock(3)
    taken = _ticks(clock, 6)
    assert taken == [None, None, 0, None, None, 1]
    clock.done()
    clock.done()
    assert _ticks(clock, 3) == [None, None, 2]
    assert clock.taken == 3


def test_the_clock_takes_none_while_the_last_frame_awaits_its_render():
    clock = FrameClock(1)
    assert clock.tick() == 0
    assert clock.tick(render_pending=True) is None
    assert clock.tick() == 1  # the number skipped isn't lost: numbers stay in order without gaps


def test_the_clock_takes_none_while_four_frames_are_written_and_one_again_once_a_place_is_free():
    clock = FrameClock(1)
    assert _ticks(clock, MAX_IN_FLIGHT + 2) == [0, 1, 2, 3, None, None]
    clock.done()
    assert clock.tick() == 4
    assert clock.tick() is None
    assert clock.in_flight == MAX_IN_FLIGHT


def test_no_number_is_given_twice_whatever_order_frames_end_in():
    # Today's recording numbered a frame when its capture ended, so ticks closer than a capture shared one (#69).
    clock = FrameClock(2)
    numbers = []
    for update in range(200):
        number = clock.tick()
        if number is not None:
            numbers.append(number)
        if update % 3 == 0:
            clock.done()
    assert numbers == list(range(len(numbers)))


def test_done_never_counts_below_none_in_flight():
    clock = FrameClock(1)
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
