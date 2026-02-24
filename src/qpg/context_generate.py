from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib import error, request


@dataclass(frozen=True)
class ColumnSummary:
    name: str
    data_type: str
    nullable: bool
    default_expr: str | None
    comment: str | None


@dataclass(frozen=True)
class TableContextCandidate:
    source_name: str
    object_id: str
    fqname: str
    schema_name: str | None
    object_name: str
    definition: str | None
    comment: str | None
    columns: list[ColumnSummary]
    has_existing_context: bool

    @property
    def target_uri(self) -> str:
        return f"qpg://{self.source_name}/{self.fqname}"


class ContextGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContextGenerationResult:
    context_text: str | None
    reason: str | None = None


def list_table_context_candidates(
    conn: sqlite3.Connection,
    *,
    source: str | None = None,
    schema: str | None = None,
    limit: int | None = None,
    include_with_existing: bool = False,
) -> list[TableContextCandidate]:
    filters = ["o.object_type = 'table'"]
    params: list[Any] = []
    if source:
        filters.append("s.name = ?")
        params.append(source)
    if schema:
        filters.append("o.schema_name = ?")
        params.append(schema)

    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT ?"
        params.append(int(limit))

    rows = conn.execute(
        f"""
        SELECT
            s.name AS source_name,
            o.id AS object_id,
            o.fqname AS fqname,
            o.schema_name AS schema_name,
            o.object_name AS object_name,
            o.definition AS definition,
            o.comment AS comment
        FROM db_objects o
        JOIN sources s ON s.id = o.source_id
        WHERE {' AND '.join(filters)}
        ORDER BY s.name, o.schema_name, o.object_name
        {limit_clause}
        """,
        params,
    ).fetchall()

    candidates: list[TableContextCandidate] = []
    for row in rows:
        fqname = str(row["fqname"])
        target_uri = f"qpg://{row['source_name']}/{fqname}"
        existing = conn.execute(
            "SELECT 1 FROM contexts WHERE target_uri = ? LIMIT 1",
            (target_uri,),
        ).fetchone()
        has_existing_context = existing is not None
        if has_existing_context and not include_with_existing:
            continue

        col_rows = conn.execute(
            """
            SELECT column_name, data_type, is_nullable, default_expr, comment
            FROM columns
            WHERE object_id = ?
            ORDER BY ordinal_position ASC
            """,
            (row["object_id"],),
        ).fetchall()
        columns = [
            ColumnSummary(
                name=str(col["column_name"]),
                data_type=str(col["data_type"]),
                nullable=bool(col["is_nullable"]),
                default_expr=str(col["default_expr"]) if col["default_expr"] is not None else None,
                comment=str(col["comment"]) if col["comment"] is not None else None,
            )
            for col in col_rows
        ]
        candidates.append(
            TableContextCandidate(
                source_name=str(row["source_name"]),
                object_id=str(row["object_id"]),
                fqname=fqname,
                schema_name=str(row["schema_name"]) if row["schema_name"] is not None else None,
                object_name=str(row["object_name"]),
                definition=str(row["definition"]) if row["definition"] is not None else None,
                comment=str(row["comment"]) if row["comment"] is not None else None,
                columns=columns,
                has_existing_context=has_existing_context,
            )
        )
    return candidates


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)] + "..."


def _build_prompt(candidate: TableContextCandidate) -> str:
    lines = [
        "You are generating conservative semantic context for PostgreSQL schema retrieval.",
        "Decide whether this table has enough signal to infer high-level intent.",
        "If not enough signal exists, skip instead of guessing.",
        "Return ONLY JSON object with keys: decision, reason, context.",
        "decision must be either \"generate\" or \"skip\".",
        "If decision is \"skip\", context must be an empty string.",
        "If decision is \"generate\", context must be 2-4 concise sentences with grounded inferences only.",
        "Do not output SQL and do not use markdown/bullets.",
        "For columns: mention only columns with clear semantics; omit uncertain ones.",
        "Example grounded inference: additional timestamp columns beyond created_at/updated_at can indicate event/time-series tracking.",
        "",
        f"Table: {candidate.fqname}",
    ]
    if candidate.comment:
        lines.append(f"Table comment: {candidate.comment}")
    if candidate.definition:
        lines.append(f"Definition excerpt: {_clip(candidate.definition, 1500)}")

    if candidate.columns:
        lines.append("Columns:")
        for col in candidate.columns:
            parts = [f"- {col.name}: {col.data_type}"]
            parts.append("nullable" if col.nullable else "not null")
            if col.default_expr:
                parts.append(f"default={_clip(col.default_expr, 100)}")
            if col.comment:
                parts.append(f"comment={_clip(col.comment, 180)}")
            lines.append(", ".join(parts))
    else:
        lines.append("Columns: none discovered")
    return "\n".join(lines)


