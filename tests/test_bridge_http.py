"""The bridge's HTTP server and the client against it, without Kit: the token, browser and Host checks, routing."""

import asyncio
import json
import socket
import threading

import pytest
from isaacsim.mcp.bridge.core.http import MAX_BODY_SIZE, BridgeServer, host_name
from isaacsim.mcp.bridge.core.token import write_token

from isaac_sim_mcp.client import PROTOCOL, BridgeError, IsaacSimClient

TOKEN = "t0k3n"


def _routes(health: dict):
    async def handle_health(_body):
        return {"status": "success", "result": health}

    async def handle_echo(body):
        return {"status": "success", "result": body}

    async def handle_boom(_body):
        raise RuntimeError("boom")

    return {"/health": handle_health, "/echo": handle_echo, "/boom": handle_boom}


class RunningBridge:
    """A BridgeServer on its own event loop in a thread, the way Kit runs it on Kit's loop."""

    def __init__(self, health: dict):
        self.server = BridgeServer(_routes(health), token=TOKEN, port=0)
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        asyncio.run_coroutine_threadsafe(self.server.start(), self.loop).result(timeout=5)

    @property
    def port(self) -> int:
        return self.server.port

    def stop(self):
        async def shutdown():
            self.server.close()
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("OMNIVERSE_MCP_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("OMNIVERSE_MCP_TOKEN", raising=False)
    return tmp_path


@pytest.fixture
def bridge(state):
    running = RunningBridge({"protocol": PROTOCOL, "extension_version": "test"})
    yield running
    running.stop()


def _request(method="POST", path="/echo", body=b"{}", token=TOKEN, host="127.0.0.1:8211", extra=()):
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", f"Content-Length: {len(body)}"]
    if token is not None:
        lines.append(f"Authorization: Bearer {token}")
    lines.extend(extra)
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


def _read(sock: socket.socket) -> tuple[int, dict[str, str], dict]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        assert chunk, "connection closed before a response"
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode().split("\r\n")
    headers = {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines[1:])}
    length = int(headers["content-length"])
    while len(rest) < length:
        rest += sock.recv(4096)
    return int(lines[0].split(" ")[1]), headers, json.loads(rest[:length])


def _send(port: int, *requests: bytes) -> list[tuple[int, dict[str, str], dict]]:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        responses = []
        for request in requests:
            sock.sendall(request)
            responses.append(_read(sock))
        return responses


def _closed(port: int, request: bytes) -> bool:
    """Send one request, read its response, and say whether the server closed the connection after it."""
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(request)
        _read(sock)
        return sock.recv(1) == b""


# ----- Refusals -----


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"host": "127.0.0.1:8211", "authorization": f"Bearer {TOKEN}"}, None),
        ({"host": "localhost:8211", "authorization": f"bearer {TOKEN}"}, None),
        ({"host": "[::1]:8211", "authorization": f"Bearer {TOKEN}"}, None),
        ({"host": "127.0.0.1:8211"}, 401),
        ({"host": "127.0.0.1:8211", "authorization": "Bearer wrong"}, 401),
        ({"host": "127.0.0.1:8211", "authorization": TOKEN}, 401),
        ({"host": "127.0.0.1:8211", "authorization": f"Basic {TOKEN}"}, 401),
        ({"host": "127.0.0.1:8211", "authorization": f"Bearer {TOKEN}", "origin": "https://evil.example"}, 403),
        ({"host": "127.0.0.1:8211", "authorization": f"Bearer {TOKEN}", "origin": "null"}, 403),
        ({"host": "evil.example:8211", "authorization": f"Bearer {TOKEN}"}, 403),
        ({"authorization": f"Bearer {TOKEN}"}, 403),
    ],
)
def test_refusal(headers, status):
    refused = BridgeServer({}, token=TOKEN).refusal(headers)
    assert (refused[0] if refused else None) == status


def test_any_host_is_accepted_when_bound_off_loopback():
    server = BridgeServer({}, token=TOKEN, host="0.0.0.0")
    assert not server.checks_host
    assert server.refusal({"host": "kit-box.lan:8211", "authorization": f"Bearer {TOKEN}"}) is None
    assert server.refusal({"host": "kit-box.lan:8211"})[0] == 401


