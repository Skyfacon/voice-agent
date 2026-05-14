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

Slice 4/5/6/7/8/9 scope:

- SlowTask runtime happy path
- UserPatch evidence construction
- UserPatch interpretation
- material patch plan advance and replanning
- SlowTask-led evidence review
- context-resolved ambiguity with argument provenance
- missing critical slot clarification and waiting-slot state
- stale ToolResult default recording without adoption
- explicit stale evidence adoption before current-plan reuse
- cancel confirmation through UserPatch interpretation and terminal cancellation
- switch-task confirmation accepted path with cancel-then-later-spawn
- switch-task confirmation rejected path preserving the active task

Slice 10 scope:

- MVP-1 acceptance manifest over all required synthetic scenario IDs
- closeout checks for replay determinism, state digests, repo-safe privacy flags,
  MVP-2/MVP-3 scope exclusion, and ADR compliance
- lightweight synthetic eval metadata for patch focus correctness, ambiguity
  no-patch behavior, and UserPatch interpretation materiality

Out of scope for this directory through Slice 10:

- Tool execution
- Composer, spoken plan, coverage, truthfulness, or frontend UI patch events
- pause/resume or multiple active SlowTasks

All committed fixtures in this directory must keep `fixture_domain=GITHUB_ALLOWED`
and must not contain raw audio, raw trace, secrets, unredacted real user input,
unredacted tool results, or large raw web content.
