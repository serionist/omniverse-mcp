"""open_scene: a USD file opened as the stage, the checks before it, and the answer after (#79).

Kit closes the open stage before it reads the file, so a file that fails to open leaves no stage at all (#79's E7).
Everything that can refuse runs first, while the open stage is still there. Kit-free, as capture.py is: the handler
passes Kit in as a StageKit, so the tests run the sequence with plain asyncio, and describe() reads a real stage, so
usd-core tests it.

The limits are read when a call runs, never bound as defaults, so a test can shorten one.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from pxr import Sdf, Usd, UsdGeom

from .usd import format_of
from .usd_files import LIBRARY_PREFIX, is_url, usd_file_url

T = TypeVar("T")

STAT_SECONDS = 20.0  # the asset library's root and the stat of the file, together
OPEN_SECONDS = 80.0  # Kit's open, which goes on in Kit when the wait runs out
# The server's client gives up after 120 s: 20 s are left for the updates, the prim count and the reply, and a unit
# test holds the sum under the client's timeout.

OPENED, OPENING, CLOSING, CLOSED = "OPENED", "OPENING", "CLOSING", "CLOSED"
FOUND = "OK"
UNSUPPORTED = "ERROR_NOT_SUPPORTED"
NOT_FOUND = "ERROR_NOT_FOUND"
UNSAVED = "an unsaved stage"


class StageKit(Protocol):
    """What open_scene asks of Kit; the bridge's handler answers it with Kit's own calls."""

    def state(self) -> str:
        """The stage's state: OPENED, OPENING, CLOSING or CLOSED."""
        ...

    def stage(self) -> Usd.Stage | None: ...

    def is_file(self, path: str) -> bool: ...

    def whole(self, path: str) -> str: ...

    async def assets_root(self) -> str | None:
        """Isaac Sim's asset library root; None in a Kit app without it. RuntimeError when it can't be found."""
        ...

    async def stat(self, url: str) -> str:
        """omni.client's answer about url, by name: OK, ERROR_NOT_FOUND, ..."""
        ...

    def stop_timeline(self) -> bool:
        """Stops the simulation; whether it was playing or paused."""
        ...

    async def next_update(self) -> None: ...

    def start_open(self, url: str) -> Awaitable[tuple[bool, str]]:
        """Starts Kit's open of url before it returns; what is returned gives Kit's (result, error)."""
        ...

    def writable(self) -> bool: ...

    def recording_note(self) -> str | None: ...


class RefusedError(Exception):
    """open_scene's error, with the stage as it was."""


async def _within(awaitable: Awaitable[T], seconds: float, late: str) -> T:
    try:
        return await asyncio.wait_for(awaitable, max(seconds, 0.0))
    except TimeoutError:  # asyncio's, since 3.11
        raise RefusedError(late) from None


def name_of(stage: Usd.Stage | None) -> str | None:
    """The stage as an answer names it: its root layer's identifier, or an unsaved stage; None for no stage."""
    if stage is None:
        return None
    identifier = stage.GetRootLayer().identifier
    return UNSAVED if Sdf.Layer.IsAnonymousLayerIdentifier(identifier) else identifier


def readable(path: str) -> bool:
    """Whether the file at path starts as its type says: a Git LFS pointer under a .usd name doesn't."""
    file_format = format_of(path)
    # No format: IsSupportedFile let it by for one a plugin reads, which Kit reads and reports itself.
    return file_format is None or bool(file_format.CanRead(path))


def describe(stage: Usd.Stage) -> dict[str, Any]:
    """The stage as the answer gives it, read as /sim/state reads it, with what the file leaves to USD's fallbacks."""
    default = stage.GetDefaultPrim()
    return {
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "up_axis_authored": stage.HasAuthoredMetadata("upAxis"),
        "meters_per_unit": float(UsdGeom.GetStageMetersPerUnit(stage)),
        "meters_per_unit_authored": stage.HasAuthoredMetadata("metersPerUnit"),
        "default_prim": str(default.GetPath()) if default.IsValid() else None,
        "prim_count": sum(1 for _ in stage.Traverse()),
        # A .usdz can't be saved back, though Kit calls its stage writable (#79's E8).
        "package": bool(stage.GetRootLayer().GetFileFormat().IsPackage()),
    }


def _busy(url: str) -> str:
    return f"Kit is opening or closing a stage now, so {url} wasn't opened: call again once that has finished"


def _not_reached(url: str, result: str) -> str:
    if result == NOT_FOUND:
        return f"No file at {url}: nothing was opened, and the open stage stays"
    return f"Kit can't reach {url} ({result}): nothing was opened, and the open stage stays"


