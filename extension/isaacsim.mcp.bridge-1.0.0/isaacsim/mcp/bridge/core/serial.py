"""One request at a time on the viewport.

Handlers share Kit's event loop and interleave at every await, so without this one request would see another's
hidden prims or moved camera. No Kit imports.
"""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import Any


class LazyLock:
    """An asyncio.Lock made on first use inside the running loop, not at import, and made again if the loop changes."""

    def __init__(self):
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock, self._loop = asyncio.Lock(), loop
        return self._lock


def serial(lock: LazyLock) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Run the decorated coroutine function holding `lock`, so no two of them overlap.

    The lock is not re-entrant: a decorated function must never await another one, or it waits on itself.
    """

    def wrap(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def run(*args: Any, **kwargs: Any) -> Any:
            async with lock.get():
                return await fn(*args, **kwargs)

        return run

    return wrap
