"""set_material's OmniPBR material, on usd-core: it names its MDL source, which every Kit app with MDL resolves (#30),
and every call sets every surface value (#82). set_physics_properties' physics material: the values a body has now,
and what the material it binds takes from the one it replaces (#105)."""

import pytest
from pxr import Gf, Sdf, Usd, UsdPhysics, UsdShade

from ovmcp.core.material import (
    DYNAMIC,
    MDL_ASSET,
    MDL_NAME,
    PHYSX_DEFAULT,
    RESTITUTION,
    STATIC,
    ensure_material,
    physics_source,
    physics_values,
    set_surface,
    start_from,
)


def _source(shader: UsdShade.Shader) -> tuple[str, str, str]:
    return (
        str(shader.GetImplementationSource()),
        shader.GetSourceAsset("mdl").path,
        str(shader.GetSourceAssetSubIdentifier("mdl")),
    )


def test_a_new_material_names_its_mdl_source():
    stage = Usd.Stage.CreateInMemory()
    mat, shader = ensure_material(stage, "/World/Looks/Cube_Mat")
    assert _source(shader) == ("sourceAsset", MDL_ASSET, MDL_NAME)
    assert shader.GetPath() == Sdf.Path("/World/Looks/Cube_Mat/Shader")
    source, name, _ = mat.GetSurfaceOutput().GetConnectedSource()
    assert (source.GetPath(), name) == (shader.GetPath(), "out")


def test_the_same_material_is_returned_again():
    stage = Usd.Stage.CreateInMemory()
    first = ensure_material(stage, "/World/Looks/Cube_Mat")
    again = ensure_material(stage, "/World/Looks/Cube_Mat")
    assert [x.GetPath() for x in again] == [x.GetPath() for x in first]


def test_a_material_from_before_the_fix_gets_its_source():
    stage = Usd.Stage.CreateInMemory()
    UsdShade.Material.Define(stage, "/World/Looks/Old_Mat")
    UsdShade.Shader.Define(stage, "/World/Looks/Old_Mat/Shader").CreateIdAttr(MDL_NAME)
    _, shader = ensure_material(stage, "/World/Looks/Old_Mat")
    assert _source(shader) == ("sourceAsset", MDL_ASSET, MDL_NAME)


def test_the_users_own_shader_is_left_alone():
    stage = Usd.Stage.CreateInMemory()
    UsdShade.Material.Define(stage, "/World/Looks/Glass")
    own = UsdShade.Shader.Define(stage, "/World/Looks/Glass/Shader")
    own.SetSourceAsset(Sdf.AssetPath("OmniGlass.mdl"), "mdl")
    own.SetSourceAssetSubIdentifier("OmniGlass", "mdl")
    _, shader = ensure_material(stage, "/World/Looks/Glass")
    assert _source(shader) == ("sourceAsset", "OmniGlass.mdl", "OmniGlass")


def _inputs(shader: UsdShade.Shader) -> dict[str, object]:
    return {i.GetBaseName(): i.Get() for i in shader.GetInputs()}


def test_an_opacity_of_1_makes_a_see_through_material_opaque_again():
    # Only an opacity below 1 was written, so a material made see-through stayed so, as the live run showed.
    stage = Usd.Stage.CreateInMemory()
    _, shader = ensure_material(stage, "/World/Looks/Cube_Mat")

    set_surface(shader, (1.0, 0.0, 0.0), 0.5, 0.3, 0.1)
    assert _inputs(shader)["enable_opacity"] is True
    assert _inputs(shader)["opacity_constant"] == pytest.approx(0.5)

    set_surface(shader, (0.0, 1.0, 0.0), 1.0, 0.5, 0.0)
    values = _inputs(shader)
    assert values["enable_opacity"] is False
    assert values["opacity_constant"] == pytest.approx(1.0)
    assert values["reflection_roughness_constant"] == pytest.approx(0.5)
    assert values["metallic_constant"] == pytest.approx(0.0)
    assert values["diffuse_color_constant"] == Gf.Vec3f(0, 1, 0)


# ---- set_physics_properties' physics material (#105) ----


def _physics_material(stage: Usd.Stage, path: str, **values: float) -> Usd.Prim:
    prim = UsdShade.Material.Define(stage, path).GetPrim()
    UsdPhysics.MaterialAPI.Apply(prim)
    for name, value in values.items():
        prim.CreateAttribute(f"physics:{name}", Sdf.ValueTypeNames.Float).Set(value)
    return prim


def _bind(prim: Usd.Prim, material: Usd.Prim, purpose: str = "physics") -> None:
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(
        UsdShade.Material(material), UsdShade.Tokens.weakerThanDescendants, purpose
    )


@pytest.fixture
def physics_stage() -> Usd.Stage:
    stage = Usd.Stage.CreateInMemory()
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdShade.Material.Define(stage, "/World/Looks/Paint")  # a look, without MaterialAPI
    for name in ("Box", "Other"):
        UsdPhysics.CollisionAPI.Apply(stage.DefinePrim(f"/World/{name}", "Cube"))
    return stage


def test_a_body_bound_to_no_physics_material_has_physx_s_default(physics_stage):
    box = physics_stage.GetPrimAtPath("/World/Box")

    assert physics_source(box) is None
    assert physics_values(None) == {STATIC: 0.5, DYNAMIC: 0.5, RESTITUTION: 0.0}
    assert physics_values(None) is not PHYSX_DEFAULT


