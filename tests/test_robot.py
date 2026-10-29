"""Where create_robot loads a robot's USD file from, and the prim it names for it (#40); where get_joint_states finds
a robot's articulation (#50). Without Kit."""

import pytest
from pxr import Usd, UsdGeom, UsdPhysics

from ovmcp.core.robot import articulation_root, is_usd_file, robot_prim_path, robot_usd_url

ROOT = "https://assets.example.invalid/Assets/Isaac/6.2"


def _no_root() -> str | None:
    raise AssertionError("the asset root is looked up only for a library path")


def _whole(path: str) -> str:
    return "<whole>" + path


def test_a_library_path_goes_under_the_asset_root():
    url = robot_usd_url("/Isaac/Robots/Franka/franka.usd", lambda: ROOT, lambda _: False, _whole)
    assert url == ROOT + "/Isaac/Robots/Franka/franka.usd"
    assert (
        robot_usd_url("/Isaac/Robots/X.usd", lambda: ROOT + "/", lambda _: False, _whole)
        == ROOT + "/Isaac/Robots/X.usd"
    )


def test_a_library_path_without_an_asset_root_stays_as_it_is():
    assert robot_usd_url("/Isaac/Robots/X.usd", lambda: None, lambda _: False, _whole) == "/Isaac/Robots/X.usd"


@pytest.mark.parametrize(
    "path",
    [
        "omniverse://server/Projects/Robots/MyBot.usd",
        "https://example.invalid/Robots/MyBot.usdc",
        "file:///C:/MyBot.usd",
    ],
)
def test_a_url_loads_as_given_with_its_case(path: str):
    assert robot_usd_url(path, _no_root, lambda _: False, _whole) == path


@pytest.mark.parametrize("path", ["/home/me/Robots/MyBot.usd", r"C:\Robots\MyBot.usda", "Robots/MyBot.usd"])
def test_a_file_on_the_kit_machine_loads_whole_with_its_case(path: str):
    # Whole: a reference reads a relative path against the stage's folder, not Kit's working folder.
    assert robot_usd_url(path, _no_root, lambda p: p == path, _whole) == "<whole>" + path


def test_a_file_in_the_library_s_folder_shape_that_exists_here_is_not_moved_under_the_root():
    assert robot_usd_url("/Isaac/Mine/Bot.usd", _no_root, lambda _: True, _whole) == "<whole>/Isaac/Mine/Bot.usd"


@pytest.mark.parametrize("path", ["/home/me/Robots/Missing.usd", r"C:\Robots\Missing.usd", "missing.usd"])
def test_a_path_that_is_nowhere_has_no_url(path: str):
    assert robot_usd_url(path, _no_root, lambda _: False, _whole) is None


@pytest.mark.parametrize(
    ("robot_type", "prim"),
    [
        ("franka", "/World/Franka"),
        ("g1", "/World/G1"),
        ("/home/me/Robots/MyBot.usd", "/World/MyBot"),
        (r"C:\Robots\My Bot-2.usda", "/World/My_Bot_2"),
        ("omniverse://server/Robots/2Arm.USD", "/World/_Arm"),
    ],
)
def test_a_robot_s_prim_is_named_after_it(robot_type: str, prim: str):
    assert robot_prim_path(robot_type) == prim


def test_a_usd_file_is_told_from_a_robot_s_name():
    assert is_usd_file("/home/me/Bot.USDA")
    assert is_usd_file("scene.usdz")
    assert not is_usd_file("franka")


# ----- The articulation root -----


@pytest.fixture
def robots() -> Usd.Stage:
    """/World/Arm has its root on itself; /World/Biped on /World/Biped/pelvis, after a link without one; /World/Copy is
    an instance of /Prototypes/Biped, whose root is only an instance proxy on the stage; /World/Table has none."""
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Arm").GetPrim())
    for biped in ("/World/Biped", "/Prototypes/Biped"):
        UsdGeom.Xform.Define(stage, biped)
        UsdGeom.Xform.Define(stage, f"{biped}/base")
        UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, f"{biped}/pelvis").GetPrim())
        UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, f"{biped}/pelvis/hand").GetPrim())
    copy = UsdGeom.Xform.Define(stage, "/World/Copy").GetPrim()
    copy.GetReferences().AddInternalReference("/Prototypes/Biped")
    copy.SetInstanceable(True)
    assert stage.GetPrimAtPath("/World/Copy/pelvis").IsInstanceProxy()
    UsdGeom.Cube.Define(stage, "/World/Table")
    return stage


@pytest.mark.parametrize(
    ("prim", "root"),
    [
        ("/World/Arm", "/World/Arm"),
        ("/World/Biped", "/World/Biped/pelvis"),
        ("/World/Biped/pelvis/hand", "/World/Biped/pelvis/hand"),
        ("/World/Copy", "/World/Copy/pelvis"),
        ("/World/Table", None),
    ],
)
def test_the_articulation_root_at_or_under_a_prim(robots: Usd.Stage, prim: str, root: str | None):
    assert articulation_root(robots.GetPrimAtPath(prim)) == root
