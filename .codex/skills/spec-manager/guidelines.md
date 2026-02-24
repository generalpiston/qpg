# Common Python Backend Coding Guidelines

Use these only when the work covers Python backend code in `jobs/**`, `lib/py/**`, or Python
backends under `api/**`.

Project-owned specs MAY add stricter rules and win on conflicts.

Do not treat this file as authority for project-specific choices such as centralized
configuration, deployment layout, framework selection, or other conventions that vary by
project.

## Baseline

- Python backends MUST use Python 3.13+ unless a project spec documents an exception.
- Dependency management MUST use `uv`.
- Build backends SHOULD use `hatchling`.
- Local shared packages MUST be linked with editable `[tool.uv.sources]` paths.

## Commands

- Install dependencies with `uv sync`.
- Run tests with `uv run pytest ...`.
- Run lint with `uv run ruff check ...`.
- Run formatting with `uv run black ...`.
- Run type checks with `uv run mypy ...` when a package maintains mypy or a project spec requires it.

## Code Shape

- Imports SHOULD appear at module top level.
- Local imports are allowed only for optional dependencies, import-cycle control, startup-cost
  control, or plugin/framework loading.
- Imports MUST be grouped as standard library, third-party, and local modules, with one blank
  line between groups.
- Packages, modules, internal directories, functions, variables, and methods MUST use
  `snake_case`.
- Class names SHOULD be singular unless the class intentionally models a collection or aggregate.
- Driver files SHOULD live under `src/`, for example `src/main.py`.
- Top-level packages SHOULD live under `src/<package_name>`.
- Functions and classes SHOULD have one clear responsibility.
- Prefer classes with explicit constructor dependencies for stateful behavior.
- Reserve free functions for pure utilities, transformations, and framework boundaries.
- Do not introduce pass-through wrapper classes.
- Prefer self-documenting identifiers over explanatory comments.
- Comments SHOULD explain non-obvious invariants, external constraints, protocol requirements,
  and performance tradeoffs.
- Comments SHOULD NOT restate obvious behavior.
- Public functions, methods, and module-level constants MUST include PEP 484 type hints.
- New backend code MUST NOT introduce untyped public APIs.
- `Any` SHOULD be avoided unless required at a third-party boundary.

## Boundaries And Runtime

- External inputs MUST be validated at the owning boundary.
- Validation SHOULD NOT be duplicated across layers without a documented reason.
- Internal layers MAY assume boundary-validated data unless they cross a new trust boundary.
- Code SHOULD fail fast with clear errors.
- Error messages SHOULD identify the invalid input or violated constraint.
- Datetimes MUST be timezone-aware.
- Backend code SHOULD use UTC internally unless a project spec documents another requirement.
- Backend code MUST use the project logging interface rather than `print()`.
- Logs MUST NOT include secrets, access tokens, or raw sensitive data.
- Exceptions SHOULD be logged at the boundary where they are handled.
- Use `async` only for I/O-bound paths that benefit from concurrency.
- Code running in an event loop MUST NOT block on synchronous network, filesystem, or database I/O.
- Sync and async APIs SHOULD NOT be mixed in the same abstraction without a documented reason.

## Errors, Testing, And Dependencies

- Domain layers SHOULD raise domain-meaningful exceptions.
- Framework or transport boundaries MUST translate internal failures into boundary-appropriate
  responses.
- Broad `except Exception` blocks SHOULD be avoided unless they re-raise, protect a process
  boundary, or perform top-level logging.
- New backend behavior MUST include tests covering successful behavior, failure behavior, and
  relevant edge cases.
- Unit tests SHOULD focus on domain logic with fakes or stubs.
- Integration tests SHOULD cover database, queue, network, or framework boundaries when behavior
  depends on them.
- Prefer the standard library unless an external package materially improves correctness,
  maintainability, or security.
- New dependencies MUST be justified in the change description.
- Dependencies SHOULD be version-constrained and pinned when stability matters.
- Remove unused code, flags, configuration, and dependencies when touched.

## Size And Cohesion

- Modules and classes SHOULD remain small enough to preserve cohesion, readability, and
  testability.
- Size alone is NOT a reason to split code.
- Code SHOULD be split when doing so improves responsibility boundaries, readability, or
  testability.
- Project specs MAY define stricter size limits.

## Disallowed Patterns

- Do not use mutable module-level state for request or job execution state.
- Do not use `print()` for backend logging.
- Do not use bare `except:` blocks.
- Do not hide network or database I/O behind misleading pure-sounding APIs.
- Do not introduce implicit global service locators without project-spec approval.

## Enforcement

- Code review MUST block violations of these `MUST` requirements when a spec adopts them.
- Project specs SHOULD reference this baseline when they inherit it.
- Lint rules and tests SHOULD enforce applicable parts of the contract where practical.
