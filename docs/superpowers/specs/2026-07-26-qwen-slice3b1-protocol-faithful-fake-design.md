# Qwen Slice 3B.1 Protocol-Faithful Provider-Free Fake Design

Date: 2026-07-26 (+0800)

Status: accepted by user on 2026-07-27; implementation planning authorized

Repository: `/Users/a123/voice-agent`

Authority: accepted ADR-018 and the accepted ADRs referenced by `AGENTS.md`

## 1. Decision

Slice 3B.1 will not fake a completed Qwen turn result. It will fake the Qwen
Audio Realtime WebSocket event stream.

The provider-free Slice uses:

- one logical Qwen Realtime session per browser Connect;
- at most one active provider transport generation at a time;
- one serialized client-event sender and one receive Session Pump;
- one `QwenRealtimeSessionAdapter` shared by the scripted Fake transport in
  3B.1 and the real WebSocket transport beginning in 3B.2;
- a separate Fake Route Evidence Adapter;
- deterministic synthetic scenarios and a provider-free CLI demo;
- canonical Event Journal, replay, Router, Gate, and output-disposition
  boundaries;
- `output_mode=mock`, `provider_free_test_support=true`,
  `real_live_support=false`, and `native_pcm_enabled=false`.

The default end-to-end runner therefore cannot authorize provider-native PCM.
Section 10 separates that runtime-faithful path from an isolated,
`mock_contract_only` Gate contract suite.

The page demo is Slice C after the CLI. It must consume the same runner and
stable result contract rather than reimplementing protocol, Router, or Gate
logic.

## 2. Scope

Slice 3B.1 proves:

1. The control plane can consume the real Qwen protocol shape: one persistent
   connection containing many asynchronous client and server events.
2. Duplex, ASR, candidate transcript, candidate PCM, response lifecycle, and
   cleanup remain separate projections with exact identity binding.
3. Provider Response generation can overlap the local turn-commit join without
   becoming authoritative or audible.
4. Route Evidence remains an independent model-adapter operation.
5. Local Router and Fast Foreground Gate remain the only route and release
   authorities.
6. Invalid, ambient, stale, malformed, interrupted, or uncorrelated provider
   output fails closed.
7. Replay can reconstruct the material result without rerunning the Fake,
   Router evidence model, or provider.

Slice 3B.1 does not:

- connect to Alibaba Cloud or any external endpoint;
- read an API key, credential, cookie, authorization header, or provider
  workspace identifier;
- qualify real `smart_turn`, real ASR, real cancellation, real item cleanup, or
  real latency;
- play provider PCM;
- implement the page demo;
- implement real Route Evidence or Candidate Safety models;
- implement Slow-to-Fast Composer injection;
- change the Slice 3A.2.1 dual-session hotfix;
- add provider-specific canonical Event Journal names;
- broaden SlowTask, UserPatch, confirmation, tool, Router, or Gate authority.

## 3. Correction to the Prior Abstraction

The rejected abstraction is:

```text
fake_qwen.run_turn(user_text)
  -> {asr, duplex, route, candidate_text, candidate_pcm}
```

It is rejected because it:

- hides the persistent connection and handshake;
- cannot model multiple audio appends with no per-frame acknowledgement;
- fixes one artificial event order;
- cannot model Response generation before the local final-ASR join;
- cannot model transcript and PCM interleaving;
- cannot test cancel/terminal/delete races;
- encourages Qwen to emit route decisions that belong to the independent Route
  Evidence Adapter and Local Router;
- bypasses the exact session/generation/response/item/output/content/chunk
  correlation required by ADR-018.

The accepted abstraction is:

```text
ScriptedFakeQwenWire ─┐
                      ├─ QwenRealtimeSessionAdapter / SessionPump
RealQwenWebSocket ────┘
                            ├─ duplex_projection
                            ├─ asr_projection
                            ├─ fast_candidate_projection
                            └─ composer_projection
```

Only one transport is active. Slice 3B.1 selects the scripted Fake. Slice 3B.2
selects the real WebSocket transport without replacing the Session Adapter or
downstream control plane.

## 4. Component Boundaries

