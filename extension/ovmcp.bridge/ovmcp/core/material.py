"""set_material's material: an OmniPBR shader that names its MDL source. And set_physics_properties' physics material:
the values a body has now, which the one it binds starts from.

A shader named only by `info:id = "OmniPBR"` resolves where a shader node is registered under that id, which not
every Kit app has (Isaac Sim 6.2 headless doesn't); RTX then renders Kit's red error material. Naming the source
asset, as Kit's own MDL materials do, resolves wherever MDL does (#30).

Needs pxr, not Kit: the tests run it on usd-core.
"""

from typing import cast

from pxr import Gf, Sdf, Usd, UsdPhysics, UsdShade

from .usd import has_api, is_a

MDL_ASSET = "OmniPBR.mdl"
MDL_NAME = "OmniPBR"


def set_surface(
    shader: UsdShade.Shader, colour: tuple[float, float, float], opacity: float, roughness: float, metallic: float
) -> None:
    """Every value set_material sets, on every call, so a call that leaves one out sets its default: opacity 1 makes a
    see-through material opaque again, where only an opacity below 1 was written (#82)."""
    shader.CreateInput("diffuse_color_constant", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*colour))
    shader.CreateInput("reflection_roughness_constant", Sdf.ValueTypeNames.Float).Set(roughness)
    shader.CreateInput("metallic_constant", Sdf.ValueTypeNames.Float).Set(metallic)
    shader.CreateInput("enable_opacity", Sdf.ValueTypeNames.Bool).Set(opacity < 1.0)
    shader.CreateInput("opacity_constant", Sdf.ValueTypeNames.Float).Set(opacity)


def ensure_material(stage: Usd.Stage, mat_path: str) -> tuple[UsdShade.Material, UsdShade.Shader]:
    """The material at mat_path and its `Shader`, made as an OmniPBR material when it isn't there."""
    prim = stage.GetPrimAtPath(mat_path)
    if prim.IsValid():
        mat = UsdShade.Material(prim)
        shader = UsdShade.Shader(stage.GetPrimAtPath(f"{mat_path}/Shader"))
        if mat and shader:
            # One made before #30 named only its id: name its source too. Any other shader is the user's own.
            if shader.GetImplementationSource() == UsdShade.Tokens.id and shader.GetShaderId() == MDL_NAME:
                _name_source(shader)
            return mat, shader

    mat = UsdShade.Material.Define(stage, mat_path)
    shader = UsdShade.Shader.Define(stage, f"{mat_path}/Shader")
    _name_source(shader)
    shader.CreateOutput("out", Sdf.ValueTypeNames.Token)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "out")
    return mat, shader


def _name_source(shader: UsdShade.Shader) -> None:
    # Sets info:implementationSource to sourceAsset, so an info:id left from before is no longer read.
    shader.SetSourceAsset(Sdf.AssetPath(MDL_ASSET), "mdl")
    shader.SetSourceAssetSubIdentifier(MDL_NAME, "mdl")


# ---- set_physics_properties' physics material ----

STATIC, DYNAMIC, RESTITUTION = "physics:staticFriction", "physics:dynamicFriction", "physics:restitution"
# What PhysX gives a collider bound to no physics material, on a stage whose scene has no default one either: #105's
# probe measured dynamic friction 0.5 and restitution 0 on Isaac Sim 6.2; static friction is PhysX's 0.5 beside it.
PHYSX_DEFAULT = {STATIC: 0.5, DYNAMIC: 0.5, RESTITUTION: 0.0}
# The attributes a physics material holds: UsdPhysics.MaterialAPI's and PhysxSchema.PhysxMaterialAPI's.
_PHYSICS_NAMESPACES = ("physics:", "physxMaterial:")
_PHYSICS_SCHEMAS = ("PhysicsMaterialAPI", "PhysxMaterialAPI")


def _physics_material(prim: Usd.Prim) -> Usd.Prim | None:
    """The physics material bound to prim, as PhysX finds it: a physics-purpose binding, else an all-purpose one, and
    only a material with MaterialAPI."""
    bound = cast("tuple[UsdShade.Material, object]", UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics"))
    material = bound[0].GetPrim() if bound[0] else None
    return material if material is not None and has_api(material, UsdPhysics.MaterialAPI) else None


def physics_source(prim: Usd.Prim) -> Usd.Prim | None:
    """The physics material whose values PhysX gives prim now: the one bound to it, else the physics scene's default
    material, the one bound to the stage's first UsdPhysics.Scene; None for PhysX's own default."""
    material = _physics_material(prim)
    if material is not None:
        return material
    scene = next((p for p in prim.GetStage().Traverse() if is_a(p, UsdPhysics.Scene)), None)
    return _physics_material(scene) if scene is not None else None


def physics_values(source: Usd.Prim | None) -> dict[str, float]:
    """source's static friction, dynamic friction and restitution as PhysX reads them: an unauthored one is USD's
    fallback, 0 (#105's probe). PHYSX_DEFAULT for no source."""
    if source is None:
        return dict(PHYSX_DEFAULT)
    values: dict[str, float] = {}
    for name in PHYSX_DEFAULT:
        attr = source.GetAttribute(name)
        value = attr.Get() if attr else None
        values[name] = float(cast("float", value)) if value is not None else 0.0
    return values


def start_from(material: Usd.Prim, source: Usd.Prim | None) -> None:
    """Gives material what source holds beside its frictions and restitution: every authored physics: and
    physxMaterial: attribute, such as a density or PhysX's combine modes, and its PhysxMaterialAPI, so the body behaves
    as before in everything a call doesn't name. Nothing when source is material itself or None.

    By name and type, not through PhysxSchema, which usd-core lacks: there HasAPI and GetAppliedSchemas() can't see
    PhysxMaterialAPI, while the apiSchemas list op holds it.
    """
    if source is None or source.GetPath() == material.GetPath():
        return
    held = cast("Sdf.TokenListOp | None", source.GetMetadata("apiSchemas"))
    applied = list(held.GetAddedOrExplicitItems()) if held is not None else []
    for schema in applied:
        if schema in _PHYSICS_SCHEMAS:
            material.AddAppliedSchema(schema)
    for attr in source.GetAuthoredAttributes():
        name = attr.GetName()
        if name.startswith(_PHYSICS_NAMESPACES) and attr.HasAuthoredValue():
            material.CreateAttribute(name, attr.GetTypeName()).Set(attr.Get())
