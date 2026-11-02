"""A capture sweep's Kit-free core (#157), on usd-core: shots read and refused before anything changes, a manifest read
back as shots, the lens against the image's shape, poses on a Z-up and a Y-up stage, the selections written before each
shot and reverted to what the session layer held at the start, the timeline put back, and the manifest, file and folder
names.

The stage is #155's case: an area's file with the variant sets state (closed selected) and lod (none selected), brought
in by a site file the stage references.
"""

import math
from pathlib import Path

import pytest
from pxr import Gf, Sdf, Usd

from ovmcp.core import sweep, variants
from ovmcp.core.sweep import Lens, Shot, Taken, TimelineStart, changes, read_shots
from ovmcp.core.usd import floats, select

from .test_variants import AREA, write_files

W, H = 1280, 720
# The case's front camera: 7.337 mm, 20.955 x 11.787 mm at 1280 x 720.
CASE_LENS = {"focal_length": 7.337, "horizontal_aperture": 20.955, "vertical_aperture": 11.787}


@pytest.fixture
def stage(tmp_path: Path) -> Usd.Stage:
    files = write_files(tmp_path)
    stage = Usd.Stage.CreateInMemory()
    stage.DefinePrim("/World")
    stage.DefinePrim("/World/Site").GetReferences().AddReference(str(files / "site.usda"), "/Site")
    return stage


def _shots(*raw: object) -> list[Shot]:
    return read_shots(list(raw), W, H)


def _one(**raw: object) -> Shot:
    return _shots(raw)[0]


def _refusal(*raw: object) -> str:
    with pytest.raises(ValueError, match=r".") as caught:
        _shots(*raw)
    return str(caught.value)


def _close(a: Gf.Vec3d, b: tuple[float, float, float]) -> bool:
    return all(math.isclose(x, y, abs_tol=1e-9) for x, y in zip(floats(a), b, strict=True))


# ----- shots read -----


def test_a_shot_with_a_yaw_and_pitch_gets_the_default_lens_fitted_to_the_image():
    shot = _one(name="dock A", position=[1, 2, 0.65], yaw=90, selections={"/World/Dock": {"door": "open"}}, time=2)

    assert (shot.position, shot.yaw, shot.pitch, shot.target) == ((1.0, 2.0, 0.65), 90.0, 0.0, None)
    assert shot.lens == sweep.default_lens(W, H)
    assert shot.lens is not None
    assert shot.lens.focal_length == sweep.FOCAL_LENGTH
    assert (shot.lens.horizontal_aperture, shot.lens.vertical_aperture) == pytest.approx((20.955, 20.955 * 720 / 1280))
    assert shot.selections == {"/World/Dock": {"door": "open"}}
    assert (shot.name, shot.time, shot.clipping) == ("dock A", 2.0, None)


def test_the_case_s_lens_fits_its_image_and_is_kept():
    assert _one(position=[0, 0, 0.65], yaw=0, **CASE_LENS).lens == Lens(7.337, 20.955, 11.787)


@pytest.mark.parametrize(
    ("given", "lens"),
    [
        ({"focal_length": 10}, Lens(10, 20.955, 11.7871875)),
        ({"horizontal_aperture": 36}, Lens(sweep.FOCAL_LENGTH, 36, 20.25)),
        ({"vertical_aperture": 9}, Lens(sweep.FOCAL_LENGTH, 16, 9)),
    ],
)
def test_an_aperture_left_out_is_fitted_to_the_image(given, lens):
    got = _one(position=[0, 0, 1], yaw=0, **given).lens
    assert got is not None
    assert got.focal_length == pytest.approx(lens.focal_length)
    assert got.horizontal_aperture == pytest.approx(lens.horizontal_aperture)
    assert got.vertical_aperture == pytest.approx(lens.vertical_aperture)


