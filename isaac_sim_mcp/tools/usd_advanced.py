"""Advanced USD tools (mesh stats, flatten, export, variants, compare, material paths)."""


def register(mcp, client, h):
    def _call(fn, *args, **kwargs):
        """Call client method with connection error handling."""
        try:
            resp = fn(*args, **kwargs)
        except Exception as e:
            return {"status": "error", "error": f"Isaac Sim connection failed: {e}"}
        return resp

    def _check_error(resp):
        """Check response for errors, including traceback."""
        if resp["status"] == "error":
            msg = f"ERROR: {resp['error']}"
            tb = resp.get("traceback", "")
            if tb:
                # Include first 5 lines of traceback for diagnosis
                tb_lines = tb.strip().split("\n")
                msg += "\n" + "\n".join(tb_lines[-5:])
            return msg
        return None

    @mcp.tool()
    def get_mesh_stats(prim_path: str) -> str:
        """Get face/vertex/triangle counts for a mesh prim or subtree.

        Returns per-mesh breakdown and totals. Use for measuring geometry budget,
        shell reduction ratios, etc.

        Args:
            prim_path: Prim to analyze (includes all descendant meshes)
        """
        resp = _call(client.mesh_stats, prim_path)
        err = _check_error(resp)
        if err:
            return err
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

    @mcp.tool()
    def get_prim_face_count_tree(root: str = "/World", max_depth: int = 10) -> str:
        """Get scene tree with face counts per mesh and subtree totals.

        Like get_scene_tree but focused on geometry budget: each mesh shows
        face/vertex/triangle counts, each group shows subtree_faces total.

        Args:
            root: Starting prim path
            max_depth: Max traversal depth (default 10)
        """
        resp = _call(client.face_count_tree, root, max_depth)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return h.text_response(r["text"], "face_count_tree")

    @mcp.tool()
    def flatten_usd(output_path: str, input_path: str = "") -> str:
        """Flatten a USD file — resolve all references, payloads, sublayers into one file.

        If input_path is omitted, flattens the current stage.

        Args:
            output_path: Where to write the flattened USD file
            input_path: Source USD file (default: current stage)
        """
        resp = _call(client.flatten_usd, output_path, input_path)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return f"Flattened {r['input_path']} ({r['layer_count']} layers) -> {r['output_path']}"

    @mcp.tool()
    def export_prim_as_file(prim_path: str, output_path: str) -> str:
        """Export a prim subtree as a standalone USD file.

        Flattens the source (resolves all references) and includes materials
        even if they live outside the exported subtree. Output is self-contained.

        Args:
            prim_path: Root of the subtree to export
            output_path: Destination file (.usd/.usda/.usdc — defaults to .usdc)
        """
        resp = _call(client.export_prim, prim_path, output_path)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return (
            f"Exported {r['prim_path']} -> {r['output_path']}\n"
            f"Root: {r['target_root']}, Materials included: {r['materials_included']}, Up: {r['up_axis']}"
        )

    @mcp.tool()
    def set_variant_selection(prim_path: str, variant_set: str, variant_name: str) -> str:
        """Switch variant selection on a prim with proper viewport refresh.

        Includes Hydra rprim refresh workaround (activation toggle + frame pumping)
        to ensure the viewport renders the correct geometry after switching.

        Args:
            prim_path: Prim with variant sets
            variant_set: Name of the variant set (e.g., "model")
            variant_name: Variant to select (e.g., "shell")
        """
        resp = _call(client.set_variant_selection, prim_path, variant_set, variant_name)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return (
            f"Variant switched: {r['prim_path']} {r['variant_set']}={r['new_selection']} "
            f"(was: {r['old_selection']})\n"
            f"Available: {r['available_variants']}"
        )

    @mcp.tool()
    def create_variant_structure(
        prim_path: str,
        variant_set_name: str,
        variant_names: list[str],
        default_variant: str = "",
    ) -> str:
        """Create variant set boilerplate on a prim.

        Adds the variant set, creates empty variant bodies, and sets the default.

        Args:
            prim_path: Target prim
            variant_set_name: Name for the new variant set (e.g., "model")
            variant_names: List of variant names to create (e.g., ["focused", "shell"])
            default_variant: Which variant to select by default (default: first in list)
        """
        resp = _call(client.create_variant_structure, prim_path, variant_set_name, variant_names, default_variant)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return (
            f"Created variant set '{r['variant_set_name']}' on {r['prim_path']}\n"
            f"Variants: {r['variants_created']}\n"
            f"Default: {r['default_selection']}"
        )

    @mcp.tool()
    def compare_prims(
        prim_path_a: str = "",
        prim_path_b: str = "",
        prim_path: str = "",
        variant_set: str = "",
        variant_a: str = "",
        variant_b: str = "",
    ) -> str:
        """Compare two prims or two variants — mesh counts, bounds, materials.

        Two modes:
        1. Prim comparison: provide prim_path_a and prim_path_b
        2. Variant comparison: provide prim_path, variant_set, variant_a, variant_b

        Returns side-by-side stats with deltas. Properly clears BBoxCache between
        variant switches to avoid stale data.

        Args:
            prim_path_a: First prim (mode 1)
            prim_path_b: Second prim (mode 1)
            prim_path: Prim with variants (mode 2)
            variant_set: Variant set name (mode 2)
            variant_a: First variant name (mode 2)
            variant_b: Second variant name (mode 2)
        """
        resp = _call(client.compare_prims, prim_path_a, prim_path_b, prim_path, variant_set, variant_a, variant_b)
        err = _check_error(resp)
        if err:
            return err
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
            f"=== Delta (B - A) ===",
            f"faces: {sign}{d['faces']} ({sign}{d['face_reduction_pct']}%)",
            f"vertices: {sign}{d['vertices']}  triangles: {sign}{d['triangles']}  meshes: {sign}{d['meshes']}",
        ]
        return "\n".join(lines)

    @mcp.tool()
    def update_material_paths(old_prefix: str, new_prefix: str, prim_path: str = "/") -> str:
        """Bulk-update material reference paths in a subtree.

        Updates both relationship targets (material bindings) and asset path
        attributes (texture file paths) that start with old_prefix.

        Args:
            old_prefix: Path prefix to find (e.g., "/OldProject/Materials")
            new_prefix: Replacement prefix (e.g., "/World/Materials")
            prim_path: Root of subtree to update (default: entire stage)
        """
        resp = _call(client.update_material_paths, old_prefix, new_prefix, prim_path)
        err = _check_error(resp)
        if err:
            return err
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
