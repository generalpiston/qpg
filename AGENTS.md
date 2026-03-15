# AGENTS.md

## Assessment Rules

- Any change to behavior, defaults, invariants, acceptance criteria, CLI semantics, MCP semantics, configuration semantics, storage contracts, or security boundaries SHOULD update the relevant file in `specs/`.
- Any change to a file under `specs/` SHOULD trigger review of [README.md](/Users/abe/Projects/generalpiston/query-tools/qpg/README.md), [docs/architecture.md](/Users/abe/Projects/generalpiston/query-tools/qpg/docs/architecture.md), [docs/cli.md](/Users/abe/Projects/generalpiston/query-tools/qpg/docs/cli.md), and [docs/mcp.md](/Users/abe/Projects/generalpiston/query-tools/qpg/docs/mcp.md) for alignment.
- Behavioral contracts belong in [specs/](/Users/abe/Projects/generalpiston/query-tools/qpg/specs), not in `AGENTS.md`.
- Architecture explanation belongs in [docs/architecture.md](/Users/abe/Projects/generalpiston/query-tools/qpg/docs/architecture.md); architectural invariants belong in `specs/`.
- When a request appears to conflict with the spec set, assess the spec impact first.

## Skills

### Available skills

- `spec-manager`: Use when creating, editing, reviewing, or extending the qpg spec set under `specs/`, including product behavior, workflow semantics, configuration interfaces, persistent state contracts, integration boundaries, confirmation rules, and acceptance criteria. File: `/Users/abe/Projects/generalpiston/query-tools/qpg/.codex/skills/spec-manager/SKILL.md`

### Skill routing

- Use `spec-manager` only for work touching files under `specs/`.
- README and files under `docs/` are not managed by `spec-manager`; they should be checked for alignment when specs change.
- Keep spec language behavioral and normative. Do not freeze internal module layout, function names, algorithms, or prompt wording unless externally required.