| Component | Input | Output | Authority and exclusions |
| --- | --- | --- | --- |
| `QwenRealtimeTransport` | Typed or validated provider client events | Provider-shaped server events | Wire only; no canonical events, Router, Gate, journal, or raw logging |
| `ScriptedFakeQwenWire` | The same client events the real transport receives | Deterministically scheduled synthetic provider events | No network, credentials, wall-clock scheduling, route proposal, or playback |
| Session Runtime | Connect/rebuild lifecycle | Current local generation and one active transport handle | Sole allocator/advancer of `provider_session_generation`; never parses provider events or decides route/release |
| `QwenRealtimeSessionAdapter` | One transport stream plus current runtime generation | Normalized projection frames and safe lifecycle facts | Binds/validates generation and owns one sender/Pump, state machine, correlation, cancellation, cleanup, and rebuild requests; never allocates generation, commits turns, or decides route/release |
| Interaction Controller | Normalized Duplex/ingress evidence | Accepted, committed, held, or rejected ingress | Only owner of local turn ingress |
| CandidateQuarantine | Correlated provider Response transcript/PCM/lifecycle frames | Complete/discarded candidate metadata, digests, and in-memory PCM ref | Never persists PCM or emits user-visible output |
| Fake Route Evidence Adapter | Final ASR plus bounded context, or complete candidate transcript plus safety context | Route Evidence or Candidate Safety Evidence | Independent from Qwen; never emits RouterDecision or answer text |
| Fast Interaction Orchestrator | Recorded Qwen, Route Evidence, Candidate Safety, context, and generation provenance | Composite Fast Interaction output | Join only; no model call, route decision, or release |
| Local Router | Committed-turn evidence and Route Evidence | One authoritative RouterDecision | Route authority only |
| Fast Foreground Gate | Current reducer state, exact correlation/digests, evidence, RouterDecision, capability state | Pass/fail and release token or discard/fallback | Release authority only |
| Slice 3B.1 runner | Scenario ID and deterministic synthetic configuration | `Slice3B1RunV1` | Orchestration only; no browser or provider call |
| CLI B | `Slice3B1RunV1` | Stable JSON or concise human summary | Presentation only; no control decision |

Implementation should use a new focused package rather than extend the large
Slice 3A experiment Coordinator. The implementation plan will assign exact
paths, but the responsibility split is:

```text
wire protocol types
transport protocol
scripted fake wire
session adapter and pump
candidate correlation/quarantine
fake route evidence
scenario scheduler
slice runner and stable result schema
CLI serialization
```

## 5. Transport Contract

The conceptual transport interface is:

```python
class QwenRealtimeTransport(Protocol):
    async def open(self) -> None: ...
    async def send(self, event: Mapping[str, object]) -> None: ...
    async def recv(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
```

The concrete implementation may replace generic mappings with validated tagged
unions, but the behavioral contract is fixed:

- Session Runtime exclusively allocates and advances the local
  `provider_session_generation` before it calls `open()`;
- `open()` establishes only the physical connection and returns no provider
  event;
- `session.created` arrives through a subsequent `recv()`;
- `session.updated` cannot be emitted until the client sends a valid
  `session.update`;
- `send()` is serialized for all client event types;
- `recv()` has exactly one consumer Pump per active generation;
- `input_audio_buffer.append` may repeat and has no per-frame server
  acknowledgement;
- the transport does not add local `turn_id`, `utterance_id`,
  `provider_session_generation`, `playback_epoch`, or context snapshot IDs;
- `close()` terminates the current generation and cannot replay buffered
  microphone frames.

Client events required by the 3B.1 contract:

```text
session.update
input_audio_buffer.append
response.cancel
conversation.item.delete
```

Normal `smart_turn` voice turns do not send `input_audio_buffer.commit` or
per-turn `response.create`. The transport type layer may reserve validated
`conversation.item.create` and `response.create` variants for the later
Composer slice, but they are outside the Slice 3B.1 conformance suite. Slice
3B.1 therefore does not claim support for the corresponding text-only Response
lifecycle.

Server events required by the 3B.1 contract:

```text
session.created
session.updated
input_audio_buffer.speech_started
input_audio_buffer.speech_stopped
input_audio_buffer.committed
conversation.item.created
conversation.item.deleted
conversation.item.input_audio_transcription.delta
conversation.item.input_audio_transcription.completed
conversation.item.input_audio_transcription.failed
conversation.item.ambient_audio_transcription.delta
conversation.item.ambient_audio_transcription.completed
response.created
response.output_item.added
response.content_part.added
response.audio_transcript.delta
response.audio.delta
response.audio_transcript.done
response.audio.done
response.content_part.done
response.output_item.done
response.done
error
```

