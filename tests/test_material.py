"""set_material's OmniPBR material, on usd-core: it names its MDL source, which every Kit app with MDL resolves (#30),
and every call sets every surface value (#82)."""

import pytest
from pxr import Gf, Sdf, Usd, UsdShade

from ovmcp.core.material import MDL_ASSET, MDL_NAME, ensure_material, set_surface


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
