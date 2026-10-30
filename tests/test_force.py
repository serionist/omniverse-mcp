"""apply_force's request, its refusals and the point it pushes at (#25, #58), without Kit."""

import math
import re
from typing import Any

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.force import (
    ForceArgs,
    Joints,
    centre_of_mass,
    fixed_refusal,
    force_args,
    refusal,
    world_point,
)
from ovmcp.core.usd import has_api

IDENTITY = (0.0, 0.0, 0.0, 1.0)  # x, y, z, w, as PhysX gives a rotation
HALF = math.sqrt(0.5)


class Float3:
    """Stands for carb.Float3: indexable and sized, not a list or a tuple."""

    def __init__(self, *values: float):
        self._values = values

    def __getitem__(self, i: int) -> float:
        return self._values[i]

    def __len__(self) -> int:
        return len(self._values)


def test_force_args_take_a_force_and_default_the_rest():
    args = force_args({"prim_path": "/World/Box", "force": [10, 0, -2.5]})
    assert args == ForceArgs("/World/Box", (10.0, 0.0, -2.5), None, False)
    assert args.mode == "Force"


def test_force_args_take_a_position_and_an_impulse():
    args = force_args({"prim_path": "/World/Box", "force": [0, 0, 1], "position": (1, 2, 3), "impulse": True})
    assert args.position == (1.0, 2.0, 3.0)
    assert args.impulse
    assert args.mode == "Impulse"


def test_a_null_position_is_the_centre_of_mass():
    assert force_args({"prim_path": "/World/Box", "force": [1, 0, 0], "position": None}).position is None


@pytest.mark.parametrize(
    ("body", "says"),
    [
        ({"force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": "", "force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": 7, "force": [1, 0, 0]}, "No prim_path provided"),
        ({"prim_path": "/World/Box"}, "force [fx, fy, fz] is required"),
        ({"prim_path": "/World/Box", "force": [1, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": "100"}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": {"x": 1, "y": 0, "z": 0}}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": 100}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, "0", 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [True, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [math.nan, 0, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [0, math.inf, 0]}, "force must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "position": [0, 0]}, "position must be 3 finite numbers"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "impulse": "yes"}, "impulse must be true or false"),
        ({"prim_path": "/World/Box", "force": [1, 0, 0], "impulse": 1}, "impulse must be true or false"),
    ],
)
def test_force_args_refuse_what_physx_cant_take(body, says):
    with pytest.raises(ValueError, match="^" + re.escape(says)):
        force_args(body)


def _why(
    path: str = "/World/Box",
    *,
    stopped: bool = False,
    direct_gpu: bool = False,
    enabled: bool = True,
    kinematic: bool = False,
    held: bool = True,
) -> str | None:
    """refusal for a body PhysX would push, but for what the test names."""
    return refusal(path, stopped=stopped, direct_gpu=direct_gpu, enabled=enabled, kinematic=kinematic, held=held)


def test_a_stopped_timeline_is_refused_first():
    # Stopped, PhysX holds no bodies, so whether it holds this one says nothing.
    why = _why(stopped=True, direct_gpu=True, enabled=False, kinematic=True, held=False)
    assert why is not None
    assert why.startswith("The simulation is stopped")
    assert "paused works too" in why


def test_the_direct_gpu_api_is_refused_before_what_the_body_says_and_says_how_to_turn_it_off():
    # Measured on Isaac Sim 6.2: with suppressReadback, a push on a lone cube returned and moved nothing (#68).
    why = _why(direct_gpu=True, enabled=False, kinematic=True, held=False)
    assert why == (
        "PhysX's Direct GPU API is on (/physics/suppressReadback is true), and a push moves nothing under it (#68). "
        "To push bodies, stop the simulation, turn it off with execute_script: "
        "carb.settings.get_settings().set_bool('/physics/suppressReadback', False), and play again"
    )


def test_a_disabled_rigid_body_is_refused_before_a_kinematic_one():
    why = _why(enabled=False, kinematic=True)
    assert why is not None
    assert why.startswith("/World/Box's rigid body is disabled (physics:rigidBodyEnabled is false)")
    assert "static body" in why


