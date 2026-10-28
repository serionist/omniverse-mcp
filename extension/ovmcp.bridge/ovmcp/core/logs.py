"""The ring of log messages the bridge keeps, and the /logs query over it.

Subscribing to Kit's log stream is Kit-bound and lives in bridge/handlers/logging.py, which feeds this ring.
"""

import threading
from collections import deque
from typing import Any, SupportsInt

# omni.log.Level's values.
LEVEL_NAMES = {0: "verbose", 1: "info", 2: "warn", 3: "error", 4: "fatal"}
LEVEL_FROM_NAME = {name: level for level, name in LEVEL_NAMES.items()}


class LogRing:
    """The latest messages, up to max_entries, each numbered in arrival order."""

    def __init__(self, max_entries: int = 2000) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._index = 0  # counts every message ever added, for since_index

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
    ) -> None:
        """Keep one message. Kit passes its level as an omni.log.Level, which converts to its int value."""
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
            self._buffer.append({"index": self._index, **entry})
            self._index += 1

    def get_entries(
        self,
        count: int = 50,
        min_level: str | None = None,
        channel: str | None = None,
        since_index: int | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """The last `count` messages that pass every filter given, oldest first.

        Args:
            count: how many at most
            min_level: verbose, info, warn, error or fatal; an unknown name filters nothing
            channel: a substring of the channel, any case
            since_index: only messages numbered above this
            search: a substring of the message, any case
        """
        min_level_num = LEVEL_FROM_NAME.get(min_level, 0) if min_level else 0

        # A copy, taken under the lock: Kit adds messages from other threads while this filters (AGENTS.md, Traps).
        with self._lock:
            entries = list(self._buffer)
            total_captured = self._index

        if since_index is not None:
            entries = [e for e in entries if e["index"] > since_index]
        if min_level_num > 0:
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
