"""Job handlers: start a script as a job, read a job, cancel it (#158).

A job runs on Kit's loop as a task of its own (ovmcp.core.jobs), so Kit renders, physics steps and other requests are
answered between its awaits, and it outlives the request that started it. The routes are every kind's: a script now,
#157's capture sweep later, read and cancelled through the same /jobs/get and /jobs/cancel.
"""

from collections.abc import Callable

import omni.usd

from ovmcp.core import script
from ovmcp.core.jobs import WORKING, Factory, Job, JobBoard, JobError

from ._updates import on_update
from ._utils import _next_update
from .misc import script_namespace

# A read's longest wait, under the server's 120 s for a call.
MAX_WAIT = 100.0
CANCELLED_BY_USER = "cancel_job was called"


def _why_stop(stage_id: int) -> str | None:
    """Why a job watching the stage it started on must stop, or None: as a recording's frames stop."""
    context = omni.usd.get_context()
    if context.get_stage_state() != omni.usd.StageState.OPENED:
        return "the stage began to close"
    if context.get_stage_id() != stage_id:
        return "the stage changed"
    return None


def _watch(job: Job) -> object:
    """Cancels `job` on the first update its stage has changed or begun to close, which also catches a stage opened
    from Kit's menu or a script; the guard returned ends the watch once dropped."""
    stage_id = omni.usd.get_context().get_stage_id()

    def check() -> None:
        if job.state != WORKING:
            return
        reason = _why_stop(stage_id)
        if reason:
            _board.cancel(job.id, reason)

    return on_update(f"job {job.id}", check)


_board = JobBoard(watch=_watch)


def start_job(
    kind: str,
    label: str,
    factory: Factory,
    *,
    watch_stage: bool = False,
    teardown: Callable[[], None] | None = None,
) -> Job:
    """Starts a job of any kind on the bridge's board: a script's here, #157's sweep with watch_stage and a teardown.
    JobError when one runs, or after the shutdown."""
    return _board.start(kind, label, factory, watch_stage=watch_stage, teardown=teardown)


def job_brief() -> dict | None:
    """The running job in a few words, for /sim/state; None when none runs."""
    return _board.brief()


def shut_down() -> None:
    """At the extension's shutdown: the running job is cancelled and torn down, and no job starts after it."""
    _board.shut_down()


def _error(message: str) -> dict:
    return {"status": "error", "error": message}


# ---------------------------------------------------------------------------
# /jobs/script
# ---------------------------------------------------------------------------


async def handle_job_script(body: dict) -> dict:
    code = body.get("code", "")
    file = body.get("file", "")
    if not isinstance(code, str) or not isinstance(file, str):
        return _error("code and file are text")
    if bool(code.strip()) == bool(file.strip()):
        return _error("Give the script as code or as file, one of them")
    if file.strip():
        try:
            source, filename = script.read_file(file.strip())
        except OSError as e:
            return _error(f"Can't read the script file {file.strip()} on the Kit app's machine: {e}")
        label = filename
    else:
        source, filename = code, script.FILENAME
        label = next((line.strip() for line in code.splitlines() if line.strip()), "")[:80]
    try:
        compiled = script.compile_script(source, filename)
    except (SyntaxError, ValueError) as e:
        return _error(f"The script doesn't compile: {e}")
    if not compiled.awaits:
        return _error(script.NEVER_AWAITS)

    namespace = script_namespace()

    async def run(_job: Job) -> dict:
        # Its first step on an update of its own, as an /execute script's.
        await _next_update()
        await script.run(compiled, namespace)
        return {"return_value": script.jsonable(namespace.get("result"))}

    try:
        job = start_job("script", label, run)
    except JobError as e:
        return _error(str(e))
    return {"status": "success", "result": {"id": job.id, "kind": job.kind, "label": job.label}}


# ---------------------------------------------------------------------------
# /jobs/get
# ---------------------------------------------------------------------------


async def handle_job_get(body: dict) -> dict:
    job_id = body.get("job_id", "")
    try:
        wait = min(max(float(body.get("wait", 0) or 0), 0.0), MAX_WAIT)
    except (TypeError, ValueError):
        return _error("wait is a number of seconds, 0 to 100")
    try:
        job = _board.get(str(job_id or ""))
    except JobError as e:
        return _error(str(e))
    await _board.wait(job, wait)
    return {"status": "success", "result": _board.read(job)}


# ---------------------------------------------------------------------------
# /jobs/cancel
# ---------------------------------------------------------------------------


async def handle_job_cancel(body: dict) -> dict:
    job_id = body.get("job_id", "")
    if not isinstance(job_id, str) or not job_id.strip():
        return _error("job_id is required: the id run_script_job answered, such as j3")
    try:
        before = _board.get(job_id.strip()).state
        job = _board.cancel(job_id.strip(), CANCELLED_BY_USER)
    except JobError as e:
        return _error(str(e))
    return {
        "status": "success",
        "result": {"id": job.id, "kind": job.kind, "state": job.state, "was": before, "message": job.message},
    }
