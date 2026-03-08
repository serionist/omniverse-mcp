"""Camera and viewport tools."""

import json
import os

from mcp.types import TextContent, ImageContent


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
    def capture_viewport(
        width: int = 640,
        height: int = 480,
        camera_path: str = "",
        include_image: bool = False,
    ) -> str | list[TextContent | ImageContent]:
        """Capture the viewport and save 3 files for scene understanding:

        1. **Viewport image** (PNG) -- what the camera sees
        2. **Bounding boxes** (TXT) -- screen-space bounding boxes mapping each visible prim to pixel coordinates
        3. **Instance segmentation** (PNG) -- each prim rendered as a unique color, with a legend mapping colors to prim paths

        Use files 2 and 3 to understand which prim is where in the viewport image.
        Set include_image=True to return the viewport image inline (uses more context but lets you see the scene directly).

        Args:
            width: Image width (default 640)
            height: Image height (default 480)
            camera_path: Camera prim path (default: active viewport)
            include_image: Return viewport image inline instead of only saving to file
        """
        resp = _call(client.capture_viewport, width, height, camera_path)
        err = _check_error(resp)
        if err:
            return err

        r = resp["result"]
        lines = []

        # 1. Save viewport image
        filepath = h.save_png(r["image_base64"], "viewport")
        capture_id = h.capture_counter  # snapshot counter for consistent filenames
        lines.append(f"Viewport: {r['width']}x{r['height']} -> {filepath}")
        if r.get("is_black"):
            has_lights = r.get("has_scene_lights", False)
            cam_light = r.get("camera_light_on", False)
            if not has_lights and not cam_light:
                lines.append("WARNING: Image is all-black. Scene has no lights and camera light is off. Use viewport_light tool to enable camera light.")
            elif not has_lights:
                lines.append("WARNING: Image is all-black. Scene has no lights (camera light is on but may need a recapture).")
            else:
                lines.append("WARNING: Image is all-black. Scene has lights but image is still dark — renderer may need warmup. Try recapturing.")

        # 2. Save screen-space bounding boxes
        bboxes = r.get("screen_bboxes", [])
        if bboxes:
            bbox_dir = os.path.join(h.output_dir, "captures")
            os.makedirs(bbox_dir, exist_ok=True)
            bbox_path = os.path.join(bbox_dir, f"viewport_{capture_id:04d}_bboxes.txt")
            with open(bbox_path, "w", encoding="utf-8") as f:
                f.write(f"# Screen-space bounding boxes ({r['width']}x{r['height']})\n")
                f.write(f"# Format: [x_min, y_min, x_max, y_max] in pixels\n\n")
                for b in bboxes:
                    sb = b["screen_bbox"]
                    f.write(f"[{b['prim_path']}]\n")
                    f.write(f"type = {b['type']}\n")
                    f.write(f"screen_bbox = [{sb[0]}, {sb[1]}, {sb[2]}, {sb[3]}]\n")
                    f.write(f"world_center = {b['world_center']}\n")
                    f.write(f"world_dimensions = {b['world_dimensions']}\n\n")
            lines.append(f"Bounding boxes ({len(bboxes)} prims) -> {h.rel(bbox_path)}")
        else:
            lines.append("Bounding boxes: none (no visible prims)")

        # 3. Save instance segmentation image + legend
        seg_b64 = r.get("segmentation_base64")
        legend = r.get("segmentation_legend", {})
        if seg_b64:
            seg_path = h.save_png(seg_b64, f"viewport_{capture_id:04d}_segmentation")
            if seg_path.startswith("ERROR"):
                lines.append(f"Segmentation: {seg_path}")
            else:
                legend_path = seg_path.replace(".png", "_legend.txt")
                abs_legend = os.path.join(os.getcwd(), legend_path) if not os.path.isabs(legend_path) else legend_path
                with open(abs_legend, "w", encoding="utf-8") as f:
                    f.write("# Instance segmentation color legend\n")
                    f.write("# Format: prim_path = [R, G, B]\n\n")
                    for prim_path, color in legend.items():
                        f.write(f"{prim_path} = [{color[0]}, {color[1]}, {color[2]}]\n")
                lines.append(f"Segmentation -> {seg_path}")
                lines.append(f"Color legend ({len(legend)} prims) -> {h.rel(abs_legend)}")
        else:
            lines.append("Segmentation: not available (omni.syntheticdata may not be loaded)")

        if include_image and r.get("image_base64"):
            content = [TextContent(type="text", text="\n".join(lines))]
            content.append(ImageContent(type="image", data=r["image_base64"], mimeType="image/png"))
            return content
        return "\n".join(lines)

    @mcp.tool()
    def set_camera(position: list[float], target: list[float] | None = None) -> str:
        """Set the viewport camera position and optionally aim it at a target point.

        Args:
            position: [x, y, z] camera position in world space
            target: [x, y, z] point to look at (optional)
        """
        resp = _call(client.camera_set, position, target)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        msg = f"Camera at {r['position']}"
        if r.get("target"):
            msg += f" looking at {r['target']}"
        return msg

    @mcp.tool()
    def look_at_prim(
        prim_path: str,
        distance: float | None = None,
        azimuth: float = 45.0,
        elevation: float = 30.0,
    ) -> str:
        """Point the viewport camera at a prim from a given angle.

        Auto-computes distance from object size if not specified.
        Azimuth 0=front, 90=right, 180=back, 270=left.

        Args:
            prim_path: Target prim to look at
            distance: Camera distance (auto if omitted)
            azimuth: Horizontal angle in degrees (0=front)
            elevation: Vertical angle in degrees above horizontal
        """
        resp = _call(client.camera_look_at, prim_path, distance, azimuth, elevation)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        return (
            f"Camera at {r['camera_position']} looking at {r['target']}\n"
            f"Distance: {r['distance']}m, Azimuth: {r['azimuth']}deg, Elevation: {r['elevation']}deg"
        )

    @mcp.tool()
    def inspect_prim(
        prim_path: str,
        angles: list[str] | None = None,
        width: int = 640,
        height: int = 480,
        distance: float | None = None,
        include_segmentation: bool = False,
    ) -> str:
        """Orbit-capture: take screenshots from 14 systematic angles around a prim (cube-based).

        Captures from all 6 face centers + 8 cube corners by default, giving full coverage.
        Saves each angle as a PNG file. Use Read tool to view images.

        Args:
            prim_path: Target prim
            angles: Angle names (default: all 14). Face centers: "front", "back", "right",
                    "left", "top", "bottom". Cube corners: "top_front_right",
                    "top_front_left", "top_back_right", "top_back_left",
                    "bottom_front_right", "bottom_front_left", "bottom_back_right",
                    "bottom_back_left". Pass a subset list to capture fewer angles.
            width: Image width per capture
            height: Image height per capture
            distance: Camera distance (auto-computed from object size if omitted)
            include_segmentation: Also capture instance segmentation at each angle
        """
        resp = _call(client.camera_inspect, prim_path, angles, width, height, distance, include_segmentation)
        err = _check_error(resp)
        if err:
            return err

        r = resp["result"]
        lines = [f"Inspect {prim_path} (dist={r['distance']}m)"]
        warned = False
        for cap in r["captures"]:
            if "error" in cap:
                lines.append(f"  {cap['angle']}: ERROR {cap['error']}")
            else:
                filepath = h.save_png(cap["image_base64"], f"inspect_{cap['angle']}")
                cap_line = f"  {cap['angle']}: {filepath}"
                if cap.get("segmentation_base64"):
                    seg_path = h.save_png(cap["segmentation_base64"], f"inspect_{cap['angle']}_seg")
                    cap_line += f" | seg: {seg_path}"
                    legend = cap.get("segmentation_legend", {})
                    if legend and not seg_path.startswith("ERROR"):
                        legend_path = seg_path.replace(".png", "_legend.txt")
                        abs_legend = os.path.join(os.getcwd(), legend_path) if not os.path.isabs(legend_path) else legend_path
                        with open(abs_legend, "w", encoding="utf-8") as f:
                            for pp, clr in legend.items():
                                f.write(f"{pp} = [{clr[0]}, {clr[1]}, {clr[2]}]\n")
                if cap.get("is_black") and not warned:
                    lines.append("  WARNING: One or more captures are all-black. Scene may have no lights. Use viewport_light tool to check and enable camera light.")
                    warned = True
                lines.append(cap_line)
        return "\n".join(lines)

    @mcp.tool()
    def viewport_light(action: str = "get", enabled: bool = True) -> str:
        """Query or control viewport lighting (camera light + scene lights).

        Actions:
        - "get": Return current lighting state (camera light on/off, scene lights list)
        - "set_camera_light": Enable or disable the viewport camera light (a fill light
          that follows the camera — non-destructive, does not modify the scene)

        When capture_viewport returns a black image, use this tool to check lighting
        and enable the camera light if needed, then recapture.

        Args:
            action: "get" or "set_camera_light"
            enabled: Whether to enable (true) or disable (false) camera light (for set_camera_light)
        """
        resp = _call(client.viewport_light, action, enabled)
        err = _check_error(resp)
        if err:
            return err

        r = resp["result"]
        lines = []
        if action == "get":
            lines.append(f"Camera light: {'ON' if r.get('camera_light_on') else 'OFF'}")
            lines.append(f"Scene has lights: {'yes' if r.get('has_scene_lights') else 'no'}")
            scene_lights = r.get("scene_lights", [])
            if scene_lights:
                lines.append(f"Scene lights ({len(scene_lights)}):")
                for lt in scene_lights:
                    lines.append(f"  {lt['path']} ({lt['type']}, intensity={lt.get('intensity', 'N/A')})")
            else:
                lines.append("No scene lights found. Consider enabling camera light or adding a light with create_prim.")
        elif action == "set_camera_light":
            state = "enabled" if r.get("camera_light_on") else "disabled"
            lines.append(f"Camera light {state}. Recapture viewport to see the effect.")
        else:
            lines.append(json.dumps(r, indent=2))
        return "\n".join(lines)
