"""The robot handlers against a fake Kit, on a usd-core stage, loaded as tests/test_scene_handler.py loads the scene
handlers. create_robot's (#82): the robot is placed through the Kit-free transform writer, and a refusal leaves nothing
behind for the retry to trip on. /robot/joint_states' without Isaac Sim (#77): an error that names no tool."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import golden
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

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


def test_joint_states_without_isaac_sim_say_so_and_name_no_tool(robot, kit, monkeypatch):
    # get_robot_info gives this error as its joint states' line; it named get_joint_states, a tool that is gone (#77).
    # The module made unimportable, as in a Kit app without Isaac Sim, wherever this runs.
    monkeypatch.setitem(sys.modules, "isaacsim.core.experimental.prims", None)
    bot = UsdGeom.Xform.Define(kit.stage, "/World/Bot").GetPrim()
    UsdPhysics.ArticulationRootAPI.Apply(bot)

    r = asyncio.run(robot.handle_get_joint_states({"prim_path": "/World/Bot"}))

    assert r["status"] == "error"
    assert r["error"].startswith("Joint states need Isaac Sim's isaacsim.core.experimental.prims extension: ")
    tools = {*json.loads(golden.GOLDEN.read_text(encoding="utf-8"))["tools"], "get_joint_states"}
    assert sorted(name for name in tools if name in r["error"]) == []
