# qpg

`qpg` is a local-first CLI to index and query PostgreSQL **schema metadata** (DDL structure only).

Full docs live in [`docs/`](docs/README.md).

It indexes:
- Schemas
- Tables
- Columns
- Constraints
- Indexes
- Views
- Extensions
- Functions/procedures

It does **not**:
- Query table rows
- Execute arbitrary SQL
- Run `EXPLAIN`
- Modify database state

## Install and Run

```bash
uv sync
uv run qpg init
uv run qpg --help
uv run pytest
```

Install as a tool:

```bash
uv tool install .
qpg --help
```

## Security Model

On PostgreSQL connect, qpg enforces:
- `SET default_transaction_read_only = on`
- `SET statement_timeout = '5s'`
- `SET idle_in_transaction_session_timeout = '10s'`

Privilege checks (`qpg auth check`) inspect role inheritance via `pg_auth_members` and fail on prohibited privileges unless `--allow-extra-privileges` is provided.

Allowed baseline:
- `SELECT`
- Schema `USAGE`
- Access to `pg_catalog` and `information_schema`

Prohibited by default:
- `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`
- `CREATE`, `ALTER`, `DROP`
- `REFERENCES`, `TRIGGER`
- Database `CREATE`/`TEMP`
- Function `EXECUTE` (unless `--allow-execute`)

## Local Index

SQLite path:
- `${XDG_CACHE_HOME:-~/.cache}/qpg/index.sqlite`

Schema includes:
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
- `object_vectors` (sqlite-vec compatible storage)
- `llm_cache`

## Commands

Source management:

```bash
qpg source add "postgresql://user:pass@localhost:5432/app" --name work
qpg source list
qpg source rm work
qpg source rename work prod
```

Configuration:

```bash
qpg config
qpg config --json
```

Passwordless DSNs are supported (for example `postgresql://user@host:5432/db`) so libpq can authenticate via `.pgpass`, `PGPASSWORD`, or other standard PostgreSQL auth mechanisms.

Source-level filtering is supported:
- `--schema <name>` (repeatable) to include only selected schemas
- `--skip-pattern <glob>` (repeatable) to skip matching objects (fqname or object name)

To provide password via stdin (instead of putting it in shell history), use `--password`:

```bash
printf '%s\n' 'supersecret' | qpg source add "postgresql://user@localhost:5432/app" --name work --password
```

Context management:

```bash
qpg context add qpg://work "Production billing DB"
qpg context add qpg://work/public "Critical payment schema"
qpg context generate --source work --api-key "$OPENAI_API_KEY"
qpg context list
qpg context rm 1
```

`qpg context generate` is an explicit OpenAI-powered workflow that drafts table-level context from indexed schema metadata (table definition/comments + columns). Generated entries are written to the same `contexts` table and target `qpg://<source>/<schema.table>`, so the same context is inherited by the table and its column objects. Generation is conservative: if it cannot make a reasonable high-level inference, it skips that table instead of guessing.

OpenAI settings are configurable via environment:
- `QPG_OPENAI_API_KEY` (or `OPENAI_API_KEY`)
- `QPG_OPENAI_MODEL` (or `OPENAI_MODEL`)
- `QPG_OPENAI_BASE_URL` (or `OPENAI_BASE_URL`)

OpenAI settings are also configurable via YAML:
- `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`

Example `config.yaml`:

```yaml
openai_api_key: "sk-..."
openai_model: "gpt-5-nano"
openai_base_url: "https://api.openai.com/v1"
```

Precedence:
1. CLI flags (`--api-key`, `--model`, `--base-url`)
2. Environment variables (`QPG_OPENAI_*`, then `OPENAI_*`)
3. YAML config file
4. Built-in defaults

Security checks:

```bash
qpg auth check
qpg auth check --source work
qpg auth check --source work --allow-extra-privileges
```

Indexing:

```bash
qpg update
qpg update --source work
qpg status
qpg cleanup
qpg repair
```

Search:

```bash
qpg search "payment status column"
qpg vsearch "table that stores subscriptions"
qpg query "how do we model refunds"
qpg get "public.orders"
qpg get "#abc123"
qpg schema --source work
```

Common options:
- `--json`
- `--files`
- `-n`
- `--all`
- `--min-score`
- `--schema`
- `--kind table|column|index|constraint|view|function`
- `--source`

## Search Pipeline

- `search`: FTS5 BM25 with weighted columns (`name_col`, `comment_col`, `defs_col`, `context_col`) and boosted context.
- `vsearch`: vector similarity on local `object_vectors` (enabled by default and required).
- `query`: deterministic expansion + fused ranking (RRF `k=60`) + top-rank bonus + optional rerank hook.

## Vector Model

qpg uses a local cached embedding model by default:
- model repo: `microsoft/codebert-base`
- cache directory: `${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`

Download model assets into cache with:

```bash
uv run qpg init
```

## MCP Server

Stdio mode:

```bash
qpg mcp
```

HTTP mode:

```bash
qpg mcp --http
# POST /mcp
# GET /health
# JSON-RPC 2.0 MCP methods: initialize, tools/list, tools/call
```

Daemon mode:

```bash
qpg mcp --http --daemon
qpg mcp stop
```

Exposed tools:
- `qpg_search`
- `qpg_deep_search`
- `qpg_get`
- `qpg_status`
- `qpg_list_sources`

## Development

Lint:

```bash
uv run ruff check .
```

Type check:

```bash
uv run mypy
```

Tests:

```bash
uv run pytest
```

Integration harness (Docker Compose, self-provisioned roles/db state):

```bash
uv run pytest --run-integration -m integration
```

Notes:
- Requires local Docker with `docker compose`.
- Harness file: `tests/harness/docker-compose.yml`.
- Default `uv run pytest` keeps integration tests skipped.
