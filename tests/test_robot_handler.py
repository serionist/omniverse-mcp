"""The robot handlers against a fake Kit, on a usd-core stage, loaded as tests/test_scene_handler.py loads the scene
handlers. create_robot's (#82): the robot is placed through the Kit-free transform writer, and a refusal leaves nothing
behind for the retry to trip on; a file of another up axis stands on the stage (#105). /robot/joint_states' without
Isaac Sim (#77): an error that names no tool."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import golden
import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.usd import floats

from .test_scene_handler import FakeKit, load_handler


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def robot(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    return load_handler("robot", kit, monkeypatch)


def _bot_file(folder: Path, animated: bool = False, up_axis: str | None = None, units_op: float | None = None) -> str:
    """A robot's USD file: a root Xform with its own [translate, orient] ops, the translate animated if asked, and a
    body 2 tall along the file's up axis, under an upAxis it authors if asked; its root ends with Kit's turn if asked,
    as a file Kit resolved and saved has."""
    layer = Sdf.Layer.CreateNew(str(folder / "bot.usda"))
    held = Usd.Stage.Open(layer)
    if up_axis is not None:
        UsdGeom.SetStageUpAxis(held, up_axis)
    root = UsdGeom.Xform.Define(held, "/Bot")
    translate = root.AddTranslateOp()
    if animated:
        translate.Set(Gf.Vec3d(0, 0, 1), 1.0)
    else:
        translate.Set(Gf.Vec3d(0, 0, 0))
    root.AddOrientOp().Set(Gf.Quatf(1, 0, 0, 0))
    if units_op is not None:
        root.AddRotateXOp(opSuffix="unitsResolve").Set(units_op)
    body = UsdGeom.Cube.Define(held, "/Bot/Body")
    tall = (1.0, 1.0, 2.0) if up_axis == "Z" else (1.0, 2.0, 1.0)
    body.AddScaleOp().Set(Gf.Vec3f(*(0.5 * v for v in tall)))
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


# ---- a file of another up axis stands on the stage (#105) ----


def _size(kit: FakeKit, path: str) -> list[float]:
    box = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(kit.stage.GetPrimAtPath(path))
    return [round(v, 6) for v in floats(box.ComputeAlignedRange().GetSize())]


def _ops(kit: FakeKit, path: str) -> list[str]:
    return [op.GetOpName() for op in UsdGeom.Xformable(kit.stage.GetPrimAtPath(path)).GetOrderedXformOps()]


def test_a_z_up_file_stands_on_a_y_up_stage(robot, kit, tmp_path):
    # The G1 on scenario 10.1's Y-up stage lay on its side: tallest along Z (#105).
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis="Z"), prim_path="/World/Bot", position=[3, 0.74, 0])

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", "xformOp:rotateX:unitsResolve"]
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:rotateX:unitsResolve").Get() == -90.0
    assert _size(kit, "/World/Bot") == [1.0, 2.0, 1.0]
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:translate").Get() == Gf.Vec3d(3, 0.74, 0)
    assert r["result"]["up_axis_turn"] == {
        "file": "Z",
        "stage": "Y",
        "degrees": -90.0,
        "op": -90.0,
        "op_name": "xformOp:rotateX:unitsResolve",
    }


def test_a_rotation_turns_the_standing_robot_about_the_stage_s_axis(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    bot = _bot_file(tmp_path, up_axis="Z")

    r = _create(robot, robot_type=bot, prim_path="/World/Bot", rotation=[0, 90, 0])

    assert r["status"] == "success", r
    # Turned about Y, the stage's up, it still stands: the turn upright is inside the rotation.
    assert _size(kit, "/World/Bot") == [1.0, 2.0, 1.0]


def test_a_y_up_file_stands_on_a_z_up_stage(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.z)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis="Y"), prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"]["degrees"] == 90.0
    assert _size(kit, "/World/Bot") == [1.0, 1.0, 2.0]


@pytest.mark.parametrize(("file_axis", "stage_axis"), [("Z", "Z"), ("Y", "Y"), (None, "Z")], ids=["Z", "Y", "unsaid"])
def test_a_file_of_the_stage_s_axis_or_none_is_left_as_it_is(robot, kit, tmp_path, file_axis, stage_axis):
    UsdGeom.SetStageUpAxis(kit.stage, stage_axis)

    r = _create(robot, robot_type=_bot_file(tmp_path, up_axis=file_axis), prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"] is None
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient"]


def test_a_file_kit_resolved_and_saved_gets_the_turn_it_still_owes(robot, kit, tmp_path):
    # A Z-up robot Kit dropped on a Y-up stage (-90) and saved as a Y-up file, given to a Z-up stage (+90).
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.z)
    bot = _bot_file(tmp_path, up_axis="Y", units_op=-90.0)

    r = _create(robot, robot_type=bot, prim_path="/World/Bot")

    assert r["result"]["up_axis_turn"]["degrees"] == 90.0
    assert r["result"]["up_axis_turn"]["op"] == 0.0
    assert _ops(kit, "/World/Bot") == ["xformOp:translate", "xformOp:orient", "xformOp:rotateX:unitsResolve"]
    # What the answer says is what the op holds (review F5).
    assert kit.stage.GetPrimAtPath("/World/Bot").GetAttribute("xformOp:rotateX:unitsResolve").Get() == 0.0


def test_a_refusal_after_the_turn_leaves_no_robot(robot, kit, tmp_path):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    bot = _bot_file(tmp_path, animated=True, up_axis="Z")

    r = _create(robot, robot_type=bot, prim_path="/World/Robots/Bot", position=[1, 2, 3])

    assert r["status"] == "error"
    assert not kit.stage.GetPrimAtPath("/World/Robots").IsValid()


def test_a_later_set_transform_keeps_the_turn_where_it_is(robot, kit, tmp_path, monkeypatch):
    UsdGeom.SetStageUpAxis(kit.stage, UsdGeom.Tokens.y)
    _create(robot, robot_type=_bot_file(tmp_path, up_axis="Z"), prim_path="/World/Bot")
    scene = load_handler("scene", kit, monkeypatch)

    r = asyncio.run(scene.handle_transform({"prim_path": "/World/Bot", "position": [0, 1, 0], "rotation": [0, 45, 0]}))

    assert r["status"] == "success", r
    assert _ops(kit, "/World/Bot")[-1] == "xformOp:rotateX:unitsResolve"
    assert _size(kit, "/World/Bot")[1] == 2.0
