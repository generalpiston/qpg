# AGENTS.md

## Assessment Rules

- Any change to behavior, defaults, invariants, acceptance criteria, CLI semantics, MCP semantics, configuration semantics, storage contracts, or security boundaries SHOULD update [docs/spec.md](/Users/abe/Projects/generalpiston/qpg/docs/spec.md).
- Any change to the canonical contract SHOULD trigger review of [README.md](/Users/abe/Projects/generalpiston/qpg/README.md), [docs/architecture.md](/Users/abe/Projects/generalpiston/qpg/docs/architecture.md), [docs/cli.md](/Users/abe/Projects/generalpiston/qpg/docs/cli.md), and [docs/mcp.md](/Users/abe/Projects/generalpiston/qpg/docs/mcp.md) for alignment.
- Behavioral contracts belong in [docs/spec.md](/Users/abe/Projects/generalpiston/qpg/docs/spec.md), not in `AGENTS.md`.
- Architecture explanation belongs in [docs/architecture.md](/Users/abe/Projects/generalpiston/qpg/docs/architecture.md); usage guidance belongs in the task-specific docs.
- When a request appears to conflict with the canonical contract, assess the contract impact first.

## Skills

### Available skills

- `spec-manager`: Use when creating, editing, reviewing, or extending the canonical qpg contract under `docs/spec.md`, including product behavior, workflow semantics, configuration interfaces, persistent state contracts, integration boundaries, confirmation rules, and acceptance criteria. File: `/Users/abe/Projects/generalpiston/qpg/.codex/skills/spec-manager/SKILL.md`

### Skill routing

- Use `spec-manager` for work touching `docs/spec.md`.
- README and task-specific files under `docs/` should be checked for alignment when the canonical contract changes.
- Keep spec language behavioral and normative. Do not freeze internal module layout, function names, algorithms, or prompt wording unless externally required.
