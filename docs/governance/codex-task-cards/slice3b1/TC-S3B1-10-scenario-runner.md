# TC-S3B1-10 Scenario Runner

## Task ID and title

`TC-S3B1-10` — Controller-owned ingress, deterministic scenario runner, and
stable safe result. Status: `not-started`. Historical source: Slice 3B.1
master-plan Task 10.

## Goal

Assemble Cards 01–09 into the provider-free scenario catalog while preserving
Interaction Controller authority, one-use projection contracts, deterministic
replay, and a single safe public serialization boundary.

## Allowed write files

- Create: `src/voice_agent/runtime/slice3b1/__init__.py`
- Create: `src/voice_agent/runtime/slice3b1/contracts.py`
- Create: `src/voice_agent/runtime/slice3b1/scenarios.py`
- Create: `src/voice_agent/runtime/slice3b1/ingress.py`
- Create: `src/voice_agent/runtime/slice3b1/runner.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/runtime/test_slice3b1_result_schema.py`
- Create: `tests/runtime/test_slice3b1_ingress.py`
- Create: `tests/runtime/test_slice3b1_runner.py`
- Create: `tests/acceptance/test_slice3b1_acceptance_scenarios.py`
- Regression test: `tests/duplex/test_mock_audio_accept.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- [TC-S3B1-02](TC-S3B1-02-capabilities-and-assembly.md)
- [TC-S3B1-03](TC-S3B1-03-protocol-and-transport.md)
- [TC-S3B1-04](TC-S3B1-04-scripted-wire.md)
- [TC-S3B1-05](TC-S3B1-05-candidate-quarantine.md)
- [TC-S3B1-06](TC-S3B1-06-session-lifecycle.md)
- [TC-S3B1-07](TC-S3B1-07-route-evidence-and-orchestration.md)
- [TC-S3B1-08](TC-S3B1-08-gate-and-release.md)
- [TC-S3B1-09](TC-S3B1-09-replay.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Decision`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Commit Boundary Definition`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `ADR-018 Accepted Addendum`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `Decision`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Decision`
- `docs/adr/ADR-010 Trace Replay Debug Policy for Web Demo.md` — `Validation Method`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `Decision`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `Validation Method`
- `docs/adr/ADR-015 Repository Governance and AGENTS.md Rules.md` — `ADR-018 Repository Review Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Validation Method`

## Input and output contracts

Inputs are a catalog scenario ID and the verified contracts from Cards 01–09.
Outputs are `run_slice3b1_scenario_async(...)`,
`run_slice3b1_scenario(...)`, `Slice3B1RunV1`, and
`Slice3B1RunV1.to_safe_dict()`. The result is the sole public serialization
boundary later consumed by CLI B.

`Slice3B1IngressProjector` maps safe Qwen boundary projections to canonical
Duplex evidence, but
`InteractionController.resolve_audio_ingress(...) -> AudioIngressResolutionV1`
alone decides commit or rejection. The runner consumes completion projections
exactly once, uses public contracts only, and never inspects Session Adapter or
Quarantine private state. Invalid/fault scenarios return a safe terminal result;
unexpected invariant or programmer errors raise `Slice3B1RunnerError` without
raw payloads.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-CONCURRENCY-01`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-02`
- `INV-FOREGROUND-03`
- `INV-VERIFY-02`

## Non-goals

- No real transport, provider credential, native PCM, Talker, Page C, tool
  side effect, or new architecture capability.
- No ingress adjudication by the runner/projector and no access to private
  quarantine/session state.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify Cards 01–09 and snapshot the stable safe result schema in a RED test.
2. Implement immutable result/nested projections with no raw transcript, PCM,
   provider body, credential, prompt, object handle, or unrestricted exception.
3. Freeze the historical scenario catalog and expected safe terminal summaries.
4. Route boundary evidence through the projector into the Interaction
   Controller, then orchestrate public contracts in canonical order.
5. Assert deterministic reruns, ingress terminal exclusivity, authority
   cardinality, replay success, and the universal no-native-release claims.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/acceptance/test_slice3b1_acceptance_scenarios.py tests/duplex/test_mock_audio_accept.py -q
git diff --check -- src/voice_agent/runtime/slice3b1/__init__.py src/voice_agent/runtime/slice3b1/contracts.py src/voice_agent/runtime/slice3b1/scenarios.py src/voice_agent/runtime/slice3b1/ingress.py src/voice_agent/runtime/slice3b1/runner.py src/voice_agent/interaction/controller.py tests/runtime/test_slice3b1_result_schema.py tests/runtime/test_slice3b1_ingress.py tests/runtime/test_slice3b1_runner.py tests/acceptance/test_slice3b1_acceptance_scenarios.py tests/duplex/test_mock_audio_accept.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

Every catalog scenario terminates twice with identical safe results; valid
committed scenarios have the required exactly-once authority chain; rejected,
ambient, stale, and malformed scenarios expose no consumable authority; every
ingress has exactly one terminal; replay passes; no release token, playback
outbox, playback span, Talker call, or real/native-success claim appears.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop on catalog/schema drift,
controller-authority bypass, private Quarantine/Session state inspection,
nondeterminism, unsafe result serialization, or native/real enablement.
Editing a `Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record stable schema keys, scenario count, deterministic pair count, ingress
terminal/cardinality matrix, replay outcomes, no-release assertions, safe
changed paths, and command results. Hand only `Slice3B1RunV1` and its safe
serializer to `TC-S3B1-11`.
