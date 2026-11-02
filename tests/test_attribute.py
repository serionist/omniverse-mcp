"""set_prim_attribute's core (#151), on usd-core: a value given in JSON converted to the attribute's type, refused when
it doesn't fit, the prim can't take it or another tool owns the name; written where it shows, Kit's own session-layer
prims in the session layer; and a shape's authored extent kept in step with its size, so its box stays right."""

import math

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdShade, Vt

from ovmcp.core.attribute import attribute_refusal, convert, set_attribute, shown, target_layer
from ovmcp.core.bounds import world_bbox


@pytest.fixture
def stage() -> Usd.Stage:
    return Usd.Stage.CreateInMemory()


def _custom(stage: Usd.Stage, type_name: Sdf.ValueTypeName) -> Usd.Attribute:
    return stage.DefinePrim("/World/Thing").CreateAttribute("my:value", type_name)


def _kit_sphere(stage: Usd.Stage, path: str = "/World/Ball", radius: float = 1.0) -> Usd.Prim:
    """A Sphere as Kit's Create menu makes one: its radius and its extent authored side by side (F14)."""
    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(radius)
    sphere.CreateExtentAttr([(-radius, -radius, -radius), (radius, radius, radius)])
    return sphere.GetPrim()


def _size(prim: Usd.Prim) -> list[float]:
    _, dims, _ = world_bbox(prim)
    return [round(float(d), 4) for d in dims]


# ----- the conversion, row by row -----


@pytest.mark.parametrize(
    ("type_name", "given", "stored"),
    [
        (Sdf.ValueTypeNames.Bool, True, True),
        (Sdf.ValueTypeNames.Int, 3, 3),
        (Sdf.ValueTypeNames.Int, 3.0, 3),
        (Sdf.ValueTypeNames.UChar, 255, 255),
        (Sdf.ValueTypeNames.UInt, 7, 7),
        (Sdf.ValueTypeNames.Int64, 2**40, 2**40),
        (Sdf.ValueTypeNames.UInt64, 2**63, 2**63),
        (Sdf.ValueTypeNames.Half, 1.5, 1.5),
        (Sdf.ValueTypeNames.Float, 2.5, 2.5),
        (Sdf.ValueTypeNames.Float, 4, 4.0),
        (Sdf.ValueTypeNames.Double, 1e300, 1e300),
        (Sdf.ValueTypeNames.String, "hello", "hello"),
        (Sdf.ValueTypeNames.Token, "orthographic", "orthographic"),
        (Sdf.ValueTypeNames.Float3, [1, 2, 3], Gf.Vec3f(1, 2, 3)),
        (Sdf.ValueTypeNames.Color3f, [1, 0, 0], Gf.Vec3f(1, 0, 0)),
        (Sdf.ValueTypeNames.Double2, [0.5, 1e300], Gf.Vec2d(0.5, 1e300)),
        (Sdf.ValueTypeNames.Half3, [1, 2, 3], Gf.Vec3h(1, 2, 3)),
        (Sdf.ValueTypeNames.Int2, [1, -2], Gf.Vec2i(1, -2)),
        (Sdf.ValueTypeNames.TexCoord2f, [0.25, 0.75], Gf.Vec2f(0.25, 0.75)),
        (Sdf.ValueTypeNames.Quatf, [1, 0, 0, 0], Gf.Quatf(1, Gf.Vec3f(0, 0, 0))),
        (Sdf.ValueTypeNames.Quatd, [0, 0, 1, 0], Gf.Quatd(0, Gf.Vec3d(0, 1, 0))),
        (Sdf.ValueTypeNames.FloatArray, [1, 2], Vt.FloatArray([1, 2])),
        (Sdf.ValueTypeNames.Color3fArray, [[1, 0, 0], [0, 1, 0]], Vt.Vec3fArray([(1, 0, 0), (0, 1, 0)])),
        (Sdf.ValueTypeNames.Color3fArray, [], Vt.Vec3fArray()),
        (Sdf.ValueTypeNames.TokenArray, ["a", "b"], Vt.TokenArray(["a", "b"])),
    ],
)
def test_a_value_is_written_in_the_attribute_s_type(stage, type_name, given, stored):
    attr = _custom(stage, type_name)

    written = set_attribute(attr.GetPrim(), "my:value", given)

    assert attr.Get() == stored
    assert written.after == stored
    assert written.type_name == str(type_name)


