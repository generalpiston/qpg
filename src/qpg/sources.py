from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from qpg.db_sqlite import ensure_schema
from qpg.util.pg_dsn import enforce_readonly_dsn


@dataclass
class SourceRecord:
    id: int
    name: str
    dsn: str
    include_schemas: list[str]
    skip_patterns: list[str]
    created_at: str
    updated_at: str
    last_indexed_at: str | None
    last_error: str | None


class SourceExistsError(RuntimeError):
    pass


class SourceNotFoundError(RuntimeError):
    pass


def _row_to_source(row: sqlite3.Row) -> SourceRecord:
    include_raw = row["include_schemas_json"]
    skip_raw = row["skip_patterns_json"]
    return SourceRecord(
        id=row["id"],
        name=row["name"],
        dsn=row["dsn"],
        include_schemas=json.loads(include_raw) if include_raw else [],
        skip_patterns=json.loads(skip_raw) if skip_raw else [],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_indexed_at=row["last_indexed_at"],
        last_error=row["last_error"],
    )


def add_source(
    conn: sqlite3.Connection,
    name: str,
    dsn: str,
    *,
    include_schemas: list[str] | None = None,
    skip_patterns: list[str] | None = None,
) -> SourceRecord:
    ensure_schema(conn)
    normalized_dsn = enforce_readonly_dsn(dsn)
    include_json = json.dumps(sorted(set(include_schemas or [])))
    skip_json = json.dumps(sorted(set(skip_patterns or [])))
    try:
        conn.execute(
            """
            INSERT INTO sources(name, dsn, include_schemas_json, skip_patterns_json, updated_at)
            VALUES(?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (name, normalized_dsn, include_json, skip_json),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SourceExistsError(f"source '{name}' already exists") from exc
    return get_source(conn, name)


def list_sources(conn: sqlite3.Connection) -> list[SourceRecord]:
    ensure_schema(conn)
    rows = conn.execute(
        """
        SELECT id, name, dsn, include_schemas_json, skip_patterns_json,
               created_at, updated_at, last_indexed_at, last_error
        FROM sources
        ORDER BY name ASC
        """
    ).fetchall()
    return [_row_to_source(row) for row in rows]


def get_source(conn: sqlite3.Connection, name: str) -> SourceRecord:
    row = conn.execute(
        """
        SELECT id, name, dsn, include_schemas_json, skip_patterns_json,
               created_at, updated_at, last_indexed_at, last_error
        FROM sources WHERE name = ?
        """,
        (name,),
    ).fetchone()
    if row is None:
        raise SourceNotFoundError(f"source '{name}' not found")
    return _row_to_source(row)


def delete_source(conn: sqlite3.Connection, name: str) -> None:
    conn.execute(
        """
        DELETE FROM contexts
        WHERE target_uri = ?
           OR target_uri LIKE ?
           OR target_uri LIKE ?
        """,
        (f"qpg://{name}", f"qpg://{name}/%", f"qpg://{name}#%"),
    )
    cursor = conn.execute("DELETE FROM sources WHERE name = ?", (name,))
    conn.commit()
    if cursor.rowcount == 0:
        raise SourceNotFoundError(f"source '{name}' not found")


def rename_source(conn: sqlite3.Connection, old_name: str, new_name: str) -> SourceRecord:
    try:
        cursor = conn.execute(
            """
            UPDATE sources
            SET name = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE name = ?
            """,
            (new_name, old_name),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise SourceExistsError(f"source '{new_name}' already exists") from exc

    if cursor.rowcount == 0:
        raise SourceNotFoundError(f"source '{old_name}' not found")
    return get_source(conn, new_name)


def mark_source_indexed(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute(
        """
        UPDATE sources
        SET last_indexed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
            last_error = NULL,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (source_id,),
    )
    conn.commit()


def mark_source_error(conn: sqlite3.Connection, source_id: int, error: str) -> None:
    conn.execute(
        """
        UPDATE sources
        SET last_error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ?
        """,
        (error, source_id),
    )
    conn.commit()
