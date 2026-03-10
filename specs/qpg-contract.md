# qpg Contract Spec

## Purpose

This spec defines the contract for `qpg`.
It is the narrow canonical description of:

- product scope
- security invariants
- local storage contract
- retrieval contract
- CLI contract
- MCP contract
- configuration contract
- testing contract
- key architecture and feature behavior

If implementation, tests, prompts, or documentation conflict with this spec, this spec wins unless the user explicitly requests a deliberate versioned redesign.

## Product Identity

`qpg` means **Query PostgreSQL (Schema)**.

`qpg` is a local-first system for indexing and querying PostgreSQL schema metadata.
It is primarily a CLI and also exposes a constrained MCP server over the local index.

## Scope

### In scope

`qpg` may index and retrieve metadata for:

- schemas
- tables
- columns
- constraints
- indexes
- views
- extensions
- functions
- procedures
- comments and normalized definitions associated with those objects

### Out of scope

`qpg` must not:

- read table row values as part of normal product behavior
- execute arbitrary user SQL against PostgreSQL
- expose EXPLAIN or query planning features
- mutate PostgreSQL state as part of normal usage
- persist row values in the local index

## Core Domain Model

### Source

A `source` is a named PostgreSQL connection target:

- identity: `name -> dsn`
- persistence: local SQLite `sources` table
- source names are stable user-facing handles
- DSNs must be normalized to enforce readonly behavior in storage and on connect

Source-level filters are part of the source definition:

- `include_schemas`
- `skip_patterns`

### Context

A `context` is semantic guidance attached to a `qpg://` target.
Its purpose is retrieval guidance, not source-of-truth schema metadata.

Allowed target levels:

- source: `qpg://work`
- schema: `qpg://work/public`
- object: `qpg://work/public.orders`
- object-id fragment: `qpg://work#<object_id>`

Context rules:

- context may be human-authored or generated only through explicit workflows
- contexts are materialized into `object_context_effective` during indexing
- table-level object context applies to child column objects
- generated context must be conservative and may skip objects if intent is unclear

### Object identity

Each indexed object has a deterministic content-addressed identifier derived from:

- `source_name`
- `object_type`
- `fqname`

Object ids are stable across reindexing unless the object identity changes.

## Security Contract

### Session guards

Every PostgreSQL connection opened by `qpg` must enforce:

- `default_transaction_read_only = on`
- `statement_timeout = 5s`
- `idle_in_transaction_session_timeout = 10s`

### Privilege policy

`qpg auth check` must evaluate effective privileges, including inherited role membership.
Privilege inspection must include role inheritance and the relevant `has_*_privilege` checks.

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

Even if a role has write-capable grants, `qpg` must still be unable to write through its own PostgreSQL sessions because readonly session guards are mandatory.

## Local Storage Contract

### SQLite location

The local index database path is:

`${XDG_CACHE_HOME:-~/.cache}/qpg/index.sqlite`

### Required tables

The following table names are contractually stable:

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

- only schema metadata, comments, context, and retrieval materializations may be stored
- row values must never be stored
- per-source rebuilds must avoid mixed-source stale retrieval artifacts
- lexical and vector retrieval state must remain local-first

## Retrieval Contract

### Retrieval inputs

Retrieval is built from schema metadata only:

- names
- comments
- normalized definitions and synthesized structure text
- effective context

### `search`

`search` is lexical retrieval over local FTS5 documents using BM25.

Contract:

- searches over multi-field materialized docs
- treats context as a first-class signal
- supports filtering by source, schema, and kind

### `vsearch`

`vsearch` is local vector similarity over `object_vectors`.

Contract:

- enabled by default
- treated as a required retrieval capability
- uses the local cached model initialized by `qpg init`

### `query`

`query` is deterministic blended retrieval.

Contract:

1. deterministic query expansion
2. lexical candidate retrieval
3. vector candidate retrieval
4. reciprocal rank fusion with `k=60`
5. top-rank bonus in fused score
6. optional rerank hook applied after fusion

If reranking fails, fused order must remain the fallback.

## Model Contract

Default embedding model contract:

- model repo: `microsoft/codebert-base`
- cache path: `${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`
- embedding dimension: `768`
- model assets are initialized explicitly via `qpg init`

