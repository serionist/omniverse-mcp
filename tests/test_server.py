"""The MCP server on SDK v2, through an in-memory MCP client against the mock bridge: a failure comes back as an error
result the model reads, tools reach the bridge one at a time, the resources read, and importing does nothing."""

import asyncio
import base64
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from mcp import Client, MCPError

from omniverse_mcp.client import BridgeClient
from omniverse_mcp.kit_extension import install_command
from omniverse_mcp.server import Helpers, create_server

from .mock_bridge import MockIsaacServer

HANDSHAKE = {"status": "success", "result": {"protocol": 1, "extension_version": "1.0.0"}}
NO_LOGS = {"status": "success", "result": {"entries": [], "count": 0, "total_captured": 0, "buffer_size": 2000}}
SCRIPT_RAN = {"status": "success", "result": {"stdout": "hello\n", "stderr": "", "return_value": None}}
SCRIPT_FAILED = {
    "status": "error",
    "error": "NameError: name 'stage' is not defined",
    "traceback": "\n".join(f'  File "<script>", line {n}' for n in range(1, 8)),
}


@pytest.fixture(scope="module")
def bridge():
    mock = MockIsaacServer()
    mock.set_response("/bridge", HANDSHAKE)
    mock.start()
    yield mock
    mock.stop()


@pytest.fixture
def client(bridge):
    # Closed after each test: an open socket left to the garbage collector is a ResourceWarning, and warnings fail.
    bridge_client = BridgeClient(port=bridge.port, token="invented-test-token")
    yield bridge_client
    bridge_client.close()


def _run(server, call):
    async def go():
        async with Client(server) as client:
            return await call(client)

    return asyncio.run(go())


def test_a_tool_returns_its_text(bridge, client, tmp_path):
    bridge.set_response("/logs", NO_LOGS)
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)

    result = _run(server, lambda c: c.call_tool("get_logs", {}))

    assert not result.is_error
    assert result.content[0].text == "No log entries found (buffer has 0 total entries)"


def test_the_bridges_error_is_an_error_result_with_the_end_of_its_traceback(bridge, client, tmp_path):
    bridge.set_response("/execute", SCRIPT_FAILED)
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)

    result = _run(server, lambda c: c.call_tool("execute_script", {"code": "stage"}))

    assert result.is_error
    text = result.content[0].text
    assert "NameError: name 'stage' is not defined" in text
    assert "line 7" in text
    assert "line 3" in text
    assert "line 2" not in text  # the last five lines only


def test_a_route_an_older_extension_lacks_names_the_command_that_installs_this_server_s(bridge, client, tmp_path):
    # An extension of 0.2.2 has no /scene/open (#79): the server's update went ahead of the extension's.
    bridge.set_response("/scene/open", {"status": "error", "error": "Unknown endpoint: /scene/open"}, status=404)
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)

    result = _run(server, lambda c: c.call_tool("open_scene", {"file_path": "C:/Scenes/room.usda"}))

    assert result.is_error
    text = result.content[0].text
    assert "Unknown endpoint: /scene/open. The Kit extension is older than this MCP server" in text
    assert f"{install_command()}, then restart Kit" in text


def test_a_value_out_of_range_is_refused_before_the_bridge(bridge, client, tmp_path):
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)
    bridge.requests.clear()

    result = _run(server, lambda c: c.call_tool("get_scene_tree", {"max_depth": -1}))

    assert result.is_error
    assert "greater than or equal to 0" in result.content[0].text
    assert bridge.requests == []


def test_an_unreachable_kit_app_is_an_error_result(tmp_path):
    with socket.socket() as probe:  # a port nothing listens on
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = create_server("127.0.0.1", port, str(tmp_path), client=BridgeClient(port=port, token="invented"))

    result = _run(server, lambda c: c.call_tool("get_logs", {}))

    assert result.is_error
    assert "Kit app connection failed" in result.content[0].text


def test_a_tools_own_argument_error_is_an_error_result(bridge, client, tmp_path):
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)

    result = _run(server, lambda c: c.call_tool("manage_extensions", {"action": "enable"}))

    assert result.is_error
    assert "extension_id is required for enable/disable" in result.content[0].text


class _CountingClient(BridgeClient):
    """Counts the threads inside one exchange with the bridge at a time, each held there a moment."""

    def __init__(self, port: int):
        super().__init__(port=port, token="invented-test-token")
        self._count_lock = threading.Lock()
        self.inside = 0
        self.most_inside = 0

    def _exchange(self, path, body, method):
        with self._count_lock:
            self.inside += 1
            self.most_inside = max(self.most_inside, self.inside)
        try:
            time.sleep(0.2)
            return super()._exchange(path, body, method)
        finally:
            with self._count_lock:
                self.inside -= 1


def test_tools_called_at_once_reach_the_bridge_one_at_a_time(bridge, tmp_path):
    # SDK v2 runs synchronous tools on worker threads, several at once; they share the client's one socket.
    bridge.set_response("/execute", SCRIPT_RAN)
    counting = _CountingClient(bridge.port)
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=counting)

    async def two_at_once(c):
        return await asyncio.gather(
            c.call_tool("execute_script", {"code": "print('hello')"}),
            c.call_tool("execute_script", {"code": "print('hello')"}),
        )

    try:
        results = _run(server, two_at_once)
    finally:
        counting.close()

    assert [r.is_error for r in results] == [False, False]
    assert all("hello" in r.content[0].text for r in results)
    assert counting.most_inside == 1


