"""apply_force's handler against a fake Kit (#68): today's call through IPhysxSimulation, which PhysX takes everywhere
but under the Direct GPU API, and the push through PhysX's tensor API there.

handlers/simulation.py is loaded from its file with Kit's modules, omni.physx, omni.physics.tensors and warp faked in
sys.modules, as tests/test_recording_handler.py loads its handler. The stage is a real usd-core one, and the Kit-free
core is the real one.
"""

import asyncio
import importlib.util
import math
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import numpy as np
import pxr
import pytest
from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from .conftest import EXTENSION_ROOT

HANDLER = EXTENSION_ROOT / "ovmcp" / "bridge" / "handlers" / "simulation.py"
SUPPRESS = "/physics/suppressReadback"
HALF = math.sqrt(0.5)
BOX = "/World/Box"


class Float3(tuple):
    def __new__(cls, x: float, y: float, z: float) -> "Float3":
        return super().__new__(cls, (x, y, z))


class FakeArray:
    """A warp array as the handler makes one: what it was made from, and where."""

    def __init__(self, data: Any, dtype: str, device: str) -> None:
        self.data = np.asarray(data)
        self.dtype = dtype
        self.device = device


class FakeRows:
    """What a view's get_* gives: an array with .numpy()."""

    def __init__(self, rows: list[list[float]]) -> None:
        self._rows = rows

    def numpy(self) -> np.ndarray:
        return np.array(self._rows, np.float32)


class FakeBodyView:
    def __init__(self, kit: "FakeKit", pattern: str) -> None:
        self.kit = kit
        matched = [pattern] if pattern in kit.tensor_bodies else []
        self.count = kit.view_count if kit.view_count is not None else len(matched)
        self.prim_paths = kit.view_paths if kit.view_paths is not None else matched

    def get_transforms(self) -> FakeRows:
        return FakeRows(self.kit.transform7)

    def get_coms(self) -> FakeRows:
        return FakeRows(self.kit.com7)

    def apply_forces_and_torques_at_position(self, forces, torques, points, indices, is_global) -> bool:
        if self.kit.push_raises:
            raise Exception("Failed to apply forces and torques at pos in backend")
        self.kit.tensor_pushes.append((forces, torques, points, indices, is_global))
        return True


class FakeSimView:
    device = "cuda:0"

    def __init__(self, kit: "FakeKit") -> None:
        self.kit = kit
        self.invalidated = 0

    def create_rigid_body_view(self, pattern: str) -> FakeBodyView:
        if self.kit.body_view_raises:
            raise Exception("no rigid bodies match")
        return FakeBodyView(self.kit, pattern)

    def invalidate(self) -> None:
        self.invalidated += 1
        if self.kit.invalidate_raises:
            raise Exception("already invalid")


