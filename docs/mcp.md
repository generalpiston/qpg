# MCP

See the [canonical specification](spec.md) for normative MCP and security behavior.

Run MCP server:

- Stdio: `qpg mcp`
- HTTP: `qpg mcp --http`
- HTTP daemon: `qpg mcp --http --daemon`
- Stop daemon: `qpg mcp stop`

Startup behavior:

- MCP starts a best-effort background refresh of configured sources during startup.
- Startup refresh uses the same guarded update path and defaults as `qpg update`.
- If a source refresh fails, MCP still starts and logs the error to stderr.
- If no sources are configured, MCP starts without error.

Default tools:

- `qpg.search`
- `qpg.deep_search`
- `qpg.get`
- `qpg.status`
- `qpg.list_sources`

Optional update tool:

- Start MCP with `qpg mcp --enable-update-tool`
- Call `qpg.update_source` with `{"source":"<name>"}` or `{"source":"<name>","skip_functions":true}`

Optional bounded row query tool:

- Start MCP with `qpg mcp --enable-query-tool`.
- Call `qpg.query_rows` with structured `source`, `table`, `projections`, and `mode` fields. A projection is either `{ "column": "name" }` or `{ "function": "left", "column": "text_col", "length": 500, "alias": "prefix" }`. `lookup` requires `key`; `page` requires `limit` and may include an exclusive `key` cursor.
- It supports eligible single-primary-key base tables only and rejects unsafe requests before execution.
