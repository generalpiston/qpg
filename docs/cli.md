# CLI Reference

`qpg` command groups:

- `init`
- `config`
- `source add|list|rm|rename`
- `usage refresh`
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

Behavior notes:
- `source add` auto-refreshes index + usage snapshot for the new source.
- `source add` auto-refresh is best-effort; source creation still succeeds on refresh failure.
- `update` auto-refreshes usage snapshot for each refreshed source.
- `context generate` remains explicit and is never auto-run.

Use:

```bash
qpg --help
qpg <command> --help
qpg <command> <subcommand> --help
```

Common output/options:

- `--json`
- `--source`
- search/query-only: `--files`, `-n`, `--all`, `--min-score`, `--schema`, `--kind`