def test_a_time_code_and_an_asset_take_a_number_and_a_string(stage):
    timecode = stage.DefinePrim("/World/A").CreateAttribute("my:time", Sdf.ValueTypeNames.TimeCode)
    asset = stage.DefinePrim("/World/B").CreateAttribute("my:file", Sdf.ValueTypeNames.Asset)

    set_attribute(timecode.GetPrim(), "my:time", 2.5)
    set_attribute(asset.GetPrim(), "my:file", "./textures/wood.png")

    assert float(timecode.Get()) == 2.5
    assert asset.Get().path == "./textures/wood.png"


@pytest.mark.parametrize(
    ("type_name", "given", "says"),
    [
        (Sdf.ValueTypeNames.Bool, 1, "takes true or false"),
        (Sdf.ValueTypeNames.Int, True, "takes a whole number"),
        (Sdf.ValueTypeNames.Int, 2.5, "takes a whole number"),
        (Sdf.ValueTypeNames.Int, 2**31, "holds whole numbers from"),
        (Sdf.ValueTypeNames.UChar, 300, "holds whole numbers from 0 to 255"),
        (Sdf.ValueTypeNames.UInt, -1, "holds whole numbers from 0"),
        (Sdf.ValueTypeNames.Float, True, "takes a number"),
        (Sdf.ValueTypeNames.Float, float("nan"), "takes a finite number"),
        (Sdf.ValueTypeNames.Float, float("inf"), "takes a finite number"),
        (Sdf.ValueTypeNames.Float, 1e300, "holds numbers up to"),  # USD would store infinity
        (Sdf.ValueTypeNames.Half, 1e6, "holds numbers up to 65504"),
        (Sdf.ValueTypeNames.Double, "1.5", "takes a number"),
        (Sdf.ValueTypeNames.String, 3, "takes a string"),
        (Sdf.ValueTypeNames.Token, 3, "takes a string"),
        (Sdf.ValueTypeNames.Asset, 3, "takes a string"),
        (Sdf.ValueTypeNames.Float3, [1, 2], "takes a list of 3 numbers"),
        (Sdf.ValueTypeNames.Float3, 1.0, "takes a list of 3 numbers"),
        (Sdf.ValueTypeNames.Float3, [1, float("nan"), 0], "takes a finite number"),
        (Sdf.ValueTypeNames.Half3, [1e6, 0, 0], "holds numbers up to 65504"),
        (Sdf.ValueTypeNames.Int2, [1.5, 2], "takes a whole number"),
        (Sdf.ValueTypeNames.Quatf, [1, 0, 0], r"quaternion as \[w, x, y, z\]"),
        (Sdf.ValueTypeNames.Color3fArray, [1, 0, 0], "takes a list of 3 numbers"),
        (Sdf.ValueTypeNames.Color3fArray, [[1, float("nan"), 0]], "takes a finite number"),
        (Sdf.ValueTypeNames.Color3fArray, (1, 0, 0), "takes a list"),
        (Sdf.ValueTypeNames.FloatArray, ["a"], "takes a number"),
        (Sdf.ValueTypeNames.Matrix4d, [[1, 0, 0, 0]] * 4, "which this tool doesn't set"),
        (Sdf.ValueTypeNames.Opaque, 1, "which this tool doesn't set"),
    ],
)
def test_a_value_that_doesn_t_fit_is_refused_with_nothing_written(stage, type_name, given, says):
    attr = _custom(stage, type_name)
    before = stage.GetRootLayer().ExportToString()

    with pytest.raises(ValueError, match=says):
        set_attribute(attr.GetPrim(), "my:value", given)

    assert stage.GetRootLayer().ExportToString() == before


def test_convert_names_the_attribute_and_its_type(stage):
    attr = _custom(stage, Sdf.ValueTypeNames.Float)

    with pytest.raises(ValueError, match=r"my:value \(float\) takes a number, got 'x'"):
        convert(attr, "x")


