"""A capture sweep's shots, their poses and lenses, the selections written before each, the timeline's state, and the
manifest Kit writes beside the pictures (#157). Needs pxr, not Kit: the tests run it on usd-core.

A sweep captures a list of shots as one job (handlers/sweep.py): each shot is a pose, a lens, the variant selections it
shows and a timeline time. Every shot is read and checked before anything changes, so a misspelled field at shot 300
is refused at the start, not minutes in. A shot shows only what it names: a set it doesn't name shows what it showed
before the sweep, never the last shot's choice, and a shot without a lens gets the default lens, never the last
shot's, so a picture never depends on its place in the list.
"""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from pxr import Gf, Sdf, Usd

from . import variants
from .usd import floats, prim_spec, select

# The most shots one sweep takes: the case's check is about 400, and a list of 2,000 is about a megabyte of JSON.
MAX_SHOTS = 2000
# A line of progress and a rewrite of the manifest every this many shots, so a read carries a few lines, not hundreds,
# and a Kit that hangs mid-sweep (#162) still leaves an index of the files taken.
PROGRESS_EVERY = 25

# Kit's own camera's lens, in millimetres (omni.kit.widget.viewport's typed default for a new camera), its vertical
# aperture fitted to the image, for a shot that names no lens.
FOCAL_LENGTH = 18.147562
HORIZONTAL_APERTURE = 20.955
# How far an aperture's ratio may be off the image's before a shot is refused: the case's 20.955 x 11.787 mm at
# 1280 x 720 is 0.002% off.
APERTURE_FIT = 0.01
# Isaac Sim's camera default in metres (apps/isaacsim.exp.base.kit, typedDefaults.camera.clippingRange), where USD's
# own, 1 to 1e6 units, cuts the floor in front of a camera 0.65 m above it on a metres stage.
CLIPPING_METRES = (0.01, 1e7)

# The sweep's own camera, in the session layer, as Kit keeps its own cameras there.
CAMERA_PATH = "/OmniverseKit_Sweep"
MANIFEST = "manifest.json"
FORMAT = "omniverse-mcp-sweep-1"

# A shot's wait for the stage to finish loading what its switch brought in, and the most a shot holds the viewport lock,
# so a capture queued behind it keeps most of its 80 s (core/capture.py's CALL_SECONDS).
LOADING_SECONDS = 20.0
SHOT_SECONDS = 30.0

# A shot's fields as a list gives them; a manifest's entries hold these too, and those after them, which a manifest
# read back as shots passes over.
_FIELDS = frozenset(
    {
        "name",
        "position",
        "yaw",
        "pitch",
        "target",
        "camera_path",
        "focal_length",
        "horizontal_aperture",
        "vertical_aperture",
        "clipping_range",
        "selections",
        "time",
    }
)
_MANIFEST_FIELDS = frozenset(
    {"index", "file", "frame", "timeline_time", "is_black", "error", "loading", "loading_seconds"}
)
_LENS_FIELDS = ("focal_length", "horizontal_aperture", "vertical_aperture")
# Kept to a few, so a list with a fault in every shot doesn't answer 2,000 lines.
_SHOWN_FAULTS = 10
_LONGEST_NAME = 100
# A folder's name: one plain name, so it can't climb out of the sweeps folder or name a drive.
_FOLDER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ -]*")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SEPARATORS = "/\\"


@dataclass(frozen=True)
class Lens:
    """A pinhole camera's focal length and apertures, in millimetres, as USD's Camera holds them."""

    focal_length: float
    horizontal_aperture: float
    vertical_aperture: float


def default_lens(width: int, height: int) -> Lens:
    """The lens of a shot that names none: Kit's own camera's, its vertical aperture fitted to the image."""
    return fit_lens(width, height)


