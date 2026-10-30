"""
Recording handlers: start, stop, and frame retrieval.

A recording renders its camera at its size through a camera feed of its own (camera_feed.py), so the user's viewport,
its camera and its size never change (#25). Frames are numbered when they are taken, never twice (#69), and stop when
the stage changes or the camera goes, since the feed would render something else then.
"""

import asyncio
import base64
import json
import os
import time
from pathlib import Path

import carb
import omni.kit.app
import omni.timeline
import omni.usd

from ovmcp.core import capture
from ovmcp.core.formatter import format_frame_state
from ovmcp.core.recording import FrameClock, RecordingArgs, camera_error, recording_args, steps_per_frame

from ._utils import _get_active_camera_path, _get_stage, capture_feed_png
from .camera_feed import CameraFeed, discard, forget

ALREADY_ACTIVE = "Recording already active. Stop it first, or use force=True to override."


class _Session:
    """One recording: its feed, the frames taken and in flight, and why its frames stopped early, if they did."""

    def __init__(self, session_id: str, folder: str, args: RecordingArgs, camera_path: str, feed: CameraFeed):
        self.session_id = session_id
        self.folder = folder
        self.args = args
        self.camera_path = camera_path
        self.feed: CameraFeed | None = feed
        self.stage_id = omni.usd.get_context().get_stage_id()
        self.tracked: list[str] = []
        timeline = omni.timeline.get_timeline_interface()
        self.clock = FrameClock(steps_per_frame(timeline.get_time_codes_per_seconds() or 60.0, args.fps))
        self.frames: list[dict] = []
        # Frames taken and not yet written, by number: their sim_time and wall_time.
        self.taking: dict[int, tuple[float, float]] = {}
        self.tasks: set[asyncio.Future] = set()
        self.ended: str | None = None
        self.started = time.time()
        self.stopped = 0.0
        self.subscription = None

    def record(self, number: int, data: bytes) -> None:
        """Writes a frame taken; an empty file marks one that didn't come, so the frames keep their numbers."""
        sim_time, wall_time = self.taking.pop(number)
        try:
            (Path(self.folder) / f"frame_{number:05d}.png").write_bytes(data)
        except OSError as e:
            carb.log_warn(f"[MCP Recording] Frame {number} not written: {e}")
        self.frames.append({"frame": number, "sim_time": sim_time, "wall_time": wall_time})
        self.clock.done()


class _State:
    """The recording running, if any; whether one is starting; the last recording's folder, for its frames."""

    def __init__(self):
        self.session: _Session | None = None
        self.starting = False
        self.last_folder = ""


_state = _State()


def recording_active() -> bool:
    return _state.session is not None


def recording_note() -> str | None:
    """Why the running recording's frames stopped early, or None."""
    return _state.session.ended if _state.session is not None else None


# ---------------------------------------------------------------------------
# /recording/start
# ---------------------------------------------------------------------------


async def handle_recording_start(body: dict) -> dict:
    if _state.starting or _state.session is not None:
        # A start still waiting for its first frame can't be forced aside: it holds no session to end yet.
        if not body.get("force", False) or _state.starting:
            return {"status": "error", "error": ALREADY_ACTIVE}
        carb.log_warn("[MCP Bridge] Force-stopping previous recording")
        await _end(_state.session, write_metadata=False)

    try:
        args = recording_args(body)
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    _state.starting = True
    try:
        return await _start(args)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    finally:
        _state.starting = False