The Fake may support additional documented events later, but it may not invent
provider events to carry local route or Gate semantics.

## 6. Session Adapter and Correlation State

The Session Adapter maintains at least:

```text
logical_session_id
provider_session_generation
provider_session_ref
provider_context_state
provider_event_seq
seen_provider_event_id_refs
wire_send_seq
session_configuration_state
active_input_item_ref optional
input_content_index optional
active_response_id optional
output_item_id optional
output_index optional
content_index optional
transcript_delta_seq
pcm_chunk_seq
transcript_done
audio_done
output_item_done
response_terminal_status optional
response_terminal_reason optional
cancel_sent
delete_ack_pending
bound_playback_epoch
stale_response_tombstones
```

Provider IDs remain opaque adapter-local refs. The provider does not supply the
local `provider_session_generation`, `turn_id`, `utterance_id`,
`context_snapshot_id`, `playback_epoch`, or canonical `event_seq`; the Adapter
and control plane attach those identities at their respective boundaries.

For every server event, the Pump first establishes safe metadata:

```text
provider_session_generation
provider_event_seq
wire_event_type
provider_event_id_ref
provider_session_ref optional
qwen_input_item_ref optional
qwen_response_id optional
qwen_output_item_id optional
qwen_output_index optional
qwen_content_index optional
terminal_status optional
response_terminal_reason optional
safe_receive_offset_ms
output_mode=mock
```

Transcript and PCM payloads remain memory-only. Safe metadata can be used for
deterministic diagnostics and canonical projection, but raw provider bodies do
not cross the Adapter boundary.

The local generation is never a Transport field. The Session Runtime advances
it before physical open/reopen, and the Session Adapter binds subsequently
received provider events to that already-current generation.

Provider-backed ingress has a strict readiness barrier:

- after `open()` and during rebuild, `provider_context_state` is non-`CLEAN`;
- `session.created` supplies default configuration only and is never final
  configuration authority;
- every allowlisted server event must carry a non-empty `event_id` that is
  unique within the current generation;
- a valid `session.updated` must have the same `session.id` as
  `session.created` and must reflect the requested `turn_detection.type`,
  modalities, voice, input-transcription, tool, and role/profile
  configuration;
- only a valid `session.updated` for the current generation transitions the
  state to `CLEAN`;
- missing/duplicate event ID, session-ID mismatch, configuration mismatch, or
  `error` keeps ingress non-`CLEAN` and fails closed;
- `input_audio_buffer.append` is permitted only while the state is `CLEAN`;
- an append attempted while non-`CLEAN` is dropped, increments a bounded safe
  drop counter, and is never buffered, committed, or replayed.

The Interaction Controller owns `playback_epoch`. The Session Adapter only
stores and validates a bound epoch. Rebuild must request the per-session
serialized control authority to advance the epoch; the Adapter cannot advance
it independently.

## 7. Protocol Partial Order

The Fake's default happy path follows the documented lifecycle:

```text
session.created
client session.update
session.updated
client input_audio_buffer.append × N
speech_started(input item U)
input transcription delta(U) × N
speech_stopped(U)
input_audio_buffer.committed(U)
conversation.item.created(user item U)
input transcription completed(U)
response.created(response R)
response.output_item.added(R, assistant item A)
conversation.item.created(assistant item A)
response.content_part.added(R, A, output index O, content index C)
assistant transcript delta(R, A, O, C) × N
audio delta(R, A, O, C) × N
assistant transcript done(R, A, O, C)
audio done(R, A, O, C)
content part done(R, A, O, C)
output item done(R, A, O)
response.done(R, completed)
```

This is a scenario, not a global total-order assertion. The Adapter relies only
on:

```text
session.created < session.update < session.updated
speech_started(U) < speech_stopped(U)|turn_invalid(U)
ASR delta(U)* < ASR completed(U)|failed(U)
response.created(R) < response output events(R) < response.done(R)
ambient delta(T)* < ambient completed(T)
```

It must not require:

```text
ASR completed(U) < response.created(R)
assistant transcript delta < audio delta
assistant transcript done < audio done
conversation.item.created(assistant A) < response.output_item.added(R, A)
response.output_item.added(R, A) < conversation.item.created(assistant A)
```