@pytest.mark.parametrize(
    ("value", "name"),
    [("127.0.0.1:8211", "127.0.0.1"), ("localhost", "localhost"), ("[::1]:8211", "::1"), ("::1", "::1")],
)
def test_host_name(value, name):
    assert host_name(value) == name


def test_request_without_the_token_is_refused_and_the_connection_closed(bridge):
    (status, headers, body), = _send(bridge.port, _request(token=None))
    assert status == 401
    assert headers["connection"] == "close"
    assert "token" in body["error"]
    assert _closed(bridge.port, _request(token=None))


def test_browser_request_is_refused_even_with_the_token(bridge):
    (status, _, body), = _send(bridge.port, _request(extra=["Origin: https://evil.example"]))
    assert status == 403
    assert "web page" in body["error"]


def test_rebound_host_is_refused(bridge):
    (status, _, _), = _send(bridge.port, _request(host="evil.example:8211"))
    assert status == 403


def test_refused_body_is_never_read_as_the_next_request(bridge):
    smuggled = _request(path="/echo", body=b'{"x": 1}')
    assert _closed(bridge.port, _request(token=None, body=smuggled))


# ----- Requests that pass the checks -----


def test_post_with_the_token_is_routed(bridge):
    (status, _, body), = _send(bridge.port, _request(body=b'{"x": 1}'))
    assert status == 200
    assert body == {"status": "success", "result": {"x": 1}}


def test_connection_stays_open_across_requests_and_errors(bridge):
    responses = _send(
        bridge.port,
        _request(path="/nope"),
        _request(body=b"not json"),
        _request(body=b"[1, 2]"),
        _request(method="GET", path="/echo"),
        _request(path="/boom"),
        _request(body=b'{"ok": true}'),
    )
    assert [status for status, _, _ in responses] == [404, 400, 400, 405, 500, 200]
    assert "traceback" in responses[4][2]


def test_health_answers_get(bridge):
    (status, _, body), = _send(bridge.port, _request(method="GET", path="/health", body=b""))
    assert status == 200
    assert body["result"]["protocol"] == PROTOCOL


def test_oversized_body_is_refused_unread(bridge):
    request = _request(body=b"").replace(b"Content-Length: 0", f"Content-Length: {MAX_BODY_SIZE + 1}".encode())
    (status, headers, _), = _send(bridge.port, request)
    assert status == 413
    assert headers["connection"] == "close"


# ----- The client against the bridge -----


def test_client_reads_the_token_file(bridge):
    write_token(bridge.port, TOKEN)
    client = IsaacSimClient(port=bridge.port, timeout=5)
    try:
        assert client.request("/echo", {"x": 1})["result"] == {"x": 1}
    finally:
        client.close()


def test_client_finds_the_new_token_after_kit_restarts(bridge):
    write_token(bridge.port, TOKEN)
    client = IsaacSimClient(port=bridge.port, timeout=5)
    try:
        client.health()
        bridge.server.token = "after-restart"
        write_token(bridge.port, "after-restart")
        assert client.request("/echo", {"x": 2})["result"] == {"x": 2}
    finally:
        client.close()


def test_client_without_a_token_says_where_it_looked(bridge, state):
    client = IsaacSimClient(port=bridge.port, timeout=5)
    try:
        with pytest.raises(BridgeError, match="No token found") as raised:
            client.health()
        assert str(state) in str(raised.value)
    finally:
        client.close()


def test_client_with_a_stale_token_is_refused(bridge):
    write_token(bridge.port, "stale")
    client = IsaacSimClient(port=bridge.port, timeout=5)
    try:
        with pytest.raises(BridgeError, match="was refused"):
            client.health()
    finally:
        client.close()


@pytest.mark.parametrize(
    ("health", "message"),
    [({}, "older than this MCP server"), ({"protocol": PROTOCOL + 1, "extension_version": "9.0.0"}, "9.0.0")],
)
def test_client_refuses_an_extension_that_speaks_another_protocol(state, health, message):
    other = RunningBridge(health)
    try:
        write_token(other.port, TOKEN)
        client = IsaacSimClient(port=other.port, timeout=5)
        try:
            with pytest.raises(BridgeError, match=message):
                client.request("/echo", {})
        finally:
            client.close()
    finally:
        other.stop()
