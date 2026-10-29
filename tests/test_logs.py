"""The bridge's log: the ring and its /logs query, the reader that fills it from Kit's log file, and the guard that
keeps Python callbacks off Kit's logging (#5). Every log line here is invented, in the shapes Kit 107 and Kit 110
write: real ones carry a machine's user folder and build ids."""

import sys
import threading
from pathlib import Path

import pytest

from ovmcp.core.logs import (
    MAX_READ_BYTES,
    REDACTED,
    Header,
    KitLog,
    LogFileReader,
    LogRing,
    log_file_path,
    no_log_file,
    parse_header,
    redact,
)

EXTENSION = Path(__file__).resolve().parents[1] / "extension" / "ovmcp.bridge"
TOKEN = "invented-token-Q1w2E3r4"


class _Level:
    """Stands in for a level object that converts to carb's number."""

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


# ----- The guard -----

# Each hands Kit's logging a Python callback that Kit then runs on whichever thread logs: omni.log's consumers and
# loggers, carb's log event stream, and omni.kit.app's error_log events, by constant or by event name. A physics worker
# that logged while Kit's main thread held the GIL waited on one of ours forever, and so did Kit (#5).
LOG_HOOKS = ("add_message_consumer", "add_channel_update_consumer", "add_logger", "get_log_event_stream", "error_log")


