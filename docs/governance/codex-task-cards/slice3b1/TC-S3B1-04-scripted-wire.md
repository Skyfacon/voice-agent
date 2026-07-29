# TC-S3B1-04 Scripted Wire

## Task ID and title

`TC-S3B1-04` — Deterministic protocol-faithful scripted Fake wire. Status:
`not-started`. Historical source: Slice 3B.1 master-plan Task 4.

## Goal

Implement a permit-driven, provider-free event stream that satisfies the shared
transport contract and exercises legal Qwen partial orders without network,
wall-clock scheduling, credentials, raw fixtures, or local authority.

## Allowed write files

- Create: `src/voice_agent/adapters/qwen_realtime/scenarios.py`
- Create: `src/voice_agent/adapters/qwen_realtime/scripted_wire.py`
- Create: `tests/adapters/qwen_realtime/test_scripted_wire.py`
- Create: `tests/adapters/qwen_realtime/test_scripted_wire_security.py`

## Required read-only dependencies

- [TC-S3B1-03](TC-S3B1-03-protocol-and-transport.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`
- `tests/adapters/qwen_realtime/transport_contract_suite.py`

## Exact ADR sections

- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Decision`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Validation Method`

## Input and output contracts

Input is Card 03's `QwenRealtimeTransport` and validated event types. Output is
`WireStep`, `QwenWireScript`, `SyntheticPayloadKind`,
`get_qwen_wire_script(scenario_id)`, `ScriptedFakeQwenWire`,
`release_next_server_event()`, and `safe_timeline()`.

`open()` creates only physical readiness; `send()` exactly consumes the next
client step; `recv()` has one queue consumer and waits for an explicit permit;
`close()` wakes blocked receive and wipes queued material. Fake-only permit
controls do not enter the shared protocol. `wire_seq` and `virtual_ms` are
scheduler evidence only and never Adapter correlation authority.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-ADAPTER-01`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-PRIVACY-03`
- `INV-CONCURRENCY-02`
- `INV-CONCURRENCY-04`
- `INV-FOREGROUND-01`

## Non-goals

- No network, provider SDK, credential, real sleep, randomness, or environment.
- No canonical event, RouterDecision, Gate result, local ID, or playback.
- No PCM/base64, prompt, unrestricted transcript, real-user text, or local path
  stored in a scenario definition.
- No claim that missing provider ordinals/checksums can detect arbitrary delta
  omission or permutation.

## Implementation outline

1. Verify Card 03 and invoke its unchanged transport conformance suite.
2. Define immutable scripts from provider-shaped safe templates and symbolic
   payload factories.
3. Materialize bounded synthetic text and wipeable PCM only at release time;
   never write material back to the script.
4. Advance one server event per explicit permit and require exact client-step
   matching, including `session.update` before `session.updated`.
5. Prove deterministic reruns and source safety with socket, environment,
   sleep, randomness, payload, and authority negative tests.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire_security.py -q
git diff --check -- src/voice_agent/adapters/qwen_realtime/scenarios.py src/voice_agent/adapters/qwen_realtime/scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire.py tests/adapters/qwen_realtime/test_scripted_wire_security.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

The shared transport suite passes against the Fake; repeated scripts have
identical safe timelines; multiple appends require no per-frame
acknowledgement; bootstrap ordering is enforced; terminal close is bounded; no
forbidden source or authority dependency is present.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop on a network/credential/time/random
dependency, Fake-emitted route/Gate/local authority, stored raw payload, or any
attempt to add Fake-only controls to the shared transport.

## Evidence and handoff

Record scenario IDs, conformance result, repeatability result, source-safety
checks, and relative changed paths. Hand the provider-shaped event source and
permit driver to `TC-S3B1-06`; retain materialized payloads only in wipeable
memory and never in the evidence handoff.