The deterministic scheduler includes both ASR-final-first and
response-start-first scenarios and multiple legal transcript/PCM
interleavings. It also permutes the assistant
`conversation.item.created`/`response.output_item.added` pair and requires
their item IDs to join before candidate eligibility.

## 8. Local Commit and Final-ASR Join

`speech_started` and `speech_stopped` are evidence. They do not directly commit
a local turn.

Canonical final ASR requires:

```text
TURN_INGRESS_COMMITTED
and normalized provider transcription.completed
```

Behavior:

- provider ASR final first: hold it in Adapter state until local commit;
- local commit first: wait for the matching provider ASR final;
- response start or output first: assemble it only in CandidateQuarantine;
- local ingress rejected or held: cancel/delete any provider speculation and
  emit no Route Evidence, Router, Gate, or output authority chain;
- both predecessors present: emit one final ASR bound to the committed
  turn/utterance and start `classify_route`.

The provider-backed final-ASR event carries safe correlation metadata:

```text
provider_session_generation
qwen_input_item_ref
qwen_input_content_index
```

It never carries raw provider JSON, raw audio, or unredacted real-user text.

## 9. Smart Turn Ambient and Invalid Paths

Ambient transcription:

- consists of zero or more
  `conversation.item.ambient_audio_transcription.delta` events followed by one
  matching `.completed` terminal;
- uses a standalone temporary provider `item_id`;
- closes the ambient segment at `.completed`;
- never binds that temporary ID to `active_input_item_ref`, a local turn, or a
  provider conversation item;
- is not a committed conversation item;
- does not create `TURN_INGRESS_COMMITTED`;
- does not start Route Evidence;
- does not create a consumable foreground candidate;
- does not create Router/Gate/output authority;
- remains safe non-turn evidence only.

`speech_stopped(reason=turn_invalid)`:

- retracts the candidate ingress;
- terminates it through the existing reject/discard policy;
- emits no final-ASR route chain;
- cancels/deletes unexpected provider assistant output;
- taints/rebuilds provider context if cleanup cannot be proven.

If a provisional speech-start already caused local playback to stop, a later
ambient/invalid classification never resumes the old playback.

## 10. Candidate Quarantine

CandidateQuarantine opens a response-level entry on correlated
`response.created` and initially binds:

```text
provider_session_generation
qwen_response_id
candidate_id
bound_playback_epoch
provisional_ingress_id optional
qwen_input_item_ref optional
```

`response.output_item.added` and assistant `conversation.item.created` may
arrive in either order. Together they must bind the same
`qwen_output_item_id`; the output-item event also binds `qwen_output_index`.
`response.content_part.added` then binds `qwen_content_index`. Every provider
binding is monotonic and immutable.

Only after `TURN_INGRESS_COMMITTED` does Quarantine bind the canonical
`turn_id`, `utterance_id`, and fast-candidate `context_snapshot_id`. These local
bindings are exactly-once and immutable. Ambient, invalid, held, or rejected
ingress never receives them and is cancelled/deleted/discarded instead. A later
event that attempts to rebind any established provider or local identity
permanently invalidates the candidate.

It accepts normalized transcript and PCM frames only when every identity
available at that lifecycle stage matches. The single receive Pump preserves
observed WebSocket order. Every accepted provider event must carry a non-empty,
generation-unique `event_id`; missing or duplicate IDs fail closed. The
Adapter assigns each accepted PCM delta a local monotonic `pcm_chunk_seq`
solely for the manifest.

A candidate is complete only when:

- complete transcript is present;
- transcript terminal is present;
- PCM terminal is present for audio mode;
- canonical `turn_id`, `utterance_id`, and `context_snapshot_id` are bound;
- exactly one assistant `message` output item and exactly one `audio` content
  part are present;
- no `function_call`, extra output item, or extra content part is present;
- output item/content lifecycle is consistent;
- `response.done(status=completed)` is present;
- all response/item/output/content/generation identities match;
- assistant `conversation.item.created`, `response.output_item.added`,
  `response.content_part.added`, every transcript/audio delta and done,
  `response.output_item.done`, and `response.done.output[]` agree on the same
  item/output/content identities;
