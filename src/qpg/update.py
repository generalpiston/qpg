from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from qpg.config import ensure_dirs, get_paths
from qpg.contexts import list_contexts
from qpg.db_pg import PostgresDependencyError, connect_pg
from qpg.index.build import update_source_index
from qpg.index.vec import require_vector_model
from qpg.schema.introspect import apply_filters, introspect_schema
from qpg.sources import (
    SourceRecord,
    get_source,
    list_sources,
    mark_source_error,
    mark_source_indexed,
)
from qpg.usage import collect_index_usage_records, usage_snapshot_path, write_usage_snapshot_records


class NoSourcesConfiguredError(RuntimeError):
    pass


@dataclass
class SourceUpdateResult:
    source: str
    ok: bool
    warnings: list[str]
    indexed: dict[str, int] | None = None
    usage_snapshot: dict[str, Any] | None = None
    error: str | None = None


def _collect_sources(conn: sqlite3.Connection, source_name: str | None) -> list[SourceRecord]:
    if source_name:
        return [get_source(conn, source_name)]
    return list_sources(conn)


def _refresh_usage_snapshot_for_source(*, source_name: str, source_dsn: str) -> tuple[Path, int]:
    try:
        with connect_pg(source_dsn) as pg_conn:
            records = collect_index_usage_records(pg_conn, source_name=source_name)
    except PostgresDependencyError:
        raise
    except Exception as exc:
        raise RuntimeError(f"failed usage refresh for '{source_name}': {exc}") from exc

    paths = ensure_dirs(get_paths())
    output_path = usage_snapshot_path(paths, source_name)
    write_usage_snapshot_records(output_path, records)
    return output_path, len(records)


def update_sources(
    conn: sqlite3.Connection,
    *,
    source_name: str | None = None,
    skip_functions: bool = False,
) -> dict[str, Any]:
    sources = _collect_sources(conn, source_name)
    if not sources:
        raise NoSourcesConfiguredError("no sources configured")

    require_vector_model()
    ctx_rows = list_contexts(conn)

    exit_code = 0
    results: list[SourceUpdateResult] = []
    for source in sources:
        result = SourceUpdateResult(source=source.name, ok=False, warnings=[])
        results.append(result)

        try:
            with connect_pg(source.dsn) as pg_conn:
                bundle = introspect_schema(pg_conn, include_functions=not skip_functions)
                bundle = apply_filters(
                    bundle,
                    include_schemas=source.include_schemas,
                    skip_patterns=source.skip_patterns,
                )
        except PostgresDependencyError:
            raise
        except Exception as exc:
            message = f"failed introspection: {exc}"
            mark_source_error(conn, source.id, message)
            result.error = message
            exit_code = 4
            continue

        result.warnings = list(bundle.warnings)

        try:
            stats = update_source_index(conn, source=source, bundle=bundle, contexts=ctx_rows)
            mark_source_indexed(conn, source.id)
            result.indexed = {
                "objects": stats.objects,
                "columns": stats.columns,
                "constraints": stats.constraints,
                "indexes": stats.indexes,
                "dependencies": stats.dependencies,
                "vectors": stats.vectors,
            }
        except Exception as exc:
            message = f"failed indexing: {exc}"
            mark_source_error(conn, source.id, message)
            result.error = message
            exit_code = 4
            continue

        try:
            usage_path, usage_count = _refresh_usage_snapshot_for_source(
                source_name=source.name,
                source_dsn=source.dsn,
            )
            result.usage_snapshot = {"path": str(usage_path), "records": usage_count}
            result.ok = True
        except PostgresDependencyError:
            raise
        except Exception as exc:
            message = str(exc)
            mark_source_error(conn, source.id, message)
            result.error = message
            exit_code = 4

    return {
        "source_count": len(sources),
        "results": [asdict(result) for result in results],
        "exit_code": exit_code,
    }
