"""
Debug drawing: /debug/draw.

Draws with isaacsim.util.debug_draw (Isaac Sim 5.x, 6.x), or omni.debugdraw in other Kit apps that ship it, turning
the extension on at the first call. The book in ovmcp/core/debug_draw.py holds what still shows; one update
subscription, on Kit's main thread, lets each drawing go after its duration and draws again what is left.
"""

import time
from typing import Any

import carb
import omni.kit.app
import omni.usd

from ovmcp.core.debug_draw import LINE_WIDTH_PX, RGBA, DebugBook, Segment, argb, duration_seconds, rgba, segments

from ._utils import enable_extension

# The extensions drawn with, in the order they are tried.
BACKENDS = ("isaacsim.util.debug_draw", "omni.debugdraw")


class _IsaacSimDraw:
    """isaacsim.util.debug_draw: a line stays until cleared, and its clear takes every line, ours or not.

    Its interface is acquired at each use, never kept: the extension releases the one it gave when it is turned off,
    and turned on again it gives another.
    """

    name = "isaacsim.util.debug_draw"

    @staticmethod
    def _draw() -> Any:
        from isaacsim.util.debug_draw import _debug_draw

        return _debug_draw.acquire_debug_draw_interface()

    def added(self, _book: DebugBook, lines: list[Segment], colour: RGBA) -> None:
        """A drawing joined the book: draw it now; the lines already drawn stay."""
        n = len(lines)
        self._draw().draw_lines([s for s, _ in lines], [e for _, e in lines], [colour] * n, [LINE_WIDTH_PX] * n)

    def show(self, book: DebugBook) -> None:
        """A drawing went: clear, then draw the book's lines again."""
        draw = self._draw()
        draw.clear_lines()
        starts, ends, colours = book.lines()
        if starts:
            draw.draw_lines(starts, ends, colours, [LINE_WIDTH_PX] * len(starts))

    def frame(self) -> None:
        """Its lines stay by themselves."""

    def forget(self) -> None:
        self._draw().clear_lines()


class _OmniDebugDraw:
    """omni.debugdraw: a line shows for one frame, so the book's lines are drawn on every update, as one draw_lines
    call over a list of points made when the book changes.

    Its interface is the one the extension holds now, read at each use: None while it is off, and another once it is
    turned on again.
    """

    name = "omni.debugdraw"

    def __init__(self) -> None:
        self._points: list[Any] = []

    def added(self, book: DebugBook, _lines: list[Segment], _colour: RGBA) -> None:
        self.show(book)

    def show(self, book: DebugBook) -> None:
        from omni.debugdraw._debugDraw import SimplexPoint

        points = []
        for start, end, colour in zip(*book.lines(), strict=True):
            packed = argb(colour)
            for position in (start, end):
                point = SimplexPoint()
                point.position = carb.Float3(*position)
                point.color = packed
                point.width = LINE_WIDTH_PX
                points.append(point)
        self._points = points

    def frame(self) -> None:
        from omni.debugdraw import get_debug_draw_interface

        draw = get_debug_draw_interface()
        if draw is not None and self._points:
            draw.draw_lines(self._points)

    def forget(self) -> None:
        self._points = []


_MAKERS = {backend.name: backend for backend in (_IsaacSimDraw, _OmniDebugDraw)}


class _Drawings:
    """The bridge's drawings: the book, the backend drawing them, and the update subscription while it is needed."""

    def __init__(self) -> None:
        self.book = DebugBook()
        self.backend: _IsaacSimDraw | _OmniDebugDraw | None = None
        self.sub: Any = None


_drawings = _Drawings()


def _stage_open() -> bool:
    return omni.usd.get_context().get_stage_state() == omni.usd.StageState.OPENED


def _drop_if_off() -> None:
    """Forgets the backend, the book and the subscription while the backend's extension is off, drawing and clearing
    nothing: an extension that is off has no interface to call. The next draw_debug chooses a backend again."""
    backend = _drawings.backend
    if backend is not None and not omni.kit.app.get_app().get_extension_manager().is_extension_enabled(backend.name):
        stop_drawing()


