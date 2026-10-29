"""Kit's log as /logs returns it: the ring of entries and its query, filled from Kit's log file.

The bridge hands Kit's logging no Python callback. Kit runs one on the thread that logs, and a physics worker that
logged while Kit's main thread held Python's GIL deadlocked Kit (#5). Each /logs request reads instead what Kit
appended to its log file since the last, on Kit's main thread. bridge/handlers/logging.py hands this module Kit's
/log/file setting and the bridge token.
"""

import os
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, SupportsInt

# carb's levels (carb/logging/Log.h, kLevelVerbose -2 to kLevelFatal 2; the same in Kit 107.3 and Isaac Sim 6.2):
# warn is 0, and the quieter levels are below it.
LEVEL_NAMES = {-2: "verbose", -1: "info", 0: "warn", 1: "error", 2: "fatal"}
LEVEL_FROM_NAME = {name: level for level, name in LEVEL_NAMES.items()}

# The most one read takes from Kit's file: the newest bytes, when more arrived since the last. The ring's 2000 entries
# fit at up to 500 bytes a line, and a day of Kit at Info costs one bounded read, not a frozen main thread.
MAX_READ_BYTES = 1 << 20
REDACTED = "<redacted>"

# How carb's file logger spells each level (carb::logging::levelToString), in any case.
_FILE_LEVELS = {"verbose": -2, "info": -1, "warning": 0, "error": 1, "fatal": 2}

# A line that starts an entry: `2026-01-01T00:00:00Z [1,234ms] [Warning] [some.channel] the message`. Kit's first line
# has no elapsed field, and Kit 107's no time either. The elapsed field's separator follows the locale, so any field
# that starts with a digit is one. The channel is empty for carb.log_* called from a script.
_HEADER = re.compile(
    r"(?:(?P<time>\d{4}-\d\d-\d\d[T ]\S+) )?"
    r"(?:(?P<elapsed>\[\d[^\]]*\]) )?"
    r"\[(?P<level>verbose|info|warning|error|fatal)\] "
    r"\[(?P<channel>[^\]]*)\]"
    r"(?: (?P<msg>.*))?",
    re.IGNORECASE,
)


class Header(NamedTuple):
    """What a header line says. The timestamp is the line's own text: its time and elapsed field, where it has them."""

    timestamp: str
    level: int
    channel: str
    msg: str


def parse_header(line: str) -> Header | None:
    """The entry a line of Kit's log file starts, or None for a line that continues the one before it."""
    match = _HEADER.fullmatch(line)
    if match is None:
        return None
    timestamp = " ".join(part for part in (match["time"], match["elapsed"]) if part)
    return Header(timestamp, _FILE_LEVELS[match["level"].lower()], match["channel"], match["msg"] or "")


def redact(text: str, token: str) -> str:
    """text with every copy of the bridge token replaced. Kit's log can hold it: a token set on Kit's command line is
    in the line Kit writes the command line to, and a reload of the extension or a script could log it."""
    return text.replace(token, REDACTED) if token else text


def log_file_path(setting: object, resolve: Callable[[str], object]) -> str | None:
    """Kit's log file from its /log/file setting; None when the setting is empty, or holds a ${...} token that
    carb.tokens can't resolve. Kit gives the path resolved, so resolve, carb.tokens' own, is asked only when a token
    is left."""
    if not isinstance(setting, str) or not setting.strip():
        return None
    path = resolve(setting) if "${" in setting else setting
    if not isinstance(path, str) or not path.strip() or "${" in path:
        return None
    return path


def no_log_file(setting: object) -> str:
    """The error get_logs gives when log_file_path finds no file."""
    return (
        f"get_logs reads Kit's log file, and Kit's /log/file setting names none it can read ({setting!r}). "
        "Start Kit with --/log/file=<path>."
    )