def test_a_bound_material_s_values_are_read_as_physx_reads_them(physics_stage):
    # Restitution unauthored: PhysX reads USD's 0, as the probe's restitution-only body showed for its friction.
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber", staticFriction=0.9, dynamicFriction=0.8)
    box = physics_stage.GetPrimAtPath("/World/Box")
    _bind(box, rubber)

    assert physics_source(box) == rubber
    assert physics_values(rubber) == pytest.approx({STATIC: 0.9, DYNAMIC: 0.8, RESTITUTION: 0.0})


def test_an_all_purpose_binding_counts_when_there_is_no_physics_one(physics_stage):
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber", staticFriction=0.9)
    box = physics_stage.GetPrimAtPath("/World/Box")
    _bind(box, rubber, purpose="")

    assert physics_source(box) == rubber


def test_a_bound_look_without_material_api_is_no_physics_material(physics_stage):
    box = physics_stage.GetPrimAtPath("/World/Box")
    _bind(box, physics_stage.GetPrimAtPath("/World/Looks/Paint"), purpose="")

    assert physics_source(box) is None


def test_the_physics_scene_s_default_material_stands_in_for_none(physics_stage):
    default = _physics_material(physics_stage, "/World/Mats/Default", staticFriction=0.7, restitution=0.2)
    _bind(physics_stage.GetPrimAtPath("/World/PhysicsScene"), default)

    assert physics_source(physics_stage.GetPrimAtPath("/World/Box")) == default


def test_start_from_copies_the_physics_attributes_and_physx_s_api(physics_stage):
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber", staticFriction=0.9, density=1000.0)
    # PhysxMaterialAPI added by name, as Kit's PhysxSchema adds it; usd-core can't see it through HasAPI.
    rubber.AddAppliedSchema("PhysxMaterialAPI")
    rubber.CreateAttribute("physxMaterial:frictionCombineMode", Sdf.ValueTypeNames.Token).Set("max")
    rubber.CreateAttribute("inputs:look", Sdf.ValueTypeNames.Float).Set(1.0)  # not a physics attribute
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat")

    start_from(own, rubber)

    schemas = own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert "PhysxMaterialAPI" in schemas
    assert own.GetAttribute("physxMaterial:frictionCombineMode").Get() == "max"
    assert own.GetAttribute("physics:density").Get() == pytest.approx(1000.0)
    assert own.GetAttribute("physics:staticFriction").Get() == pytest.approx(0.9)
    assert not own.GetAttribute("inputs:look")


def test_start_from_a_scene_default_copies_it_too(physics_stage):
    default = _physics_material(physics_stage, "/World/Mats/Default", staticFriction=0.7)
    default.AddAppliedSchema("PhysxMaterialAPI")
    default.CreateAttribute("physxMaterial:restitutionCombineMode", Sdf.ValueTypeNames.Token).Set("max")
    _bind(physics_stage.GetPrimAtPath("/World/PhysicsScene"), default)
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat")

    start_from(own, physics_source(physics_stage.GetPrimAtPath("/World/Box")))

    assert own.GetAttribute("physxMaterial:restitutionCombineMode").Get() == "max"


def test_start_from_the_material_itself_changes_nothing(physics_stage):
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat", restitution=0.3)
    before = own.GetStage().GetRootLayer().ExportToString()

    start_from(own, own)

    assert own.GetStage().GetRootLayer().ExportToString() == before


def _held(own: Usd.Prim) -> list[str]:
    return sorted(a.GetName() for a in own.GetAuthoredAttributes() if a.GetName().startswith(("physics:", "physx")))


def test_start_from_keeps_nothing_the_new_source_lacks(physics_stage):
    # A material there already, made for a same-named prim, held a density and a combine mode; its new source,
    # Rubber, has neither: they go, so the copy is exact (review I8).
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat", density=1000.0, restitution=0.3)
    own.AddAppliedSchema("PhysxMaterialAPI")
    own.CreateAttribute("physxMaterial:frictionCombineMode", Sdf.ValueTypeNames.Token).Set("max")
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber", staticFriction=0.9)

    start_from(own, rubber)

    assert _held(own) == ["physics:staticFriction"]
    assert "PhysxMaterialAPI" not in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert "PhysicsMaterialAPI" in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()


def test_start_from_none_leaves_physx_s_default(physics_stage):
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat", density=1000.0, restitution=0.3)

    start_from(own, None)

    assert _held(own) == []


def test_start_from_reads_a_material_a_reference_brings(physics_stage, tmp_path):
    asset = Usd.Stage.CreateNew(str(tmp_path / "asset.usda"))
    mat = _physics_material(asset, "/Asset", staticFriction=0.6)
    mat.AddAppliedSchema("PhysxMaterialAPI")
    mat.CreateAttribute("physxMaterial:frictionCombineMode", Sdf.ValueTypeNames.Token).Set("min")
    asset.SetDefaultPrim(mat)
    asset.GetRootLayer().Save()
    referenced = physics_stage.DefinePrim("/World/Mats/FromAsset")
    referenced.GetReferences().AddReference(str(tmp_path / "asset.usda"))
    own = _physics_material(physics_stage, "/World/PhysicsMaterials/Box_PhysMat")

    start_from(own, referenced)

    assert "PhysxMaterialAPI" in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert own.GetAttribute("physxMaterial:frictionCombineMode").Get() == "min"
    assert physics_values(referenced)[STATIC] == pytest.approx(0.6)
