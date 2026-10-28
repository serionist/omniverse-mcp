"""Viewport handlers run one at a time on the event loop: core/serial.py, with plain asyncio."""

import asyncio

from ovmcp.core.serial import LazyLock, serial


def _run(coro):
    return asyncio.run(coro)


def test_two_serial_coroutines_never_overlap_but_others_still_run():
    lock = LazyLock()
    events = []

    @serial(lock)
    async def viewport_work(name):
        events.append(f"{name} start")
        for _ in range(3):
            await asyncio.sleep(0)
        events.append(f"{name} end")

    async def other_request():
        await asyncio.sleep(0)
        events.append("other")

    async def main():
        await asyncio.gather(viewport_work("a"), viewport_work("b"), other_request())

    _run(main())
    assert events.index("a end") < events.index("b start")
    assert events.index("other") < events.index("a end")


def test_a_second_caller_waits_for_the_first():
    lock = LazyLock()
    release = None

    @serial(lock)
    async def hold():
        await release.wait()
        return "first"

    @serial(lock)
    async def second():
        return "second"

    async def main():
        nonlocal release
        release = asyncio.Event()
        first = asyncio.ensure_future(hold())
        await asyncio.sleep(0)
        waiting = asyncio.ensure_future(second())
        await asyncio.sleep(0.01)
        assert not waiting.done()
        release.set()
        return await first, await waiting

    assert _run(main()) == ("first", "second")


def test_the_lock_is_made_again_for_a_new_loop():
    lock = LazyLock()

    @serial(lock)
    async def work():
        return asyncio.get_running_loop()

    first_loop = _run(work())
    second_loop = _run(work())
    assert first_loop is not second_loop


def test_the_decorated_function_keeps_its_name():
    @serial(LazyLock())
    async def handle_capture(_body):
        return {}

    assert handle_capture.__name__ == "handle_capture"