def test_apertures_that_don_t_fit_the_image_are_refused_naming_the_one_that_fits():
    # Kit's 4:3 default, 20.955 x 15.2908, on a 16:9 image would be stretched or cropped.
    why = _refusal({"position": [0, 0, 1], "yaw": 0, "horizontal_aperture": 20.955, "vertical_aperture": 15.2908})

    assert why.startswith("shot 1: apertures 20.955 x 15.2908 mm don't fit a 1280 x 720 image")
    assert "give vertical_aperture 11.79 for horizontal_aperture 20.955" in why


def test_a_target_shot_and_a_camera_path_shot_are_read():
    target, camera = _shots(
        {"position": [0, 0, 1], "target": [5, 0, 0]}, {"camera_path": "/World/Robot/FrontCam", "time": 1.5}
    )

    assert (target.target, target.yaw) == ((5.0, 0.0, 0.0), None)
    assert (camera.camera_path, camera.lens, camera.position, camera.time) == ("/World/Robot/FrontCam", None, None, 1.5)


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        ({"yaw": 3}, "a shot needs a pose"),
        ({"position": [0, 0, 1]}, "position needs yaw (and pitch) or target"),
        ({"position": [0, 0, 1], "yaw": 0, "target": [1, 0, 0]}, "with yaw and pitch, or with target, not both"),
        ({"position": [0, 0, 1], "target": [0, 0, 1]}, "is the position: there is nothing to look at"),
        ({"position": [0, 0], "yaw": 0}, "position must be [x, y, z], 3 numbers"),
        ({"position": [0, 0, "up"], "yaw": 0}, "position must be a number"),
        ({"position": [0, 0, 1], "yaw": math.inf}, "yaw must be a number"),
        ({"position": [0, 0, 1], "yaw": True}, "yaw must be a number"),
        ({"position": [0, 0, 1], "yaw": 0, "pitch": -91}, "pitch must be from -90 (straight down) to 90"),
        ({"position": [0, 0, 1], "yaw": 0, "focal_length": 0}, "focal_length must be above 0"),
        ({"position": [0, 0, 1], "yaw": 0, "clipping_range": [5, 1]}, "clipping_range's near must be under its far"),
        ({"position": [0, 0, 1], "yaw": 0, "clipping_range": 5}, "clipping_range must be [near, far]"),
        ({"position": [0, 0, 1], "yaw": 0, "selections": {"/World/A B": {"a": "b"}}}, "must be a prim path"),
        (
            {"position": [0, 0, 1], "yaw": 0, "selections": {"/World": {}}},
            "selections of /World must be {set: variant}",
        ),
        ({"position": [0, 0, 1], "yaw": 0, "time": "3"}, "time must be a number"),
        ({"position": [0, 0, 1], "yaw": 0, "selections": {"World": {"a": "b"}}}, "must be an absolute prim path"),
        ({"position": [0, 0, 1], "yaw": 0, "selections": {"/World": {"door": ""}}}, "both names"),
        ({"position": [0, 0, 1], "yaw": 0, "selections": ["/World"]}, "selections must be {prim: {set: variant}}"),
        ({"camera_path": "World/Cam"}, "camera_path must be an absolute prim path"),
        ({"camera_path": "/World/Cam", "focal_length": 7}, "a camera_path shot renders through /World/Cam as it is"),
        ({"camera_path": "/World/Cam", "yaw": 7}, "give a pose and a lens, or camera_path, not both"),
        ({"position": [0, 0, 1], "yaw": 0, "focal_lenght": 7}, "unknown fields focal_lenght; a shot's fields:"),
        ({"position": [0, 0, 1], "yaw": 0, "file": "0001.png"}, "unknown fields file"),
        ({"position": [0, 0, 1], "yaw": 0, "name": 3}, "name must be text"),
        ("dock", "a shot is an object of its fields"),
    ],
)
def test_a_bad_shot_is_refused_naming_its_number(raw, says):
    why = _refusal({"position": [0, 0, 1], "yaw": 0}, raw)
    assert why.startswith("shot 2: ")
    assert says in why


