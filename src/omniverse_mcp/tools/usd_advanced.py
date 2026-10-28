"""Advanced USD tools (mesh stats, flatten, export, variants, compare, material paths)."""

from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import DESTROYS, EDITS, READS
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=READS)
    def get_mesh_stats(
        prim_path: Annotated[str, Field(description="The prim to measure, its descendant meshes included")],
    ) -> str:
        """Get face/vertex/triangle counts for a mesh prim or subtree.

        Returns per-mesh breakdown and totals. Use for measuring geometry budget,
        shell reduction ratios, etc.
        """
        resp = bridge_call(client.mesh_stats, prim_path)
        r = resp["result"]
        lines = [
            f"[{r['prim_path']}]",
            f"meshes = {r['mesh_count']}",
            f"total_faces = {r['total_faces']}",
            f"total_vertices = {r['total_vertices']}",
            f"total_triangles = {r['total_triangles']}",
        ]
        if r["mesh_count"] <= 20:
            lines.append("")
            for m in r["meshes"]:
                lines.append(f"[{m['path']}]")
                lines.append(f"faces = {m['faces']}, vertices = {m['vertices']}, triangles = {m['triangles']}")
        text = "\n".join(lines)
        return h.text_response(text, "mesh_stats")

    @mcp.tool(annotations=READS)
    def get_prim_face_count_tree(
        root: Annotated[str, Field(description="Prim path to start from")] = "/World",
        max_depth: Annotated[int, Field(ge=0, description="How many levels below root; 0 for root alone")] = 10,
    ) -> str:
        """Get scene tree with face counts per mesh and subtree totals.

        Like get_scene_tree but focused on geometry budget: each mesh shows
        face/vertex/triangle counts, each group shows subtree_faces total.
        """
        resp = bridge_call(client.face_count_tree, root, max_depth)
        r = resp["result"]
        return h.text_response(r["text"], "face_count_tree")

    @mcp.tool(annotations=DESTROYS)
    def flatten_usd(
        output_path: Annotated[str, Field(description="The flattened USD file to write")],
        input_path: Annotated[str, Field(description="The USD file to flatten; the open stage when empty")] = "",
    ) -> str:
        """Flatten a USD file: resolve all references, payloads, sublayers into one file.

        If input_path is omitted, flattens the current stage.
        """
        resp = bridge_call(client.flatten_usd, output_path, input_path)
        r = resp["result"]
        return f"Flattened {r['input_path']} ({r['layer_count']} layers) -> {r['output_path']}"

    @mcp.tool(annotations=DESTROYS)
    def export_prim_as_file(
        prim_path: Annotated[str, Field(description="The root of the subtree to export")],
        output_path: Annotated[str, Field(description="The file to write: .usd, .usda or .usdc (the default)")],
    ) -> str:
        """Export a prim subtree as a standalone USD file.

        Flattens the source (resolves all references) and includes materials
        even if they live outside the exported subtree. Output is self-contained.
        """
        resp = bridge_call(client.export_prim, prim_path, output_path)
        r = resp["result"]
        return (
            f"Exported {r['prim_path']} -> {r['output_path']}\n"
            f"Root: {r['target_root']}, Materials included: {r['materials_included']}, Up: {r['up_axis']}"
        )

    @mcp.tool(annotations=EDITS)
    def set_variant_selection(
        prim_path: Annotated[str, Field(description="The prim with the variant set")],
        variant_set: Annotated[str, Field(description='The variant set\'s name, e.g. "model"')],
        variant_name: Annotated[str, Field(description='The variant to select, e.g. "shell"')],
    ) -> str:
        """Switch variant selection on a prim with proper viewport refresh.

        Includes Hydra rprim refresh workaround (activation toggle + frame pumping)
        to ensure the viewport renders the correct geometry after switching.
        """
        resp = bridge_call(client.set_variant_selection, prim_path, variant_set, variant_name)
        r = resp["result"]
        return (
            f"Variant switched: {r['prim_path']} {r['variant_set']}={r['new_selection']} "
            f"(was: {r['old_selection']})\n"
            f"Available: {r['available_variants']}"
        )

    @mcp.tool(annotations=EDITS)
    def create_variant_structure(
        prim_path: Annotated[str, Field(description="The prim to add the variant set to")],
        variant_set_name: Annotated[str, Field(description='The new variant set\'s name, e.g. "model"')],
        variant_names: Annotated[list[str], Field(description='The variants to create, e.g. ["focused", "shell"]')],
        default_variant: Annotated[str, Field(description="The variant selected at first; the first when empty")] = "",
    ) -> str:
        """Create variant set boilerplate on a prim.

        Adds the variant set, creates empty variant bodies, and sets the default.
        """
        resp = bridge_call(client.create_variant_structure, prim_path, variant_set_name, variant_names, default_variant)
        r = resp["result"]
        return (
            f"Created variant set '{r['variant_set_name']}' on {r['prim_path']}\n"
            f"Variants: {r['variants_created']}\n"
            f"Default: {r['default_selection']}"
        )

    @mcp.tool(annotations=EDITS)
    def compare_prims(
        prim_path_a: Annotated[str, Field(description="Two prims: the first")] = "",
        prim_path_b: Annotated[str, Field(description="Two prims: the second")] = "",
        prim_path: Annotated[str, Field(description="Two variants: the prim that has them")] = "",
        variant_set: Annotated[str, Field(description="Two variants: their variant set")] = "",
        variant_a: Annotated[str, Field(description="Two variants: the first")] = "",
        variant_b: Annotated[str, Field(description="Two variants: the second")] = "",
    ) -> str:
        """Compare two prims or two variants: mesh counts, bounds, materials.

        Two modes:
        1. Prim comparison: provide prim_path_a and prim_path_b
        2. Variant comparison: provide prim_path, variant_set, variant_a, variant_b

        Returns side-by-side stats with deltas. Properly clears BBoxCache between
        variant switches to avoid stale data.
        """
        resp = bridge_call(client.compare_prims, prim_path_a, prim_path_b, prim_path, variant_set, variant_a, variant_b)
        r = resp["result"]
        a, b, d = r["a"], r["b"], r["delta"]

        sign = "+" if d["faces"] >= 0 else ""
        lines = [
            f"=== A: {a['label']} ===",
            f"meshes={a['mesh_count']}  faces={a['total_faces']}  vertices={a['total_vertices']}  triangles={a['total_triangles']}",
            f"bounds_center={a['bounds_center']}  bounds_dims={a['bounds_dimensions']}",
            f"materials: {', '.join(a['materials']) if a['materials'] else 'none'}",
            "",
            f"=== B: {b['label']} ===",
            f"meshes={b['mesh_count']}  faces={b['total_faces']}  vertices={b['total_vertices']}  triangles={b['total_triangles']}",
            f"bounds_center={b['bounds_center']}  bounds_dims={b['bounds_dimensions']}",
            f"materials: {', '.join(b['materials']) if b['materials'] else 'none'}",
            "",
            "=== Delta (B - A) ===",
            f"faces: {sign}{d['faces']} ({sign}{d['face_reduction_pct']}%)",
            f"vertices: {sign}{d['vertices']}  triangles: {sign}{d['triangles']}  meshes: {sign}{d['meshes']}",
        ]
        return "\n".join(lines)

    @mcp.tool(annotations=DESTROYS)
    def update_material_paths(
        old_prefix: Annotated[str, Field(description='The path prefix to find, e.g. "/OldProject/Materials"')],
        new_prefix: Annotated[str, Field(description='What to put in its place, e.g. "/World/Materials"')],
        prim_path: Annotated[str, Field(description="The subtree to update; the whole stage by default")] = "/",
    ) -> str:
        """Bulk-update material reference paths in a subtree.

        Updates both relationship targets (material bindings) and asset path
        attributes (texture file paths) that start with old_prefix.
        """
        resp = bridge_call(client.update_material_paths, old_prefix, new_prefix, prim_path)
        r = resp["result"]
        lines = [
            f"Updated {r['updated_count']} references in {len(r['updated_prims'])} prims",
            f"'{r['old_prefix']}' -> '{r['new_prefix']}'",
        ]
        if r["updated_prims"]:
            for p in r["updated_prims"][:10]:
                lines.append(f"  {p}")
            if len(r["updated_prims"]) > 10:
                lines.append(f"  ... and {len(r['updated_prims']) - 10} more")
        return "\n".join(lines)