async def _start(args: RecordingArgs) -> dict:
    stage = _get_stage()
    camera_path = args.camera_path or _get_active_camera_path()
    problem = camera_error(stage, camera_path)
    if problem:
        return {"status": "error", "error": problem}

    context = omni.usd.get_context()
    stage_id = context.get_stage_id()
    feed = CameraFeed(camera_path, args.width, args.height)
    try:
        # The bound a viewport frame gets, sized for a renderer's cold start (#27).
        await feed.first_frame(capture.FRAME_SECONDS)
        if context.get_stage_id() != stage_id:
            raise RuntimeError("The stage changed while the recording started: start it again")
        session_id = f"rec_{int(time.time())}"
        folder = os.path.join(args.output_dir, session_id)
        Path(folder).mkdir(parents=True, exist_ok=True)
        session = _Session(session_id, folder, args, camera_path, feed)
        session.tracked = _tracked_paths(stage, args.track_prims)
        if session.tracked:
            _write_state_header(session)
    except BaseException:
        # Nothing of a start that failed stays: not the texture, nor its render product on the stage.
        discard(feed)
        raise

    session.subscription = (
        omni.kit.app.get_app()
        .get_update_event_stream()
        .create_subscription_to_pop(lambda _event: _on_update(session), name=f"mcp_recording_{session_id}")
    )
    _state.session = session
    _state.last_folder = folder
    return {
        "status": "success",
        "result": {
            "session_id": session_id,
            "output_dir": folder,
            "fps": args.fps,
            "resolution": [args.width, args.height],
            "camera_path": camera_path,
            # Also tells the server this extension records from the camera at the size: an older one sent none.
            "render_product": feed.render_product_path,
            "track_prims": len(session.tracked),
            "property_filter": args.property_filter,
        },
    }


def _tracked_paths(stage, roots: list[str]) -> list[str]:
    """The tracked prims and their descendants, through instances, as the state file lists them."""
    from pxr import Usd

    paths = []
    for path in roots:
        root = stage.GetPrimAtPath(path)
        if root.IsValid():
            paths.extend(str(p.GetPath()) for p in Usd.PrimRange(root, Usd.TraverseInstanceProxies()))
    return paths


def _write_state_header(session: _Session) -> None:
    args = session.args
    lines = [
        "# Omniverse MCP Recording State",
        "# format = omniverse-mcp-v1",
        f"# session = {session.session_id}",
        f"# fps = {args.fps}",
        f"# tracked_prims = {len(session.tracked)}",
    ]
    if args.property_filter:
        lines.append(f"# property_filter = {', '.join(args.property_filter)}")
    lines.append(f"# track_roots = {', '.join(args.track_prims)}")
    (Path(session.folder) / "state.txt").write_text("\n".join(lines) + "\n\n")


# ---------------------------------------------------------------------------
# Each update
# ---------------------------------------------------------------------------


def _why_frames_stop(session: _Session) -> str | None:
    """Why the feed can no longer render the recording's camera, or None."""
    context = omni.usd.get_context()
    if context.get_stage_state() != omni.usd.StageState.OPENED:
        return "the stage began to close"
    if context.get_stage_id() != session.stage_id:
        # The feed would go on rendering the new stage, from its default camera (#25's E13).
        return "the stage changed"
    stage = context.get_stage()
    if camera_error(stage, session.camera_path):
        # A deleted camera renders white frames, with no error from Kit (#25's E8). Said plainly: camera_error's
        # wording is for a start, and its advice to look for another prim doesn't fit a recording under way.
        deleted = not stage.GetPrimAtPath(session.camera_path).IsValid()
        return f"the camera is gone: {session.camera_path} {'was deleted' if deleted else 'is no longer a Camera'}"
    return None


def _stop_frames(session: _Session, reason: str) -> None:
    sim_time = omni.timeline.get_timeline_interface().get_current_time()
    session.ended = f"frames stopped after {session.clock.taken}, at {sim_time:.2f} s of simulation: {reason}"
    carb.log_warn(f"[MCP Recording] {session.session_id}: {session.ended}")
    # Frames in flight would wait out their bounds for a frame that won't come: each ends now, as an empty file.
    for task in session.tasks:
        task.cancel()
    feed, session.feed = session.feed, None
    if feed is not None:
        discard(feed)


def _on_update(session: _Session) -> None:
    feed = session.feed
    if feed is None:
        return
    reason = _why_frames_stop(session)
    if reason:
        _stop_frames(session, reason)
        return
    number = session.clock.tick(render_pending=feed.waiting)
    if number is None:
        return
    # Read now, not when the capture ends: the frame shows this update's simulation, give or take one (#25's E17).
    sim_time = omni.timeline.get_timeline_interface().get_current_time()
    session.taking[number] = (sim_time, time.time() - session.started)
    if session.tracked:
        _write_state(session, number, sim_time)
    task = asyncio.ensure_future(_take_frame(session, feed, number))
    session.tasks.add(task)
    task.add_done_callback(session.tasks.discard)


