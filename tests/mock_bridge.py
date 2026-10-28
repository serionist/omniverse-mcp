"""A stand-in for the ovmcp.bridge extension: an HTTP/1.1 server on its own event loop thread that answers each path
with a set response and records each request."""

import asyncio
import json
import threading


class MockIsaacServer:
    """Minimal async HTTP server that mimics the Isaac Sim extension."""

    def __init__(self, host="127.0.0.1", port=0):
        self.host = host
        self.port = port
        self.server = None
        self.requests: list[tuple[str, str, dict]] = []
        self._responses: dict[str, dict] = {}
        self._statuses: dict[str, int] = {}

    def set_response(self, path: str, response: dict, status: int = 200):
        self._responses[path] = response
        self._statuses[path] = status

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                request_line = await reader.readline()
                if not request_line:
                    break
                request_line = request_line.decode().strip()
                if not request_line:
                    continue
                parts = request_line.split(" ")
                method, path = parts[0], parts[1]
                content_length = 0
                while True:
                    header = await reader.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                    h = header.decode().strip()
                    if h.lower().startswith("content-length:"):
                        content_length = int(h.split(":", 1)[1].strip())
                body = {}
                if content_length > 0:
                    raw = await reader.readexactly(content_length)
                    body = json.loads(raw.decode())
                self.requests.append((method, path, body))
                response = self._responses.get(path, {"status": "success", "result": {}})
                body_bytes = json.dumps(response).encode()
                header_str = (
                    f"HTTP/1.1 {self._statuses.get(path, 200)} OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(body_bytes)}\r\n"
                    f"Connection: keep-alive\r\n\r\n"
                )
                writer.write(header_str.encode() + body_bytes)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()

    async def _start(self):
        self.server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self.server.sockets[0].getsockname()[1]

    def start(self):
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._start())
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            # Whatever the loop still holds would be reported unclosed, and warnings are errors (pyproject.toml).
            self._loop.run_until_complete(self._shutdown())
            self._loop.close()

    async def _shutdown(self):
        server = self.server
        assert server is not None  # _start ran before the loop did
        server.close()
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()

    def stop(self):
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