- no provider event ID is duplicated;
- no delta arrives after its content/audio terminal;
- no delta is cross-lifecycle, late-generation, cross-response,
  cross-item, or cross-content;
- text, audio, chunk, byte, and duration bounds pass.

Completion computes:

```text
candidate_transcript_digest
candidate_pcm_manifest_digest
```

The PCM manifest covers observed local chunk sequence, byte length, format,
sample rate, channel count, and decoded duration. PCM is synthetic, generated
at runtime, memory-only, and destroyed after discard or test completion.

When the provider supplies no chunk ordinal or end-to-end checksum, neither
Fake nor Real code may claim detection of an arbitrary omitted or permuted
intermediate delta. Detectable failures are duplicate provider event IDs,
illegal lifecycle or identity transitions, missing required terminals,
disconnect, overflow, and terminal mismatch. Fake fault injection must exercise
those Real-observable facts; scheduler-only `wire_seq` is never an Adapter
correlation field.

An immutable `ForegroundReleaseTokenV1`, when produced by the Gate contract,
includes the complete ADR-018 field set:

```text
release_token_id
session_id
provider_session_generation
context_snapshot_id
source_event_seq
turn_id
utterance_id
qwen_response_id
qwen_output_item_id
qwen_output_index
qwen_content_index
candidate_id
candidate_transcript_digest
candidate_pcm_manifest_digest
candidate_audio_format_ref
candidate_audio_duration_ms
candidate_audio_shadow_verification_event_id optional
router_decision_event_id
route_evidence_event_id
candidate_safety_evidence_event_id
playback_epoch
gate_policy_version
```

Any mismatch fails closed.

Slice 3B.1 keeps two validation paths explicitly separate:

1. The default runtime-faithful runner advertises
   `native_pcm_enabled=false`. Its native-audio Gate check fails closed, creates
   no release token or playback outbox item, and never calls Talker.
2. An isolated `mock_contract_only` Gate contract suite constructs synthetic
   policy inputs to verify the complete token, compare-and-authorize boundary,
   outbox insertion, and stale-binding failures. It remains
   `output_mode=mock`, does not alter the advertised Fake capability profile,
   never invokes Talker, and cannot count as native-PCM qualification or
   enablement.

## 11. Independent Route Evidence

The Fake Route Evidence Adapter is a separate adapter instance:

```python
class RouteEvidenceAdapter(Protocol):
    async def classify_route(
        self, request: RouteEvidenceRequestV1
    ) -> RouteEvidenceOutputV1: ...

    async def classify_candidate_safety(
        self, request: CandidateSafetyRequestV1
    ) -> CandidateSafetyEvidenceV1: ...
```

Rules:

- `classify_route` starts only after canonical final ASR and bounded route
  context exist;
- it never receives the Qwen answer candidate;
- `classify_candidate_safety` starts only after the complete candidate
  transcript and immutable digest exist;
- it never receives raw PCM;
- timeout, malformed schema, unknown enum, oversized output, low confidence,
  prohibited flags, or `UNCERTAIN` fails closed;
- its output is evidence, never RouterDecision, UserPatch interpretation,
  confirmation, tool authorization, or Gate release.

`ScriptedFakeQwenWire` must never emit `route.proposed`.

## 12. Barge-In, Cancel, Delete, and Rebuild

For an active Response:

1. In `server_vad`/`smart_turn`,
   `input_audio_buffer.speech_started` while a Response is active automatically
   interrupts it, even though local validity may be decided later. The provider
   terminal is `response.done(status=cancelled,
   status_details.reason=turn_detected)`.
2. Local Interaction Controller independently advances playback epoch and
   clears queued playback.
3. The Session Adapter sends `response.cancel` only while the same Response is
   still active and no auto-cancel terminal has been observed. A successful
   explicit cancel terminates with
   `status_details.reason=client_cancelled`.
4. Local cancel handling and canonical terminal emission are idempotent. A
   second provider terminal for the same Response is a correlation violation:
   it invalidates the candidate, cannot create a second authority chain, and
   taints/rebuilds provider context according to policy. If automatic
   interruption wins the race, a later explicit cancel may produce a
   non-terminal `invalid_request_error`; that error is not a second Response
   terminal and cannot create another authority chain.
