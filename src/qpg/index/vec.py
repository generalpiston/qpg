from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Any

import torch
import torch.nn.functional as torch_f
from huggingface_hub import snapshot_download
from transformers import AutoModel, AutoTokenizer

from qpg.config import ensure_dirs, get_paths

CODE_MODEL_REPO = "microsoft/codebert-base"
CODE_MODEL_DIRNAME = "microsoft__codebert-base"
CODE_MODEL_ID = "codebert-base-v1"
_MAX_TOKENS = 256


class VectorModelNotInitializedError(RuntimeError):
    pass


class _CodeLabelEmbedder:
    def __init__(self, model_repo: str = CODE_MODEL_REPO) -> None:
        self.model_repo = model_repo
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    def _models_root(self) -> Path:
        return ensure_dirs(get_paths()).models_dir

    def _model_dir(self) -> Path:
        return self._models_root() / CODE_MODEL_DIRNAME

    def ensure_cached(self, *, download: bool) -> Path:
        model_dir = self._model_dir()
        if model_dir.exists() and any(model_dir.iterdir()):
            return model_dir

        if not download:
            raise VectorModelNotInitializedError(
                "vector model is not initialized. Run `qpg init` to download it into the local cache."
            )

        model_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(repo_id=self.model_repo, local_dir=str(model_dir))
        return model_dir

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return

        model_dir = self.ensure_cached(download=False)
        self._tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        self._model = AutoModel.from_pretrained(str(model_dir), local_files_only=True)
        self._model.eval()

    def embed(self, text: str) -> list[float]:
        self._ensure_loaded()
        assert self._tokenizer is not None
        assert self._model is not None

        encoded = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=_MAX_TOKENS,
        )
        with torch.no_grad():
            output = self._model(**encoded)

        hidden = output.last_hidden_state
        mask = encoded["attention_mask"].unsqueeze(-1)
        summed = (hidden * mask).sum(dim=1)
        denom = mask.sum(dim=1).clamp(min=1)
        pooled = summed / denom
        normalized = torch_f.normalize(pooled, p=2, dim=1)
        return [float(value) for value in normalized[0].tolist()]


_EMBEDDER_LOCK = Lock()
_EMBEDDER: _CodeLabelEmbedder | None = None


def _embedder() -> _CodeLabelEmbedder:
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    with _EMBEDDER_LOCK:
        if _EMBEDDER is None:
            _EMBEDDER = _CodeLabelEmbedder()
    return _EMBEDDER


def init_vector_model() -> Path:
    """Download and cache the configured local embedding model."""
    return _embedder().ensure_cached(download=True)


def require_vector_model() -> Path:
    """Return cached model path or raise if not initialized."""
    return _embedder().ensure_cached(download=False)


def _has_vec_functions(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT vec_f32('[0.0, 1.0]')").fetchone()
    except sqlite3.DatabaseError:
        return False
    return True


def embed_text(text: str) -> list[float]:
    if not text.strip():
        return [0.0] * 768
    return _embedder().embed(text)


def _to_json_vector(vector: list[float]) -> str:
    return json.dumps([round(v, 8) for v in vector], separators=(",", ":"))


def upsert_embedding(
    conn: sqlite3.Connection,
    *,
    object_id: str,
    text: str,
    model: str = CODE_MODEL_ID,
) -> None:
    vector = embed_text(text)
    payload = _to_json_vector(vector)

    if _has_vec_functions(conn):
        conn.execute(
            """
            INSERT INTO object_vectors(object_id, embedding, model, updated_at)
            VALUES(?, vec_f32(?), ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(object_id) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                updated_at = excluded.updated_at
            """,
            (object_id, payload, model),
        )
    else:
        conn.execute(
            """
            INSERT INTO object_vectors(object_id, embedding, model, updated_at)
            VALUES(?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(object_id) DO UPDATE SET
                embedding = excluded.embedding,
                model = excluded.model,
                updated_at = excluded.updated_at
            """,
            (object_id, payload.encode("utf-8"), model),
        )


def _decode_vector(blob: bytes | str) -> list[float] | None:
    if isinstance(blob, bytes):
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        text = blob

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    return [float(item) for item in raw]


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def vector_search(
    conn: sqlite3.Connection,
    *,
    query: str,
    limit: int = 10,
    source: str | None = None,
    schema: str | None = None,
    kind: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    query_vec = embed_text(query)

    filters: list[str] = []
    params: list[Any] = []
    if source:
        filters.append("s.name = ?")
        params.append(source)
    if schema:
        filters.append("o.schema_name = ?")
        params.append(schema)
    if kind:
        filters.append("o.object_type = ?")
        params.append(kind)

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""

    if _has_vec_functions(conn):
        sql = f"""
            SELECT o.id AS object_id,
                   o.fqname,
                   o.object_type,
                   s.name AS source_name,
                   (1.0 - vec_distance_cosine(ov.embedding, vec_f32(?))) AS score
            FROM object_vectors ov
            JOIN db_objects o ON o.id = ov.object_id
            JOIN sources s ON s.id = o.source_id
            {where_clause}
            ORDER BY score DESC
            LIMIT ?
        """
        rows = conn.execute(sql, (_to_json_vector(query_vec), *params, limit)).fetchall()
        scored = [dict(row) for row in rows]
    else:
        sql = f"""
            SELECT o.id AS object_id,
                   o.fqname,
                   o.object_type,
                   s.name AS source_name,
                   ov.embedding AS embedding
            FROM object_vectors ov
            JOIN db_objects o ON o.id = ov.object_id
            JOIN sources s ON s.id = o.source_id
            {where_clause}
        """
        rows = conn.execute(sql, params).fetchall()
        scored = []
        for row in rows:
            vector = _decode_vector(row["embedding"])
            if vector is None:
                continue
            score = _cosine(query_vec, vector)
            scored.append(
                {
                    "object_id": row["object_id"],
                    "fqname": row["fqname"],
                    "object_type": row["object_type"],
                    "source_name": row["source_name"],
                    "score": score,
                }
            )
        scored.sort(key=lambda item: item["score"], reverse=True)
        scored = scored[:limit]

    if min_score is not None:
        scored = [row for row in scored if float(row["score"]) >= min_score]
    return scored
