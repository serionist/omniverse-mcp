"""ovmcp.core.output, Kit-free (#158): one router over sys.stdout and sys.stderr sends what a task prints to that task's
sink, and the rest to the stream beneath as before; it passes the stream's other attributes through, as Kit's own
StreamInterceptor does, and comes off at shutdown (round 1, P1)."""

import asyncio
import copy
import io
import sys
import threading
from collections.abc import Callable, Iterator

import pytest

from ovmcp.core import output

from .conftest import reset_output


class Stream(io.StringIO):
    """A console stream as Kit's interceptor stands for one: text, and attributes of its own."""

    kit_name = "omni.kit.app:script_stdout"

    def __init__(self) -> None:
        super().__init__()
        self.flushes = 0

    def isatty(self) -> bool:
        return True

    def flush(self) -> None:
        self.flushes += 1


@pytest.fixture
def streams(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], tuple[Stream, Stream]]]:
    """Puts streams of the test's own as sys.stdout and sys.stderr, when the test calls it: pytest sets its own at the
    start of a test's call, over any a fixture set up."""

    def put() -> tuple[Stream, Stream]:
        out, err = Stream(), Stream()
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        return out, err

    yield put
    reset_output()


def test_two_tasks_print_into_their_own_sinks(streams):
    out, err = streams()

    async def call(name: str) -> output.Printed:
        with output.collect(output.Printed()) as printed:
            for i in range(3):
                print(f"{name}{i}")
                print(f"{name} err", file=sys.stderr)
                await asyncio.sleep(0)
        return printed

    async def both() -> list[output.Printed]:
        return list(await asyncio.gather(call("a"), call("b")))

    a, b = asyncio.run(both())

    assert a.text(output.STDOUT) == "a0\na1\na2\n"
    assert b.text(output.STDOUT) == "b0\nb1\nb2\n"
    assert b.text(output.STDERR) == "b err\n" * 3
    assert out.getvalue() == err.getvalue() == ""


def test_a_task_without_a_sink_prints_to_the_stream_beneath(streams):
    out, _ = streams()

    async def _bystander() -> None:
        # Its own task, made before the sink: what a handler printing during a script's call prints.
        print("from Kit's own work")

    async def run() -> None:
        bystander = asyncio.ensure_future(_bystander())
        with output.collect(output.Printed()) as printed:
            await bystander
        assert printed.text(output.STDOUT) == ""

    asyncio.run(run())
    assert out.getvalue() == "from Kit's own work\n"


def test_a_thread_prints_to_the_stream_beneath(streams):
    out, _ = streams()

    async def main() -> output.Printed:
        with output.collect(output.Printed()) as printed:
            worker = threading.Thread(target=print, args=("from a worker",))
            worker.start()
            worker.join()
        return printed

    assert asyncio.run(main()).text(output.STDOUT) == ""
    assert out.getvalue() == "from a worker\n"


def test_a_task_left_behind_prints_to_the_stream_once_its_call_ends(streams):
    out, _ = streams()

    left: list[asyncio.Future[None]] = []

    async def later() -> None:
        print("early")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        print("late")

    async def main() -> output.Printed:
        with output.collect(output.Printed()) as printed:
            left.append(asyncio.ensure_future(later()))
            await asyncio.sleep(0)
        await left[0]
        return printed

    printed = asyncio.run(main())

    assert printed.closed
    assert printed.text(output.STDOUT) == "early\n"
    assert out.getvalue() == "late\n"


def test_writelines_is_routed_and_flush_reaches_the_stream(streams):
    out, _ = streams()

    async def main() -> output.Printed:
        with output.collect(output.Printed()) as printed:
            sys.stdout.writelines(["one\n", "two\n"])
            sys.stdout.flush()
        return printed

    assert asyncio.run(main()).text(output.STDOUT) == "one\ntwo\n"
    assert out.flushes == 1


def test_every_other_attribute_is_the_stream_s(streams):
    out, _ = streams()

    output.install()

    assert sys.stdout is not out
    assert sys.stdout.isatty() is True
    assert getattr(sys.stdout, "kit_name", None) == "omni.kit.app:script_stdout"


def test_install_puts_one_router_over_each_stream(streams):
    out, err = streams()

    output.install()
    output.install()

    assert isinstance(sys.stdout, output.Router)
    assert sys.stdout.beneath is out
    assert isinstance(sys.stderr, output.Router)
    assert sys.stderr.beneath is err


def test_uninstall_puts_the_streams_back(streams):
    out, err = streams()

    output.install()
    output.uninstall()

    assert (sys.stdout, sys.stderr) == (out, err)
    # The next start, a fresh import of the module as Kit makes it, installs a router of its own over Kit's stream,
    # never over the last.
    output._state.closed = False
    output.install()
    assert isinstance(sys.stdout, output.Router)
    assert sys.stdout.beneath is out


def test_a_router_under_another_stream_passes_everything_on_after_uninstall(streams):
    out, _ = streams()

    output.install()
    router = sys.stdout
    above = io.StringIO()
    sys.stdout = above

    output.uninstall()

    assert sys.stdout is above
    printed = output.Printed()

    async def main() -> None:
        with output.collect(printed):
            router.write("through")

    asyncio.run(main())
    assert printed.text(output.STDOUT) == ""
    assert out.getvalue() == "through"


def test_a_router_copies_without_an_endless_lookup(streams):
    out, _ = streams()
    output.install()

    copied = copy.copy(sys.stdout)

    assert isinstance(copied, output.Router)
    assert copied.beneath is out


def test_a_block_puts_back_the_router_its_code_replaced(streams):
    out, err = streams()

    async def main() -> None:
        with output.collect(output.Printed()):
            sys.stdout = io.StringIO()
            sys.stderr = sys.__stderr__

    asyncio.run(main())

    assert isinstance(sys.stdout, output.Router)
    assert sys.stdout.beneath is out
    assert isinstance(sys.stderr, output.Router)
    assert sys.stderr.beneath is err


def test_after_uninstall_a_call_still_in_flight_installs_nothing(streams):
    # A request in flight at the shutdown resumes after it: a router put back over Kit's stream would outlive it.
    out, _ = streams()
    output.install()
    output.uninstall()

    async def main() -> output.Printed:
        with output.collect(output.Printed()) as printed:
            print("after the shutdown")
        return printed

    printed = asyncio.run(main())

    assert sys.stdout is out
    assert printed.text(output.STDOUT) == ""
    assert out.getvalue() == "after the shutdown\n"


def test_a_block_after_uninstall_puts_nothing_back(streams):
    out, _ = streams()

    async def main() -> None:
        with output.collect(output.Printed()):
            output.uninstall()
            sys.stdout = io.StringIO()

    asyncio.run(main())

    assert not isinstance(sys.stdout, output.Router)
    assert sys.stdout is not out


def test_a_task_with_a_sink_is_no_terminal(streams):
    # A library that finds a terminal writes colour codes, which would land in an answer.
    streams()

    async def main() -> bool:
        with output.collect(output.Printed()):
            return sys.stdout.isatty()

    assert asyncio.run(main()) is False
    assert sys.stdout.isatty() is True
