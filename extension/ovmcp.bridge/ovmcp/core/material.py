"""set_material's material: an OmniPBR shader that names its MDL source. And set_physics_properties' physics material:
the prim's own, a child of the prim; the values a body has now, which it starts from; the other prims a write into it
changes; and the older extension's shared material a call moves the prim off, deleted when nothing binds it.

A shader named only by `info:id = "OmniPBR"` resolves where a shader node is registered under that id, which not
every Kit app has (Isaac Sim 6.2 headless doesn't); RTX then renders Kit's red error material. Naming the source
asset, as Kit's own MDL materials do, resolves wherever MDL does (#30).

Needs pxr, not Kit: the tests run it on usd-core.
"""

from dataclasses import dataclass
from typing import cast

from pxr import Gf, Sdf, Usd, UsdPhysics, UsdShade

from .deletion import instance_of
from .usd import has_api, is_a
from .xform import layer_name

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


def physics_material(prim: Usd.Prim) -> Usd.Prim | None:
    """The physics material bound to prim, as PhysX finds it: a physics-purpose binding, else an all-purpose one, and
    only a material with MaterialAPI."""
    bound = cast("tuple[UsdShade.Material, object]", UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial("physics"))
    material = bound[0].GetPrim() if bound[0] else None
    return material if material is not None and has_api(material, UsdPhysics.MaterialAPI) else None


def physics_source(prim: Usd.Prim) -> Usd.Prim | None:
    """The physics material whose values PhysX gives prim now: the one bound to it, else the physics scene's default
    material, the one bound to the stage's first UsdPhysics.Scene; None for PhysX's own default."""
    material = physics_material(prim)
    if material is not None:
        return material
    scene = next((p for p in prim.GetStage().Traverse() if is_a(p, UsdPhysics.Scene)), None)
    return physics_material(scene) if scene is not None else None


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
    as before in everything a call doesn't name, and keeps none source lacks. Nothing when source is material
    itself; with None, PhysX's own default, material keeps none of them.

    By name and type, not through PhysxSchema, which usd-core lacks: there HasAPI and GetAppliedSchemas() can't see
    PhysxMaterialAPI, while the apiSchemas list op holds it.
    """
    if source is not None and source.GetPath() == material.GetPath():
        return
    # Exact: a material that is there already, made by an older extension or before the prim was bound to another,
    # keeps nothing its new source lacks, such as a density or a combine mode; with no source, it starts from PhysX's
    # own (review I8).
    wanted = _applied(source) if source is not None else []
    for schema in _applied(material):
        if schema not in wanted and schema == "PhysxMaterialAPI":
            material.RemoveAppliedSchema(schema)
    for attr in material.GetAuthoredAttributes():
        name = attr.GetName()
        there = source.GetAttribute(name) if source is not None else None
        if name.startswith(_PHYSICS_NAMESPACES) and not (there and there.HasAuthoredValue()):
            material.RemoveProperty(name)
    if source is None:
        return
    for schema in wanted:
        if schema in _PHYSICS_SCHEMAS:
            material.AddAppliedSchema(schema)
    for attr in source.GetAuthoredAttributes():
        name = attr.GetName()
        if name.startswith(_PHYSICS_NAMESPACES) and attr.HasAuthoredValue():
            material.CreateAttribute(name, attr.GetTypeName()).Set(attr.Get())


def _applied(prim: Usd.Prim) -> list[str]:
    """The API schemas prim's composed apiSchemas list op holds, by name: PhysxMaterialAPI among them on usd-core,
    whose GetAppliedSchemas() can't see it."""
    held = cast("Sdf.TokenListOp | None", prim.GetMetadata("apiSchemas"))
    return [str(schema) for schema in held.GetAddedOrExplicitItems()] if held is not None else []


# ---- the prim's own physics material, and who else a write reaches (#113) ----

PHYS_MAT = "PhysMat"
# Where an extension of 0.3.0 or older put a prim's physics material: named after the prim's last name alone, so prims
# of one name shared it.
OLD_FOLDER = Sdf.Path("/World/PhysicsMaterials")
# How many of the other prims a write changes the answer names; it counts the rest.
NAMED = 5
_BINDING = "material:binding"


def physics_material_path(path: Sdf.Path) -> Sdf.Path:
    """The prim's own physics material: its child, so a copy takes one of its own and delete_prim removes it with the
    prim."""
    return path.AppendChild(PHYS_MAT)


def _instance_refusal(instance: Usd.Prim) -> str:
    path = instance.GetPath()
    text = (
        f"{path} is an instance, which USD lets hold no prim of its own, so it can't hold its own physics material, "
        f"{physics_material_path(path)}."
    )
    parent = path.GetParentPath()
    if parent.IsPrimPath():
        # Not "call the parent": its material reaches every prim under it without one, the other instances too (P4).
        text += (
            f" A call on its parent, {parent}, would give the parent's material to every prim under {parent} that "
            "has none of its own, not only to this one"
        )
    return text