def _cache_lookup(conn: sqlite3.Connection, key: str) -> ContextGenerationResult | None:
    row = conn.execute(
        "SELECT value_json FROM llm_cache WHERE key = ? LIMIT 1",
        (key,),
    ).fetchone()
    if row is None:
        return None
    try:
        payload = json.loads(str(row["value_json"]))
    except json.JSONDecodeError:
        return None
    decision = str(payload.get("decision", "")).strip().lower()
    reason_value = payload.get("reason")
    reason = str(reason_value).strip() if isinstance(reason_value, str) else None
    value = payload.get("context")
    context_text = str(value).strip() if isinstance(value, str) else None

    if decision == "skip":
        return ContextGenerationResult(context_text=None, reason=reason or "cached skip")
    if context_text:
        return ContextGenerationResult(context_text=context_text, reason=reason)
    return None


def _cache_store(conn: sqlite3.Connection, key: str, result: ContextGenerationResult) -> None:
    payload_obj: dict[str, str] = {}
    if result.context_text:
        payload_obj["decision"] = "generate"
        payload_obj["context"] = result.context_text
    else:
        payload_obj["decision"] = "skip"
        payload_obj["context"] = ""
    if result.reason:
        payload_obj["reason"] = result.reason
    payload = json.dumps(payload_obj, sort_keys=True)
    conn.execute(
        """
        INSERT INTO llm_cache(key, value_json)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json
        """,
        (key, payload),
    )
    conn.commit()


def _cache_key(*, model: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{model}\n{prompt}".encode()).hexdigest()
    return f"context-gen:{digest}"


def _call_openai_chat(
    *,
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
) -> str:
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": "You generate concise semantic context for PostgreSQL schema objects.",
            },
            {"role": "user", "content": prompt},
        ],
    }
    encoded = json.dumps(payload).encode("utf-8")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    req = request.Request(
        endpoint,
        data=encoded,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise ContextGenerationError(f"OpenAI API error ({exc.code}): {detail}") from exc
    except error.URLError as exc:
        raise ContextGenerationError(f"OpenAI request failed: {exc}") from exc

    try:
        data = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ContextGenerationError("OpenAI response was not valid JSON") from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ContextGenerationError("OpenAI response did not include choices")
    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise ContextGenerationError("OpenAI response did not include text content")
    text = content.strip()
    if not text:
        raise ContextGenerationError("OpenAI returned empty context")
    return text


def _extract_json_text(text: str) -> str:
    trimmed = text.strip()
    if trimmed.startswith("```"):
        lines = trimmed.splitlines()
        if len(lines) >= 3:
            inner = "\n".join(lines[1:-1]).strip()
            if inner:
                return inner
    return trimmed


def _parse_generation_output(text: str) -> ContextGenerationResult:
    raw = _extract_json_text(text)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Backwards-compatible fallback for older cached/raw responses.
        trimmed = text.strip()
        if not trimmed:
            return ContextGenerationResult(context_text=None, reason="empty model output")
        return ContextGenerationResult(context_text=trimmed)

    if not isinstance(payload, dict):
        raise ContextGenerationError("OpenAI generation response must be a JSON object")

    decision_raw = payload.get("decision")
    decision = str(decision_raw).strip().lower() if isinstance(decision_raw, str) else ""
    reason_raw = payload.get("reason")
    reason = str(reason_raw).strip() if isinstance(reason_raw, str) else None
    context_raw = payload.get("context")
    context_text = str(context_raw).strip() if isinstance(context_raw, str) else ""

    if decision == "skip":
        return ContextGenerationResult(context_text=None, reason=reason or "insufficient inference signal")
    if decision == "generate":
        if not context_text:
            return ContextGenerationResult(context_text=None, reason=reason or "model produced empty context")
        return ContextGenerationResult(context_text=context_text, reason=reason)

    # Missing decision: keep compatibility by treating non-empty context as generated text.
    if context_text:
        return ContextGenerationResult(context_text=context_text, reason=reason)
    raise ContextGenerationError("OpenAI response missing valid decision ('generate' or 'skip')")


_BOILERPLATE_COLUMN_NAMES = {
    "id",
    "created_at",
    "updated_at",
    "deleted_at",
    "inserted_at",
    "modified_at",
    "created_on",
    "updated_on",
}


def _has_reasonable_signal(candidate: TableContextCandidate) -> tuple[bool, str]:
    if candidate.comment and candidate.comment.strip():
        return True, "table comment present"
    if candidate.definition and candidate.definition.strip():
        return True, "table definition present"

    non_boilerplate = [
        col for col in candidate.columns if col.name.strip().lower() not in _BOILERPLATE_COLUMN_NAMES
    ]
    if non_boilerplate:
        return True, "non-boilerplate columns present"
    return False, "only boilerplate fields available"


def generate_table_context_text(
    conn: sqlite3.Connection,
    candidate: TableContextCandidate,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> ContextGenerationResult:
    prompt = _build_prompt(candidate)
    key = _cache_key(model=model, prompt=prompt)
    cached = _cache_lookup(conn, key)
    if cached is not None:
        return cached

    has_signal, signal_reason = _has_reasonable_signal(candidate)
    if not has_signal:
        result = ContextGenerationResult(
            context_text=None,
            reason=f"skipped: {signal_reason}",
        )
        _cache_store(conn, key, result)
        return result

    text = _call_openai_chat(
        api_key=api_key,
        model=model,
        base_url=base_url,
        prompt=prompt,
    )
    result = _parse_generation_output(text)
    _cache_store(conn, key, result)
    return result
