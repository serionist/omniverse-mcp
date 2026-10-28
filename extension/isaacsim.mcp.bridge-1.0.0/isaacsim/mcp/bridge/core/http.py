"""The bridge's HTTP/1.1 server: request parsing, the token and browser checks, and routing.

Handlers run on the server's event loop (Kit's, inside the app), never in a thread: USD is not thread-safe.
"""

import asyncio
import hmac
import json
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .protocol import PROTOCOL, extension_version

MAX_BODY_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_HANDLERS = 20
MAX_PENDING = 32  # connections that have not yet sent a request with the token
MAX_HEADERS = 100
IDLE_TIMEOUT = 300.0  # seconds an authenticated, kept-alive connection may wait for its next request
HEADER_TIMEOUT = 10.0  # seconds a new connection has to send a request with the token, and any request its headers
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

Handler = Callable[[dict], Awaitable[dict]]

STATUS_TEXTS = {
    200: "OK",
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    413: "Payload Too Large",
    500: "Internal Server Error",
}


class Log(Protocol):
    def info(self, msg: str) -> Any: ...
    def warning(self, msg: str) -> Any: ...
    def error(self, msg: str) -> Any: ...


def host_name(host_header: str) -> str:
    """The name part of a Host header: '127.0.0.1:8211' -> '127.0.0.1', '[::1]:8211' -> '::1'."""
    value = host_header.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end > 0 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def _error(message: str) -> dict:
    return {"status": "error", "error": message}


