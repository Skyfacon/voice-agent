# TC-S3B1-06 Session Lifecycle

## Task ID and title

`TC-S3B1-06` — Single sender/Pump, strict readiness, controller-owned epoch,
and runtime-owned generation lifecycle. Status: `not-started`. Historical
source: Slice 3B.1 master-plan Task 6.

## Goal

Connect the protocol-faithful transport to one Session Adapter and one Session
Runtime while preserving exact readiness, ASR/local-commit join, cancellation,
cleanup, rebuild, generation, playback-epoch, and payload-ownership boundaries.

## Allowed write files

- Create: `src/voice_agent/adapters/qwen_realtime/session_adapter.py`
- Create: `src/voice_agent/runtime/qwen_realtime_session.py`
- Modify: `src/voice_agent/interaction/controller.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_handshake.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_partial_order.py`
- Create: `tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py`
- Create: `tests/interaction/test_playback_epoch_authority.py`
- Create: `tests/runtime/test_qwen_realtime_session.py`
- Regression test: `tests/interaction/test_barge_in_truncate.py`

## Required read-only dependencies

- [TC-S3B1-01](TC-S3B1-01-events-and-envelopes.md)
- [TC-S3B1-02](TC-S3B1-02-capabilities-and-assembly.md)
- [TC-S3B1-03](TC-S3B1-03-protocol-and-transport.md)
- [TC-S3B1-04](TC-S3B1-04-scripted-wire.md)
- [TC-S3B1-05](TC-S3B1-05-candidate-quarantine.md)
- `stage_b_adr_register.md`
- `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`

## Exact ADR sections

- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Decision`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `Commit Boundary Definition`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md` — `ADR-018 Accepted Addendum`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `Decision`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md` — `ADR-018 Accepted Addendum`
- `docs/adr/ADR-018 Single-session Qwen Realtime Parallel Route Evidence and Slow-to-Fast Context Projection.md` — `Decision`

## Input and output contracts

Inputs are Cards 01–05: canonical lifecycle events, validated mock assembly,
typed transport/projections, permit-driven wire, Quarantine, and ephemeral text
store. Output is `QwenRealtimeSessionAdapter`,
`QwenRealtimeSessionRuntime`, ordered safe projection frames, strict provider
context transitions, and `ASRJoinDispositionV1`.

Adapter signatures:

```python
def fence_for_generation(self, *, generation: int, playback_epoch: int) -> None: ...
async def attach_open_transport(self, transport: QwenRealtimeTransport) -> None: ...
async def stop_pump(self) -> None: ...
async def append_audio(self, pcm16le: bytes | bytearray | memoryview) -> bool: ...
async def cancel_active_response(self) -> bool: ...
async def delete_assistant_item(self, item_id: str) -> bool: ...
def bind_committed_turn(
    self, *, input_item_ref: str, binding: CommittedCandidateBinding
) -> ASRJoinDispositionV1: ...
```

Runtime and Controller signatures:

```python
async def connect(self) -> int: ...
async def rebuild(self, *, reason: str) -> int: ...
async def close(self) -> None: ...
async def dispose_resources(self) -> None: ...
def current_epoch_snapshot(self) -> InteractionEpochSnapshot: ...
def advance_playback_epoch_for_provider_rebuild(
    self, *, provider_session_generation: int, reason: str
) -> InteractionEpochSnapshot: ...
```

`InteractionEpochSnapshot` contains `playback_epoch: int` and
`interaction_state_version: int`. `ASRJoinDispositionV1` contains
`status: Literal["WAITING_PROVIDER_FINAL", "READY", "REJECTED"]` and
`final_asr_projection: FinalASRReadyProjectionV1 | None`.

Session Runtime exclusively advances `provider_session_generation` before every
open/reopen. Interaction Controller exclusively reads and advances
`playback_epoch` and interaction-state version. One serialized sender and one
receive Pump exist per active generation. Only an exact matching
`session.updated` makes context `CLEAN`; non-clean microphone frames are
dropped, counted, never buffered, and never replayed.

The historical `Regression test:` entry in Allowed write files is read-only
verification input; its verbatim presence is not authorization to edit it.

## Stable invariant IDs

- `INV-ADR-01`
- `INV-ADAPTER-01`
- `INV-JOURNAL-01`
- `INV-PRIVACY-01`
- `INV-CONCURRENCY-02`
- `INV-CONCURRENCY-04`
- `INV-CONCURRENCY-05`
- `INV-FOREGROUND-01`
- `INV-FOREGROUND-06`

## Non-goals

- No second sender, Pump, active response, or transport generation.
- No Adapter-owned generation, Controller epoch mutation, or direct turn commit.
- No buffering/replay during cleanup, taint, rebuild, or closed state.
- No Router, Gate, release, playback, durable memory, or real WebSocket.
- Only paths labeled `Create:` or `Modify:` above are writable. Rows labeled
  `Regression test:` are read-only verification surfaces and do not grant
  mutation authority.

## Implementation outline

1. Verify all predecessors and preserve the overlap-sensitive Controller diff.
2. Make Runtime allocate generation and query/advance Controller epoch before
   fencing and opening the transport.
3. Bootstrap through `session.created`, serialized `session.update`, and exact
   `session.updated`; fail closed on ID/config/event-ID mismatch.
4. Pump each server event once into safe ordered projections and Quarantine;
   join provider ASR final with canonical local commit exactly once.
5. Converge auto/explicit cancellation to one terminal, delete unheard items,
   and rebuild on unproved cleanup while fencing old generations and epochs.
6. Separate logical `close()` from idempotent harness-only resource disposal.

## Verification commands

```bash
VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test tests/adapters/qwen_realtime/test_session_adapter_handshake.py tests/adapters/qwen_realtime/test_session_adapter_partial_order.py tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py tests/interaction/test_playback_epoch_authority.py tests/interaction/test_barge_in_truncate.py tests/runtime/test_qwen_realtime_session.py -q
git diff --check -- src/voice_agent/adapters/qwen_realtime/session_adapter.py src/voice_agent/runtime/qwen_realtime_session.py src/voice_agent/interaction/controller.py tests/adapters/qwen_realtime/test_session_adapter_handshake.py tests/adapters/qwen_realtime/test_session_adapter_partial_order.py tests/adapters/qwen_realtime/test_session_adapter_ambient_cancel.py tests/interaction/test_playback_epoch_authority.py tests/interaction/test_barge_in_truncate.py tests/runtime/test_qwen_realtime_session.py
```

For each linked dependency whose verify-first status is `verified`, rerun that
card's exact `Verification commands` test command before editing and again
after this card's focused command; any dependency-overlap failure stops.

## Pass criteria

Handshake, one-Pump/sender, readiness, generation, epoch, ASR join, partial
order, ambient/invalid, cancel race, delete acknowledgement, rebuild, frame
drop, and old-generation rejection tests pass deterministically. Existing
barge-in/truncate behavior remains green.

## Stop conditions

Stop on any ADR conflict, write-set expansion, new architecture capability or
event, runtime/provider/network scope expansion, sensitive artifact discovery,
or focused/overlap test failure. Also stop on a second Pump/sender,
Adapter-owned generation or epoch, non-clean buffering, Controller bypass,
duplicate authority terminal, or payload leakage. Editing a
`Regression test:` path is write-set expansion and requires stopping.

## Evidence and handoff

Record generation/epoch transitions, one-Pump proof, readiness/drop counts,
join cardinality, cancel/cleanup outcomes, safe test counts, and relative
changed paths. Hand ordered projection and current-binding contracts to
`TC-S3B1-07`, `TC-S3B1-08`, `TC-S3B1-09`, and `TC-S3B1-10`.
