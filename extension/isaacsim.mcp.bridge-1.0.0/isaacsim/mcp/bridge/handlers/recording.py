"""
Recording handlers.

Handles recording start, stop, and frame retrieval.
"""

import asyncio
import base64
import json
import os
import time

import carb
import omni.kit.app

from ._utils import _get_active_camera_path, _get_stage, _next_update


# ---------------------------------------------------------------------------
# Global recording state (shared across handlers)
# ---------------------------------------------------------------------------

_recording_state = {
    "active": False,
    "session_id": None,
    "output_dir": None,
    "frame_count": 0,
    "fps": 5,
    "width": 640,
    "height": 480,
    "camera_path": "",
    "start_time": 0.0,
    "metadata": [],
    "callback_name": None,
    "_step_counter": 0,
    "_steps_per_frame": 1,
}


# ---------------------------------------------------------------------------
# /recording/start
# ---------------------------------------------------------------------------

async def handle_recording_start(body: dict) -> dict:
    global _recording_state

    force = body.get("force", False)
    if _recording_state["active"]:
        if force:
            # Force-stop the existing recording
            _recording_state["active"] = False
            _recording_state.pop("_sub", None)
            carb.log_warn("[MCP Bridge] Force-stopping previous recording")
        else:
            return {"status": "error", "error": "Recording already active. Stop it first, or use force=True to override."}

    output_dir = body.get("output_dir", "")
    fps = body.get("fps", 5)
    width = body.get("width", 640)
    height = body.get("height", 480)
    camera_path = body.get("camera_path", "")
    track_prims = body.get("track_prims", [])
    property_filter = body.get("property_filter", None)

    if not output_dir:
        return {"status": "error", "error": "output_dir is required"}

    if not camera_path:
        camera_path = _get_active_camera_path()

    session_id = f"rec_{int(time.time())}"
    session_dir = os.path.join(output_dir, session_id)
    os.makedirs(session_dir, exist_ok=True)

    timeline = omni.timeline.get_timeline_interface()
    sim_fps = timeline.get_time_codes_per_seconds() or 60.0
    steps_per_frame = max(1, int(sim_fps / fps))

    # Resolve tracked prims (expand to include descendants)
    tracked_prim_paths = []
    if track_prims:
        stage = _get_stage()
        if stage:
            from pxr import Usd
            for path in track_prims:
                root = stage.GetPrimAtPath(path)
                if root.IsValid():
                    for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
                        tracked_prim_paths.append(str(p.GetPath()))

    _recording_state.update({
        "active": True,
        "session_id": session_id,
        "output_dir": session_dir,
        "frame_count": 0,
        "fps": fps,
        "width": width,
        "height": height,
        "camera_path": camera_path,
        "start_time": time.time(),
        "metadata": [],
        "_step_counter": 0,
        "_steps_per_frame": steps_per_frame,
        "track_prims": tracked_prim_paths,
        "property_filter": property_filter,
    })

    # Write state file header if tracking prims
    if tracked_prim_paths:
        state_path = os.path.join(session_dir, "state.txt")
        with open(state_path, "w") as f:
            f.write(f"# Isaac Sim MCP Recording State\n")
            f.write(f"# format = isaacsim-mcp-v1\n")
            f.write(f"# session = {session_id}\n")
            f.write(f"# fps = {fps}\n")
            f.write(f"# tracked_prims = {len(tracked_prim_paths)}\n")
            if property_filter:
                f.write(f"# property_filter = {', '.join(property_filter)}\n")
            f.write(f"# track_roots = {', '.join(track_prims)}\n")
            f.write(f"\n")

    # Register a physics callback to capture frames
    callback_name = f"mcp_recording_{session_id}"
    _recording_state["callback_name"] = callback_name

    async def _record_tick(sim_time_seconds: float):
        """Called from the app update loop to capture frames.

        Args:
            sim_time_seconds: Simulation time captured synchronously in _on_update
                so it reflects the actual physics time, not a stale value from
                an async delay.
        """
        if not _recording_state["active"]:
            return

        frame_idx = _recording_state["frame_count"]
        try:
            import tempfile
            from omni.kit.viewport.utility import capture_viewport_to_file, get_active_viewport

            viewport = get_active_viewport()
            if viewport is None:
                return

            # Capture to temp file, then move to final location
            tmp_path = os.path.join(tempfile.gettempdir(), f"mcp_rec_{frame_idx}.png")
            cap = capture_viewport_to_file(viewport, file_path=tmp_path)
            await cap.wait_for_result()

            # Wait for file flush
            for _ in range(10):
                await _next_update()
                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    break

            frame_path = os.path.join(
                _recording_state["output_dir"],
                f"frame_{frame_idx:05d}.png",
            )

            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                import shutil
                shutil.move(tmp_path, frame_path)
            else:
                # File not ready — write empty marker
                with open(frame_path, "wb") as f:
                    pass

            _recording_state["metadata"].append({
                "frame": frame_idx,
                "sim_time": sim_time_seconds,
                "wall_time": time.time() - _recording_state["start_time"],
            })

            # Capture prim state if tracking
            if _recording_state["track_prims"]:
                try:
                    from ..formatter import format_frame_state
                    stage = _get_stage()
                    if stage:
                        prims = [
                            stage.GetPrimAtPath(p)
                            for p in _recording_state["track_prims"]
                        ]
                        state_text = format_frame_state(
                            prims,
                            frame_index=frame_idx,
                            sim_time=sim_time_seconds,
                            property_filter=_recording_state["property_filter"],
                        )
                        state_path = os.path.join(
                            _recording_state["output_dir"], "state.txt"
                        )
                        with open(state_path, "a") as sf:
                            sf.write(state_text)
                            sf.write("\n")
                except Exception as state_err:
                    carb.log_warn(
                        f"[MCP Recording] Frame {frame_idx} state capture failed: {state_err}"
                    )

            _recording_state["frame_count"] = frame_idx + 1

        except Exception as e:
            carb.log_warn(f"[MCP Recording] Frame {frame_idx} capture failed: {e}")

    def _on_update(event):
        if not _recording_state["active"]:
            return
        _recording_state["_step_counter"] += 1
        if _recording_state["_step_counter"] % _recording_state["_steps_per_frame"] != 0:
            return
        # Capture sim time synchronously — the async _record_tick runs later
        # and timeline.get_current_time() may return stale/reset values by then.
        timeline = omni.timeline.get_timeline_interface()
        sim_time = timeline.get_current_time()
        asyncio.ensure_future(_record_tick(sim_time))

    app = omni.kit.app.get_app()
    _recording_state["_sub"] = app.get_update_event_stream().create_subscription_to_pop(
        _on_update, name=callback_name
    )

    return {
        "status": "success",
        "result": {
            "session_id": session_id,
            "output_dir": session_dir,
            "fps": fps,
            "resolution": [width, height],
            "camera_path": camera_path,
            "track_prims": len(tracked_prim_paths),
            "property_filter": property_filter,
        },
    }