def test_a_kinematic_body_is_refused():
    why = _why(kinematic=True)
    assert why is not None
    assert why.startswith("/World/Box is kinematic (physics:kinematicEnabled is true)")


def test_a_body_physx_doesnt_hold_is_refused():
    why = _why(held=False)
    assert why is not None
    assert why.startswith("PhysX holds no rigid body at /World/Box")


def test_a_body_physx_holds_while_it_plays_or_pauses_is_pushed():
    assert _why() is None


def test_an_articulation_s_link_is_pushed():
    # 0.2.1 refused it on a misread measurement; PhysX's push reaches a link (#58).
    assert _why("/World/G1/hip") is None


def test_a_body_a_fixed_joint_holds_to_the_world_is_refused():
    assert fixed_refusal("/World/Box", "/World/Box", None) == (
        "/World/Box is held to the world by a fixed joint: no force moves it"
    )


def test_a_fixed_base_names_its_articulation():
    assert fixed_refusal("/World/Arm/base", "/World/Arm/base", "/World/Arm") == (
        "/World/Arm/base is held to the world by a fixed joint, as the base of the articulation at /World/Arm: no "
        "force moves it"
    )


def test_a_body_welded_to_its_fixed_base_is_refused():
    assert fixed_refusal("/World/Shelf", "/World/Post", None) == (
        "/World/Shelf is welded to its fixed base /World/Post, which a fixed joint holds to the world: no force "
        "moves it"
    )


def test_a_link_welded_to_its_fixed_base_names_its_articulation():
    assert fixed_refusal("/World/Arm/sensor", "/World/Arm/base", "/World/Arm") == (
        "/World/Arm/sensor is welded to its fixed base /World/Arm/base, which a fixed joint holds to the world, in "
        "the articulation at /World/Arm: no force moves it"
    )


def _body(stage: Usd.Stage, path: str, *, enabled: bool = True, kinematic: bool = False) -> Usd.Prim:
    prim = UsdGeom.Cube.Define(stage, path).GetPrim()
    body = UsdPhysics.RigidBodyAPI.Apply(prim)
    if not enabled:
        body.CreateRigidBodyEnabledAttr().Set(False)
    if kinematic:
        body.CreateKinematicEnabledAttr().Set(True)
    UsdPhysics.CollisionAPI.Apply(prim)
    return prim


def _joint(
    stage: Usd.Stage,
    path: str,
    body0: str | None,
    body1: str,
    *,
    fixed: bool = False,
    excluded: bool = False,
    enabled: bool = True,
) -> Usd.Prim:
    joint = (UsdPhysics.FixedJoint if fixed else UsdPhysics.RevoluteJoint).Define(stage, path)
    if body0 is not None:  # none: held to the world
        joint.CreateBody0Rel().SetTargets([Sdf.Path(body0)])
    joint.CreateBody1Rel().SetTargets([Sdf.Path(body1)])
    if excluded:
        joint.CreateExcludeFromArticulationAttr().Set(True)
    if not enabled:
        joint.CreateJointEnabledAttr().Set(False)
    return joint.GetPrim()


