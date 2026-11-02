"""Advanced USD tools (mesh stats, flatten, export, variants, compare, material paths)."""

from typing import TYPE_CHECKING, Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import install_advice

from ._annotations import DESTROYS, EDITS, READS, tool
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers

# How /scene/face_count_tree's text ends: the faces and meshes it listed, within max_depth only.
TREE_TOTAL = "# total:"
# How the extension names the stage's root layer in written_to (xform.layer_name), its file after it when it has one.
ROOT_LAYER = "the stage's root layer"
# How an extension from before #155 refuses variant_name "", a clear it can't do.
OLDER_REFUSES_A_CLEAR = "variant_name is required"


def _without_total(tree: str) -> str:
    """The face count tree's text without its last line when that starts TREE_TOTAL. That line counts only the meshes
    within max_depth, and counts a mesh without face data that /scene/mesh_stats skips, so beside the totals it would
    contradict them; a tree that ends otherwise is kept whole."""
    lines = tree.rstrip().split("\n")
    if lines[-1].startswith(TREE_TOTAL):
        lines.pop()
    return "\n".join(lines).rstrip()


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @tool(mcp, READS)
    def get_mesh_stats(
        prim_path: Annotated[str, Field(description="The prim to measure, its descendant meshes included")],
        max_depth: Annotated[
            int, Field(ge=0, description="How many levels of the tree below prim_path to list; 0 for prim_path alone")
        ] = 2,
    ) -> str:
        """Count the faces, vertices and triangles of every mesh at or under a prim: the totals, then the prims under it
        to max_depth, each mesh with its counts and each prim above meshes with subtree_faces.

        Use it for a geometry budget, what a simplification saved, or the heavy subtrees: a heavy one is the next
        call's prim_path. compare_prims puts two prims or variants side by side. Only UsdGeom.Mesh prims count, inside
        instances too, which get_scene_tree doesn't list: implicit shapes such as Cube and Sphere have no faces. Prims
        below max_depth aren't listed, but count in the totals and in their ancestors' subtree_faces. The totals always
        come inline; a tree too long to give with them goes to a file, its path in the answer.
        """
        r = bridge_call(client.mesh_stats, prim_path)["result"]
        totals = "\n".join(
            [
                f"[{r['prim_path']}]",
                f"meshes = {r['mesh_count']}",
                f"total_faces = {r['total_faces']}",
                f"total_vertices = {r['total_vertices']}",
                f"total_triangles = {r['total_triangles']}",
            ]
        )
        tree = _without_total(bridge_call(client.face_count_tree, prim_path, max_depth)["result"]["text"])
        whole = f"{totals}\n\n{tree}"
        if h.fits(whole):
            return whole
        return f"{totals}\n\n{h.write_response(tree, 'mesh_stats', f'the face count tree to depth {max_depth}')}"

    @tool(mcp, DESTROYS)
    def flatten_usd(
        output_path: Annotated[
            str,
            Field(
                description="The USD file to write, on Kit's machine; overwritten if there, but never one the open "
                "stage has loaded"
            ),
        ],
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
        name a USD file: one the open stage has loaded, its own file included, is flattened as Kit holds it, unsaved
        edits too, and the open stage is left as it is; one USD can't open is an error. output_path is overwritten, but
        one the open stage has loaded (its own file, a sublayer, a referenced or payload file) is an error, since
        writing it would replace a file the open scene is made of: name another path, or save the open stage with
        save_scene. Textures and other files the stage points at are not copied.
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
                description="The file to write on Kit's machine: .usd, .usda or .usdc, which a path without one gets; "
                "never one the open stage has loaded"
            ),
        ],
    ) -> str:
        """Write one prim's subtree to a USD file of its own, flattened, with the materials it is bound to from outside
        the subtree, so the file opens without the scene.

        The prim becomes /<its name> and the file's default prim, with the stage's up axis and units. Use it to hand
        one asset to another tool or project; flatten_usd writes the whole stage, save_scene the root layer as it is.
        output_path is overwritten, but one the open stage has loaded (its own file, a sublayer, a referenced or
        payload file) is an error, since writing it would replace a file the open scene is made of: name another path.
        An error too when the prim doesn't exist. Textures and other files the subtree points at are not copied.
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
        variant_name: Annotated[
            str,
            Field(
                description='The variant to select, e.g. "shell"; "" clears the layer\'s selection, so the one '
                "beneath shows again"
            ),
        ],
        layer: Annotated[
            Literal["session", "edit_target"],
            Field(
                description="session: Kit's session layer, which no save writes, so every file stays as it is; "
                "edit_target: where edits go, the stage's root layer, which save_scene writes, unless Kit's Layer "
                "window made a sublayer the edit target"
            ),
        ] = "session",
    ) -> str:
        """Select a variant in a prim's variant set, or clear a layer's selection, and wait until the viewport shows it.

        By default the selection goes to Kit's session layer: it shows at once over what the files select, and
        save_scene leaves it out of the file, so a check leaves every file as it found it; it lasts until it is
        cleared or the stage is opened again. To keep one in the stage's file, use layer="edit_target", where edits
        go: the root layer, which save_scene writes, unless Kit's Layer window made a sublayer the edit target, which
        save_scene doesn't write; the answer names the layer. It is refused while the session layer holds a selection
        for the set, since that would hide it: clear that first with variant_name="". An extension older than the
        server writes every switch at the edit target and can't clear, and the answer warns. get_prim_properties'
        variant_sets line lists a prim's sets, their options and the layer
        holding each selection. A selection on an instance prim gives it a prototype of its own; a prim inside an
        instance is refused, naming the instance. An unknown set or variant is refused, listing those there
        (create_variant_structure makes them). Switch variants with this rather than execute_script: with Fabric
        Scene Delegate on, it deactivates and reactivates the prim in the session layer around the switch, some 40 app
        updates, so the viewport drops the old geometry; otherwise it waits 5. compare_prims measures two variants and
        leaves the selection as it was.
        """
        try:
            r = bridge_call(client.set_variant_selection, prim_path, variant_set, variant_name, layer)["result"]
        except ToolError as e:
            # An extension from before #155 refuses a clear with this alone, which reads as the caller's mistake.
            if variant_name or str(e) != OLDER_REFUSES_A_CLEAR:
                raise
            raise ToolError(
                f"{e}\nWARNING: This Kit extension, older than the server, can't clear a selection, and writes every "
                f"switch at the edit target, into the stage's file. Install this server's, {install_advice()}."
            ) from e
        if "layer" not in r:
            # An extension from before #155 takes no layer and writes at the edit target, and the plugin updates the
            # server ahead of the extension.
            return (
                f"Variant switched: {r['prim_path']} {r['variant_set']}={r['new_selection']} "
                f"(was: {r['old_selection']})\nAvailable: {r['available_variants']}\n"
                "WARNING: This Kit extension, older than the server, wrote the selection at the edit target, into the "
                f"stage's file, and takes no layer. Install this server's, {install_advice()}."
            )
        session = r["layer"] == "session"
        where = "in the session layer" if session else f"at the edit target, {r['written_to']}"
        files = f"{'the files' if session else 'the files beneath'} select {r['files_select'] or 'none'}"
        shows = f"{r['prim_path']} {r['variant_set']}={r['new_selection'] or 'none'}"
        if variant_name:
            if session:
                kept = "save_scene leaves it out of the file"
            elif r["written_to"].startswith(ROOT_LAYER):
                kept = "save_scene writes it into the file"
            else:
                # A sublayer Kit's Layer window made the edit target: save_scene writes the root layer alone.
                kept = f"save_scene writes only the root layer, not {r['written_to']}"
            first = f"Variant switched {where}: {shows} ({files}; {kept})"
        else:
            first = f"Variant selection cleared {where}: {shows} ({files})"
        lines = [first, f"Was: {r['old_selection'] or 'none'}. Available: {', '.join(r['available_variants'])}"]
        if r.get("note"):
            lines.append(f"Note: {r['note']}")
        return "\n".join(lines)

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
        bounds and bound materials, with B minus A, and the change in faces as a percentage when A has faces.

        Two modes:
        1. Two prims: prim_path_a and prim_path_b.
        2. Two variants: prim_path, variant_set, variant_a and variant_b; this mode wins when all four are given.

        Variant mode switches to each variant in turn in Kit's session layer, then puts that layer back exactly as it
        was, so no file and no selection changes. An unknown variant set or variant is refused, listing those there,
        and so is a prim inside an instance, naming the instance. For one prim's counts, use get_mesh_stats.
        """
        resp = bridge_call(client.compare_prims, prim_path_a, prim_path_b, prim_path, variant_set, variant_a, variant_b)
        r = resp["result"]
        a, b, d = r["a"], r["b"], r["delta"]

        # A change from 0 faces has no percentage; the extension sends 0 for it, which read as "+0%" (#105).
        faces_change = f"{d['face_reduction_pct']:+}%" if a["total_faces"] else "A has 0 faces"
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
            # Each delta its own sign: one sign, the faces', read "+-5" for vertices that fell as faces rose (#105).
            f"faces: {d['faces']:+} ({faces_change})",
            f"vertices: {d['vertices']:+}  triangles: {d['triangles']:+}  meshes: {d['meshes']:+}",
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