def fit_lens(
    width: int,
    height: int,
    focal_length: float | None = None,
    horizontal: float | None = None,
    vertical: float | None = None,
) -> Lens:
    """The lens a shot's intrinsics give at width x height: an aperture left out is fitted to the image's shape, the
    horizontal one from Kit's default when both are. ValueError, naming the aperture that fits, when the two given
    don't fit the image within APERTURE_FIT: RTX would stretch or crop the picture."""
    aspect = width / height
    if horizontal is None:
        horizontal = vertical * aspect if vertical is not None else HORIZONTAL_APERTURE
    if vertical is None:
        vertical = horizontal / aspect
    if abs(horizontal / vertical / aspect - 1) > APERTURE_FIT:
        raise ValueError(
            f"apertures {horizontal:g} x {vertical:g} mm don't fit a {width} x {height} image: give "
            f"vertical_aperture {horizontal / aspect:.4g} for horizontal_aperture {horizontal:g}, or leave one out to "
            "have it fitted"
        )
    return Lens(focal_length if focal_length is not None else FOCAL_LENGTH, horizontal, vertical)


def clipping_range(meters_per_unit: float) -> tuple[float, float]:
    """CLIPPING_METRES in the stage's units."""
    near, far = CLIPPING_METRES
    return near / meters_per_unit, far / meters_per_unit


Selections = Mapping[str, Mapping[str, str]]


@dataclass(frozen=True)
class Shot:
    """One picture: a pose (a position with a yaw and pitch, a position and a target, or a camera of the stage's), a
    lens (None for a camera's own), the selections it shows and the timeline's time, None to leave the timeline as it
    was at the sweep's start."""

    name: str = ""
    position: tuple[float, float, float] | None = None
    yaw: float | None = None
    pitch: float | None = None
    target: tuple[float, float, float] | None = None
    camera_path: str = ""
    lens: Lens | None = None
    clipping: tuple[float, float] | None = None  # None: CLIPPING_METRES in the stage's units
    selections: Selections = field(default_factory=dict[str, Mapping[str, str]])
    time: float | None = None


# ----- reading shots -----


