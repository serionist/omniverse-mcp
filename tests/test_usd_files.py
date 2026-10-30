"""Where a tool loads a USD file it is given from: create_robot's robot files (#40) and open_scene's stages (#79).
Without Kit."""

import pytest

from ovmcp.core.usd_files import is_url, usd_file_url

ROOT = "https://assets.example.invalid/Assets/Isaac/6.2"


def _no_root() -> str | None:
    raise AssertionError("the asset root is looked up only for a library path")


def _whole(path: str) -> str:
    return "<whole>" + path


def test_a_library_path_goes_under_the_asset_root():
    url = usd_file_url("/Isaac/Robots/Franka/franka.usd", lambda: ROOT, lambda _: False, _whole)
    assert url == ROOT + "/Isaac/Robots/Franka/franka.usd"
    assert (
        usd_file_url("/Isaac/Robots/X.usd", lambda: ROOT + "/", lambda _: False, _whole) == ROOT + "/Isaac/Robots/X.usd"
    )


def test_a_library_path_without_an_asset_root_stays_as_it_is():
    assert usd_file_url("/Isaac/Robots/X.usd", lambda: None, lambda _: False, _whole) == "/Isaac/Robots/X.usd"


@pytest.mark.parametrize(
    "path",
    [
        "omniverse://server/Projects/Robots/MyBot.usd",
        "https://example.invalid/Robots/MyBot.usdc",
        "file:///C:/MyBot.usd",
    ],
)
def test_a_url_loads_as_given_with_its_case(path: str):
    assert usd_file_url(path, _no_root, lambda _: False, _whole) == path


@pytest.mark.parametrize("path", ["/home/me/Robots/MyBot.usd", r"C:\Robots\MyBot.usda", "Robots/MyBot.usd"])
def test_a_file_on_the_kit_machine_loads_whole_with_its_case(path: str):
    # Whole: a reference reads a relative path against the stage's folder, not Kit's working folder.
    assert usd_file_url(path, _no_root, lambda p: p == path, _whole) == "<whole>" + path


def test_a_file_in_the_library_s_folder_shape_that_exists_here_is_not_moved_under_the_root():
    assert usd_file_url("/Isaac/Mine/Bot.usd", _no_root, lambda _: True, _whole) == "<whole>/Isaac/Mine/Bot.usd"


@pytest.mark.parametrize("path", ["/home/me/Robots/Missing.usd", r"C:\Robots\Missing.usd", "missing.usd"])
def test_a_path_that_is_nowhere_has_no_url(path: str):
    assert usd_file_url(path, _no_root, lambda _: False, _whole) is None


@pytest.mark.parametrize(
    ("path", "url"),
    [
        ("omniverse://server/Scenes/Room.usd", True),
        ("https://example.invalid/Room.usda", True),
        ("file:///C:/Scenes/Room.usd", True),
        # Kit's own spelling of a file URL has no //, so it reads as a path (#79's E9).
        ("file:/C:/Scenes/Room.usd", False),
        (r"C:\Scenes\Room.usd", False),
        ("/Isaac/Environments/Simple_Room/simple_room.usd", False),
        ("Scenes/Room.usd", False),
    ],
)
def test_a_url_is_told_from_a_path(path: str, url: bool):
    assert is_url(path) is url
