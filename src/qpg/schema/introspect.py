from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from typing import Any

from qpg.db_pg import fetch_all


@dataclass
class ColumnMeta:
    parent_fqname: str
    column_name: str
    data_type: str
    is_nullable: bool
    ordinal_position: int
    default_expr: str | None
    comment: str | None


@dataclass
class ConstraintMeta:
    parent_fqname: str
    constraint_name: str
    constraint_type: str
    definition: str
    columns: list[str]


@dataclass
class IndexMeta:
    parent_fqname: str
    index_name: str
    definition: str
    is_unique: bool
    is_primary: bool
    columns: list[str]


@dataclass
class DependencyMeta:
    parent_fqname: str
    depends_on_fqname: str
    dependency_type: str


@dataclass
class IntrospectedObject:
    schema_name: str | None
    object_name: str
    object_type: str
    definition: str | None
    comment: str | None
    signature: str | None = None
    owner: str | None = None
    is_system: bool = False

    @property
    def fqname(self) -> str:
        if self.schema_name:
            return f"{self.schema_name}.{self.object_name}"
        return self.object_name


@dataclass
class IntrospectionBundle:
    objects: list[IntrospectedObject] = field(default_factory=list)
    columns: list[ColumnMeta] = field(default_factory=list)
    constraints: list[ConstraintMeta] = field(default_factory=list)
    indexes: list[IndexMeta] = field(default_factory=list)
    dependencies: list[DependencyMeta] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _system_schema(name: str | None) -> bool:
    if name is None:
        return False
    return name.startswith("pg_") or name == "information_schema"


def _object_from_row(row: dict[str, Any]) -> IntrospectedObject:
    schema_name = row.get("schema_name")
    return IntrospectedObject(
        schema_name=str(schema_name) if schema_name is not None else None,
        object_name=str(row["object_name"]),
        object_type=str(row["object_type"]),
        definition=str(row["definition"]) if row.get("definition") is not None else None,
        comment=str(row["comment"]) if row.get("comment") is not None else None,
        signature=str(row["signature"]) if row.get("signature") is not None else None,
        owner=str(row["owner"]) if row.get("owner") is not None else None,
        is_system=_system_schema(str(schema_name) if schema_name is not None else None),
    )


