# TC-S3B1-09 Replay

## Task ID and title

`TC-S3B1-09` — Deterministic ADR-018 parallel-chain replay, reducer, and
conditional digest. Status: `not-started`. Historical source: Slice 3B.1
master-plan Task 9.

## Goal

Make the complete provider-free parallel chain replayable from canonical events
alone, with bounded safe state, strict correlation validation, and no change to
legacy digest shape when ADR-018 events are absent.

## Allowed write files

- Create: `src/voice_agent/state/qwen_parallel_state.py`
- Modify: `src/voice_agent/state/adapter_health_state.py`
- Modify: `src/voice_agent/replay/runner.py`
- Modify: `src/voice_agent/replay/state_digest.py`
- Create: `tests/replay/test_adr018_parallel_replay.py`
- Create: `tests/state/test_qwen_parallel_state.py`
- Regression test: `tests/replay/test_mvp63_audio_native_fast_interaction_replay.py`
- Regression test: `tests/replay/test_mvp5_live_route_replay.py`
- Regression test: `tests/state/test_state_digest.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- [TC-S3B1-06](TC-S3B1-06-session-lifecycle.md)
- [TC-S3B1-07](TC-S3B1-07-route-evidence-and-orchestration.md)
- [TC-S3B1-08](TC-S3B1-08-gate-and-release.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `Decision`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `Canonical MVP-0 Event Registry`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md` — `ADR-018 Canonical Event Addendum`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Decision`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Validation Method`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Input is the canonical event sequence produced by Cards 01, 06, 07, and 08,
including safe opaque refs, exact generations, snapshot identities, and
terminal dispositions. Outputs are `QwenParallelState.reduce_event(...)`,
`QwenParallelState.to_digest_dict()`, `ReplayResult.qwen_parallel_state`, and a
conditional `qwen_parallel_state_hash`.

The replay runner consumes canonical events only. It never calls a model,
adapter, Fake, network, tool, clock, transcript store, PCM source, or provider
wire reconstruction. The new hash is present only when an ADR-018 event was
seen; legacy replay output remains byte-shape compatible.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-JOURNAL-02`
- `INV-PRIVACY-01`
- `INV-CONCURRENCY-04`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-02`
- `INV-VERIFY-02`

## Non-goals

- No provider/Fake rerun, transcript or PCM reconstruction, model evaluation,
  tool execution, clock read, or new event name.
- No broadening of legacy replay or digest semantics.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify predecessor cards and inspect overlap-sensitive replay diffs.
2. Add a bounded `QwenParallelState` reducer for context transitions, evidence
   IDs, candidate identity/disposition, handoff, and delivery terminals.
3. Validate the canonical chain, exact source refs/digests, legal generation
   fences, unique terminals, and release-token continuity.
4. Integrate reducer ownership, safe adapter outcomes, approved data-plane
   refs, and the conditional digest without altering legacy shape.
5. Add deterministic happy/rejected replay cases plus mutations for ordering,
   identity, generation, terminal uniqueness, and zero external calls.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/replay/test_adr018_parallel_replay.py tests/state/test_qwen_parallel_state.py tests/replay/test_mvp63_audio_native_fast_interaction_replay.py tests/replay/test_mvp5_live_route_replay.py tests/state/test_state_digest.py -q
git diff --check -- src/voice_agent/state/qwen_parallel_state.py src/voice_agent/state/adapter_health_state.py src/voice_agent/replay/runner.py src/voice_agent/replay/state_digest.py tests/replay/test_adr018_parallel_replay.py tests/state/test_qwen_parallel_state.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

Two runs of each canonical fixture produce identical state digests; rejected
ingress yields zero downstream authority; illegal order, correlation,
generation, duplicate terminal, or changed release-token ref fails closed;
every ADR-018 event is reducer-owned; legacy replay tests and digest shape stay
green; no external entry point is invoked.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if replay depends on noncanonical
payloads, external calls, clocks, randomness, async scheduling order, or
reconstructs provider/Fake/model data; stop on unsafe retention or legacy
digest drift.
Editing a `Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record deterministic digest pairs, reducer-owned event coverage, mutation
failure counts, zero-call probes, legacy-shape evidence, safe changed paths,
and command results. Hand the stable replay result and conditional digest
contract to `TC-S3B1-10` and `TC-S3B1-11`.