def _number(value: object, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError(f"{what} must be a number, got {value!r}")
    return float(value)


def _positive(value: object, what: str) -> float:
    number = _number(value, what)
    if number <= 0:
        raise ValueError(f"{what} must be above 0, got {value!r}")
    return number


def _point(value: object, what: str) -> tuple[float, float, float]:
    items = cast("list[object]", value) if isinstance(value, list | tuple) else None
    if items is None or len(items) != 3:
        raise ValueError(f"{what} must be [x, y, z], 3 numbers, got {value!r}")
    x, y, z = (_number(v, what) for v in items)
    return x, y, z


def _prim_path(value: object, what: str) -> str:
    if not isinstance(value, str) or not Sdf.Path.IsValidPathString(value):
        raise ValueError(f"{what} must be a prim path, such as /World/Camera, got {value!r}")
    path = Sdf.Path(value)
    if not path.IsAbsolutePath() or not path.IsPrimPath():
        raise ValueError(f"{what} must be an absolute prim path, such as /World/Camera, got {value!r}")
    return str(path)


def _selections(value: object) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        example = '{"/World/Dock": {"door": "open"}}'
        raise ValueError(f"selections must be {{prim: {{set: variant}}}}, such as {example}, got {value!r}")
    found: dict[str, dict[str, str]] = {}
    for prim, sets in cast("dict[object, object]", value).items():
        path = _prim_path(prim, "a selection's prim")
        if not isinstance(sets, dict) or not sets:
            raise ValueError(f"selections of {path} must be {{set: variant}}, got {sets!r}")
        chosen: dict[str, str] = {}
        for name, variant in cast("dict[object, object]", sets).items():
            if not isinstance(name, str) or not name or not isinstance(variant, str) or not variant:
                raise ValueError(
                    f"{path}'s selections name a variant set and a variant, both names, got {name!r}: {variant!r}"
                )
            chosen[name] = variant
        found[path] = chosen
    return found


def _clipping(value: object) -> tuple[float, float]:
    items = cast("list[object]", value) if isinstance(value, list | tuple) else None
    if items is None or len(items) != 2:
        raise ValueError(f"clipping_range must be [near, far], got {value!r}")
    near, far = (_positive(v, "clipping_range") for v in items)
    if near >= far:
        raise ValueError(f"clipping_range's near must be under its far, got {value!r}")
    return near, far


def _shot(raw: object, width: int, height: int, from_manifest: bool) -> Shot:
    if not isinstance(raw, dict):
        raise ValueError(f"a shot is an object of its fields, got {raw!r}")
    entry = cast("dict[str, object]", raw)
    known = _FIELDS | _MANIFEST_FIELDS if from_manifest else _FIELDS
    unknown = sorted(str(k) for k in entry if k not in known)
    if unknown:
        raise ValueError(f"unknown fields {', '.join(unknown)}; a shot's fields: {', '.join(sorted(_FIELDS))}")
    name = entry.get("name", "")
    if not isinstance(name, str) or len(name) > _LONGEST_NAME:
        raise ValueError(f"name must be text of up to {_LONGEST_NAME} characters, got {name!r}")
    camera_path = entry.get("camera_path") or ""
    if from_manifest and camera_path and entry.get("position") is not None:
        # Taken through a camera of its stage: read back as the pose and lens it rendered with, which the manifest
        # records, so a twin on another scene takes the same view without that scene having the camera (round 2, P15).
        camera_path = ""
    lens_given = {k: entry[k] for k in _LENS_FIELDS if entry.get(k) is not None}
    clipping_given = entry.get("clipping_range")
    pose = {k: entry[k] for k in ("position", "yaw", "pitch", "target") if entry.get(k) is not None}
    if camera_path:
        path = _prim_path(camera_path, "camera_path")
        if pose or lens_given or clipping_given is not None:
            given = ", ".join([*pose, *lens_given, *(["clipping_range"] if clipping_given is not None else [])])
            raise ValueError(
                f"a camera_path shot renders through {path} as it is: give a pose and a lens, or camera_path, not both "
                f"(it also gives {given})"
            )
        return Shot(
            name, camera_path=path, selections=_selections(entry.get("selections")), time=_time(entry.get("time"))
        )
    if "position" not in pose:
        raise ValueError("a shot needs a pose: position with yaw (and pitch) or with target, or camera_path")
    position = _point(pose["position"], "position")
    target = yaw = pitch = None
    if "target" in pose:
        if "yaw" in pose or "pitch" in pose:
            raise ValueError("give position with yaw and pitch, or with target, not both")
        target = _point(pose["target"], "target")
        if target == position:
            raise ValueError(f"target {list(target)} is the position: there is nothing to look at")
    elif "yaw" in pose:
        yaw = _number(pose["yaw"], "yaw")
        pitch = _number(pose.get("pitch", 0.0), "pitch")
        if not -90 <= pitch <= 90:
            raise ValueError(f"pitch must be from -90 (straight down) to 90 (straight up) degrees, got {pitch:g}")
    else:
        raise ValueError("position needs yaw (and pitch) or target, to say where the camera looks")
    lens = fit_lens(
        width,
        height,
        _positive(lens_given["focal_length"], "focal_length") if "focal_length" in lens_given else None,
        _positive(lens_given["horizontal_aperture"], "horizontal_aperture")
        if "horizontal_aperture" in lens_given
        else None,
        _positive(lens_given["vertical_aperture"], "vertical_aperture") if "vertical_aperture" in lens_given else None,
    )
    return Shot(
        name,
        position=position,
        yaw=yaw,
        pitch=pitch,
        target=target,
        lens=lens,
        clipping=_clipping(clipping_given) if clipping_given is not None else None,
        selections=_selections(entry.get("selections")),
        time=_time(entry.get("time")),
    )


def _time(value: object) -> float | None:
    return None if value is None else _number(value, "time")


def read_shots(value: object, width: int, height: int) -> list[Shot]:
    """The shots of a list of them, or of a sweep's manifest (a dict with its "shots"), at width x height, every one
    checked first. ValueError naming each shot at fault, by its number from 1, the first few of them."""
    mapping = cast("dict[str, object]", value) if isinstance(value, dict) else {}
    from_manifest = "shots" in mapping
    items = mapping.get("shots") if from_manifest else cast("object", value)
    kind = "a manifest without a list of shots" if from_manifest else type(items).__name__
    entries = cast("list[object]", items) if isinstance(items, list) else None
    if entries is None:
        raise ValueError(f"shots must be a list of shots, or a sweep's manifest, got {kind}")
    if not entries:
        raise ValueError("shots is empty: give at least one shot")
    if len(entries) > MAX_SHOTS:
        raise ValueError(f"{len(entries)} shots is more than a sweep takes, {MAX_SHOTS}: split them into sweeps")
    shots: list[Shot] = []
    faults: list[str] = []
    for index, raw in enumerate(entries, 1):
        try:
            shots.append(_shot(raw, width, height, from_manifest))
        except ValueError as e:
            faults.append(f"shot {index}: {e}")
    if faults:
        more = len(faults) - _SHOWN_FAULTS
        shown = faults[:_SHOWN_FAULTS] + ([f"and {more} more"] if more > 0 else [])
        raise ValueError("\n".join(shown))
    return shots


# ----- poses -----


def direction(yaw: float, pitch: float, up_axis: str) -> Gf.Vec3d:
    """The unit vector a camera at yaw and pitch, in degrees, looks along: yaw about the stage's up axis, counter-
    clockwise seen from above, 0 along +X; pitch above the horizon, -90 straight down."""
    y, p = math.radians(yaw), math.radians(pitch)
    across, ahead, up = math.cos(p) * math.cos(y), math.cos(p) * math.sin(y), math.sin(p)
    if up_axis == "Z":
        return Gf.Vec3d(across, ahead, up)
    # About +Y, counter-clockwise from above, turns +X towards -Z.
    return Gf.Vec3d(across, up, -ahead)


def yaw_pitch(forward: Gf.Vec3d, up_axis: str) -> tuple[float, float]:
    """The yaw and pitch, in degrees, of a camera looking along forward: direction's inverse."""
    unit = forward.GetNormalized()
    x, y, z = floats(unit)
    up, across, ahead = (z, x, y) if up_axis == "Z" else (y, x, -z)
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, up))))
    yaw = math.degrees(math.atan2(ahead, across)) if abs(up) < 1 - 1e-12 else 0.0
    return yaw, pitch


