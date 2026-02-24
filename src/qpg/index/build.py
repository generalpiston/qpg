from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from qpg.contexts import ContextRecord, ObjectRef, resolve_effective_context
from qpg.index.fts import rebuild_fts
from qpg.index.vec import upsert_embedding
from qpg.schema.introspect import IntrospectionBundle
from qpg.schema.normalize import normalize_object
from qpg.sources import SourceRecord


@dataclass
class UpdateStats:
    objects: int
    columns: int
    constraints: int
    indexes: int
    dependencies: int
    vectors: int


def update_source_index(
    conn: sqlite3.Connection,
    *,
    source: SourceRecord,
    bundle: IntrospectionBundle,
    contexts: list[ContextRecord],
) -> UpdateStats:
    conn.execute("DELETE FROM db_objects WHERE source_id = ?", (source.id,))

    root_fqname_to_id: dict[str, str] = {}
    root_schema_by_fqname: dict[str, str | None] = {}
    defs_map: dict[str, list[str]] = {}
    comments_map: dict[str, str] = {}
    object_name_map: dict[str, str] = {}
    schema_map: dict[str, str | None] = {}

    def register_object(
        *,
        schema_name: str | None,
        object_name: str,
        object_type: str,
        definition: str | None,
        comment: str | None,
        signature: str | None = None,
        owner: str | None = None,
        is_system: bool = False,
    ) -> str:
        normalized = normalize_object(
            source_name=source.name,
            schema_name=schema_name,
            object_name=object_name,
            object_type=object_type,
            definition=definition,
            comment=comment,
            signature=signature,
            owner=owner,
            is_system=is_system,
        )
        conn.execute(
            """
            INSERT INTO db_objects(
                id,
                source_id,
                schema_name,
                object_name,
                object_type,
                fqname,
                definition,
                comment,
                signature,
                owner,
                is_system,
                updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                normalized.object_id,
                source.id,
                normalized.schema_name,
                normalized.object_name,
                normalized.object_type,
                normalized.fqname,
                normalized.definition,
                normalized.comment,
                normalized.signature,
                normalized.owner,
                int(normalized.is_system),
            ),
        )
        defs_map[normalized.object_id] = [normalized.definition]
        comments_map[normalized.object_id] = normalized.comment
        object_name_map[normalized.object_id] = normalized.object_name
        schema_map[normalized.object_id] = normalized.schema_name
        return normalized.object_id

    for obj in bundle.objects:
        object_id = register_object(
            schema_name=obj.schema_name,
            object_name=obj.object_name,
            object_type=obj.object_type,
            definition=obj.definition,
            comment=obj.comment,
            signature=obj.signature,
            owner=obj.owner,
            is_system=obj.is_system,
        )
        root_fqname_to_id[obj.fqname] = object_id
        root_schema_by_fqname[obj.fqname] = obj.schema_name

    col_count = 0
    for column in bundle.columns:
        parent_object_id = root_fqname_to_id.get(column.parent_fqname)
        parent_schema = root_schema_by_fqname.get(column.parent_fqname)
        if parent_object_id is None:
            continue
        conn.execute(
            """
            INSERT INTO columns(
                object_id,
                column_name,
                data_type,
                is_nullable,
                ordinal_position,
                default_expr,
                comment,
                updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                parent_object_id,
                column.column_name,
                column.data_type,
                int(column.is_nullable),
                column.ordinal_position,
                column.default_expr,
                column.comment,
            ),
        )
        col_count += 1
        default_part = f" default={column.default_expr}" if column.default_expr else ""
        defs_map[parent_object_id].append(f"column {column.column_name} {column.data_type}{default_part}")

        parent_object_name = (
            column.parent_fqname.split(".", 1)[1]
            if "." in column.parent_fqname
            else column.parent_fqname
        )
        register_object(
            schema_name=parent_schema,
            object_name=f"{parent_object_name}.{column.column_name}",
            object_type="column",
            definition=f"{column.data_type}{default_part}".strip(),
            comment=column.comment,
            signature=f"in {column.parent_fqname}",
        )

    constraint_count = 0
    for constraint in bundle.constraints:
        parent_object_id = root_fqname_to_id.get(constraint.parent_fqname)
        parent_schema = root_schema_by_fqname.get(constraint.parent_fqname)
        if parent_object_id is None:
            continue
        conn.execute(
            """
            INSERT INTO constraints(
                object_id,
                constraint_name,
                constraint_type,
                definition,
                columns_json,
                updated_at
            ) VALUES(?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                parent_object_id,
                constraint.constraint_name,
                constraint.constraint_type,
                constraint.definition,
                json.dumps(constraint.columns),
            ),
        )
        constraint_count += 1
        defs_map[parent_object_id].append(
            f"constraint {constraint.constraint_name} {constraint.definition}"
        )

        parent_object_name = (
            constraint.parent_fqname.split(".", 1)[1]
            if "." in constraint.parent_fqname
            else constraint.parent_fqname
        )
        register_object(
            schema_name=parent_schema,
            object_name=f"{parent_object_name}.{constraint.constraint_name}",
            object_type="constraint",
            definition=constraint.definition,
            comment=None,
            signature=f"in {constraint.parent_fqname}",
        )

    index_count = 0
    for index in bundle.indexes:
        parent_object_id = root_fqname_to_id.get(index.parent_fqname)
        parent_schema = root_schema_by_fqname.get(index.parent_fqname)
        if parent_object_id is None:
            continue
        conn.execute(
            """
            INSERT INTO indexes(
                object_id,
                index_name,
                definition,
                is_unique,
                is_primary,
                columns_json,
                updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                parent_object_id,
                index.index_name,
                index.definition,
                int(index.is_unique),
                int(index.is_primary),
                json.dumps(index.columns),
            ),
        )
        index_count += 1
        defs_map[parent_object_id].append(f"index {index.index_name} {index.definition}")

        parent_object_name = (
            index.parent_fqname.split(".", 1)[1]
            if "." in index.parent_fqname
            else index.parent_fqname
        )
        register_object(
            schema_name=parent_schema,
            object_name=f"{parent_object_name}.{index.index_name}",
            object_type="index",
            definition=index.definition,
            comment=None,
            signature=f"in {index.parent_fqname}",
        )

    dep_count = 0
    for dep in bundle.dependencies:
        dep_object_id = root_fqname_to_id.get(dep.parent_fqname)
        depends_on_id = root_fqname_to_id.get(dep.depends_on_fqname)
        if dep_object_id is None or depends_on_id is None:
            continue
        conn.execute(
            """
            INSERT INTO dependencies(
                object_id,
                depends_on_object_id,
                dependency_type,
                updated_at
            ) VALUES(?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (dep_object_id, depends_on_id, dep.dependency_type),
        )
        dep_count += 1

    conn.execute(
        "DELETE FROM object_context_effective WHERE object_id IN (SELECT id FROM db_objects WHERE source_id = ?)",
        (source.id,),
    )
    conn.execute("DELETE FROM lexical_docs WHERE source_id = ?", (source.id,))

    vector_count = 0

    for object_id, obj_name in object_name_map.items():
        schema: str | None = schema_map[object_id]
        obj_ref = ObjectRef(
            source=source.name,
            schema=schema,
            object_name=obj_name,
            object_id=object_id,
        )
        context_text = resolve_effective_context(contexts, obj_ref)
        if context_text:
            conn.execute(
                """
                INSERT INTO object_context_effective(object_id, context_text, updated_at)
                VALUES(?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(object_id) DO UPDATE SET
                    context_text = excluded.context_text,
                    updated_at = excluded.updated_at
                """,
                (object_id, context_text),
            )

        comment_text = comments_map.get(object_id, "")
        defs_text = "\n".join(part for part in defs_map.get(object_id, []) if part)
        name_col = obj_name if schema is None else f"{schema}.{obj_name}"
        conn.execute(
            """
            INSERT INTO lexical_docs(
                object_id,
                source_id,
                name_col,
                comment_col,
                defs_col,
                context_col,
                updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (object_id, source.id, name_col, comment_text, defs_text, context_text),
        )

        vector_text = "\n".join(part for part in [name_col, comment_text, defs_text, context_text] if part)
        upsert_embedding(conn, object_id=object_id, text=vector_text)
        vector_count += 1

    rebuild_fts(conn, source_id=source.id)
    conn.commit()

    return UpdateStats(
        objects=len(object_name_map),
        columns=col_count,
        constraints=constraint_count,
        indexes=index_count,
        dependencies=dep_count,
        vectors=vector_count,
    )
