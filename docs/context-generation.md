# Context Generation

Command:

```bash
qpg context generate --source <source>
```

With usage evidence:

```bash
qpg usage refresh --source <source>
qpg context generate --source <source> --use-latest-usage
```

Legacy index usage ingestion mode:

```bash
qpg context generate --from index-usage --source <source> --input <path-or-"-"> --unused-days 14 --replace-managed
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
- `--use-latest-usage`: include latest usage snapshot (`qpg usage refresh`) as prompt evidence
- `--from index-usage`: ingest index usage records instead of OpenAI generation
- `--input`: JSON/JSONL path (`-` for stdin) for `--from index-usage`
- `--unused-days`: minimum threshold for `unused_days` records
- `--replace-managed`: clear previously managed index-usage context for the source before apply