class FakeKit:
    """Kit and PhysX as the handler sees them: the stage and the timeline, the setting, both ways to push, and what the
    handler logged."""

    def __init__(self) -> None:
        self.stage = Usd.Stage.CreateInMemory()
        scene = UsdPhysics.Scene.Define(self.stage, "/World/PhysicsScene").GetPrim()
        self.scene = scene
        scene.CreateAttribute("physxScene:enableGPUDynamics", Sdf.ValueTypeNames.Bool).Set(True)
        self.add_body(BOX)
        self.stopped = False
        self.suppress = True
        self.stage_id = 7
        # The CPU path's PhysX: the pose it holds, its mass information and the pushes made.
        self.held = True
        self.pose = {"ret_val": True, "position": (1.0, 2.0, 3.0), "rotation": (0.0, 0.0, 0.0, 1.0)}
        self.mass_information = {"mass": 5.0, "com": (0.0, 0.0, 0.25)}
        self.physx_pushes: list[tuple[Any, ...]] = []
        self.physx_push_raises = False
        # The tensor path's PhysX: the bodies it holds, the rows it reports, and the views and pushes made.
        self.tensor_bodies = [BOX]
        self.view_count: int | None = None
        self.view_paths: list[str] | None = None
        self.transform7 = [[-15.0, 0.0, 5.0, 0.0, 0.0, HALF, HALF]]
        self.com7 = [[0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]]
        self.views: list[FakeSimView] = []
        self.view_frontends: list[tuple[str, int]] = []
        self.view_raises = False
        self.body_view_raises = False
        self.push_raises = False
        self.invalidate_raises = False
        self.tensor_pushes: list[tuple[Any, ...]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def add_body(self, path: str) -> None:
        prim = UsdGeom.Cube.Define(self.stage, path).GetPrim()
        UsdPhysics.RigidBodyAPI.Apply(prim)

    def scene_attr(self, name: str, kind: Any, value: Any) -> None:
        self.scene.CreateAttribute(f"physxScene:{name}", kind).Set(value)

    def create_simulation_view(self, frontend: str, stage_id: int = -1, backend: str = "physx") -> FakeSimView:
        if self.view_raises:
            raise Exception("Failed to create simulation view")
        self.view_frontends.append((frontend, stage_id))
        self.views.append(FakeSimView(self))
        return self.views[-1]

    def apply_force_at_pos(self, stage_id: int, path_int: int, force: Any, point: Any, mode: str) -> None:
        if self.physx_push_raises:
            raise RuntimeError("the scene is gone")
        self.physx_pushes.append((stage_id, path_int, tuple(force), tuple(point), mode))


def _module(name: str, **attrs: Any) -> ModuleType:
    module = ModuleType(name)
    module.__dict__.update(attrs)
    return module


@pytest.fixture
def kit() -> FakeKit:
    return FakeKit()


@pytest.fixture
def simulation(kit: FakeKit, monkeypatch: pytest.MonkeyPatch) -> Any:
    async def next_update() -> None:
        await asyncio.sleep(0)

    settings = SimpleNamespace(get_as_bool=lambda name: kit.suppress if name == SUPPRESS else False)
    carb = _module(
        "carb",
        Float3=Float3,
        settings=SimpleNamespace(get_settings=lambda: settings),
        log_error=kit.errors.append,
        log_warn=kit.warnings.append,
    )
    timeline = SimpleNamespace(is_stopped=lambda: kit.stopped)
    context = SimpleNamespace(get_stage_id=lambda: kit.stage_id, get_stage=lambda: kit.stage)
    omni_usd = _module("omni.usd", get_context=lambda: context)
    omni_timeline = _module("omni.timeline", get_timeline_interface=lambda: timeline)
    kit_app = _module("omni.kit.app")
    omni_kit = _module("omni.kit", app=kit_app)
    physx = _module(
        "omni.physx",
        get_physx_interface=lambda: SimpleNamespace(
            get_rigidbody_transformation=lambda _path: kit.pose if kit.held else {"ret_val": False}
        ),
        get_physx_simulation_interface=lambda: SimpleNamespace(apply_force_at_pos=kit.apply_force_at_pos),
        get_physxunittests_interface=lambda: SimpleNamespace(get_mass_information=lambda _p: kit.mass_information),
    )
    tensors = _module("omni.physics.tensors", create_simulation_view=kit.create_simulation_view)
    omni_physics = _module("omni.physics", tensors=tensors)
    omni = _module("omni", kit=omni_kit, usd=omni_usd, timeline=omni_timeline, physx=physx, physics=omni_physics)
    warp = _module(
        "warp",
        float32="float32",
        uint32="uint32",
        array=FakeArray,
    )
    fakes = {
        "carb": carb,
        "omni": omni,
        "omni.kit": omni_kit,
        "omni.kit.app": kit_app,
        "omni.usd": omni_usd,
        "omni.timeline": omni_timeline,
        "omni.physx": physx,
        "omni.physics": omni_physics,
        "omni.physics.tensors": tensors,
        "warp": warp,
        "handlers_under_test": _module("handlers_under_test", __path__=[]),
        "handlers_under_test._utils": _module(
            "handlers_under_test._utils", _get_stage=lambda: kit.stage, _next_update=next_update
        ),
        "handlers_under_test.recording": _module(
            "handlers_under_test.recording", recording_active=lambda: False, recording_note=lambda: None
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    # PhysicsSchemaTools is Kit's: the path as an integer, which the fake push records.
    monkeypatch.setattr(pxr, "PhysicsSchemaTools", SimpleNamespace(sdfPathToInt=len), raising=False)
    spec = importlib.util.spec_from_file_location("handlers_under_test.simulation", Path(HANDLER))
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _push(simulation: Any, **extra: Any) -> dict[str, Any]:
    body = {"prim_path": BOX, "force": [10.0, 0.0, 0.0], **extra}
    return asyncio.run(simulation.handle_apply_force(body))


# ----- today's path: IPhysxSimulation.apply_force_at_pos -----


def test_the_cpu_pipeline_pushes_through_physx_at_the_centre_of_mass(simulation, kit):
    kit.suppress = False
    r = _push(simulation, impulse=True)
    assert r["status"] == "success", r
    assert r["result"]["method"] == "physx"
    assert r["result"]["at"] == "centre of mass"
    assert r["result"]["position"] == pytest.approx([1.0, 2.0, 3.25])
    ((stage_id, _, force, point, mode),) = kit.physx_pushes
    assert (stage_id, force, mode) == (7, (10.0, 0.0, 0.0), "Impulse")
    assert point == pytest.approx((1.0, 2.0, 3.25))
    assert not kit.views, "the tensor API stays out of the CPU path"


def test_a_force_with_a_position_is_pushed_there(simulation, kit):
    kit.suppress = False
    r = _push(simulation, position=[4.0, 5.0, 6.0])
    assert r["result"]["at"] == "given"
    assert r["result"]["position"] == [4.0, 5.0, 6.0]
    assert kit.physx_pushes[0][4] == "Force"


def test_the_setting_alone_on_a_cpu_scene_takes_todays_call(simulation, kit):
    # #68's E15 and E16: with readback on, or with the setting true on a CPU scene, PhysX's call pushes.
    kit.scene_attr("enableGPUDynamics", Sdf.ValueTypeNames.Bool, False)
    r = _push(simulation)
    assert r["status"] == "success", r
    assert r["result"]["method"] == "physx"
    assert len(kit.physx_pushes) == 1
    assert not kit.views


def test_gpu_dynamics_with_readback_on_takes_todays_call(simulation, kit):
    kit.suppress = False
    r = _push(simulation)
    assert r["result"]["method"] == "physx"
    assert not kit.views


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda k: setattr(k, "stopped", True), "The simulation is stopped"),
        (lambda k: setattr(k, "held", False), "PhysX holds no rigid body at /World/Box"),
        (lambda k: k.stage.GetPrimAtPath(BOX).GetAttribute("physics:kinematicEnabled").Set(True), "is kinematic"),
        (lambda k: k.stage.GetPrimAtPath(BOX).GetAttribute("physics:rigidBodyEnabled").Set(False), "is disabled"),
    ],
)
def test_the_cpu_path_refuses_what_physx_wont_move(simulation, kit, change, says):
    kit.suppress = False
    UsdPhysics.RigidBodyAPI(kit.stage.GetPrimAtPath(BOX)).CreateKinematicEnabledAttr(False)
    UsdPhysics.RigidBodyAPI(kit.stage.GetPrimAtPath(BOX)).CreateRigidBodyEnabledAttr(True)
    change(kit)
    r = _push(simulation)
    assert r["status"] == "error"
    assert says in r["error"]
    assert not kit.physx_pushes


