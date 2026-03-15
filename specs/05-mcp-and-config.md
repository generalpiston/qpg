# MCP And Configuration

## MCP Contract

### Default MCP tools

The canonical MCP tool names MUST be:

- `qpg.search`
- `qpg.deep_search`
- `qpg.get`
- `qpg.status`
- `qpg.list_sources`

### Opt-in MCP tools

Optional MCP tools MUST be explicitly gated off by default.
Current opt-in tool:

- `qpg.update_source`

### MCP restrictions

The MCP surface MUST NOT:

- execute arbitrary SQL
- read row values
- expose a more permissive database access path than the CLI

### MCP startup behavior

When the MCP server starts, it MUST kick off a best-effort refresh of all configured sources without blocking server readiness.

Contract:

- startup refresh MUST begin during MCP startup, but MUST NOT delay MCP readiness
- startup refresh MUST use the same guarded update flow and defaults as `qpg update`
- startup refresh failure MUST NOT prevent MCP startup
- source refresh errors MUST be recorded in source state and surfaced to stderr logs
- if no sources are configured, MCP startup MUST continue without error

## Configuration Contract

Runtime settings MUST resolve through `pydantic-settings` with this precedence:

1. CLI flags where applicable
2. environment variables:
   - `QPG_PG_CONNECT_TIMEOUT_SEC`
   - `QPG_OPENAI_API_KEY`
   - `QPG_OPENAI_MODEL`
   - `QPG_OPENAI_BASE_URL`
   - fallback aliases `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`
3. YAML file: `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`
4. built-in defaults

Stable YAML keys:

- `pg_connect_timeout_sec`
- `openai_api_key`
- `openai_model`
- `openai_base_url`

`pg_connect_timeout_sec` MUST control PostgreSQL connection startup timeout in seconds.
Allowed values: integer seconds greater than or equal to `1`.
Default: `1`.

`qpg config` MUST expose effective resolved configuration with secret values redacted.