# ---------------------------------------------------------------------------
# /recording/stop
# ---------------------------------------------------------------------------

async def handle_recording_stop(_body: dict) -> dict:
    global _recording_state

    if not _recording_state["active"]:
        return {"status": "error", "error": "No active recording"}

    _recording_state["active"] = False

    # Unsubscribe
    _recording_state["_sub"] = None  # Releases subscription via destructor

    # Write metadata
    meta_path = os.path.join(_recording_state["output_dir"], "metadata.json")
    meta = {
        "session_id": _recording_state["session_id"],
        "fps": _recording_state["fps"],
        "resolution": [_recording_state["width"], _recording_state["height"]],
        "camera_path": _recording_state["camera_path"],
        "frame_count": _recording_state["frame_count"],
        "duration_seconds": round(time.time() - _recording_state["start_time"], 2),
        "track_prims": _recording_state.get("track_prims", []),
        "property_filter": _recording_state.get("property_filter"),
        "frames": _recording_state["metadata"],
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Check if state file was written
    state_file = None
    state_path = os.path.join(_recording_state["output_dir"], "state.txt")
    if os.path.exists(state_path):
        state_file = state_path

    return {
        "status": "success",
        "result": {
            "session_id": _recording_state["session_id"],
            "output_dir": _recording_state["output_dir"],
            "frame_count": _recording_state["frame_count"],
            "duration_seconds": meta["duration_seconds"],
            "metadata_file": meta_path,
            "state_file": state_file,
        },
    }


# ---------------------------------------------------------------------------
# /recording/frame
# ---------------------------------------------------------------------------

async def handle_recording_frame(body: dict) -> dict:
    session_dir = body.get("session_dir", "")
    frame_index = body.get("frame_index", 0)

    if not session_dir:
        # Use current/last session
        session_dir = _recording_state.get("output_dir", "")
    if not session_dir:
        return {"status": "error", "error": "No session_dir provided and no recent recording"}

    frame_path = os.path.join(session_dir, f"frame_{frame_index:05d}.png")
    if not os.path.exists(frame_path):
        return {"status": "error", "error": f"Frame not found: {frame_path}"}

    with open(frame_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    # Load metadata if available
    meta_path = os.path.join(session_dir, "metadata.json")
    frame_meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
        for fm in meta.get("frames", []):
            if fm.get("frame") == frame_index:
                frame_meta = fm
                break

    return {
        "status": "success",
        "result": {
            "frame_index": frame_index,
            "image_base64": b64,
            "format": "png",
            **frame_meta,
        },
    }
