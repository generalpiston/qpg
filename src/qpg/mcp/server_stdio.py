from __future__ import annotations

import json
import sqlite3
import sys

from qpg.mcp.protocol import handle_request


def serve_stdio(conn: sqlite3.Connection) -> int:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
                )
                + "\n"
            )
            sys.stdout.flush()
            continue

        if not isinstance(payload, dict):
            sys.stdout.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}
                )
                + "\n"
            )
            sys.stdout.flush()
            continue

        response = handle_request(conn, payload)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()

    return 0