def test_every_shot_is_checked_and_the_first_ten_faults_shown():
    why = _refusal(*[{"position": [0, 0, 1]}] * 14)

    lines = why.splitlines()
    assert lines[0].startswith("shot 1: position needs yaw")
    assert lines[9].startswith("shot 10: ")
    assert lines[10:] == ["and 4 more"]


@pytest.mark.parametrize(
    ("value", "says"),
    [
        ([], "shots is empty"),
        ([{"position": [0, 0, 1], "yaw": 0}] * (sweep.MAX_SHOTS + 1), "2001 shots is more than a sweep takes, 2000"),
        ({"position": [0, 0, 1]}, "shots must be a list of shots, or a sweep's manifest, got dict"),
        ({"shots": "all"}, "got a manifest without a list of shots"),
        ("shots", "got str"),
    ],
)
def test_a_list_that_isn_t_one_is_refused(value, says):
    with pytest.raises(ValueError, match=r".") as caught:
        read_shots(value, W, H)
    assert says in str(caught.value)


# ----- a manifest read back -----


def _manifest(*taken: Taken) -> dict[str, object]:
    return sweep.manifest({"name": "site_a", "width": W, "height": H}, taken)


def test_a_manifest_reads_back_as_the_shots_it_took():
    shots = _shots(
        {"name": "a", "position": [1, 2, 0.65], "yaw": 30, "pitch": -10, **CASE_LENS},
        {"name": "b", "position": [0, 0, 1], "target": [3, 4, 0], "selections": {AREA: {"state": "open"}}, "time": 2},
        {"position": [0, 0, 1], "yaw": 0, "clipping_range": [0.1, 500]},
    )
    taken = [
        Taken(i, shot, file=sweep.file_name(i, shot), frame=48.0, timeline_time=2.0) for i, shot in enumerate(shots, 1)
    ]

    assert read_shots(_manifest(*taken), W, H) == shots


def test_a_camera_path_shot_reads_back_as_the_pose_lens_and_clipping_it_rendered_with():
    # So a twin on another scene takes the same view without that scene having the camera (round 2, P15).
    (shot,) = _shots({"camera_path": "/World/Robot/FrontCam", "selections": {AREA: {"lod": "low"}}, "time": 1})
    taken = Taken(
        1,
        shot,
        file="0001.png",
        position=(4.0, 5.0, 0.65),
        yaw=120.0,
        pitch=-5.0,
        lens=Lens(7.337, 20.955, 11.787),
        clipping=(0.05, 200.0),
    )

    entry = sweep.entry(taken)
    (back,) = read_shots(_manifest(taken), W, H)

    assert entry["camera_path"] == "/World/Robot/FrontCam"
    assert back == Shot(
        position=(4.0, 5.0, 0.65),
        yaw=120.0,
        pitch=-5.0,
        lens=Lens(7.337, 20.955, 11.787),
        clipping=(0.05, 200.0),
        selections={AREA: {"lod": "low"}},
        time=1.0,
    )


def test_a_camera_path_shot_that_never_rendered_reads_back_as_its_camera():
    (shot,) = _shots({"camera_path": "/World/Robot/FrontCam"})
    taken = Taken(1, shot, error="No prim at /World/Robot/FrontCam")

    assert read_shots(_manifest(taken), W, H) == [shot]


def test_a_manifest_entry_s_unknown_field_is_still_refused():
    manifest = _manifest(Taken(1, _one(position=[0, 0, 1], yaw=0), file="0001.png"))
    shots = manifest["shots"]
    assert isinstance(shots, list)
    shots[0]["focal_lenght"] = 7

    with pytest.raises(ValueError, match="shot 1: unknown fields focal_lenght"):
        read_shots(manifest, W, H)


# ----- poses -----


