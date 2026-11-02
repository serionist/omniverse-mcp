"""The bridge's jobs (#158): long work that runs on Kit's loop as a task of its own, so Kit renders and other requests
are answered between its awaits, read and cancelled by id. A user's script is one kind of job; #157's capture sweep
is another, through the same board and the same routes.

One job at a time. Its states mirror an MCP task's (working, completed, failed, cancelled, with a status message),
with cancelling between a cancel and the end of the job's own cleanup, so a later binding of MCP's tasks maps one onto
the other. What a job prints is its progress: its lines, the last KEEP_LINES kept. The last job stays readable until
the next one starts. Kit-free: Kit's stage is watched by the caller's `watch`, handed in.
"""

import asyncio
import time
import traceback
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import output

WORKING = "working"
CANCELLING = "cancelling"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
RUNNING = frozenset({WORKING, CANCELLING})

# The lines a job keeps, of all it printed and of each stream for its output; and how long a line may grow without its
# end before it counts as one, so text printed with no line end can't grow without bound.
KEEP_LINES = 200
LONGEST_LINE = 10_000

SHUT_DOWN = "the extension shut down"


class JobError(Exception):
    """A request the board refuses; the message says why, and what to do."""


def _redrawn(text: str) -> str:
    """The text after its last carriage return, so a progress bar redrawn in place reads as its latest state; a
    carriage return at its very end stays, since a "\\n" may follow it in the next write."""
    cut = text.rfind("\r", 0, len(text) - 1)
    return text[cut + 1 :] if cut >= 0 else text


class Lines:
    """What a job printed, line by line: both streams in the order they came, the last KEEP_LINES kept with a count
    of all and of those a read has given; and each stream's own last KEEP_LINES, for its output once it ends.

    The job's sink (ovmcp.core.output): its task, and the tasks it starts, print here.
    """

    def __init__(self) -> None:
        self.closed = False
        self.count = 0
        self.seen = 0
        self._last: deque[str] = deque(maxlen=KEEP_LINES)
        self._pending = {output.STDOUT: "", output.STDERR: ""}
        self._kept: dict[str, deque[str]] = {stream: deque(maxlen=KEEP_LINES) for stream in self._pending}
        self._counts = dict.fromkeys(self._pending, 0)

    def write(self, stream: str, text: str) -> None:
        *ended, rest = (self._pending[stream] + text).split("\n")
        for line in ended:
            self._add(stream, line)
        rest = _redrawn(rest)
        if len(rest) > LONGEST_LINE:
            self._add(stream, rest)
            rest = ""
        self._pending[stream] = rest

    def flush(self) -> None:
        """The line each stream had begun, as a line: the job has ended."""
        for stream, rest in self._pending.items():
            if rest:
                self._add(stream, rest)
                self._pending[stream] = ""

    def _add(self, stream: str, line: str) -> None:
        line = _redrawn(line.removesuffix("\r"))
        self._last.append(line)
        self.count += 1
        self._kept[stream].append(line)
        self._counts[stream] += 1

    @property
    def last(self) -> str:
        return self._last[-1] if self._last else ""

    def unread(self) -> tuple[list[str], int]:
        """The lines since the last read, as many of them as are kept, and how many came; they count as read now."""
        new = self.count - self.seen
        self.seen = self.count
        return (list(self._last)[-new:] if new else []), new

    def kept(self) -> dict[str, Any]:
        """Each stream's kept lines as text, with how many lines it printed in all."""
        kept: dict[str, Any] = {}
        for stream, lines in self._kept.items():
            kept[stream] = "".join(f"{line}\n" for line in lines)
            kept[f"{stream}_lines"] = self._counts[stream]
        return kept


