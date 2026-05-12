# MVP-1 Replay Fixtures

This directory starts the MVP-1 replay fixture suite with repo-safe, synthetic,
minimal fixtures only.

Slice 0/1 scope:

- fixture safety skeleton
- empty deterministic replay fixture
- MVP-1 event registry validation through unit tests

Slice 2/3 scope:

- TaskFocusState router decision replay fixture
- SlowTaskState reducer skeleton replay fixtures
- completed, cancelled, and failed terminal sticky behavior

Out of scope for this directory through Slice 3:

- SlowTask runtime behavior
- UserPatch construction
- UserPatch interpretation
- Tool execution
- Composer, spoken plan, coverage, truthfulness, or frontend UI patch events

All committed fixtures in this directory must keep `fixture_domain=GITHUB_ALLOWED`
and must not contain raw audio, raw trace, secrets, unredacted real user input,
unredacted tool results, or large raw web content.
