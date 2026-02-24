# Troubleshooting

## `missing OpenAI API key`

Set one of:

- `QPG_OPENAI_API_KEY`
- `OPENAI_API_KEY`

Or configure `${XDG_CONFIG_HOME:-~/.config}/qpg/config.yaml`.

## `context generate` skips everything

- Existing context may already be present (check `skipped_existing`).
- Conservative generation may skip weak-signal tables (check `skipped_inference`).
- Use `--overwrite` to re-evaluate existing entries.

## Vector/model errors

Initialize model assets:

```bash
qpg init
```

## Privilege check failures

Inspect:

```bash
qpg auth check --source <source>
```

Use `--allow-extra-privileges` only when intentionally overriding policy.
