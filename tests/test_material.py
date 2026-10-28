"""set_material's OmniPBR material names its MDL source, which every Kit app with MDL resolves (#30), on usd-core."""

from pxr import Sdf, Usd, UsdShade

from ovmcp.core.material import MDL_ASSET, MDL_NAME, ensure_material


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