def _write_state(session: _Session, number: int, sim_time: float) -> None:
    try:
        stage = _get_stage()
        prims = [stage.GetPrimAtPath(p) for p in session.tracked]
        text = format_frame_state(
            prims, frame_index=number, sim_time=sim_time, property_filter=session.args.property_filter
        )
        with (Path(session.folder) / "state.txt").open("a") as f:
            f.write(text)
            f.write("\n")
    except Exception as e:
        carb.log_warn(f"[MCP Recording] Frame {number} state capture failed: {e}")


async def _take_frame(session: _Session, feed: CameraFeed, number: int) -> None:
    data = b""
    try:
        data = await capture_feed_png(feed)
    except capture.CaptureError as e:
        carb.log_warn(f"[MCP Recording] Frame {number} not captured: {e}")
    finally:
        # Cancelled too, when frames stop early: the frame is then the empty marker at once.
        session.record(number, data)


# ---------------------------------------------------------------------------
# /recording/stop
# ---------------------------------------------------------------------------


async def _end(session: _Session, write_metadata: bool) -> tuple[str | None, list[str]]:
    """Ends `session`: its updates, its frames in flight, its feed and render product, then its metadata.json. Each
    step on its own, so one that fails leaves the rest done; what failed comes back, with the metadata file's path."""
    _state.session = None
    session.subscription = None
    session.stopped = time.time()
    problems = []
    if session.tasks:
        await asyncio.gather(*list(session.tasks), return_exceptions=True)
    # A frame whose task was cancelled before it ever ran is still owed its empty marker.
    for number in list(session.taking):
        session.record(number, b"")
    feed, session.feed = session.feed, None
    if feed is not None:
        try:
            discard(feed)
        except Exception as e:
            problems.append(f"its render product {feed.render_product_path} was not deleted: {e}")
            carb.log_warn(f"[MCP Recording] {session.session_id}: {problems[-1]}")
    if not write_metadata:
        return None, problems
    args = session.args
    meta = {
        "session_id": session.session_id,
        "fps": args.fps,
        "resolution": [args.width, args.height],
        "camera_path": session.camera_path,
        "frame_count": session.clock.taken,
        "duration_seconds": round(session.stopped - session.started, 2),
        "track_prims": session.tracked,
        "property_filter": args.property_filter,
        "frames": sorted(session.frames, key=lambda f: f["frame"]),
    }
    if session.ended:
        meta["ended"] = session.ended
    meta_path = os.path.join(session.folder, "metadata.json")
    try:
        Path(meta_path).write_text(json.dumps(meta, indent=2))
    except OSError as e:
        problems.append(f"metadata.json was not written: {e}")
        carb.log_warn(f"[MCP Recording] {session.session_id}: {problems[-1]}")
        return None, problems
    return meta_path, problems


async def handle_recording_stop(_body: dict) -> dict:
    session = _state.session
    if session is None:
        return {"status": "error", "error": "No active recording"}

    meta_path, problems = await _end(session, write_metadata=True)
    state_path = os.path.join(session.folder, "state.txt")
    result = {
        "session_id": session.session_id,
        "output_dir": session.folder,
        "frame_count": session.clock.taken,
        "duration_seconds": round(session.stopped - session.started, 2),
        "metadata_file": meta_path,
        "state_file": state_path if os.path.exists(state_path) else None,
    }
    notes = [session.ended] if session.ended else []
    notes += problems
    if notes:
        result["note"] = "; ".join(notes)
    return {"status": "success", "result": result}


def shut_down() -> None:
    """At the extension's shutdown: ends a running recording's frames and feed, and deletes nothing, since the stage
    may be tearing down."""
    session, _state.session = _state.session, None
    if session is not None:
        session.subscription = None
        for task in session.tasks:
            task.cancel()
        feed, session.feed = session.feed, None
        if feed is not None:
            feed.drop()
        carb.log_info("[MCP Bridge] Stopped active recording on shutdown")
    forget()


# ---------------------------------------------------------------------------
# /recording/frame
# ---------------------------------------------------------------------------


async def handle_recording_frame(body: dict) -> dict:
    session_dir = body.get("session_dir", "")
    frame_index = body.get("frame_index", 0)

    if not session_dir:
        # Use current/last session
        session_dir = _state.last_folder
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
