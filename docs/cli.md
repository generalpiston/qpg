# CLI Reference

See the [canonical specification](spec.md) for normative command and safety behavior.

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
- `rows`
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

Bounded row query example:

```bash
qpg rows lookup --source work --table public.orders --key 42 \
  --column id --column status --json

qpg rows page --source work --table public.orders --after 42 --limit 25 \
  --column id --column status --json
```

Row queries support only eligible single-primary-key tables. They perform an exact key lookup or ascending keyset page, always require explicit safe columns, and never accept SQL text, `SELECT *`, filters, offsets, or custom ordering. Unsafe plans are rejected before execution; row values are not stored locally.
