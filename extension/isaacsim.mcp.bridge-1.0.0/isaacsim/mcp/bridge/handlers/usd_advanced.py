"""
Advanced USD handlers.

Handles flatten, export, variant selection, variant structure creation,
prim comparison, and material path updates.
"""

import carb
from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

from ._utils import (
    _collect_materials,
    _compute_mesh_stats,
    _compute_world_bbox,
    _get_stage,
    _next_update,
)


# ---------------------------------------------------------------------------
# /scene/flatten
# ---------------------------------------------------------------------------

async def handle_flatten_usd(body: dict) -> dict:
    """Flatten a USD file (resolve references, payloads, sublayers) into one file."""
    input_path = body.get("input_path", "")
    output_path = body.get("output_path", "")

    if not output_path:
        return {"status": "error", "error": "output_path is required"}

    await _next_update()

    if input_path:
        # Clear cached layer to avoid "layer already exists" errors
        cached = Sdf.Layer.Find(input_path)
        if cached:
            cached.Clear()
        src_stage = Usd.Stage.Open(input_path)
        if not src_stage:
            return {"status": "error", "error": f"Could not open: {input_path}"}
    else:
        src_stage = _get_stage()
        input_path = src_stage.GetRootLayer().realPath or "(current stage)"

    layer_count = len(src_stage.GetUsedLayers())
    flattened = src_stage.Flatten()

    # Clear target layer if cached
    cached_out = Sdf.Layer.Find(output_path)
    if cached_out:
        cached_out.Clear()

    success = flattened.Export(output_path)
    if not success:
        return {"status": "error", "error": f"Failed to export flattened stage to: {output_path}"}

    return {
        "status": "success",
        "result": {
            "input_path": input_path,
            "output_path": output_path,
            "layer_count": layer_count,
        },
    }


# ---------------------------------------------------------------------------
# /scene/export
# ---------------------------------------------------------------------------

async def handle_export_prim(body: dict) -> dict:
    """Export a prim subtree as a standalone USD file.

    Flattens the source stage (resolves all references) and copies the
    subtree plus any externally-referenced materials.
    """
    prim_path = body.get("prim_path", "")
    output_path = body.get("output_path", "")

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}
    if not output_path:
        return {"status": "error", "error": "output_path is required"}

    if not output_path.lower().endswith((".usd", ".usda", ".usdc", ".usdz")):
        output_path += ".usdc"

    await _next_update()

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    # Collect material bindings from source BEFORE flattening
    materials_outside = set()
    for p in Usd.PrimRange(prim, Usd.TraverseInstanceProxies()):
        binding = UsdShade.MaterialBindingAPI(p)
        mat, _ = binding.ComputeBoundMaterial()
        if mat:
            mat_path = str(mat.GetPath())
            if not mat_path.startswith(prim_path):
                materials_outside.add(mat_path)

    # Flatten source and copy subtree
    src_layer = stage.Flatten()

    # Clear target layer if cached
    cached_out = Sdf.Layer.Find(output_path)
    if cached_out:
        cached_out.Clear()

    new_stage = Usd.Stage.CreateNew(output_path)
    UsdGeom.SetStageUpAxis(new_stage, UsdGeom.GetStageUpAxis(stage))
    UsdGeom.SetStageMetersPerUnit(new_stage, UsdGeom.GetStageMetersPerUnit(stage))

    dst_layer = new_stage.GetRootLayer()
    prim_name = prim_path.rsplit("/", 1)[-1]
    target_path = f"/{prim_name}"

    Sdf.CopySpec(src_layer, prim_path, dst_layer, target_path)

    # Copy referenced materials that live outside the exported subtree
    for mat_path in materials_outside:
        if src_layer.GetPrimAtPath(mat_path):
            # Ensure parent prims exist
            parts = mat_path.strip("/").split("/")
            for i in range(1, len(parts)):
                parent = "/" + "/".join(parts[:i])
                if not dst_layer.GetPrimAtPath(parent):
                    Sdf.CreatePrimInLayer(dst_layer, parent)
            Sdf.CopySpec(src_layer, mat_path, dst_layer, mat_path)

    exported_prim = new_stage.GetPrimAtPath(target_path)
    if exported_prim.IsValid():
        new_stage.SetDefaultPrim(exported_prim)
    new_stage.GetRootLayer().Save()

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "output_path": output_path,
            "target_root": target_path,
            "materials_included": len(materials_outside),
            "up_axis": UsdGeom.GetStageUpAxis(stage),
        },
    }


# ---------------------------------------------------------------------------
# /scene/variant_selection
# ---------------------------------------------------------------------------