@pytest.fixture
def robots() -> Usd.Stage:
    """Robots as Isaac Sim's assets build them, beside bodies that are no robot's."""
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    # The G1: the root on the pelvis, the links its siblings, the joints in a folder of their own.
    UsdGeom.Xform.Define(stage, "/World/G1")
    UsdPhysics.ArticulationRootAPI.Apply(_body(stage, "/World/G1/pelvis"))
    _body(stage, "/World/G1/hip")
    _body(stage, "/World/G1/knee")
    _joint(stage, "/World/G1/joints/hip", "/World/G1/pelvis", "/World/G1/hip")
    _joint(stage, "/World/G1/joints/knee", "/World/G1/hip", "/World/G1/knee")
    # A tool held by a joint excluded from articulations: the parser still counts the tool in the G1's.
    _body(stage, "/World/Tool")
    _joint(stage, "/World/toolmount", "/World/G1/knee", "/World/Tool", excluded=True)
    # A floating robot whose root is on its Xform.
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Dog").GetPrim())
    _body(stage, "/World/Dog/trunk")
    _body(stage, "/World/Dog/leg")
    _joint(stage, "/World/Dog/hip", "/World/Dog/trunk", "/World/Dog/leg")
    # A fixed arm: held to the world, its root on its Xform; the joint names a child of the base, not the base.
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Arm").GetPrim())
    _body(stage, "/World/Arm/base")
    UsdGeom.Xform.Define(stage, "/World/Arm/base/flange")
    _body(stage, "/World/Arm/link")
    _joint(stage, "/World/Arm/fix", None, "/World/Arm/base")
    _joint(stage, "/World/Arm/j1", "/World/Arm/base/flange", "/World/Arm/link")
    # Bolted to the wall the gate below hangs on: a static anchor joins the arm to nothing.
    _joint(stage, "/World/Arm/mount", "/World/Wall", "/World/Arm/base")
    # A crane whose root is on its fixed joint to the world, as UsdPhysics allows for a fixed articulation.
    UsdGeom.Xform.Define(stage, "/World/Crane")
    _body(stage, "/World/Crane/base")
    _body(stage, "/World/Crane/boom")
    UsdPhysics.ArticulationRootAPI.Apply(_joint(stage, "/World/Crane/fix", None, "/World/Crane/base", fixed=True))
    _joint(stage, "/World/Crane/slew", "/World/Crane/base", "/World/Crane/boom")
    # A fixed arm as the Franka is built: its base fixed to the world, a sensor welded to the base, a link that turns.
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Panda").GetPrim())
    _body(stage, "/World/Panda/base")
    _body(stage, "/World/Panda/sensor")
    _body(stage, "/World/Panda/link")
    _joint(stage, "/World/Panda/fix", None, "/World/Panda/base", fixed=True)
    _joint(stage, "/World/Panda/weld", "/World/Panda/base", "/World/Panda/sensor", fixed=True)
    _joint(stage, "/World/Panda/j1", "/World/Panda/base", "/World/Panda/link")
    # A cart bolted to the wall, a static prim; a rover held by a fixed joint excluded from articulations; a lift
    # whose fixed joint is disabled; and a crate bolted to the world, in no articulation.
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Cart").GetPrim())
    _body(stage, "/World/Cart/base")
    _body(stage, "/World/Cart/wheel")
    _joint(stage, "/World/Cart/bolt", "/World/Wall", "/World/Cart/base", fixed=True)
    _joint(stage, "/World/Cart/axle", "/World/Cart/base", "/World/Cart/wheel")
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Rover").GetPrim())
    _body(stage, "/World/Rover/base")
    _body(stage, "/World/Rover/wheel")
    _joint(stage, "/World/Rover/fix", None, "/World/Rover/base", fixed=True, excluded=True)
    _joint(stage, "/World/Rover/axle", "/World/Rover/base", "/World/Rover/wheel")
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Lift").GetPrim())
    _body(stage, "/World/Lift/base")
    _body(stage, "/World/Lift/arm")
    _joint(stage, "/World/Lift/fix", None, "/World/Lift/base", fixed=True, enabled=False)
    _joint(stage, "/World/Lift/j1", "/World/Lift/base", "/World/Lift/arm")
    _body(stage, "/World/Crate")
    _joint(stage, "/World/cratebolt", None, "/World/Crate", fixed=True)
    # No articulation: a hinged door, a gate hinged to a wall that is no body, and a loose box.
    _body(stage, "/World/Door")
    _body(stage, "/World/Frame")
    _joint(stage, "/World/hinge", "/World/Frame", "/World/Door")
    UsdGeom.Xform.Define(stage, "/World/Wall")
    _body(stage, "/World/Gate")
    _joint(stage, "/World/gatehinge", "/World/Wall", "/World/Gate")
    _body(stage, "/World/Box")
    return stage