def pose(shot: Shot, up_axis: str) -> tuple[Gf.Vec3d, Gf.Vec3d]:
    """A shot's eye and the point it looks at, for core/xform.py's aim; ValueError for a camera_path shot."""
    if shot.position is None:
        raise ValueError(f"a camera_path shot renders through {shot.camera_path}, which has a pose of its own")
    eye = Gf.Vec3d(*shot.position)
    if shot.target is not None:
        return eye, Gf.Vec3d(*shot.target)
    return eye, eye + direction(shot.yaw or 0.0, shot.pitch or 0.0, up_axis)


# ----- selections -----

# A (prim, set)'s selection in the session layer: absent (None), blocked ("") or a variant's name.
SetKey = tuple[str, str]
Held = dict[SetKey, str | None]
# What to write before a shot, by prim and set: a variant's name, "" for a block, None to clear.
Changes = dict[str, dict[str, str | None]]


def named(shots: Iterable[Shot]) -> list[SetKey]:
    """Every (prim, set) any shot selects, in the order they first come."""
    found: dict[SetKey, None] = {}
    for shot in shots:
        for prim, sets in shot.selections.items():
            for name in sets:
                found[prim, name] = None
    return list(found)


def held(layer: Sdf.Layer, keys: Iterable[SetKey]) -> Held:
    """What layer holds of each (prim, set) now: absent, blocked or a name."""
    return {(prim, name): variants.selections_of(layer, prim).get(name) for prim, name in keys}


