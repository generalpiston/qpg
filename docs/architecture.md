# Architecture

## Overview
`qpg` is a local-first system for indexing and querying **PostgreSQL schema metadata**.

Core invariant:
- `qpg` indexes DDL-level structure and metadata only.
- `qpg` does not retrieve or index row values.

## Guiding Principles
1. Security-first by default.
2. Local-first indexing and retrieval.
3. Deterministic behavior where practical.
4. Explicit boundaries between ingestion, indexing, and retrieval.
5. Stable CLI/MCP surface with backwards-compatible defaults.

## High-Level System

```text
+---------------------------+            +------------------------------+
|        PostgreSQL         |            |         Local SQLite         |
|  (schema metadata only)   |            |  ${XDG_CACHE_HOME}/qpg/...   |
+-------------+-------------+            +--------------+---------------+
              |                                         ^
              | introspection SQL                       |
              v                                         |
+---------------------------+                           |
|   qpg ingestion pipeline  |---------------------------+
|  - connect guards         | writes normalized objects,
|  - privilege checks       | contexts, lexical docs,
|  - schema introspection   |
|  - label extraction       | FTS index, dense vectors
+-------------+-------------+
              |
              v
+---------------------------- Query/Retrieval ----------------------------+
|                                                                          |
|  sparse lexical retrieval               dense vector retrieval            |
|  objects_fts (BM25)                     object_vectors (CodeBERT)        |
|          |                                          |                     |
|          +------------------ candidates ------------+                     |
|                              |                                            |
|                              v                                            |
|                   Reciprocal Rank Fusion (RRF, k=60)                      |
|                              |                                            |
|                              v                                            |
|                optional reranker hook (QPG_RERANK_HOOK)                  |
|                                                                          |
+-------------------------------+------------------------------------------+
              |
              v
+---------------------------+
| CLI + MCP interfaces      |
| - qpg command surface     |
| - stdio/http MCP tools    |
+---------------------------+
```

## Request / Data Flow

### 0) Initialization
```text
qpg init
   |
   v
download model repo snapshot
   |
   v
cache in ${XDG_CACHE_HOME:-~/.cache}/qpg/models/...
```

### 1) Source Registration
```text
qpg source add <dsn> --name <source>
       |
       v
normalize DSN -> enforce readonly options
       |
       v
insert into SQLite.sources
```

### 2) Index Update
```text
qpg update [--source ...]
       |
       v
for each source:
  connect_pg()
    -> apply session guards
    -> run privilege checks
    -> introspect schema metadata
    -> normalize objects
    -> persist db_objects + related tables
    -> materialize contexts
    -> build lexical_docs + objects_fts
    -> compute object_vectors
```

### 3) Retrieval
```text
search   -> sparse lexical retrieval (FTS5 BM25 over objects_fts)
vsearch  -> dense vector retrieval (object_vectors + local embedding model)
query    -> expansion -> lexical+dense candidate sets -> RRF -> optional reranker
get      -> hydrate one object + columns/constraints/indexes/dependencies/context
```

## Security Architecture

### Connect-time guards (mandatory)
- `default_transaction_read_only = on`
- `statement_timeout = 5s`
- `idle_in_transaction_session_timeout = 10s`

### Privilege policy
`qpg auth check` evaluates inherited role privileges via recursive `pg_auth_members` traversal and `has_*_privilege` checks.

Policy outcomes:
- Pass: only baseline read capabilities.
- Fail: prohibited privileges detected.
- Override: allowed only with explicit `--allow-extra-privileges`.

### Security intent
Even if DB role has write grants, qpg sessions are read-only and must reject writes.

## Index Design

### Why SQLite
- Single-file local index.
- Portable and inspectable.
- Native FTS5 support.
- Compatible with local vector extensions (`sqlite-vec`).

### Core tables and responsibilities
```text
sources                  -> named Postgres targets
contexts                 -> human semantic annotations

(db metadata graph)
db_objects               -> canonical object records
columns                  -> column metadata per parent object
constraints              -> constraint metadata
indexes                  -> index metadata
dependencies             -> object dependency edges

(retrieval materialization)
object_context_effective -> inherited + resolved context per object
lexical_docs             -> assembled text fields for retrieval
objects_fts              -> FTS5 virtual index for lexical search
object_vectors           -> local vector embeddings
llm_cache                -> optional local cache for future hooks
```