@pytest.mark.parametrize(
    ("up_axis", "yaw", "pitch", "looks"),
    [
        ("Z", 0, 0, (1, 0, 0)),
        ("Z", 90, 0, (0, 1, 0)),
        ("Z", 0, 90, (0, 0, 1)),
        ("Z", 0, -90, (0, 0, -1)),
        ("Y", 0, 0, (1, 0, 0)),
        ("Y", 90, 0, (0, 0, -1)),
        ("Y", 0, -90, (0, -1, 0)),
    ],
)
def test_yaw_turns_about_the_stage_s_up_axis_and_pitch_tilts_above_the_horizon(up_axis, yaw, pitch, looks):
    assert _close(sweep.direction(yaw, pitch, up_axis), looks)


@pytest.mark.parametrize("up_axis", ["Z", "Y"])
@pytest.mark.parametrize(("yaw", "pitch"), [(0, 0), (37.5, -12), (-150, 60), (179, 0)])
def test_yaw_pitch_reads_back_a_direction(up_axis, yaw, pitch):
    got = sweep.yaw_pitch(sweep.direction(yaw, pitch, up_axis) * 4, up_axis)
    assert got == pytest.approx((yaw, pitch))


def test_a_pose_is_its_position_and_a_point_along_its_direction_or_its_target():
    eye, target = sweep.pose(_one(position=[1, 2, 3], yaw=90, pitch=0), "Z")
    assert _close(eye, (1, 2, 3))
    assert _close(target, (1, 3, 3))
    eye, target = sweep.pose(_one(position=[1, 2, 3], target=[9, 9, 9]), "Y")
    assert _close(target, (9, 9, 9))
    with pytest.raises(ValueError, match="has a pose of its own"):
        sweep.pose(_one(camera_path="/World/Cam"), "Z")


# ----- the selections before each shot -----

DOCK, LIGHT = "/World/Dock", "/World/Light"


def test_a_set_a_shot_doesn_t_name_goes_back_to_its_start_absent_blocked_or_named():
    # Start: the dock's door absent from the session layer, its lamp blocked, the light's time named night (an earlier
    # set_variant_selection, session by default); shot 1 changes all three, shot 2 names none (round 1, P1).
    start: sweep.Held = {(DOCK, "door"): None, (DOCK, "lamp"): "", (LIGHT, "time"): "night"}
    shot1 = _one(position=[0, 0, 1], yaw=0, selections={DOCK: {"door": "open", "lamp": "on"}, LIGHT: {"time": "dusk"}})
    shot2 = _one(position=[0, 0, 1], yaw=0)

    first = changes(start, start, shot1)
    written = sweep.written_after(start, first)
    second = changes(start, written, shot2)

    assert first == {DOCK: {"door": "open", "lamp": "on"}, LIGHT: {"time": "dusk"}}
    assert second == {DOCK: {"door": None, "lamp": ""}, LIGHT: {"time": "night"}}
    assert sweep.written_after(written, second) == start


def test_a_shot_merges_its_own_selections_with_the_reverts_of_the_last_shot_s():
    start: sweep.Held = {(DOCK, "door"): None, (LIGHT, "time"): None}
    written = sweep.written_after(start, {DOCK: {"door": "open"}})
    shot = _one(position=[0, 0, 1], yaw=0, selections={LIGHT: {"time": "day"}})

    assert changes(start, written, shot) == {DOCK: {"door": None}, LIGHT: {"time": "day"}}


def test_a_run_of_shots_in_one_state_writes_nothing():
    start: sweep.Held = {(DOCK, "door"): None}
    shot = _one(position=[0, 0, 1], yaw=0, selections={DOCK: {"door": "open"}})
    written = sweep.written_after(start, changes(start, start, shot))

    assert changes(start, written, shot) == {}
    assert changes(start, start, _one(position=[0, 0, 1], yaw=0)) == {}


def test_after_a_refused_shot_the_next_writes_what_it_shares_with_it():
    # Against what was written, never the last shot asked for: a refused shot wrote nothing (round 2, P13).
    start: sweep.Held = {(DOCK, "door"): None, (DOCK, "lamp"): None}
    refused = _one(position=[0, 0, 1], yaw=0, selections={DOCK: {"door": "open", "lamp": "bogus"}})
    nxt = _one(position=[0, 0, 1], yaw=0, selections={DOCK: {"door": "open"}})
    assert changes(start, start, refused)  # its switch raised: written stays the start

    assert changes(start, start, nxt) == {DOCK: {"door": "open"}}