def _failed(url: str, error: str, state: str, replaced: str | None, now: str | None) -> str:
    """Why the open failed, and what is open now: the state says, not the failure (#79's E7, E14)."""
    said = f"Kit could not open {url}" + (f": {error}" if error else "")
    if state in (OPENING, CLOSING):
        return f"{said}. Another open is under way, so this file wasn't opened: call again once it has finished"
    if state == OPENED and now is not None:
        return f"{said}. The stage open now is {now}"
    what_now = "open_scene another file, or new_scene"
    if replaced is not None:
        return f"{said}. Kit closed {replaced} before the file failed to load, so no stage is open: {what_now}"
    return f"{said}. No stage is open: {what_now}"


async def _library_root(path: str, kit: StageKit, seconds: float) -> str | None:
    late = f"Isaac Sim's asset library didn't answer in {seconds:g} s, so {path} wasn't opened"
    try:
        return await _within(kit.assets_root(), seconds, late)
    except RuntimeError as e:
        raise RefusedError(f"Isaac Sim's asset library can't be found, so {path} wasn't opened: {e}") from None


async def open_stage(file_path: object, kit: StageKit, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Opens file_path as the stage, or refuses with the open stage kept; the handler's answer either way."""
    try:
        return await _open(file_path, kit, clock)
    except RefusedError as e:
        return {"status": "error", "error": str(e)}


async def _open(file_path: object, kit: StageKit, clock: Callable[[], float]) -> dict[str, Any]:
    if not isinstance(file_path, str) or not file_path.strip():
        raise RefusedError(
            "No file_path: give a USD file on the Kit app's machine, a URL, or a path in Isaac Sim's asset library "
            f"({LIBRARY_PREFIX}...)"
        )
    path = file_path
    stat_seconds = STAT_SECONDS
    started = clock()

    local = not is_url(path) and kit.is_file(path)
    root = None
    if not is_url(path) and not local and path.startswith(LIBRARY_PREFIX):
        root = await _library_root(path, kit, stat_seconds)
        if root is None:
            raise RefusedError(f"This Kit app has no Isaac Sim asset library to find {path} in")
    url = usd_file_url(path, lambda: root, kit.is_file, kit.whole)
    if url is None:
        raise RefusedError(
            f"No USD file at {kit.whole(path)} on the Kit app's machine. A relative path is read from the folder Kit "
            f"was started in; a URL (omniverse://, https://, file:///) opens as given, and a path in Isaac Sim's "
            f"asset library starts {LIBRARY_PREFIX}"
        )
    if not Usd.Stage.IsSupportedFile(url):
        raise RefusedError(
            f"USD can't open {url} as a stage: give a .usd, .usda, .usdc or .usdz file, or a type a plugin of this "
            "Kit app reads"
        )
    if kit.state() in (OPENING, CLOSING):
        raise RefusedError(_busy(url))

    left = stat_seconds - (clock() - started)
    result = await _within(kit.stat(url), left, f"Kit got no answer about {url} in {stat_seconds:g} s")
    # Isaac Sim takes ERROR_NOT_SUPPORTED as found for its own library (accept_unsupported), and so does this.
    under_root = root is not None and url.startswith(root.rstrip("/") + "/")
    if result != FOUND and not (result == UNSUPPORTED and under_root):
        raise RefusedError(_not_reached(url, result))
    if local and not readable(url):
        raise RefusedError(
            f"{url} holds nothing USD reads as its type: a Git LFS pointer, say, or another kind of file under a USD "
            "name"
        )

    replaced = name_of(kit.stage()) if kit.state() == OPENED else None
    stopped = kit.stop_timeline()
    # Kit's File > Open stops the timeline and lets updates pass before it opens.
    await kit.next_update()
    # Another open may have started during the stat or the update. From this check to the start nothing awaits, so
    # none can start in between (#79's E14).
    if kit.state() in (OPENING, CLOSING):
        raise RefusedError(_busy(url))
    opening = kit.start_open(url)

    open_seconds = OPEN_SECONDS
    try:
        ok, error = await asyncio.wait_for(opening, open_seconds)
    except TimeoutError:
        # Kit's open can't be cancelled; its late answer finds the wait gone.
        return {
            "status": "error",
            "error": f"Kit hasn't finished opening {url} in {open_seconds:g} s and goes on in the background: until "
            "it has, no stage is open and tools that read the stage fail; get_sim_state answers once it has opened",
        }
    state = kit.state()
    if not ok or state != OPENED:
        return {"status": "error", "error": _failed(url, error, state, replaced, name_of(kit.stage()))}

    # As new_scene waits: the recording's and the drawings' update handlers see the new stage before the answer.
    await kit.next_update()
    await kit.next_update()
    stage = kit.stage()
    if stage is None:
        return {"status": "error", "error": f"Kit opened {url}, but no stage is open now: another call closed it"}
    return {
        "status": "success",
        "result": {
            "file_path": url,
            "replaced": replaced,
            **describe(stage),
            "writable": kit.writable(),
            "stopped": stopped,
            "recording_note": kit.recording_note(),
        },
    }