@dataclass(eq=False)
class Job:
    id: str
    kind: str  # "script", or "sweep" (#157)
    label: str
    started: float
    teardown: Callable[[], None] | None = None
    state: str = WORKING
    message: str = ""  # the MCP task's status message: why it was cancelled, what became of a cancel
    ended: float | None = None
    cancel_asked: float | None = None  # when the first cancel came
    cancel_reason: str = ""
    result: dict[str, Any] | None = None  # in its kind's shape
    error: str = ""
    traceback: str = ""
    lines: Lines = field(default_factory=Lines)
    watch: object = None  # the stage watch's guard, held while the job runs
    task: "asyncio.Task[None] | None" = None
    waiters: "list[asyncio.Future[None]]" = field(default_factory=list)

    def elapsed(self, now: float) -> float:
        return (self.ended if self.ended is not None else now) - self.started


Factory = Callable[[Job], Awaitable[dict[str, Any]]]


class JobBoard:
    """The job running, or the last one, and the starts, reads and cancels of them.

    `watch(job)`, given, watches Kit's stage for a job started with watch_stage, and returns a guard the board holds
    until the job ends: dropping it ends the watch.
    """

    def __init__(self, watch: Callable[[Job], object] | None = None, clock: Callable[[], float] = time.monotonic):
        self._watch = watch
        self._clock = clock
        self._job: Job | None = None
        self._made = 0
        self.closed = False

    def running(self) -> Job | None:
        """The job working or cancelling, or None."""
        job = self._job
        return job if job is not None and job.state in RUNNING else None

    def start(
        self,
        kind: str,
        label: str,
        factory: Factory,
        *,
        watch_stage: bool = False,
        teardown: Callable[[], None] | None = None,
    ) -> Job:
        """Starts `factory(job)` as a task of its own, so it outlives the request that started it, and returns the job
        at once. Its return is its result. A second start while one runs, or any after the shutdown, is a JobError.

        `teardown`, given, is called at the extension's shutdown while the job runs, which can't await its cleanup.
        """
        if self.closed:
            raise JobError(f"No job starts now: {SHUT_DOWN}. Turn the bridge on again, or restart the Kit app")
        running = self.running()
        if running is not None:
            raise JobError(
                f"Job {running.id} ({running.kind}) is {running.state}: one job runs at a time. Read it with get_job, "
                "or cancel it with cancel_job, and start this one once it has ended"
            )
        if watch_stage and self._watch is None:
            raise ValueError("This board was given no watch, so it can't watch the stage")
        job = Job(f"j{self._made + 1}", kind, label, started=self._clock(), teardown=teardown)
        if watch_stage and self._watch is not None:
            job.watch = self._watch(job)
        self._made += 1
        self._job = job
        job.task = asyncio.ensure_future(self._run(job, factory))
        job.task.add_done_callback(lambda task: self._ended(job, task))
        return job

    async def _run(self, job: Job, factory: Factory) -> None:
        with output.collect(job.lines):
            try:
                job.result = await factory(job)
            except SystemExit as e:
                # Raised out of a task, it would end Kit's loop: the job fails instead.
                raise RuntimeError(f"The job called sys.exit({e.code}), which would end Kit's loop") from e
            finally:
                job.lines.flush()

    def _ended(self, job: Job, task: "asyncio.Task[None]") -> None:
        """The job's end, once its task is done: its own cleanup has returned by then, so the next job may start."""
        if job.ended is not None:  # the shutdown ended it
            return
        job.ended = self._clock()
        job.watch = None
        if task.cancelled():
            job.state = CANCELLED
            job.message = job.cancel_reason or "cancelled"
        elif (error := task.exception()) is not None:
            job.state = FAILED
            job.error = str(error) or type(error).__name__
            job.traceback = "".join(traceback.format_exception(error))
        else:
            job.state = COMPLETED
            if job.cancel_asked is not None:
                job.message = (
                    f"it ran to its end {job.ended - job.cancel_asked:.1f} s after the cancel ({job.cancel_reason}), "
                    "which its code caught"
                )
        self._changed(job)

    def get(self, job_id: str = "") -> Job:
        """The job `job_id`, or with "", the running or the last job. JobError when there is none such."""
        job = self._job
        if job is None:
            raise JobError("No job has run since the bridge started: start one with run_script_job or capture_sweep")
        if job_id and job_id != job.id:
            raise JobError(
                f"No job {job_id}: the bridge keeps only the last job, {job.id} ({job.kind}, {job.state}), until the "
                "next one starts"
            )
        return job

    def cancel(self, job_id: str, reason: str) -> Job:
        """Cancels the job at its next await, `reason` passed through task.cancel(msg), so its cleanup can tell a
        user's cancel from a stage change. It is cancelling, and holds the slot, until its own cleanup has returned.
        A second cancel cancels again, for code whose bare except swallowed the first (round 1, P7). An ended job is
        left as it is."""
        job = self.get(job_id)
        if job.state not in RUNNING or job.task is None:
            return job
        if job.cancel_asked is None:
            job.cancel_asked = self._clock()
        job.cancel_reason = reason
        job.message = reason
        changed = job.state != CANCELLING
        job.state = CANCELLING
        job.task.cancel(reason)
        if changed:
            self._changed(job)
        return job

    async def wait(self, job: Job, seconds: float) -> None:
        """Until the job ends or its state changes, or `seconds` pass. A line printed doesn't end the wait, so a job
        that prints a line a step doesn't bring its reader back every few seconds (round 1, P3)."""
        if job.ended is not None or seconds <= 0:
            return
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        job.waiters.append(waiter)
        try:
            await asyncio.wait({waiter}, timeout=seconds)
        finally:
            if waiter in job.waiters:
                job.waiters.remove(waiter)

    def _changed(self, job: Job) -> None:
        for waiter in job.waiters:
            if not waiter.done():
                waiter.set_result(None)
        job.waiters.clear()

    def read(self, job: Job) -> dict[str, Any]:
        """The job as a read gives it: its state, its time, the lines since the last read, which count as read now,
        and once it ends, what it printed and its result, or its error."""
        now = self._clock()
        lines, new = job.lines.unread()
        answer: dict[str, Any] = {
            "id": job.id,
            "kind": job.kind,
            "label": job.label,
            "state": job.state,
            "message": job.message,
            "elapsed": round(job.elapsed(now), 3),
            "lines": lines,
            "lines_new": new,
            "lines_total": job.lines.count,
            "last": job.lines.last,
        }
        if job.state == CANCELLING and job.cancel_asked is not None:
            answer["cancelling"] = round(now - job.cancel_asked, 3)
        if job.ended is not None:
            answer["output"] = job.lines.kept()
        if job.state == COMPLETED:
            answer["result"] = job.result
        elif job.state == FAILED:
            answer["error"] = job.error
            answer["traceback"] = job.traceback
        return answer

    def brief(self) -> dict[str, Any] | None:
        """The running job in a few words, for get_sim_state; None when none runs."""
        job = self.running()
        if job is None:
            return None
        return {"id": job.id, "kind": job.kind, "state": job.state, "elapsed": round(job.elapsed(self._clock()), 3)}

    def shut_down(self) -> None:
        """At the extension's shutdown, which can't await, as recording's shut_down: no job starts after it (round 1,
        I16), and a running job's watch is dropped, its task cancelled and it reads cancelled, so nothing of it runs
        where no route could reach it; then its teardown is called, which undoes at once what its own cleanup, which
        may never run now, would have. A teardown that raises is the caller's to log."""
        self.closed = True
        job = self.running()
        if job is None:
            return
        job.watch = None
        if job.cancel_asked is None:
            job.cancel_asked = self._clock()
        job.cancel_reason = job.message = SHUT_DOWN
        if job.task is not None:
            job.task.cancel(SHUT_DOWN)
        job.state = CANCELLED
        job.ended = self._clock()
        self._changed(job)
        if job.teardown is not None:
            job.teardown()
