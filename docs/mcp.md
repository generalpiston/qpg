# MCP

Run MCP server:

- Stdio: `qpg mcp`
- HTTP: `qpg mcp --http`
- HTTP daemon: `qpg mcp --http --daemon`
- Stop daemon: `qpg mcp stop`

Default tools:

- `qpg.search`
- `qpg.deep_search`
- `qpg.get`
- `qpg.status`
- `qpg.list_sources`

Optional update tool:

- Start MCP with `qpg mcp --enable-update-tool`
- Call `qpg.update_source` with `{"source":"<name>"}` or `{"source":"<name>","skip_functions":true}`
