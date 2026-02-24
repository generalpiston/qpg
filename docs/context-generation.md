# Context Generation

Command:

```bash
qpg context generate --source <source>
```

## Scope

- Generates object-level context entries for table targets (`qpg://<source>/<schema.table>`).
- Table context is inherited by child objects (for example column objects), so one table context can cover table + columns.

## Conservative Policy

- Generation is conservative by design.
- If the model cannot make a reasonable high-level inference from schema signals, generation is skipped for that object.
- Output tracks:
  - `generated`
  - `skipped_existing`
  - `skipped_inference`

## Controls

- `--overwrite`: regenerate even when context already exists
- `--dry-run`: do not persist entries
- `--model`, `--api-key`, `--base-url`: explicit overrides
