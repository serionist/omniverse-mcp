"""ovmcp.core.jobs, Kit-free (#158): a job starts as a task of its own and answers at once; one runs at a time; a
cancel reaches its code with its reason, and the job holds the slot until its own cleanup has returned; what it prints
is its lines, the last 200 kept with a count, each read giving those since the last; a finished job is read until the
next starts; a read's wait ends early only on a change of state; the shutdown cancels, tears down and refuses."""

import asyncio
import contextlib
import sys
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest

from ovmcp.core import output
from ovmcp.core.jobs import (
    CANCELLED,
    CANCELLING,
    COMPLETED,
    FAILED,
    KEEP_LINES,
    LONGEST_LINE,
    SHUT_DOWN,
    WORKING,
    Job,
    JobBoard,
    JobError,
)


class Clock:
    """time.monotonic as the board reads it, moved by the test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _router_off() -> Iterator[None]:
    yield
    output.uninstall()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def board(clock: Clock) -> JobBoard:
    return JobBoard(clock=clock)


async def _turns(count: int = 5) -> None:
    """A few turns of the loop: a job's task, and the callbacks its end schedules, run in them."""
    for _ in range(count):
        await asyncio.sleep(0)


def _returning(value: dict[str, Any]) -> Callable[[Job], Awaitable[dict[str, Any]]]:
    async def factory(_job: Job) -> dict[str, Any]:
        await asyncio.sleep(0)
        return value

    return factory


def _held(gate: "asyncio.Future[None]") -> Callable[[Job], Awaitable[dict[str, Any]]]:
    async def factory(_job: Job) -> dict[str, Any]:
        await gate
        return {"done": True}

    return factory


# ----- starting and ending -----


def test_a_job_answers_at_once_and_ends_with_its_result(board, clock):
    async def main() -> tuple[str, dict[str, Any]]:
        job = board.start("script", "bake.py", _returning({"return_value": 7}))
        at_start = job.state
        clock.now += 4.5
        await _turns()
        return at_start, board.read(job)

    at_start, read = asyncio.run(main())

    assert at_start == WORKING
    assert read["id"] == "j1"
    assert (read["kind"], read["label"], read["state"]) == ("script", "bake.py", COMPLETED)
    assert read["result"] == {"return_value": 7}
    assert read["elapsed"] == 4.5


def test_one_job_runs_at_a_time(board):
    async def main() -> tuple[str, str, Job]:
        gate = asyncio.get_running_loop().create_future()
        board.start("script", "first", _held(gate))
        with pytest.raises(JobError) as refused:
            board.start("script", "second", _returning({}))
        gate.set_result(None)
        await _turns()
        second = board.start("script", "second", _returning({}))
        await _turns()
        with pytest.raises(JobError) as gone:
            board.get("j1")
        return str(refused.value), str(gone.value), second

    refused, gone, second = asyncio.run(main())

    assert refused.startswith("Job j1 (script) is working: one job runs at a time")
    assert second.id == "j2"
    assert "the bridge keeps only the last job, j2 (script, completed)" in gone


def test_get_with_no_id_is_the_running_or_the_last_job(board):
    with pytest.raises(JobError, match="No job has run"):
        board.get("")

    async def main() -> tuple[Job, Job]:
        gate = asyncio.get_running_loop().create_future()
        board.start("script", "", _held(gate))
        running = board.get("")
        gate.set_result(None)
        await _turns()
        return running, board.get("")

    running, last = asyncio.run(main())

    assert running is last
    assert last.state == COMPLETED
    assert board.running() is None


def test_a_finished_job_is_read_late_with_its_time_at_its_end(board, clock):
    async def main() -> Job:
        job = board.start("script", "", _returning({"return_value": [1, 2]}))
        clock.now += 2.0
        await _turns()
        return job

    job = asyncio.run(main())
    clock.now += 600.0

    read = board.read(job)
    assert (read["state"], read["result"], read["elapsed"]) == (COMPLETED, {"return_value": [1, 2]}, 2.0)


def test_a_failure_gives_its_error_and_its_traceback(board):
    async def failing(_job: Job) -> dict[str, Any]:
        await asyncio.sleep(0)
        raise ValueError("the stack fell over")

    async def main() -> Job:
        job = board.start("script", "", failing)
        await _turns()
        return job

    read = board.read(asyncio.run(main()))

    assert (read["state"], read["error"]) == (FAILED, "the stack fell over")
    assert 'raise ValueError("the stack fell over")' in read["traceback"]
    assert "result" not in read


