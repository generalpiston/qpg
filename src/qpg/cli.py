from __future__ import annotations

import argparse
import json
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO

from qpg.config import ensure_dirs, get_paths
from qpg.context_generate import (
    ContextGenerationError,
    ContextGenerationResult,
    generate_table_context_text,
    list_table_context_candidates,
)
from qpg.contexts import (
    ContextSourceNotFoundError,
    InvalidContextTarget,
    add_context,
    list_contexts,
    remove_context,
)
from qpg.db_pg import PostgresDependencyError, connect_pg
from qpg.db_sqlite import connect_sqlite, ensure_schema
from qpg.get import ObjectNotFoundError, get_object_payload
from qpg.index.build import update_source_index
from qpg.index.fts import rebuild_fts, search_fts
from qpg.index.vec import (
    VectorModelNotInitializedError,
    init_vector_model,
    require_vector_model,
    vector_search,
)
from qpg.mcp.server_http import serve_http
from qpg.mcp.server_stdio import serve_stdio
from qpg.query.expand import expand_query
from qpg.query.rerank import RerankHookError, rerank_with_hook
from qpg.query.rrf import reciprocal_rank_fusion
from qpg.schema.introspect import apply_filters, introspect_schema
from qpg.schema.privilege_check import check_privileges, format_privilege_report
from qpg.settings import config_yaml_path, resolve_openai_settings
from qpg.sources import (
    SourceExistsError,
    SourceNotFoundError,
    add_source,
    delete_source,
    get_source,
    list_sources,
    mark_source_error,
    mark_source_indexed,
    rename_source,
)
from qpg.util.pg_dsn import dsn_has_password, dsn_with_password
from qpg.util.redaction import redact_dsn, redact_secret


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _with_db(*, check_same_thread: bool = True) -> sqlite3.Connection:
    paths = ensure_dirs(get_paths())
    conn = connect_sqlite(paths.index_db, check_same_thread=check_same_thread)
    ensure_schema(conn)
    return conn


def _format_rows(rows: list[dict[str, Any]], *, files: bool = False) -> None:
    for row in rows:
        if files:
            print(row["fqname"])
            continue
        score = float(row.get("score", row.get("rrf_score", 0.0)))
        source = row.get("source_name", "?")
        print(f"{row['object_id']}\t{row['fqname']}\t{row.get('object_type', '?')}\t{source}\t{score:.4f}")


def _short_description(payload: dict[str, Any]) -> str:
    comment = str(payload.get("comment", "")).strip()
    if comment:
        return comment
    context = str(payload.get("context", "")).strip()
    if context:
        return context.splitlines()[0]
    kind = payload.get("kind", "object")
    return f"{kind} schema object"


def _table_definition_from_payload(payload: dict[str, Any]) -> str:
    fqname = str(payload.get("fqname", "unknown_table"))
    columns = payload.get("columns", [])
    if not isinstance(columns, list) or not columns:
        return f"CREATE TABLE {fqname} ();"

    lines: list[str] = []
    for column in columns:
        parts = [f"{column['name']} {column['type']}"]
        if not bool(column.get("nullable", True)):
            parts.append("NOT NULL")
        default = column.get("default")
        if default:
            parts.append(f"DEFAULT {default}")
        lines.append("  " + " ".join(parts))
    return "CREATE TABLE " + fqname + " (\n" + ",\n".join(lines) + "\n);"


def _definition_text(payload: dict[str, Any]) -> str:
    definition = str(payload.get("definition", "")).strip()
    if definition:
        return definition
    if payload.get("kind") == "table":
        return _table_definition_from_payload(payload)
    return f"-- No definition available for {payload.get('fqname', 'object')}"