def changes(start: Held, written: Held, shot: Shot) -> Changes:
    """The selections to write before shot: each (prim, set) it names, and each it doesn't, which goes back to its
    starting value, absent, blocked or named, not to a clear, so a selection made before the sweep holds for every shot
    that doesn't name its set (round 1, P1). Against `written`, the values last written, never the last shot asked
    for: after a shot whose switch was refused nothing it asked for counts as shown (round 2, P13). A run of shots in
    one state writes nothing."""
    out: Changes = {}
    for key, before in start.items():
        prim, name = key
        wanted = shot.selections.get(prim, {}).get(name, before)
        if written.get(key, before) != wanted:
            out.setdefault(prim, {})[name] = wanted
    return out


def written_after(written: Held, done: Changes) -> Held:
    """`written` once `done` is written."""
    after = dict(written)
    for prim, sets in done.items():
        for name, value in sets.items():
            after[prim, name] = value
    return after


def refusals(stage: Usd.Stage, shots: Iterable[Shot], layer: Sdf.Layer) -> list[str]:
    """Why each selection a shot asks for would be refused in layer, where its prim and set exist now (round 1, P8): a
    misspelled variant fails at the start, not at its shot. A prim or set that only a switch brings in is checked at its
    shot."""
    reasons: dict[str, None] = {}
    for shot in shots:
        for prim_path, sets in shot.selections.items():
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                continue
            for name, variant in sets.items():
                if not prim.GetVariantSets().HasVariantSet(name):
                    continue
                why = variants.variant_refusal(prim, name, variant, layer)
                if why:
                    reasons[why] = None
    return list(reasons)


def switch(stage: Usd.Stage, out: Changes, layer: Sdf.Layer) -> list[variants.Snapshot]:
    """Writes `out` into layer and returns the snapshots that put it back: names and clears through #155's switch, a
    block, which switch would take for a clear, through the block helper (round 2, P11). ValueError, with nothing
    written, when any one is refused."""
    plain = {
        Sdf.Path(prim): {name: value or "" for name, value in sets.items() if value != ""} for prim, sets in out.items()
    }
    plain = {prim: sets for prim, sets in plain.items() if sets}
    blocks = {Sdf.Path(prim): [name for name, value in sets.items() if value == ""] for prim, sets in out.items()}
    blocks = {prim: names for prim, names in blocks.items() if names}
    reasons: list[str] = []
    for path, names in blocks.items():
        prim = stage.GetPrimAtPath(path)
        if not prim.IsValid():
            reasons.append(f"Prim not found: {path}")
            continue
        reasons += [why for name in names if (why := variants.variant_refusal(prim, name, "", layer))]
    if reasons:
        raise ValueError("\n".join(reasons))
    snapshots = [variants.switch(stage, plain, layer)] if plain else []
    if blocks:
        snapshot = variants.Snapshot(layer)
        for path, names in blocks.items():
            snapshot.keep(path, names)
        with Sdf.ChangeBlock():
            for path, names in blocks.items():
                spec = prim_spec(layer, path)
                for name in names:
                    select(spec if spec is not None else Sdf.CreatePrimInLayer(layer, path), name, "")
        snapshot.wrote = True
        snapshots.append(snapshot)
    return snapshots


# ----- the timeline -----


class Timeline(Protocol):
    """What a sweep uses of Kit's timeline (omni.timeline's Timeline, Kit 105 and up)."""

    def is_playing(self) -> bool: ...
    def is_stopped(self) -> bool: ...
    def get_current_time(self) -> float: ...
    def set_current_time(self, time_in_seconds: float) -> None: ...
    def play(self) -> None: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def commit(self) -> None: ...