def test_a_token_outside_its_allowed_ones_is_written_with_a_note(stage):
    camera = UsdGeom.Camera.Define(stage, "/World/Cam").GetPrim()

    written = set_attribute(camera, "projection", "fisheye")

    assert camera.GetAttribute("projection").Get() == "fisheye"
    assert written.note == (
        "fisheye isn't among projection's allowed tokens (perspective, orthographic); written as given"
    )
    assert set_attribute(camera, "projection", "orthographic").note == ""


def test_the_value_is_read_back_as_usd_stored_it(stage):
    light = UsdLux.DistantLight.Define(stage, "/World/Sun").GetPrim()

    written = set_attribute(light, "inputs:intensity", 0.1)

    assert written.before == 50000  # UsdLux's fallback for a DistantLight (F1)
    assert written.after == light.GetAttribute("inputs:intensity").Get()
    assert written.after != 0.1 and math.isclose(written.after, 0.1, rel_tol=1e-6)  # a float rounds
    assert written.layer.identifier == stage.GetRootLayer().identifier


# ----- what is refused -----


def test_an_inactive_prim_is_refused(stage):
    prim = UsdLux.DistantLight.Define(stage, "/World/Sun").GetPrim()
    prim.SetActive(False)

    assert (
        attribute_refusal(prim, "inputs:intensity")
        == "/World/Sun is inactive, so a value set on it wouldn't show: activate it first"
    )


def _instanced(stage: Usd.Stage) -> Usd.Prim:
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    UsdGeom.Xform.Define(held, "/Lamp")
    UsdLux.SphereLight.Define(held, "/Lamp/Bulb")
    for name in ("A", "B"):
        instance = stage.DefinePrim(f"/World/{name}")
        instance.GetReferences().AddReference(asset.identifier, "/Lamp")
        instance.SetInstanceable(True)
    return stage.GetPrimAtPath("/World/A")


def test_a_prim_inside_an_instance_is_refused_naming_the_instance(stage):
    _instanced(stage)

    why = attribute_refusal(stage.GetPrimAtPath("/World/A/Bulb"), "inputs:intensity")

    assert why is not None
    assert why.startswith("/World/A/Bulb is inside the instance /World/A")
    assert "turn off /World/A's instanceable" in why


def test_a_prototype_s_prim_is_refused_rather_than_raising(stage):
    # USD raises on a write in a prototype, which would come back as a traceback (round 1, P3).
    _instanced(stage)
    prototype = stage.GetPrototypes()[0]
    bulb = prototype.GetChildren()[0]

    with pytest.raises(ValueError, match="is in an instance prototype"):
        set_attribute(bulb, "inputs:intensity", 5)


@pytest.mark.parametrize(
    ("name", "says"),
    [
        ("", "name must be an attribute's name"),
        ("bad name", "name must be an attribute's name"),
        ("material:binding", "is a relationship, not an attribute: set_material binds a prim's material"),
        ("xformOp:translate", "isn't set here: set_prim_transform"),
        ("xformOpOrder", "isn't set here: set_prim_transform"),
        ("visibility", "isn't set here: set_visibility"),
    ],
)
def test_a_name_another_tool_owns_or_that_isn_t_an_attribute_is_refused(stage, name, says):
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.AddTranslateOp().Set(Gf.Vec3d(1, 0, 0))
    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(UsdShade.Material.Define(stage, "/World/Looks/Red"))
    before = stage.GetRootLayer().ExportToString()

    with pytest.raises(ValueError, match=says):
        set_attribute(cube.GetPrim(), name, 1)

    assert stage.GetRootLayer().ExportToString() == before


@pytest.mark.parametrize(("asked", "first"), [("intensity", "inputs:intensity"), ("colour", "inputs:color")])
def test_a_name_the_prim_lacks_gives_its_closest_names_first(stage, asked, first):
    # A DistantLight's first 12 names in order are ten collection:* ones (round 1, I1; round 2, I5).
    light = UsdLux.DistantLight.Define(stage, "/World/Sun").GetPrim()

    why = attribute_refusal(light, asked)

    assert why is not None
    assert why.startswith(f"/World/Sun has no attribute {asked}; its attributes, closest first: {first}, ")
    assert len(why.split(": ", 1)[1].split(", ")) == 12


