from __future__ import annotations

import re
import sqlite3
from typing import Any


def _sanitize_tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text)


def make_match_query(text: str) -> str:
    tokens = _sanitize_tokens(text)
    if not tokens:
        return '""'
    return " OR ".join(f'"{token}"' for token in tokens)


def rebuild_fts(conn: sqlite3.Connection, *, source_id: int | None = None) -> None:
    if source_id is None:
        conn.execute("DELETE FROM objects_fts")
        rows = conn.execute(
            """
            SELECT ld.object_id,
                   s.name AS source_name,
                   o.schema_name,
                   o.object_type,
                   ld.name_col,
                   ld.comment_col,
                   ld.defs_col,
                   ld.context_col
            FROM lexical_docs ld
            JOIN db_objects o ON o.id = ld.object_id
            JOIN sources s ON s.id = ld.source_id
            """
        ).fetchall()
    else:
        conn.execute(
            """
            DELETE FROM objects_fts
            WHERE object_id IN (
                SELECT object_id FROM lexical_docs WHERE source_id = ?
            )
            """,
            (source_id,),
        )
        rows = conn.execute(
            """
            SELECT ld.object_id,
                   s.name AS source_name,
                   o.schema_name,
                   o.object_type,
                   ld.name_col,
                   ld.comment_col,
                   ld.defs_col,
                   ld.context_col
            FROM lexical_docs ld
            JOIN db_objects o ON o.id = ld.object_id
            JOIN sources s ON s.id = ld.source_id
            WHERE ld.source_id = ?
            """,
            (source_id,),
        ).fetchall()

    for row in rows:
        conn.execute(
            """
            INSERT INTO objects_fts(
                object_id,
                source_name,
                schema_name,
                kind,
                name_col,
                comment_col,
                defs_col,
                context_col
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["object_id"],
                row["source_name"],
                row["schema_name"],
                row["object_type"],
                row["name_col"],
                row["comment_col"],
                row["defs_col"],
                row["context_col"],
            ),
        )


def search_fts(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int = 10,
    source: str | None = None,
    schema: str | None = None,
    kind: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    match_query = make_match_query(query)
    filters: list[str] = ["objects_fts MATCH ?"]
    params: list[Any] = [match_query]

    if source:
        filters.append("s.name = ?")
        params.append(source)
    if schema:
        filters.append("o.schema_name = ?")
        params.append(schema)
    if kind:
        filters.append("o.object_type = ?")
        params.append(kind)

    where_clause = " AND ".join(filters)
    params.append(limit)

    rows = conn.execute(
        f"""
        SELECT o.id AS object_id,
               o.fqname,
               o.object_type,
               s.name AS source_name,
               bm25(objects_fts, 3.5, 1.5, 1.1, 5.0) AS bm25_score,
               snippet(objects_fts, 4, '[', ']', '...', 8) AS name_snippet,
               snippet(objects_fts, 7, '[', ']', '...', 12) AS context_snippet
        FROM objects_fts
        JOIN db_objects o ON o.id = objects_fts.object_id
        JOIN sources s ON s.id = o.source_id
        WHERE {where_clause}
        ORDER BY bm25_score ASC
        LIMIT ?
        """,
        params,
    ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        bm25_score = float(row["bm25_score"])
        score = 1.0 / (1.0 + max(bm25_score, 0.0))
        if min_score is not None and score < min_score:
            continue
        result.append(
            {
                "object_id": row["object_id"],
                "fqname": row["fqname"],
                "object_type": row["object_type"],
                "source_name": row["source_name"],
                "score": score,
                "bm25": bm25_score,
                "name_snippet": row["name_snippet"],
                "context_snippet": row["context_snippet"],
            }
        )
    return result
