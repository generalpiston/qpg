from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class ContextRecord:
    id: int
    target_uri: str
    body: str
    created_at: str


@dataclass(frozen=True)
class ContextScope:
    source: str
    schema: str | None = None
    object_name: str | None = None
    object_id: str | None = None


@dataclass(frozen=True)
class ObjectRef:
    source: str
    schema: str | None
    object_name: str
    object_id: str


class InvalidContextTarget(ValueError):
    pass


class ContextSourceNotFoundError(ValueError):
    pass


def add_context(conn: sqlite3.Connection, target_uri: str, body: str) -> ContextRecord:
    scope = parse_context_target(target_uri)
    source_row = conn.execute("SELECT 1 FROM sources WHERE name = ?", (scope.source,)).fetchone()
    if source_row is None:
        raise ContextSourceNotFoundError(f"source '{scope.source}' not found")
    conn.execute(
        """
        INSERT INTO contexts(target_uri, body)
        VALUES(?, ?)
        """,
        (target_uri, body),
    )
    conn.commit()
    row = conn.execute(
        """
        SELECT id, target_uri, body, created_at
        FROM contexts
        WHERE rowid = last_insert_rowid()
        """
    ).fetchone()
    assert row is not None
    return ContextRecord(
        id=row["id"],
        target_uri=row["target_uri"],
        body=row["body"],
        created_at=row["created_at"],
    )


def list_contexts(conn: sqlite3.Connection) -> list[ContextRecord]:
    rows = conn.execute(
        """
        SELECT id, target_uri, body, created_at
        FROM contexts
        ORDER BY id ASC
        """
    ).fetchall()
    return [
        ContextRecord(
            id=row["id"],
            target_uri=row["target_uri"],
            body=row["body"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def remove_context(conn: sqlite3.Connection, key: str) -> int:
    if key.isdigit():
        cursor = conn.execute("DELETE FROM contexts WHERE id = ?", (int(key),))
    else:
        cursor = conn.execute("DELETE FROM contexts WHERE target_uri = ?", (key,))
    conn.commit()
    return cursor.rowcount


def parse_context_target(target_uri: str) -> ContextScope:
    parsed = urlsplit(target_uri)
    if parsed.scheme != "qpg":
        raise InvalidContextTarget("context target must begin with qpg://")
    if not parsed.netloc:
        raise InvalidContextTarget("context target must include a source name")

    source = parsed.netloc
    fragment = parsed.fragment.strip()
    if fragment:
        return ContextScope(source=source, object_id=fragment)

    path = parsed.path.strip("/")
    if not path:
        return ContextScope(source=source)

    if "/" in path:
        schema_part, object_part = path.split("/", 1)
        schema_value = schema_part.strip() or None
        object_value = object_part.strip() or None
        if object_value:
            return ContextScope(source=source, schema=schema_value, object_name=object_value)

    if "." in path:
        schema_part, object_part = path.split(".", 1)
        return ContextScope(
            source=source,
            schema=schema_part.strip() or None,
            object_name=object_part.strip() or None,
        )

    return ContextScope(source=source, schema=path)


def context_applies(scope: ContextScope, obj: ObjectRef) -> bool:
    if scope.source != obj.source:
        return False
    if scope.object_id and scope.object_id != obj.object_id:
        return False
    if scope.schema and scope.schema != (obj.schema or ""):
        return False
    if scope.object_name:
        if scope.object_name == obj.object_name:
            return True
        # Child synthetic object names are stored as "<parent>.<child>".
        # Treat parent object context as inherited by its children.
        return obj.object_name.startswith(f"{scope.object_name}.")
    return True


def resolve_effective_context(
    contexts: list[ContextRecord],
    obj: ObjectRef,
) -> str:
    lines: list[str] = []
    for ctx in contexts:
        try:
            scope = parse_context_target(ctx.target_uri)
        except InvalidContextTarget:
            continue
        if context_applies(scope, obj):
            value = ctx.body.strip()
            if value and value not in lines:
                lines.append(value)
    return "\n".join(lines)