def test_the_cpu_path_refuses_a_body_a_fixed_joint_holds(simulation, kit):
    kit.suppress = False
    joint = UsdPhysics.FixedJoint.Define(kit.stage, "/World/Bolt")
    joint.CreateBody1Rel().SetTargets([Sdf.Path(BOX)])
    r = _push(simulation)
    assert r["status"] == "error"
    assert "held to the world by a fixed joint" in r["error"]


def test_the_cpu_path_answers_a_physx_failure(simulation, kit):
    kit.suppress = False
    kit.physx_push_raises = True
    r = _push(simulation)
    assert r["error"] == "PhysX could not push /World/Box: the scene is gone"


def test_the_cpu_path_without_a_mass_asks_for_a_position(simulation, kit):
    kit.suppress = False
    kit.mass_information = {"mass": 0.0, "com": (0.0, 0.0, 0.0)}
    r = _push(simulation)
    assert r["status"] == "error"
    assert "PhysX has no mass for /World/Box" in r["error"]


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"prim_path": BOX}, "force [fx, fy, fz] is required"),
        ({"prim_path": "/World/Nothing", "force": [1, 0, 0]}, "Prim not found: /World/Nothing"),
        ({"prim_path": "/World", "force": [1, 0, 0]}, "Prim has no RigidBodyAPI: /World"),
    ],
)
def test_the_request_is_checked_before_either_path(simulation, kit, body, says):
    r = asyncio.run(simulation.handle_apply_force(body))
    assert r == {"status": "error", "error": says}
    assert not kit.views
    assert not kit.physx_pushes


# ----- the tensor path -----


