"""set_material's material: an OmniPBR shader that names its MDL source.

A shader named only by `info:id = "OmniPBR"` resolves where a shader node is registered under that id, which not
every Kit app has (Isaac Sim 6.2 headless doesn't); RTX then renders Kit's red error material. Naming the source
asset, as Kit's own MDL materials do, resolves wherever MDL does (#30).

Needs pxr, not Kit: the tests run it on usd-core.
"""

from pxr import Gf, Sdf, Usd, UsdShade

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