### Label extraction (what gets encoded)
`qpg` builds retrieval labels/features from schema metadata only.

Extraction inputs:
- canonical name label: `schema.object` (or object name)
- comment label: object comments
- definition label: normalized DDL/signature text + synthesized column/constraint/index lines
- context label: effective inherited context (`object_context_effective`)

Materialization:
- lexical labels -> `lexical_docs` -> `objects_fts`
- dense labels -> concatenated text -> `object_vectors`

This label pipeline is shared by `search`, `vsearch`, and `query`.

## Source and Context Semantics

### Source
A source is a stable environment handle (`work`, `prod`, etc.) that binds all indexed objects to one Postgres target.
Source also carries optional ingestion filters:
- include schemas (`--schema`, repeatable)
- skip patterns (`--skip-pattern`, glob, repeatable)

### Context
Context is operator-authored meaning layered on top of schema shape.

Targets:
- Source-level: `qpg://work`
- Schema-level: `qpg://work/public`
- Object-level: `qpg://work/public.orders` or object-id fragment

Context inheritance is resolved during indexing into `object_context_effective`, then included in lexical/vector docs.
Object-level table context also applies to its child objects (for example `orders.id`) so table and columns can share one context entry.

## Query Architecture

### `search`
- FTS5 BM25 over weighted fields:
  - `name_col`
  - `comment_col`
  - `defs_col`
  - `context_col` (boosted)

### `vsearch`
- Vector similarity over local `object_vectors`.
- Enabled by default and treated as required retrieval capability.

### `query`
- Deterministic expansion.
- Parallel lexical + vector candidate retrieval.
- Reciprocal Rank Fusion (RRF, `k=60`) + top-rank bonus.
- Optional rerank hook (post-fusion).

## Key Design Decisions (Pinned)

### Retrieval/ranking pipeline (hard contract)
Decision:
- The retrieval pipeline order is fixed:
  1. lexical retrieval (FTS5 BM25),
  2. vector retrieval (local embeddings),
  3. Reciprocal Rank Fusion (RRF),
  4. optional rerank hook.

Contract:
- `query` and MCP deep search must use RRF fusion.
- RRF constant is pinned to `k=60`.
- Top-rank bonus remains part of fused scoring.
- If rerank hook fails or returns invalid output, fused order is kept.

### Vector representation and storage
Decision:
- Use local vectors stored in SQLite `object_vectors`.
- Primary representation is JSON float arrays derived from deterministic local embeddings.
- When sqlite-vec scalar/vector functions are available, qpg stores/query vectors through that path.
- When sqlite-vec functions are unavailable, qpg falls back to local cosine computation over stored vectors.

Rationale:
- Keeps retrieval local-first and portable.
- Avoids coupling correctness to optional native extension availability.
- Preserves deterministic behavior across environments.

Current contract:
- Embedding model id: `codebert-base-v1`.
- Model repository: `microsoft/codebert-base`.
- Model cache directory: `${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`.
- Embedding dimension: 768.
- Text source for embedding: `name + comment + defs + effective context`.
- Model download is executed explicitly via `qpg init`.

### Model usage policy
Decision:
- No mandatory external model *services* in the default architecture.
- Model inference is local; first-use model download from model registry is allowed.
- `llm_cache` is used by optional, explicit LLM workflows (for example `qpg context generate`), and is not required for normal retrieval.

Rationale:
- Predictable offline behavior.
- Zero external inference dependency for core indexing/search.
- Lower operational/security risk.

### Runtime configuration policy
Decision:
- Runtime settings resolve via `pydantic-settings`.
- OpenAI configuration may come from:
  - CLI flags (`context generate --api-key/--model/--base-url`)
  - environment variables (`QPG_OPENAI_*`, then `OPENAI_*`)
  - YAML file (`${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`)
  - defaults
- Effective precedence is: CLI > env > YAML > defaults.
- `qpg config` reports effective values and must redact secrets.
- `qpg context generate` must be conservative: if reasonable inference is not supported by schema signals, it skips generation instead of hallucinating.

Rationale:
- Keeps local operator configuration explicit and inspectable.
- Preserves safe secret handling in terminal and JSON output.
- Allows stable per-machine defaults without requiring shell env setup.

