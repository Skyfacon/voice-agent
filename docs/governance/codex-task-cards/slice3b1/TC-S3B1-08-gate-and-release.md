# TC-S3B1-08 Gate and Release

## Task ID and title

`TC-S3B1-08` — Default fail-closed parallel Gate and isolated contract-only
release boundary. Status: `not-started`. Historical source: Slice 3B.1
master-plan Task 8.

## Goal

Keep the normal provider-free runner incapable of native release while proving
the complete immutable token comparison, atomic journal batch, and memory-only
outbox contract through a private test-only harness.

## Allowed write files

- Create: `src/voice_agent/runtime/slice3b1_release.py`
- Modify: `src/voice_agent/runtime/fast_foreground_gate.py`
- Modify: `src/voice_agent/events/journal.py`
- Modify: `tests/qwen_slice3b1_support.py`
- Create: `tests/events/test_event_journal_atomic_batch.py`
- Create: `tests/runtime/test_slice3b1_default_gate.py`
- Create: `tests/runtime/test_slice3b1_release_contract.py`
- Regression test: `tests/events/test_event_journal.py`
- Regression test: `tests/runtime/test_mvp63_fast_foreground_gate.py`
- Regression test: `tests/runtime/test_mvp63_fast_interaction_provenance.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- [TC-S3B1-02](TC-S3B1-02-capabilities-and-assembly.md)
- [TC-S3B1-05](TC-S3B1-05-candidate-quarantine.md)
- [TC-S3B1-06](TC-S3B1-06-session-lifecycle.md)
- [TC-S3B1-07](TC-S3B1-07-route-evidence-and-orchestration.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `Decision`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `ADR-018 Canonical Event Addendum`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `Decision`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `ADR-018 Topology Compatibility Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Inputs are validated mock assembly/snapshot digest, current reducer bindings,
recorded Router/route/safety/candidate events, and Card 05 immutable eligibility
facts. Output is `ForegroundReleaseTokenV1`,
`ParallelForegroundGateContextV1`, `PlaybackOutboxItemV1`,
`InMemoryPlaybackOutbox`, `build_slice3b1_gate_context(...)`,
`run_parallel_fast_foreground_gate(...)`, and synchronous prevalidated
`InMemoryEventJournal.append_atomic_batch(...)`.

The isolated test contract is
`_compare_authorize_and_enqueue_contract_only(...)`; it stays private, absent
from package `__all__`, and reachable only from focused unit tests. Test-only
builders are `valid_fast_router_event()`, `valid_route_evidence_event()`,
`valid_safe_candidate_evidence_event()`,
`valid_default_parallel_context()`, and `gate_event_ids(case_id: str)`.

Normal context derives `output_mode=mock` and
`native_pcm_enabled=false`; it accepts no enable boolean and creates no token,
commit, or outbox item. The private contract primitive is absent from exports
and production runner/CLI imports. Historical `Regression test:` paths are
read-only verification inputs, not authorized edits.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-JOURNAL-02`
- `INV-PRIVACY-01`
- `INV-CONCURRENCY-05`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-02`
- `INV-FOREGROUND-03`

## Non-goals

- No native PCM authorization, Talker call, playback, or qualification claim.
- No caller-selectable native capability or reuse as the Slice 3B.2 authority.
- No public contract-only harness or production import path.
- No network await, model call, clock read, token restamping, or cross-thread
  transaction claim inside compare-and-authorize.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify predecessors and preserve overlap-sensitive legacy Gate/Journal work.
2. Build Gate context only from validated assembly, recorded snapshot, current
   binding, exact evidence, candidate identities/digests, and policy checks.
3. Make the default branch append one fail and one terminal discard for every
   disabled, stale, mismatched, unsafe, non-fast, or incomplete input.
4. Keep the contract-only primitive private; compare every immutable field,
   preflight outbox capacity, atomically append pass+commit, then perform an
   infallible memory-only reservation.
5. Test every field mismatch and every second-envelope/outbox fault for zero
   partial authority mutation.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/events/test_event_journal_atomic_batch.py tests/events/test_event_journal.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py tests/runtime/test_mvp63_fast_foreground_gate.py tests/runtime/test_mvp63_fast_interaction_provenance.py -q
git diff --check -- src/voice_agent/events/journal.py src/voice_agent/runtime/slice3b1_release.py src/voice_agent/runtime/fast_foreground_gate.py tests/events/test_event_journal_atomic_batch.py tests/events/test_event_journal.py tests/runtime/test_slice3b1_default_gate.py tests/runtime/test_slice3b1_release_contract.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

The normal path always fails closed without token/outbox/commit; the isolated
contract passes only exact bindings and labels itself non-qualification; every
fault leaves journal sequence/storage and outbox unchanged; valid batches are
consecutive and causal; all legacy Journal and Gate tests remain green.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if the normal runner creates a token
or outbox, the harness becomes public, append can partially commit, a caller
can enable PCM, or legacy Gate behavior drifts. Editing a `Regression test:`
path is write-set expansion and requires stopping.

## Evidence and handoff

Record default fail reason, zero token/outbox proof, mismatch/fault matrix
counts, atomic sequence evidence, import-surface check, safe test counts, and
relative changed paths. Hand the canonical fail/pass/disposition and exact
token-ref contract to `TC-S3B1-09` and the default fail-closed API to
`TC-S3B1-10`.
