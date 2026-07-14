# qpg Specification

This document is the canonical behavioral contract for qpg. If implementation, tests, or other
documentation conflict with this document, this document MUST win unless a deliberate versioned
redesign is approved.

The specification defines externally observable behavior, invariants, defaults, allowed values,
failure behavior, side effects, and security boundaries. It MUST NOT freeze internal module layout,
class names, function names, algorithms, or prompt wording unless externally required.

## Product And Domain

`qpg` means **Query PostgreSQL (Schema)**. qpg MUST remain a local-first system for indexing and
querying PostgreSQL schema metadata, with an explicitly bounded row-query capability. It MUST expose
a CLI and MAY expose a constrained MCP server.

qpg MAY index and retrieve metadata for schemas, tables, columns, constraints, indexes, views,
extensions, functions, procedures, comments, and normalized definitions. It MUST NOT execute
arbitrary user SQL, expose EXPLAIN or planning controls to users, mutate PostgreSQL state, or persist
row values. Row queries are the sole permitted transient row-value access.

A source is a stable named PostgreSQL connection target. Sources MUST be stored in local SQLite,
retain a stable user-facing name, and use DSNs normalized for readonly behavior. Source filters MAY
include `include_schemas` and `skip_patterns`; matching objects MUST be excluded from indexing.

Contexts are retrieval guidance attached to `qpg://` targets. They MUST remain separate from
source-of-truth schema metadata, be materialized into effective object context, and may be human-
authored or generated through explicit workflows.

Object IDs MUST be deterministic from source name, object type, and fully qualified name, and MUST
remain stable across reindexing unless object identity changes.

## Security And Storage

Every PostgreSQL connection MUST enforce:

- `default_transaction_read_only = on`
- `statement_timeout = 5s`
- `idle_in_transaction_session_timeout = 10s`

`qpg auth check` MUST inspect inherited roles and effective privileges. The default allowed baseline
is SELECT, schema USAGE, and catalog access needed for introspection. INSERT, UPDATE, DELETE,
TRUNCATE, CREATE, ALTER, DROP, REFERENCES, TRIGGER, database CREATE/TEMP, and function EXECUTE are
prohibited by default.

Even a role with write grants MUST be unable to write through qpg sessions because readonly guards
are mandatory.

### Bounded row queries

Row queries MUST use structured inputs for one indexed base table only. A table is eligible only when
it has one indexed, non-null, single-column primary key of a supported scalar type. Joins, views,
aggregates, subqueries, arbitrary expressions, unallowlisted functions, arbitrary SQL, filters, user-selected
ordering, offsets, and `SELECT *` MUST be rejected.

The only allowed operations are:

- primary-key equality lookup with an effective limit of one;
- ascending keyset pagination on the same primary key with a limit from 1 through 100.

Requested projections MUST be explicit and unique. Physical projections must use supported scalar
types and use `{ "column": "name" }`. The only expression projection is
`{ "function": "left", "column": "name", "length": N, "alias": "name" }`, where the alias
is explicit and unique, `N` is an integer from 1 through 4096, and the source is text-like. The
reserved output name `__qpg_cursor` MUST be rejected. Arbitrary SQL, nested expressions, casts,
predicates, and other functions MUST be rejected. A serialized response MUST be no larger than
256,000 bytes. The bound limits returned text, but does not guarantee that PostgreSQL avoids reading
or decompressing the source value.

Before execution, qpg MUST validate local indexed metadata and run `EXPLAIN (FORMAT JSON)` without
`ANALYZE`. The accepted plan MUST use the indexed primary key and MUST NOT contain sequential,
bitmap, sort, materialization, filter, or unrecognized nodes. Estimated plan cost above 1,000 MUST
be rejected. EXPLAIN is an admission check, not a runtime or cost guarantee.

Accepted row queries MUST run in a readonly transaction with transaction-local 2-second statement
timeout, lock timeout, conservative work memory, and parallel gather disabled before preflight begins.
Row values MUST be returned only to the caller and MUST NOT be stored in SQLite, logs, snapshots, or
caches.

The local SQLite index path MUST be `${XDG_CACHE_HOME:-~/.cache}/qpg/index.sqlite`.

Contractually stable SQLite tables are `sources`, `db_objects`, `columns`, `constraints`, `indexes`,
`dependencies`, `contexts`, `object_context_effective`, `lexical_docs`, `objects_fts`,
`object_vectors`, and `llm_cache`. Only schema metadata, comments, context, and retrieval
materializations MAY be stored.

