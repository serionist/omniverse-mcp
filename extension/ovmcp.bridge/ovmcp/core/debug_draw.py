"""draw_debug without Kit: each shape as line segments, its colour, and the book of the drawings still due to show.

The handler (`ovmcp/bridge/handlers/debug_draw.py`) draws what the book holds. isaacsim.util.debug_draw keeps a line
until it is cleared, and its clear takes every line, so when one drawing goes the bridge clears and draws the rest
again; omni.debugdraw forgets a line after one frame, so the book's lines are drawn on every update.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, cast

Vec3 = tuple[float, float, float]
Segment = tuple[Vec3, Vec3]
RGBA = tuple[float, float, float, float]

LINE_WIDTH_PX = 2.0  # the width every line is drawn with
RED: RGBA = (1.0, 0.0, 0.0, 1.0)
SHAPES = ("line", "lines", "sphere", "points", "point")  # "point", one cross, stays for direct callers


@dataclass(frozen=True)
class Shape:
    segments: list[Segment]
    drawn: list[dict[str, Any]]  # what the answer reports: one entry per element, as before


def segments(shape: str, body: Mapping[str, object]) -> Shape:
    """`shape` from the request `body` as line segments: a `line` one, `lines` one per pair of neighbours in
    `points`, a `sphere` three crossing lines, each of `points` a cross of half-length `size`, a `point` one cross.

    A ValueError says what is missing or wrong: a part the shape needs, a vector that isn't three finite numbers, a
    radius or size that isn't a finite number, an unknown shape.
    """
    if shape == "line":
        start, end = body.get("start"), body.get("end")
        if not start or not end:
            raise ValueError("start and end required for line")
        a, b = _vector(start, "start"), _vector(end, "end")
        return Shape([(a, b)], [{"type": "line", "start": list(a), "end": list(b)}])
    if shape == "lines":
        points = _vectors(body.get("points"), "points")
        if len(points) < 2:
            raise ValueError("At least 2 points needed for lines")
        return Shape(list(pairwise(points)), [{"type": "lines", "segments": len(points) - 1}])
    if shape == "sphere":
        center = body.get("center")
        if not center:
            raise ValueError("center required for sphere")
        c = _vector(center, "center")
        radius = _number(body.get("radius", 0.1), "radius")
        return Shape(_cross(c, radius), [{"type": "sphere", "center": list(c), "radius": radius}])
    if shape == "points":
        points = _vectors(body.get("points"), "points")
        if not points:
            raise ValueError("points list required for points")
        size = _number(body.get("size", 0.05), "size")
        return Shape(
            [segment for p in points for segment in _cross(p, size)],
            [{"type": "point", "position": list(p)} for p in points],
        )
    if shape == "point":
        position = body.get("position")
        if not position:
            raise ValueError("position required for point")
        p = _vector(position, "position")
        return Shape(_cross(p, _number(body.get("size", 0.05), "size")), [{"type": "point", "position": list(p)}])
    raise ValueError(f"Unknown shape {shape!r}: one of line, lines, sphere or points")


def rgba(color: object) -> RGBA:
    """`color`, [r, g, b] in 0-1, as the RGBA isaacsim.util.debug_draw takes: each channel clamped to 0-1, alpha 1,
    red when it is None. Values past the third are ignored, as before."""
    if color is None:
        return RED
    channels = cast("Sequence[object]", color) if isinstance(color, (list, tuple)) else ()
    if len(channels) < 3 or not all(_is_number(v) for v in channels[:3]):
        raise ValueError(f"color must be [r, g, b], three numbers in 0-1 (got {color!r})")
    r, g, b = (_clamp(cast("float", v)) for v in channels[:3])
    return (r, g, b, 1.0)


def argb(color: RGBA) -> int:
    """An RGBA colour packed as omni.debugdraw takes it, 0xAARRGGBB, each channel clamped first: unclamped, a channel
    above 1 spilt into the one above it."""
    r, g, b, a = (round(_clamp(c) * 255) for c in color)
    return (a << 24) | (r << 16) | (g << 8) | b


def duration_seconds(value: object) -> float:
    """How long a drawing shows, in seconds: a finite number above 0."""
    if not _is_number(value) or cast("float", value) <= 0:
        raise ValueError(f"duration must be a number of seconds above 0 (got {value!r})")
    return float(cast("float", value))


@dataclass(frozen=True)
class _Drawing:
    segments: list[Segment]
    colour: RGBA
    stage: int
    expires: float


class DebugBook:
    """The drawings still due to show, each with the id of the stage it was drawn on and the moment it expires, and
    whether a clear is owed: what is on screen must be cleared and the rest drawn again, since a drawing went.

    A clear is paid only on an update with the stage open: isaacsim.util.debug_draw before 3.2.8 crashed Kit when
    cleared while the stage and renderer tear down.
    """

    def __init__(self) -> None:
        self._drawings: list[_Drawing] = []
        self.clear_owed = False

    def add(self, lines: Sequence[Segment], colour: RGBA, stage: int, now: float, duration: float) -> None:
        self._drawings.append(_Drawing(list(lines), colour, stage, now + duration))

    def expire(self, now: float) -> bool:
        """Drops the drawings whose time is up at `now`; true when one went."""
        return self._keep(lambda d: d.expires > now)

    def keep_stage(self, stage: int) -> bool:
        """Drops the drawings made on a stage other than `stage`, the one open now; true when one went. A new stage
        must not get the old one's lines back when the rest are drawn again."""
        return self._keep(lambda d: d.stage == stage)

    def tick(self, now: float, stage: int, stage_open: bool) -> bool:
        """One update: drops what expired or belongs to another stage, which owes a clear. True when the clear is due
        now, the stage being open: the caller clears and draws `lines()` again."""
        went = self.keep_stage(stage)
        went = self.expire(now) or went
        self.clear_owed = self.clear_owed or went
        if self.clear_owed and stage_open:
            self.clear_owed = False
            return True
        return False

    def lines(self) -> tuple[list[Vec3], list[Vec3], list[RGBA]]:
        """The starts, ends and colours of every segment still due, as isaacsim.util.debug_draw's draw_lines takes
        them."""
        starts: list[Vec3] = []
        ends: list[Vec3] = []
        colours: list[RGBA] = []
        for drawing in self._drawings:
            for start, end in drawing.segments:
                starts.append(start)
                ends.append(end)
                colours.append(drawing.colour)
        return starts, ends, colours

    @property
    def empty(self) -> bool:
        return not self._drawings

    @property
    def idle(self) -> bool:
        """Nothing to show and no clear owed: the update subscription can go."""
        return self.empty and not self.clear_owed

    def reset(self) -> None:
        """Forgets every drawing and any clear owed, drawing nothing: a change of backend, or the extension stopping."""
        self._drawings.clear()
        self.clear_owed = False

    def _keep(self, keep: Callable[[_Drawing], bool]) -> bool:
        before = len(self._drawings)
        self._drawings = [d for d in self._drawings if keep(d)]
        return len(self._drawings) < before


def _cross(centre: Vec3, half: float) -> list[Segment]:
    """Three lines through `centre`, one along each axis, reaching `half` either side."""
    crossing: list[Segment] = []
    for axis in range(3):
        start, end = list(centre), list(centre)
        start[axis] -= half
        end[axis] += half
        crossing.append(((start[0], start[1], start[2]), (end[0], end[1], end[2])))
    return crossing


def _vector(value: object, name: str) -> Vec3:
    items = cast("Sequence[object]", value) if isinstance(value, (list, tuple)) else ()
    if len(items) != 3 or not all(_is_number(v) for v in items):
        raise ValueError(f"{name} must be [x, y, z], three finite numbers (got {value!r})")
    x, y, z = (float(cast("float", v)) for v in items)
    return (x, y, z)


def _vectors(value: object, name: str) -> list[Vec3]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list of [x, y, z] (got {value!r})")
    return [_vector(v, f"{name}[{i}]") for i, v in enumerate(cast("Sequence[object]", value))]


def _number(value: object, name: str) -> float:
    if not _is_number(value):
        raise ValueError(f"{name} must be a finite number (got {value!r})")
    return float(cast("float", value))


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
