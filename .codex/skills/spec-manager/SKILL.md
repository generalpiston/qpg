---
name: spec-manager
description: Use when creating, editing, reviewing, or extending the qpg spec set under specs/, including product behavior, workflow semantics, configuration interfaces, persistent state contracts, integration boundaries, confirmation rules, and acceptance criteria.
---

# Trigger

Use this skill when the task changes or reviews the qpg spec files under `specs/`.

Activate it for work on:

- externally observable behavior
- system invariants
- configuration or CLI interfaces
- workflow semantics
- persistent state contracts
- integration or confirmation boundaries
- acceptance criteria

# Purpose

The spec is the behavioral source of truth for qpg. Treat it as a contract for what the system
MUST do, not as a blueprint for how the code must be organized internally.

The canonical spec lives under `specs/`. Read the relevant files there before changing contract behavior.

The spec MUST define:

- contracts
- invariants
- defaults
- allowed values
- failure behavior
- side effects
- security boundaries

The spec MUST NOT freeze:

- internal module layout
- class or function names
- algorithms
- prompt wording
- low-level implementation details

# Actions

1. Read the relevant sections before changing anything.
2. Identify the externally observable behavior or invariant being added, changed, or removed.
3. Decide whether the change belongs in an existing contract or requires a new contract with a distinct responsibility.
4. Write or revise the contract using explicit normative language.
5. State defaults, configurable behavior, allowed values, failure behavior, side effects, and security constraints where relevant.
6. Update related contracts in the same pass so terminology and rules stay aligned.
7. Remove or rewrite implementation detail that is not externally required.

# Guidelines

## Contract Rules

- Prefer behavioral contracts over implementation instructions.
- Define inputs, outputs, allowed values, defaults, failure behavior, and side effects where they matter.
- Keep clear boundaries between interpretation, validation, state transition, and side effects.
- Treat AI as a data-producing boundary only.
- Make configurable behavior explicit and distinguish it from defaults.

## Writing Rules

- Use **MUST**, **SHOULD**, and **MAY** consistently.
- Keep sections short, single-purpose, and easy to scan.
- Prefer concrete requirements over narrative explanation.
- Use examples only to clarify a contract, never to carry it.
- Remove vague phrases such as "handle nicely," "should work," "support somehow," and "etc."

## Consistency Rules

- Keep terminology stable across the spec.
- Update related contracts and acceptance criteria when behavior changes.
- Remove stale or conflicting language in the same pass.
- Do not let the spec drift away from the intended behavior of the system.
