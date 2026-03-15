from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from qpg.contexts import ContextSourceNotFoundError

INDEX_USAGE_MANAGED_PREFIX = "[qpg-managed:index-usage]"


class IndexUsageInputError(ValueError):
    pass


@dataclass(frozen=True)
class IndexUsageRecord:
    schema: str
    table: str
    index: str
    unused_days: float
    as_of: str | None = None
    source: str | None = None
    idx_scan: float | None = None


@dataclass(frozen=True)
class IndexUsageApplyResult:
    applied: int
    skipped_below_threshold: int
    skipped_missing_index: int
    skipped_source_mismatch: int
    removed_managed: int
    results: list[dict[str, Any]]


def load_index_usage_records(input_path: str, *, stdin: TextIO) -> list[IndexUsageRecord]:
    if input_path == "-":
        raw_text = stdin.read()
    else:
        try:
            raw_text = Path(input_path).read_text(encoding="utf-8")
        except OSError as exc:
            raise IndexUsageInputError(f"unable to read input file '{input_path}': {exc}") from exc
    return parse_index_usage_records(raw_text)


def parse_index_usage_records(raw_text: str) -> list[IndexUsageRecord]:
    content = raw_text.strip()
    if not content:
        return []

    if content.startswith("["):
        return _parse_json_array(content)
    return _parse_json_lines(raw_text)


def _parse_json_array(content: str) -> list[IndexUsageRecord]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise IndexUsageInputError(f"invalid JSON array input: {exc}") from exc

    if not isinstance(payload, list):
        raise IndexUsageInputError("index usage input must be a JSON array or JSONL stream")

    records: list[IndexUsageRecord] = []
    for idx, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise IndexUsageInputError(f"array item {idx} must be a JSON object")
        records.append(_record_from_payload(item, location=f"array item {idx}"))
    return records


