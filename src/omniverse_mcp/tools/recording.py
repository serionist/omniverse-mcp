"""Recording tools."""

import os


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
    def start_recording(
        fps: int = 5,
        width: int = 640,
        height: int = 480,
        camera_path: str = "",
        track_prims: list[str] | None = None,
        property_filter: list[str] | None = None,
    ) -> str:
        """Start recording simulation frames to disk.

        Captures a screenshot every 1/fps seconds while the simulation is playing.
        Frames are saved as PNGs in mcp_output/recordings/. Use stop_recording when done,
        then get_recording_frame to review any frame.

        Optionally tracks prim state (transforms, properties) alongside video frames.
        State is written to a grep-friendly state.txt in prim-block format.

        Args:
            fps: Capture rate (default 5 = one frame every 0.2s)
            width: Frame width
            height: Frame height
            camera_path: Camera to record from (default: active viewport)
            track_prims: Prim paths to track state for (includes descendants). E.g. ["/World/G1"]
            property_filter: Only record properties containing these substrings. E.g. ["joint", "pos", "vel"]
        """
        rec_dir = os.path.join(h.output_dir, "recordings")
        resp = _call(
            client.recording_start,
            rec_dir, fps, width, height, camera_path,
            track_prims=track_prims, property_filter=property_filter,
        )
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        msg = f"Recording {r['session_id']} at {r['fps']}fps -> {h.rel(r['output_dir'])}"
        if r.get("track_prims"):
            tp = r["track_prims"]
            count = len(tp) if isinstance(tp, list) else tp
            msg += f"\nTracking {count} prims"
        msg += "\nCall sim_control('play') to start."
        return msg

    @mcp.tool()
    def stop_recording() -> str:
        """Stop the active recording session.

        Returns session info and frame count. Use get_recording_frame to review frames.
        """
        resp = _call(client.recording_stop)
        err = _check_error(resp)
        if err:
            return err
        r = resp["result"]
        msg = f"Stopped. {r['frame_count']} frames, {r['duration_seconds']}s -> {h.rel(r['output_dir'])}"
        if r.get("state_file"):
            msg += f"\nState: {h.rel(r['state_file'])}"
        return msg

    @mcp.tool()
    def get_recording_frame(
        frame_index: int = 0,
        session_dir: str = "",
    ) -> str:
        """Get a specific frame from a recording session. Saves as PNG file.

        Args:
            frame_index: Frame number (0-based)
            session_dir: Session directory (uses last recording if empty)
        """
        resp = _call(client.recording_frame, session_dir, frame_index)
        err = _check_error(resp)
        if err:
            return err

        r = resp["result"]
        filepath = h.save_png(r["image_base64"], f"frame_{r['frame_index']:04d}")

        meta = f"Frame {r['frame_index']}"
        if "sim_time" in r:
            meta += f" t={r['sim_time']:.3f}s"
        return f"{meta} -> {filepath}"