# ----- where it is written -----


def test_a_write_a_stronger_layer_would_hide_is_refused(stage):
    light = UsdLux.DistantLight.Define(stage, "/World/Sun")
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        light.CreateIntensityAttr(800.0)
    # The session layer holds only a value, the root defines the prim: the edit target, the root, is written to.
    assert target_layer(light.GetPrim()).identifier == stage.GetRootLayer().identifier

    with pytest.raises(ValueError, match="which outranks the stage's root layer"):
        set_attribute(light.GetPrim(), "inputs:intensity", 3000)
    assert light.GetIntensityAttr().Get() == 800.0


def test_an_animated_attribute_is_refused(stage):
    light = UsdLux.DistantLight.Define(stage, "/World/Sun")
    light.CreateIntensityAttr().Set(100.0, 1.0)

    with pytest.raises(ValueError, match="is animated in the stage's root layer"):
        set_attribute(light.GetPrim(), "inputs:intensity", 3000)


def test_kit_s_own_camera_is_written_in_the_session_layer(stage):
    # Kit's cameras live in the session layer: a root write would be hidden there (round 1, P2).
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        camera = UsdGeom.Camera.Define(stage, "/OmniverseKit_Persp")
        camera.CreateFocalLengthAttr(18.0)

    written = set_attribute(camera.GetPrim(), "focalLength", 35)

    assert written.layer.identifier == stage.GetSessionLayer().identifier
    assert camera.GetFocalLengthAttr().Get() == 35.0
    assert not stage.GetRootLayer().GetPrimAtPath("/OmniverseKit_Persp")


def test_a_light_rig_s_light_is_written_in_the_session_layer_not_the_user_s_file(stage):
    # A rig is an over in the session layer that references the rig's file, whose prims define the lights (round 2, R2).
    rig = Sdf.Layer.CreateAnonymous("rig.usda")
    rig_stage = Usd.Stage.Open(rig)
    UsdGeom.Xform.Define(rig_stage, "/Rig")
    UsdLux.DistantLight.Define(rig_stage, "/Rig/Key")
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        stage.OverridePrim("/OmniKit_Viewport_LightRig").GetReferences().AddReference(rig.identifier, "/Rig")
    key = stage.GetPrimAtPath("/OmniKit_Viewport_LightRig/Key")

    written = set_attribute(key, "inputs:intensity", 1200)

    assert written.layer.identifier == stage.GetSessionLayer().identifier
    assert key.GetAttribute("inputs:intensity").Get() == 1200
    assert not stage.GetRootLayer().GetPrimAtPath("/OmniKit_Viewport_LightRig")


# ----- the extent -----


def test_a_size_change_moves_an_authored_extent_so_the_box_follows(stage):
    # Kit authors extent beside radius; left stale, get_prim_bounds would give the old size (round 1, P1).
    ball = _kit_sphere(stage)

    written = set_attribute(ball, "radius", 5)

    assert _size(ball) == [10.0, 10.0, 10.0]
    assert written.extent == Vt.Vec3fArray([(-5, -5, -5), (5, 5, 5)])


def test_turning_a_cylinder_moves_its_extent_too(stage):
    cylinder = UsdGeom.Cylinder.Define(stage, "/World/Can")
    cylinder.CreateHeightAttr(6.0)
    cylinder.CreateRadiusAttr(1.0)
    cylinder.CreateAxisAttr("Z")
    cylinder.CreateExtentAttr([(-1, -1, -3), (1, 1, 3)])

    set_attribute(cylinder.GetPrim(), "axis", "X")

    assert _size(cylinder.GetPrim()) == [6.0, 2.0, 2.0]


def test_a_shape_without_an_authored_extent_keeps_none(stage):
    # USD computes the box from the size itself; nothing is authored for it.
    sphere = UsdGeom.Sphere.Define(stage, "/World/Ball")

    written = set_attribute(sphere.GetPrim(), "radius", 3)

    assert written.extent is None
    assert not sphere.GetExtentAttr().HasAuthoredValue()
    assert _size(sphere.GetPrim()) == [6.0, 6.0, 6.0]


