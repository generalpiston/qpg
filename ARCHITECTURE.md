# Architecture

Canonical architecture documentation moved to:
- [docs/architecture.md](docs/architecture.md)

Other reference docs:
- [docs/cli.md](docs/cli.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/context-generation.md](docs/context-generation.md)
- [docs/mcp.md](docs/mcp.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)

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
