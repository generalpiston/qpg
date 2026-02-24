from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from qpg.mcp.protocol import handle_request


class MCPHTTPHandler(BaseHTTPRequestHandler):
    server_version = "qpg-mcp/0.1"

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    @property
    def _conn(self) -> sqlite3.Connection:
        server = cast(Any, self.server)
        return cast(sqlite3.Connection, server.sqlite_conn)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})
            return
        self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/mcp":
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        payload = self._read_json()
        if payload is None:
            self._write_json(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON payload"})
            return

        response = handle_request(self._conn, payload)
        self._write_json(HTTPStatus.OK, response)


def serve_http(conn: sqlite3.Connection, *, host: str = "127.0.0.1", port: int = 8765) -> int:
    server = ThreadingHTTPServer((host, port), MCPHTTPHandler)
    server.sqlite_conn = conn  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