def test_named_lists_every_set_a_shot_selects_once_in_order():
    shots = _shots(
        {"position": [0, 0, 1], "yaw": 0, "selections": {DOCK: {"door": "open"}}},
        {"position": [0, 0, 1], "yaw": 0, "selections": {LIGHT: {"time": "day"}, DOCK: {"door": "shut"}}},
    )
    assert sweep.named(shots) == [(DOCK, "door"), (LIGHT, "time")]


def test_held_reads_each_set_s_session_value(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    select(Sdf.CreatePrimInLayer(session, AREA), "state", "open")
    select(Sdf.CreatePrimInLayer(session, AREA), "lod", "")

    got = sweep.held(session, [(AREA, "state"), (AREA, "lod"), ("/World/Site", "x")])

    assert got == {(AREA, "state"): "open", (AREA, "lod"): "", ("/World/Site", "x"): None}


# ----- the switch -----


def _area(stage: Usd.Stage, name: str = "state") -> str:
    return stage.GetPrimAtPath(AREA).GetVariantSet(name).GetVariantSelection()


def test_a_switch_writes_names_clears_and_blocks_and_its_snapshots_put_the_session_layer_back(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    select(Sdf.CreatePrimInLayer(session, AREA), "lod", "high")
    before, root = session.ExportToString(), stage.GetRootLayer().ExportToString()

    snapshots = sweep.switch(stage, {AREA: {"state": "open", "lod": None}}, session)
    assert (_area(stage), _area(stage, "lod")) == ("open", "")
    snapshots += sweep.switch(stage, {AREA: {"state": ""}}, session)
    # A block shows no variant, where a clear would give the file's closed back (round 2, P11).
    assert _area(stage) == ""
    assert variants.selections_of(session, AREA) == {"state": ""}

    for snapshot in reversed(snapshots):
        snapshot.restore()
    assert session.ExportToString() == before
    assert stage.GetRootLayer().ExportToString() == root


def test_a_refused_switch_writes_nothing(stage: Usd.Stage):
    session = stage.GetSessionLayer()
    before = session.ExportToString()

    with pytest.raises(ValueError, match="has no variant 'ajar'"):
        sweep.switch(stage, {AREA: {"state": "ajar", "lod": "low"}}, session)
    with pytest.raises(ValueError, match="Prim not found: /World/Nowhere"):
        sweep.switch(stage, {AREA: {"lod": "low"}, "/World/Nowhere": {"state": ""}}, session)

    assert session.ExportToString() == before


def test_refusals_at_the_start_name_a_misspelled_variant_where_its_set_exists(stage: Usd.Stage):
    shots = _shots(
        {"position": [0, 0, 1], "yaw": 0, "selections": {AREA: {"state": "ajar"}}},
        # Brought in by a switch, perhaps: checked at its shot.
        {"position": [0, 0, 1], "yaw": 0, "selections": {"/World/Later": {"state": "x"}, AREA: {"later": "x"}}},
        {"position": [0, 0, 1], "yaw": 0, "selections": {AREA: {"state": "open"}}},
    )

    (why,) = sweep.refusals(stage, shots, stage.GetSessionLayer())

    assert why.startswith(f"{AREA}'s variant set 'state' has no variant 'ajar'")


# ----- the timeline -----


class FakeTimeline:
    """Kit's timeline as the sweep uses it: a state and a time, each change applied at the commit, as Kit applies
    pending changes, and each call logged."""

    def __init__(self, state: str = "stopped", time: float = 0.0) -> None:
        self.state, self.time = state, time
        self.pending: list[tuple[str, float]] = []
        self.calls: list[str] = []

    def is_playing(self) -> bool:
        return self.state == "playing"

    def is_stopped(self) -> bool:
        return self.state == "stopped"

    def get_current_time(self) -> float:
        return self.time

    def set_current_time(self, time_in_seconds: float) -> None:
        self.calls.append(f"time {time_in_seconds:g}")
        self.pending.append(("time", time_in_seconds))

    def play(self) -> None:
        self.calls.append("play")
        self.pending.append(("playing", 0))

    def pause(self) -> None:
        self.calls.append("pause")
        self.pending.append(("paused", 0))

    def stop(self) -> None:
        self.calls.append("stop")
        self.pending.append(("stopped", 0))

    def commit(self) -> None:
        for what, value in self.pending:
            if what == "time":
                self.time = value
            else:
                self.state = what
                self.time = 0.0 if what == "stopped" else self.time
        self.pending = []


@pytest.mark.parametrize(
    ("state", "calls"),
    [("playing", ["pause", "time 3"]), ("paused", ["time 3"]), ("stopped", ["time 3"])],
)
def test_a_timed_shot_pauses_a_playing_timeline_and_leaves_a_stopped_one_stopped(state, calls):
    timeline = FakeTimeline(state, 1.0)

    TimelineStart.seek(timeline, 3.0)

    assert timeline.calls == calls
    assert (timeline.state, timeline.time) == ("paused" if state == "playing" else state, 3.0)


@pytest.mark.parametrize("state", ["playing", "paused", "stopped"])
def test_the_start_s_state_and_time_come_back_after_a_timed_shot(state):
    timeline = FakeTimeline(state, 1.0 if state != "stopped" else 0.0)
    start = TimelineStart.read(timeline)
    TimelineStart.seek(timeline, 3.0)

    start.restore(timeline)

    assert (timeline.state, timeline.time) == (state, start.time)


def test_a_playing_timeline_nothing_paused_plays_on_untouched():
    timeline = FakeTimeline("playing", 1.0)
    start = TimelineStart.read(timeline)
    timeline.time = 4.0  # it played on

    start.restore(timeline)

    assert timeline.calls == []
    assert (timeline.state, timeline.time) == ("playing", 4.0)


def test_a_shot_without_a_time_after_another_commits_nothing():
    timeline = FakeTimeline("paused", 1.0)
    start = TimelineStart.read(timeline)
    commits: list[int] = []
    timeline.commit = lambda: commits.append(1)  # type: ignore[method-assign]

    start.restore(timeline)

    assert (timeline.calls, commits) == ([], [])


def test_a_stopped_timeline_moved_by_hand_gets_its_time_back_without_a_stop():
    timeline = FakeTimeline("stopped", 0.0)
    start = TimelineStart.read(timeline)
    TimelineStart.seek(timeline, 3.0)

    start.restore(timeline)

    assert "stop" not in timeline.calls
    assert (timeline.state, timeline.time) == ("stopped", 0.0)


@pytest.mark.parametrize(("start_state", "now"), [("paused", "playing"), ("stopped", "paused")])
def test_a_timeline_someone_played_or_paused_mid_sweep_gets_its_start_s_state_back(start_state, now):
    timeline = FakeTimeline(start_state, 1.0 if start_state == "paused" else 0.0)
    start = TimelineStart.read(timeline)
    timeline.state, timeline.time = now, 5.0

    start.restore(timeline)

    assert (timeline.state, timeline.time) == (start_state, start.time)


@pytest.mark.parametrize(("status", "loading"), [(("", 0, 0), False), (("Loading", 2, 7), True)])
def test_still_loading_reads_the_files_left_to_load(status, loading):
    assert sweep.still_loading(status) is loading


# ----- names, files and the manifest -----


@pytest.mark.parametrize("name", ["site_a", "20261102-153012", "Site A v2.1"])
def test_a_plain_folder_name_is_kept(name):
    assert sweep.folder_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "..", ".hidden", "a/b", "a\\b", "../site", "C:site", "site.", "site ", "x" * 101, 3, None]
)
def test_a_name_that_isn_t_one_plain_folder_name_is_refused(name):
    with pytest.raises(ValueError, match="name must be one plain folder name"):
        sweep.folder_name(name)