def introspect_schema(conn: Any, *, include_functions: bool = True) -> IntrospectionBundle:
    bundle = IntrospectionBundle()

    def safe_fetch(section: str, sql: str) -> list[dict[str, Any]]:
        try:
            return fetch_all(conn, sql)
        except Exception as exc:
            bundle.warnings.append(f"{section}: {exc}")
            return []

    schema_rows = safe_fetch(
        "schemas",
        """
        SELECT n.nspname AS schema_name,
               n.nspname AS object_name,
               'schema' AS object_type,
               NULL::text AS definition,
               NULL::text AS comment,
               NULL::text AS signature,
               NULL::text AS owner
        FROM pg_namespace n
        WHERE n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        ORDER BY n.nspname
        """,
    )
    bundle.objects.extend(_object_from_row(row) for row in schema_rows)

    relation_rows = safe_fetch(
        "relations",
        """
        SELECT n.nspname AS schema_name,
               c.relname AS object_name,
               CASE c.relkind
                    WHEN 'r' THEN 'table'
                    WHEN 'p' THEN 'table'
                    WHEN 'v' THEN 'view'
                    WHEN 'm' THEN 'view'
                    WHEN 'f' THEN 'table'
                    ELSE 'table'
               END AS object_type,
               CASE
                    WHEN c.relkind IN ('v', 'm') THEN pg_get_viewdef(c.oid, true)
                    ELSE NULL
               END AS definition,
               obj_description(c.oid, 'pg_class') AS comment,
               NULL::text AS signature,
               pg_get_userbyid(c.relowner) AS owner
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        ORDER BY n.nspname, c.relname
        """,
    )
    bundle.objects.extend(_object_from_row(row) for row in relation_rows)

    extension_rows = safe_fetch(
        "extensions",
        """
        SELECT n.nspname AS schema_name,
               e.extname AS object_name,
               'extension' AS object_type,
               ('version=' || e.extversion) AS definition,
               obj_description(e.oid, 'pg_extension') AS comment,
               NULL::text AS signature,
               NULL::text AS owner
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        ORDER BY e.extname
        """,
    )
    bundle.objects.extend(_object_from_row(row) for row in extension_rows)

    if include_functions:
        function_rows = safe_fetch(
            "functions",
            """
            SELECT n.nspname AS schema_name,
                   p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS object_name,
                   CASE p.prokind WHEN 'p' THEN 'procedure' ELSE 'function' END AS object_type,
                   pg_get_functiondef(p.oid) AS definition,
                   obj_description(p.oid, 'pg_proc') AS comment,
                   pg_get_function_identity_arguments(p.oid) AS signature,
                   pg_get_userbyid(p.proowner) AS owner
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'
              AND p.prokind IN ('f', 'p')
            ORDER BY n.nspname, p.proname, pg_get_function_identity_arguments(p.oid)
            """,
        )
        bundle.objects.extend(_object_from_row(row) for row in function_rows)

    column_rows = safe_fetch(
        "columns",
        """
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               a.attname AS column_name,
               format_type(a.atttypid, a.atttypmod) AS data_type,
               NOT a.attnotnull AS is_nullable,
               a.attnum AS ordinal_position,
               pg_get_expr(ad.adbin, ad.adrelid) AS default_expr,
               col_description(a.attrelid, a.attnum) AS comment
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attrdef ad ON ad.adrelid = a.attrelid AND ad.adnum = a.attnum
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND a.attnum > 0
          AND NOT a.attisdropped
          AND n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        ORDER BY n.nspname, c.relname, a.attnum
        """,
    )
    for row in column_rows:
        parent_fqname = f"{row['schema_name']}.{row['table_name']}"
        bundle.columns.append(
            ColumnMeta(
                parent_fqname=parent_fqname,
                column_name=str(row["column_name"]),
                data_type=str(row["data_type"]),
                is_nullable=bool(row["is_nullable"]),
                ordinal_position=int(row["ordinal_position"]),
                default_expr=str(row["default_expr"]) if row.get("default_expr") else None,
                comment=str(row["comment"]) if row.get("comment") else None,
            )
        )

    constraint_rows = safe_fetch(
        "constraints",
        """
        SELECT n.nspname AS schema_name,
               c.relname AS table_name,
               con.conname AS constraint_name,
               CASE con.contype
                    WHEN 'p' THEN 'primary_key'
                    WHEN 'f' THEN 'foreign_key'
                    WHEN 'u' THEN 'unique'
                    WHEN 'c' THEN 'check'
                    WHEN 'x' THEN 'exclusion'
                    ELSE con.contype::text
               END AS constraint_type,
               pg_get_constraintdef(con.oid, true) AS definition,
               COALESCE(
                 ARRAY(
                    SELECT att.attname
                    FROM unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = keys.attnum
                    ORDER BY keys.ord
                 ),
                 ARRAY[]::text[]
               ) AS columns
        FROM pg_constraint con
        JOIN pg_class c ON c.oid = con.conrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        ORDER BY n.nspname, c.relname, con.conname
        """,
    )
    for row in constraint_rows:
        parent_fqname = f"{row['schema_name']}.{row['table_name']}"
        bundle.constraints.append(
            ConstraintMeta(
                parent_fqname=parent_fqname,
                constraint_name=str(row["constraint_name"]),
                constraint_type=str(row["constraint_type"]),
                definition=str(row["definition"]),
                columns=[str(x) for x in row.get("columns", [])],
            )
        )

    index_rows = safe_fetch(
        "indexes",
        """
        SELECT n.nspname AS schema_name,
               t.relname AS table_name,
               i.relname AS index_name,
               pg_get_indexdef(i.oid) AS definition,
               ix.indisunique AS is_unique,
               ix.indisprimary AS is_primary,
               COALESCE(
                 ARRAY(
                    SELECT att.attname
                    FROM unnest(ix.indkey) WITH ORDINALITY AS keys(attnum, ord)
                    JOIN pg_attribute att ON att.attrelid = t.oid AND att.attnum = keys.attnum
                    WHERE keys.attnum > 0
                    ORDER BY keys.ord
                 ),
                 ARRAY[]::text[]
               ) AS columns
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname !~ '^pg_'
          AND n.nspname <> 'information_schema'
        ORDER BY n.nspname, t.relname, i.relname
        """,
    )
    for row in index_rows:
        parent_fqname = f"{row['schema_name']}.{row['table_name']}"
        bundle.indexes.append(
            IndexMeta(
                parent_fqname=parent_fqname,
                index_name=str(row["index_name"]),
                definition=str(row["definition"]),
                is_unique=bool(row["is_unique"]),
                is_primary=bool(row["is_primary"]),
                columns=[str(x) for x in row.get("columns", [])],
            )
        )

    dependency_rows = safe_fetch(
        "dependencies",
        """
        SELECT src_ns.nspname AS src_schema,
               src.relname AS src_name,
               dst_ns.nspname AS dst_schema,
               dst.relname AS dst_name,
               dep.deptype::text AS dependency_type
        FROM pg_depend dep
        JOIN pg_class src ON src.oid = dep.objid
        JOIN pg_namespace src_ns ON src_ns.oid = src.relnamespace
        JOIN pg_class dst ON dst.oid = dep.refobjid
        JOIN pg_namespace dst_ns ON dst_ns.oid = dst.relnamespace
        WHERE src_ns.nspname !~ '^pg_'
          AND src_ns.nspname <> 'information_schema'
          AND dst_ns.nspname !~ '^pg_'
          AND dst_ns.nspname <> 'information_schema'
          AND src.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND dst.relkind IN ('r', 'p', 'v', 'm', 'f')
        """,
    )
    for row in dependency_rows:
        bundle.dependencies.append(
            DependencyMeta(
                parent_fqname=f"{row['src_schema']}.{row['src_name']}",
                depends_on_fqname=f"{row['dst_schema']}.{row['dst_name']}",
                dependency_type=str(row["dependency_type"]),
            )
        )

    return bundle