def test_the_bridge_hands_kits_logging_no_python_callback():
    files = [p for p in sorted(EXTENSION.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
    assert EXTENSION / "ovmcp" / "bridge" / "handlers" / "logging.py" in files  # the scan sees the bridge's code
    found = [
        f"{path.relative_to(EXTENSION).as_posix()}: {hook}"
        for path in files
        for hook in LOG_HOOKS
        if hook.encode() in path.read_bytes()
    ]
    assert not found, (
        "A Python hook on Kit's logging deadlocks Kit when a worker logs while the main thread holds the GIL (#5, "
        f"AGENTS.md Traps); get_logs reads Kit's log file instead: {found}"
    )


# ----- The ring -----


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


def test_an_unknown_level_is_named_by_what_was_passed():
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
    # carb's levels: verbose -2, info -1, warn 0, error 1, fatal 2.
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


def test_only_the_newest_entry_takes_another_line():
    ring = _ring(("c", 1, "first"), ("c", 1, "second"))

    assert not ring.amend(0, "late")
    assert ring.amend(1, "more")
    assert [e["msg"] for e in ring.get_entries()["entries"]] == ["first", "second\nmore"]
    assert not LogRing().amend(0, "nothing to amend")


def test_a_query_while_another_thread_adds():
    # Filtering iterated the live buffer, and a thread that added changed it underneath (AGENTS.md, Traps). A full
    # ring and a short switch interval make the adding thread run in the middle of a query.
    ring = _ring(*[("chan", 1, "msg")] * 20_000, max_entries=20_000)
    stop = threading.Event()

    def log() -> None:
        i = 0
        while not stop.is_set():
            ring.add("chan", i % 5 - 2, None, None, None, 0, f"msg {i}", i)  # carb's levels, -2 to 2
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


# ----- A line of Kit's log file -----


def test_a_header_line_in_each_shape():
    # Kit 110's and Kit 107's lines; the first line of the file has no elapsed field, and on Kit 107 no time either.
    assert parse_header("2026-01-01T00:00:00Z [1,234,567ms] [Warning] [some.channel] the message") == Header(
        "2026-01-01T00:00:00Z [1,234,567ms]", 0, "some.channel", "the message"
    )
    assert parse_header("2026-01-01T00:00:00Z [Info] [carb] Logging to file: C:/invented/logs/kit.log") == Header(
        "2026-01-01T00:00:00Z", -1, "carb", "Logging to file: C:/invented/logs/kit.log"
    )
    assert parse_header("[Info] [carb] Logging to file: /invented/logs/kit.log") == Header(
        "", -1, "carb", "Logging to file: /invented/logs/kit.log"
    )


@pytest.mark.parametrize("elapsed", ["[0ms]", "[456,355ms]", "[456.355ms]", "[456355ms]", "[456\u202f355ms]"])
def test_the_elapsed_field_takes_any_separator(elapsed):
    header = parse_header(f"2026-01-01T00:00:00Z {elapsed} [Info] [omni.example] invented")

    assert header == Header(f"2026-01-01T00:00:00Z {elapsed}", -1, "omni.example", "invented")


@pytest.mark.parametrize(
    ("word", "level", "name"),
    [
        ("Verbose", -2, "verbose"),
        ("Info", -1, "info"),
        ("Warning", 0, "warn"),
        ("Error", 1, "error"),
        ("FATAL", 2, "fatal"),
    ],
)
def test_every_level(word, level, name):
    header = parse_header(f"2026-01-01T00:00:00Z [12ms] [{word}] [omni.example] invented")
    assert header is not None
    assert header.level == level

    ring = LogRing()
    ring.add(header.channel, header.level, None, None, None, 0, header.msg, header.timestamp)
    assert ring.get_entries()["entries"][0]["level"] == name


def test_the_channel_and_the_message():
    # carb.log_* called from a script has no channel.
    assert parse_header("2026-01-01T00:00:00Z [5ms] [Error] [] from a script") == Header(
        "2026-01-01T00:00:00Z [5ms]", 1, "", "from a script"
    )
    assert parse_header("2026-01-01T00:00:00Z [5ms] [Info] [omni.example]") == Header(
        "2026-01-01T00:00:00Z [5ms]", -1, "omni.example", ""
    )
    assert parse_header("2026-01-01T00:00:00Z [5ms] [Info] [omni.example]   indented [x] text") == Header(
        "2026-01-01T00:00:00Z [5ms]", -1, "omni.example", "  indented [x] text"
    )


@pytest.mark.parametrize(
    "line",
    [
        "Traceback (most recent call last):",
        '  File "C:/invented/script.py", line 3, in <module>',
        "ValueError: invented",
        "b",
        "",
        "2026-01-01T00:00:00Z [5ms] [Notice] [omni.example] a level carb doesn't have",
        "2026-01-01T00:00:00Z [5ms] [Info] omni.example without its brackets",
        "    commandLine: kit.exe --invented",
    ],
)
def test_a_line_that_starts_no_entry(line):
    assert parse_header(line) is None


# ----- The token -----


def test_the_token_is_redacted_wherever_it_appears():
    assert redact(f"--/exts/ovmcp.bridge/token={TOKEN} and {TOKEN}", TOKEN) == (
        f"--/exts/ovmcp.bridge/token={REDACTED} and {REDACTED}"
    )
    assert redact("nothing secret", TOKEN) == "nothing secret"
    assert redact("an empty token redacts nothing", "") == "an empty token redacts nothing"


# ----- Kit's /log/file setting -----


def _no_resolve(_text: str) -> object:
    raise AssertionError("a path without ${...} is never resolved")


def test_the_log_file_from_kits_setting():
    assert log_file_path("C:/invented/logs/kit_20260101_000000.log", _no_resolve) == (
        "C:/invented/logs/kit_20260101_000000.log"
    )
    resolved = log_file_path("${logs}/kit_${start_timestamp}.log", lambda text: "/invented/logs/kit_1.log")
    assert resolved == "/invented/logs/kit_1.log"


@pytest.mark.parametrize(
    ("setting", "resolved"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (42, None),
        ("${logs}/kit.log", "${logs}/kit.log"),  # carb.tokens left a token it doesn't know
        ("${logs}/kit.log", None),  # carb.tokens failed
        ("${logs}/kit.log", ""),
    ],
)
def test_no_log_file_from_an_empty_or_unresolved_setting(setting, resolved):
    assert log_file_path(setting, lambda _text: resolved) is None
    assert "--/log/file=<path>" in no_log_file(setting)
    assert repr(setting) in no_log_file(setting)


# ----- Reading Kit's log file -----


def _line(msg: str, level: str = "Info", channel: str = "omni.example") -> str:
    return f"2026-01-01T00:00:00Z [1,234ms] [{level}] [{channel}] {msg}\n"


def _append(path: Path, text: str | bytes) -> None:
    with path.open("ab") as file:
        file.write(text.encode() if isinstance(text, str) else text)


def _reader(tmp_path: Path, before: str = "", **kwargs) -> tuple[Path, LogFileReader, LogRing]:
    path = tmp_path / "kit_20260101_000000.log"
    path.write_bytes(before.encode())
    ring = LogRing(kwargs.pop("max_entries", 2000))
    return path, LogFileReader(str(path), ring, kwargs.pop("token", TOKEN), **kwargs), ring


def _msgs(ring: LogRing) -> list[str]:
    return [e["msg"] for e in ring.get_entries(count=100_000)["entries"]]


def test_reading_starts_where_the_file_ended_when_the_reader_was_made(tmp_path):
    # Kit's first lines hold its command line, and a remote setup passes the token there.
    opening = "[Info] [carb] Logging to file: /invented/logs/kit.log\n" + _line(
        f"Cmd: kit.exe --/exts/ovmcp.bridge/token={TOKEN}", channel="omni.kit.app.plugin"
    )
    path, reader, ring = _reader(tmp_path, opening)
    _append(path, _line("after the start"))

    reader.read()

    assert _msgs(ring) == ["after the start"]
    reader.read()  # nothing new
    assert ring.get_entries()["total_captured"] == 1


def test_a_file_not_there_yet_is_read_from_its_start(tmp_path):
    path = tmp_path / "kit_20260101_000000.log"
    ring = LogRing()
    reader = LogFileReader(str(path), ring, TOKEN)
    path.write_text("[Info] [carb] Logging to file: /invented/logs/kit.log\n", encoding="utf-8")

    reader.read()

    assert _msgs(ring) == ["Logging to file: /invented/logs/kit.log"]


def test_an_entry_from_kits_file(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("invented warning", level="Warning", channel="omni.physx.cooking.plugin"))

    reader.read()

    assert ring.get_entries()["entries"] == [
        {
            "index": 0,
            "level": "warn",
            "channel": "omni.physx.cooking.plugin",
            "module": "",
            "source": "",
            "func": "",
            "msg": "invented warning",
            "timestamp": "2026-01-01T00:00:00Z [1,234ms]",
        }
    ]


def test_a_multi_line_message_is_one_entry(tmp_path):
    # carb.log_error("a\nb\nc") writes b and c on lines of their own, with no header.
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("a", level="Error", channel="") + "b\nc\n" + _line("next"))

    reader.read()

    assert _msgs(ring) == ["a\nb\nc", "next"]


def test_a_logged_traceback_joins_its_entry(tmp_path):
    # logging.error(..., exc_info=True): the traceback's first line is not indented.
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "C:/invented/script.py", line 3, in <module>\n'
        "    raise ValueError('invented')\n"
        "ValueError: invented\n"
    )
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("x", level="Error", channel="ovmcp.probe") + traceback + _line("after"))

    reader.read()

    assert _msgs(ring) == ["x\n" + traceback.rstrip("\n"), "after"]