@pytest.mark.parametrize(
    ("body", "root"),
    [
        ("/World/G1/pelvis", "/World/G1/pelvis"),
        ("/World/G1/hip", "/World/G1/pelvis"),
        ("/World/G1/knee", "/World/G1/pelvis"),
        ("/World/Tool", "/World/G1/pelvis"),
        ("/World/Dog/trunk", "/World/Dog"),
        ("/World/Dog/leg", "/World/Dog"),
        ("/World/Arm/base", "/World/Arm"),
        ("/World/Arm/link", "/World/Arm"),
        ("/World/Crane/base", "/World/Crane/fix"),
        ("/World/Crane/boom", "/World/Crane/fix"),
        ("/World/Panda/base", "/World/Panda"),
        ("/World/Panda/sensor", "/World/Panda"),
        ("/World/Panda/link", "/World/Panda"),
        ("/World/Cart/wheel", "/World/Cart"),
        ("/World/Rover/wheel", "/World/Rover"),
        ("/World/Lift/arm", "/World/Lift"),
        ("/World/Crate", None),
        ("/World/Door", None),
        ("/World/Frame", None),
        ("/World/Gate", None),
        ("/World/Box", None),
    ],
)
def test_a_body_joined_to_an_articulation_root_is_its_link(robots: Usd.Stage, body: str, root: str | None):
    assert Joints(robots).articulation_holding(body) == root


@pytest.mark.parametrize(
    ("body", "base"),
    [
        ("/World/Panda/base", "/World/Panda/base"),
        ("/World/Panda/sensor", "/World/Panda/base"),  # welded to it
        ("/World/Crane/base", "/World/Crane/base"),
        ("/World/Cart/base", "/World/Cart/base"),  # bolted to a static prim, which PhysX holds still
        ("/World/Rover/base", "/World/Rover/base"),  # excluded from the articulation, the joint still holds it
        ("/World/Crate", "/World/Crate"),  # in no articulation
        ("/World/Panda/link", None),  # turns about its joint
        ("/World/Crane/boom", None),
        ("/World/Cart/wheel", None),
        ("/World/Rover/wheel", None),
        ("/World/Lift/base", None),  # its fixed joint is disabled
        ("/World/Lift/arm", None),
        ("/World/Arm/base", None),  # held by revolute joints, about which it turns
        ("/World/Arm/link", None),
        ("/World/G1/pelvis", None),
        ("/World/Tool", None),
        ("/World/Gate", None),
        ("/World/Box", None),
    ],
)
def test_a_fixed_joint_to_the_world_holds_its_body_and_what_is_welded_to_it(
    robots: Usd.Stage, body: str, base: str | None
):
    assert Joints(robots).held_to_world(body) == base


def _parsed(stage: Usd.Stage, kind: str) -> list[tuple[str, Any]]:
    # UsdPhysics's own parser, which the pxr stubs predate: each object of a kind, as (path, description).
    physics: Any = UsdPhysics
    paths, descs = physics.UsdPhysicsLoadStageFromPrimRange(stage, ["/"])[getattr(physics.ObjectType, kind)]
    return [(str(path), desc) for path, desc in zip(paths, descs, strict=True)]


def test_the_links_are_the_articulated_bodies_usd_physics_parses(robots: Usd.Stage):
    articulated = {str(b) for _, desc in _parsed(robots, "Articulation") for b in desc.articulatedBodies} - {""}
    bodies = [str(p.GetPath()) for p in robots.Traverse() if has_api(p, UsdPhysics.RigidBodyAPI)]
    assert len(bodies) == 24
    joints = Joints(robots)
    assert {b for b in bodies if joints.articulation_holding(b) is not None} == articulated