def test_a_mesh_with_no_points_keeps_its_extent(stage):
    mesh = UsdGeom.Mesh.Define(stage, "/World/Empty")
    mesh.CreateExtentAttr([(-1, -1, -1), (1, 1, 1)])

    written = set_attribute(mesh.GetPrim(), "doubleSided", True)

    assert written.extent is None
    assert mesh.GetExtentAttr().Get() == Vt.Vec3fArray([(-1, -1, -1), (1, 1, 1)])


def test_a_size_change_whose_extent_a_stronger_layer_holds_is_refused_and_undone_exactly(stage):
    ball = _kit_sphere(stage)
    with Usd.EditContext(stage, stage.GetSessionLayer()):
        UsdGeom.Sphere(ball).GetExtentAttr().Set([(-1, -1, -1), (1, 1, 1)])
    before = stage.GetRootLayer().ExportToString()

    with pytest.raises(ValueError, match="its extent can't follow"):
        set_attribute(ball, "radius", 5)

    assert stage.GetRootLayer().ExportToString() == before
    assert UsdGeom.Sphere(ball).GetRadiusAttr().Get() == 1.0


def test_an_undone_write_drops_the_overs_it_made(stage):
    # The write made overs in a layer that held nothing of the prim; undone, they go too (round 2, R1).
    asset = Sdf.Layer.CreateAnonymous("asset.usda")
    held = Usd.Stage.Open(asset)
    _kit_sphere(held, "/Ball")
    UsdGeom.Sphere(held.GetPrimAtPath("/Ball")).GetExtentAttr().Set([(-1, -1, -1), (1, 1, 1)], 1.0)
    ball = stage.DefinePrim("/World/Ball")
    ball.GetReferences().AddReference(asset.identifier, "/Ball")
    sub = Sdf.Layer.CreateAnonymous("sub.usda")
    stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    before = sub.ExportToString()

    with pytest.raises(ValueError, match="its extent can't follow"):
        set_attribute(ball, "radius", 5, layer=sub)

    assert sub.ExportToString() == before


def test_a_colour_on_a_mesh_whose_extent_is_animated_is_set(stage):
    # The colour leaves the box as it was, so the animated extent never comes into it (round 2, R1).
    asset = Sdf.Layer.CreateAnonymous("cache.usda")
    held = Usd.Stage.Open(asset)
    mesh = UsdGeom.Mesh.Define(held, "/Cache")
    for t in (1.0, 2.0):
        mesh.CreatePointsAttr().Set([(0, 0, 0), (t, 0, 0), (0, t, 0)], t)
        mesh.CreateExtentAttr().Set([(0, 0, 0), (t, t, 0)], t)
    mesh.CreateFaceVertexCountsAttr([3])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2])
    prim = stage.DefinePrim("/World/Cache")
    prim.GetReferences().AddReference(asset.identifier, "/Cache")

    set_attribute(prim, "primvars:displayColor", [[1, 0, 0]])

    assert UsdGeom.Mesh(prim).GetDisplayColorAttr().Get() == Vt.Vec3fArray([(1, 0, 0)])


# ----- the answer -----


def test_an_array_is_shown_as_its_first_8_values_and_its_length():
    # A Vt array would come back whole: 100,000 colours are 1.5 million characters (round 2, R3).
    colours = Vt.Vec3fArray([(1, 0, 0)] * 100_000)

    text = shown(colours)

    assert text.endswith(" ... (100000 items)")
    assert text.count("(1.0000, 0.0000, 0.0000)") == 8
    assert len(text) < 300


def test_shown_writes_values_as_get_prim_properties_does():
    assert shown(50000.0) == "50000"
    assert shown(Gf.Vec3f(1, 0, 0)) == "1.0000, 0.0000, 0.0000"
    assert shown(Gf.Vec2i(1, -2)) == "1, -2"
    assert shown(Vt.FloatArray()) == "[]"
    assert shown(Vt.TokenArray(["a", "b"])) == "a, b"
