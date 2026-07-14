from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from qpg.sources import SourceRecord, get_source

MAX_LIMIT = 100
MAX_COLUMNS = 16
MAX_RESPONSE_BYTES = 256_000
MAX_ESTIMATED_COST = 1_000.0
MAX_VARCHAR_LENGTH = 4_096
MAX_ALIAS_LENGTH = 64
_VARCHAR_RE = re.compile(r"^(?:character varying|varchar)\((\d+)\)$", re.IGNORECASE)
_CHARACTER_RE = re.compile(r"^character\(\d+\)$", re.IGNORECASE)
_SAFE_SCALAR_TYPES = {
    "smallint",
    "integer",
    "bigint",
    "uuid",
    "date",
    "timestamp without time zone",
    "timestamp with time zone",
}
_LEFT_TYPES = {"text", "character", "character varying"}


class RowQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhysicalProjection:
    column: str


@dataclass(frozen=True)
class LeftProjection:
    column: str
    length: int
    alias: str


Projection = PhysicalProjection | LeftProjection


@dataclass(frozen=True)
class RowQuery:
    source: str
    table: str
    projections: tuple[Projection, ...]
    mode: str
    key: Any | None
    limit: int


@dataclass(frozen=True)
class TableAccess:
    source: SourceRecord
    primary_key: str
    primary_index: str
    columns: dict[str, str]


@dataclass(frozen=True)
class QueryPlan:
    total_cost: float
    node_types: tuple[str, ...]


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _safe_type(data_type: str) -> bool:
    normalized = data_type.strip().lower()
    if normalized in _SAFE_SCALAR_TYPES:
        return True
    match = _VARCHAR_RE.fullmatch(normalized)
    return match is not None and int(match.group(1)) <= MAX_VARCHAR_LENGTH


def _left_type(data_type: str) -> bool:
    normalized = data_type.strip().lower()
    if normalized in _LEFT_TYPES:
        return True
    match = _VARCHAR_RE.fullmatch(normalized)
    return match is not None or _CHARACTER_RE.fullmatch(normalized) is not None


