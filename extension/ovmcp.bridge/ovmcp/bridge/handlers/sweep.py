"""The capture sweep (#157): a list of shots, each with its own pose, lens, variant selections and timeline time,
captured as one job on #158's board, the PNGs and a manifest written by Kit into `<output>/sweeps/<name>/`, as a
recording's frames are.

It renders as a recording does (handlers/recording.py): the captures' feed is lent at the start and handed back at the
end, so no RTX view is set up per shot (#114), and each shot takes its frame 20 of the feed's frames after its camera
is set (#57). The viewport lock is held for one shot at a time, so a capture or inspect_prim called meanwhile runs
between shots, never inside one, and for at most SHOT_SECONDS, so it keeps most of its own 80 s.

Every selection is written in the session layer through #155's switch, and its snapshot kept; at the end, a cancel and
an error included, each is restored, last first, so every layer is as it was; the timeline is put back and the sweep's
camera deleted. A stage that changed or began to close took its layers with it: its replacement is left alone (round 1,
P7).
"""

import asyncio
import json
import time
from importlib import import_module
from pathlib import Path

import carb
import carb.settings
import omni.timeline
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom

from ovmcp.core import capture, output, protocol, sweep
from ovmcp.core.jobs import Job, JobError
from ovmcp.core.recording import camera_error
from ovmcp.core.usd import floats, prim_spec, remove_child_spec
from ovmcp.core.variants import Snapshot
from ovmcp.core.xform import aim

from ._utils import CAMERA_SETTLE_FRAMES, _get_active_camera_path, _get_stage, _next_update, _settle_frames
from .camera import _capture_frame, _get_current_lighting_mode
from .camera_feed import _viewport, hand_back, lend, let_go_now
from .jobs import start_job
from .variants import refresh

# What a shot's own steps may raise, from Kit or USD (pxr's errors are RuntimeErrors) or the disk: that shot fails, and
# the sweep goes on. Anything else fails the sweep, which still puts everything back.
_SHOT_ERRORS = (RuntimeError, ValueError, OSError)
# What one step of the cleanup may raise, so that step fails alone and the next ones still run, as recording's _end.
_STEP_ERRORS = (RuntimeError, ValueError, OSError, AttributeError, KeyError, TypeError)

DEFAULT_SIZE = (1280, 720)


def _error(message: str) -> dict:
    return {"status": "error", "error": message}


def _write_png(folder: str, name: str, data: bytes) -> None:
    (Path(folder) / name).write_bytes(data)


