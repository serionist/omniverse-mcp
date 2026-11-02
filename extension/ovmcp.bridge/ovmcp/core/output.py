"""Where a script's print goes (#158): one router over sys.stdout and sys.stderr, which writes to the sink of the task
printing, an /execute call's or a job's, and everything else to the stream beneath, Kit's console as before.

Before, /execute swapped sys.stdout for its call's buffer while the call ran, so whatever printed meanwhile, another
handler or a job, landed in that call's answer. A context variable keeps each sink to its own task and the tasks it
starts; a thread, or a task with no sink, prints to the stream beneath. Kit-free.
"""

import io
import sys
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Protocol, TextIO, TypeVar, cast

STDOUT = "stdout"
STDERR = "stderr"


class Sink(Protocol):
    """What a task's printed text goes to; once closed, its task and those it started print to the stream beneath."""

    closed: bool

    def write(self, stream: str, text: str) -> None: ...


S = TypeVar("S", bound=Sink)

_sink: ContextVar[Sink | None] = ContextVar("ovmcp_output_sink", default=None)


class Printed:
    """One /execute call's stdout and stderr, whole, as its answer gives them."""

    def __init__(self) -> None:
        self.closed = False
        self._text = {STDOUT: io.StringIO(), STDERR: io.StringIO()}

    def write(self, stream: str, text: str) -> None:
        self._text[stream].write(text)

    def text(self, stream: str) -> str:
        return self._text[stream].getvalue()


class Router:
    """Stands for sys.stdout or sys.stderr: what is written goes to the writing task's sink, or to the stream beneath.

    Every other attribute (encoding, isatty, fileno) is the stream's, as Kit's own StreamInterceptor passes them to the
    console stream beneath it. Once turned off, at the extension's shutdown, everything goes to the stream.
    """

    def __init__(self, stream: str, beneath: TextIO) -> None:
        self.stream = stream
        self.beneath = beneath
        self.on = True

    def write(self, text: str) -> int:
        sink = _sink.get()
        if not self.on or sink is None or sink.closed:
            return self.beneath.write(text)
        sink.write(self.stream, text)
        return len(text)

    def writelines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        self.beneath.flush()

    def __getattr__(self, name: str) -> Any:
        if name == "beneath":  # not set yet, as while copy or pickle makes one: no endless lookup
            raise AttributeError(name)
        return getattr(self.beneath, name)


# The routers this module put over the streams, which uninstall turns off.
_installed: list[Router] = []


def install() -> None:
    """Puts a router over sys.stdout and over sys.stderr, unless one of this module's is there already."""
    if not isinstance(sys.stdout, Router):
        router = Router(STDOUT, sys.stdout)
        _installed.append(router)
        sys.stdout = cast("TextIO", router)
    if not isinstance(sys.stderr, Router):
        router = Router(STDERR, sys.stderr)
        _installed.append(router)
        sys.stderr = cast("TextIO", router)


def uninstall() -> None:
    """At the extension's shutdown: every router this module installed passes everything to its stream from now on,
    and one still over sys.stdout or sys.stderr gives the stream its place back. Kit's own restore at exit replaces
    only its interceptor, so a router left on top would outlive the interceptor it writes to; and the next start
    installs a router of its own rather than one over this (round 1, P1)."""
    for router in _installed:
        router.on = False
    while any(router is sys.stdout for router in _installed):
        sys.stdout = cast("Router", sys.stdout).beneath
    while any(router is sys.stderr for router in _installed):
        sys.stderr = cast("Router", sys.stderr).beneath
    _installed.clear()


@contextmanager
def collect(sink: S) -> Generator[S]:
    """While the block runs, what this task prints, and the tasks and callbacks it starts meanwhile, goes to `sink`.
    The sink is closed when the block ends, so a task it left running prints to the stream beneath, as it did before
    #158, not into a sink nobody reads."""
    install()
    token = _sink.set(sink)
    try:
        yield sink
    finally:
        sink.closed = True
        _sink.reset(token)
