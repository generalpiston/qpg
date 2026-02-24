from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

import sqlite_vec  # type: ignore[import-untyped]

from qpg.config import ensure_dirs


def now_expr() -> str:
    return "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def connect_sqlite(path: Path | None = None, *, check_same_thread: bool = True) -> sqlite3.Connection:
    paths = ensure_dirs()
    db_path = path or paths.index_db
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _executescript(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def ensure_schema(conn: sqlite3.Connection) -> bool:
    vec_loaded = load_sqlite_vec(conn)

    ddl = [
        f"""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            dsn TEXT NOT NULL,
            include_schemas_json TEXT,
            skip_patterns_json TEXT,
            created_at TEXT NOT NULL DEFAULT ({now_expr()}),
            updated_at TEXT NOT NULL DEFAULT ({now_expr()}),
            last_indexed_at TEXT,
            last_error TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS db_objects (
            id TEXT PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            schema_name TEXT,
            object_name TEXT NOT NULL,
            object_type TEXT NOT NULL,
            fqname TEXT NOT NULL,
            definition TEXT,
            comment TEXT,
            signature TEXT,
            owner TEXT,
            is_system INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()}),
            UNIQUE(source_id, object_type, fqname)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_db_objects_source_type
        ON db_objects(source_id, object_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_db_objects_fqname
        ON db_objects(fqname)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS columns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id TEXT NOT NULL REFERENCES db_objects(id) ON DELETE CASCADE,
            column_name TEXT NOT NULL,
            data_type TEXT NOT NULL,
            is_nullable INTEGER NOT NULL,
            ordinal_position INTEGER NOT NULL,
            default_expr TEXT,
            comment TEXT,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()}),
            UNIQUE(object_id, column_name)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_columns_object_id
        ON columns(object_id)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS constraints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id TEXT NOT NULL REFERENCES db_objects(id) ON DELETE CASCADE,
            constraint_name TEXT NOT NULL,
            constraint_type TEXT NOT NULL,
            definition TEXT,
            columns_json TEXT,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()}),
            UNIQUE(object_id, constraint_name)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS indexes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id TEXT NOT NULL REFERENCES db_objects(id) ON DELETE CASCADE,
            index_name TEXT NOT NULL,
            definition TEXT,
            is_unique INTEGER NOT NULL DEFAULT 0,
            is_primary INTEGER NOT NULL DEFAULT 0,
            columns_json TEXT,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()}),
            UNIQUE(object_id, index_name)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id TEXT NOT NULL REFERENCES db_objects(id) ON DELETE CASCADE,
            depends_on_object_id TEXT REFERENCES db_objects(id) ON DELETE CASCADE,
            dependency_type TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()})
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_dependencies_object_id
        ON dependencies(object_id)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_uri TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ({now_expr()})
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS object_context_effective (
            object_id TEXT PRIMARY KEY REFERENCES db_objects(id) ON DELETE CASCADE,
            context_text TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()})
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS lexical_docs (
            object_id TEXT PRIMARY KEY REFERENCES db_objects(id) ON DELETE CASCADE,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            name_col TEXT NOT NULL,
            comment_col TEXT NOT NULL,
            defs_col TEXT NOT NULL,
            context_col TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ({now_expr()})
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS objects_fts USING fts5(
            object_id UNINDEXED,
            source_name UNINDEXED,
            schema_name UNINDEXED,
            kind UNINDEXED,
            name_col,
            comment_col,
            defs_col,
            context_col,
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS object_vectors (
            object_id TEXT PRIMARY KEY REFERENCES db_objects(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL,
            model TEXT NOT NULL DEFAULT 'codebert-base-v1',
            updated_at TEXT NOT NULL DEFAULT ({now_expr()})
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_object_vectors_model
        ON object_vectors(model)
        """,
        f"""
        CREATE TABLE IF NOT EXISTS llm_cache (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT ({now_expr()}),
            expires_at TEXT
        )
        """,
    ]

    _executescript(conn, ddl)
    _ensure_sources_columns(conn)
    conn.commit()
    return vec_loaded


def _ensure_sources_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
    if "include_schemas_json" not in columns:
        conn.execute("ALTER TABLE sources ADD COLUMN include_schemas_json TEXT")
    if "skip_patterns_json" not in columns:
        conn.execute("ALTER TABLE sources ADD COLUMN skip_patterns_json TEXT")


def load_sqlite_vec(conn: sqlite3.Connection) -> bool:
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    except Exception:
        return False
    finally:
        with suppress(Exception):
            conn.enable_load_extension(False)
    return True