class BridgeServer:
    """Serves `routes` to clients that hold `token`.

    A request is refused before its body is read when it carries an Origin header (browsers send one on every POST,
    our client never does), when the server is bound to loopback and the Host header names something else (DNS
    rebinding), or when its bearer token is missing or wrong. A refusal closes the connection.

    A new connection has HEADER_TIMEOUT to send a request with the token. At most MAX_PENDING connections wait
    without one; a newer one pushes the oldest out, so connections without the token cannot crowd the client out.

    `GET /bridge` is answered here, not by a handler, so the client's handshake works whatever state Kit is in.
    """

    def __init__(
        self,
        routes: dict[str, Handler],
        token: str,
        host: str = "127.0.0.1",
        port: int = 8211,
        log: Log | None = None,
    ):
        if not token:
            raise ValueError("The bridge token must not be empty")
        self.routes = routes
        self.token = token
        self.host = host
        self.port = port
        self.idle_timeout = IDLE_TIMEOUT
        self.header_timeout = HEADER_TIMEOUT
        self._log: Log = log or logging.getLogger(__name__)
        self._server: asyncio.Server | None = None
        self._closed = False
        self._handlers = asyncio.Semaphore(MAX_HANDLERS)
        self._open: set[asyncio.StreamWriter] = set()
        # Insertion-ordered, so the oldest is pushed out first.
        self._pending: dict[asyncio.StreamWriter, None] = {}

    @property
    def checks_host(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    def info(self) -> dict:
        """What GET /bridge answers: the client's handshake."""
        return {"protocol": PROTOCOL, "extension_version": extension_version()}

    async def start(self) -> bool:
        """Listen; False when close() came while the port was being bound, and nothing is left listening."""
        server = await asyncio.start_server(self._handle_connection, self.host, self.port)
        if self._closed:
            server.close()
            return False
        self._server = server
        address = server.sockets[0].getsockname()
        self.port = address[1]
        self._log.info(f"[MCP Bridge] Listening on {address[0]}:{address[1]}")
        return True

    def close(self) -> None:
        """Stop listening and drop every open connection, so nothing is served once the extension is off."""
        self._closed = True
        if self._server is not None:
            self._server.close()
            self._server = None
        for writer in list(self._open):
            writer.close()

    def refusal(self, headers: dict[str, str]) -> tuple[int, str] | None:
        """The status and message a request with these (lower-cased) headers is refused with, or None."""
        if "origin" in headers:
            return 403, "Refused: the request came from a web page (it carried an Origin header)."
        if self.checks_host and host_name(headers.get("host", "")) not in LOOPBACK_HOSTS:
            return 403, f"Refused: the Host header {headers.get('host', '')!r} is not a loopback name."
        scheme, _, presented = headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            presented.strip().encode("utf-8"), self.token.encode("utf-8")
        ):
            return 401, "Missing or wrong bridge token."
        return None

    def _admit(self, writer: asyncio.StreamWriter) -> None:
        if len(self._pending) >= MAX_PENDING:
            oldest = next(iter(self._pending))
            del self._pending[oldest]
            oldest.close()
        self._pending[writer] = None
        self._open.add(writer)

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        self._log.info(f"[MCP Bridge] Connection from {peer}")
        self._admit(writer)
        loop = asyncio.get_running_loop()
        # Blank lines do not move this: a connection without the token gets HEADER_TIMEOUT in all.
        deadline = loop.time() + self.header_timeout
        try:
            while True:
                timeout = max(deadline - loop.time(), 0.0) if writer in self._pending else self.idle_timeout
                if not await self._serve_one(reader, writer, timeout):
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError, asyncio.TimeoutError):
            pass
        except Exception as e:
            self._log.error(f"[MCP Bridge] Connection error: {e}")
        finally:
            self._pending.pop(writer, None)
            self._open.discard(writer)
            writer.close()
            self._log.info(f"[MCP Bridge] Connection closed from {peer}")

    async def _serve_one(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, timeout: float) -> bool:
        """Answer one request; False when the connection should close."""
        request_line = await asyncio.wait_for(reader.readline(), timeout)
        if not request_line:
            return False
        parts = request_line.decode("latin-1").strip().split(" ")
        if not parts[0]:
            return True
        if len(parts) < 2:
            await self._send(writer, 400, _error("Bad request"), close=True)
            return False
        method, path = parts[0], parts[1]
        headers = await asyncio.wait_for(self._read_headers(reader), self.header_timeout)

        refused = self.refusal(headers)
        if refused is not None:
            status, message = refused
            self._log.warning(f"[MCP Bridge] {status} on {method} {path}: {message}")
            await self._send(writer, status, _error(message), close=True)
            return False
        self._pending.pop(writer, None)

        try:
            content_length = int(headers.get("content-length", "0"))
        except ValueError:
            await self._send(writer, 400, _error("Bad Content-Length"), close=True)
            return False
        if content_length > MAX_BODY_SIZE:
            await self._send(
                writer,
                413,
                _error(f"Request body too large ({content_length} bytes, max {MAX_BODY_SIZE})"),
                close=True,
            )
            return False

        body: Any = {}
        if content_length > 0:
            raw_body = await reader.readexactly(content_length)
            try:
                body = json.loads(raw_body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                await self._send(writer, 400, _error("Invalid JSON body"))
                return True
        if not isinstance(body, dict):
            await self._send(writer, 400, _error("The JSON body must be an object"))
            return True

        if method == "GET" and path == "/bridge":
            await self._send(writer, 200, {"status": "success", "result": self.info()})
            return True

        handler = self.routes.get(path)
        if handler is None:
            await self._send(writer, 404, _error(f"Unknown endpoint: {path}"))
            return True
        if method != "POST" and not (method == "GET" and path == "/health"):
            await self._send(writer, 405, _error("Method not allowed, use POST"))
            return True

        async with self._handlers:
            try:
                # Run the handler as its own task so this connection's task suspends properly and doesn't block
                # Kit's async work (viewport updates, property widgets); awaiting it inline broke Kit's UI.
                result = await asyncio.ensure_future(handler(body))
                await self._send(writer, 200, result)
            except Exception as e:
                tb = traceback.format_exc()
                self._log.error(f"[MCP Bridge] Handler error on {path}: {tb}")
                await self._send(writer, 500, {"status": "error", "error": str(e), "traceback": tb})
        return True

    async def _read_headers(self, reader: asyncio.StreamReader) -> dict[str, str]:
        headers: dict[str, str] = {}
        for _ in range(MAX_HEADERS):
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                return headers
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()
        raise ValueError(f"More than {MAX_HEADERS} headers")

    async def _send(self, writer: asyncio.StreamWriter, status_code: int, body: dict, close: bool = False) -> None:
        body_bytes = json.dumps(body).encode("utf-8")
        header = (
            f"HTTP/1.1 {status_code} {STATUS_TEXTS.get(status_code, 'Unknown')}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: {'close' if close else 'keep-alive'}\r\n"
            "\r\n"
        )
        writer.write(header.encode("utf-8") + body_bytes)
        await writer.drain()
