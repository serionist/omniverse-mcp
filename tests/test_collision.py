"""A prim made a collider or its collision turned off (ovmcp/core/collision.py, #150), on usd-core stages: which prims
PhysX makes a shape for and the refusals for the rest, the rigid body a collider moves with, a moving Mesh's convex
hull, and the echo set_physics_properties answers with."""

import pytest
from pxr import Sdf, Usd, UsdGeom, UsdPhysics

from ovmcp.core.collision import collision_refusal, set_collision
from ovmcp.core.usd import has_api


@pytest.fixture
def stage() -> Usd.Stage:
    made = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(made, "/World")
    return made


def _mesh(stage: Usd.Stage, path: str) -> Usd.Prim:
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    return mesh.GetPrim()


def _body(prim: Usd.Prim, kinematic: bool = False) -> Usd.Prim:
    body = UsdPhysics.RigidBodyAPI.Apply(prim)
    if kinematic:
        body.CreateKinematicEnabledAttr().Set(True)
    return prim


# ---- which prims may take a collider ----


@pytest.mark.parametrize("kind", ["Cube", "Sphere", "Capsule", "Cylinder", "Cone", "Mesh", "Plane"])
def test_each_shape_physx_collides_is_let_through(stage, kind):
    assert collision_refusal(stage.DefinePrim(f"/World/{kind}", kind)) is None


def test_curves_are_a_gprim_physx_makes_no_shape_for(stage):
    curves = stage.DefinePrim("/World/Cable", "BasisCurves")

    said = collision_refusal(curves)

    assert said is not None
    assert said.startswith("/World/Cable is a BasisCurves, which PhysX makes no shape for")
    assert "Cube, Sphere, Capsule, Cylinder, Cone, Mesh and Plane" in said


def test_an_xform_names_the_shapes_under_it(stage):
    UsdGeom.Xform.Define(stage, "/World/Ground")
    UsdGeom.Cube.Define(stage, "/World/Ground/Slab")
    _mesh(stage, "/World/Ground/Rocks")

    said = collision_refusal(stage.GetPrimAtPath("/World/Ground"))

    assert said is not None
    assert said.startswith("/World/Ground is an Xform, which PhysX makes no shape for")
    assert said.endswith("Make the shapes under it colliders one by one: /World/Ground/Slab, /World/Ground/Rocks")


def test_an_xform_over_many_shapes_names_five_and_counts_them(stage):
    for n in range(7):
        UsdGeom.Cube.Define(stage, f"/World/Pile/Box{n}")

    said = collision_refusal(stage.GetPrimAtPath("/World/Pile"))

    assert said is not None
    assert said.endswith("/World/Pile/Box3, /World/Pile/Box4, of 7 in all")
    assert "Box5" not in said


def _instanced_floor(stage: Usd.Stage) -> Usd.Prim:
    UsdGeom.Xform.Define(stage, "/Props/Floor")
    UsdGeom.Cube.Define(stage, "/Props/Floor/geo")
    floor = stage.DefinePrim("/World/Floor", "Xform")
    floor.GetReferences().AddInternalReference("/Props/Floor")
    floor.SetInstanceable(True)
    return floor


def test_an_xform_whose_shapes_lie_inside_an_instance_says_so(stage):
    # Naming /World/Floor/geo would send the next call to a prim it refuses (round 1, P4).
    said = collision_refusal(_instanced_floor(stage))

    assert said is not None
    assert "lie inside the instance /World/Floor" in said
    assert "geo" not in said


def test_a_prim_inside_an_instance_is_refused_naming_the_instance(stage):
    _instanced_floor(stage)

    said = collision_refusal(stage.GetPrimAtPath("/World/Floor/geo"))

    assert said is not None
    assert said.startswith("/World/Floor/geo is inside the instance /World/Floor")
    assert "instanceable turned off" in said


def test_an_instanceable_shape_itself_is_let_through(stage):
    cube = UsdGeom.Cube.Define(stage, "/World/Crate").GetPrim()
    cube.SetInstanceable(True)

    assert collision_refusal(cube) is None


def test_an_inactive_prim_is_refused(stage):
    cube = UsdGeom.Cube.Define(stage, "/World/Crate").GetPrim()
    cube.SetActive(False)

    said = collision_refusal(cube)

    assert said == "/World/Crate is inactive, so PhysX makes no shape for it: activate it first"


def test_an_empty_xform_says_none_lies_under_it(stage):
    said = collision_refusal(stage.GetPrimAtPath("/World"))

    assert said is not None
    assert said.endswith("and none lies under it")


# ---- collision on and off ----


def test_on_makes_a_static_collider_with_no_body_and_no_material(stage):
    floor = UsdGeom.Cube.Define(stage, "/World/Floor").GetPrim()

    echo = set_collision(floor, True)

    assert echo == {"applied": ["CollisionAPI"], "collision": True}
    assert has_api(floor, UsdPhysics.CollisionAPI)
    assert not has_api(floor, UsdPhysics.RigidBodyAPI)
    assert not floor.GetRelationship("material:binding:physics").IsValid()


