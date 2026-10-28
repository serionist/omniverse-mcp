"""
Log buffer — captures Omniverse log messages in a ring buffer for querying.

Uses omni.log.add_message_consumer() to subscribe to all log messages
(carb.log_*, Python logging, etc.); the ring and its query are ovmcp.core.logs.
"""

from ovmcp.core.logs import LogRing


class LogBuffer(LogRing):
    """The log ring, fed by Kit's log stream between start() and stop()."""

    def __init__(self, max_entries: int = 2000):
        super().__init__(max_entries)
        self._consumer = None

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
        self.add(channel, level, module, filename, func, line_no, msg, timestamp)


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