def test_continuation_lines_in_a_later_read_amend_the_newest_entry(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("Traceback follows", level="Error"))
    reader.read()
    assert _msgs(ring) == ["Traceback follows"]  # in the ring at once

    _append(path, "Traceback (most recent call last):\nValueError: invented\n")
    reader.read()

    assert _msgs(ring) == ["Traceback follows\nTraceback (most recent call last):\nValueError: invented"]
    assert ring.get_entries()["total_captured"] == 1


def test_lines_before_the_first_header_are_left_out(tmp_path):
    # The tail of an entry Kit wrote before the extension started.
    path, reader, ring = _reader(tmp_path)
    _append(path, "  an orphan line\n" + _line("first"))

    reader.read()

    assert _msgs(ring) == ["first"]


def test_a_continuation_never_joins_an_entry_another_writer_added(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("read"))
    reader.read()
    ring.add("other", 0, None, None, None, 0, "added by hand", "")

    _append(path, "not a header\n")
    reader.read()
    _append(path, "nor this\n")
    reader.read()

    assert _msgs(ring) == ["read", "added by hand"]


def test_a_partial_last_line_waits_for_the_next_read(tmp_path):
    path, reader, ring = _reader(tmp_path)
    whole = _line("written in two parts")
    _append(path, whole[:30])

    reader.read()
    assert _msgs(ring) == []

    _append(path, whole[30:])
    reader.read()
    assert _msgs(ring) == ["written in two parts"]


def test_crlf_line_endings(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("windows").replace("\n", "\r\n") + "continued\r\n")

    reader.read()

    assert _msgs(ring) == ["windows\ncontinued"]


def test_invalid_utf8_is_replaced(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("bad ").encode().replace(b"bad ", b"bad \xff\xfe byte"))

    reader.read()

    assert _msgs(ring) == ["bad \ufffd\ufffd byte"]


def test_byte_offsets_after_non_ascii_text(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line("probe é ✓"))
    reader.read()
    _append(path, _line("the next one"))

    reader.read()

    assert _msgs(ring) == ["probe é ✓", "the next one"]


def test_a_shorter_file_starts_over(tmp_path):
    path, reader, ring = _reader(tmp_path, _line("before the start") * 3)
    _append(path, _line("read", level="Error"))
    reader.read()

    # A new file in its place, shorter than what was read; its first line continues nothing of the old one.
    path.write_bytes(b"left over\n" + _line("new file").encode())
    reader.read()

    assert _msgs(ring) == ["read", "new file"]


