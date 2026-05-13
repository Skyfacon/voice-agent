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

Slice 4/5/6 scope:

- SlowTask runtime happy path
- UserPatch evidence construction
- UserPatch interpretation
- material patch plan advance and replanning

Out of scope for this directory through Slice 6:

- stale result adoption runtime
- Tool execution
- Composer, spoken plan, coverage, truthfulness, or frontend UI patch events

All committed fixtures in this directory must keep `fixture_domain=GITHUB_ALLOWED`
and must not contain raw audio, raw trace, secrets, unredacted real user input,
unredacted tool results, or large raw web content.