def choose_backend(names: tuple[str, ...] = BACKENDS) -> str:
    """The first of `names` that enable_extension gives, which draws from now on; a RuntimeError naming them all when
    none does. Only a success is kept, so an extension turned on by hand later is found by the next call.

    A change of backend clears what ours drew with the old one, and empties the book. The live suite calls this
    through execute_script to run omni.debugdraw on Isaac Sim, then again to put the default back.
    """
    unknown = [name for name in names if name not in _MAKERS]
    if unknown or not names:
        raise ValueError(f"Not a drawing backend: {', '.join(unknown) or '(none given)'}; the backends are {BACKENDS}")
    _drop_if_off()
    for name in names:
        current = _drawings.backend
        if current is not None and current.name == name:
            return name
        if enable_extension(name):
            backend = _MAKERS[name]()
            if current is not None:
                _forget(current)
            _drawings.backend = backend
            return name
    raise RuntimeError(f"No debug drawing extension in this Kit app: it has none of {', '.join(names)}")


def _forget(backend: _IsaacSimDraw | _OmniDebugDraw) -> None:
    """Clears what ours drew with `backend`, unless the stage is changing (no clear then, as in `_on_update`), and
    empties the book. Nothing drawn by us, nothing cleared: the clear would take other code's lines."""
    if not _drawings.book.idle and _stage_open():
        backend.forget()
    _drawings.book.reset()


async def handle_draw_debug(body: dict) -> dict:
    """Draw debug lines, spheres and points for `duration` seconds."""
    try:
        shape = segments(body.get("type", "line"), body)
        colour = rgba(body.get("color"))
        duration = duration_seconds(body.get("duration", 5.0))
    except ValueError as e:
        return {"status": "error", "error": str(e)}

    context = omni.usd.get_context()
    # isaacsim.util.debug_draw before 3.2.8 (Isaac Sim 5.x, 6.1) could crash when called while a stage closed or
    # reopened.
    if context.get_stage_state() != omni.usd.StageState.OPENED:
        return {"status": "error", "error": "No stage is open to draw on; draw once it has opened"}
    _drop_if_off()
    if _drawings.backend is None:
        try:
            choose_backend()
        except RuntimeError as e:
            return {"status": "error", "error": str(e)}
    backend = _drawings.backend

    _drawings.book.add(shape.segments, colour, context.get_stage_id(), time.monotonic(), duration)
    backend.added(_drawings.book, shape.segments, colour)
    if _drawings.sub is None:
        stream = omni.kit.app.get_app().get_update_event_stream()
        _drawings.sub = stream.create_subscription_to_pop(_on_update, name="ovmcp.bridge debug draw")

    return {"status": "success", "result": {"drawn": shape.drawn, "backend": backend.name, "duration": duration}}


def _on_update(_event: Any) -> None:
    """Each update, on Kit's main thread, while a drawing shows or a clear is owed: drops the drawings whose time is
    up and those of another stage, then clears and draws the rest again once the stage is open; drops itself when
    nothing is left. `duration` is real seconds from the call, whether the simulation plays or not."""
    _drop_if_off()
    backend, book = _drawings.backend, _drawings.book
    if backend is None:
        _drawings.sub = None
        return
    context = omni.usd.get_context()
    stage_open = context.get_stage_state() == omni.usd.StageState.OPENED
    if book.tick(time.monotonic(), context.get_stage_id(), stage_open):
        backend.show(book)
    if stage_open:
        backend.frame()
    if book.idle:
        _drawings.sub = None


def stop_drawing() -> None:
    """Drops the subscription, the book and the backend, and clears nothing. At shutdown the stage and renderer may be
    tearing down, when a clear crashed Kit before isaacsim.util.debug_draw 3.2.8."""
    _drawings.sub = None
    _drawings.book.reset()
    _drawings.backend = None