@pytest.mark.parametrize(("width", "kept"), [(100, MAX_READ_BYTES // 100), (64, MAX_READ_BYTES // 64)])
def test_a_read_over_the_cap_takes_its_newest_bytes(tmp_path, width, kept):
    # Lines of `width` bytes, more than MAX_READ_BYTES of them. 100 doesn't divide the cap, so the cut lands inside
    # a line, which is left out; 64 does, so the cut lands on a line's start, which is kept.
    path, reader, ring = _reader(tmp_path, max_entries=50_000)
    count = MAX_READ_BYTES // width + 500
    _append(path, "".join(_line(f"{i:08d}".ljust(width - len(_line(""))), level="Info") for i in range(count)))
    assert path.stat().st_size == count * width

    reader.read()

    numbers = [int(m.split()[0]) for m in _msgs(ring)]
    assert numbers == list(range(count - kept, count))
    assert ring.get_entries()["total_captured"] == kept


def test_a_cut_resumes_at_the_next_header_and_leaves_the_last_entry_alone(tmp_path):
    path, reader, ring = _reader(tmp_path, max_read=200)
    _append(path, _line("before the cut", level="Error"))
    reader.read()

    # More than the cap arrives, and the cut lands among a traceback's lines.
    frames = "".join(f'  File "C:/invented/m{i}.py", line {i}\n' for i in range(10))
    _append(path, "Traceback (most recent call last):\n" + frames + "ValueError: the tail\n" + _line("after the cut"))
    reader.read()

    assert _msgs(ring) == ["before the cut", "after the cut"]


def test_a_cut_inside_a_line_longer_than_the_cap(tmp_path):
    path, reader, ring = _reader(tmp_path, max_read=80)
    _append(path, _line("x" * 120).rstrip("\n"))  # no line end yet
    reader.read()
    assert _msgs(ring) == []

    _append(path, " its end\n" + _line("next"))
    reader.read()

    assert _msgs(ring) == ["next"]


def test_the_token_is_redacted_in_every_line_read(tmp_path):
    path, reader, ring = _reader(tmp_path)
    _append(path, _line(f"token={TOKEN}", channel=f"ext.{TOKEN}") + f"continued {TOKEN} {TOKEN}\n")

    reader.read()

    entry = ring.get_entries()["entries"][0]
    assert TOKEN not in str(entry)
    assert entry["channel"] == f"ext.{REDACTED}"
    assert entry["msg"] == f"token={REDACTED}\ncontinued {REDACTED} {REDACTED}"


# ----- /logs -----


def test_logs_before_the_extension_starts():
    assert KitLog().query({}) == {
        "status": "error",
        "error": "get_logs has no log to read: the bridge extension hasn't started",
    }


def test_logs_without_a_log_file():
    log = KitLog()
    log.start("", _no_resolve, TOKEN)

    result = log.query({})

    assert result["status"] == "error"
    assert "--/log/file=<path>" in result["error"]


def test_logs_read_kits_file_at_each_query(tmp_path):
    path = tmp_path / "kit.log"
    path.write_text(_line("before the start"), encoding="utf-8")
    log = KitLog()
    log.start(str(path), _no_resolve, TOKEN)
    _append(path, _line("cooking", channel="omni.physx.cooking.plugin") + _line(f"a {TOKEN}", level="Warning"))

    first = log.query({"count": 10})

    assert first["status"] == "success"
    assert [(e["index"], e["level"], e["msg"]) for e in first["result"]["entries"]] == [
        (0, "info", "cooking"),
        (1, "warn", f"a {REDACTED}"),
    ]
    _append(path, _line("later", level="Error"))
    assert [e["msg"] for e in log.query({"since_index": 1})["result"]["entries"]] == ["later"]
    filtered = log.query({"min_level": "warn", "channel": "", "search": "A ", "count": 5})["result"]
    assert [e["msg"] for e in filtered["entries"]] == [f"a {REDACTED}"]
    assert filtered["total_captured"] == 3


def test_logs_when_kits_file_is_gone(tmp_path):
    path = tmp_path / "kit.log"
    path.write_text("", encoding="utf-8")
    log = KitLog()
    log.start(str(path), _no_resolve, TOKEN)
    path.unlink()

    result = log.query({})

    assert result["status"] == "error"
    assert result["error"].startswith(f"Could not read Kit's log file {path}")


def test_a_new_start_reads_from_the_new_end(tmp_path):
    path = tmp_path / "kit.log"
    path.write_text("", encoding="utf-8")
    log = KitLog()
    log.start(str(path), _no_resolve, TOKEN)
    _append(path, _line("first start"))
    assert log.query({})["result"]["count"] == 1

    log.start(str(path), _no_resolve, "another-invented-token")

    assert log.query({})["result"] == {"entries": [], "count": 0, "total_captured": 0, "buffer_size": 2000}
