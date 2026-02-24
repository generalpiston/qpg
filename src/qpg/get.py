from __future__ import annotations

import json
import sqlite3
from typing import Any, cast


class ObjectNotFoundError(RuntimeError):
    pass


def _resolve_object_row(
    conn: sqlite3.Connection,
    ref: str,
    *,
    source: str | None = None,
) -> sqlite3.Row:
    params: list[Any] = []
    where_parts: list[str] = []

    if ref.startswith("#"):
        where_parts.append("o.id LIKE ?")
        params.append(f"{ref[1:]}%")
    else:
        where_parts.append("o.fqname = ?")
        params.append(ref)

    if source:
        where_parts.append("s.name = ?")
        params.append(source)

    row = conn.execute(
        f"""
        SELECT o.id,
               o.fqname,
               o.schema_name,
               o.object_name,
               o.object_type,
               o.definition,
               o.comment,
               o.signature,
               o.owner,
               s.name AS source_name
        FROM db_objects o
        JOIN sources s ON s.id = o.source_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY o.fqname ASC
        LIMIT 1
        """,
        params,
    ).fetchone()

    if row is None:
        raise ObjectNotFoundError(f"object '{ref}' not found")
    return cast(sqlite3.Row, row)


def _decode_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def get_object_payload(
    conn: sqlite3.Connection,
    ref: str,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    row = _resolve_object_row(conn, ref, source=source)
    object_id = row["id"]

    columns = conn.execute(
        """
        SELECT column_name, data_type, is_nullable, ordinal_position, default_expr, comment
        FROM columns
        WHERE object_id = ?
        ORDER BY ordinal_position ASC
        """,
        (object_id,),
    ).fetchall()

    constraints = conn.execute(
        """
        SELECT constraint_name, constraint_type, definition, columns_json
        FROM constraints
        WHERE object_id = ?
        ORDER BY constraint_name ASC
        """,
        (object_id,),
    ).fetchall()

    indexes = conn.execute(
        """
        SELECT index_name, definition, is_unique, is_primary, columns_json
        FROM indexes
        WHERE object_id = ?
        ORDER BY index_name ASC
        """,
        (object_id,),
    ).fetchall()

    dependencies = conn.execute(
        """
        SELECT d.dependency_type,
               d.depends_on_object_id,
               o.fqname AS depends_on_fqname
        FROM dependencies d
        LEFT JOIN db_objects o ON o.id = d.depends_on_object_id
        WHERE d.object_id = ?
        ORDER BY d.id ASC
        """,
        (object_id,),
    ).fetchall()

    context = conn.execute(
        """
        SELECT context_text
        FROM object_context_effective
        WHERE object_id = ?
        """,
        (object_id,),
    ).fetchone()

    payload = {
        "object_id": object_id,
        "source": row["source_name"],
        "fqname": row["fqname"],
        "schema": row["schema_name"],
        "name": row["object_name"],
        "kind": row["object_type"],
        "definition": row["definition"] or "",
        "comment": row["comment"] or "",
        "signature": row["signature"],
        "owner": row["owner"],
        "columns": [
            {
                "name": col["column_name"],
                "type": col["data_type"],
                "nullable": bool(col["is_nullable"]),
                "ordinal": col["ordinal_position"],
                "default": col["default_expr"],
                "comment": col["comment"],
            }
            for col in columns
        ],
        "constraints": [
            {
                "name": con["constraint_name"],
                "type": con["constraint_type"],
                "definition": con["definition"] or "",
                "columns": _decode_json_list(con["columns_json"]),
            }
            for con in constraints
        ],
        "indexes": [
            {
                "name": idx["index_name"],
                "definition": idx["definition"] or "",
                "is_unique": bool(idx["is_unique"]),
                "is_primary": bool(idx["is_primary"]),
                "columns": _decode_json_list(idx["columns_json"]),
            }
            for idx in indexes
        ],
        "dependencies": [
            {
                "type": dep["dependency_type"],
                "object_id": dep["depends_on_object_id"],
                "fqname": dep["depends_on_fqname"],
            }
            for dep in dependencies
        ],
        "context": context["context_text"] if context else "",
    }
    return payload
