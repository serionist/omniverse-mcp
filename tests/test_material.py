"""set_material's OmniPBR material, on usd-core: it names its MDL source, which every Kit app with MDL resolves (#30),
and every call sets every surface value (#82). set_physics_properties' physics material: the values a body has now,
and what the material it binds takes from the one it replaces (#105); the prim's own, a child of the prim, its
refusals, the other prims a write changes, and the older shared material a call deletes (#113)."""

import pytest
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

from ovmcp.core.material import (
    DYNAMIC,
    MDL_ASSET,
    MDL_NAME,
    PHYSX_DEFAULT,
    RESTITUTION,
    STATIC,
    also_changed,
    drop_old_material,
    ensure_material,
    material_refusal,
    own_physics_material,
    physics_material,
    physics_material_path,
    physics_source,
    physics_values,
    set_surface,
    start_from,
    walk_bindings,
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
    own = _physics_material(physics_stage, "/World/Box/PhysMat")

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
    own = _physics_material(physics_stage, "/World/Box/PhysMat")

    start_from(own, physics_source(physics_stage.GetPrimAtPath("/World/Box")))

    assert own.GetAttribute("physxMaterial:restitutionCombineMode").Get() == "max"


def test_start_from_the_material_itself_changes_nothing(physics_stage):
    own = _physics_material(physics_stage, "/World/Box/PhysMat", restitution=0.3)
    before = own.GetStage().GetRootLayer().ExportToString()

    start_from(own, own)

    assert own.GetStage().GetRootLayer().ExportToString() == before


def _held(own: Usd.Prim) -> list[str]:
    return sorted(a.GetName() for a in own.GetAuthoredAttributes() if a.GetName().startswith(("physics:", "physx")))


def test_start_from_keeps_nothing_the_new_source_lacks(physics_stage):
    # A material there already, made by an older extension, held a density and a combine mode; its new source,
    # Rubber, has neither: they go, so the copy is exact (review I8).
    own = _physics_material(physics_stage, "/World/Box/PhysMat", density=1000.0, restitution=0.3)
    own.AddAppliedSchema("PhysxMaterialAPI")
    own.CreateAttribute("physxMaterial:frictionCombineMode", Sdf.ValueTypeNames.Token).Set("max")
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber", staticFriction=0.9)

    start_from(own, rubber)

    assert _held(own) == ["physics:staticFriction"]
    assert "PhysxMaterialAPI" not in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert "PhysicsMaterialAPI" in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()


def test_start_from_none_leaves_physx_s_default(physics_stage):
    own = _physics_material(physics_stage, "/World/Box/PhysMat", density=1000.0, restitution=0.3)

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
    own = _physics_material(physics_stage, "/World/Box/PhysMat")

    start_from(own, referenced)

    assert "PhysxMaterialAPI" in own.GetMetadata("apiSchemas").GetAddedOrExplicitItems()
    assert own.GetAttribute("physxMaterial:frictionCombineMode").Get() == "min"
    assert physics_values(referenced)[STATIC] == pytest.approx(0.6)


# ---- the prim's own physics material (#113) ----


@pytest.mark.parametrize(
    ("prim", "material"),
    [
        ("/World/Franka_1/panda_leftfinger", "/World/Franka_1/panda_leftfinger/PhysMat"),
        ("/World/Cube", "/World/Cube/PhysMat"),
        ("/Box", "/Box/PhysMat"),
        ("/World/Würfel", "/World/Würfel/PhysMat"),
    ],
)
def test_a_prim_s_own_material_is_its_child(prim: str, material: str):
    assert physics_material_path(Sdf.Path(prim)) == Sdf.Path(material)


def test_two_prims_of_one_name_get_two_materials():
    # The issue's case: both fingers bound panda_leftfinger_PhysMat.
    first, second = (physics_material_path(Sdf.Path(f"/World/Franka_{n}/panda_leftfinger")) for n in (1, 2))
    assert first != second


def test_own_material_is_made_with_material_api(physics_stage):
    box = physics_stage.GetPrimAtPath("/World/Box")

    own = own_physics_material(physics_stage, box)

    assert own.GetPath() == Sdf.Path("/World/Box/PhysMat")
    assert own.GetTypeName() == "Material"
    assert own.HasAPI("PhysicsMaterialAPI")


def test_own_material_there_is_kept_with_its_values(physics_stage):
    there = _physics_material(physics_stage, "/World/Box/PhysMat", staticFriction=0.4)

    own = own_physics_material(physics_stage, physics_stage.GetPrimAtPath("/World/Box"))

    assert own == there
    assert own.GetAttribute("physics:staticFriction").Get() == pytest.approx(0.4)


def test_a_material_there_without_material_api_gets_it(physics_stage):
    UsdShade.Material.Define(physics_stage, "/World/Box/PhysMat")

    own = own_physics_material(physics_stage, physics_stage.GetPrimAtPath("/World/Box"))

    assert own.HasAPI("PhysicsMaterialAPI")


def test_an_over_alone_is_defined_as_the_material(physics_stage):
    physics_stage.OverridePrim("/World/Box/PhysMat")
    box = physics_stage.GetPrimAtPath("/World/Box")

    assert material_refusal(box) is None
    own = own_physics_material(physics_stage, box)

    assert own.IsDefined()
    assert own.GetTypeName() == "Material"


def _instances(stage: Usd.Stage) -> None:
    """An instanceable prop twice under one parent, as a shelf of crates, and a prim flagged instanceable with no
    reference or payload, which is no instance."""
    UsdGeom.Cube.Define(stage, "/Props/Crate/Box")
    for name in ("CrateA", "CrateB"):
        crate = stage.DefinePrim(f"/World/Shelf/{name}", "Xform")
        crate.GetReferences().AddInternalReference("/Props/Crate")
        crate.SetInstanceable(True)
    stage.DefinePrim("/World/Flagged", "Xform").SetInstanceable(True)


def test_an_instance_is_refused_and_the_error_says_what_its_parent_s_call_reaches(physics_stage):
    _instances(physics_stage)
    crate = physics_stage.GetPrimAtPath("/World/Shelf/CrateA")
    before = physics_stage.GetRootLayer().ExportToString()

    why = material_refusal(crate)
    with pytest.raises(ValueError, match="is an instance"):
        own_physics_material(physics_stage, crate)

    assert why is not None
    assert why.startswith("/World/Shelf/CrateA is an instance, which USD lets hold no prim of its own")
    # Both crates take the parent's material, so the text doesn't send the agent to the parent as a fix (P4).
    assert "every prim under /World/Shelf that has none of its own, not only to this one" in why
    assert physics_stage.GetRootLayer().ExportToString() == before


def test_an_instance_at_the_root_has_no_parent_to_name(physics_stage):
    _instances(physics_stage)
    crate = physics_stage.DefinePrim("/Crate", "Xform")
    crate.GetReferences().AddInternalReference("/Props/Crate")
    crate.SetInstanceable(True)

    why = material_refusal(crate)

    assert why is not None
    assert "parent" not in why


def test_a_prim_inside_an_instance_is_refused_naming_its_instance(physics_stage):
    _instances(physics_stage)
    proxy = physics_stage.GetPrimAtPath("/World/Shelf/CrateA/Box")

    why = material_refusal(proxy)

    assert why is not None
    assert why.startswith(
        "/World/Shelf/CrateA/Box is inside the instance /World/Shelf/CrateA, whose prims can't be changed one by one."
    )


def test_a_prim_flagged_instanceable_without_an_arc_takes_its_material(physics_stage):
    # The flag alone makes no instance, and USD lets it hold a child (I5).
    _instances(physics_stage)
    flagged = physics_stage.GetPrimAtPath("/World/Flagged")

    assert material_refusal(flagged) is None
    assert own_physics_material(physics_stage, flagged).GetPath() == Sdf.Path("/World/Flagged/PhysMat")


def test_a_child_physmat_that_is_no_material_is_refused(physics_stage):
    physics_stage.DefinePrim("/World/Box/PhysMat", "Xform")

    why = material_refusal(physics_stage.GetPrimAtPath("/World/Box"))

    assert why is not None
    assert why.startswith("/World/Box/PhysMat is a Xform, not a Material")


# ---- the walk, and the other prims a write changes (#113, Q3) ----


def _call(stage: Usd.Stage, path: str, friction: float) -> tuple[Usd.Prim, Usd.Prim | None]:
    """What set_physics_properties does to a prim's material, with restitution 0: its own, starting from the body's,
    the three values, the binding. The prim's own and the material bound before."""
    prim = stage.GetPrimAtPath(path)
    before = physics_material(prim)
    own = own_physics_material(stage, prim)
    start_from(own, physics_source(prim))
    api = UsdPhysics.MaterialAPI(own)
    api.CreateStaticFrictionAttr().Set(friction)
    api.CreateDynamicFrictionAttr().Set(friction)
    api.CreateRestitutionAttr().Set(0.0)
    _bind(prim, own)
    return own, before


def _changed(stage: Usd.Stage, path: str, friction: float) -> list[str]:
    own, _ = _call(stage, path, friction)
    return [str(p) for p in also_changed(stage, stage.GetPrimAtPath(path), own, walk_bindings(stage))]


def _envs(stage: Usd.Stage, clones: int = 2) -> None:
    """Isaac Sim's cloner with copy_from_source=False: env_1 on inherit from env_0, whose link has its material."""
    UsdGeom.Cube.Define(stage, "/World/envs/env_0/Robot/link")
    for e in range(1, clones + 1):
        spec = Sdf.CreatePrimInLayer(stage.GetRootLayer(), f"/World/envs/env_{e}")
        spec.specifier = Sdf.SpecifierDef
        spec.inheritPathList.Prepend("/World/envs/env_0")


def test_the_walk_reads_the_all_purpose_binding_and_the_physics_one(physics_stage):
    rubber = _physics_material(physics_stage, "/World/Mats/Rubber")
    _bind(physics_stage.GetPrimAtPath("/World/Box"), rubber, purpose="")
    _bind(physics_stage.GetPrimAtPath("/World/Other"), rubber)

    found = walk_bindings(physics_stage)

    assert sorted(map(str, found.binders[rubber.GetPath()])) == ["/World/Box", "/World/Other"]
    assert found.unseen is None


def test_the_walk_notes_an_inactive_prim(physics_stage):
    physics_stage.GetPrimAtPath("/World/Other").SetActive(False)

    assert walk_bindings(physics_stage).unseen == "/World/Other is inactive, so a prim under it could bind it"


def test_the_walk_notes_an_unloaded_payload(physics_stage):
    asset = Usd.Stage.CreateInMemory("asset.usda")
    UsdGeom.Cube.Define(asset, "/Root/Box")
    asset.SetDefaultPrim(asset.GetPrimAtPath("/Root"))
    env = physics_stage.DefinePrim("/World/Env")
    env.GetPayloads().AddPayload(asset.GetRootLayer().identifier)
    physics_stage.Unload("/World/Env")

    assert (
        walk_bindings(physics_stage).unseen == "the payload of /World/Env isn't loaded, so a prim in it could bind it"
    )


def test_a_copy_binds_its_own_and_is_never_named(physics_stage):
    # clone_prim's CopySpec maps a binding inside the copied tree to the copy.
    _call(physics_stage, "/World/Box", 0.9)
    layer = physics_stage.GetRootLayer()
    Sdf.CopySpec(layer, "/World/Box", layer, "/World/Box_01")

    assert _changed(physics_stage, "/World/Box", 0.1) == []
    copy = physics_stage.GetPrimAtPath("/World/Box_01/PhysMat")
    assert copy.GetAttribute("physics:staticFriction").Get() == pytest.approx(0.9)


def test_an_inheriting_clone_is_named_until_a_call_gives_it_its_own(physics_stage):
    _envs(physics_stage)
    _call(physics_stage, "/World/envs/env_0/Robot/link", 0.9)

    assert _changed(physics_stage, "/World/envs/env_0/Robot/link", 0.8) == [
        "/World/envs/env_1/Robot/link",
        "/World/envs/env_2/Robot/link",
    ]
    # A call on the clone writes its own three values, and leaves its source's as they were.
    assert _changed(physics_stage, "/World/envs/env_1/Robot/link", 0.2) == []
    source = physics_stage.GetPrimAtPath("/World/envs/env_0/Robot/link/PhysMat")
    assert source.GetAttribute("physics:staticFriction").Get() == pytest.approx(0.8)
    assert _changed(physics_stage, "/World/envs/env_0/Robot/link", 0.7) == ["/World/envs/env_2/Robot/link"]


def test_a_clone_under_a_spec_without_a_value_is_still_named(physics_stage):
    # A spec that declares a value it doesn't hold sits above the source's in the clone's property stack.
    _envs(physics_stage, clones=1)
    _call(physics_stage, "/World/envs/env_0/Robot/link", 0.9)
    over = Sdf.CreatePrimInLayer(physics_stage.GetRootLayer(), "/World/envs/env_1/Robot/link/PhysMat")
    for name in PHYSX_DEFAULT:
        Sdf.AttributeSpec(over, name, Sdf.ValueTypeNames.Float)

    assert _changed(physics_stage, "/World/envs/env_0/Robot/link", 0.5) == ["/World/envs/env_1/Robot/link"]


def test_a_prim_bound_by_hand_is_named_and_a_descendant_or_a_class_is_not(physics_stage):
    own, _ = _call(physics_stage, "/World/Box", 0.9)
    _bind(physics_stage.GetPrimAtPath("/World/Other"), own)
    _bind(UsdGeom.Cube.Define(physics_stage, "/World/Box/Lid").GetPrim(), own)
    _bind(physics_stage.CreateClassPrim("/_Template"), own)

    assert _changed(physics_stage, "/World/Box", 0.3) == ["/World/Other"]


# ---- the older shared material a call moves the prim off (#113, Q4) ----

OLD = "/World/PhysicsMaterials/Box_PhysMat"


@pytest.fixture
def old_stage(physics_stage) -> Usd.Stage:
    """/World/Box bound to the material an extension of 0.3.0 or older gave it, Material.Define's typeless folder
    above it."""
    _bind(physics_stage.GetPrimAtPath("/World/Box"), _physics_material(physics_stage, OLD, staticFriction=0.7))
    return physics_stage


def _drop(stage: Usd.Stage, path: str = "/World/Box") -> dict[str, object] | None:
    _, before = _call(stage, path, 0.3)
    return drop_old_material(stage, stage.GetPrimAtPath(path), before, walk_bindings(stage))


def test_the_material_the_call_moved_the_prim_off_is_deleted_with_its_empty_folder(old_stage):
    assert _drop(old_stage) == {"path": OLD, "deleted": [OLD, "/World/PhysicsMaterials"]}

    assert not old_stage.GetPrimAtPath("/World/PhysicsMaterials")
    own = old_stage.GetPrimAtPath("/World/Box/PhysMat")
    assert own.GetAttribute("physics:staticFriction").Get() == pytest.approx(0.3)


def test_the_folder_stays_while_it_holds_another_material(old_stage):
    _physics_material(old_stage, "/World/PhysicsMaterials/Crate_PhysMat")

    assert _drop(old_stage) == {"path": OLD, "deleted": [OLD]}
    assert old_stage.GetPrimAtPath("/World/PhysicsMaterials/Crate_PhysMat")


@pytest.mark.parametrize(
    ("kind", "deleted"), [("Scope", [OLD, "/World/PhysicsMaterials"]), ("Xform", [OLD])], ids=["Scope", "Xform"]
)
def test_a_scope_folder_goes_but_one_of_another_type_stays(old_stage, kind: str, deleted: list[str]):
    old_stage.GetPrimAtPath("/World/PhysicsMaterials").SetTypeName(kind)

    assert _drop(old_stage) == {"path": OLD, "deleted": deleted}


def test_the_material_stays_while_another_prim_binds_it(old_stage):
    _bind(old_stage.GetPrimAtPath("/World/Other"), old_stage.GetPrimAtPath(OLD))

    assert _drop(old_stage) == {"path": OLD, "kept": "1 prim still binds it: /World/Other"}
    assert old_stage.GetPrimAtPath(OLD).GetAttribute("physics:staticFriction").Get() == pytest.approx(0.7)


def test_the_material_stays_while_a_material_composed_from_it_is_bound(old_stage):
    mine = old_stage.DefinePrim("/World/Mats/Mine")
    mine.GetInherits().AddInherit(OLD)
    _bind(old_stage.GetPrimAtPath("/World/Other"), mine)

    assert _drop(old_stage) == {"path": OLD, "kept": "1 prim still binds it: /World/Other"}


def test_the_material_stays_while_another_layer_holds_it(old_stage):
    sub = Sdf.Layer.CreateAnonymous("sub.usda")
    old_stage.GetRootLayer().subLayerPaths.append(sub.identifier)
    Sdf.CreatePrimInLayer(sub, OLD)

    r = _drop(old_stage)

    assert r is not None
    assert str(r["kept"]).startswith("another layer holds it too: ")
    assert old_stage.GetPrimAtPath(OLD)


def test_an_inactive_prim_keeps_the_material(old_stage):
    old_stage.GetPrimAtPath("/World/Other").SetActive(False)

    assert _drop(old_stage) == {
        "path": OLD,
        "kept": "/World/Other is inactive, so a prim under it could bind it",
    }


def test_an_unloaded_payload_keeps_the_material(old_stage):
    asset = Usd.Stage.CreateInMemory("asset.usda")
    UsdGeom.Cube.Define(asset, "/Root/Box")
    asset.SetDefaultPrim(asset.GetPrimAtPath("/Root"))
    env = old_stage.DefinePrim("/World/Env")
    env.GetPayloads().AddPayload(asset.GetRootLayer().identifier)
    old_stage.Unload("/World/Env")

    r = _drop(old_stage)

    assert r == {"path": OLD, "kept": "the payload of /World/Env isn't loaded, so a prim in it could bind it"}


def test_a_user_s_own_material_of_that_name_elsewhere_is_never_touched(physics_stage):
    mine = _physics_material(physics_stage, "/World/Mats/Box_PhysMat", staticFriction=0.7)
    _bind(physics_stage.GetPrimAtPath("/World/Box"), mine)

    assert _drop(physics_stage) is None
    assert physics_stage.GetPrimAtPath("/World/Mats/Box_PhysMat")


def test_an_older_material_of_another_prim_s_name_is_never_touched(physics_stage):
    # Bound to Box by hand, but named for Other: not the one an older extension gave Box.
    theirs = _physics_material(physics_stage, "/World/PhysicsMaterials/Other_PhysMat")
    _bind(physics_stage.GetPrimAtPath("/World/Box"), theirs)

    assert _drop(physics_stage) is None
    assert physics_stage.GetPrimAtPath("/World/PhysicsMaterials/Other_PhysMat")