5. Late old-epoch output is discarded.
6. Unheard provider assistant items are deleted.
7. `conversation.item.deleted` acknowledgement closes cleanup.
8. Missing/invalid acknowledgement advances provider context through
   `CLEANUP_PENDING -> TAINTED -> REBUILDING`.
9. Before network-equivalent rebuild work, Session Runtime advances
   `provider_session_generation` and the serialized control authority asks the
   Interaction Controller to advance `playback_epoch`; the Adapter only binds
   the resulting epoch.
10. Old-generation events and recovery-window microphone frames are dropped
    and never replayed.

A cancelled provider terminal proves only that the current provider Response
became terminal. It does not stop the provider session generation/WebSocket,
prove local playback stopped, or establish delivery status. Cleanup policy may
separately trigger a rebuild.

## 13. Canonical Event and Replay Boundary

Raw Qwen events remain inside the Transport and Session Adapter. Only
normalized, exactly correlated transcript frames and memory-only PCM frames
enter Quarantine. Do not add provider-specific canonical names such as:

```text
QWEN_SESSION_UPDATED
QWEN_RESPONSE_CREATED
QWEN_AUDIO_DELTA_RECEIVED
QWEN_RESPONSE_DONE
QWEN_ITEM_DELETED
```

Minimum normalized mapping:

| Raw provider fact | Canonical result |
| --- | --- |
| session handshake/readiness | Existing session/capability facts and material `PROVIDER_CONTEXT_STATE_CHANGED` |
| speech start/stop | Existing audio span, speech, and barge-in/ingress chain |
| ASR completed after local commit join | `ASR_TRANSCRIPT_OUTPUT_EMITTED` |
| ambient/invalid | Existing non-assistant/rejected-ingress path; no route/output chain |
| complete correlated candidate | Composite Fast Interaction and `FOREGROUND_REPLY_CANDIDATE_EMITTED` chain |
| route/candidate-safety results | ADR-018 evidence events |
| cancellation/cleanup | Existing interrupt/arbitration/adapter failure facts and material provider-context transition |
| delete acknowledgement and delivery outcome | `PROVIDER_CONTEXT_STATE_CHANGED` and `ASSISTANT_DELIVERY_DISPOSITIONED` as applicable |
| malformed/error/disconnect | Existing adapter validation/failure/degraded events plus provider-context transition |

Replay consumes only recorded canonical refs, digests, enums, decisions,
dispositions, bounded counts, and state changes. It never reruns the wire Fake,
Router evidence operations, Qwen, or playback.

Before the Slice 3B.1 end-to-end runner is accepted, the nine accepted ADR-018
event names and the conditional existing-event fields must exist in the runtime
registry and derived event specification. Historical ADR-017 fixtures remain
compatible through:

```text
missing fast_interaction_topology => atomic_single_call
fast_interaction_topology=speculative_candidate_parallel_route
```

## 14. Deterministic Scenario Scheduler

`ScriptedFakeQwenWire` uses:

```text
wire_seq: monotonic integer
virtual_ms: deterministic integer offset
scenario_id: stable identifier
fixture_domain=GITHUB_ALLOWED
generated_from=synthetic
scenario_source=SYNTHETIC
```

It does not use wall clock, randomness, real sleep, provider SDKs, network, or
environment credentials. Scenario scripts describe only provider-shaped safe
event templates, payload refs, and fault injections.

Synthetic PCM:

- is generated at runtime;
- exists only in memory;
- is never committed as a fixture;
- is represented in Journal/report output only by format, byte length,
  duration, chunk metadata, and digest.

The scheduler can pause after any wire event so tests can independently advance
Route Evidence, local commit, cancellation, cleanup, or rebuild. Repeating a
scenario with the same inputs produces the same safe wire order, canonical
event order, terminal state, and state digest.

## 15. CLI B and Page C Reuse Contract

The core runner is presentation-independent:

```python
run_slice3b1_scenario(scenario_id: str) -> Slice3B1RunV1
```

`Slice3B1RunV1` contains:

```text
schema_name=voice_agent.slice3b1.run.v1
scenario_id
fixture_domain=GITHUB_ALLOWED
generated_from=synthetic
scenario_source=SYNTHETIC
output_mode=mock
wire_timeline_safe
canonical_event_ids
route_evidence_summary
candidate_safety_summary
router_decision
gate_terminal
candidate_disposition
provider_context_terminal_state
replay_status
state_digest
safety_flags
```