def material_refusal(prim: Usd.Prim) -> str | None:
    """Why prim can't hold its own physics material, or None. USD lets neither an instance nor a prim inside one hold
    a child (the instance flag alone, with no reference or payload, makes no instance); a child PhysMat that isn't a
    Material is the user's own."""
    if prim.IsInstanceProxy():
        instance = instance_of(prim)
        return (
            f"{prim.GetPath()} is inside the instance {instance.GetPath()}, whose prims can't be changed one by one. "
            + _instance_refusal(instance)
        )
    if prim.IsInstance():
        return _instance_refusal(prim)
    child = prim.GetStage().GetPrimAtPath(physics_material_path(prim.GetPath()))
    if child and child.IsDefined() and not is_a(child, UsdShade.Material):
        kind = child.GetTypeName() or "typeless prim"
        return (
            f"{child.GetPath()} is a {kind}, not a Material, where set_physics_properties keeps the prim's own physics "
            "material: rename or delete it first"
        )
    return None


def own_physics_material(stage: Usd.Stage, prim: Usd.Prim) -> Usd.Prim:
    """prim's own physics material, a Material with MaterialAPI at physics_material_path, made when missing. One there
    already is kept, an inheriting clone's composed from its source's included. ValueError with material_refusal's
    text when prim can't hold one."""
    refusal = material_refusal(prim)
    if refusal:
        raise ValueError(refusal)
    path = physics_material_path(prim.GetPath())
    material = stage.GetPrimAtPath(path)
    # An over alone, with no def anywhere, is no prim on the stage: Define makes it the Material.
    if not (material and material.IsDefined() and is_a(material, UsdShade.Material)):
        material = UsdShade.Material.Define(stage, path).GetPrim()
    if not has_api(material, UsdPhysics.MaterialAPI):
        UsdPhysics.MaterialAPI.Apply(material)
    return material


def _is_binding(name: object) -> bool:
    # A property name, which the stubs type as a str or an Ar.ResolvedPath.
    text = str(name)
    return text == _BINDING or text.startswith(f"{_BINDING}:")


@dataclass(frozen=True)
class Bindings:
    """One walk of the stage: each path a binding targets, with the prims that bind it; those of them that are no body
    on the stage (inactive, an over alone, or a class); and why a prim the walk couldn't see could bind one too."""

    binders: dict[Sdf.Path, list[Sdf.Path]]
    ghosts: set[Sdf.Path]
    unseen: str | None


def walk_bindings(stage: Usd.Stage) -> Bindings:
    """Every prim's binding relationships, of every purpose and collection, the all-purpose one included, which
    GetAuthoredPropertiesInNamespace leaves out. Instance proxies and prototypes aren't walked, an instance's own
    binding is. An inactive prim's children and an unloaded payload's aren't on the stage to walk, so the first of
    each is noted."""
    binders: dict[Sdf.Path, list[Sdf.Path]] = {}
    ghosts: set[Sdf.Path] = set()
    unseen: str | None = None
    for prim in Usd.PrimRange.Stage(stage, Usd.PrimAllPrimsPredicate):
        active = prim.IsActive()
        if unseen is None:
            if not active:
                unseen = f"{prim.GetPath()} is inactive, so a prim under it could bind it"
            elif prim.HasAuthoredPayloads() and not prim.IsLoaded():
                unseen = f"the payload of {prim.GetPath()} isn't loaded, so a prim in it could bind it"
        for prop in prim.GetAuthoredProperties(_is_binding):
            if not isinstance(prop, Usd.Relationship):
                continue
            targets = [target for target in prop.GetTargets() if target.IsPrimPath()]
            for target in targets:
                binders.setdefault(target, []).append(prim.GetPath())
            if targets and not (active and prim.IsDefined() and not prim.IsAbstract()):
                ghosts.add(prim.GetPath())
    return Bindings(binders, ghosts, unseen)


def _holds_spec(prim: Usd.Prim, layer: Sdf.Layer, path: Sdf.Path) -> bool:
    """Whether prim is composed from the spec at path in layer, as an inheriting clone's material is from its
    source's."""
    return any(spec.layer.identifier == layer.identifier and spec.path == path for spec in prim.GetPrimStack())


def _reads_from(attr: Usd.Attribute, layer: Sdf.Layer, path: Sdf.Path) -> bool:
    """Whether attr's value comes from the spec at path in layer. The strongest spec holding a value says, not the
    strongest spec: one can declare the attribute with no value above it."""
    for spec in attr.GetPropertyStack(Usd.TimeCode.Default()):
        if cast("Sdf.AttributeSpec", spec).HasDefaultValue():
            return spec.layer.identifier == layer.identifier and spec.path == path
    return False