def _parse_json_lines(raw_text: str) -> list[IndexUsageRecord]:
    records: list[IndexUsageRecord] = []
    for lineno, raw_line in enumerate(raw_text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IndexUsageInputError(f"invalid JSON on line {lineno}: {exc}") from exc
        if not isinstance(payload, dict):
            raise IndexUsageInputError(f"line {lineno} must contain a JSON object")
        records.append(_record_from_payload(payload, location=f"line {lineno}"))
    return records


def _record_from_payload(payload: dict[str, Any], *, location: str) -> IndexUsageRecord:
    schema = _require_text(payload, keys=("schema",), location=location)
    table = _require_text(payload, keys=("table", "table_name"), location=location)
    index = _require_text(payload, keys=("index", "index_name"), location=location)
    unused_days = _require_number(payload, keys=("unused_days",), location=location)

    as_of = _optional_text(payload, keys=("as_of", "snapshot_at", "observed_at"))
    source = _optional_text(payload, keys=("source", "source_name"))
    idx_scan = _optional_number(payload, keys=("idx_scan",))

    return IndexUsageRecord(
        schema=schema,
        table=table,
        index=index,
        unused_days=unused_days,
        as_of=as_of,
        source=source,
        idx_scan=idx_scan,
    )


def _require_text(payload: dict[str, Any], *, keys: tuple[str, ...], location: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed:
                return trimmed
        elif value is not None:
            raise IndexUsageInputError(f"{location}: '{key}' must be a non-empty string")

    joined = ", ".join(keys)
    raise IndexUsageInputError(f"{location}: missing required field ({joined})")


def _optional_text(payload: dict[str, Any], *, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise IndexUsageInputError(f"'{key}' must be a string when present")
        trimmed = value.strip()
        if trimmed:
            return trimmed
    return None


def _require_number(payload: dict[str, Any], *, keys: tuple[str, ...], location: str) -> float:
    value = _optional_number(payload, keys=keys)
    if value is None:
        joined = ", ".join(keys)
        raise IndexUsageInputError(f"{location}: missing required numeric field ({joined})")
    return value


def _optional_number(payload: dict[str, Any], *, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            raise IndexUsageInputError(f"'{key}' must be numeric when present")
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError as exc:
                raise IndexUsageInputError(f"'{key}' must be numeric when present") from exc
        raise IndexUsageInputError(f"'{key}' must be numeric when present")
    return None


def apply_index_usage_contexts(
    conn: sqlite3.Connection,
    *,
    source: str,
    records: list[IndexUsageRecord],
    unused_days_threshold: float,
    replace_managed: bool,
    dry_run: bool,
) -> IndexUsageApplyResult:
    if unused_days_threshold < 0:
        raise IndexUsageInputError("--unused-days must be >= 0")

    source_exists = conn.execute("SELECT 1 FROM sources WHERE name = ?", (source,)).fetchone()
    if source_exists is None:
        raise ContextSourceNotFoundError(f"source '{source}' not found")

    managed_like = f"{INDEX_USAGE_MANAGED_PREFIX}%"
    source_scope = (f"qpg://{source}", f"qpg://{source}/%", f"qpg://{source}#%")

    removed_managed = 0
    if replace_managed:
        if dry_run:
            row = conn.execute(
                """
                SELECT COUNT(*) AS c
                FROM contexts
                WHERE body LIKE ?
                  AND (
                    target_uri = ?
                    OR target_uri LIKE ?
                    OR target_uri LIKE ?
                  )
                """,
                (managed_like, *source_scope),
            ).fetchone()
            removed_managed = int(row["c"]) if row is not None else 0
        else:
            cursor = conn.execute(
                """
                DELETE FROM contexts
                WHERE body LIKE ?
                  AND (
                    target_uri = ?
                    OR target_uri LIKE ?
                    OR target_uri LIKE ?
                  )
                """,
                (managed_like, *source_scope),
            )
            removed_managed = int(cursor.rowcount)

    applied = 0
    skipped_below_threshold = 0
    skipped_missing_index = 0
    skipped_source_mismatch = 0
    results: list[dict[str, Any]] = []

    for record in records:
        if record.source and record.source != source:
            skipped_source_mismatch += 1
            results.append(
                {
                    "status": "skipped_source_mismatch",
                    "source": record.source,
                    "schema": record.schema,
                    "table": record.table,
                    "index": record.index,
                }
            )
            continue

        if record.unused_days < unused_days_threshold:
            skipped_below_threshold += 1
            results.append(
                {
                    "status": "skipped_below_threshold",
                    "schema": record.schema,
                    "table": record.table,
                    "index": record.index,
                    "unused_days": record.unused_days,
                }
            )
            continue

        object_name = f"{record.table}.{record.index}"
        row = conn.execute(
            """
            SELECT o.id, o.fqname
            FROM db_objects o
            JOIN sources s ON s.id = o.source_id
            WHERE s.name = ?
              AND o.object_type = 'index'
              AND o.schema_name = ?
              AND o.object_name = ?
            LIMIT 1
            """,
            (source, record.schema, object_name),
        ).fetchone()

        if row is None:
            skipped_missing_index += 1
            results.append(
                {
                    "status": "skipped_missing_index",
                    "schema": record.schema,
                    "table": record.table,
                    "index": record.index,
                }
            )
            continue

        object_id = str(row["id"])
        fqname = str(row["fqname"])
        target_uri = f"qpg://{source}#{object_id}"
        body = _format_index_usage_context(record=record, fqname=fqname)

        if not dry_run:
            conn.execute(
                "DELETE FROM contexts WHERE target_uri = ? AND body LIKE ?",
                (target_uri, managed_like),
            )
            conn.execute(
                """
                INSERT INTO contexts(target_uri, body)
                VALUES(?, ?)
                """,
                (target_uri, body),
            )

        applied += 1
        results.append(
            {
                "status": "applied",
                "target_uri": target_uri,
                "fqname": fqname,
                "unused_days": record.unused_days,
                "as_of": record.as_of,
            }
        )

    if not dry_run and (replace_managed or applied > 0):
        conn.commit()

    return IndexUsageApplyResult(
        applied=applied,
        skipped_below_threshold=skipped_below_threshold,
        skipped_missing_index=skipped_missing_index,
        skipped_source_mismatch=skipped_source_mismatch,
        removed_managed=removed_managed,
        results=results,
    )


def _format_index_usage_context(*, record: IndexUsageRecord, fqname: str) -> str:
    unused_days_text = _format_days(record.unused_days)
    as_of_suffix = f" as of {record.as_of}" if record.as_of else ""
    scan_suffix = ""
    if record.idx_scan is not None:
        scan_suffix = f" Observed idx_scan={_format_days(record.idx_scan)}."

    return "\n".join(
        [
            INDEX_USAGE_MANAGED_PREFIX,
            (
                f"Operational signal: index '{fqname}' appears unused for {unused_days_text} days"
                f"{as_of_suffix} based on supplied usage statistics.{scan_suffix}"
            ),
            "Validate across representative workload windows before considering index removal.",
        ]
    )


def _format_days(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