def _format_search_rows_detailed(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no matching objects found")
        return

    for row in rows:
        payload = get_object_payload(conn, str(row["fqname"]), source=row.get("source_name"))
        description = _short_description(payload)
        definition = _definition_text(payload)
        score = float(row.get("score", 0.0))
        print(f"{payload['fqname']} ({payload['kind']}) [{payload['source']}] score={score:.4f}")
        print(f"description: {description}")
        print("definition:")
        print(definition)
        print()


def _collect_sources(conn: sqlite3.Connection, source_name: str | None) -> list[Any]:
    if source_name:
        return [get_source(conn, source_name)]
    return list_sources(conn)


def _resolve_source_add_dsn(dsn: str, *, use_stdin_password: bool, stdin: TextIO) -> str:
    if not use_stdin_password:
        return dsn

    if dsn_has_password(dsn):
        raise ValueError("do not use --password when DSN already contains a password")

    password = stdin.readline().rstrip("\r\n")
    if not password:
        raise ValueError("missing password on stdin for --password")

    return dsn_with_password(dsn, password)


def cmd_source(args: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        if args.source_cmd == "add":
            try:
                resolved_dsn = _resolve_source_add_dsn(
                    args.dsn,
                    use_stdin_password=bool(getattr(args, "password", False)),
                    stdin=sys.stdin,
                )
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2

            source = add_source(
                conn,
                args.name,
                resolved_dsn,
                include_schemas=args.schemas,
                skip_patterns=args.skip_patterns,
            )
            if args.json:
                _print_json(
                    {
                        "name": source.name,
                        "dsn": redact_dsn(source.dsn),
                        "include_schemas": source.include_schemas,
                        "skip_patterns": source.skip_patterns,
                    }
                )
            else:
                print(f"added source '{source.name}'")
            return 0

        if args.source_cmd == "list":
            rows = list_sources(conn)
            payload = [
                {
                    "name": row.name,
                    "dsn": redact_dsn(row.dsn),
                    "include_schemas": row.include_schemas,
                    "skip_patterns": row.skip_patterns,
                    "last_indexed_at": row.last_indexed_at,
                    "last_error": row.last_error,
                }
                for row in rows
            ]
            if args.json:
                _print_json(payload)
            else:
                for row in payload:
                    include_schemas_raw = row["include_schemas"]
                    skip_patterns_raw = row["skip_patterns"]
                    include_schemas = (
                        include_schemas_raw if isinstance(include_schemas_raw, list) else []
                    )
                    skip_patterns = (
                        skip_patterns_raw if isinstance(skip_patterns_raw, list) else []
                    )
                    print(
                        f"{row['name']}\t{row['dsn']}\tinclude_schemas={','.join(include_schemas) or '-'}"
                        f"\tskip_patterns={','.join(skip_patterns) or '-'}"
                        f"\tlast_indexed={row['last_indexed_at'] or '-'}\tlast_error={row['last_error'] or '-'}"
                    )
            return 0

        if args.source_cmd == "rm":
            delete_source(conn, args.name)
            print(f"removed source '{args.name}'")
            return 0

        if args.source_cmd == "rename":
            source = rename_source(conn, args.old_name, args.new_name)
            print(f"renamed source to '{source.name}'")
            return 0
    except (SourceExistsError, SourceNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()

    return 1


def cmd_context(args: argparse.Namespace) -> int:
    conn = _with_db(check_same_thread=not getattr(args, "http", False))
    try:
        if args.context_cmd == "add":
            context = add_context(conn, args.target, args.body)
            if args.json:
                _print_json({"id": context.id, "target_uri": context.target_uri, "body": context.body})
            else:
                print(f"added context {context.id}")
            return 0

        if args.context_cmd == "list":
            rows = list_contexts(conn)
            payload = [
                {"id": row.id, "target_uri": row.target_uri, "body": row.body, "created_at": row.created_at}
                for row in rows
            ]
            if args.json:
                _print_json(payload)
            else:
                for row in payload:
                    print(f"{row['id']}\t{row['target_uri']}\t{row['body']}")
            return 0

        if args.context_cmd == "rm":
            deleted = remove_context(conn, args.key)
            if deleted == 0:
                print("no contexts removed", file=sys.stderr)
                return 2
            print(f"removed {deleted} context(s)")
            return 0

        if args.context_cmd == "generate":
            openai = resolve_openai_settings(
                api_key_override=args.api_key,
                base_url_override=args.base_url,
                model_override=args.model,
            )
            api_key = str(openai.api_key or "").strip()
            if not api_key:
                print(
                    "missing OpenAI API key "
                    "(set QPG_OPENAI_API_KEY/OPENAI_API_KEY or pass --api-key)",
                    file=sys.stderr,
                )
                return 2
            base_url = str(openai.base_url).strip()
            model = str(openai.model).strip()
            if not model:
                print("model must not be empty", file=sys.stderr)
                return 2
            if args.limit is not None and args.limit <= 0:
                print("--limit must be a positive integer", file=sys.stderr)
                return 2

            candidates = list_table_context_candidates(
                conn,
                source=args.source,
                schema=args.schema,
                limit=args.limit,
                include_with_existing=True,
            )
            if not candidates:
                if args.json:
                    _print_json(
                        {
                            "model": model,
                            "generated": 0,
                            "skipped_existing": 0,
                            "skipped_inference": 0,
                            "dry_run": bool(args.dry_run),
                            "results": [],
                        }
                    )
                else:
                    print("no table objects found")
                return 0

            generated = 0
            skipped_existing = 0
            skipped_inference = 0
            results: list[dict[str, Any]] = []
            for candidate in candidates:
                if candidate.has_existing_context and not args.overwrite:
                    skipped_existing += 1
                    results.append({"target_uri": candidate.target_uri, "status": "skipped_existing"})
                    if not args.json:
                        print(f"skipped existing context: {candidate.target_uri}")
                    continue

                generated_result = generate_table_context_text(
                    conn,
                    candidate,
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                )
                if isinstance(generated_result, ContextGenerationResult):
                    context_text = (
                        generated_result.context_text.strip()
                        if isinstance(generated_result.context_text, str)
                        else None
                    )
                    skip_reason = (
                        generated_result.reason.strip()
                        if isinstance(generated_result.reason, str)
                        else None
                    )
                elif isinstance(generated_result, str):
                    context_text = generated_result.strip() or None
                    skip_reason = None
                else:
                    context_text = None
                    skip_reason = None

                if not args.dry_run and args.overwrite:
                    conn.execute("DELETE FROM contexts WHERE target_uri = ?", (candidate.target_uri,))

                if context_text:
                    if not args.dry_run:
                        add_context(conn, candidate.target_uri, context_text)

                    generated += 1
                    results.append(
                        {
                            "target_uri": candidate.target_uri,
                            "status": "generated",
                            "body": context_text,
                        }
                    )
                    if not args.json:
                        if args.dry_run:
                            print(f"generated (dry-run): {candidate.target_uri}")
                        else:
                            print(f"generated context: {candidate.target_uri}")
                    continue

                skipped_inference += 1
                result_payload = {
                    "target_uri": candidate.target_uri,
                    "status": "skipped_inference",
                }
                if skip_reason:
                    result_payload["reason"] = skip_reason
                results.append(result_payload)
                if not args.json:
                    if skip_reason:
                        print(f"skipped inference: {candidate.target_uri} ({skip_reason})")
                    else:
                        print(f"skipped inference: {candidate.target_uri}")

            payload = {
                "model": model,
                "generated": generated,
                "skipped_existing": skipped_existing,
                "skipped_inference": skipped_inference,
                "dry_run": bool(args.dry_run),
                "results": results,
            }
            if args.json:
                _print_json(payload)
            else:
                print(
                    f"done: generated={generated} skipped_existing={skipped_existing} "
                    f"skipped_inference={skipped_inference} "
                    f"dry_run={bool(args.dry_run)}"
                )
            return 0
    except (InvalidContextTarget, ContextSourceNotFoundError, ContextGenerationError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()

    return 1


def _run_privilege_check(
    conn: Any,
    *,
    allow_extra_privileges: bool,
    allow_execute: bool,
    json_output: bool,
) -> int:
    report = check_privileges(conn, allow_execute=allow_execute)
    if json_output:
        _print_json(
            {
                "current_user": report.current_user,
                "roles": report.inherited_roles,
                "passed": report.passed,
                "violations": [
                    {
                        "role": item.role,
                        "scope": item.scope,
                        "object": item.object_name,
                        "privilege": item.privilege,
                    }
                    for item in report.violations
                ],
            }
        )
    else:
        print(format_privilege_report(report))

    if report.passed or allow_extra_privileges:
        return 0
    return 3


def cmd_auth_check(args: argparse.Namespace) -> int:
    conn = _with_db(check_same_thread=not args.http)
    try:
        try:
            sources = _collect_sources(conn, args.source)
        except SourceNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not sources:
            print("no sources configured", file=sys.stderr)
            return 2

        exit_code = 0
        for source in sources:
            print(f"== auth check: {source.name} ==")
            try:
                with connect_pg(source.dsn) as pg_conn:
                    code = _run_privilege_check(
                        pg_conn,
                        allow_extra_privileges=args.allow_extra_privileges,
                        allow_execute=args.allow_execute,
                        json_output=args.json,
                    )
            except PostgresDependencyError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except Exception as exc:
                print(f"connection failed for '{source.name}': {exc}", file=sys.stderr)
                exit_code = 4
                continue

            if code != 0:
                exit_code = code
        return exit_code
    finally:
        conn.close()


def cmd_update(args: argparse.Namespace) -> int:
    conn = _with_db()
    exit_code = 0
    try:
        try:
            sources = _collect_sources(conn, args.source)
        except SourceNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not sources:
            print("no sources configured", file=sys.stderr)
            return 2

        try:
            require_vector_model()
        except VectorModelNotInitializedError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        ctx_rows = list_contexts(conn)

        for source in sources:
            print(f"== update: {source.name} ==")
            try:
                with connect_pg(source.dsn) as pg_conn:
                    bundle = introspect_schema(pg_conn, include_functions=not args.skip_functions)
                    bundle = apply_filters(
                        bundle,
                        include_schemas=source.include_schemas,
                        skip_patterns=source.skip_patterns,
                    )
            except PostgresDependencyError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            except Exception as exc:
                message = f"failed introspection: {exc}"
                mark_source_error(conn, source.id, message)
                print(message, file=sys.stderr)
                exit_code = 4
                continue

            for warning in bundle.warnings:
                print(f"warning: {warning}", file=sys.stderr)

            try:
                stats = update_source_index(conn, source=source, bundle=bundle, contexts=ctx_rows)
                mark_source_indexed(conn, source.id)
                print(
                    "indexed "
                    f"objects={stats.objects} columns={stats.columns} "
                    f"constraints={stats.constraints} indexes={stats.indexes} "
                    f"dependencies={stats.dependencies} vectors={stats.vectors}"
                )
            except Exception as exc:
                message = f"failed indexing: {exc}"
                mark_source_error(conn, source.id, message)
                print(message, file=sys.stderr)
                exit_code = 4
                continue

        return exit_code
    finally:
        conn.close()


def cmd_init(args: argparse.Namespace) -> int:
    try:
        model_dir = init_vector_model()
    except Exception as exc:
        print(f"init failed: {exc}", file=sys.stderr)
        return 2

    payload = {
        "models_dir": str(model_dir.parent),
        "model_path": str(model_dir),
    }
    if args.json:
        _print_json(payload)
    else:
        print(f"initialized model: {model_dir}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    openai = resolve_openai_settings()
    yaml_path = config_yaml_path()
    payload = {
        "config_yaml_path": str(yaml_path),
        "config_yaml_exists": yaml_path.exists(),
        "openai": {
            "api_key_configured": bool(openai.api_key),
            "api_key_redacted": redact_secret(openai.api_key),
            "model": openai.model,
            "base_url": openai.base_url,
        }
    }
    if args.json:
        _print_json(payload)
    else:
        openai_payload = payload["openai"]
        print(f"config_yaml: {payload['config_yaml_path']}")
        print(f"config_yaml_exists: {payload['config_yaml_exists']}")
        if openai_payload["api_key_configured"]:
            print(f"openai_api_key: set ({openai_payload['api_key_redacted']})")
        else:
            print("openai_api_key: unset")
        print(f"openai_model: {openai_payload['model']}")
        print(f"openai_base_url: {openai_payload['base_url']}")
    return 0


def _status_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = list_sources(conn)
    total_objects = conn.execute("SELECT COUNT(*) AS count FROM db_objects").fetchone()["count"]
    by_kind_rows = conn.execute(
        """
        SELECT object_type, COUNT(*) AS count
        FROM db_objects
        GROUP BY object_type
        ORDER BY count DESC, object_type ASC
        """
    ).fetchall()

    source_rows = []
    for source in sources:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM db_objects WHERE source_id = ?",
            (source.id,),
        ).fetchone()["count"]
        source_rows.append(
            {
                "name": source.name,
                "dsn": redact_dsn(source.dsn),
                "include_schemas": source.include_schemas,
                "skip_patterns": source.skip_patterns,
                "objects": count,
                "last_indexed_at": source.last_indexed_at,
                "last_error": source.last_error,
            }
        )

    return {
        "source_count": len(sources),
        "object_count": total_objects,
        "sources": source_rows,
        "by_kind": [{"kind": row["object_type"], "count": row["count"]} for row in by_kind_rows],
    }


def cmd_status(args: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        payload = _status_payload(conn)
        if args.json:
            _print_json(payload)
            return 0

        print(f"sources={payload['source_count']} objects={payload['object_count']}")
        for source in payload["sources"]:
            print(
                f"{source['name']}\tobjects={source['objects']}\t"
                f"last_indexed={source['last_indexed_at'] or '-'}\t"
                f"last_error={source['last_error'] or '-'}"
            )
        return 0
    finally:
        conn.close()


def cmd_cleanup(_: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        conn.execute(
            """
            DELETE FROM llm_cache
            WHERE expires_at IS NOT NULL AND expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        )
        conn.execute("VACUUM")
        conn.commit()
        print("cleanup complete")
        return 0
    finally:
        conn.close()


def cmd_repair(_: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        row = conn.execute("PRAGMA quick_check").fetchone()
        if row is None or row[0] != "ok":
            print("sqlite integrity check failed", file=sys.stderr)
            return 4
        rebuild_fts(conn)
        conn.commit()
        print("repair complete")
        return 0
    finally:
        conn.close()


def _search_common(
    conn: sqlite3.Connection,
    *,
    query: str,
    source: str | None,
    schema: str | None,
    kind: str | None,
    limit: int,
    min_score: float | None,
) -> list[dict[str, Any]]:
    return search_fts(
        conn,
        query=query,
        source=source,
        schema=schema,
        kind=kind,
        limit=limit,
        min_score=min_score,
    )


def cmd_search(args: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        rows = _search_common(
            conn,
            query=args.text,
            source=args.source,
            schema=args.schema,
            kind=args.kind,
            limit=args.n if not args.all else 10_000,
            min_score=args.min_score,
        )

        if args.json:
            _print_json(rows)
        elif args.files:
            _format_rows(rows, files=True)
        else:
            _format_search_rows_detailed(conn, rows)
        return 0
    finally:
        conn.close()


def cmd_vsearch(args: argparse.Namespace) -> int:
    try:
        require_vector_model()
    except VectorModelNotInitializedError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    conn = _with_db()
    try:
        rows = vector_search(
            conn,
            query=args.text,
            source=args.source,
            schema=args.schema,
            kind=args.kind,
            limit=args.n if not args.all else 10_000,
            min_score=args.min_score,
        )
        if args.json:
            _print_json(rows)
        else:
            _format_rows(rows, files=args.files)
        return 0
    finally:
        conn.close()


def cmd_query(args: argparse.Namespace) -> int:
    try:
        require_vector_model()
    except VectorModelNotInitializedError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    conn = _with_db()
    try:
        expanded = expand_query(args.text)
        fts_lists = [
            _search_common(
                conn,
                query=text,
                source=args.source,
                schema=args.schema,
                kind=args.kind,
                limit=(args.n if not args.all else 10_000),
                min_score=None,
            )
            for text in expanded
        ]

        ranked_lists = fts_lists
        ranked_lists.append(
            vector_search(
                conn,
                query=args.text,
                source=args.source,
                schema=args.schema,
                kind=args.kind,
                limit=(args.n if not args.all else 10_000),
                min_score=None,
            )
        )

        fused = reciprocal_rank_fusion(ranked_lists, k=60, top_rank_bonus=0.02)
        for idx, row in enumerate(fused, start=1):
            row["position_bonus"] = 1.0 / (idx + 1)
            row["score"] = row["rrf_score"] + 0.1 * row["position_bonus"]

        fused.sort(key=lambda item: item["score"], reverse=True)
        try:
            fused = rerank_with_hook(args.text, fused)
        except RerankHookError as exc:
            print(f"rerank hook failed: {exc}", file=sys.stderr)

        if args.min_score is not None:
            fused = [row for row in fused if float(row.get("score", 0.0)) >= args.min_score]

        if not args.all:
            fused = fused[: args.n]

        if args.json:
            _print_json(fused)
        else:
            _format_rows(fused, files=args.files)
        return 0
    finally:
        conn.close()


def cmd_get(args: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        payload = get_object_payload(conn, args.ref, source=args.source)
        if args.json:
            _print_json(payload)
            return 0

        print(f"id: {payload['object_id']}")
        print(f"source: {payload['source']}")
        print(f"kind: {payload['kind']}")
        print(f"name: {payload['fqname']}")
        if payload["comment"]:
            print(f"comment: {payload['comment']}")
        if payload["context"]:
            print(f"context: {payload['context']}")
        if payload["columns"]:
            print("columns:")
            for column in payload["columns"]:
                nullable = "NULL" if column["nullable"] else "NOT NULL"
                print(f"- {column['ordinal']}: {column['name']} {column['type']} {nullable}")
        if payload["constraints"]:
            print("constraints:")
            for constraint in payload["constraints"]:
                print(f"- {constraint['name']} ({constraint['type']}): {constraint['definition']}")
        if payload["indexes"]:
            print("indexes:")
            for index in payload["indexes"]:
                print(f"- {index['name']}: {index['definition']}")
        return 0
    except ObjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        conn.close()


def _schema_objects_query(source: str | None = None) -> tuple[str, list[Any]]:
    where: list[str] = []
    params: list[Any] = []
    if source:
        where.append("s.name = ?")
        params.append(source)
    where_clause = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT o.id AS object_id,
               o.fqname,
               o.object_type,
               o.schema_name,
               o.object_name,
               s.name AS source_name
        FROM db_objects o
        JOIN sources s ON s.id = o.source_id
        {where_clause}
        ORDER BY s.name, o.schema_name, o.object_type, o.object_name
    """
    return sql, params


def cmd_schema(args: argparse.Namespace) -> int:
    conn = _with_db()
    try:
        try:
            if args.source:
                _ = get_source(conn, args.source)
        except SourceNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        sql, params = _schema_objects_query(args.source)
        rows = conn.execute(sql, params).fetchall()

        if args.json:
            payload: list[dict[str, Any]] = []
            for row in rows:
                item = get_object_payload(conn, row["fqname"], source=row["source_name"])
                item["definition"] = _definition_text(item)
                item["description"] = _short_description(item)
                payload.append(item)
            _print_json(payload)
            return 0

        if not rows:
            print("no schema objects indexed")
            return 0

        current_source: str | None = None
        for row in rows:
            source_name = str(row["source_name"])
            if current_source != source_name:
                if current_source is not None:
                    print()
                print(f"== source: {source_name} ==")
                current_source = source_name

            item = get_object_payload(conn, row["fqname"], source=source_name)
            print(f"\n-- {item['fqname']} ({item['kind']})")
            print(f"-- { _short_description(item) }")
            print(_definition_text(item))
        return 0
    finally:
        conn.close()


def _write_pid_file(pid_file: Path, pid: int) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid), encoding="utf-8")


def _read_pid_file(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    text = pid_file.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _mcp_stop(paths_pid: Path) -> int:
    pid = _read_pid_file(paths_pid)
    if pid is None:
        print("mcp daemon is not running", file=sys.stderr)
        return 2

    try:
        os_kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        paths_pid.unlink(missing_ok=True)
        print("mcp daemon pid file removed (process not found)")
        return 0

    paths_pid.unlink(missing_ok=True)
    print(f"stopped mcp daemon (pid={pid})")
    return 0


def os_kill(pid: int, sig: signal.Signals) -> None:
    import os

    os.kill(pid, sig)


def cmd_mcp(args: argparse.Namespace) -> int:
    paths = ensure_dirs(get_paths())

    if args.mcp_cmd == "stop":
        return _mcp_stop(paths.mcp_pid_file)

    if args.http and args.daemon:
        existing = _read_pid_file(paths.mcp_pid_file)
        if existing is not None:
            print(f"mcp daemon already running (pid={existing})", file=sys.stderr)
            return 2

        cmd = [
            sys.executable,
            "-m",
            "qpg.cli",
            "mcp",
            "--http",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _write_pid_file(paths.mcp_pid_file, proc.pid)
        print(f"started mcp daemon pid={proc.pid} host={args.host} port={args.port}")
        print("codex/claude-code integration: configure MCP command as `qpg mcp --http --host "
              f"{args.host} --port {args.port}`")
        return 0

    conn = _with_db(check_same_thread=not args.http)
    try:
        if args.http:
            print(f"qpg MCP HTTP server listening on http://{args.host}:{args.port}")
            print("health endpoint: GET /health, rpc endpoint: POST /mcp")
            print("codex/claude-code integration: set MCP server command to "
                  f"`qpg mcp --http --host {args.host} --port {args.port}`")
            return serve_http(conn, host=args.host, port=args.port)
        print("qpg MCP stdio server started", file=sys.stderr)
        print("codex/claude-code integration: set MCP server command to `qpg mcp`", file=sys.stderr)
        return serve_stdio(conn)
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qpg", description="Query PostgreSQL schema metadata")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    init_parser = subparsers.add_parser("init", help="download and initialize local vector model assets")
    init_parser.add_argument("--json", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    config_parser = subparsers.add_parser("config", help="show effective configuration")
    config_parser.add_argument("--json", action="store_true")
    config_parser.set_defaults(func=cmd_config)

    source_parser = subparsers.add_parser("source", help="manage PostgreSQL sources")
    source_sub = source_parser.add_subparsers(dest="source_cmd", required=True)

    source_add = source_sub.add_parser("add", help="add a source")
    source_add.add_argument("dsn")
    source_add.add_argument("--name", required=True)
    source_add.add_argument(
        "--password",
        action="store_true",
        help="read PostgreSQL password from stdin and inject into DSN (first line)",
    )
    source_add.add_argument(
        "--schema",
        dest="schemas",
        action="append",
        default=[],
        help="include only this schema (repeatable)",
    )
    source_add.add_argument(
        "--skip-pattern",
        dest="skip_patterns",
        action="append",
        default=[],
        help="skip objects matching glob pattern (repeatable, matches fqname or object name)",
    )
    source_add.add_argument("--json", action="store_true")
    source_add.set_defaults(func=cmd_source)

    source_list = source_sub.add_parser("list", help="list sources")
    source_list.add_argument("--json", action="store_true")
    source_list.set_defaults(func=cmd_source)

    source_rm = source_sub.add_parser("rm", help="remove a source")
    source_rm.add_argument("name")
    source_rm.set_defaults(func=cmd_source)

    source_rename = source_sub.add_parser("rename", help="rename a source")
    source_rename.add_argument("old_name")
    source_rename.add_argument("new_name")
    source_rename.set_defaults(func=cmd_source)

    context_parser = subparsers.add_parser("context", help="manage context entries")
    context_sub = context_parser.add_subparsers(dest="context_cmd", required=True)

    context_add = context_sub.add_parser("add", help="add a context")
    context_add.add_argument("target")
    context_add.add_argument("body")
    context_add.add_argument("--json", action="store_true")
    context_add.set_defaults(func=cmd_context)

    context_list = context_sub.add_parser("list", help="list contexts")
    context_list.add_argument("--json", action="store_true")
    context_list.set_defaults(func=cmd_context)

    context_rm = context_sub.add_parser("rm", help="remove context by id or target uri")
    context_rm.add_argument("key")
    context_rm.set_defaults(func=cmd_context)

    context_generate = context_sub.add_parser(
        "generate",
        help="generate table contexts via OpenAI from indexed schema metadata",
    )
    context_generate.add_argument("--source", help="limit generation to a source name")
    context_generate.add_argument("--schema", help="limit generation to a schema name")
    context_generate.add_argument("--limit", type=int, help="max number of tables to process")
    context_generate.add_argument("--model", help="OpenAI model (falls back to QPG_OPENAI_MODEL/OPENAI_MODEL)")
    context_generate.add_argument(
        "--api-key",
        help="OpenAI API key (falls back to QPG_OPENAI_API_KEY/OPENAI_API_KEY)",
    )
    context_generate.add_argument(
        "--base-url",
        help=(
            "OpenAI base URL "
            "(falls back to QPG_OPENAI_BASE_URL/OPENAI_BASE_URL or https://api.openai.com/v1)"
        ),
    )
    context_generate.add_argument("--overwrite", action="store_true")
    context_generate.add_argument("--dry-run", action="store_true")
    context_generate.add_argument("--json", action="store_true")
    context_generate.set_defaults(func=cmd_context)

    auth_parser = subparsers.add_parser("auth", help="authentication and privilege checks")
    auth_sub = auth_parser.add_subparsers(dest="auth_cmd", required=True)
    auth_check = auth_sub.add_parser("check", help="check role privileges")
    auth_check.add_argument("--source")
    auth_check.add_argument("--allow-extra-privileges", action="store_true")
    auth_check.add_argument("--allow-execute", action="store_true")
    auth_check.add_argument("--json", action="store_true")
    auth_check.set_defaults(func=cmd_auth_check)

    update_parser = subparsers.add_parser("update", help="introspect and refresh the local index")
    update_parser.add_argument("--source")
    update_parser.add_argument("--allow-extra-privileges", action="store_true")
    update_parser.add_argument("--allow-execute", action="store_true")
    update_parser.add_argument("--skip-functions", action="store_true")
    update_parser.set_defaults(func=cmd_update)

    status_parser = subparsers.add_parser("status", help="show index status")
    status_parser.add_argument("--json", action="store_true")
    status_parser.set_defaults(func=cmd_status)

    cleanup_parser = subparsers.add_parser("cleanup", help="cleanup local cache")
    cleanup_parser.set_defaults(func=cmd_cleanup)

    repair_parser = subparsers.add_parser("repair", help="repair local index")
    repair_parser.set_defaults(func=cmd_repair)

    for command_name, handler in (("search", cmd_search), ("vsearch", cmd_vsearch), ("query", cmd_query)):
        search_parser = subparsers.add_parser(command_name, help=f"{command_name} local index")
        search_parser.add_argument("text")
        search_parser.add_argument("--json", action="store_true")
        search_parser.add_argument("--files", action="store_true")
        search_parser.add_argument("-n", type=int, default=10)
        search_parser.add_argument("--all", action="store_true")
        search_parser.add_argument("--min-score", type=float)
        search_parser.add_argument("--schema")
        search_parser.add_argument(
            "--kind",
            choices=["table", "column", "index", "constraint", "view", "function", "procedure", "schema", "extension"],
        )
        search_parser.add_argument("--source")
        search_parser.set_defaults(func=handler)

    get_parser = subparsers.add_parser("get", help="get object details by name or id")
    get_parser.add_argument("ref")
    get_parser.add_argument("--source")
    get_parser.add_argument("--json", action="store_true")
    get_parser.set_defaults(func=cmd_get)

    schema_parser = subparsers.add_parser("schema", help="print indexed schema objects and definitions")
    schema_parser.add_argument("--source")
    schema_parser.add_argument("--json", action="store_true")
    schema_parser.set_defaults(func=cmd_schema)

    mcp_parser = subparsers.add_parser("mcp", help="run MCP server")
    mcp_parser.add_argument("--http", action="store_true")
    mcp_parser.add_argument("--daemon", action="store_true")
    mcp_parser.add_argument("--host", default="127.0.0.1")
    mcp_parser.add_argument("--port", type=int, default=8765)
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_cmd")
    mcp_stop = mcp_sub.add_parser("stop", help="stop MCP HTTP daemon")
    mcp_stop.set_defaults(func=cmd_mcp)
    mcp_parser.set_defaults(func=cmd_mcp)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return int(func(args))


def app() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    app()
