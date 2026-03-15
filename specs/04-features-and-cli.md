# Features And CLI

## Feature Contract

### Source management

Stable source operations:

- add a source
- list sources
- remove a source
- rename a source

Source management contract:

- adding a source MUST normalize the DSN to readonly form
- adding a source MUST accept passwordless DSNs supported by standard PostgreSQL authentication mechanisms
- `source add --password` MUST read the password from stdin and MUST fail if the DSN already contains a password or stdin does not provide one
- adding a source MUST perform best-effort auto-refresh of index and usage snapshot
- auto-refresh failure MUST NOT prevent the source from being stored

### Update

`qpg update` MUST refresh one or more sources.

Per updated source it MUST:

1. connect with guards
2. introspect schema metadata
3. apply source filters
4. rebuild normalized metadata tables
5. materialize effective context
6. rebuild lexical retrieval docs
7. rebuild vector retrieval data
8. refresh usage snapshot
9. record source success or source error status

### Usage snapshots

`qpg usage refresh --source <name>` MUST collect index usage signals from PostgreSQL and store a local snapshot at `${XDG_STATE_HOME:-~/.local/state}/qpg/usage/<source>.jsonl`.

`qpg update` and source auto-refresh MUST also refresh usage snapshots.

### Context generation

`qpg context generate` MUST be explicit-only.

Contracts:

- it MUST never run automatically during normal update flows
- OpenAI-backed generation MAY use schema metadata and optional usage evidence
- generated context MUST be written into the same `contexts` table
- generated OpenAI context MUST target table objects using `qpg://<source>/<schema.table>`
- generated table context MUST be inherited by the table and its column objects through normal context materialization
- operator-provided index-usage ingestion MAY be used as an explicit workflow
- `context generate --use-latest-usage` MUST read the latest local usage snapshot and MAY include matching table-level usage evidence in the prompt input
- `context generate --from index-usage` MUST accept JSON arrays and JSONL input
- `context generate --from index-usage` records MUST require `schema`, `table` or `table_name`, `index` or `index_name`, and `unused_days`
- `context generate --from index-usage` records MAY include `source`, `as_of`, and `idx_scan`
- records with a non-matching `source` value MUST be skipped
- managed index-usage context MUST target matching index objects by object-id fragment and MUST NOT overwrite manual context unless explicitly requested

## CLI Contract

The stable command surface MUST be:

- `init`
- `config`
- `source add`
- `source list`
- `source rm`
- `source rename`
- `usage refresh`
- `context add`
- `context list`
- `context rm`
- `context generate`
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

Stable output and filtering flags include:

- `--json`
- `--files`
- `-n`
- `--all`
- `--min-score`
- `--schema`
- `--kind`
- `--source`

CLI argument contract:

- `--schema` on `source add` MUST be repeatable and MUST add entries to `include_schemas`
- `--skip-pattern` on `source add` MUST be repeatable and MUST add glob entries to `skip_patterns`
- `--kind` on retrieval commands MUST accept only documented object kinds
- unsupported commands, flags, or flag combinations MUST fail through CLI argument parsing with a non-zero exit status
