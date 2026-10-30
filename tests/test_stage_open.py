"""open_scene's sequence against a fake Kit (#79): what it refuses while the open stage is still there, the order it
stops, waits and opens in, what a failed open says, and the answer read from a real usd-core stage."""

import asyncio
import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdUtils

from omniverse_mcp.client import BridgeClient
from ovmcp.core import stage_open
from ovmcp.core.stage_open import CLOSED, CLOSING, OPENED, OPENING, UNSAVED, path_of

ROOT = "https://assets.example.invalid/Assets/Isaac/6.2"
LIBRARY_ROOM = "/Isaac/Environments/Simple_Room/simple_room.usd"
REMOTE = "https://example.invalid/Scenes/Room.usd"
LFS_POINTER = "version https://git-lfs.github.com/spec/v1\noid sha256:0123\nsize 4107\n"


class FakeKit:
    """Kit as open_scene sees it, in the folder `folder` (Kit's working folder), recording each call in order."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.calls: list[str] = []
        self.state_now = OPENED
        self.current: Usd.Stage | None = Usd.Stage.CreateInMemory()
        self.root: str | None = ROOT
        self.root_error: Exception | None = None
        self.root_hangs = False
        self.stat_result = "OK"
        self.stat_hangs = False
        self.during_stat_state: str | None = None
        self.running = False
        self.open_answer = (True, "")
        self.open_hangs = False
        self.after_open: tuple[str, Usd.Stage | None] | None = None
        self.is_writable = True
        self.note: str | None = None
        # The clock open_stage is handed, which the asset-root lookup moves on by root_takes.
        self.now = 0.0
        self.root_takes = 0.0

    def state(self) -> str:
        self.calls.append("state")
        return self.state_now

    def stage(self) -> Usd.Stage | None:
        return self.current

    def whole(self, path: str) -> str:
        return path if Path(path).is_absolute() else str(self.folder / path)

    def is_file(self, path: str) -> bool:
        return Path(self.whole(path)).is_file()

    async def assets_root(self) -> str | None:
        self.calls.append("assets_root")
        self.now += self.root_takes
        if self.root_hangs:
            await asyncio.sleep(10)
        if self.root_error is not None:
            raise self.root_error
        return self.root

    async def stat(self, url: str) -> str:
        self.calls.append(f"stat {url}")
        if self.during_stat_state is not None:
            self.state_now = self.during_stat_state
        if self.stat_hangs:
            await asyncio.sleep(10)
        return self.stat_result

    def stop_timeline(self) -> bool:
        self.calls.append("stop")
        was, self.running = self.running, False
        return was

    async def next_update(self) -> None:
        self.calls.append("update")
        await asyncio.sleep(0)

    def start_open(self, url: str) -> "asyncio.Future[tuple[bool, str]]":
        self.calls.append(f"open {url}")
        future: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()
        if self.open_hangs:
            return future
        if self.after_open is not None:
            self.state_now, self.current = self.after_open
        else:
            self.state_now = OPENED
            self.current = Usd.Stage.Open(url) if Path(url).is_file() else Usd.Stage.CreateInMemory()
        future.set_result(self.open_answer)
        return future

    def writable(self) -> bool:
        return self.is_writable

    def recording_note(self) -> str | None:
        return self.note

    @property
    def opened(self) -> list[str]:
        return [c.removeprefix("open ") for c in self.calls if c.startswith("open ")]


@pytest.fixture
def kit(tmp_path: Path) -> FakeKit:
    return FakeKit(tmp_path)


@pytest.fixture
def short(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stage_open, "STAT_SECONDS", 0.05)
    monkeypatch.setattr(stage_open, "OPEN_SECONDS", 0.05)


def _scene(path: Path, *, up: str | None = "Z", units: float | None = 1.0, default: bool = True) -> str:
    stage = Usd.Stage.CreateNew(str(path))
    if up is not None:
        UsdGeom.SetStageUpAxis(stage, up)
    if units is not None:
        UsdGeom.SetStageMetersPerUnit(stage, units)
    world = UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    if default:
        stage.SetDefaultPrim(world.GetPrim())
    stage.GetRootLayer().Save()
    return str(path)


def _open(kit: FakeKit, file_path: object) -> dict[str, Any]:
    return asyncio.run(stage_open.open_stage(file_path, kit))


def _error(kit: FakeKit, file_path: object) -> str:
    r = _open(kit, file_path)
    assert r["status"] == "error", r
    return r["error"]


def _nothing_changed(kit: FakeKit) -> None:
    assert "stop" not in kit.calls
    assert kit.opened == []


# ----- Refusals, before anything stops or closes -----


@pytest.mark.parametrize("file_path", ["", "   ", None, 3])
def test_no_file_path_is_refused(kit, file_path):
    assert "No file_path" in _error(kit, file_path)
    _nothing_changed(kit)


def test_a_missing_file_is_refused_by_its_whole_path(kit, tmp_path):
    error = _error(kit, "Scenes/missing.usda")
    assert str(tmp_path / "Scenes" / "missing.usda") in error
    assert "the folder Kit was started in" in error
    _nothing_changed(kit)
    assert not [c for c in kit.calls if c.startswith("stat")]


def test_a_type_usd_does_not_open_is_refused(kit, tmp_path):
    (tmp_path / "notes.txt").write_text("plain text\n", encoding="utf-8")
    assert "USD can't open" in _error(kit, "notes.txt")
    _nothing_changed(kit)


@pytest.mark.parametrize("state", [OPENING, CLOSING])
def test_a_call_while_kit_opens_or_closes_a_stage_is_refused(kit, state):
    kit.state_now = state
    assert "opening or closing a stage now" in _error(kit, REMOTE)
    _nothing_changed(kit)


def test_a_url_with_no_file_is_refused(kit):
    kit.stat_result = "ERROR_NOT_FOUND"
    error = _error(kit, REMOTE)
    assert f"No file at {REMOTE}" in error
    assert "the open stage stays" in error
    _nothing_changed(kit)


def test_a_url_kit_cant_reach_is_refused_by_its_result(kit):
    kit.stat_result = "ERROR_CONNECTION"
    assert f"Kit can't reach {REMOTE} (ERROR_CONNECTION)" in _error(kit, REMOTE)
    _nothing_changed(kit)


def test_a_stat_kit_doesnt_support_is_refused_outside_the_asset_library(kit):
    kit.stat_result = "ERROR_NOT_SUPPORTED"
    assert "(ERROR_NOT_SUPPORTED)" in _error(kit, REMOTE)
    _nothing_changed(kit)


def test_a_stat_kit_doesnt_support_goes_on_under_the_asset_library_s_root(kit):
    # Isaac Sim's own check takes ERROR_NOT_SUPPORTED as found for its library (accept_unsupported).
    kit.stat_result = "ERROR_NOT_SUPPORTED"
    r = _open(kit, LIBRARY_ROOM)
    assert r["status"] == "success", r
    assert kit.opened == [ROOT + LIBRARY_ROOM]


def test_the_asset_root_and_the_stat_share_one_budget(kit):
    # The lookup takes all but 0.05 s of STAT_SECONDS on open_stage's clock: the stat gets what is left, not 20 s more.
    kit.root_takes = stage_open.STAT_SECONDS - 0.05
    kit.stat_hangs = True
    started = time.monotonic()
    r = asyncio.run(stage_open.open_stage(LIBRARY_ROOM, kit, clock=lambda: kit.now))
    assert time.monotonic() - started < 2.0
    assert r["status"] == "error"
    assert f"Kit got no answer about {ROOT + LIBRARY_ROOM}" in r["error"]
    _nothing_changed(kit)


def test_a_stat_that_doesnt_answer_in_time_is_refused(kit, short):
    kit.stat_hangs = True
    assert f"Kit got no answer about {REMOTE}" in _error(kit, REMOTE)
    _nothing_changed(kit)


def test_a_library_path_is_refused_when_isaac_sim_cant_find_its_library(kit):
    kit.root_error = RuntimeError(f"Could not find assets root folder: {ROOT}")
    error = _error(kit, LIBRARY_ROOM)
    assert "Isaac Sim's asset library can't be found" in error
    assert ROOT in error
    _nothing_changed(kit)


def test_a_library_path_is_refused_when_the_library_doesnt_answer_in_time(kit, short):
    kit.root_hangs = True
    assert "asset library didn't answer" in _error(kit, LIBRARY_ROOM)
    _nothing_changed(kit)


def test_a_library_path_is_refused_in_a_kit_app_without_the_library(kit):
    kit.root = None
    assert "no Isaac Sim asset library" in _error(kit, LIBRARY_ROOM)
    _nothing_changed(kit)


@pytest.mark.parametrize("name", ["scene.usd", "scene.usda", "scene.usdc", "scene.usdz"])
def test_a_git_lfs_pointer_under_a_usd_name_is_refused(kit, tmp_path, name):
    (tmp_path / name).write_text(LFS_POINTER, encoding="utf-8")
    assert "Git LFS pointer" in _error(kit, name)
    _nothing_changed(kit)


def test_the_state_is_read_again_after_the_stat(kit):
    # Another open started meanwhile (#79's E14): this one is refused, and never started.
    kit.during_stat_state = CLOSING
    assert "opening or closing a stage now" in _error(kit, REMOTE)
    assert kit.opened == []


# ----- The sequence -----


def test_it_stops_the_timeline_waits_an_update_and_reads_the_state_straight_before_the_open(kit):
    kit.running = True
    r = _open(kit, REMOTE)
    assert r["status"] == "success", r
    assert r["result"]["stopped"] is True
    tail = kit.calls[kit.calls.index("stop") :]
    assert tail[:4] == ["stop", "update", "state", f"open {REMOTE}"]


def test_a_stopped_timeline_isnt_reported_as_stopped_by_the_call(kit):
    r = _open(kit, REMOTE)
    assert r["result"]["stopped"] is False


@pytest.mark.parametrize(
    ("given", "handed"),
    [
        ("file:///C:/Scenes/Room.usd", "file:///C:/Scenes/Room.usd"),
        (REMOTE, REMOTE),
        (LIBRARY_ROOM, ROOT + LIBRARY_ROOM),
    ],
)
def test_the_path_the_rule_makes_is_opened_and_answered(kit, given, handed):
    r = _open(kit, given)
    assert r["status"] == "success", r
    assert kit.opened == [handed]
    # What the answer gives is a path open_scene takes back, whatever Kit's identifier for it (#79's E9).
    assert r["result"]["file_path"] == handed


def test_a_relative_file_is_opened_by_its_whole_path(kit, tmp_path):
    (tmp_path / "Scenes").mkdir()
    whole = _scene(tmp_path / "Scenes" / "room.usda")
    r = _open(kit, "Scenes/room.usda")
    assert r["status"] == "success", r
    assert kit.opened == [whole]
    assert r["result"]["file_path"] == whole


# ----- A failed open says what is open now -----


def test_kit_busy_says_another_open_is_under_way_and_claims_no_close(kit):
    kit.open_answer = (False, "UsdContext busy")
    kit.after_open = (CLOSING, None)
    error = _error(kit, REMOTE)
    assert "UsdContext busy" in error
    assert "Another open is under way, so this file wasn't opened" in error
    assert "closed" not in error


def test_a_failed_open_names_the_stage_kit_closed_first(kit, tmp_path):
    before = Usd.Stage.Open(_scene(tmp_path / "before.usda"))
    kit.current = before
    kit.open_answer = (False, f"Failed to open: {REMOTE}")
    kit.after_open = (CLOSED, None)
    error = _error(kit, REMOTE)
    assert f"Kit closed {before.GetRootLayer().identifier} before the file failed to load" in error
    assert "open_scene another file, or new_scene" in error


def test_a_failed_open_of_an_unsaved_stage_says_so(kit):
    kit.open_answer = (False, "Failed to open")
    kit.after_open = (CLOSED, None)
    assert f"Kit closed {UNSAVED} before" in _error(kit, REMOTE)


def test_a_failed_open_with_no_stage_before_claims_no_close(kit):
    kit.state_now, kit.current = CLOSED, None
    kit.open_answer = (False, "Failed to open")
    kit.after_open = (CLOSED, None)
    error = _error(kit, REMOTE)
    assert "No stage is open: open_scene another file, or new_scene" in error
    assert "closed" not in error


def test_a_failed_open_names_the_stage_open_after_it(kit, tmp_path):
    other = Usd.Stage.Open(_scene(tmp_path / "other.usda"))
    kit.open_answer = (False, "UsdContext busy")
    kit.after_open = (OPENED, other)
    assert f"The stage open now is {other.GetRootLayer().identifier}" in _error(kit, REMOTE)


def test_an_open_whose_stage_is_gone_by_the_answer_says_so(kit):
    # Another call closed it during the two updates after the open.
    kit.after_open = (OPENED, None)
    assert "no stage is open now" in _error(kit, REMOTE)


def test_an_open_past_its_time_says_kit_goes_on(kit, short):
    kit.open_hangs = True
    error = _error(kit, REMOTE)
    assert "goes on in the background" in error
    assert "get_sim_state answers once it has opened" in error


# ----- The answer -----


def test_the_answer_names_the_stage_it_replaced(kit, tmp_path):
    before = Usd.Stage.Open(_scene(tmp_path / "before.usda"))
    kit.current = before
    r = _open(kit, REMOTE)
    assert r["result"]["replaced"] == before.GetRootLayer().identifier


def test_an_anonymous_stage_is_replaced_as_an_unsaved_one(kit):
    assert _open(kit, REMOTE)["result"]["replaced"] == UNSAVED


def test_nothing_is_replaced_when_no_stage_was_open(kit):
    kit.state_now, kit.current = CLOSED, None
    assert _open(kit, REMOTE)["result"]["replaced"] is None


def test_a_stage_opened_from_a_file_url_is_named_by_its_path(kit):
    # Kit names it file:/C:/..., which open_scene refuses (#79's E9): the answer gives the path it takes back.
    kit.current = cast(Any, SimpleNamespace(GetRootLayer=lambda: SimpleNamespace(identifier="file:/C:/Scenes/a.usda")))
    assert _open(kit, REMOTE)["result"]["replaced"] == "C:/Scenes/a.usda"


@pytest.mark.parametrize(
    ("identifier", "path"),
    [
        ("file:/C:/Scenes/Room.usda", "C:/Scenes/Room.usda"),
        ("file:///C:/Scenes/Room.usda", "C:/Scenes/Room.usda"),
        ("file://localhost/C:/Scenes/Room.usda", "C:/Scenes/Room.usda"),
        ("file:/home/me/Room.usda", "/home/me/Room.usda"),
        ("file:/C:/My%20Scenes/Room.usda", "C:/My Scenes/Room.usda"),
        ("file://server/share/Room.usda", "//server/share/Room.usda"),
        ("C:/Scenes/Room.usda", "C:/Scenes/Room.usda"),
        (REMOTE, REMOTE),
    ],
)
def test_a_file_url_is_named_by_its_path_and_anything_else_as_it_is(identifier, path):
    assert path_of(identifier) == path


def test_a_file_s_axis_units_and_default_prim_are_answered(kit, tmp_path):
    r = _open(kit, _scene(tmp_path / "room.usda"))
    result = r["result"]
    assert result["up_axis"] == "Z"
    assert result["up_axis_authored"] is True
    assert result["meters_per_unit"] == 1.0
    assert result["meters_per_unit_authored"] is True
    assert result["default_prim"] == "/World"
    assert result["prim_count"] == 2
    assert result["package"] is False


def test_a_file_that_sets_no_axis_or_units_is_answered_with_usd_s_fallbacks(kit, tmp_path):
    result = _open(kit, _scene(tmp_path / "bare.usda", up=None, units=None, default=False))["result"]
    assert (result["up_axis"], result["up_axis_authored"]) == ("Y", False)
    assert (result["meters_per_unit"], result["meters_per_unit_authored"]) == (0.01, False)
    assert result["default_prim"] is None


def test_a_usdz_is_answered_as_a_package(kit, tmp_path):
    usdz = tmp_path / "room.usdz"
    assert UsdUtils.CreateNewUsdzPackage(Sdf.AssetPath(_scene(tmp_path / "room.usda")), str(usdz))
    result = _open(kit, str(usdz))["result"]
    assert result["package"] is True


def test_kit_s_own_values_pass_through(kit):
    kit.is_writable = False
    kit.note = "frames stopped after 28, at 0.00 s of simulation: the stage began to close"
    result = _open(kit, REMOTE)["result"]
    assert result["writable"] is False
    assert result["recording_note"] == kit.note


def test_the_open_and_its_checks_end_before_the_server_gives_up():
    # The bridge sends nothing until the handler returns; 20 s are left for the updates, the prim count and the reply.
    client_timeout = inspect.signature(BridgeClient.__init__).parameters["timeout"].default
    assert client_timeout >= stage_open.STAT_SECONDS + stage_open.OPEN_SECONDS + 20