def test_an_error_without_a_message_is_named_by_its_type(board):
    async def failing(_job: Job) -> dict[str, Any]:
        raise KeyError

    async def main() -> Job:
        job = board.start("script", "", failing)
        await _turns()
        return job

    assert asyncio.run(main()).error == "KeyError"


def test_sys_exit_fails_the_job_and_leaves_kits_loop_running(board):
    async def exiting(_job: Job) -> dict[str, Any]:
        sys.exit(3)

    async def main() -> Job:
        job = board.start("script", "", exiting)
        await _turns()
        return job

    job = asyncio.run(main())

    assert job.state == FAILED
    assert job.error == "The job called sys.exit(3), which would end Kit's loop"


# ----- cancelling -----


def test_a_cancelling_job_holds_the_slot_until_its_cleanup_returns(board, clock):
    seen: list[Any] = []

    async def bake(_job: Job) -> dict[str, Any]:
        try:
            await asyncio.get_running_loop().create_future()  # a step that never ends by itself
        except asyncio.CancelledError as e:
            seen.append(e.args)
            raise
        finally:
            # An async cleanup, as a sweep's that puts the stage back.
            await cleanup
            seen.append("cleaned up")
        return {}

    async def main() -> tuple[str, str, Job]:
        nonlocal cleanup
        cleanup = asyncio.get_running_loop().create_future()
        job = board.start("sweep", "", bake)
        await _turns()
        clock.now += 1.0
        board.cancel(job.id, "the stage changed")
        await _turns()
        state = job.state
        clock.now += 2.5
        cancelling = board.read(job)["cancelling"]
        with pytest.raises(JobError, match="is cancelling"):
            board.start("script", "", _returning({}))
        cleanup.set_result(None)
        await _turns()
        return state, cancelling, job

    cleanup: asyncio.Future[None]
    state, cancelling, job = asyncio.run(main())

    assert (state, cancelling) == (CANCELLING, 2.5)
    assert seen == [("the stage changed",), "cleaned up"]
    assert (job.state, job.message, job.cancel_reason) == (CANCELLED, "the stage changed", "the stage changed")
    assert board.running() is None


def test_a_second_cancel_cancels_a_script_that_swallowed_the_first(board):
    swallowed: list[str] = []

    async def stubborn(_job: Job) -> dict[str, Any]:
        while True:
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError as e:  # swallowed, as a bare except in a careless script does
                swallowed.append(str(e))
                break
        await asyncio.get_running_loop().create_future()
        return {}

    async def main() -> tuple[str, Job]:
        job = board.start("script", "", stubborn)
        await _turns()
        board.cancel(job.id, "cancel_job was called")
        await _turns()
        between = job.state
        board.cancel(job.id, "cancel_job was called again")
        await _turns()
        return between, job

    between, job = asyncio.run(main())

    assert swallowed == ["cancel_job was called"]
    assert between == CANCELLING
    assert (job.state, job.message) == (CANCELLED, "cancel_job was called again")


def test_a_job_that_runs_on_past_a_cancel_completes_and_says_so(board, clock):
    async def stubborn(_job: Job) -> dict[str, Any]:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0)
        clock.now += 3.0
        await asyncio.sleep(0)
        return {"return_value": "done anyway"}

    async def main() -> Job:
        job = board.start("script", "", stubborn)
        await asyncio.sleep(0)
        board.cancel(job.id, "cancel_job was called")
        await _turns()
        return job

    job = asyncio.run(main())

    assert job.state == COMPLETED
    assert job.result == {"return_value": "done anyway"}
    assert job.message == "it ran to its end 3.0 s after the cancel (cancel_job was called), which its code caught"


def test_a_job_cancelled_before_its_first_step_reads_cancelled(board):
    async def main() -> Job:
        job = board.start("script", "", _returning({}))
        board.cancel(job.id, "cancel_job was called")
        await _turns()
        return job

    job = asyncio.run(main())

    assert (job.state, job.message) == (CANCELLED, "cancel_job was called")


def test_a_cancel_of_an_ended_job_leaves_it(board):
    async def main() -> Job:
        job = board.start("script", "", _returning({"return_value": 1}))
        await _turns()
        return board.cancel(job.id, "cancel_job was called")

    job = asyncio.run(main())

    assert (job.state, job.message, job.cancel_asked) == (COMPLETED, "", None)


def test_a_cancel_of_another_id_is_refused(board):
    async def main() -> None:
        board.start("script", "", _returning({}))
        await _turns()

    asyncio.run(main())
    with pytest.raises(JobError, match="No job j9"):
        board.cancel("j9", "cancel_job was called")


