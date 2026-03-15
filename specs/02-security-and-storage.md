# Security And Storage

## Security Contract

### Session guards

Every PostgreSQL connection opened by `qpg` MUST enforce:

- `default_transaction_read_only = on`
- `statement_timeout = 5s`
- `idle_in_transaction_session_timeout = 10s`

### Privilege policy

`qpg auth check` MUST evaluate effective privileges, including inherited role membership.
Privilege inspection MUST include role inheritance and the relevant `has_*_privilege` checks.

Allowed baseline:

- `SELECT`
- schema `USAGE`
- catalog access needed for introspection

Prohibited by default:

- `INSERT`
- `UPDATE`
- `DELETE`
- `TRUNCATE`
- `CREATE`
- `ALTER`
- `DROP`
- `REFERENCES`
- `TRIGGER`
- database `CREATE`
- database `TEMP`
- function `EXECUTE` unless explicitly allowed

### Security intent

Even if a role has write-capable grants, `qpg` MUST still be unable to write through its own PostgreSQL sessions because readonly session guards are mandatory.

## Local Storage Contract

### SQLite location

The local index database path MUST be:

`${XDG_CACHE_HOME:-~/.cache}/qpg/index.sqlite`

### Required tables

The following table names are contractually stable and MUST NOT change without migration:

- `sources`
- `db_objects`
- `columns`
- `constraints`
- `indexes`
- `dependencies`
- `contexts`
- `object_context_effective`
- `lexical_docs`
- `objects_fts`
- `object_vectors`
- `llm_cache`

### Storage rules

- only schema metadata, comments, context, and retrieval materializations MAY be stored
- row values MUST never be stored
- per-source rebuilds MUST avoid mixed-source stale retrieval artifacts
- lexical and vector retrieval state MUST remain local-first

## Architectural Invariants

- PostgreSQL MUST be used only for schema introspection and usage-signal collection.
- SQLite MUST remain the local source of truth for indexed metadata and retrieval state.
- Retrieval commands and MCP tools MUST answer from the local SQLite index and MUST NOT read PostgreSQL row values at query time.

Separation-of-concerns invariants:

- context MUST remain a retrieval layer on top of schema structure rather than source-of-truth schema metadata
- MCP MUST remain a constrained interface over local indexed capabilities