def test_on_turns_an_authored_false_back_on_and_names_no_api(stage):
    floor = UsdGeom.Cube.Define(stage, "/World/Floor").GetPrim()
    UsdPhysics.CollisionAPI.Apply(floor).CreateCollisionEnabledAttr().Set(False)

    echo = set_collision(floor, True)

    assert echo == {"applied": [], "collision": True}
    assert UsdPhysics.CollisionAPI(floor).GetCollisionEnabledAttr().Get() is True


def test_off_turns_collision_off_and_keeps_the_api(stage):
    floor = UsdGeom.Cube.Define(stage, "/World/Floor").GetPrim()
    UsdPhysics.CollisionAPI.Apply(floor)

    echo = set_collision(floor, False)

    assert echo == {"applied": [], "collision": False}
    assert has_api(floor, UsdPhysics.CollisionAPI)
    assert UsdPhysics.CollisionAPI(floor).GetCollisionEnabledAttr().Get() is False


def test_off_on_a_prim_without_a_collider_writes_nothing_and_says_so(stage):
    floor = UsdGeom.Cube.Define(stage, "/World/Floor").GetPrim()
    before = stage.GetRootLayer().ExportToString()

    echo = set_collision(floor, False)

    # Its own key, so "had none" isn't read as an extension that dropped collision (round 1, P2).
    assert echo == {"applied": [], "collider": False, "collision": False}
    assert stage.GetRootLayer().ExportToString() == before


def test_the_echo_reads_back_what_a_stronger_layer_holds(stage):
    floor = UsdGeom.Cube.Define(stage, "/World/Floor").GetPrim()
    UsdPhysics.CollisionAPI.Apply(floor)
    session = stage.GetSessionLayer()
    over = Sdf.CreatePrimInLayer(session, "/World/Floor")
    Sdf.AttributeSpec(over, "physics:collisionEnabled", Sdf.ValueTypeNames.Bool).default = False

    echo = set_collision(floor, True)

    assert echo["collision"] is False


# ---- a Mesh that moves ----


def test_a_mesh_that_is_a_rigid_body_gets_a_convex_hull(stage):
    rock = _body(_mesh(stage, "/World/Rock"))

    echo = set_collision(rock, True)

    assert echo == {
        "applied": ["CollisionAPI", "MeshCollisionAPI"],
        "approximation": "convexHull",
        "body": "/World/Rock",
        "collision": True,
    }
    assert UsdPhysics.MeshCollisionAPI(rock).GetApproximationAttr().Get() == "convexHull"


def test_a_mesh_under_a_rigid_body_gets_a_hull_and_names_the_body(stage):
    _body(UsdGeom.Xform.Define(stage, "/World/Cart").GetPrim())
    wheel = _mesh(stage, "/World/Cart/Wheel")

    echo = set_collision(wheel, True)

    assert echo["approximation"] == "convexHull"
    assert echo["body"] == "/World/Cart"


def test_a_static_mesh_keeps_physx_s_triangles(stage):
    terrain = _mesh(stage, "/World/Terrain")

    echo = set_collision(terrain, True)

    assert "approximation" not in echo
    assert not has_api(terrain, UsdPhysics.MeshCollisionAPI)


def test_a_kinematic_body_s_mesh_keeps_its_triangles(stage):
    arm = _body(_mesh(stage, "/World/Arm"), kinematic=True)

    echo = set_collision(arm, True)

    assert "approximation" not in echo
    assert echo["body"] == "/World/Arm"


def test_an_approximation_already_authored_is_kept(stage):
    rock = _body(_mesh(stage, "/World/Rock"))
    UsdPhysics.MeshCollisionAPI.Apply(rock).CreateApproximationAttr().Set(UsdPhysics.Tokens.convexDecomposition)

    echo = set_collision(rock, True)

    assert "approximation" not in echo
    assert UsdPhysics.MeshCollisionAPI(rock).GetApproximationAttr().Get() == "convexDecomposition"


def test_a_cube_under_a_rigid_body_names_the_body_and_gets_no_hull(stage):
    _body(UsdGeom.Xform.Define(stage, "/World/Cart").GetPrim())
    bumper = UsdGeom.Cube.Define(stage, "/World/Cart/Bumper").GetPrim()

    echo = set_collision(bumper, True)

    assert echo == {"applied": ["CollisionAPI"], "body": "/World/Cart", "collision": True}


def test_turning_collision_off_is_refused_in_off_s_own_words(stage):
    # "Activate it first" would bring back a prim the user hid, which then renders and collides (code review, F1).
    crate = UsdGeom.Cube.Define(stage, "/World/Crate").GetPrim()
    crate.SetActive(False)
    UsdGeom.Xform.Define(stage, "/World/Ground")
    UsdGeom.Cube.Define(stage, "/World/Ground/Slab")

    inactive = collision_refusal(crate, on=False)
    xform = collision_refusal(stage.GetPrimAtPath("/World/Ground"), on=False)
    empty = collision_refusal(stage.DefinePrim("/World/Empty", "Xform"), on=False)

    assert inactive is not None and inactive.endswith("it collides with nothing, and there is no collision to turn off")
    assert "activate" not in inactive
    assert xform is not None and xform.endswith(
        "Turn collision off on the shapes under it one by one: /World/Ground/Slab"
    )
    assert empty is not None and empty.endswith("nothing under it collides: no collision to turn off")
