# EXAMPLES.md

This is a practical quick-start for running `qpg` locally.
For full references, see `docs/README.md`.

## 1) Install and verify

```bash
uv sync
uv run qpg init
uv run qpg --help
```

Optional tool install:

```bash
uv tool install .
qpg --help
```

## 2) Add a source

### Option A: Passwordless DSN (`.pgpass` / libpq auth)

```bash
uv run qpg source add "postgresql://app_user@localhost:5432/appdb" --name work
```

With source filters:

```bash
uv run qpg source add "postgresql://app_user@localhost:5432/appdb" \
  --name work \
  --schema public \
  --schema billing \
  --skip-pattern "*.tmp_*" \
  --skip-pattern "public.audit_*"
```

### Option B: Pass password by STDIN with `--password`

```bash
printf '%s\n' 'supersecret' | uv run qpg source add "postgresql://app_user@localhost:5432/appdb" --name work --password
```

### List sources

```bash
uv run qpg source list
uv run qpg source list --json
```

## 3) Validate privileges (required safety check)

```bash
uv run qpg auth check --source work
```

If you need to inspect but not fail on extra privileges:

```bash
uv run qpg auth check --source work --allow-extra-privileges
```

## 4) Build local index

```bash
uv run qpg update --source work
uv run qpg status
```

## 5) Add context (improves relevance)

```bash
uv run qpg context add qpg://work "Production billing database"
uv run qpg context add qpg://work/public "Core payment schema"
uv run qpg context list
```

Re-index after adding context:

```bash
uv run qpg update --source work
```

## 6) Search and retrieval

Lexical search:

```bash
uv run qpg search "payment status column" --source work
uv run qpg search "refund" --source work --schema public --kind table --json
```

Hybrid query pipeline:

```bash
uv run qpg query "how do we model refunds" --source work
```

Get one object:

```bash
uv run qpg get "public.orders" --source work
uv run qpg get "#abc123" --source work --json
```

## 7) Vector search (default)

Vectors are enabled by default. Initialize model assets once:

```bash
uv run qpg init
uv run qpg update --source work
uv run qpg vsearch "table that stores subscriptions" --source work
```

## 8) MCP server

### Stdio mode

```bash
uv run qpg mcp
```

### HTTP mode

```bash
uv run qpg mcp --http --host 127.0.0.1 --port 8765
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"example","version":"1.0.0"}}}'
curl -s -X POST http://127.0.0.1:8765/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"qpg_status","arguments":{}}}'
```

### HTTP daemon mode

```bash
uv run qpg mcp --http --daemon
uv run qpg mcp stop
```

## 9) Maintenance

```bash
uv run qpg cleanup
uv run qpg repair
```

## 10) Tests

Fast default tests:

```bash
uv run pytest
```

Integration tests with Docker harness:

```bash
uv run pytest --run-integration -m integration
```