@dataclass(frozen=True)
class TimelineStart:
    """The timeline's state and time at a sweep's start, which a shot without a time and the sweep's end put back."""

    playing: bool
    stopped: bool
    time: float

    @classmethod
    def read(cls, timeline: Timeline) -> "TimelineStart":
        return cls(timeline.is_playing(), timeline.is_stopped(), timeline.get_current_time())

    @staticmethod
    def seek(timeline: Timeline, time: float) -> None:
        """A timed shot's time: a playing timeline paused first, a stopped one left stopped (round 1, I11), since a
        stop puts the simulation back and a play would step it. Committed at once, so the shot's frames show it."""
        if timeline.is_playing():
            timeline.pause()
        timeline.set_current_time(time)
        timeline.commit()

    def restore(self, timeline: Timeline) -> None:
        """The state and time of the start again, committed when anything changed: a commit runs the timeline's
        callbacks, which a shot without a time after another such shot has no need of. A timeline playing at the start
        that is still playing is left to play, as nothing of the sweep stopped it."""
        changed = False
        if self.playing:
            if not timeline.is_playing():
                timeline.set_current_time(self.time)
                timeline.play()
                changed = True
        else:
            if self.stopped and not timeline.is_stopped():
                # Committed before the time is read: a stop puts the time back to the start's.
                timeline.stop()
                timeline.commit()
            elif not self.stopped and timeline.is_playing():
                timeline.pause()
                changed = True
            if timeline.get_current_time() != self.time:
                timeline.set_current_time(self.time)
                changed = True
        if changed:
            timeline.commit()


def still_loading(status: Sequence[Any]) -> bool:
    """Whether omni.usd's stage loading status, (message, files loaded, files to load), says files are loading, as
    Isaac Sim's own tests wait for it."""
    return int(status[2]) > 0


# ----- names, files and the manifest -----


def folder_name(name: object) -> str:
    """name, when it is one plain folder name: letters, digits, '.', '_', '-' and spaces, from a letter or a digit,
    not ending in a dot or a space (Windows drops them). ValueError otherwise, before it is joined to any path (round
    1, P9)."""
    if (
        not isinstance(name, str)
        or len(name) > _LONGEST_NAME
        or not _FOLDER.fullmatch(name)
        or name.endswith((".", " "))
    ):
        raise ValueError(
            "name must be one plain folder name: letters, digits, '.', '_', '-' and spaces, from a letter or a digit, "
            f"up to {_LONGEST_NAME} characters, got {name!r}"
        )
    return name


def file_name(index: int, shot: Shot) -> str:
    """The PNG of shot number index, from 1: `0007.png`, or `0007_dock_a_open.png` for a shot named "dock A open"."""
    safe = _UNSAFE.sub("_", shot.name).strip("._")[:60]
    return f"{index:04d}_{safe}.png" if safe else f"{index:04d}.png"


@dataclass
class Taken:
    """What became of one shot: its file, or why it has none, and what it rendered with."""

    index: int
    shot: Shot
    file: str | None = None
    error: str | None = None
    # A camera_path shot's pose as it rendered: its eye, yaw and pitch.
    position: tuple[float, float, float] | None = None
    yaw: float | None = None
    pitch: float | None = None
    lens: Lens | None = None
    clipping: tuple[float, float] | None = None
    timeline_time: float | None = None
    frame: float | None = None
    is_black: bool = False
    loading: str | None = None
    loading_seconds: float | None = None
    # Whether its capture failed, which may mean the feed renders nothing; not in the manifest, whose error says so.
    capture_failed: bool = False