def test_a_file_is_named_by_its_shot_s_number_and_its_name_made_safe():
    assert sweep.file_name(7, Shot()) == "0007.png"
    assert sweep.file_name(7, Shot(name="dock A/open")) == "0007_dock_A_open.png"
    assert sweep.file_name(12, Shot(name="../..")) == "0012.png"


def test_the_manifest_records_each_shot_s_pose_lens_file_and_frame():
    shot = _one(name="a", position=[1, 2, 0.65], yaw=30, **CASE_LENS, selections={AREA: {"state": "open"}}, time=2)
    taken = Taken(1, shot, file="0001_a.png", timeline_time=2.0, frame=48.0, is_black=True, loading_seconds=0.25)
    failed = Taken(2, _one(camera_path="/World/Cam"), error="the camera is gone")

    manifest = sweep.manifest({"name": "site_a", "width": W}, [taken, failed])

    assert manifest["format"] == sweep.FORMAT
    assert (manifest["name"], manifest["width"]) == ("site_a", W)
    assert manifest["shots"] == [
        {
            "index": 1,
            "name": "a",
            "position": [1.0, 2.0, 0.65],
            "yaw": 30.0,
            "pitch": 0.0,
            "focal_length": 7.337,
            "horizontal_aperture": 20.955,
            "vertical_aperture": 11.787,
            "selections": {AREA: {"state": "open"}},
            "time": 2.0,
            "file": "0001_a.png",
            "is_black": True,
            "timeline_time": 2.0,
            "frame": 48.0,
            "loading_seconds": 0.25,
        },
        {
            "index": 2,
            "name": "",
            "camera_path": "/World/Cam",
            "selections": {},
            "time": None,
            "error": "the camera is gone",
        },
    ]


