"""/scene/open: open_scene's calls into Kit, handed to its Kit-free core (ovmcp.core.stage_open), which checks the
file, opens it and answers (#79).

Its own module, importing only what it calls, so tests/test_scene_open_handler.py fakes little of Kit.
"""

import asyncio
import os
from typing import Any

import omni.kit.app
import omni.timeline
import omni.usd

from ovmcp.core import stage_open

from .recording import recording_note

_STATES = (stage_open.OPENED, stage_open.OPENING, stage_open.CLOSING, stage_open.CLOSED)


def _name(value: Any) -> str:
    """A Kit enum's member by its name: omni.client's Result.OK is OK."""
    return str(value).rsplit(".", 1)[-1]


class _Kit:
    """open_scene's StageKit, through Kit's own calls."""

    def __init__(self) -> None:
        self._context = omni.usd.get_context()

    def state(self) -> str:
        now = self._context.get_stage_state()
        for name in _STATES:
            if now == getattr(omni.usd.StageState, name):
                return name
        return _name(now)

    def stage(self) -> Any:
        return self._context.get_stage()

    # As create_robot reads a file: a relative path against the folder Kit was started in (#79's E1).
    is_file = staticmethod(os.path.isfile)
    whole = staticmethod(os.path.abspath)

    async def assets_root(self) -> str | None:
        try:
            from isaacsim.storage.native import get_assets_root_path_async
        except ImportError:
            return None  # a Kit app without Isaac Sim's asset library
        # Not get_assets_root_path: it waits on the main thread, up to 10 s a server, with Kit's loop stopped.
        return await get_assets_root_path_async()

    async def stat(self, url: str) -> str:
        import omni.client

        result, _entry = await omni.client.stat_async(url)
        return _name(result)

    def stop_timeline(self) -> bool:
        timeline = omni.timeline.get_timeline_interface()
        running = not timeline.is_stopped()
        timeline.stop()
        return running

    async def next_update(self) -> None:
        await omni.kit.app.get_app().next_update_async()

    def start_open(self, url: str) -> "asyncio.Future[tuple[bool, str]]":
        future: asyncio.Future[tuple[bool, str]] = asyncio.get_running_loop().create_future()

        def done(ok: bool, error: str) -> None:
            # Once only, as omni.usd's own open_stage_async guards it: a wait that ran out has given the future up.
            if not future.done():
                future.set_result((bool(ok), str(error or "")))

        # Called, not awaited: Kit's open starts in the same step as the core's last look at the state. omni.usd's own
        # open_stage_async, the call Isaac Sim 5.1 makes, is this same call underneath.
        if not self._context.open_stage_with_callback(url, done) and not future.done():
            # Kit called back "UsdContext busy" for a second open (#79's E14), but when was not measured.
            done(False, "Kit didn't start the open")
        return future

    def writable(self) -> bool:
        return bool(self._context.is_writable())

    def recording_note(self) -> str | None:
        return recording_note()


async def handle_open_scene(body: dict) -> dict:
    return await stage_open.open_stage(body.get("file_path"), _Kit())
