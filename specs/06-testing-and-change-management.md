# Testing And Change Management

## Testing Contract

### Default suite

`uv run pytest` MUST pass quickly without Docker.

### Integration coverage

Opt-in integration tests MUST validate:

- readonly role pass
- elevated role fail
- write attempts are still blocked through `qpg` session guards even for roles with write grants

## Dependency And Tooling Contract

- Python version MUST be `3.13`
- project workflows MUST use `uv`
- `requirements.txt`-based workflows MUST NOT be introduced
- project metadata MUST use PEP 621 in `pyproject.toml`
- the project MUST remain installable via `uv tool install .`
- dependencies declared as core project requirements MUST be treated as present once declared
- import-time fallback behavior that silently degrades missing core dependencies MUST NOT be added

## Change Management

Any change to this spec MUST:

1. update tests in the same change when behavior changes
2. update user-facing docs when behavior changes
3. preserve defaults unless the user explicitly approves a breaking redesign
4. use a versioned or gated migration path when introducing incompatible behavior without explicit approval
