"""The bridge's log ring and its /logs query: what get_logs returns."""

import sys
import threading

from ovmcp.core.logs import LogRing


class _Level:
    """Stands in for omni.log.Level, which Kit passes and which converts to its int value."""

    def __init__(self, value: int):
        self.value = value

    def __int__(self) -> int:
        return self.value

    def __str__(self) -> str:
        return f"Level.{self.value}"


def _ring(*messages: tuple[str, int, str], max_entries: int = 2000) -> LogRing:
    ring = LogRing(max_entries)
    for channel, level, msg in messages:
        ring.add(channel, level, "mod", "file.py", "func", 7, msg, 1.5)
    return ring


def test_an_entry_says_where_it_came_from():
    ring = LogRing()
    ring.add("omni.usd", _Level(1), "usd", "stage.cpp", "open", 42, "Could not open", 99.0)
    ring.add(None, -1, None, None, None, 0, None, 100.0)

    result = ring.get_entries()

    assert result == {
        "entries": [
            {
                "index": 0,
                "level": "error",
                "channel": "omni.usd",
                "module": "usd",
                "source": "stage.cpp:42",
                "func": "open",
                "msg": "Could not open",
                "timestamp": 99.0,
            },
            {
                "index": 1,
                "level": "info",
                "channel": "",
                "module": "",
                "source": "",
                "func": "",
                "msg": "",
                "timestamp": 100.0,
            },
        ],
        "count": 2,
        "total_captured": 2,
        "buffer_size": 2000,
    }


def test_an_unknown_level_is_named_by_what_kit_passed():
    ring = LogRing()
    ring.add("c", _Level(9), None, None, None, 0, "m", 0)

    assert ring.get_entries()["entries"][0]["level"] == "Level.9"


def test_the_ring_keeps_the_latest_and_counts_them_all():
    ring = _ring(*[("c", 1, f"m{i}") for i in range(5)], max_entries=3)

    result = ring.get_entries()

    assert [e["msg"] for e in result["entries"]] == ["m2", "m3", "m4"]
    assert [e["index"] for e in result["entries"]] == [2, 3, 4]
    assert (result["total_captured"], result["buffer_size"]) == (5, 3)


def test_count_keeps_the_last_ones():
    ring = _ring(*[("c", 1, f"m{i}") for i in range(10)])

    assert [e["msg"] for e in ring.get_entries(count=3)["entries"]] == ["m7", "m8", "m9"]


def test_the_filters():
    # Kit's levels, as omni.log.Level gives them on Isaac Sim 6.2: verbose -2, info -1, warn 0, error 1, fatal 2.
    ring = _ring(
        ("omni.physx", -2, "verbose step"),
        ("omni.usd", -1, "stage opened"),
        ("omni.physx", 0, "Joint limit EXCEEDED"),
        ("omni.kit.app", 1, "extension failed"),
        ("ovmcp.bridge", 2, "bridge stopped"),
    )

    def msgs(**filters):
        return [e["msg"] for e in ring.get_entries(**filters)["entries"]]

    assert [e["level"] for e in ring.get_entries()["entries"]] == ["verbose", "info", "warn", "error", "fatal"]
    assert msgs(min_level="warn") == ["Joint limit EXCEEDED", "extension failed", "bridge stopped"]
    assert msgs(min_level="info") == ["stage opened", "Joint limit EXCEEDED", "extension failed", "bridge stopped"]
    assert msgs(min_level="fatal") == ["bridge stopped"]
    assert msgs(min_level="verbose") == msgs()
    assert msgs(min_level="nonsense") == msgs()
    assert msgs(channel="PHYSX") == ["verbose step", "Joint limit EXCEEDED"]
    assert msgs(search="exceeded") == ["Joint limit EXCEEDED"]
    assert msgs(since_index=2) == ["extension failed", "bridge stopped"]
    assert msgs(channel="omni", min_level="error", since_index=0) == ["extension failed"]


def test_level_num_stays_inside():
    assert "level_num" not in _ring(("c", 2, "m")).get_entries()["entries"][0]


def test_a_query_while_kit_logs_from_another_thread():
    # Filtering iterated the live buffer, and Kit's logging thread changed it underneath (AGENTS.md, Traps). A full
    # ring and a short switch interval make the logging thread run in the middle of a query.
    ring = _ring(*[("chan", 1, "msg")] * 20_000, max_entries=20_000)
    stop = threading.Event()

    def log() -> None:
        i = 0
        while not stop.is_set():
            ring.add("chan", i % 5 - 2, None, None, None, 0, f"msg {i}", i)  # Kit's levels, -2 to 2
            i += 1

    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    writer = threading.Thread(target=log)
    writer.start()
    try:
        for _ in range(50):
            result = ring.get_entries(count=100, min_level="info", channel="chan", search="msg")
            assert result["count"] == 100
    finally:
        stop.set()
        writer.join()
        sys.setswitchinterval(interval)