def parse_request(value: dict[str, Any]) -> RowQuery:
    unknown = set(value) - {"source", "table", "projections", "mode", "key", "limit"}
    if unknown:
        raise RowQueryError(f"unsupported row-query fields: {', '.join(sorted(unknown))}")
    source = str(value.get("source", "")).strip()
    table = str(value.get("table", "")).strip()
    mode = str(value.get("mode", "")).strip().lower()
    if not source or not table or table.count(".") != 1:
        raise RowQueryError("source and schema-qualified table are required")
    if mode not in {"lookup", "page"}:
        raise RowQueryError("mode must be 'lookup' or 'page'")
    raw_projections = value.get("projections")
    if not isinstance(raw_projections, list) or not raw_projections or len(raw_projections) > MAX_COLUMNS:
        raise RowQueryError(f"projections must contain between 1 and {MAX_COLUMNS} entries")
    projections: list[Projection] = []
    names: set[str] = set()
    for raw in raw_projections:
        if not isinstance(raw, dict):
            raise RowQueryError("each projection must be an object")
        if set(raw) == {"column"} and isinstance(raw.get("column"), str):
            projection: Projection = PhysicalProjection(raw["column"].strip())
            if not projection.column or projection.column in {"*", "__qpg_cursor"}:
                raise RowQueryError("physical projections require an explicit column")
        elif set(raw) == {"function", "column", "length", "alias"}:
            if raw.get("function") != "left" or not isinstance(raw.get("column"), str) or not isinstance(raw.get("alias"), str):
                raise RowQueryError("the only supported expression is LEFT with a column and alias")
            length = raw["length"]
            alias = raw["alias"].strip()
            if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= MAX_VARCHAR_LENGTH:
                raise RowQueryError(f"LEFT length must be between 1 and {MAX_VARCHAR_LENGTH}")
            if not alias or len(alias) > MAX_ALIAS_LENGTH or alias == "__qpg_cursor":
                raise RowQueryError("expression aliases must be non-empty, short, and not internal")
            projection = LeftProjection(raw["column"].strip(), length, alias)
        else:
            raise RowQueryError("projection must be a physical column or a LEFT expression")
        name = projection.column if isinstance(projection, PhysicalProjection) else projection.alias
        if not name or name in names:
            raise RowQueryError("projection output names must be explicit and unique")
        names.add(name)
        projections.append(projection)
    key = value.get("key")
    if mode == "lookup" and key is None:
        raise RowQueryError("lookup mode requires key")
    if mode == "lookup":
        if "limit" in value:
            raise RowQueryError("lookup mode does not accept limit")
        limit = 1
    else:
        try:
            limit_value = value["limit"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RowQueryError("page mode requires an integer limit") from exc
        if isinstance(limit_value, bool) or not isinstance(limit_value, int):
            raise RowQueryError("page mode requires an integer limit")
        limit = limit_value
        if not 1 <= limit <= MAX_LIMIT:
            raise RowQueryError(f"limit must be between 1 and {MAX_LIMIT}")
    return RowQuery(source, table, tuple(projections), mode, key, limit)


def _table_access(sqlite_conn: Any, request: RowQuery) -> TableAccess:
    source = get_source(sqlite_conn, request.source)
    schema, table = request.table.split(".", 1)
    object_row = sqlite_conn.execute(
        "SELECT id FROM db_objects WHERE source_id = ? AND schema_name = ? "
        "AND object_name = ? AND object_type = 'table'",
        (source.id, schema, table),
    ).fetchone()
    if object_row is None:
        raise RowQueryError(f"base table '{request.table}' is not indexed")
    object_id = str(object_row["id"])
    column_rows = sqlite_conn.execute(
        "SELECT column_name, data_type, is_nullable FROM columns WHERE object_id = ? ORDER BY ordinal_position",
        (object_id,),
    ).fetchall()
    columns = {str(row["column_name"]): str(row["data_type"]) for row in column_rows}
    nullable = {str(row["column_name"]): bool(row["is_nullable"]) for row in column_rows}
    primary_rows = sqlite_conn.execute(
        "SELECT index_name, columns_json FROM indexes WHERE object_id = ? AND is_primary = 1",
        (object_id,),
    ).fetchall()
    if len(primary_rows) != 1:
        raise RowQueryError(f"table '{request.table}' requires one indexed primary key")
    primary_columns = json.loads(str(primary_rows[0]["columns_json"]))
    if not isinstance(primary_columns, list) or len(primary_columns) != 1 or not isinstance(primary_columns[0], str):
        raise RowQueryError("only single-column primary keys are supported")
    primary_key = primary_columns[0]
    if primary_key not in columns or nullable.get(primary_key, True) or not _safe_type(columns[primary_key]):
        raise RowQueryError("primary key type is not eligible for bounded row queries")
    for projection in request.projections:
        if projection.column not in columns:
            raise RowQueryError("query references an unknown column")
        if isinstance(projection, PhysicalProjection) and not _safe_type(columns[projection.column]):
            raise RowQueryError("query selects an unsupported or unbounded column type")
        if isinstance(projection, LeftProjection) and not _left_type(columns[projection.column]):
            raise RowQueryError("LEFT expressions require a text column")
    return TableAccess(source, primary_key, str(primary_rows[0]["index_name"]), columns)


def _build_sql(request: RowQuery, access: TableAccess) -> tuple[str, list[Any]]:
    qualified = ".".join(_identifier(part) for part in request.table.split("."))
    selected_parts: list[str] = []
    params: list[Any] = []
    for projection in request.projections:
        if isinstance(projection, PhysicalProjection):
            selected_parts.append(_identifier(projection.column))
        else:
            selected_parts.append(f"LEFT({_identifier(projection.column)}, %s) AS {_identifier(projection.alias)}")
            params.append(projection.length)
    selected = ", ".join(selected_parts)
    sql = f"SELECT {selected}, {_identifier(access.primary_key)} AS \"__qpg_cursor\" FROM {qualified}"
    if request.mode == "lookup":
        sql += f" WHERE {_identifier(access.primary_key)} = %s"
        params.append(request.key)
    elif request.key is not None:
        sql += f" WHERE {_identifier(access.primary_key)} > %s"
        params.append(request.key)
    sql += f" ORDER BY {_identifier(access.primary_key)} ASC LIMIT %s"
    params.append(request.limit)
    return sql, params


def _plan_details(value: Any) -> tuple[dict[str, Any], QueryPlan]:
    try:
        root = value[0]["Plan"] if isinstance(value, list) else value["Plan"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RowQueryError("PostgreSQL returned an invalid query plan") from exc
    node_types: list[str] = []

    def visit(node: dict[str, Any]) -> None:
        node_types.append(str(node.get("Node Type", "Unknown")))
        for child in node.get("Plans", []):
            if not isinstance(child, dict):
                raise RowQueryError("PostgreSQL returned an invalid query plan")
            visit(child)

    visit(root)
    return root, QueryPlan(float(root.get("Total Cost", 0)), tuple(node_types))


def _preflight(pg_conn: Any, request: RowQuery, access: TableAccess, sql: str, params: list[Any]) -> QueryPlan:
    with pg_conn.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + sql, params)
        row = cur.fetchone()
    if not isinstance(row, dict) or "QUERY PLAN" not in row:
        raise RowQueryError("PostgreSQL returned an invalid query plan")
    root, plan = _plan_details(row["QUERY PLAN"])
    if plan.total_cost > MAX_ESTIMATED_COST:
        raise RowQueryError(f"query plan cost exceeds the safety limit of {MAX_ESTIMATED_COST:g}")
    if any(node not in {"Limit", "Index Scan", "Index Only Scan"} for node in plan.node_types):
        raise RowQueryError("query plan contains an unsafe execution node")
    if not any(node in {"Index Scan", "Index Only Scan"} for node in plan.node_types):
        raise RowQueryError("query plan must use the primary-key index")

    def validate(node: dict[str, Any]) -> None:
        if node.get("Node Type") in {"Index Scan", "Index Only Scan"}:
            if node.get("Index Name") != access.primary_index:
                raise RowQueryError("query plan must use the primary-key index")
            if (request.mode == "lookup" or request.key is not None) and not node.get("Index Cond"):
                raise RowQueryError("query plan must use the primary-key index condition")
            if node.get("Filter") or node.get("Recheck Cond"):
                raise RowQueryError("query plan contains an unsafe filter")
        for child in node.get("Plans", []):
            validate(child)

    validate(root)
    return plan


def _normalize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    raise RowQueryError(f"result contains unsupported value type: {type(value).__name__}")


def _normalize_rows(raw_rows: list[dict[str, Any]], request: RowQuery) -> tuple[list[dict[str, Any]], Any | None]:
    rows: list[dict[str, Any]] = []
    byte_count = 0
    next_cursor: Any | None = None
    for raw_row in raw_rows:
        row = {
            (projection.column if isinstance(projection, PhysicalProjection) else projection.alias):
            _normalize_value(raw_row[projection.column if isinstance(projection, PhysicalProjection) else projection.alias])
            for projection in request.projections
        }
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        byte_count += len(encoded)
        if byte_count > MAX_RESPONSE_BYTES:
            raise RowQueryError(f"row result exceeds the {MAX_RESPONSE_BYTES} byte response limit")
        rows.append(row)
        next_cursor = _normalize_value(raw_row["__qpg_cursor"])
    return rows, next_cursor


def execute_row_query(sqlite_conn: Any, pg_conn: Any, value: dict[str, Any]) -> dict[str, Any]:
    request = parse_request(value)
    access = _table_access(sqlite_conn, request)
    sql, params = _build_sql(request, access)
    with pg_conn.transaction():
        with pg_conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '2s'")
            cur.execute("SET LOCAL lock_timeout = '250ms'")
            cur.execute("SET LOCAL work_mem = '1MB'")
            cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        plan = _preflight(pg_conn, request, access, sql, params)
        with pg_conn.cursor() as cur:
            cur.execute(sql, params)
            raw_rows = [dict(row) for row in cur.fetchall()]
    rows, next_cursor = _normalize_rows(raw_rows, request)
    return {
        "source": access.source.name,
        "table": request.table,
        "projections": [
            {"column": p.column} if isinstance(p, PhysicalProjection)
            else {"function": "left", "column": p.column, "length": p.length, "alias": p.alias}
            for p in request.projections
        ],
        "mode": request.mode,
        "limit": request.limit,
        "rows": rows,
        "next_cursor": next_cursor if request.mode == "page" and len(rows) == request.limit else None,
        "preflight": {"total_cost": plan.total_cost, "node_types": list(plan.node_types)},
    }