def also_changed(stage: Usd.Stage, prim: Usd.Prim, material: Usd.Prim, bindings: Bindings) -> list[Sdf.Path]:
    """The other prims the write into prim's material changes, sorted: those that bind it, and those that bind a
    material composed from it whose static friction, dynamic friction or restitution now comes from the written spec,
    as an inheriting clone's does until a call gives it its own. Not prim or its descendants, which the call is about,
    and only prims that are bodies on the stage. A copy made with CopySpec binds its own copy, so it never counts."""
    own = material.GetPath()
    layer = stage.GetEditTarget().GetLayer()
    called = prim.GetPath()
    changed: set[Sdf.Path] = set()
    for target, prims in bindings.binders.items():
        others = [p for p in prims if not p.HasPrefix(called) and p not in bindings.ghosts]
        if not others:
            continue
        if target != own:
            bound = stage.GetPrimAtPath(target)
            if not (bound and _holds_spec(bound, layer, own)):
                continue
            if not any(
                _reads_from(bound.GetAttribute(name), layer, own.AppendProperty(name)) for name in PHYSX_DEFAULT
            ):
                continue
        changed.update(others)
    return sorted(changed)


def _counted(prims: list[Sdf.Path]) -> str:
    """The first NAMED of prims, then how many more."""
    named = ", ".join(str(p) for p in prims[:NAMED])
    return named + (f" and {len(prims) - NAMED} more" if len(prims) > NAMED else "")


def _held_elsewhere(prim: Usd.Prim, layer: Sdf.Layer) -> str | None:
    """Why RemovePrim in layer wouldn't take prim off the stage whole: another layer holds a spec of it, or it is
    composed from a spec at another path, through a reference, inherit, specialize or payload, even in layer itself.
    None when every spec is layer's own at prim's path."""
    for spec in prim.GetPrimStack():
        if spec.layer.identifier != layer.identifier:
            return f"another layer holds it too: {layer_name(prim.GetStage(), spec.layer)}"
        if spec.path != prim.GetPath():
            return f"it is composed from {spec.path} too"
    return None


def _why_kept(stage: Usd.Stage, old: Usd.Prim, layer: Sdf.Layer, bindings: Bindings) -> str | None:
    """Why the older material stays, or None when deleting it changes no prim the walk could see or not see."""
    held = _held_elsewhere(old, layer)
    if held is not None:
        return held
    path = old.GetPath()
    # RemovePrim takes the whole subtree, which an older extension never wrote: what is under it is someone's own.
    under = [path.AppendChild(name) for name in old.GetAllChildrenNames()]
    if under:
        return f"it holds prims of its own: {_counted(under)}"
    binding = list(bindings.binders.get(path, []))
    for target, prims in bindings.binders.items():
        if target != path and (bound := stage.GetPrimAtPath(target)) and _holds_spec(bound, layer, path):
            binding += prims
    if binding:
        binding = sorted(set(binding))
        verb = "prim still binds" if len(binding) == 1 else "prims still bind"
        return f"{len(binding)} {verb} it: {_counted(binding)}"
    return bindings.unseen


def drop_old_material(
    stage: Usd.Stage, prim: Usd.Prim, before: Usd.Prim | None, bindings: Bindings
) -> dict[str, object] | None:
    """The older extension's shared material the call moved prim off, deleted when nothing could still bind it (Q4):
    exactly /World/PhysicsMaterials/<prim's name>_PhysMat, a Material with MaterialAPI, its specs all the edit
    layer's at its path, holding no prim of its own, which after the rebinding no prim binds, nor a material composed
    from it, on a stage the walk saw whole.
    /World/PhysicsMaterials goes too when that leaves it empty and it is typeless or a Scope of the edit layer's alone.

    The answer's old_material, {"path", "deleted"} or {"path", "kept"} with why; None when prim wasn't bound to such a
    material, so a user's own material, under any other path, is never touched."""
    path = OLD_FOLDER.AppendChild(f"{prim.GetName()}_PhysMat")
    if before is None or before.GetPath() != path:
        return None
    if not (is_a(before, UsdShade.Material) and has_api(before, UsdPhysics.MaterialAPI)):
        return None
    layer = stage.GetEditTarget().GetLayer()
    why = _why_kept(stage, before, layer, bindings)
    if why:
        return {"path": str(path), "kept": why}
    stage.RemovePrim(path)
    deleted = [str(path)]
    folder = stage.GetPrimAtPath(OLD_FOLDER)
    if (
        folder
        and not folder.GetAllChildrenNames()
        and folder.GetTypeName() in ("", "Scope")
        and _held_elsewhere(folder, layer) is None
    ):
        stage.RemovePrim(OLD_FOLDER)
        deleted.append(str(OLD_FOLDER))
    return {"path": str(path), "deleted": deleted}