def _write_json(path: str, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _make_folder(folder: str) -> bool:
    """Makes folder, its parents too; whether it is new, so a start the board refuses removes it again."""
    path = Path(folder)
    made = not path.is_dir()
    path.mkdir(parents=True, exist_ok=True)
    return made


def _holds_manifest(folder: str) -> bool:
    return (Path(folder) / sweep.MANIFEST).exists()


def _render_settings() -> dict:
    """The renderer and, under Path Tracing, its samples, so a twin taken under other settings shows why it differs
    (round 1, I10)."""
    settings = carb.settings.get_settings()
    mode = settings.get("/rtx/rendermode")
    found: dict = {"render_mode": mode}
    if mode == "PathTracing":
        found["samples_per_pixel"] = settings.get("/rtx/pathtracing/spp")
        found["total_samples"] = settings.get("/rtx/pathtracing/totalSpp")
    return found


class _Sweep:
    """One sweep: its shots and folder, what it wrote and must put back, its feed, and what each shot gave."""

    def __init__(self, shots: list[sweep.Shot], width: int, height: int, name: str, folder: str, stage_id: object):
        self.shots = shots
        self.width, self.height = width, height
        self.name = name
        self.folder = folder
        self.manifest_path = str(Path(folder) / sweep.MANIFEST)
        self.stage_id = stage_id
        self.job: Job | None = None
        self.taken: list[sweep.Taken] = []
        # The session layer's value at the start of each (prim, set) a shot names, and the values last written.
        self.start: sweep.Held = {}
        self.written: sweep.Held = {}
        self.snapshots: list[Snapshot] = []
        self.timeline: sweep.TimelineStart | None = None
        self.camera_made = False
        self.up_axis = "Z"
        self.clipping = sweep.CLIPPING_METRES
        self.feed = None
        # A capture that raised leaves the feed in doubt: released at the end, not kept (#141).
        self.doubted = False
        self.header: dict = {"name": name, "width": width, "height": height}
        self.started = time.monotonic()
        self.line: str | None = None

    # ----- the job -----

    async def run(self, job: Job) -> dict:
        self.job = job
        ended = "failed"
        try:
            # Its first step on an update of its own, as a script job's.
            await _next_update()
            await self._begin()
            await self._shoot()
            ended = ""
        except asyncio.CancelledError:
            ended = f"cancelled: {job.cancel_reason or 'cancelled'}"
            raise
        except Exception as e:
            ended = f"failed: {e}"
            raise
        finally:
            await self._end(ended)
        return sweep.result(self.folder, self.manifest_path, len(self.shots), self.taken)

    def teardown(self) -> None:
        """At the extension's shutdown, which can't await: everything put back at once, the feed torn down as a
        recording's is (let_go_now), and the manifest written."""
        if self._same_stage():
            self._put_stage_back()
        feed, self.feed = self.feed, None
        if feed is not None:
            self._step("letting the feed go", lambda: let_go_now(feed))
        reason = self.job.cancel_reason if self.job is not None else ""
        self._finish(f"cancelled: {reason or 'the extension shut down'}")

    def _say(self, line: str) -> None:
        """A line of the job's progress, which get_job reads."""
        if self.job is not None:
            self.job.lines.write(output.STDOUT, f"{line}\n")

    # ----- the start -----

    async def _begin(self) -> None:
        stage = _get_stage()
        session = stage.GetSessionLayer()
        self.start = sweep.held(session, sweep.named(self.shots))
        self.written = dict(self.start)
        self.timeline = sweep.TimelineStart.read(omni.timeline.get_timeline_interface())
        self.up_axis = str(UsdGeom.GetStageUpAxis(stage))
        meters_per_unit = UsdGeom.GetStageMetersPerUnit(stage)
        self.clipping = sweep.clipping_range(meters_per_unit)
        self._make_camera(stage)
        self.header.update(
            {
                "stage": stage.GetRootLayer().identifier,
                "up_axis": self.up_axis,
                "meters_per_unit": meters_per_unit,
                "time_codes_per_second": stage.GetTimeCodesPerSecond(),
                "kit_app": protocol.kit_app(),
                **_render_settings(),
                "lighting_mode": _get_current_lighting_mode(),
                "camera": sweep.CAMERA_PATH,
                "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
        )
        # At once, so a second sweep given this name is refused while this one runs.
        self._write_manifest("working")
        self.feed = await lend(sweep.CAMERA_PATH, self.width, self.height)
        # The bound a viewport frame gets, sized for a renderer's cold start (#27); at once for a kept feed.
        await self.feed.first_frame(capture.FRAME_SECONDS)

    def _make_camera(self, stage: Usd.Stage) -> None:
        """The sweep's camera, in the session layer as Kit's own are, so no file changes, with Isaac Sim's clipping
        range, where USD's default cuts the floor in front of a camera 0.65 m above it (round 1, P2)."""
        with Usd.EditContext(stage, Usd.EditTarget(stage.GetSessionLayer())):
            camera = UsdGeom.Camera.Define(stage, sweep.CAMERA_PATH)
            camera.GetClippingRangeAttr().Set(Gf.Vec2f(*self.clipping))
        self.camera_made = True

    # ----- the shots -----

    async def _shoot(self) -> None:
        count = len(self.shots)
        for index, shot in enumerate(self.shots, 1):
            if self.job is not None:
                self.job.message = f"shot {index} of {count}"
            frames = self.feed.frames
            # For this shot alone (round 1, I9): a capture called meanwhile runs between shots.
            async with _viewport.get():
                taken = await self._take(index, shot)
            self.taken.append(taken)
            if taken.error is not None:
                self._say(f"shot {index} of {count} failed: {taken.error}")
                if taken.capture_failed and self.feed.frames == frames:
                    # The feed rendered nothing in the shot's time: every shot after would wait the same.
                    raise RuntimeError(
                        f"The camera feed rendered no frame for shot {index} in {sweep.SHOT_SECONDS:g} s, so the "
                        "shots after it weren't taken"
                    )
            if index % sweep.PROGRESS_EVERY == 0 and index < count:
                done = sum(1 for t in self.taken if t.file is not None)
                self._say(f"shot {index} of {count}: {done} taken")
                # An index of the files taken, should Kit hang mid-sweep (#162; round 1, I7).
                self._write_manifest("working")
        if self.job is not None:
            self.job.message = ""

    async def _take(self, index: int, shot: sweep.Shot) -> sweep.Taken:
        """One shot, holding the viewport lock, its waits within SHOT_SECONDS: its selections written, its time set,
        its camera aimed, its frame taken and written. What fails is the shot's, recorded with why."""
        taken = sweep.Taken(index, shot)
        budget = capture.Budget(sweep.SHOT_SECONDS)
        stage = _get_stage()
        session = stage.GetSessionLayer()
        timeline = omni.timeline.get_timeline_interface()

        out = sweep.changes(self.start, self.written, shot)
        if out:
            try:
                self.snapshots += sweep.switch(stage, out, session)
            except ValueError as e:
                taken.error = f"its selections were refused: {e}"
                return taken
            self.written = sweep.written_after(self.written, out)
            await refresh(stage, [Sdf.Path(prim) for prim in out])
            await self._wait_for_loading(taken, budget)

        if shot.time is not None:
            sweep.TimelineStart.seek(timeline, shot.time)
        elif self.timeline is not None:
            self.timeline.restore(timeline)

        try:
            camera_path = self._point_camera(stage, shot, taken, timeline)
        except ValueError as e:
            taken.error = str(e)
            return taken

        feed = self.feed
        try:
            feed.aim(camera_path, self.width, self.height)
            # A camera moved, or a stage switched, just before shows only frames later (#51's E14, #57); Path Tracing
            # renders its samples too.
            await feed.wait_frames(CAMERA_SETTLE_FRAMES + _settle_frames(), budget)
            png, is_black = await _capture_frame(feed, budget)
        except _SHOT_ERRORS as e:
            self.doubted = True
            taken.error = f"not captured: {e}"
            taken.capture_failed = True
            return taken

        file = sweep.file_name(index, shot)
        try:
            _write_png(self.folder, file, png)
        except OSError as e:
            taken.error = f"{file} not written: {e}"
            return taken
        taken.file = file
        taken.is_black = is_black
        taken.timeline_time = timeline.get_current_time()
        taken.frame = taken.timeline_time * stage.GetTimeCodesPerSecond()
        return taken

    async def _wait_for_loading(self, taken: sweep.Taken, budget: capture.Budget) -> None:
        """Until the stage has loaded what the switch brought in, LOADING_SECONDS at most: a variant whose payloads,
        materials or textures are captured part loaded differs from its twin (fit I5). Past the bound the shot is
        taken anyway, and says so."""
        context = omni.usd.get_context()
        started = time.monotonic()
        loaded = await capture.poll(
            context.get_stage_loading_status,
            lambda status: not sweep.still_loading(status),
            _next_update,
            sweep.LOADING_SECONDS,
            budget,
        )
        taken.loading_seconds = time.monotonic() - started
        if loaded is None:
            _, done, total = context.get_stage_loading_status()
            taken.loading = f"taken still loading, {done} of {total} files, after {taken.loading_seconds:.1f} s"

    def _point_camera(self, stage: Usd.Stage, shot: sweep.Shot, taken: sweep.Taken, timeline) -> str:
        """The camera the shot renders through, aimed and its lens set: the sweep's own, or a camera_path as it is,
        checked after the shot's switch, which may have removed it (a missing camera renders white), its pose and lens
        recorded so a rerun on another scene takes the same view (round 1, P5). ValueError when it can't."""
        if shot.camera_path:
            problem = camera_error(stage, shot.camera_path)
            if problem:
                raise ValueError(problem)
            camera = UsdGeom.Camera(stage.GetPrimAtPath(shot.camera_path))
            code = Usd.TimeCode(timeline.get_current_time() * stage.GetTimeCodesPerSecond())
            matrix = camera.ComputeLocalToWorldTransform(code)
            x, y, z = floats(matrix.ExtractTranslation())
            taken.position = (x, y, z)
            taken.yaw, taken.pitch = sweep.yaw_pitch(matrix.TransformDir(Gf.Vec3d(0, 0, -1)), self.up_axis)
            horizontal = float(camera.GetHorizontalApertureAttr().Get(code))
            # Kit renders a camera matching its horizontal aperture, its vertical one fitted to the image (the
            # viewport's default aperture conform): what it rendered with, which a rerun's own camera takes.
            taken.lens = sweep.Lens(
                float(camera.GetFocalLengthAttr().Get(code)), horizontal, horizontal * self.height / self.width
            )
            near, far = camera.GetClippingRangeAttr().Get(code)
            taken.clipping = (float(near), float(far))
            return shot.camera_path
        session = stage.GetSessionLayer()
        prim = stage.GetPrimAtPath(sweep.CAMERA_PATH)
        eye, target = sweep.pose(shot, self.up_axis)
        # In the session layer: aim's default would put the new camera's ops in the root layer (round 1, P3).
        aim(prim, eye, target, session)
        lens = shot.lens or sweep.default_lens(self.width, self.height)
        taken.clipping = shot.clipping or self.clipping
        camera = UsdGeom.Camera(prim)
        with Usd.EditContext(stage, Usd.EditTarget(session)):
            camera.GetFocalLengthAttr().Set(lens.focal_length)
            camera.GetHorizontalApertureAttr().Set(lens.horizontal_aperture)
            camera.GetVerticalApertureAttr().Set(lens.vertical_aperture)
            camera.GetClippingRangeAttr().Set(Gf.Vec2f(*taken.clipping))
        return sweep.CAMERA_PATH

    # ----- the end -----

    async def _end(self, ended: str) -> None:
        """Everything put back, each step on its own so one that raises can't stop the rest (round 2, P12): the
        selections, the timeline and the camera, unless the stage went; the manifest and the summary line, the job's
        last; then the feed handed back, kept for the next capture when healthy (#141)."""
        if self._same_stage():
            self._put_stage_back()
        self._finish(ended)
        feed, self.feed = self.feed, None
        if feed is not None:
            try:
                await hand_back(feed, self.stage_id, healthy=not self.doubted)
            except _STEP_ERRORS as e:
                carb.log_warn(f"[MCP Sweep] Its render product {feed.render_product_path} was not deleted: {e}")

    def _same_stage(self) -> bool:
        context = omni.usd.get_context()
        return context.get_stage_id() == self.stage_id and context.get_stage_state() == omni.usd.StageState.OPENED

    def _put_stage_back(self) -> None:
        snapshots, self.snapshots = self.snapshots, []
        for snapshot in reversed(snapshots):
            self._step("putting a selection back", snapshot.restore)
        start, self.timeline = self.timeline, None
        if start is not None:
            self._step("putting the timeline back", lambda: start.restore(omni.timeline.get_timeline_interface()))
        feed = self.feed
        if feed is not None and not feed.dropped:
            # Off the camera about to go, onto the one a capture takes by default: a deleted camera renders white.
            self._step(
                "pointing the feed at the viewport's camera",
                lambda: feed.aim(_get_active_camera_path(), self.width, self.height),
            )
        if self.camera_made:
            self.camera_made = False
            self._step("deleting its camera", self._delete_camera)

    def _delete_camera(self) -> None:
        session = _get_stage().GetSessionLayer()
        path = Sdf.Path(sweep.CAMERA_PATH)
        parent = prim_spec(session, path.GetParentPath())
        if parent is not None and prim_spec(session, path) is not None:
            remove_child_spec(parent, path.name)

    def _finish(self, ended: str) -> None:
        """The manifest of the shots done and the summary line, once."""
        if self.line is not None:
            return
        self.line = sweep.summary(self.folder, len(self.shots), self.taken, ended)
        self.header["seconds"] = round(time.monotonic() - self.started, 1)
        self._write_manifest(ended or "completed")
        self._say(self.line)

    def _write_manifest(self, ended: str) -> None:
        header = {**self.header, "ended": ended, "shots_asked": len(self.shots), "shots_done": len(self.taken)}
        manifest = sweep.manifest(header, self.taken)
        self._step(f"writing {self.manifest_path}", lambda: _write_json(self.manifest_path, manifest))

    def _step(self, what: str, step) -> None:
        try:
            step()
        except _STEP_ERRORS as e:
            carb.log_warn(f"[MCP Sweep] {what} failed: {e}")
            self._say(f"{what} failed: {e}")


# ---------------------------------------------------------------------------
# /jobs/sweep
# ---------------------------------------------------------------------------


async def handle_sweep_start(body: dict) -> dict:
    """Checks the whole sweep, then starts it as a job and answers at once with its id and its folder, which the
    agent then knows even if the sweep ends without a result (round 1, P6)."""
    root = body.get("output_dir")
    if not isinstance(root, str) or not root.strip():
        return _error("output_dir is required: the folder the sweep's own folder is made in")
    try:
        # The name alone, before it is joined to any path (round 1, P9).
        name = sweep.folder_name(body.get("name"))
        width, height = capture.frame_size(body.get("width", DEFAULT_SIZE[0]), body.get("height", DEFAULT_SIZE[1]))
        shots = sweep.read_shots(body.get("shots"), width, height)
    except ValueError as e:
        return _error(str(e))
    # A Kit app without them can't render a camera into a texture or capture one: said at the start, not per shot.
    for module in ("omni.kit.hydra_texture", "omni.kit.widget.viewport.capture"):
        try:
            import_module(module)
        except ImportError:
            return _error(f"This Kit app can't capture from a camera: it has no {module}")
    try:
        stage = _get_stage()
    except RuntimeError as e:
        return _error(str(e))
    reasons = sweep.refusals(stage, shots, stage.GetSessionLayer())
    if reasons:
        return _error("\n".join(reasons))
    if stage.GetPrimAtPath(sweep.CAMERA_PATH).IsValid():
        return _error(
            f"{sweep.CAMERA_PATH} is on the stage already, the camera of an earlier sweep that couldn't delete it: "
            "delete it with delete_prim, then start the sweep again"
        )
    folder = str(Path(root) / name)
    if _holds_manifest(folder):
        return _error(
            f"{folder} holds a sweep's {sweep.MANIFEST} already, and a sweep never writes over another's: give "
            "another name, or delete that folder"
        )
    try:
        made = _make_folder(folder)
    except OSError as e:
        return _error(f"Can't make the sweep's folder {folder} on the Kit app's machine: {e}")

    state = _Sweep(shots, width, height, name, folder, omni.usd.get_context().get_stage_id())
    label = f"{len(shots)} shots at {width}x{height}: {name}"
    try:
        job = start_job("sweep", label, state.run, watch_stage=True, teardown=state.teardown)
    except JobError as e:
        if made:
            _remove_empty(folder)
        return _error(str(e))
    return {
        "status": "success",
        "result": {
            "id": job.id,
            "kind": job.kind,
            "label": job.label,
            "folder": folder,
            "manifest": state.manifest_path,
            "shots": len(shots),
            "width": width,
            "height": height,
        },
    }


def _remove_empty(folder: str) -> None:
    try:
        Path(folder).rmdir()
    except OSError as e:
        carb.log_info(f"[MCP Sweep] {folder} stays: {e}")