SQLite is the local source of truth for indexed metadata and retrieval state. Schema retrieval
commands and default MCP tools MUST use the local index. The explicitly enabled bounded row-query
capability is the sole exception.

## Retrieval And Model

Retrieval inputs MUST be derived from schema metadata: names, comments, normalized definitions,
synthesized structure text, and effective context.

`search` MUST perform lexical BM25 retrieval over local FTS5 documents and support source, schema,
and kind filters. `vsearch` MUST perform local vector similarity over `object_vectors`, use the
cached model initialized by `qpg init`, and remain available without sqlite-vec acceleration.

`query` MUST be deterministic blended retrieval in this order:

1. deterministic query expansion;
2. lexical candidate retrieval;
3. vector candidate retrieval;
4. reciprocal rank fusion with `k=60`;
5. top-rank bonus;
6. optional rerank hook.

Reranking is advisory; if it fails, fused ordering MUST remain the fallback.

The default embedding model is `microsoft/codebert-base`, cached at
`${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`, with dimension 768. Model assets
MUST be initialized explicitly, core retrieval MUST use local inference, and optional LLM workflows
MUST remain separate from core retrieval.

## Features And CLI

Stable commands are:

`init`, `config`, `source add`, `source list`, `source rm`, `source rename`, `usage refresh`,
`context add`, `context list`, `context rm`, `context generate`, `auth check`, `update`, `status`,
`cleanup`, `repair`, `search`, `vsearch`, `query`, `rows`, `get`, `schema`, and `mcp`.

Adding a source MUST normalize its DSN, support passwordless standard PostgreSQL authentication,
and perform best-effort index and usage refresh without failing source creation when refresh fails.

`qpg update` MUST connect with guards, introspect metadata, apply filters, rebuild normalized metadata,
materialize context, rebuild lexical and vector retrieval data, refresh usage, and record success or
error per source.

Context generation MUST be explicit-only and MUST never run automatically during normal updates.
Generated context MUST use the existing contexts table and the documented qpg target forms.

Stable common flags include `--json`, `--source`, `--schema`, `--kind`, `--min-score`, `--files`,
`-n`, and `--all` where applicable. Unsupported commands, flags, and combinations MUST fail with a
non-zero argument-parsing result.

### Row CLI

`qpg rows lookup` MUST require `--source`, `--table`, repeatable JSON `--projection`, and `--key`.
`qpg rows page` MUST require `--source`, `--table`, repeatable JSON `--projection`, and `--limit`; it MAY
accept `--after` as an exclusive primary-key cursor. Both commands MUST reject unsafe requests before
executing the data query.

## MCP And Configuration

Default MCP tools MUST be exactly:

- `qpg.search`
- `qpg.deep_search`
- `qpg.get`
- `qpg.status`
- `qpg.list_sources`

Optional MCP tools MUST be disabled by default. `qpg.update_source` requires
`--enable-update-tool`; `qpg.query_rows` requires `--enable-query-tool`.

MCP MUST never execute arbitrary SQL or expose a more permissive database access path than the CLI.
`qpg.query_rows` MUST expose the same lookup and keyset-page contract as the row CLI. Its schema MUST
reject unknown fields and define supported modes, limits, and projection bounds.

MCP startup MUST begin a best-effort background refresh without delaying readiness. Refresh failure
MUST NOT prevent startup and MUST be logged.

Configuration precedence is CLI flags, environment variables, YAML at
`${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`, then built-in defaults. Stable YAML keys are
`pg_connect_timeout_sec`, `openai_api_key`, `openai_model`, and `openai_base_url`.
`pg_connect_timeout_sec` MUST be an integer at least 1 and defaults to 1. `qpg config` MUST redact
secrets.

## Testing And Change Management

`uv run pytest` MUST pass quickly without Docker. Opt-in integration tests MUST validate readonly
role success, elevated-role failure, write blocking, and bounded row-query behavior against real
PostgreSQL, including primary-key lookup/page plans, limits, unsupported shapes, and transient-only
results.

The project MUST use Python 3.13, uv, PEP 621 metadata, and remain installable with
`uv tool install .`. Core dependencies MUST be treated as present once declared; silent import-time
degradation MUST NOT be added.

Any contract change MUST update tests and user-facing docs in the same change, preserve defaults
unless breakage is explicitly approved, and use a versioned or gated migration path when necessary.

## Governance

Behavioral contracts belong in this document. Architecture explanation belongs in
`docs/architecture.md`; usage guidance belongs in the task-specific docs. Those documents MUST link
to this contract instead of duplicating normative rules.

When implementation and contract conflict, state the conflict clearly and preserve current behavior
by default unless a deliberate redesign is approved.
