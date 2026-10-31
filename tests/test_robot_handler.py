"""create_robot's handler against a fake Kit, on a usd-core stage (#82): the robot is placed through the Kit-free
transform writer, and a refusal leaves nothing behind for the retry to trip on. Loaded as tests/test_scene_handler.py
loads the scene handlers."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom

from .test_scene_handler import FakeKit, load_handler


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def robot(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler("robot", kit, monkeypatch)


def _bot_file(folder: Path, animated: bool = False) -> str:
    """A robot's USD file: a root Xform with its own [translate, orient] ops, the translate animated if asked."""
    layer = Sdf.Layer.CreateNew(str(folder / "bot.usda"))
    held = Usd.Stage.Open(layer)
    root = UsdGeom.Xform.Define(held, "/Bot")
    translate = root.AddTranslateOp()
    if animated:
        translate.Set(Gf.Vec3d(0, 0, 1), 1.0)
    else:
        translate.Set(Gf.Vec3d(0, 0, 0))
    root.AddOrientOp().Set(Gf.Quatf(1, 0, 0, 0))
    UsdGeom.Cube.Define(held, "/Bot/Body")
    held.SetDefaultPrim(root.GetPrim())
    layer.Save()
    return layer.realPath


def _create(robot: Any, **body: Any) -> dict[str, Any]:
    return asyncio.run(robot.handle_create_robot(body))


def test_a_robot_from_a_file_is_placed_through_its_own_ops(robot, kit, tmp_path):
    r = _create(robot, robot_type=_bot_file(tmp_path), prim_path="/World/Bot", position=[1, 2, 3], rotation=[0, 0, 90])

    assert r["status"] == "success", r
    prim = kit.stage.GetPrimAtPath("/World/Bot")
    assert [op.GetOpName() for op in UsdGeom.Xformable(prim).GetOrderedXformOps()] == [
        "xformOp:translate",
        "xformOp:orient",
    ]
    assert prim.GetAttribute("xformOp:translate").Get() == Gf.Vec3d(1, 2, 3)


def test_a_malformed_rotation_makes_no_robot(robot, kit, tmp_path):
    # 0.2.3 made the robot, then failed, and the retry was refused as taken.
    r = _create(robot, robot_type=_bot_file(tmp_path), prim_path="/World/Bot", rotation=[0, 90])

    assert r["status"] == "error"
    assert "rotation must be" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Bot").IsValid()


def test_a_refusal_found_once_the_robot_is_there_takes_it_away(robot, kit, tmp_path):
    r = _create(robot, robot_type=_bot_file(tmp_path, animated=True), prim_path="/World/Robots/Bot", position=[1, 2, 3])

    assert r["status"] == "error"
    assert "The robot was not added" in r["error"]
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()
