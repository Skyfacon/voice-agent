# Development Test Environment

This repository uses one canonical test entrypoint:

```bash
./scripts/test -q
```

Agents and humans should use this script for pytest runs instead of calling
`pytest`, `python -m pytest`, or `uv --with pytest` directly.

## Why

Different Codex threads may start with different shell PATH values. On this
machine, `pytest` may not be on PATH and `python3` may not have pytest installed,
while `/Users/a123/anaconda3/bin/python` does. A repo-owned test entrypoint keeps
slice work from spending time rediscovering the same runtime details.

## Interpreter Resolution

`./scripts/test` runs offline and tries these interpreters in order:

1. `VOICE_AGENT_PYTHON`, when explicitly set.
2. `.venv/bin/python`, when it exists and already has pytest.
3. `/Users/a123/anaconda3/bin/python`, when it exists and already has pytest.
4. `python3`, when it already has pytest.

The script never installs packages, never invokes `uv --with`, and never fetches
from PyPI. If no candidate has pytest, it fails with setup instructions instead
of silently changing the environment.

## Recommended Commands

Run the current full test suite:

```bash
./scripts/test -q
```

Run a slice-specific subset:

```bash
./scripts/test tests/replay/test_fixture_safety.py tests/events/test_event_journal.py -q
```

If a thread needs an explicit interpreter:

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test -q
```

## Dependency Policy

The project declares pytest as a dev dependency in `pyproject.toml`, but slice
implementation threads should not perform network dependency installation unless
the user explicitly approves it. Prefer an already-provisioned interpreter and
record the exact test command used in the final report.
