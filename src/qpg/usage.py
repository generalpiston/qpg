from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qpg.config import Paths
from qpg.context_usage import IndexUsageInputError, IndexUsageRecord, parse_index_usage_records
from qpg.db_pg import fetch_all, fetch_one


class UsageSnapshotError(RuntimeError):
    pass


def usage_snapshot_path(paths: Paths, source: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", source).strip("._")
    if not safe_name:
        safe_name = "source"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    return paths.state_dir / "usage" / f"{safe_name}-{digest}.jsonl"


def load_usage_snapshot_records(paths: Paths, *, source: str) -> list[IndexUsageRecord]:
    path = usage_snapshot_path(paths, source)
    if not path.exists():
        raise UsageSnapshotError(
            f"usage snapshot not found for source '{source}': {path}. "
            f"run `qpg usage refresh --source {source}` first"
        )

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageSnapshotError(f"unable to read usage snapshot '{path}': {exc}") from exc

    try:
        return parse_index_usage_records(raw_text)
    except IndexUsageInputError as exc:
        raise UsageSnapshotError(f"invalid usage snapshot '{path}': {exc}") from exc


def write_usage_snapshot_records(path: Path, records: list[IndexUsageRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for record in records:
        payload: dict[str, Any] = {
            "schema": record.schema,
            "table": record.table,
            "index": record.index,
            "unused_days": record.unused_days,
        }
        if record.source:
            payload["source"] = record.source
        if record.as_of:
            payload["as_of"] = record.as_of
        if record.idx_scan is not None:
            payload["idx_scan"] = record.idx_scan
        rows.append(json.dumps(payload, sort_keys=True))

    text = "\n".join(rows)
    if rows:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def collect_index_usage_records(pg_conn: Any, *, source_name: str) -> list[IndexUsageRecord]:
    supports_last_idx_scan = _supports_last_idx_scan(pg_conn)
    as_of = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    if supports_last_idx_scan:
        rows = fetch_all(
            pg_conn,
            """
            SELECT
                idx.schemaname AS schema_name,
                idx.relname AS table_name,
                idx.indexrelname AS index_name,
                idx.idx_scan AS idx_scan,
                EXTRACT(
                    EPOCH FROM (
                        CURRENT_TIMESTAMP
                        - COALESCE(idx.last_idx_scan, db.stats_reset, CURRENT_TIMESTAMP)
                    )
                ) / 86400.0 AS unused_days
            FROM pg_stat_user_indexes idx
            LEFT JOIN LATERAL (
                SELECT stats_reset
                FROM pg_stat_database
                WHERE datname = current_database()
            ) db ON true
            ORDER BY idx.schemaname, idx.relname, idx.indexrelname
            """,
        )
    else:
        rows = fetch_all(
            pg_conn,
            """
            SELECT
                idx.schemaname AS schema_name,
                idx.relname AS table_name,
                idx.indexrelname AS index_name,
                idx.idx_scan AS idx_scan,
                CASE
                    WHEN idx.idx_scan = 0
                    THEN EXTRACT(
                        EPOCH FROM (
                            CURRENT_TIMESTAMP
                            - COALESCE(db.stats_reset, CURRENT_TIMESTAMP)
                        )
                    ) / 86400.0
                    ELSE 0.0
                END AS unused_days
            FROM pg_stat_user_indexes idx
            LEFT JOIN LATERAL (
                SELECT stats_reset
                FROM pg_stat_database
                WHERE datname = current_database()
            ) db ON true
            ORDER BY idx.schemaname, idx.relname, idx.indexrelname
            """,
        )

    records: list[IndexUsageRecord] = []
    for row in rows:
        schema_name = str(row.get("schema_name", "")).strip()
        table_name = str(row.get("table_name", "")).strip()
        index_name = str(row.get("index_name", "")).strip()
        if not schema_name or not table_name or not index_name:
            continue

        idx_scan_raw = row.get("idx_scan")
        idx_scan = float(idx_scan_raw) if isinstance(idx_scan_raw, int | float) else None

        unused_days_raw = row.get("unused_days")
        if not isinstance(unused_days_raw, int | float):
            continue
        unused_days = max(float(unused_days_raw), 0.0)

        records.append(
            IndexUsageRecord(
                schema=schema_name,
                table=table_name,
                index=index_name,
                unused_days=unused_days,
                as_of=as_of,
                source=source_name,
                idx_scan=idx_scan,
            )
        )
    return records


def _supports_last_idx_scan(pg_conn: Any) -> bool:
    row = fetch_one(
        pg_conn,
        """
        SELECT 1 AS has_column
        FROM information_schema.columns
        WHERE table_schema = 'pg_catalog'
          AND table_name = 'pg_stat_user_indexes'
          AND column_name = 'last_idx_scan'
        LIMIT 1
        """,
    )
    return row is not None
