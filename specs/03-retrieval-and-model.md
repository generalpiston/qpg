# Retrieval And Model

## Retrieval Contract

### Retrieval inputs

Retrieval inputs MUST be derived from schema metadata only:

- names
- comments
- normalized definitions and synthesized structure text
- effective context

### `search`

`search` MUST be lexical retrieval over local FTS5 documents using BM25.

Contract:

- `search` MUST query multi-field materialized docs
- `search` MUST treat context as a first-class signal
- `search` MUST support filtering by source, schema, and kind

### `vsearch`

`vsearch` MUST be local vector similarity over `object_vectors`.

Contract:

- `vsearch` MUST be enabled by default
- `vsearch` MUST be treated as a required retrieval capability
- `vsearch` MUST use the local cached model initialized by `qpg init`

### `query`

`query` MUST be deterministic blended retrieval.

Contract:

1. deterministic query expansion
2. lexical candidate retrieval
3. vector candidate retrieval
4. reciprocal rank fusion with `k=60`
5. top-rank bonus in fused score
6. optional rerank hook applied after fusion

If reranking fails, fused order MUST remain the fallback.

## Model Contract

Default embedding model contract:

- model repo: `microsoft/codebert-base`
- cache path: `${XDG_CACHE_HOME:-~/.cache}/qpg/models/microsoft__codebert-base`
- embedding dimension: `768`
- model assets MUST be initialized explicitly via `qpg init`

Model usage rules:

- core retrieval MUST use local inference
- no external vector service is required
- vector retrieval MUST remain available even when optional local vector-extension acceleration is unavailable
- optional LLM workflows MUST remain explicit and separate from core retrieval

## Retrieval Invariants

- The `query` retrieval pipeline MUST preserve this order: deterministic expansion, lexical retrieval, vector retrieval, reciprocal rank fusion, optional rerank hook.
- The optional rerank hook MUST be advisory only and MUST NOT replace lexical or vector candidate generation.
