"""Recording tools."""

import os
from typing import TYPE_CHECKING, Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from omniverse_mcp.client import BridgeClient

from ._annotations import EDITS, READS
from ._bridge import bridge_call

if TYPE_CHECKING:
    from omniverse_mcp.server import Helpers


def register(mcp: MCPServer, client: BridgeClient, h: "Helpers") -> None:
    @mcp.tool(annotations=EDITS)
    def start_recording(
        fps: Annotated[int, Field(ge=1, description="Frames a second: 5 captures one every 0.2 s")] = 5,
        width: Annotated[
            int, Field(ge=1, description="Frame width in pixels; for now frames keep the viewport's size (#25)")
        ] = 640,
        height: Annotated[
            int, Field(ge=1, description="Frame height in pixels; for now frames keep the viewport's size (#25)")
        ] = 480,
        camera_path: Annotated[
            str, Field(description="The camera to record from; for now frames come from the active viewport (#25)")
        ] = "",
        track_prims: Annotated[
            list[str] | None, Field(description='Prims whose state to record, descendants included, e.g. ["/World/G1"]')
        ] = None,
        property_filter: Annotated[
            list[str] | None,
            Field(description='Only properties whose names contain one of these, e.g. ["joint", "pos", "vel"]'),
        ] = None,
    ) -> str:
        """Start recording simulation frames to disk.

        Captures a screenshot every 1/fps seconds while the simulation is playing.
        Frames are saved as PNGs in mcp_output/recordings/. Use stop_recording when done,
        then get_recording_frame to review any frame.

        Optionally tracks prim state (transforms, properties) alongside video frames.
        State is written to a grep-friendly state.txt in prim-block format.
        """
        rec_dir = os.path.join(h.output_dir, "recordings")
        resp = bridge_call(
            client.recording_start,
            rec_dir,
            fps,
            width,
            height,
            camera_path,
            track_prims=track_prims,
            property_filter=property_filter,
        )
        r = resp["result"]
        msg = f"Recording {r['session_id']} at {r['fps']}fps -> {h.rel(r['output_dir'])}"
        if r.get("track_prims"):
            tp: list[str] | int = r["track_prims"]
            count = len(tp) if isinstance(tp, list) else tp
            msg += f"\nTracking {count} prims"
        msg += "\nCall sim_control('play') to start."
        return msg

    @mcp.tool(annotations=EDITS)
    def stop_recording() -> str:
        """Stop the active recording session.

        Returns session info and frame count. Use get_recording_frame to review frames.
        """
        resp = bridge_call(client.recording_stop)
        r = resp["result"]
        msg = f"Stopped. {r['frame_count']} frames, {r['duration_seconds']}s -> {h.rel(r['output_dir'])}"
        if r.get("state_file"):
            msg += f"\nState: {h.rel(r['state_file'])}"
        return msg

    @mcp.tool(annotations=READS)
    def get_recording_frame(
        frame_index: Annotated[int, Field(ge=0, description="The frame's number, from 0")] = 0,
        session_dir: Annotated[str, Field(description="The session's folder; the last recording when empty")] = "",
    ) -> str:
        """Get a specific frame from a recording session. Saves as PNG file."""
        resp = bridge_call(client.recording_frame, session_dir, frame_index)

        r = resp["result"]
        filepath = h.save_png(r["image_base64"], f"frame_{r['frame_index']:04d}")

        meta = f"Frame {r['frame_index']}"
        if "sim_time" in r:
            meta += f" t={r['sim_time']:.3f}s"
        return f"{meta} -> {filepath}"