def entry(taken: Taken) -> dict[str, object]:
    """A shot's entry in the manifest: its name, the pose and lens it rendered with, its selections and time, its file,
    the timeline's time and frame it was taken on, whether it came out black; or why it wasn't taken. Its numbers are
    unrounded, since JSON keeps a float exactly: read back as a shot (read_shots), it is the same shot."""
    shot = taken.shot
    out: dict[str, object] = {"index": taken.index, "name": shot.name}
    if shot.camera_path:
        out["camera_path"] = shot.camera_path
    position = taken.position or shot.position
    if position is not None:
        out["position"] = list(position)
    if shot.target is not None:
        out["target"] = list(shot.target)
    yaw = taken.yaw if taken.yaw is not None else shot.yaw
    pitch = taken.pitch if taken.pitch is not None else shot.pitch
    if yaw is not None:
        out["yaw"] = yaw
        out["pitch"] = pitch or 0.0
    lens = taken.lens or shot.lens
    if lens is not None:
        out["focal_length"] = lens.focal_length
        out["horizontal_aperture"] = lens.horizontal_aperture
        out["vertical_aperture"] = lens.vertical_aperture
    clipping = taken.clipping or shot.clipping
    if clipping is not None:
        out["clipping_range"] = list(clipping)
    out["selections"] = {prim: dict(sets) for prim, sets in shot.selections.items()}
    out["time"] = shot.time
    if taken.file is not None:
        out["file"] = taken.file
        out["is_black"] = taken.is_black
    if taken.timeline_time is not None:
        out["timeline_time"] = taken.timeline_time
    if taken.frame is not None:
        out["frame"] = taken.frame
    if taken.loading_seconds is not None:
        out["loading_seconds"] = round(taken.loading_seconds, 3)
    if taken.loading is not None:
        out["loading"] = taken.loading
    if taken.error is not None:
        out["error"] = taken.error
    return out


def manifest(header: Mapping[str, object], taken: Iterable[Taken]) -> dict[str, object]:
    """The manifest: the sweep's own facts (its size, renderer, Kit app, how it ended), then each shot's entry."""
    return {"format": FORMAT, **header, "shots": [entry(t) for t in taken]}


def _indices(found: Sequence[int]) -> str:
    shown = ", ".join(str(i) for i in found[:_SHOWN_FAULTS])
    more = len(found) - _SHOWN_FAULTS
    return f"{'shot' if len(found) == 1 else 'shots'} {shown}" + (f" and {more} more" if more > 0 else "")


def summary(folder: str, asked: int, taken: Sequence[Taken], ended: str = "") -> str:
    """The sweep's line: `400 shots in .../sweeps/site_a/ (manifest.json); 2 black: shots 12, 13; 1 failed: shot 300`,
    `37 of 400 ...` when it stopped short, and how it ended unless it completed."""
    done = len(taken)
    count = f"{done} of {asked}" if done < asked else f"{done}"
    parts = [f"{count} {'shot' if asked == 1 else 'shots'} in {folder.rstrip(_SEPARATORS)}/ ({MANIFEST})"]
    black = [t.index for t in taken if t.file is not None and t.is_black]
    failed = [t.index for t in taken if t.error is not None]
    late = [t.index for t in taken if t.loading is not None]
    if black:
        parts.append(f"{len(black)} black: {_indices(black)}")
    if failed:
        parts.append(f"{len(failed)} failed: {_indices(failed)}")
    if late:
        parts.append(f"{len(late)} taken still loading: {_indices(late)}")
    if ended:
        parts.append(ended)
    return "; ".join(parts)


def result(folder: str, manifest_path: str, asked: int, taken: Sequence[Taken]) -> dict[str, object]:
    """A completed sweep's result, which get_job reads: where it is, and which shots came out black, failed or were
    taken while files still loaded."""
    return {
        "folder": folder,
        "manifest": manifest_path,
        "asked": asked,
        "done": len(taken),
        "taken": sum(1 for t in taken if t.file is not None),
        "black": [t.index for t in taken if t.file is not None and t.is_black],
        "failed": [t.index for t in taken if t.error is not None],
        "loading": [t.index for t in taken if t.loading is not None],
        "summary": summary(folder, asked, taken),
    }