def test_the_resources_read_and_fail_as_errors(bridge, client, tmp_path):
    server = create_server("127.0.0.1", bridge.port, str(tmp_path), client=client)
    bridge.set_response("/sim/state", {"status": "success", "result": {"playing": False, "time": 0.0}})

    result = _run(server, lambda c: c.read_resource("omniverse://sim/state"))
    assert '"playing": false' in result.contents[0].text

    bridge.set_response("/sim/state", {"status": "error", "error": "no stage"})

    async def read_failing(c):
        with pytest.raises(MCPError, match="no stage"):
            await c.read_resource("omniverse://sim/state")

    _run(server, read_failing)


def test_importing_the_server_does_nothing(tmp_path):
    # Before SDK v2, importing parsed sys.argv and made ./mcp_output; a flag it doesn't know proves it reads none now.
    done = subprocess.run(
        [sys.executable, "-c", "import omniverse_mcp.server", "--not-a-flag"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert not (tmp_path / "mcp_output").exists()


def test_starting_the_server_makes_no_output_folder(tmp_path, monkeypatch):
    # A client's health check starts the server and calls no tool; it used to leave an empty mcp_output behind (#43).
    # The real server is made, its tools and Helpers too; only serving stdio is left out.
    from mcp.server.mcpserver import MCPServer

    import omniverse_mcp.server as server_module

    monkeypatch.delenv("OMNIVERSE_MCP_OUTPUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(MCPServer, "run", lambda self, *args, **kwargs: None)
    server_module.main([])
    assert not (tmp_path / "mcp_output").exists()


def test_a_relative_output_folder_is_made_whole_at_start(tmp_path, monkeypatch):
    # Kit writes get_scene_tree's dump and recordings into it itself, and would read a relative folder against its own.
    import omniverse_mcp.server as server_module

    started: list[str] = []

    class _Server:
        def run(self) -> None:
            pass

    def _create_server(host: str, port: int, output_dir: str) -> _Server:
        started.append(output_dir)
        return _Server()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server_module, "create_server", _create_server)
    server_module.main(["--output-dir", "out"])
    assert started == [str(Path.cwd() / "out")]


_IMAGE = base64.b64encode(b"\x89PNG\r\n\x1a\ninvented").decode()


def test_a_file_under_the_working_folder_is_given_by_its_short_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Helpers(str(tmp_path / "mcp_output")).save_png(_IMAGE, "t") == "mcp_output/captures/t_0001.png"


def test_a_file_outside_the_working_folder_is_given_by_its_absolute_path(tmp_path, monkeypatch):
    # A relative ../ path is right only for a reader in the server's working folder (#41).
    (tmp_path / "project").mkdir()
    monkeypatch.chdir(tmp_path / "project")
    given = Helpers(str(tmp_path / "elsewhere")).save_png(_IMAGE, "t")
    assert given == str((tmp_path / "elsewhere" / "captures" / "t_0001.png").resolve())
    assert Path(given).is_file()


def test_a_working_folder_at_a_drive_s_root_gives_absolute_paths(tmp_path, monkeypatch):
    # Some clients start servers in /: every file is under it, but a short path would still need a reader there.
    monkeypatch.chdir(tmp_path.anchor)
    given = Helpers(str(tmp_path / "out")).save_png(_IMAGE, "t")
    assert given == str((tmp_path / "out" / "captures" / "t_0001.png").resolve())


def test_a_path_that_cant_be_resolved_is_given_whole(tmp_path, monkeypatch):
    # An unreachable share or a symlink loop makes resolve raise; write's own error message calls rel, so rel can't.
    def _fail(self: Path, strict: bool = False) -> Path:
        raise OSError(1231, "The network location cannot be reached")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "resolve", _fail)
    assert Helpers(str(tmp_path)).rel("out/x.png") == str(tmp_path / "out" / "x.png")


class _SlowCounter(Helpers):
    """A capture counter that takes a moment between being read and being set, so two threads that both read it
    before either sets it would get the same number."""

    @property
    def capture_counter(self) -> int:
        value = self._count
        time.sleep(0.001)
        return value

    @capture_counter.setter
    def capture_counter(self, value: int) -> None:
        self._count = value


def test_files_are_named_once_each_across_threads(tmp_path):
    helpers = _SlowCounter(str(tmp_path))
    image = base64.b64encode(b"\x89PNG\r\n\x1a\ninvented").decode()
    paths: list[str] = []
    threads = [threading.Thread(target=lambda: paths.append(helpers.save_png(image, "t"))) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(set(paths)) == 40
    assert len(list(Path(tmp_path, "captures").glob("t_*.png"))) == 40


def test_a_folder_that_cant_be_written_is_a_tool_error_naming_it(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    blocker = tmp_path / "out"
    blocker.write_text("a file where the output folder should be", encoding="utf-8")
    helpers = Helpers(str(blocker))
    with pytest.raises(ToolError, match=r"Could not write .*captures"):
        helpers.save_png(base64.b64encode(b"invented").decode(), "t")
    with pytest.raises(ToolError, match=r"Could not write .*responses"):
        helpers.text_response("x" * 2000, "long")


def test_an_image_that_wont_decode_is_a_tool_error(tmp_path):
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="Failed to decode image data"):
        Helpers(str(tmp_path)).save_png("abc")
