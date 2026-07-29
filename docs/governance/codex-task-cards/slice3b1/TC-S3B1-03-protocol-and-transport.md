# TC-S3B1-03 Protocol and Transport

## Task ID and title

`TC-S3B1-03` — Typed Qwen protocol and Fake/Real-shared transport contract.
Status: `not-started`. Historical source: Slice 3B.1 master-plan Task 3.

## Goal

Freeze validated client/server event types, safe wire metadata, ordered
projection frames, and one transport interface that the provider-free Fake and
future Real transport must satisfy unchanged.

## Allowed write files

- Create: `src/voice_agent/adapters/qwen_realtime/__init__.py`
- Create: `src/voice_agent/adapters/qwen_realtime/protocol.py`
- Create: `src/voice_agent/adapters/qwen_realtime/transport.py`
- Create: `src/voice_agent/adapters/qwen_realtime/projections.py`
- Create: `tests/adapters/qwen_realtime/test_protocol.py`
- Create: `tests/adapters/qwen_realtime/test_transport_contract.py`
- Create: `tests/adapters/qwen_realtime/transport_contract_suite.py`

## Required read-only dependencies

- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`
- `docs/specs/model-adapter-capabilities.md`

This card has no Task Card predecessor. It defines the contract consumed by
Cards 04, 05, and 06.

## Exact ADR sections

- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Decision`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `Decision`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md` — `Decision`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Input is the documented Qwen Audio Realtime protocol shape locked by the
accepted Slice 3B.1 design. Output includes `QwenClientEvent`,
`QwenServerEvent`, `QwenSessionConfiguration`,
`encode_client_event(...)`, `parse_server_event(...)`,
`safe_wire_metadata(...)`, `QwenRealtimeTransport`,
`QwenProjectionFrameV1`, and asynchronous
`QwenProjectionSink.accept(frame)`.

The reusable `exercise_qwen_transport_contract(factory, driver)` suite is
transport-neutral. Wire types and the transport contain no local generation,
turn, utterance, playback epoch, context snapshot, route, journal, or Gate
authority. Raw bodies remain adapter-local; exceptions and metadata expose only
validated bounded fields.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-ADAPTER-01`
- `INV-ADAPTER-02`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-CONCURRENCY-02`
- `INV-FOREGROUND-01`

## Non-goals

- No Fake scheduler or Real WebSocket implementation.
- No Session Pump, readiness state, generation allocation, or turn commit.
- No Router, Gate, candidate release, playback, or canonical journal append.
- No provider SDK, network, environment credential, or aggregate turn RPC.

## Implementation outline

1. Lock exact allowlists and strict tagged parsing before implementation.
2. Represent client and server events with validated immutable structures;
   reject unknown/malformed fields before projection.
3. Keep local control identity out of transport values.
4. Define ordered safe projection frames and the single sink boundary.
5. Make conformance reusable so Card 04 and the future Real transport execute
   the same behavioral suite.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_protocol.py tests/adapters/qwen_realtime/test_transport_contract.py -q
git diff --check -- src/voice_agent/adapters/qwen_realtime/__init__.py src/voice_agent/adapters/qwen_realtime/protocol.py src/voice_agent/adapters/qwen_realtime/transport.py src/voice_agent/adapters/qwen_realtime/projections.py tests/adapters/qwen_realtime/test_protocol.py tests/adapters/qwen_realtime/test_transport_contract.py tests/adapters/qwen_realtime/transport_contract_suite.py
```

No dependency-overlap command applies because this card is a DAG root.

## Pass criteria

Allowlist, schema, leakage, close/error, and shared conformance tests pass.
Round trips are deterministic; safe metadata contains no payload; local
authority fields are absent; the suite can be invoked through a factory and
driver without transport-specific branches.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop if transport acquires
generation/turn/route/Gate/journal/playback authority, parsing preserves raw
provider bodies, or a provider dependency is required.

## Evidence and handoff

Record allowlist coverage, conformance results, safe exception behavior, and
relative changed paths. Hand the frozen event, transport, projection, and
conformance interfaces to `TC-S3B1-04`, `TC-S3B1-05`, and `TC-S3B1-06`; do not
hand off raw provider examples.