def test_under_the_direct_gpu_api_the_body_is_pushed_through_the_tensor_api(simulation, kit):
    r = _push(simulation, position=[1.0, 2.0, 3.0])
    assert r["status"] == "success", r
    assert r["result"] == {
        "prim_path": BOX,
        "force": [10.0, 0.0, 0.0],
        "position": [1.0, 2.0, 3.0],
        "at": "given",
        "impulse": False,
        "method": "tensor",
    }
    assert not kit.physx_pushes, "today's call moves nothing there"
    assert kit.view_frontends == [("warp", 7)]
    ((forces, torques, points, indices, is_global),) = kit.tensor_pushes
    assert forces.data.tolist() == [[10.0, 0.0, 0.0]]
    assert points.data.tolist() == [[1.0, 2.0, 3.0]]
    assert (forces.data.shape, points.data.shape, indices.data.shape) == ((1, 3), (1, 3), (1,))
    assert (forces.dtype, points.dtype, indices.dtype) == ("float32", "float32", "uint32")
    assert forces.data.dtype == points.data.dtype == np.float32
    assert indices.data.dtype == np.uint32
    assert indices.data.tolist() == [0]
    assert (forces.device, points.device, indices.device) == ("cuda:0",) * 3
    assert torques is None
    assert is_global is True


def test_without_a_position_the_push_is_at_the_centre_of_mass_from_both_rows(simulation, kit):
    r = _push(simulation)
    assert r["result"]["at"] == "centre of mass"
    assert r["result"]["position"] == pytest.approx([-15.0, 0.1, 5.0], abs=1e-6)
    ((_, _, points, _, _),) = kit.tensor_pushes
    assert points.data[0].tolist() == pytest.approx([-15.0, 0.1, 5.0], abs=1e-6)


def test_an_impulse_is_the_force_over_one_step_of_the_scenes_rate(simulation, kit):
    kit.scene_attr("timeStepsPerSecond", Sdf.ValueTypeNames.UInt, 240)
    r = _push(simulation, impulse=True)
    assert r["result"]["impulse"] is True
    assert r["result"]["force"] == [10.0, 0.0, 0.0], "the answer repeats the request"
    ((forces, *_),) = kit.tensor_pushes
    assert forces.data.tolist() == [[2400.0, 0.0, 0.0]]


def test_an_impulse_is_a_sixtieth_s_force_without_a_rate(simulation, kit):
    _push(simulation, impulse=True)
    assert kit.tensor_pushes[0][0].data[0].tolist() == pytest.approx([600.0, 0.0, 0.0])


def test_a_force_is_pushed_as_it_is(simulation, kit):
    kit.scene_attr("timeStepsPerSecond", Sdf.ValueTypeNames.UInt, 240)
    _push(simulation)
    assert kit.tensor_pushes[0][0].data.tolist() == [[10.0, 0.0, 0.0]]


def test_a_step_the_scene_cant_give_is_said_before_any_tensor_call(simulation, kit):
    kit.scene_attr("timeStepsPerSecond", Sdf.ValueTypeNames.UInt, 0)
    r = _push(simulation)
    assert r["status"] == "error"
    assert r["error"].startswith("the physics scene's step can't be used: /World/PhysicsScene's")
    assert not kit.views


def test_the_view_is_invalidated_after_a_push(simulation, kit):
    _push(simulation)
    assert [v.invalidated for v in kit.views] == [1]


def test_a_view_of_the_wrong_count_is_a_body_physx_doesnt_hold(simulation, kit):
    kit.view_count = 2
    kit.view_paths = [BOX, "/World/Other"]
    r = _push(simulation)
    assert r["status"] == "error"
    assert r["error"].startswith("PhysX holds no rigid body at /World/Box")
    assert not kit.tensor_pushes
    assert [v.invalidated for v in kit.views] == [1]


def test_a_view_of_another_prim_is_a_body_physx_doesnt_hold(simulation, kit):
    kit.view_count = 1
    kit.view_paths = ["/World/Other"]
    assert _push(simulation)["error"].startswith("PhysX holds no rigid body at /World/Box")


def test_a_view_of_no_body_is_a_body_physx_doesnt_hold(simulation, kit):
    kit.tensor_bodies = []
    assert _push(simulation)["error"].startswith("PhysX holds no rigid body at /World/Box")


