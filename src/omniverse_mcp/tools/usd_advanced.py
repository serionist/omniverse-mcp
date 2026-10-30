"""Advanced USD tools (mesh stats, flatten, export, variants, compare, material paths)."""

from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import DESTROYS, EDITS, READS, tool
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, READS)
    def get_mesh_stats(
        prim_path: Annotated[str, Field(description="The prim to measure, its descendant meshes included")],
    ) -> str:
        """Count the faces, vertices and triangles of every mesh at or under a prim: totals, and each mesh's own counts
        when there are 20 or fewer.

        Use it for one subtree's geometry budget, or what a simplification saved; get_prim_face_count_tree shows where
        the faces are across a whole tree, and compare_prims puts two prims or variants side by side. Only UsdGeom.Mesh
        prims count, inside instances too: implicit shapes such as Cube and Sphere have no faces.
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

    @tool(mcp, READS)
    def get_prim_face_count_tree(
        root: Annotated[str, Field(description="Prim path to start from")] = "/World",
        max_depth: Annotated[int, Field(ge=0, description="How many levels below root; 0 for root alone")] = 10,
    ) -> str:
        """List the prims under root with their geometry: faces, vertices and triangles on each mesh, and subtree_faces
        on each prim above meshes, to find where a scene's faces are.

        Use it to find the heavy subtrees, then get_mesh_stats for one subtree's totals or compare_prims for two.
        Unlike get_scene_tree, it looks inside instanceable prims. Prims below max_depth are left out of the list but
        still count in their ancestors' subtree_faces.
        """
        resp = bridge_call(client.face_count_tree, root, max_depth)
        r = resp["result"]
        return h.text_response(r["text"], "face_count_tree")

    @tool(mcp, DESTROYS)
    def flatten_usd(
        output_path: Annotated[str, Field(description="The USD file to write, on Kit's machine; overwritten if there")],
        input_path: Annotated[
            str,
            Field(
                description="The USD file to flatten, on Kit's machine; the open stage, unsaved edits too, when empty"
            ),
        ] = "",
    ) -> str:
        """Write a stage flattened into one USD file: its references, payloads and sublayers resolved into a single
        layer.

        Use it to hand the whole scene to another tool as one file; save_scene keeps the references and writes only the
        root layer, and export_prim_as_file writes one prim's subtree. Leave input_path empty for the open stage, or
        name another USD file. output_path is overwritten; textures and other files the stage points at are not copied.
        Never name a file the open stage has loaded (its own file, a sublayer, a referenced asset) as either path: the
        bridge first clears an open layer of that name in memory, which empties it in the open scene too.
        """
        resp = bridge_call(client.flatten_usd, output_path, input_path)
        r = resp["result"]
        return f"Flattened {r['input_path']} ({r['layer_count']} layers) -> {r['output_path']}"

    @tool(mcp, DESTROYS)
    def export_prim_as_file(
        prim_path: Annotated[str, Field(description="The root of the subtree to export")],
        output_path: Annotated[
            str,
            Field(
                description="The file to write on Kit's machine: .usd, .usda or .usdc, which a path without one gets"
            ),
        ],
    ) -> str:
        """Write one prim's subtree to a USD file of its own, flattened, with the materials it is bound to from outside
        the subtree, so the file opens without the scene.

        The prim becomes /<its name> and the file's default prim, with the stage's up axis and units. Use it to hand
        one asset to another tool or project; flatten_usd writes the whole stage, save_scene the root layer as it is.
        output_path is overwritten. Never name a file the open stage has loaded: the bridge first clears an open layer
        of that name in memory, which empties it in the open scene too. Textures and other files the subtree points at
        are not copied.
        """
        resp = bridge_call(client.export_prim, prim_path, output_path)
        r = resp["result"]
        return (
            f"Exported {r['prim_path']} -> {r['output_path']}\n"
            f"Root: {r['target_root']}, Materials included: {r['materials_included']}, Up: {r['up_axis']}"
        )

    @tool(mcp, EDITS)
    def set_variant_selection(
        prim_path: Annotated[str, Field(description="The prim with the variant set")],
        variant_set: Annotated[str, Field(description='The variant set\'s name, e.g. "model"')],
        variant_name: Annotated[str, Field(description='The variant to select, e.g. "shell"')],
    ) -> str:
        """Select a variant in a prim's variant set, and wait until the viewport shows it.

        Switch variants with this rather than execute_script: with Fabric Scene Delegate on, it deactivates and
        reactivates the prim around the switch, some 40 app updates, so the viewport drops the old geometry; otherwise
        it waits 5. The set and the variant must exist (create_variant_structure makes them): an error lists the ones
        there. The selection is written to the stage; compare_prims measures two variants and puts the selection back.
        """
        resp = bridge_call(client.set_variant_selection, prim_path, variant_set, variant_name)
        r = resp["result"]
        return (
            f"Variant switched: {r['prim_path']} {r['variant_set']}={r['new_selection']} "
            f"(was: {r['old_selection']})\n"
            f"Available: {r['available_variants']}"
        )

    @tool(mcp, EDITS)
    def create_variant_structure(
        prim_path: Annotated[str, Field(description="The prim to add the variant set to")],
        variant_set_name: Annotated[str, Field(description='The new variant set\'s name, e.g. "model"')],
        variant_names: Annotated[list[str], Field(description='The variants to create, e.g. ["focused", "shell"]')],
        default_variant: Annotated[
            str, Field(description="The variant to select; the first of variant_names when empty or not among them")
        ] = "",
    ) -> str:
        """Add a variant set of empty variants to a prim and select one, ready to fill and to switch between with
        set_variant_selection.

        A set or variant that already exists is kept and added to, never replaced. The variants hold nothing until you
        author into them, with execute_script. An error when the prim doesn't exist.
        """
        resp = bridge_call(client.create_variant_structure, prim_path, variant_set_name, variant_names, default_variant)
        r = resp["result"]
        return (
            f"Created variant set '{r['variant_set_name']}' on {r['prim_path']}\n"
            f"Variants: {r['variants_created']}\n"
            f"Default: {r['default_selection']}"
        )

    @tool(mcp, EDITS)
    def compare_prims(
        prim_path_a: Annotated[str, Field(description="Two prims: the first")] = "",
        prim_path_b: Annotated[str, Field(description="Two prims: the second")] = "",
        prim_path: Annotated[str, Field(description="Two variants: the prim that has them")] = "",
        variant_set: Annotated[str, Field(description="Two variants: their variant set")] = "",
        variant_a: Annotated[str, Field(description="Two variants: the first")] = "",
        variant_b: Annotated[str, Field(description="Two variants: the second")] = "",
    ) -> str:
        """Compare two prims, or two variants of one prim, side by side: mesh, face, vertex and triangle counts, world
        bounds and bound materials, with B minus A and the change in faces as a percentage.

        Two modes:
        1. Two prims: prim_path_a and prim_path_b.
        2. Two variants: prim_path, variant_set, variant_a and variant_b; this mode wins when all four are given.

        Variant mode switches the selection to each variant in turn, then back to the one before. A variant name is not
        checked: one not in the set measures the prim with none of the set's variants. For one prim's counts, use
        get_mesh_stats.
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

    @tool(mcp, DESTROYS)
    def update_material_paths(
        old_prefix: Annotated[
            str, Field(description='The start of the paths to change, matched as text, e.g. "/OldProject/Materials/"')
        ],
        new_prefix: Annotated[str, Field(description='What to put in its place, e.g. "/World/Materials/"')],
        prim_path: Annotated[str, Field(description="The subtree to update; the whole stage by default")] = "/",
    ) -> str:
        """Rewrite every path under a subtree that starts with old_prefix to start with new_prefix instead: relationship
        targets, such as material bindings, and asset paths, such as texture files.

        Use it after materials or textures move, so bindings and textures point at their new place. The match is a plain
        text prefix, on any relationship or asset path: a joint's bodies or a shader's source file change too if they
        match, so end the prefix with "/" and keep it specific. Nothing checks that the new paths exist. Kit's undo
        doesn't record the change, and a failure part way keeps the edits made before it. The answer counts the paths
        changed and names the prims.
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
