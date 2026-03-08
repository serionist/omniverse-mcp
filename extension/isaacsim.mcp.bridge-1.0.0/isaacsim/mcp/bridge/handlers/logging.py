"""
Log buffer — captures Omniverse log messages in a ring buffer for querying.

Uses omni.log.add_message_consumer() to subscribe to all log messages
(carb.log_*, Python logging, etc.) and stores them in a deque.
"""

import threading
import time
from collections import deque
from typing import Optional


# Log level mapping (omni.log.Level values)
_LEVEL_NAMES = {0: "verbose", 1: "info", 2: "warn", 3: "error", 4: "fatal"}
_LEVEL_FROM_NAME = {v: k for k, v in _LEVEL_NAMES.items()}


class LogBuffer:
    """Ring buffer that captures Omniverse log messages."""

    def __init__(self, max_entries: int = 2000):
        self._buffer: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._consumer = None
        self._index = 0  # monotonic counter for since_index support

    def start(self):
        """Subscribe to omni.log message stream."""
        try:
            import omni.log
            log = omni.log.get_log()
            self._consumer = log.add_message_consumer(self._on_log)
        except Exception:
            # omni.log may not be available in all Kit builds
            pass

    def stop(self):
        """Unsubscribe from log messages."""
        if self._consumer is not None:
            try:
                import omni.log
                log = omni.log.get_log()
                log.remove_message_consumer(self._consumer)
            except Exception:
                pass
            self._consumer = None

    def _on_log(self, channel, level, module, filename, func, line_no, msg, pid, tid, timestamp):
        # Do NOT log from within this callback (undefined behavior per omni.log docs)
        # level may be an omni.log.Level enum — coerce to int for comparisons
        level_int = int(level) if not isinstance(level, int) else level
        entry = {
            "index": self._index,
            "level": _LEVEL_NAMES.get(level_int, str(level)),
            "level_num": level_int,
            "channel": channel or "",
            "module": module or "",
            "source": f"{filename}:{line_no}" if filename else "",
            "func": func or "",
            "msg": msg or "",
            "timestamp": timestamp,
        }
        with self._lock:
            self._buffer.append(entry)
            self._index += 1

    def get_entries(
        self,
        count: int = 50,
        min_level: Optional[str] = None,
        channel: Optional[str] = None,
        since_index: Optional[int] = None,
        search: Optional[str] = None,
    ) -> dict:
        """Query recent log entries.

        Args:
            count: Max entries to return (default 50)
            min_level: Minimum level filter: verbose/info/warn/error/fatal
            channel: Filter by channel substring
            since_index: Only entries with index > this value
            search: Filter by message substring (case-insensitive)
        """
        min_level_num = _LEVEL_FROM_NAME.get(min_level, 0) if min_level else 0

        with self._lock:
            entries = list(self._buffer)
            total_captured = self._index

        # Apply filters
        if since_index is not None:
            entries = [e for e in entries if e["index"] > since_index]
        if min_level_num > 0:
            entries = [e for e in entries if int(e["level_num"]) >= min_level_num]
        if channel:
            channel_lower = channel.lower()
            entries = [e for e in entries if channel_lower in e["channel"].lower()]
        if search:
            search_lower = search.lower()
            entries = [e for e in entries if search_lower in e["msg"].lower()]

        # Take last N and strip level_num (internal use only)
        entries = [
            {k: v for k, v in e.items() if k != "level_num"}
            for e in entries[-count:]
        ]

        return {
            "entries": entries,
            "count": len(entries),
            "total_captured": total_captured,
            "buffer_size": self._buffer.maxlen,
        }


# Singleton instance — created on import, started from extension.py
log_buffer = LogBuffer()


# ---------------------------------------------------------------------------
# /logs
# ---------------------------------------------------------------------------

async def handle_get_logs(body: dict) -> dict:
    """Return recent log entries from the ring buffer."""
    result = log_buffer.get_entries(
        count=body.get("count", 50),
        min_level=body.get("min_level"),
        channel=body.get("channel"),
        since_index=body.get("since_index"),
        search=body.get("search"),
    )
    return {"status": "success", "result": result}
