from __future__ import annotations

import json
import sqlite3
from typing import Any

from qpg import __version__
from qpg.get import ObjectNotFoundError, get_object_payload
from qpg.index.fts import search_fts
from qpg.index.vec import vector_search
from qpg.query.expand import expand_query
from qpg.query.rerank import rerank_with_hook
from qpg.query.rrf import reciprocal_rank_fusion
from qpg.sources import list_sources


class MCPError(RuntimeError):
    pass


SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "qpg_search",
        "description": "Run lexical search over indexed PostgreSQL schema metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10},
                "source": {"type": "string"},
                "schema": {"type": "string"},
                "kind": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "qpg_deep_search",
        "description": "Run blended lexical+vector schema search with deterministic RRF fusion.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 10},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "qpg_get",
        "description": "Get a detailed metadata payload for one schema object by fqname or id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "source": {"type": "string"},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    },
    {
        "name": "qpg_status",
        "description": "Return index status and object counts by kind.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "qpg_list_sources",
        "description": "List configured PostgreSQL sources in the local index.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _negotiate_protocol_version(client_version: Any) -> str:
    if isinstance(client_version, str) and client_version:
        return client_version
    return SUPPORTED_PROTOCOL_VERSIONS[0]


def _status_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    source_count = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    object_count = conn.execute("SELECT COUNT(*) FROM db_objects").fetchone()[0]
    by_kind = conn.execute(
        """
        SELECT object_type, COUNT(*) AS count
        FROM db_objects
        GROUP BY object_type
        ORDER BY count DESC
        """
    ).fetchall()
    return {
        "sources": source_count,
        "objects": object_count,
        "by_kind": [{"kind": row[0], "count": row[1]} for row in by_kind],
    }


def _deep_search(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    expansions = expand_query(query)
    fts_ranked: list[list[dict[str, Any]]] = []
    for text in expansions:
        rows = search_fts(conn, query=text, limit=limit)
        fts_ranked.append(rows)

    ranked_lists = fts_ranked
    ranked_lists.append(vector_search(conn, query=query, limit=limit))

    fused = reciprocal_rank_fusion(ranked_lists, k=60)

    for idx, row in enumerate(fused, start=1):
        row["position_bonus"] = 1.0 / (idx + 1)
        row["score"] = row["rrf_score"] + 0.1 * row["position_bonus"]

    fused.sort(key=lambda item: item["score"], reverse=True)
    fused = rerank_with_hook(query, fused)
    return fused[:limit]


def handle_tool_call(conn: sqlite3.Connection, tool: str, args: dict[str, Any] | None = None) -> Any:
    args = args or {}

    if tool == "qpg_search":
        return search_fts(
            conn,
            query=str(args.get("query", "")),
            limit=int(args.get("limit", 10)),
            source=args.get("source"),
            schema=args.get("schema"),
            kind=args.get("kind"),
        )

    if tool == "qpg_deep_search":
        return _deep_search(conn, str(args.get("query", "")), int(args.get("limit", 10)))

    if tool == "qpg_get":
        ref = str(args.get("ref", ""))
        if not ref:
            raise MCPError("qpg_get requires 'ref'")
        try:
            return get_object_payload(conn, ref, source=args.get("source"))
        except ObjectNotFoundError as exc:
            raise MCPError(str(exc)) from exc

    if tool == "qpg_status":
        return _status_payload(conn)

    if tool == "qpg_list_sources":
        return [
            {
                "name": source.name,
                "dsn": source.dsn,
                "include_schemas": source.include_schemas,
                "skip_patterns": source.skip_patterns,
                "last_indexed_at": source.last_indexed_at,
                "last_error": source.last_error,
            }
            for source in list_sources(conn)
        ]

    raise MCPError(f"unknown tool: {tool}")


def _handle_legacy_request(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    tool = payload.get("tool")
    args = payload.get("args")

    if not isinstance(tool, str):
        return {"id": request_id, "error": "payload must include string field 'tool'"}

    try:
        result = handle_tool_call(conn, tool, args if isinstance(args, dict) else None)
    except Exception as exc:
        return {"id": request_id, "error": str(exc)}

    return {"id": request_id, "result": result}


def _handle_mcp_request(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any] | None:
    request_id = payload.get("id")
    method = payload.get("method")
    if not isinstance(method, str):
        return _jsonrpc_error(request_id, -32600, "Invalid Request: missing method")

    params = payload.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params: expected object")

    # Notification: no response expected.
    if method == "notifications/initialized":
        return None

    if method == "initialize":
        protocol_version = _negotiate_protocol_version(params.get("protocolVersion"))
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "qpg", "version": __version__},
                "instructions": (
                    "qpg exposes PostgreSQL schema-index retrieval tools only. "
                    "It never executes arbitrary SQL or reads table row values."
                ),
            },
        )

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOL_SCHEMAS})

    if method == "tools/call":
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return _jsonrpc_error(request_id, -32602, "Invalid params: tools/call requires string 'name'")
        arguments = params.get("arguments")
        if arguments is not None and not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "Invalid params: 'arguments' must be an object")
        try:
            result = handle_tool_call(conn, tool_name, arguments)
            return _jsonrpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                    "structuredContent": result,
                    "isError": False,
                },
            )
        except Exception as exc:
            return _jsonrpc_result(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def handle_request(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any] | None:
    if "method" in payload:
        return _handle_mcp_request(conn, payload)
    return _handle_legacy_request(conn, payload)