def apply_filters(
    bundle: IntrospectionBundle,
    *,
    include_schemas: list[str] | None = None,
    skip_patterns: list[str] | None = None,
) -> IntrospectionBundle:
    schemas = {name.strip() for name in (include_schemas or []) if name.strip()}
    patterns = [pattern.strip() for pattern in (skip_patterns or []) if pattern.strip()]

    if not schemas and not patterns:
        return bundle

    def object_allowed(obj: IntrospectedObject) -> bool:
        if schemas and (obj.schema_name is None or obj.schema_name not in schemas):
            return False
        fqname = obj.fqname
        for pattern in patterns:
            if fnmatch(fqname, pattern) or fnmatch(obj.object_name, pattern):
                return False
        return True

    filtered = IntrospectionBundle(warnings=list(bundle.warnings))
    filtered.objects = [obj for obj in bundle.objects if object_allowed(obj)]
    allowed_fqnames = {obj.fqname for obj in filtered.objects}

    filtered.columns = [column for column in bundle.columns if column.parent_fqname in allowed_fqnames]
    filtered.constraints = [
        constraint for constraint in bundle.constraints if constraint.parent_fqname in allowed_fqnames
    ]
    filtered.indexes = [index for index in bundle.indexes if index.parent_fqname in allowed_fqnames]
    filtered.dependencies = [
        dep
        for dep in bundle.dependencies
        if dep.parent_fqname in allowed_fqnames and dep.depends_on_fqname in allowed_fqnames
    ]
    return filtered