async def handle_set_variant_selection(body: dict) -> dict:
    """Switch variant selection with Hydra rprim refresh workaround.

    After SetVariantSelection(), toggles prim activation and pumps frames
    to force Hydra to rebuild rprims. This works around known FSD/Hydra bugs
    (OMPE-54434, OMPE-70769, OMPE-71336) that cause stale viewport geometry.
    """
    prim_path = body.get("prim_path", "")
    variant_set = body.get("variant_set", "")
    variant_name = body.get("variant_name", "")

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}
    if not variant_set:
        return {"status": "error", "error": "variant_set is required"}
    if not variant_name:
        return {"status": "error", "error": "variant_name is required"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    vsets = prim.GetVariantSets()
    if not vsets.HasVariantSet(variant_set):
        available = vsets.GetNames()
        return {"status": "error", "error": f"Variant set '{variant_set}' not found. Available: {available}"}

    vs = vsets.GetVariantSet(variant_set)
    available_variants = vs.GetVariantNames()
    if variant_name not in available_variants:
        return {"status": "error", "error": f"Variant '{variant_name}' not in '{variant_set}'. Available: {available_variants}"}

    old_selection = vs.GetVariantSelection()

    await _next_update()

    # Set the variant selection
    vs.SetVariantSelection(variant_name)

    # Hydra rprim refresh workaround — only needed when FSD is enabled.
    fsd_on = False
    try:
        import carb.settings
        fsd_on = carb.settings.get_settings().get_as_bool("/app/useFabricSceneDelegate") or False
    except Exception:
        pass

    if fsd_on:
        prim.SetActive(False)
        for _ in range(10):
            await _next_update()
        prim.SetActive(True)
        for _ in range(30):
            await _next_update()
    else:
        # Without FSD, just wait for Hydra to process the variant switch
        for _ in range(5):
            await _next_update()

    # Clear bbox cache so subsequent bounds queries return fresh data
    UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"]).Clear()

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "variant_set": variant_set,
            "old_selection": old_selection,
            "new_selection": variant_name,
            "available_variants": available_variants,
        },
    }


# ---------------------------------------------------------------------------
# /scene/create_variant_structure
# ---------------------------------------------------------------------------

async def handle_create_variant_structure(body: dict) -> dict:
    """Create variant set boilerplate: add variantSet, create variant bodies, set default."""
    prim_path = body.get("prim_path", "")
    variant_set_name = body.get("variant_set_name", "")
    variant_names = body.get("variant_names", ["focused", "shell"])
    default_variant = body.get("default_variant", "")

    if not prim_path:
        return {"status": "error", "error": "prim_path is required"}
    if not variant_set_name:
        return {"status": "error", "error": "variant_set_name is required"}
    if not variant_names:
        return {"status": "error", "error": "variant_names must be a non-empty list"}

    stage = _get_stage()
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()

    vsets = prim.GetVariantSets()
    vs = vsets.AddVariantSet(variant_set_name)

    for name in variant_names:
        vs.AddVariant(name)

    default = default_variant if default_variant in variant_names else variant_names[0]
    vs.SetVariantSelection(default)

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "variant_set_name": variant_set_name,
            "variants_created": variant_names,
            "default_selection": default,
        },
    }


# ---------------------------------------------------------------------------
# /scene/compare
# ---------------------------------------------------------------------------

