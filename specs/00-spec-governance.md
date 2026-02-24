# Spec Governance

## Purpose

The files in `specs/` are the canonical behavioral contract for `qpg`.

If implementation, tests, prompts, or documentation conflict with the spec set, the spec set MUST win unless the user explicitly requests a deliberate versioned redesign.

The spec set MUST define externally observable behavior, invariants, defaults, allowed values, failure behavior, side effects, and security boundaries where relevant.
The spec set MUST NOT freeze internal module layout, class names, function names, algorithms, prompt wording, or other implementation detail unless that detail is externally observable.

## Reading Order

Read these files together as the canonical contract:

1. `00-spec-governance.md`
2. `01-product-and-domain.md`
3. `02-security-and-storage.md`
4. `03-retrieval-and-model.md`
5. `04-features-and-cli.md`
6. `05-mcp-and-config.md`
7. `06-testing-and-change-management.md`

## Conflict Handling

If a request conflicts with the spec set:

1. the conflict MUST be stated clearly
2. a versioned migration path SHOULD be proposed, such as a `v2` feature gate
3. current behavior MUST be preserved by default unless the user explicitly approves the change

## Documentation Alignment

- README and docs that describe behavioral contracts MUST stay aligned with the spec set
- behavioral contracts SHOULD be written in `specs/` and referenced elsewhere rather than duplicated
