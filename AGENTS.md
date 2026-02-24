# AGENTS.md

## Purpose
This file defines the non-negotiable product and architecture decisions for `qpg`.
All future prompts, code changes, and generated plans must conform to this document unless the user explicitly requests a deliberate versioned redesign.
Architecture details and component flow are specified in `docs/architecture.md` (with a root `ARCHITECTURE.md` pointer); this file and `docs/architecture.md` must remain consistent.

If a request conflicts with this file:
1. State the conflict clearly.
2. Propose a versioned migration path (for example `v2` feature gate).
3. Preserve current behavior by default.

## Product Identity
`qpg` means **Query PostgreSQL (Schema)**.
It is a local-first CLI that indexes PostgreSQL **schema metadata only**.

### In Scope
- Schemas
- Tables
- Columns
- Constraints
- Indexes
- Views
- Extensions
- Functions/procedures (still schema-level metadata)

### Out of Scope (for current major line)
- Reading table row values
- Executing arbitrary user SQL against Postgres
- EXPLAIN / query planning features
- Any DB state mutation as part of normal qpg usage

## Core Domain Model

### Source
A `source` is a named Postgres connection target (`name -> dsn`) representing one logical database environment.
- Sources are persisted in local SQLite (`sources` table).
- Source names are stable handles used by all commands.
- DSNs must enforce readonly behavior (`options=-c default_transaction_read_only=on`) in storage and at connect time.

### Context
A `context` is semantic guidance attached to `qpg://` targets (human-authored by default, optionally generated via explicit tooling).
Purpose:
- Improve search relevance and retrieval intent.
- Encode operational/business meaning that is not present in DDL text.

Context is not data lineage and not row-level annotation.
Contexts are inherited and materialized to `object_context_effective` during indexing.
Object-level table context should apply to table child objects (for example column objects) so one table context can cover table + columns.
Automatically generated context must be conservative and skip objects when high-level intent cannot be reasonably inferred from schema metadata.

Supported target levels:
- Source level (`qpg://work`)
- Schema level (`qpg://work/public`)
- Object level (`qpg://work/public.orders` or fragment object id)

### Object IDs
Object IDs are deterministic content-addressed identifiers generated from:
- `source_name`
- `object_type`
- `fqname`

They are stable within a source across reindexing unless identity changes.

## Security Contract (Non-Negotiable)

### Session guards on connect
Must always apply:
- `default_transaction_read_only = on`
- `statement_timeout = 5s`
- `idle_in_transaction_session_timeout = 10s`

### Privilege enforcement
`qpg auth check` must fail when prohibited privileges are detected unless explicitly overridden.
Must evaluate inherited privileges through role membership (`pg_auth_members` recursion).
Must inspect table/schema/database capability functions (`has_*_privilege`).

Allowed baseline:
- SELECT
- Schema USAGE
- Catalog access

Prohibited by default:
- INSERT / UPDATE / DELETE / TRUNCATE
- CREATE / ALTER / DROP capability
- REFERENCES / TRIGGER
- Database CREATE / TEMP
- Function EXECUTE unless explicitly allowed

### Design intent
Even if a connected role has write grants, qpg must still be unable to write due to enforced readonly session settings.
Integration tests must keep this invariant.

## Local Index Contract (SQLite)

### Storage location
Use XDG cache semantics:
- `${XDG_CACHE_HOME:-~/.cache}/qpg/index.sqlite`

### Required tables
These names are part of the contract and should not be changed without migration:
- `sources`
- `db_objects`
- `columns`
- `constraints`
- `indexes`
- `dependencies`
- `contexts`
- `object_context_effective`
- `lexical_docs`
- `objects_fts` (FTS5)
- `object_vectors` (sqlite-vec compatible)
- `llm_cache`

### Indexing principles
- Index DDL metadata and comments only.
- Never persist row values.
- Rebuild per-source atomically enough to avoid mixed-source stale docs.
- Keep lexical and vector indices local; no external vector services.

## Retrieval Contract

### search
- FTS5 BM25 over multi-field docs (`name`, `comment`, `definition`, `context`).
- Context text must be boostable and treated as first-class relevance signal.

### vsearch
- Local vector similarity over `object_vectors`.
- Must be enabled by default and treated as a required retrieval signal.
- Baseline model contract: `microsoft/codebert-base` cached at `${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`.
- Model assets are initialized via `qpg init`.

### query
- Deterministic expansion.
- Blend lexical + vector results with RRF (`k=60` default contract).
- Keep ranking deterministic given identical index + query + config.

## CLI Contract
Commands and semantics are stable surface area:
- `init`
- `config`
- `source add|list|rm|rename`
- `context add|list|rm|generate`
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

Output flags to preserve:
- `--json`, `--files`, `-n`, `--all`, `--min-score`, `--schema`, `--kind`, `--source`

## Configuration Contract
OpenAI runtime configuration must resolve through `pydantic-settings` with this source order:
1. CLI flags (where applicable, for example `context generate --api-key/--model/--base-url`)
2. Environment variables:
   - `QPG_OPENAI_API_KEY`, `QPG_OPENAI_MODEL`, `QPG_OPENAI_BASE_URL`
   - fallback aliases: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`
3. YAML file: `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`
4. Built-in defaults

YAML keys are flat and stable:
- `openai_api_key`
- `openai_model`
- `openai_base_url`

`qpg config` must expose effective configuration with secret values redacted.

## MCP Contract
Expose only schema-index retrieval tools by default:
- `qpg_search`
- `qpg_deep_search`
- `qpg_get`
- `qpg_status`
- `qpg_list_sources`

No tool may execute arbitrary SQL or row queries in current line.

## Testing Contract

### Default suite
`uv run pytest` must pass quickly without requiring Docker.
Integration tests are opt-in.

### Integration harness
- Uses local ephemeral Postgres harness.
- Must validate readonly role pass + elevated role fail.
- Must include negative write-attempt test where writer-capable role still cannot write through qpg connection guards.

## Dependency and Tooling Contract
- Python 3.13
- `uv` only (no pip workflows, no requirements.txt)
- PEP 621 in `pyproject.toml`
- Installable via `uv tool install .`

Dependencies are treated as present once declared; do not add import-time fallback behavior that silently degrades missing core deps.

## Change Management Rules
For any change that alters behavior in this file's contracts:
1. Add/update tests first or within same change.
2. Document migration path in README.
3. Keep backwards-compatible defaults unless user explicitly approves breakage.
4. Prefer feature flags for experimental behavior.