def test_the_held_links_are_the_ones_usd_physics_fixes_to_the_world(robots: Usd.Stage):
    # The parser lists a fixed base's joint to the world ("", a static prim's end too) among an articulation's
    # joints, an excluded one too, and leaves a disabled one out. Held: a body fixed to "" by one of those joints, and
    # a body welded to a held one.
    fixed = dict(_parsed(robots, "FixedJoint"))
    held: set[str] = set()
    welds: list[tuple[str, str]] = []
    for _, desc in _parsed(robots, "Articulation"):
        for joint in map(str, desc.articulatedJoints):
            if joint in fixed and fixed[joint].jointEnabled:
                ends = (str(fixed[joint].body0), str(fixed[joint].body1))
                if "" in ends:
                    held.update(set(ends) - {""})
                else:
                    welds.append(ends)
    for _ in welds:
        held.update(b for a, c in welds for b in (a, c) if {a, c} & held)
    articulated = {str(b) for _, desc in _parsed(robots, "Articulation") for b in desc.articulatedBodies} - {""}
    joints = Joints(robots)
    assert held == {b for b in articulated if joints.held_to_world(b) is not None}
    assert held == {
        "/World/Panda/base",
        "/World/Panda/sensor",
        "/World/Crane/base",
        "/World/Cart/base",
        "/World/Rover/base",
    }


def test_a_disabled_body_is_static_ground_that_joins_nothing():
    # PhysX holds a disabled body as a static one, and UsdPhysics's parser reads it so: what is fixed to it is held,
    # and it joins no articulation through it.
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdPhysics.ArticulationRootAPI.Apply(_body(stage, "/World/Rig/base"))
    _body(stage, "/World/Rig/off", enabled=False)
    _body(stage, "/World/Rig/tip")
    _joint(stage, "/World/Rig/j1", "/World/Rig/base", "/World/Rig/off")
    _joint(stage, "/World/Rig/j2", "/World/Rig/off", "/World/Rig/tip", fixed=True)
    # Bolting the disabled body to the world joins no body at either end, so it holds nothing more.
    _joint(stage, "/World/Rig/bolt", None, "/World/Rig/off", fixed=True)
    joints = Joints(stage)
    assert joints.held_to_world("/World/Rig/tip") == "/World/Rig/tip"
    assert joints.held_to_world("/World/Rig/base") is None
    assert joints.articulation_holding("/World/Rig/base") == "/World/Rig/base"
    assert joints.articulation_holding("/World/Rig/tip") is None


def test_a_fixed_joint_to_a_deleted_prim_holds_nothing_and_one_to_a_scope_holds():
    # Measured on Isaac Sim 6.2: a cube fixed to a prim that doesn't exist moved as a free one did, so PhysX makes no
    # joint of it; one fixed to a Scope didn't move, held as by the world. usd-core's parser reads both ends as the
    # world (""), so this stays out of the parser checks above.
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdGeom.Scope.Define(stage, "/World/Looks")
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Cart").GetPrim())
    _body(stage, "/World/Cart/base")
    _body(stage, "/World/Cart/wheel")
    _joint(stage, "/World/Cart/axle", "/World/Cart/base", "/World/Cart/wheel")
    _joint(stage, "/World/Cart/bolt", "/World/Pallet", "/World/Cart/base", fixed=True)  # the pallet was deleted
    _body(stage, "/World/Crate")
    _joint(stage, "/World/cratebolt", "/World/Crate", "/World/Pallet", fixed=True)
    _body(stage, "/World/Badge")
    _joint(stage, "/World/badgepin", "/World/Looks", "/World/Badge", fixed=True)
    joints = Joints(stage)
    assert joints.held_to_world("/World/Cart/base") is None
    assert joints.held_to_world("/World/Crate") is None
    assert joints.held_to_world("/World/Badge") == "/World/Badge"
    assert joints.articulation_holding("/World/Cart/wheel") == "/World/Cart"


