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

### Bounded row queries

Row queries MUST use structured inputs for one indexed base table only. A table is eligible only when it has one indexed, non-null, single-column primary key of a supported scalar type. Joins, views, aggregates, subqueries, expressions, functions, aliases, arbitrary SQL, filters, user-selected ordering, offsets, and `SELECT *` MUST be rejected.

The only allowed operations are a primary-key equality lookup with an effective limit of one and ascending keyset pagination on that same key with a limit from 1 through 100. Requested result columns MUST be explicit, unique, supported scalar types; unbounded or complex types MUST be rejected. Returned rows MUST fit within a fixed 256,000-byte serialized response budget.

Before execution, qpg MUST validate the local indexed metadata and run `EXPLAIN (FORMAT JSON)` without `ANALYZE`. The accepted plan MUST use the indexed primary key and MUST NOT contain sequential, bitmap, sort, materialization, filter, or unrecognized nodes. Estimated plan cost above 1,000 MUST be rejected. `EXPLAIN` is an admission check and MUST NOT be represented as a cost or runtime guarantee.

Accepted row queries MUST run in a read-only transaction with transaction-local 2-second statement timeout, lock timeout, conservative work memory, and parallel-gather disabled before preflight begins. Row values MUST be returned to the caller only and MUST NOT be stored in SQLite or query caches.

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

- PostgreSQL MUST be used only for schema introspection, usage-signal collection, and accepted bounded row queries.
- SQLite MUST remain the local source of truth for indexed metadata and retrieval state.
- Schema retrieval commands and default MCP tools MUST answer from the local SQLite index and MUST NOT read PostgreSQL row values at query time. The explicitly enabled bounded row-query capability is the sole exception.

Separation-of-concerns invariants:

- context MUST remain a retrieval layer on top of schema structure rather than source-of-truth schema metadata
- MCP MUST remain a constrained interface over local indexed capabilities