Model usage rules:

- core retrieval uses local inference
- no external vector service is required
- optional LLM workflows are explicit and separate from core retrieval

## Feature Contract

### Source management

Stable source operations:

- add a source
- list sources
- remove a source
- rename a source

Behavior:

- adding a source normalizes the DSN to readonly form
- adding a source performs best-effort auto-refresh of index and usage snapshot
- auto-refresh failure must not prevent the source from being stored

### Update

`qpg update` refreshes one or more sources.

Per updated source it must:

1. connect with guards
2. introspect schema metadata
3. apply source filters
4. rebuild normalized metadata tables
5. materialize effective context
6. rebuild lexical retrieval docs
7. rebuild vector retrieval data
8. refresh usage snapshot
9. record source success or source error status

### Usage snapshots

`qpg usage refresh --source <name>` collects index usage signals from PostgreSQL and stores a local snapshot under the XDG state directory.

`qpg update` and source auto-refresh also refresh usage snapshots.

### Context generation

`qpg context generate` is explicit-only.

Contracts:

- it must never run automatically during normal update flows
- OpenAI-backed generation may use schema metadata and optional usage evidence
- generated context is written into the same `contexts` table
- operator-provided index-usage ingestion is allowed as an explicit workflow

## CLI Contract

The stable command surface is:

- `init`
- `config`
- `source add`
- `source list`
- `source rm`
- `source rename`
- `usage refresh`
- `context add`
- `context list`
- `context rm`
- `context generate`
- `auth check`
- `update`
- `status`
- `cleanup`
- `repair`
- `search`
- `vsearch`
- `query`
- `get`
- `schema`
- `mcp`

Stable output and filtering flags include:

- `--json`
- `--files`
- `-n`
- `--all`
- `--min-score`
- `--schema`
- `--kind`
- `--source`

## MCP Contract

### Default MCP tools

The canonical MCP tool names are:

- `qpg.search`
- `qpg.deep_search`
- `qpg.get`
- `qpg.status`
- `qpg.list_sources`

### Opt-in MCP tools

Optional MCP tools must be explicitly gated off by default.
Current opt-in tool:

- `qpg.update_source`

### MCP restrictions

The MCP surface must not:

- execute arbitrary SQL
- read row values
- expose a more permissive database access path than the CLI

## Configuration Contract

OpenAI runtime settings resolve through `pydantic-settings` with this precedence:

1. CLI flags where applicable
2. environment variables:
   - `QPG_OPENAI_API_KEY`
   - `QPG_OPENAI_MODEL`
   - `QPG_OPENAI_BASE_URL`
   - fallback aliases `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`
3. YAML file: `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`
4. built-in defaults

Stable YAML keys:

- `openai_api_key`
- `openai_model`
- `openai_base_url`

`qpg config` must expose effective resolved configuration with secret values redacted.

## Architecture

### High-level flow

1. `qpg init` downloads local model assets
2. `qpg source add` stores a normalized readonly source definition
3. `qpg update` introspects PostgreSQL schema metadata and rebuilds local retrieval state
4. retrieval commands and MCP tools query the local SQLite index, not PostgreSQL rows

### Main subsystems

- PostgreSQL introspection with mandatory guards
- local SQLite metadata graph
- lexical retrieval materialization
- vector retrieval materialization
- CLI command surface
- MCP server surface

### Separation of concerns

- PostgreSQL is only for schema introspection and usage-signal collection
- SQLite is the local source of truth for indexed metadata and retrieval state
- context is a retrieval layer on top of schema structure
- MCP is a constrained interface over local indexed capabilities

## Testing Contract

### Default suite

`uv run pytest` must pass quickly without Docker.

### Integration coverage

Opt-in integration tests must validate:

- readonly role pass
- elevated role fail
- write attempts are still blocked through `qpg` session guards even for roles with write grants

## Change Management

Any change to this spec must:

1. update tests in the same change when behavior changes
2. update user-facing docs when behavior changes
3. preserve defaults unless the user explicitly approves a breaking redesign
4. use a versioned or gated migration path when introducing incompatible behavior without explicit approval