# ----- lines -----


def _printing(*parts: tuple[str, str]) -> Callable[[Job], Awaitable[dict[str, Any]]]:
    """A job that prints each (stream, text) in turn, a turn of the loop after each."""

    async def factory(_job: Job) -> dict[str, Any]:
        for stream, text in parts:
            print(text, end="", file=sys.stdout if stream == output.STDOUT else sys.stderr)
            await asyncio.sleep(0)
        return {}

    return factory


def _ran(board: JobBoard, factory: Callable[[Job], Awaitable[dict[str, Any]]]) -> Job:
    async def main() -> Job:
        job = board.start("script", "", factory)
        await _turns(10)
        return job

    return asyncio.run(main())


def test_lines_are_kept_to_the_last_200_with_a_count_of_all(board):
    count = KEEP_LINES + 50

    async def chatty(_job: Job) -> dict[str, Any]:
        for i in range(count):
            print(f"stack {i} settled")
        await asyncio.sleep(0)
        return {}

    read = board.read(_ran(board, chatty))

    assert (read["lines_new"], read["lines_total"], len(read["lines"])) == (count, count, KEEP_LINES)
    assert read["lines"][0] == "stack 50 settled"
    assert read["last"] == f"stack {count - 1} settled"
    stdout = read["output"]["stdout"].splitlines()
    assert (len(stdout), read["output"]["stdout_lines"]) == (KEEP_LINES, count)
    assert stdout[-1] == f"stack {count - 1} settled"


def test_each_read_gives_the_lines_since_the_last(board):
    async def main() -> list[dict[str, Any]]:
        gates = [asyncio.get_running_loop().create_future() for _ in range(2)]

        async def stepping(_job: Job) -> dict[str, Any]:
            print("1 of 5\n2 of 5\n3 of 5")
            await gates[0]
            print("4 of 5\n5 of 5")
            await gates[1]
            return {}

        job = board.start("script", "", stepping)
        await _turns()
        reads = [board.read(job)]
        gates[0].set_result(None)
        await _turns()
        reads += [board.read(job), board.read(job)]
        gates[1].set_result(None)
        await _turns()
        return reads

    first, second, third = asyncio.run(main())

    assert (first["lines"], first["lines_new"], first["last"]) == (["1 of 5", "2 of 5", "3 of 5"], 3, "3 of 5")
    assert (second["lines"], second["lines_new"], second["lines_total"]) == (["4 of 5", "5 of 5"], 2, 5)
    assert (third["lines"], third["lines_new"], third["last"]) == ([], 0, "5 of 5")


def test_a_line_comes_whole_and_one_left_open_counts_at_the_end(board):
    job = _ran(
        board, _printing((output.STDOUT, "settling "), (output.STDOUT, "stack 3\r\n"), (output.STDOUT, "almost"))
    )

    read = board.read(job)
    assert read["lines"] == ["settling stack 3", "almost"]


def test_a_line_that_never_ends_counts_once_it_grows_too_long(board):
    job = _ran(board, _printing((output.STDOUT, "x" * (LONGEST_LINE + 1)), (output.STDOUT, "y\n")))

    assert [len(line) for line in board.read(job)["lines"]] == [LONGEST_LINE + 1, 1]


def test_stdout_and_stderr_come_in_order_in_the_lines_and_apart_in_the_output(board):
    job = _ran(board, _printing((output.STDOUT, "out 1\n"), (output.STDERR, "err 1\n"), (output.STDOUT, "out 2\n")))

    read = board.read(job)
    assert read["lines"] == ["out 1", "err 1", "out 2"]
    assert read["output"] == {"stdout": "out 1\nout 2\n", "stdout_lines": 2, "stderr": "err 1\n", "stderr_lines": 1}


def test_a_job_s_lines_are_its_own(board):
    # Another task's print, such as an /execute call's or a handler's, never lands in the job's lines.
    async def main() -> Job:
        gate = asyncio.get_running_loop().create_future()

        async def bake(_job: Job) -> dict[str, Any]:
            print("from the job")
            await gate
            return {}

        job = board.start("script", "", bake)
        await _turns()
        with output.collect(output.Printed()) as printed:
            print("from a call")
        gate.set_result(None)
        await _turns()
        assert printed.text(output.STDOUT) == "from a call\n"
        return job

    assert board.read(asyncio.run(main()))["lines"] == ["from the job"]


# ----- waiting -----