def test_a_kinematic_mount_holds_what_is_fixed_to_it():
    # A kinematic body moves only by its transform, so a base fixed to one takes a push and doesn't move. It still
    # joins the articulation: UsdPhysics's parser lists it among the articulated bodies.
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdPhysics.ArticulationRootAPI.Apply(UsdGeom.Xform.Define(stage, "/World/Turret").GetPrim())
    _body(stage, "/World/Mount", kinematic=True)
    _body(stage, "/World/Turret/base")
    _body(stage, "/World/Turret/gun")
    _body(stage, "/World/Turret/sight")
    _joint(stage, "/World/Turret/fix", "/World/Mount", "/World/Turret/base", fixed=True)
    _joint(stage, "/World/Turret/swivel", "/World/Turret/base", "/World/Turret/gun")
    _joint(stage, "/World/Turret/weld", "/World/Turret/base", "/World/Turret/sight", fixed=True)
    # Two kinematic bodies fixed together: neither is held by the other, and a push on either is refused as kinematic.
    _body(stage, "/World/Hoist", kinematic=True)
    _joint(stage, "/World/hoistweld", "/World/Mount", "/World/Hoist", fixed=True)
    joints = Joints(stage)
    assert joints.held_to_world("/World/Turret/base") == "/World/Turret/base"
    assert joints.held_to_world("/World/Turret/sight") == "/World/Turret/base"
    assert joints.held_to_world("/World/Turret/gun") is None
    assert joints.held_to_world("/World/Hoist") is None
    assert joints.articulation_holding("/World/Mount") == "/World/Turret"


def test_the_centre_of_mass_comes_from_physx_s_mass_information():
    assert centre_of_mass({"mass": 5.0, "inertia": Float3(1, 1, 1), "com": Float3(0, 0, 0.25)}, "/B") == (0, 0, 0.25)


@pytest.mark.parametrize(
    "info",
    [
        {"mass": 0.0, "com": (0.0, 0.0, 0.0)},  # what PhysX gives for a body it hasn't parsed
        {"mass": -1.0, "com": (0.0, 0.0, 0.0)},
        {"com": (0.0, 0.0, 0.0)},
        {"mass": "5", "com": (0.0, 0.0, 0.0)},
        {"mass": 5.0},
        {"mass": 5.0, "com": None},
        {},
    ],
)
def test_no_mass_is_no_centre_of_mass(info):
    with pytest.raises(ValueError, match=r"^PhysX has no mass for /World/Box, so no centre of mass"):
        centre_of_mass(info, "/World/Box")


def test_a_centre_of_mass_that_isnt_three_numbers_is_an_error():
    with pytest.raises(ValueError, match="com must be 3 finite numbers"):
        centre_of_mass({"mass": 5.0, "com": (0.0, math.nan, 0.0)}, "/World/Box")


def test_no_rotation_and_no_translation_keeps_the_point():
    assert world_point((0, 0, 0), IDENTITY, (0.1, 0.2, 0.3)) == pytest.approx((0.1, 0.2, 0.3))


def test_the_body_s_position_moves_the_point():
    assert world_point(Float3(1, 2, 3), Float3(*IDENTITY), Float3(0, 0, 0.5)) == pytest.approx((1, 2, 3.5))


def test_a_quarter_turn_about_z_takes_x_to_y():
    # PhysX's order: x, y, z, then w.
    assert world_point((0, 0, 0), (0, 0, HALF, HALF), (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-12)


def test_a_quarter_turn_about_y_takes_x_to_minus_z():
    assert world_point((10, 0, 0), (0, HALF, 0, HALF), (1, 0, 0)) == pytest.approx((10, 0, -1), abs=1e-12)


def test_a_half_turn_about_x_takes_y_to_minus_y():
    assert world_point((0, 0, 0), (1, 0, 0, 0), (0, 2, 0)) == pytest.approx((0, -2, 0), abs=1e-12)


def test_a_rotation_that_isnt_a_unit_quaternion_is_normalised():
    assert world_point((0, 0, 0), (0, 0, 3, 3), (1, 0, 0)) == pytest.approx((0, 1, 0), abs=1e-12)


@pytest.mark.parametrize(
    ("position", "rotation", "local", "says"),
    [
        ((0, 0, 0), (0, 0, 0, 0), (1, 0, 0), "rotation must be a quaternion"),
        ((0, 0, 0), (0, 0, 1), (1, 0, 0), "rotation must be 4 finite numbers"),
        ((0, 0), IDENTITY, (1, 0, 0), "position must be 3 finite numbers"),
        ((0, 0, 0), IDENTITY, None, "local must be 3 finite numbers"),
    ],
)
def test_a_pose_that_isnt_one_is_an_error(position, rotation, local, says):
    with pytest.raises(ValueError, match=says):
        world_point(position, rotation, local)