### Re-ranker design
Decision:
- First-stage retrieval uses lexical and vector candidate sets.
- Fusion is Reciprocal Rank Fusion (RRF) with `k=60` and top-rank bonus.
- Final reranking is optional via external hook (`QPG_RERANK_HOOK`), and only after deterministic fusion.

Rationale:
- RRF is robust across heterogeneous rankers without score calibration.
- Deterministic fused baseline keeps default behavior stable and testable.
- Hook-based rerank allows experimentation without changing core semantics.

Current hook contract:
- Input to hook: JSON on stdin with `{ \"query\": ..., \"results\": [...] }`.
- Output from hook: JSON list of `object_id` order.
- On hook failure or invalid output, qpg preserves fused ordering and reports hook error.
- Hook reranking is advisory only and never replaces lexical/vector candidate generation.

### Score handling policy
Decision:
- Lexical BM25 scores are converted to monotonic relevance score for presentation.
- Vector similarity uses cosine-like score (`1 - cosine distance` when available).
- Fused ranking uses rank positions (RRF), not absolute score magnitudes.

Rationale:
- Prevents brittle cross-signal score coupling.
- Makes lexical/vector combination stable even if underlying score distributions shift.

### Determinism policy
Decision:
- Keep query expansion deterministic.
- Keep fusion deterministic for identical index state and query.
- Optional rerank hook is the only explicitly non-core-deterministic extension point.

Rationale:
- Improves reproducibility for CLI and MCP consumers.
- Simplifies debugging and regression testing.

## MCP Architecture

```text
         +-------------------+
stdin -->| qpg mcp (stdio)   |--> JSON responses
         +-------------------+

         +-------------------+      POST /mcp
HTTP --->| qpg mcp --http    |<---------------- clients
         | + /health         |
         +-------------------+
```

MCP tools:
- `qpg_search`
- `qpg_deep_search`
- `qpg_get`
- `qpg_status`
- `qpg_list_sources`

Constraint:
- MCP exposes retrieval/status only, not arbitrary SQL execution.

## Component Map

```text
src/qpg/
  cli.py                -> command parsing, orchestration
  db_pg.py              -> Postgres connection and session guards
  db_sqlite.py          -> SQLite schema and connection
  sources.py            -> source CRUD + DSN policy
  contexts.py           -> context parsing/inheritance
  get.py                -> object hydration API

  schema/
    introspect.py       -> Postgres metadata extraction SQL
    privilege_check.py  -> privilege policy evaluation
    normalize.py        -> canonical object id/fqname normalization

  index/
    build.py            -> index assembly/materialization
    fts.py              -> lexical indexing and search
    vec.py              -> embedding storage/search

  query/
    expand.py           -> deterministic expansion
    rrf.py              -> reciprocal rank fusion
    normalize_scores.py -> score normalization helpers
    rerank.py           -> optional rerank hook

  mcp/
    protocol.py         -> tool dispatch and response envelope
    server_stdio.py     -> stdio transport
    server_http.py      -> HTTP transport

  util/
    redaction.py        -> DSN redaction helpers
    pg_dsn.py           -> readonly DSN enforcement
    logging.py          -> logging setup helpers
```

## Operational Modes

### Default local workflow
1. `qpg init`
2. `qpg source add ...`
3. `qpg auth check`
4. `qpg update`
5. `qpg search|query|get`

### Repair and maintenance
- `qpg config`
- `qpg status`
- `qpg cleanup`
- `qpg repair`

### MCP service mode
- `qpg mcp` (stdio)
- `qpg mcp --http`
- `qpg mcp --http --daemon`
- `qpg mcp stop`

## Testing Strategy

### Unit tests
- Privilege enforcement transformation logic
- Context inheritance behavior
- RRF behavior
- JSON payload stability
- DSN readonly normalization

### Integration tests (opt-in)
- Harness-backed Postgres with controlled roles
- Readonly role passes checks
- Writer role fails checks
- Negative write attempt fails despite writer privileges when connected through qpg guards

Run:
- Fast default: `uv run pytest`
- Integration: `uv run pytest --run-integration -m integration`

## Evolution Rules
Any change that modifies these contracts should:
1. Be explicit and versioned (`v2` feature gate or migration).
2. Preserve current defaults unless the user explicitly approves breakage.
3. Update tests and documentation in the same change.