def test_view_creation_that_raises_is_answered_and_logged(simulation, kit):
    kit.view_raises = True
    r = _push(simulation)
    assert r == {
        "status": "error",
        "error": "PhysX's tensor API could not push /World/Box: Failed to create simulation view",
    }
    (logged,) = kit.errors
    assert "Traceback" in logged
    assert "Failed to create simulation view" in logged
    assert not kit.tensor_pushes


def test_a_rigid_body_view_that_raises_is_answered_and_the_simulation_view_invalidated(simulation, kit):
    kit.body_view_raises = True
    r = _push(simulation)
    assert r["error"] == "PhysX's tensor API could not push /World/Box: no rigid bodies match"
    assert [v.invalidated for v in kit.views] == [1]


def test_a_push_that_raises_is_answered_and_the_view_invalidated_after_it(simulation, kit):
    kit.push_raises = True
    r = _push(simulation)
    assert r["error"] == (
        "PhysX's tensor API could not push /World/Box: Failed to apply forces and torques at pos in backend"
    )
    assert [v.invalidated for v in kit.views] == [1]
    assert len(kit.errors) == 1


def test_a_slip_in_the_rows_is_answered_and_logged_with_its_traceback(simulation, kit):
    kit.com7 = [[0.0, 0.0, 0.0]]  # not the 7 numbers a row holds
    r = _push(simulation)
    assert r["status"] == "error"
    assert r["error"].startswith("PhysX's tensor API could not push /World/Box:")
    assert "Traceback" in kit.errors[0]


def test_a_failing_invalidate_doesnt_hide_the_answer(simulation, kit):
    kit.invalidate_raises = True
    r = _push(simulation)
    assert r["status"] == "success", r
    assert r["result"]["method"] == "tensor"
    assert kit.warnings == ["apply_force could not invalidate its tensor view: already invalid"]


@pytest.mark.parametrize(
    ("change", "says"),
    [
        (lambda k: setattr(k, "stopped", True), "The simulation is stopped"),
        (lambda k: k.stage.GetPrimAtPath(BOX).GetAttribute("physics:kinematicEnabled").Set(True), "is kinematic"),
        (lambda k: k.stage.GetPrimAtPath(BOX).GetAttribute("physics:rigidBodyEnabled").Set(False), "is disabled"),
    ],
)
def test_the_tensor_path_refuses_what_physx_wont_move(simulation, kit, change, says):
    UsdPhysics.RigidBodyAPI(kit.stage.GetPrimAtPath(BOX)).CreateKinematicEnabledAttr(False)
    UsdPhysics.RigidBodyAPI(kit.stage.GetPrimAtPath(BOX)).CreateRigidBodyEnabledAttr(True)
    change(kit)
    r = _push(simulation)
    assert r["status"] == "error"
    assert says in r["error"]
    assert not kit.views


def test_the_tensor_path_refuses_a_body_a_fixed_joint_holds(simulation, kit):
    joint = UsdPhysics.FixedJoint.Define(kit.stage, "/World/Bolt")
    joint.CreateBody1Rel().SetTargets([Sdf.Path(BOX)])
    r = _push(simulation)
    assert r["error"] == f"{BOX} is held to the world by a fixed joint: no force moves it"
    assert not kit.views


@pytest.mark.parametrize("missing", ["omni.physics.tensors", "warp"])
def test_a_kit_app_without_the_tensor_api_or_warp_refuses_and_names_the_issue(simulation, kit, monkeypatch, missing):
    if missing == "omni.physics.tensors":
        # A Kit app without the extension has neither the module nor the attribute on its package.
        monkeypatch.delitem(sys.modules, missing)
        monkeypatch.delattr(sys.modules["omni.physics"], "tensors")
    else:
        monkeypatch.setitem(sys.modules, missing, None)
    r = _push(simulation)
    assert r["status"] == "error"
    assert "goes through omni.physics.tensors and warp" in r["error"]
    assert "(#68)" in r["error"]
    assert not kit.views
    assert not kit.physx_pushes


def test_a_stopped_simulation_is_refused_before_a_missing_module(simulation, kit, monkeypatch):
    monkeypatch.setitem(sys.modules, "warp", None)
    kit.stopped = True
    assert _push(simulation)["error"].startswith("The simulation is stopped")


def test_a_stage_without_a_scene_takes_todays_call(simulation, kit):
    kit.stage.RemovePrim("/World/PhysicsScene")
    r = _push(simulation)
    assert r["result"]["method"] == "physx"
