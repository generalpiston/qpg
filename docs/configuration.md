# Configuration

## Effective Precedence

1. CLI flags (where applicable, for example `context generate --api-key/--model/--base-url`)
2. Environment variables (`QPG_PG_CONNECT_TIMEOUT_SEC`, then `QPG_OPENAI_*`, then `OPENAI_*`)
3. Config file (`${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`)
4. Built-in defaults

## Config File

Path:

- `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`

Supported formats:

- YAML mapping
- Dotenv-style `KEY=VALUE` (fallback parser for compatibility)

YAML keys:

- `pg_connect_timeout_sec`
- `openai_api_key`
- `openai_model`
- `openai_base_url`

Example:

```yaml
pg_connect_timeout_sec: 1
openai_api_key: "sk-..."
openai_model: "gpt-5-nano"
openai_base_url: "https://api.openai.com/v1"
```

`pg_connect_timeout_sec` controls the PostgreSQL startup connection timeout in seconds. Default: `1`.

## Environment Variables

- `QPG_PG_CONNECT_TIMEOUT_SEC`
- `QPG_OPENAI_API_KEY` or `OPENAI_API_KEY`
- `QPG_OPENAI_MODEL` or `OPENAI_MODEL`
- `QPG_OPENAI_BASE_URL` or `OPENAI_BASE_URL`

## Inspect Effective Configuration

```bash
qpg config
qpg config --json
```