async def handle_compare_prims(body: dict) -> dict:
    """Compare two prims or two variants — mesh counts, bounds, materials.

    Two modes:
    1. Prim comparison: provide prim_path_a and prim_path_b
    2. Variant comparison: provide prim_path, variant_set, variant_a, variant_b
    """
    prim_path_a = body.get("prim_path_a", "")
    prim_path_b = body.get("prim_path_b", "")
    variant_prim = body.get("prim_path", "")
    variant_set = body.get("variant_set", "")
    variant_a = body.get("variant_a", "")
    variant_b = body.get("variant_b", "")

    stage = _get_stage()
    await _next_update()

    if variant_prim and variant_set and variant_a and variant_b:
        # --- Variant comparison mode ---
        prim = stage.GetPrimAtPath(variant_prim)
        if not prim.IsValid():
            return {"status": "error", "error": f"Prim not found: {variant_prim}"}

        vsets = prim.GetVariantSets()
        if not vsets.HasVariantSet(variant_set):
            return {"status": "error", "error": f"Variant set '{variant_set}' not found"}

        vs = vsets.GetVariantSet(variant_set)
        old_selection = vs.GetVariantSelection()

        # Stats for variant A
        vs.SetVariantSelection(variant_a)
        await _next_update()
        bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
        stats_a = _compute_mesh_stats(prim)
        center_a, dims_a, _ = _compute_world_bbox(prim)
        mats_a = _collect_materials(prim)

        # Clear bbox cache before switching variant
        bbox_cache.Clear()

        # Stats for variant B
        vs.SetVariantSelection(variant_b)
        await _next_update()
        stats_b = _compute_mesh_stats(prim)
        center_b, dims_b, _ = _compute_world_bbox(prim)
        mats_b = _collect_materials(prim)

        # Restore original selection
        vs.SetVariantSelection(old_selection)
        await _next_update()

        label_a = f"{variant_prim} [{variant_set}={variant_a}]"
        label_b = f"{variant_prim} [{variant_set}={variant_b}]"

    elif prim_path_a and prim_path_b:
        # --- Direct prim comparison mode ---
        pa = stage.GetPrimAtPath(prim_path_a)
        pb = stage.GetPrimAtPath(prim_path_b)
        if not pa.IsValid():
            return {"status": "error", "error": f"Prim not found: {prim_path_a}"}
        if not pb.IsValid():
            return {"status": "error", "error": f"Prim not found: {prim_path_b}"}

        stats_a = _compute_mesh_stats(pa)
        center_a, dims_a, _ = _compute_world_bbox(pa)
        mats_a = _collect_materials(pa)

        stats_b = _compute_mesh_stats(pb)
        center_b, dims_b, _ = _compute_world_bbox(pb)
        mats_b = _collect_materials(pb)

        label_a = prim_path_a
        label_b = prim_path_b
    else:
        return {"status": "error", "error": "Provide (prim_path_a, prim_path_b) or (prim_path, variant_set, variant_a, variant_b)"}

    face_delta = stats_b["total_faces"] - stats_a["total_faces"]
    face_pct = (face_delta / stats_a["total_faces"] * 100) if stats_a["total_faces"] > 0 else 0

    return {
        "status": "success",
        "result": {
            "a": {
                "label": label_a,
                "total_faces": stats_a["total_faces"],
                "total_vertices": stats_a["total_vertices"],
                "total_triangles": stats_a["total_triangles"],
                "mesh_count": stats_a["mesh_count"],
                "bounds_center": center_a,
                "bounds_dimensions": dims_a,
                "materials": mats_a,
            },
            "b": {
                "label": label_b,
                "total_faces": stats_b["total_faces"],
                "total_vertices": stats_b["total_vertices"],
                "total_triangles": stats_b["total_triangles"],
                "mesh_count": stats_b["mesh_count"],
                "bounds_center": center_b,
                "bounds_dimensions": dims_b,
                "materials": mats_b,
            },
            "delta": {
                "faces": face_delta,
                "vertices": stats_b["total_vertices"] - stats_a["total_vertices"],
                "triangles": stats_b["total_triangles"] - stats_a["total_triangles"],
                "meshes": stats_b["mesh_count"] - stats_a["mesh_count"],
                "face_reduction_pct": round(face_pct, 1),
            },
        },
    }


# ---------------------------------------------------------------------------
# /scene/update_material_paths
# ---------------------------------------------------------------------------

async def handle_update_material_paths(body: dict) -> dict:
    """Bulk-update material reference paths (relationship targets + asset paths)."""
    prim_path = body.get("prim_path", "/")
    old_prefix = body.get("old_prefix", "")
    new_prefix = body.get("new_prefix", "")

    if not old_prefix:
        return {"status": "error", "error": "old_prefix is required"}
    if new_prefix is None:
        return {"status": "error", "error": "new_prefix is required"}

    stage = _get_stage()
    root = stage.GetPrimAtPath(prim_path)
    if not root.IsValid():
        return {"status": "error", "error": f"Prim not found: {prim_path}"}

    await _next_update()

    updated_count = 0
    updated_prims = set()

    for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
        # Update relationship targets (material bindings, etc.)
        for rel in prim.GetRelationships():
            targets = rel.GetTargets()
            new_targets = []
            changed = False
            for t in targets:
                t_str = str(t)
                if t_str.startswith(old_prefix):
                    new_targets.append(Sdf.Path(new_prefix + t_str[len(old_prefix):]))
                    changed = True
                else:
                    new_targets.append(t)
            if changed:
                rel.SetTargets(new_targets)
                updated_count += 1
                updated_prims.add(str(prim.GetPath()))

        # Update asset path attributes (texture paths, etc.)
        for attr in prim.GetAttributes():
            try:
                val = attr.Get()
            except Exception:
                continue
            if isinstance(val, Sdf.AssetPath):
                path_str = val.path
                if path_str.startswith(old_prefix):
                    new_path = new_prefix + path_str[len(old_prefix):]
                    attr.Set(Sdf.AssetPath(new_path))
                    updated_count += 1
                    updated_prims.add(str(prim.GetPath()))

    return {
        "status": "success",
        "result": {
            "prim_path": prim_path,
            "old_prefix": old_prefix,
            "new_prefix": new_prefix,
            "updated_count": updated_count,
            "updated_prims": sorted(updated_prims),
        },
    }
