# Product And Domain

## Product Identity

`qpg` means **Query PostgreSQL (Schema)**.

`qpg` MUST remain a local-first system for indexing and querying PostgreSQL schema metadata.
`qpg` MUST expose a CLI and MAY expose a constrained MCP server over the local index.

## Scope

### In scope

`qpg` MAY index and retrieve metadata for:

- schemas
- tables
- columns
- constraints
- indexes
- views
- extensions
- functions
- procedures
- comments and normalized definitions associated with those objects

### Out of scope

`qpg` MUST NOT:

- read table row values as part of normal product behavior
- execute arbitrary user SQL against PostgreSQL
- expose EXPLAIN or query planning features
- mutate PostgreSQL state as part of normal usage
- persist row values in the local index

## Core Domain Model

### Source

A `source` is a named PostgreSQL connection target.

Source contract:

- identity MUST be `name -> dsn`
- sources MUST persist in the local SQLite `sources` table
- source names MUST be stable user-facing handles
- DSNs MUST be normalized to enforce readonly behavior in storage and on connect

Source-level filters are part of the source definition and MAY include:

- `include_schemas`
- `skip_patterns`

Source filter contract:

- `include_schemas` MAY contain zero or more schema names
- `skip_patterns` MAY contain zero or more glob patterns
- if `include_schemas` is empty, objects from all visible schemas MUST remain eligible for indexing
- `skip_patterns` MUST match against fully qualified object names and bare object names
- objects matching any `skip_patterns` entry MUST be excluded from indexing

### Context

A `context` is semantic guidance attached to a `qpg://` target.
Its purpose MUST be retrieval guidance, not source-of-truth schema metadata.

Allowed target levels are:

- source: `qpg://work`
- schema: `qpg://work/public`
- object: `qpg://work/public.orders`
- object-id fragment: `qpg://work#<object_id>`

Context rules:

- context MUST be either human-authored or generated through an explicit workflow
- contexts MUST be materialized into `object_context_effective` during indexing
- table-level object context MUST apply to child column objects
- generated context MUST be conservative and MAY skip objects if intent is unclear

### Object identity

Each indexed object MUST have a deterministic content-addressed identifier derived from:

- `source_name`
- `object_type`
- `fqname`

Object ids MUST remain stable across reindexing unless object identity changes.
