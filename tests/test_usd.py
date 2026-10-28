"""The typed forms of pxr calls whose stubs are wrong do what the pxr calls do, on usd-core."""

from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics

from ovmcp.core.usd import attribute_spec, children, floats, has_api, is_a, prim_spec, remove_child_spec


def test_is_a_and_has_api_take_schema_classes():
    stage = Usd.Stage.CreateInMemory()
    cube = UsdGeom.Cube.Define(stage, "/Cube").GetPrim()
    light = UsdLux.SphereLight.Define(stage, "/Light").GetPrim()
    UsdPhysics.RigidBodyAPI.Apply(cube)

    assert is_a(cube, UsdGeom.Xformable)
    assert is_a(cube, UsdGeom.Gprim)
    assert not is_a(cube, UsdGeom.Camera)
    assert is_a(light, UsdLux.BoundableLightBase)
    assert has_api(cube, UsdPhysics.RigidBodyAPI)
    assert not has_api(light, UsdPhysics.RigidBodyAPI)
    assert has_api(light, UsdLux.LightAPI)


def test_children_are_what_get_children_gives():
    stage = Usd.Stage.CreateInMemory()
    parent = stage.DefinePrim("/P")
    for name in ("B", "A", "Off", "C"):
        stage.DefinePrim(f"/P/{name}")
    stage.GetPrimAtPath("/P/Off").SetActive(False)
    stage.OverridePrim("/P/Undefined")
    stage.CreateClassPrim("/P/Abstract")

    assert children(parent) == parent.GetChildren()
    assert [c.GetName() for c in children(parent)] == ["B", "A", "C"]


def test_floats_reads_gf_vectors():
    assert floats(Gf.Vec3f(1, 2, 3)) == [1.0, 2.0, 3.0]
    assert floats(Gf.Vec4d(1, 2, 3, 4), 4) == [1.0, 2.0, 3.0, 4.0]


def test_specs_are_none_where_the_layer_has_none():
    layer = Sdf.Layer.CreateAnonymous()
    Sdf.CreatePrimInLayer(layer, "/A/B")

    assert prim_spec(layer, Sdf.Path("/A/B")) is not None
    assert prim_spec(layer, Sdf.Path("/A/C")) is None
    assert attribute_spec(layer, Sdf.Path("/A/B.visibility")) is None


def test_remove_child_spec():
    layer = Sdf.Layer.CreateAnonymous()
    Sdf.CreatePrimInLayer(layer, "/A/B")
    Sdf.CreatePrimInLayer(layer, "/A/C")

    remove_child_spec(layer.GetPrimAtPath("/A"), "B")

    assert prim_spec(layer, Sdf.Path("/A/B")) is None
    assert list(layer.GetPrimAtPath("/A").nameChildren.keys()) == ["C"]
