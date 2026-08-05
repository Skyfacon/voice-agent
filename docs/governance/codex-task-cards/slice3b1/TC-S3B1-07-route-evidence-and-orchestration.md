# TC-S3B1-07 Route Evidence and Orchestration

## Task ID and title

`TC-S3B1-07` — Bounded context, independent Route Evidence, Local Router input,
and join-only orchestration. Status: `not-started`. Historical source: Slice
3B.1 master-plan Task 7.

## Goal

Build immutable bounded context projections, separate route and candidate-safety
adapter operations, one mutually exclusive Local Router evidence branch, and a
join-only Fast Interaction output without moving authority into any model.

## Allowed write files

- Create: `src/voice_agent/adapters/route_evidence_contract.py`
- Create: `src/voice_agent/adapters/route_evidence_fake.py`
- Create: `src/voice_agent/runtime/slice3b1/context_projection.py`
- Create: `src/voice_agent/runtime/slice3b1/orchestrator.py`
- Modify: `src/voice_agent/router/router.py`
- Create: `tests/adapters/test_route_evidence_fake.py`
- Create: `tests/runtime/test_slice3b1_context_projection.py`
- Create: `tests/runtime/test_slice3b1_orchestrator.py`
- Create: `tests/router/test_adr018_route_evidence_router.py`
- Regression test: `tests/router/test_router_task_focus_mvp1.py`
- Regression test: `tests/runtime/test_mvp63_live_fast_interaction_evidence.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- [TC-S3B1-02](TC-S3B1-02-capabilities-and-assembly.md)
- [TC-S3B1-05](TC-S3B1-05-candidate-quarantine.md)
- [TC-S3B1-06](TC-S3B1-06-session-lifecycle.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-006 Router Task Focus and Single Active SlowTask MVP.md` — `Decision`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md` — `Decision`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md` — `ADR-018 Capability Addendum`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `Decision`
- `docs/adr/ADR-017 Fast Interaction Adapter and Foreground Act Contract.md` — `ADR-018 Topology Compatibility Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Inputs are canonical final ASR, bounded current-session state, Card 05 transcript
completion/full completion metadata, Card 02 profile facts, and Card 06 current
generation. Output is strict `RouteEvidenceRequestV1`,
`RouteEvidenceOutputV1`, `CandidateSafetyRequestV1`,
`CandidateSafetyEvidenceV1`, `build_context_projection(...)`,
the optional Route Evidence branch of `MVP1Router.emit_decision(...)`, and
`ParallelFastInteractionOrchestrator.emit(...)`.

`RouteEvidenceAdapter` has exactly these classification signatures:

```python
async def classify_route(
    self, request: RouteEvidenceRequestV1
) -> RouteEvidenceOutputV1: ...
async def classify_candidate_safety(
    self, request: CandidateSafetyRequestV1
) -> CandidateSafetyEvidenceV1: ...
```

Route classification receives final ASR and route context, never the candidate.
Candidate safety receives a complete transcript only through a scoped opaque
ref and immutable digest, never PCM. The orchestrator joins recorded
provenance; Local Router alone decides route/task focus, and Gate alone may
release. The `Regression test:` paths above are read-only verification inputs,
not authorized edits.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-ADAPTER-01`
- `INV-ADAPTER-02`
- `INV-JOURNAL-01`
- `INV-PLAN-01`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-04`
- `INV-FOREGROUND-06`

## Non-goals

- No candidate-visible route classification or raw PCM in safety evidence.
- No provider conversation as authoritative task/confirmation/session memory.
- No model call, RouterDecision, Gate invocation, or release by orchestrator.
- No durable cross-session memory or multiple active SlowTasks.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify predecessors and freeze role-specific bounded projection limits.
2. Resolve ephemeral text only inside each adapter call; canonical events retain
   refs, digests, enums, confidence, and safe provenance.
3. Fail closed on timeout, malformed/oversized schema, invalid enum,
   insufficient confidence, uncertainty, or prohibited flags.
4. Add a mutually exclusive Router branch that validates final-ASR, turn,
   utterance, mode, and adapter provenance before Local Router derives route.
5. Join final ASR, route evidence, candidate safety, full candidate completion,
   context snapshot, generation, and exact digests into the two canonical fast
   events without calling models or Gate.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/test_route_evidence_fake.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/router/test_adr018_route_evidence_router.py tests/router/test_router_task_focus_mvp1.py tests/runtime/test_mvp63_live_fast_interaction_evidence.py -q
git diff --check -- src/voice_agent/adapters/route_evidence_contract.py src/voice_agent/adapters/route_evidence_fake.py src/voice_agent/runtime/slice3b1/context_projection.py src/voice_agent/runtime/slice3b1/orchestrator.py src/voice_agent/router/router.py tests/adapters/test_route_evidence_fake.py tests/runtime/test_slice3b1_context_projection.py tests/runtime/test_slice3b1_orchestrator.py tests/router/test_adr018_route_evidence_router.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

Route and safety schemas are strict and independently timed; context is bounded
and session-only; all route/task-focus cases preserve Local Router authority;
both completion orders join deterministically; digest/correlation mismatches
fail closed; legacy Router and Fast Interaction paths remain green.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if route classification sees the
candidate, provider memory becomes authoritative, Router authority moves, the
orchestrator calls a model/Gate, or a ref is retained beyond its lease. Editing
a `Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record projection bounds, adapter mode/schema outcomes, route cardinality,
orchestrator join provenance, fail-closed cases, safe test counts, and relative
changed paths. Hand only recorded events and immutable completion facts to
`TC-S3B1-08`, `TC-S3B1-09`, and `TC-S3B1-10`.