`wire_timeline_safe` contains event type, virtual offset, direction, safe
opaque refs, indexes, byte counts, terminal enums, and output mode. It excludes
raw PCM, provider body, prompts, credentials, authorization, real user text,
and unrestricted candidate text.

If a human-readable synthetic utterance is needed, the runner exposes a
separate `SyntheticDisplayProjectionV1`. It is explicitly synthetic and is not
the canonical Journal payload.

CLI B serializes `Slice3B1RunV1` or renders a concise view of the same object.
Page C later calls the same runner/result mapper. The page may select a
scenario and display lanes, but it may not construct provider events, rerun
Router/Gate logic, or infer a different result.

## 16. Scenario Matrix

### Protocol bootstrap and partial order

- `bootstrap_requires_session_update`
- `session_created_defaults_not_authority`
- `session_updated_session_id_mismatch`
- `session_updated_configuration_mismatch`
- `missing_or_duplicate_server_event_id`
- `audio_append_before_clean_dropped`
- `multiple_audio_appends_without_ack`
- `valid_turn_asr_before_response`
- `valid_turn_response_starts_before_asr_final`
- `transcript_and_pcm_interleave`
- `assistant_item_created_before_output_item`
- `output_item_before_assistant_item_created`
- `route_before_candidate_complete`
- `candidate_before_route_complete`
- `second_active_response_rejected`

### Smart Turn ingress

- `ambient_audio_no_committed_turn`
- `ambient_delta_completed_temporary_item`
- `turn_invalid_no_commit_no_route_no_release`
- `precommit_turn_rejected_cancel_delete`

### Candidate correlation and completeness

- `wrong_response_id`
- `wrong_output_item_id`
- `wrong_output_index`
- `wrong_content_index`
- `duplicate_provider_audio_event_id`
- `audio_delta_after_audio_done`
- `cross_content_audio_delta`
- `extra_output_item`
- `extra_content_part`
- `function_call_output_ineligible`
- `response_done_output_item_mismatch`
- `missing_audio_done`
- `missing_response_terminal`
- `response_failed`
- `quarantine_overflow`

### Barge-in, cleanup, and generation

- `barge_in_provider_auto_cancel`
- `barge_in_explicit_cancel`
- `auto_and_explicit_cancel_race`
- `late_explicit_cancel_invalid_request_is_not_terminal`
- `late_old_pcm_after_cancel`
- `missing_cancel_terminal`
- `delete_ack_missing_rebuild`
- `old_generation_event_after_rebuild`
- `recovery_audio_dropped_never_replayed`

### Route Evidence and Gate

- each authoritative route;
- active-task foreground chat, patch, new-task, cancel/confirmation, and
  ambiguity;
- Candidate Safety `SAFE`, `UNSAFE`, `UNCERTAIN`, timeout, and malformed;
- Route Evidence timeout, malformed, low-confidence, and prohibited-risk;
- default-runner native capability disabled, Gate fail, and no token/outbox;
- `mock_contract_only` Gate contract: each release-token field mismatched
  independently;
- `mock_contract_only` Gate contract: barge-in or rebuild between authorization
  and mock outbox handoff, with no playback.

## 17. Failure and Security Policy

- Unknown client or server event type fails closed or is explicitly ignored by
  a versioned allowlist; it never mutates control state silently.
- Invalid wire schema cannot reach normalized projections.
- Invalid correlation permanently disqualifies the candidate.
- Local cancel handling and canonical terminal emission are idempotent. A
  second provider terminal is a correlation violation that invalidates the
  candidate and taints/rebuilds according to policy; it cannot produce a second
  Router, Gate, output, cleanup, or delivery authority chain.
- Missing response terminal, delete acknowledgement, or required content
  terminal causes bounded timeout handling and provider-context taint/rebuild.
- Raw provider events are not written to the Event Journal.
- Raw PCM is never written to trace, replay fixture, diagnostics, or Git.
- Synthetic display text is clearly marked synthetic and separated from
  canonical payloads.
- Secrets and credential-like values are rejected before serialization.
- Shareable fixtures are synthetic, redacted, minimal, and bounded.
- 3B.1 never emits a real native-PCM playback success claim.

## 18. Acceptance Criteria

Slice 3B.1 design implementation is accepted only when:

1. The default runner uses zero network and reads zero provider credentials.
2. All capabilities truthfully report mock/provider-free status and
   `native_pcm_enabled=false`.
3. A Connect creates one logical session and at most one active provider
   transport generation.
4. Fake and future Real transports satisfy the same transport contract and
   feed the same Session Adapter/Pump.
5. Session Runtime advances generation before `open()`; `session.created`
   arrives through `recv()`; Transport never owns or emits the local generation.
6. Every allowlisted server event has a non-empty, generation-unique
   `event_id`. `session.created` defaults never authorize ingress; a matching
   session ID and requested smart-turn/configuration echo in `session.updated`
   are required before `provider_context_state=CLEAN`. Appends while
   non-`CLEAN` are dropped and counted, and cannot commit or replay.
7. Handshake, multiple append, no per-frame acknowledgement, partial-order
   permutations, ambient, invalid turn, cancellation, cleanup, and generation
   scenarios pass deterministically.
8. Provider ASR final may arrive early, but canonical final ASR is emitted only
   after local `TURN_INGRESS_COMMITTED`.
9. Route Evidence never starts before canonical final ASR.
10. Candidate Safety never starts before complete candidate transcript and
   immutable digest.
11. Ambient, invalid, rejected, stale, and malformed turns emit no consumable
   candidate or route/output authority chain.
12. Each committed turn has at most one RouterDecision, one terminal Gate, and
    one terminal candidate/output disposition.
13. A candidate has exactly one assistant message output item and one audio
    content part. Any extra/function-call output or detectable
    generation/response/item/output/content/event-ID/lifecycle mismatch fails
    closed; tests make no unsupported claim about arbitrary provider deltas
    lacking ordinals/checksums.
14. Fake fault injection uses only facts observable by the Real transport and
    never uses `wire_seq` as an Adapter correlation field.
15. Qwen Fake never emits `route.proposed`; Route Evidence is independent and
    non-authoritative.
16. The default runner keeps native PCM disabled, produces no release token or
    playback outbox item, and does not call a real Talker.
17. The isolated `mock_contract_only` suite validates the full ADR-018 release
    token and Gate/outbox contract without changing runtime capabilities or
    claiming playback.
18. Canonical replay reconstructs evidence, route, Gate, quarantine lifecycle,
    digests and disposition, provider-context state, and output disposition
    without rerunning any model or Fake; it does not reconstruct PCM.
19. Repeating a scenario produces identical canonical ordering and state
    digest.
20. `Slice3B1RunV1` has a schema/snapshot test and is reusable unchanged by
    Page C.
21. Fixtures and outputs contain no raw PCM, provider body, prompt, secret,
    credential, authorization header, or unredacted real-user input.
22. Python tests run through:

    ```bash
    VOICE_AGENT_PYTHON=/Users/a123/anaconda3/bin/python ./scripts/test ...
    ```

23. `git diff --check`, secret scans, and prohibited artifact scans pass.

## 19. Slice 3B.2 Handoff

Slice 3B.2:

1. Implements `RealQwenWebSocketTransport`.
2. Runs the same transport conformance suite.
3. Selects Real transport instead of `ScriptedFakeQwenWire`.
4. Reuses the same Session Adapter/Pump, normalized projections, exact
   correlation, quarantine, Router, and Gate boundaries.
5. Introduces real Qwen and real Route/Candidate-Safety evidence only in
   shadow/qualification.
6. Keeps provider-native PCM inaudible.
7. Records documentation support, provider-free support, and real-live support
   as distinct capability evidence.

Only after 3B.2 live qualification may later slices let real Route Evidence
affect Local Router decisions, and only after the separate native-PCM promotion
gate may provider audio become audible.

## 20. Protocol Source Lock

This design was checked on 2026-07-26 against the current official Alibaba
Cloud contract:

- [Qwen-Audio Realtime server events](https://help.aliyun.com/en/model-studio/qwen-audio-realtime-server-events)
- [Qwen-Audio Realtime user guide](https://help.aliyun.com/en/model-studio/qwen-audio-realtime-user-guides)

The Fake locks to the event names, mandatory server `event_id`, bootstrap
semantics, ambient temporary-item lifecycle, assistant item/output lifecycle,
and cancellation reasons documented there. Provider documentation support is
not real-live qualification. Contract drift must fail closed and trigger
profile/conformance review before the Real transport is promoted.