class LogRing:
    """The latest entries, up to max_entries, each numbered in arrival order."""

    def __init__(self, max_entries: int = 2000) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._index = 0  # counts every entry ever added, for since_index

    def add(
        self,
        channel: str | None,
        level: SupportsInt,
        module: str | None,
        filename: str | None,
        func: str | None,
        line_no: int,
        msg: str | None,
        timestamp: object,
    ) -> int:
        """Keep one entry, and give its index. level is carb's number, or anything that converts to it."""
        level_num = int(level)
        entry: dict[str, Any] = {
            "level": LEVEL_NAMES.get(level_num, str(level)),
            "level_num": level_num,
            "channel": channel or "",
            "module": module or "",
            "source": f"{filename}:{line_no}" if filename else "",
            "func": func or "",
            "msg": msg or "",
            "timestamp": timestamp,
        }
        with self._lock:
            index = self._index
            self._buffer.append({"index": index, **entry})
            self._index += 1
        return index

    def amend(self, index: int, line: str) -> bool:
        """Add a line to entry `index`'s message, while it is the newest; False once another came after it."""
        with self._lock:
            if not self._buffer or self._buffer[-1]["index"] != index:
                return False
            newest = self._buffer[-1]
            newest["msg"] = f"{newest['msg']}\n{line}"
        return True

    def get_entries(
        self,
        count: int = 50,
        min_level: str | None = None,
        channel: str | None = None,
        since_index: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """The last `count` entries that pass every filter given, oldest first.

        Args:
            count: how many at most
            min_level: verbose, info, warn, error or fatal; an unknown name filters nothing
            channel: a substring of the channel, any case
            since_index: only entries numbered above this
            search: a substring of the message, any case
        """
        min_level_num = LEVEL_FROM_NAME.get(min_level) if min_level else None

        # A copy, taken under the lock, so the ring can't change while this filters (AGENTS.md, Traps).
        with self._lock:
            entries = list(self._buffer)
            total_captured = self._index

        if since_index is not None:
            entries = [e for e in entries if e["index"] > since_index]
        if min_level_num is not None:
            entries = [e for e in entries if e["level_num"] >= min_level_num]
        if channel:
            channel_lower = channel.lower()
            entries = [e for e in entries if channel_lower in e["channel"].lower()]
        if search:
            search_lower = search.lower()
            entries = [e for e in entries if search_lower in e["msg"].lower()]

        # level_num is for filtering only.
        entries = [{k: v for k, v in e.items() if k != "level_num"} for e in entries[-count:]]
        return {
            "entries": entries,
            "count": len(entries),
            "total_captured": total_captured,
            "buffer_size": self._buffer.maxlen,
        }


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


class LogFileReader:
    """Kit's log file, read into a ring from where it ended when the reader was made.

    Each read takes what Kit appended since the last, the newest max_read bytes at most. An entry is a header line and
    the lines after it that start none: a multi-line message, or a traceback. It enters the ring with its header, and
    continuation lines amend it, in a later read too.
    """

    def __init__(self, path: str, ring: LogRing, token: str, max_read: int = MAX_READ_BYTES) -> None:
        self.path = Path(path)
        self._ring = ring
        self._token = token
        self._max_read = max_read
        # Kit's first lines hold its command line, where a remote setup passes the bridge token; reading starts after
        # them, where the file ended when the extension started.
        self._offset = _size(self.path)
        self._in_line = False  # the offset is inside a line, after a cut: skip to the next one
        self._open: int | None = None  # the entry continuation lines amend; None after a cut, or before a header

    def read(self) -> None:
        """Read what Kit appended since the last read into the ring. OSError when the file can't be read."""
        with self.path.open("rb") as file:
            size = os.fstat(file.fileno()).st_size
            if size < self._offset:
                # Shorter than what was read: a new file in its place. Start over.
                self._offset, self._in_line, self._open = 0, False, None
            if size - self._offset > self._max_read:
                # A cut: only the newest bytes. Read from the byte before them, to see whether they start a line.
                self._offset, self._in_line, self._open = size - self._max_read - 1, True, None
            file.seek(self._offset)
            data = file.read(size - self._offset)
        start = 0
        if self._in_line:
            start = data.find(b"\n") + 1
            if not start:
                self._offset += len(data)
                return
            self._in_line = False
        end = data.rfind(b"\n") + 1  # a line Kit is still writing waits for the next read
        self._offset += end
        for raw in data[start:end].split(b"\n")[:-1]:
            self._take(raw.decode("utf-8", errors="replace").removesuffix("\r"))

    def _take(self, line: str) -> None:
        line = redact(line, self._token)
        header = parse_header(line)
        if header is None:
            # With no entry open, this continues one from before the cut or the extension's start, which the ring
            # never got.
            if self._open is not None and not self._ring.amend(self._open, line):
                self._open = None
            return
        self._open = self._ring.add(header.channel, header.level, None, None, None, 0, header.msg, header.timestamp)


class KitLog:
    """What /logs answers from: Kit's log file, read into a ring before each query. start() finds the file."""

    def __init__(self, max_entries: int = 2000, max_read: int = MAX_READ_BYTES) -> None:
        self._max_entries = max_entries
        self._max_read = max_read
        self.ring = LogRing(max_entries)
        self._reader: LogFileReader | None = None
        self._error = "get_logs has no log to read: the bridge extension hasn't started"

    def start(self, setting: object, resolve: Callable[[str], object], token: str) -> None:
        """Find Kit's log file from its /log/file setting, and note where it ends now: queries read from there, with
        token redacted."""
        self.ring = LogRing(self._max_entries)
        path = log_file_path(setting, resolve)
        if path is None:
            self._reader, self._error = None, no_log_file(setting)
            return
        self._reader = LogFileReader(path, self.ring, token, self._max_read)

    def query(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """/logs' answer: the newest entries that pass body's filters, after reading what Kit wrote since the last."""
        if self._reader is None:
            return {"status": "error", "error": self._error}
        try:
            self._reader.read()
        except OSError as e:
            return {"status": "error", "error": f"Could not read Kit's log file {self._reader.path}: {e}"}
        result = self.ring.get_entries(
            count=body.get("count", 50),
            min_level=body.get("min_level"),
            channel=body.get("channel"),
            since_index=body.get("since_index"),
            search=body.get("search"),
        )
        return {"status": "success", "result": result}