def test_a_wait_ends_on_a_change_of_state_not_on_a_line(board):
    async def main() -> list[tuple[str, bool]]:
        printed = asyncio.get_running_loop().create_future()
        seen: list[tuple[str, bool]] = []

        async def bake(_job: Job) -> dict[str, Any]:
            await printed
            print("1 of 150 stacks settled")
            await asyncio.get_running_loop().create_future()
            return {}

        job = board.start("script", "", bake)
        waiting = asyncio.ensure_future(board.wait(job, 30))
        await _turns()
        printed.set_result(None)
        await _turns()
        seen.append(("after a line", waiting.done()))
        board.cancel(job.id, "cancel_job was called")
        await _turns()
        seen.append(("after the cancel", waiting.done()))
        ending = asyncio.ensure_future(board.wait(job, 30))
        await _turns()
        seen.append(("after the end", ending.done()))
        return seen

    assert asyncio.run(main()) == [("after a line", False), ("after the cancel", True), ("after the end", True)]


def test_a_wait_ends_when_its_time_runs_out(board):
    async def main() -> tuple[str, int]:
        job = board.start("script", "", _held(asyncio.get_running_loop().create_future()))
        await asyncio.wait_for(board.wait(job, 0.01), timeout=5)
        return job.state, len(job.waiters)

    assert asyncio.run(main()) == (WORKING, 0)


def test_a_wait_on_an_ended_job_or_of_no_time_returns_at_once(board):
    async def main() -> None:
        gate = asyncio.get_running_loop().create_future()
        job = board.start("script", "", _held(gate))
        await asyncio.wait_for(board.wait(job, 0), timeout=0.5)
        gate.set_result(None)
        await _turns()
        await asyncio.wait_for(board.wait(job, 30), timeout=0.5)

    asyncio.run(main())


# ----- the stage watch, get_sim_state's line and the shutdown -----


def test_a_watching_job_holds_its_watch_until_it_ends(clock):
    watched: list[Job] = []

    def watch(job: Job) -> object:
        watched.append(job)
        return object()

    board = JobBoard(watch=watch, clock=clock)

    async def main() -> tuple[object, Job, Job]:
        gate = asyncio.get_running_loop().create_future()
        sweep = board.start("sweep", "", _held(gate), watch_stage=True)
        held = sweep.watch
        gate.set_result(None)
        await _turns()
        script = board.start("script", "", _returning({}))
        await _turns()
        return held, sweep, script

    held, sweep, script = asyncio.run(main())

    assert watched == [sweep]
    assert held is not None
    assert sweep.watch is None
    assert script.watch is None


def test_a_board_with_no_watch_refuses_a_watching_job(board):
    with pytest.raises(ValueError, match="no watch"):
        board.start("sweep", "", _returning({}), watch_stage=True)
    assert board.running() is None


def test_brief_names_the_running_job_and_nothing_after_it(board, clock):
    async def main() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        gate = asyncio.get_running_loop().create_future()
        board.start("script", "", _held(gate))
        clock.now += 252.0
        running = board.brief()
        gate.set_result(None)
        await _turns()
        return running, board.brief()

    assert asyncio.run(main()) == ({"id": "j1", "kind": "script", "state": WORKING, "elapsed": 252.0}, None)


def test_the_shutdown_cancels_the_running_job_tears_it_down_and_refuses_starts(board):
    torn: list[str] = []

    async def main() -> tuple[Job, bool]:
        gate = asyncio.get_running_loop().create_future()
        job = board.start("sweep", "", _held(gate), teardown=lambda: torn.append("stage put back"))
        await _turns()
        board.shut_down()
        task = job.task
        assert task is not None
        await _turns()
        return job, task.cancelled()

    job, cancelled = asyncio.run(main())

    assert torn == ["stage put back"]
    assert cancelled
    assert (job.state, job.message) == (CANCELLED, SHUT_DOWN)
    with pytest.raises(JobError, match="No job starts now: the extension shut down"):
        board.start("script", "", _returning({}))


def test_a_teardown_that_raises_leaves_the_job_cancelled(board):
    def broken() -> None:
        raise RuntimeError("the layer is locked")

    async def main() -> Job:
        job = board.start("sweep", "", _held(asyncio.get_running_loop().create_future()), teardown=broken)
        await _turns()
        with pytest.raises(RuntimeError, match="locked"):
            board.shut_down()
        await _turns()
        return job

    job = asyncio.run(main())
    assert job.state == CANCELLED
    assert board.closed


def test_the_shutdown_with_no_job_refuses_later_starts(board):
    board.shut_down()
    board.shut_down()
    with pytest.raises(JobError, match="shut down"):
        board.start("script", "", _returning({}))