def _taken(count: int, black: tuple[int, ...] = (), failed: tuple[int, ...] = (), late: tuple[int, ...] = ()):
    shot = Shot(position=(0, 0, 1), yaw=0, pitch=0)
    return [
        Taken(
            i,
            shot,
            file=None if i in failed else f"{i:04d}.png",
            error="refused" if i in failed else None,
            is_black=i in black,
            loading="still loading" if i in late else None,
        )
        for i in range(1, count + 1)
    ]


def test_the_summary_names_the_folder_and_the_shots_black_failed_and_still_loading():
    line = sweep.summary("/out/sweeps/site_a", 400, _taken(400, black=(12, 13), failed=(300,), late=(5,)))

    assert line == (
        "400 shots in /out/sweeps/site_a/ (manifest.json); 2 black: shots 12, 13; 1 failed: shot 300; "
        "1 taken still loading: shot 5"
    )


def test_a_sweep_that_stopped_short_says_how_many_of_how_many_and_why():
    line = sweep.summary("C:\\out\\sweeps\\site_a\\", 400, _taken(37), "cancelled: cancel_job was called")
    assert line == "37 of 400 shots in C:\\out\\sweeps\\site_a/ (manifest.json); cancelled: cancel_job was called"


def test_a_long_list_of_shots_is_cut_to_ten():
    line = sweep.summary("/s", 30, _taken(30, black=tuple(range(1, 15))))
    assert "14 black: shots 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 and 4 more" in line


def test_the_result_counts_what_get_job_reports():
    result = sweep.result("/s", "/s/manifest.json", 5, _taken(4, black=(2,), failed=(3,)))

    assert result == {
        "folder": "/s",
        "manifest": "/s/manifest.json",
        "asked": 5,
        "done": 4,
        "taken": 3,
        "black": [2],
        "failed": [3],
        "loading": [],
        "summary": "4 of 5 shots in /s/ (manifest.json); 1 black: shot 2; 1 failed: shot 3",
    }


def test_the_clipping_range_is_isaac_sim_s_in_the_stage_s_units():
    assert sweep.clipping_range(1.0) == (0.01, 1e7)
    assert sweep.clipping_range(0.01) == pytest.approx((1.0, 1e9))
