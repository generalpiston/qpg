from __future__ import annotations

import sqlite3

from qpg.db_sqlite import ensure_schema
from qpg.mcp.protocol import handle_request


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def test_initialize_negotiates_protocol_and_reports_tools_capability() -> None:
    conn = _db()
    try:
        response = handle_request(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
        )
        assert response is not None
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["result"]["protocolVersion"] == "2025-06-18"
        assert "tools" in response["result"]["capabilities"]
    finally:
        conn.close()


def test_initialize_echoes_unknown_protocol_version_for_compatibility() -> None:
    conn = _db()
    try:
        response = handle_request(
            conn,
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "initialize",
                "params": {"protocolVersion": "2026-01-01"},
            },
        )
        assert response is not None
        assert response["result"]["protocolVersion"] == "2026-01-01"
    finally:
        conn.close()


def test_tools_list_and_call_status() -> None:
    conn = _db()
    try:
        listed = handle_request(conn, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert listed is not None
        names = [tool["name"] for tool in listed["result"]["tools"]]
        assert "qpg_status" in names
        assert "qpg_get" in names

        called = handle_request(
            conn,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qpg_status", "arguments": {}}},
        )
        assert called is not None
        assert called["result"]["isError"] is False
        assert called["result"]["structuredContent"]["sources"] == 0
        assert called["result"]["structuredContent"]["objects"] == 0
    finally:
        conn.close()


def test_initialized_notification_has_no_response() -> None:
    conn = _db()
    try:
        response = handle_request(conn, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        assert response is None
    finally:
        conn.close()


def test_legacy_tool_payload_still_supported() -> None:
    conn = _db()
    try:
        response = handle_request(conn, {"id": 9, "tool": "qpg_status", "args": {}})
        assert response == {"id": 9, "result": {"sources": 0, "objects": 0, "by_kind": []}}
    finally:
        conn.close()
