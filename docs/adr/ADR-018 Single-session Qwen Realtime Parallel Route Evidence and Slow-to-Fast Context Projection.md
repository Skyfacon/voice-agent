# ADR-018 Single-session Qwen Realtime, Parallel Route Evidence, and Slow-to-Fast Context Projection

## Status

accepted

Accepted by explicit human review on 2026-07-25. This accepted governance
contract authorizes later Slice 3B implementation plans; it does not claim
runtime implementation, model qualification, or native-PCM enablement.

The proposal-era validation and promotion clauses preserved below are
historical pre-acceptance conditions. The explicit human acceptance on
2026-07-25 and this authoritative governance synchronization satisfy those
conditions. They do not revoke ADR-018's accepted status or its authority for
later Slice 3B implementation plans.

The exact capability identifiers synchronized into ADR-011 and the derived
capability specifications are acceptance metadata and do not change the
Decision below:

```text
adapter_type=route_evidence
supports_route_schema
supports_task_focus
supports_foreground_act_hint
supports_ack_kind
supports_candidate_safety_schema
supports_prohibited_claim_detection
supports_strict_json_validation
supports_risk_tags
supports_confidence
supports_candidate_output_audio_shadow_verification
supports_smart_turn
supports_streaming_asr
supports_provider_response_cancellation
supports_provider_item_create
supports_provider_item_delete_ack
supports_manual_response_while_idle
supports_text_only_response_override
supports_candidate_quarantine
supports_provider_native_audio_release
supports_provider_context_readiness
supports_context_rebuild
```

## Context

ADR-017 defines an atomic Fast Interaction Adapter call that produces route
evidence, a foreground act, and a reply candidate while keeping the Local
Router and Fast Foreground Gate authoritative. The approved Qwen single-session
design explores a second topology for Post-ADR-017 / MVP6.x work: one
audio-native Qwen session speculatively generates a short candidate while an
independent small-text adapter classifies route evidence in parallel, then
classifies the completed candidate transcript for safety. This can avoid a
second answer-model round trip without making either model authoritative.

That topology changes architecture boundaries beyond the Slice 3A.2.1
recovery hotfix. It introduces separately correlated route evidence,
candidate-safety evidence, quarantined provider-native PCM, a local context
projection layer, delivery-aware provider history, and a same-session
SlowTask-to-Composer bridge. It therefore requires a new ADR before runtime
implementation.

The design must preserve the authority contracts in ADR-001, ADR-002, ADR-003,
ADR-009, ADR-011, ADR-012, ADR-013, ADR-015, ADR-016, and ADR-017:

- the Interaction Controller is the only owner of turn ingress;
- model adapters emit normalized evidence, not state-changing decisions;
- the Local Router remains the only owner of the four authoritative routes and
  TaskFocusState;
- the Fast Foreground Gate remains the only owner of fast-candidate release;
- SlowTask remains the owner of task lifecycle, confirmation, plan version,
  tool authority, and SemanticCommitment;
- Thinker-as-Composer cannot rewrite slow-system facts;
- every critical state transition and delivery outcome must be journaled and
  replayable;
- no raw audio, raw provider payload, secret, or unredacted real-user text may
  enter a shareable trace or repository artifact.

## Decision

### Scope and relationship to Slice 3A.2.1

This decision is scoped to Post-ADR-017 / MVP6.x Slice 3B. Slice 3A.2.1 remains
a dual-session, provider-audio-disabled recovery hotfix. Nothing here
retroactively authorizes single-session behavior, provider-native playback, or
new canonical runtime events in Slice 3A.2.1.

Slice 3B phase one uses one logical Qwen Realtime session per browser Connect,
at most one active provider WebSocket transport at a time, session-only memory,
and one active SlowTask. A browser Connect defines the memory lifetime. A
transport rebuild replaces the physical WebSocket, advances
`provider_session_generation`, and may rehydrate from local committed state
inside the same logical session. Closing the Connect discards session memory
and a new Connect starts clean.

Durable cross-session memory, multiple active SlowTasks, pause/resume,
streaming-prefix playback, production privacy/retention, and real external
side effects are outside this decision.

The focused provider-free implementation design is
`docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`.

The normative Slice 3B.0 terms are:

```text
one logical Qwen Realtime session per browser Connect
at most one active provider WebSocket transport at a time
one serialized sender and one receive Session Pump per provider generation
protocol-faithful Fake and Real transports share one Session Adapter
session-only memory
one active SlowTask
Route Evidence Adapter.classify_route
Route Evidence Adapter.classify_candidate_safety
Local Router owns RouterDecision
Fast Foreground Gate owns release
no audible PCM before Gate
no per-turn independent PCM back-transcription
exact provider generation/response/output-item/output-index/content-index correlation
immutable candidate_transcript_digest
immutable candidate_pcm_manifest_digest
pre-promotion PCM back-transcription qualification
non-blocking live PCM shadow verification
shadow mismatch disables native PCM for subsequent turns
SlowToFastHandoffV1
text-only Qwen Composer before truthfulness/coverage checks
provider_context_state=CLEAN before provider-backed ingress
FULL|TRUNCATED|NOT_STARTED delivery disposition
```

### WebSocket transport and single Session Pump

Qwen Audio Realtime is a persistent, event-driven WebSocket protocol, not an
atomic per-turn RPC. Within one provider generation, the client sends
`session.update` and many `input_audio_buffer.append` events while the provider
independently emits Session, Duplex, ASR, Response, conversation-item, cleanup,
and error events. Audio append has no per-frame acknowledgement requirement.

Exactly one serialized sender and one receive Session Pump own the active
WebSocket generation. The four logical projections must not read or write the
socket independently. Session Runtime exclusively allocates and advances the
local `provider_session_generation` before opening or reopening the physical
transport. The Transport never sees that local generation. The Pump binds
received events to it and attaches an adapter-local monotonic
`provider_event_seq`, receive-order metadata, and the available provider
session/input-item/response/output-item/output-index/content-index identities
before passing each event into the shared Qwen Realtime Session Adapter state
machine.

Every allowlisted server event requires a non-empty, generation-unique
`event_id`. `session.created` contains provider defaults and does not authorize
ingress. After the serialized sender emits `session.update`, the matching
`session.updated` must preserve the `session.created.session.id` and reflect the
requested `smart_turn`, modalities, voice, input-transcription, tool, and
role/profile configuration before provider context may transition to `CLEAN`.
Missing/duplicate event IDs or session/configuration mismatch fail closed.

`RealQwenWebSocketTransport` and `ScriptedFakeQwenWire` implement the same
transport contract and feed the same Session Adapter, normalization,
correlation, quarantine, cancellation, cleanup, and rebuild logic. The Fake
emits provider-shaped events one at a time; it must not return an aggregate
turn result, emit canonical events directly, invent route evidence, emit a
RouterDecision, or decide a Gate result.

Raw provider events remain adapter-local. They are not canonical Event Journal
events and must not enter a shareable trace as raw payloads. Only normalized
facts that affect ingress, evidence, routing, Gate, provider readiness,
cleanup, or delivery may reach the existing canonical event boundary.

### One logical Qwen session and four logical projections

The one logical Qwen session exposes four separately declared logical
projections:

1. `duplex_projection` provides speech-start, speech-stop, smart-turn,
   semantic-boundary, directedness, barge-in, and provider cancellation
   evidence.
2. `asr_projection` provides transcript deltas, final transcript evidence, and
   provider item correlation.
3. `fast_candidate_projection` provides a bounded complete transcript and
   bounded provider-native PCM candidate, with no route or release authority.
4. `composer_projection` consumes a sanitized runtime handoff and produces a
   text-only SpokenPlan candidate.

Provider reuse does not merge permissions. Each projection has its own
capability declaration, prompt/profile ID, output mode, normalization schema,
and source refs. The Qwen provider conversation is a cache and projection; it
is never the Event Journal, task state, confirmation authority, or
authoritative memory.

The provider event families map to these projections and internal lifecycle
state as follows:

| Provider event family | Adapter-local meaning |
| --- | --- |
| `session.created`, `session.updated` | Transport bootstrap and readiness; never a user turn |
| `input_audio_buffer.speech_started` | Speech-start and possible barge-in evidence; never sufficient for local commit |
| input transcription `delta`, `completed`, `failed` | ASR assembly correlated by input item and content index |
| ambient transcription `delta`, `completed` | Temporary-ID non-turn evidence; never bind to a conversation item, local commit, Route Evidence, or foreground output |
| `speech_stopped(reason=turn_invalid)` | Retract/reject the candidate turn; never trigger route or output authority |
| `conversation.item.created`, `conversation.item.deleted` | Input/output item inventory and cleanup acknowledgement |
| `response.created` and output-item/content-part lifecycle | Open response-scoped CandidateQuarantine and exact output/content correlation |
| assistant transcript `delta`, `done` | Candidate transcript assembly |
| audio `delta`, `done` | Candidate PCM-manifest assembly in memory |
| `response.done` | Completed, cancelled, or failed response terminal; never Gate or playback evidence by itself |

### Interaction Controller commit boundary

Provider `smart_turn` may begin response generation before
`TURN_INGRESS_COMMITTED`, but that work is provider-local speculation inside
CandidateQuarantine. Before the local commit it cannot emit a consumable
foreground candidate, start Route Evidence classification, start
candidate-safety classification, create a Fast Interaction output, or mutate
control-plane state. Rejected or held ingress cancels and deletes the
speculation.

Canonical final ASR is a two-predecessor join:

```text
ASR_TRANSCRIPT_OUTPUT_EMITTED
  requires TURN_INGRESS_COMMITTED
  and normalized provider transcription.completed
```

Either predecessor may arrive first. An early provider ASR final remains
adapter-local until the Interaction Controller commits the turn. An early
local commit waits for the correlated provider ASR final. Only after both exist
may canonical final ASR be emitted and route classification start.
Candidate-safety classification starts only after a complete, exactly
correlated candidate transcript exists.

The protocol defines causal partial order, not one total order:

```text
speech_started < speech_stopped|turn_invalid
ASR delta* < ASR completed|failed
response.created < response output events < response.done
ambient delta* < ambient completed
```

The runtime must not require `ASR completed < response.created`, and assistant
transcript and PCM deltas may interleave. Assistant
`conversation.item.created` and `response.output_item.added` may arrive in
either order. Response events observed before the local join remain
quarantined. All downstream events remain bound to the same committed turn,
utterance, context snapshot, and provider session generation.

Ambient transcription closes with `.completed` under a standalone temporary
item ID that never binds to a conversation item, active input item, or local
turn. It never creates a committed turn. A
`speech_stopped(reason=turn_invalid)` retracts the candidate ingress and
produces no Route Evidence, Router, Gate, or output chain. If provider output
nevertheless appears for ambient, invalid, rejected, or held ingress, it
remains quarantined, is cancelled and deleted, and taints/rebuilds provider
context when cleanup cannot be proven. Playback stopped for a provisional
barge-in is never resumed after a later `turn_invalid` result.

### Route Evidence and Candidate Safety Evidence

The stateless small-text adapter is named Route Evidence Adapter. It provides
two independent operations:

- `Route Evidence Adapter.classify_route` consumes final ASR plus a bounded
  route context projection. It emits a route hint, task-focus hint, foreground
  act hint, ACK kind, risk class/tags, uncertainty, and confidence. It does not
  receive the Qwen candidate.
- `Route Evidence Adapter.classify_candidate_safety` consumes the complete
  candidate transcript and its immutable digest plus a bounded safety context
  projection. It emits `SAFE`, `UNSAFE`, or `UNCERTAIN` evidence, prohibited
  claim flags, semantic categories, and confidence. It never receives raw PCM.

Both operations use strict schema validation. Timeout, malformed or oversized
output, invalid enums, unknown fields, confidence outside `[0,1]`,
`UNCERTAIN`, insufficient confidence, or a prohibited flag fails closed. A
`SAFE` label is still non-authoritative evidence and cannot itself release
output, decide confirmation, interpret UserPatch, or authorize a tool.

### Fast Interaction Orchestrator and Local Router authority

The local Fast Interaction Orchestrator joins separately recorded Qwen
candidate provenance, route-evidence provenance, candidate-safety provenance,
the immutable context snapshot, and provider generation into the normalized
Fast Interaction contract. It does not call a model, decide a route, release a
candidate, or disguise separate provider operations as one call.

Local Router owns RouterDecision. It is the only owner of `FAST_ONLY`,
`SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`, and TaskFocusState. Route
Evidence remains evidence. Candidate Safety Evidence remains evidence.

Fast Foreground Gate owns release. It deterministically compares the current
reducer state, Router decision, task focus, candidate policy checks, evidence
schemas and thresholds, capability health, exact correlation, immutable
digests, context snapshot, provider generation, turn, utterance, response, and
playback epoch. Only `FAST_ONLY + FOREGROUND_CHAT + ANSWER`, low risk, and all
checks passing can release the Qwen candidate. Slow, patch, ignore, ambiguous,
stale, degraded, or failed paths discard it and use only the applicable safe
template, clarification, or silence policy.

### Candidate quarantine, online correlation, and release token

CandidateQuarantine holds provider text and PCM in memory until permanent
release or discard. Phase one permits only complete, short, low-risk
candidates: at most 80 Unicode scalar values, at most 2,000 ms decoded audio,
and a correlated terminal provider response with completed status. Prefix-only
or partially correlated output is never eligible.

Because Response generation may begin before `TURN_INGRESS_COMMITTED`,
`response.created` opens only a response-level provisional quarantine entry
bound to provider generation, response ID, candidate ID, current playback
epoch, and optional provisional ingress/input-item refs. Canonical `turn_id`,
`utterance_id`, and fast-candidate `context_snapshot_id` bind exactly once only
after local ingress commit. Ambient, invalid, held, or rejected ingress never
receives those bindings and is cancelled/deleted/discarded.

Assistant `conversation.item.created` and `response.output_item.added` may
arrive in either order. CandidateQuarantine joins their item IDs, then
monotonically binds output and content indexes. Eligibility requires exactly
one assistant `message` output item and one `audio` content part. A
`function_call`, extra output/content part, identity rebind, or mismatch among
the assistant item, all output/content/delta/done events, and
`response.done.output[]` fails closed.

Online release requires exact provider correlation across the provider session
generation, response ID, output item ID, output index, content index,
transcript, and every PCM delta observed by the single receive Pump.
CandidateQuarantine computes an immutable `candidate_transcript_digest` and an
immutable `candidate_pcm_manifest_digest`. The PCM manifest covers observed
chunk order, byte length, audio format, sample rate, channel count, and decoded
duration.

WebSocket delivery and the single receive Pump preserve the order that the
Adapter observes. The Adapter requires provider `event_id` uniqueness and
assigns a local monotonic manifest sequence to accepted deltas.
It fails closed on duplicate provider event IDs, deltas after their terminal,
cross-lifecycle or cross-identity data, missing required terminals,
late-generation data, overflow, and terminal mismatch. If the provider does
not supply a chunk ordinal or end-to-end checksum, the Adapter must not claim
that it can detect an arbitrary omitted or permuted intermediate PCM delta;
disconnect, malformed lifecycle, or missing terminal remains the detectable
failure boundary.

There is no audible PCM before Gate. A passing Gate creates one immutable
`ForegroundReleaseTokenV1` bound to:

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

One per-session serialized compare-and-authorize boundary re-reads current
state, compares every token field, appends Gate pass and
`FOREGROUND_OUTPUT_COMMITTED` with the unchanged token, and inserts a local
playback-outbox item before leaving the event-loop critical section. It
performs no network await, model call, clock read, or token restamping.

Talker validates the unchanged release token immediately before
`PLAYBACK_SPAN_STARTED` and before writing the first PCM byte. A mismatch
retires the outbox item and records cancellation/arbitration without starting
playback. `FOREGROUND_OUTPUT_COMMITTED(user_visible_channel=audio_pending)` is
authorization, not evidence that the user heard audio.

### PCM qualification and non-blocking shadow verification

The online low-latency path performs no per-turn independent PCM
back-transcription. Online Gate inputs are the complete candidate transcript
and PCM, exact correlation, immutable digests, independent candidate-safety
evidence, capability state, and deterministic policy checks.

Before native PCM is enabled for a selected model/profile/correlation
implementation, pre-promotion PCM back-transcription qualification must pass on
a locked synthetic or provider-generated corpus with playback disabled.

After promotion, every released native-PCM turn runs non-blocking live PCM
shadow verification through an independent ASR adapter. It begins after
complete PCM is available and never authorizes, delays, or gates the current
turn. The recorded result contains digests, bounded refs, duration, format,
normalized transcript metadata, number/entity/unit equivalence, output mode,
and `MATCH|MISMATCH|UNCERTAIN`; it contains no PCM.

A shadow mismatch disables native PCM for subsequent turns in the Connect
session. A shadow `MISMATCH`, `UNCERTAIN`, timeout, or digest disagreement is a
critical capability violation: disable the capability, taint and rebuild
provider context, and fall back to approved text plus TTS or deterministic
templates. It cannot retract audio already played.

PCM remains memory-only and is destroyed after playback/discard plus shadow
completion or timeout.

### Context Assembler and session-only memory

The local Context Assembler reads only the per-session Event Journal, reducer
state, committed local conversation items, an in-memory Session Memory store,
and versioned persona/style configuration. It emits immutable
`ContextSnapshotV1` projections for route evidence, candidate safety, Qwen
candidate generation, and Composer. The provider conversation is never read
back as the sole source of task state, plan version, confirmation state, or
memory.

`ContextSnapshotV1` binds:

```text
snapshot_id
session_id
conversation_id
source_event_seq
provider_session_generation
interaction_state_version
task_focus_state_version
active_task_ref optional
active_task_state optional
plan_version optional
task_event_seq optional
pending_confirmation_ref optional
last_assistant_act
recent_dialogue_refs
session_summary_ref optional
persona_profile_id
policy_versions
redaction_status
```

Authoritative task or confirmation changes invalidate stale requests whose
results could mutate state or authorize playback. Results never silently bind
to a newer snapshot.

Memory is separated into current-turn memory, current-task memory, and bounded
session memory. Session memory retains only committed dialogue, a bounded local
summary, and session-local style hints. There is no durable memory store or
cross-Connect rehydration in Slice 3B.

### Slow-to-Fast handoff and text-only Composer

SlowTask progress, clarification, confirmation, final commitment, degraded,
and failed states enter the fast expression path only as
`SlowToFastHandoffV1`:

```text
handoff_id
kind=PROGRESS|CLARIFICATION|CONFIRMATION|FINAL|DEGRADED|FAILED
delivery_mode=CONTEXT_ONLY|SPEAK_WHEN_IDLE
task_id
plan_version
task_event_seq
source_event_ids
facts_ref
must_say_fields
forbidden_claims
risk_warnings
confirmation_state optional
response_style_hint
priority
expires_at_monotonic_ms optional
redaction_status
```

Only canonical current-plan source events may create a handoff. Raw Slow LLM
text, raw reasoning, raw tool output, stale evidence, and untrusted web content
are not handoff sources. Every handoff is revalidated against current reducer
state and receives a replayable queue, coalesce, selection, stale, expiry,
cancel, or discard disposition.

The same Qwen session may implement the Composer role only with a separate
role/profile and sanitized ephemeral context projection. Phase one uses a
text-only Qwen Composer before truthfulness/coverage checks. It captures the
complete text-only SpokenPlan candidate, then requires
ProgressTruthfulnessCheck for progress or CommitmentCoverageCheck for final
commitments before TTS/Talker. The Composer cannot change immutable facts,
must-say fields, resolved arguments, risk warnings, confirmation state, tool
status, or current plan identity.

Ephemeral handoff and Composer assistant items are deleted with acknowledged
cleanup. A failed check retries once with the same immutable facts or falls
back to a deterministic safe template. Provider cleanup failure taints and
rebuilds the session.

A per-session Response Arbiter serializes user fast responses, confirmation,
clarification, progress, and final delivery. User speech has highest priority;
user-turn fast responses outrank progress; confirmation/clarification outrank
ordinary progress; final results outrank stale or repetitive progress; only
one provider response may be active; repeated progress is coalesced to the
newest current-plan handoff.

### Provider-context readiness and rebuild

The adapter exposes:

```text
provider_context_state=
  CLEAN|CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED
```

The system requires `provider_context_state=CLEAN before provider-backed
ingress`. Only `CLEAN` accepts microphone frames that can become a committed
provider turn. During cleanup, taint, or rebuild, provider ingress drops frames
at the boundary, records bounded/coalesced counts, never queues or replays the
audio, pauses provider-backed turn commit, and asks for a fresh utterance after
recovery.

Provider item deletion requires acknowledgement. Pending acknowledgement sets
`CLEANUP_PENDING`; missing or invalid acknowledgement advances to `TAINTED`,
then `REBUILDING`. Generation observed outside `CLEAN` is quarantined,
cancelled, and cannot create control-plane events.

Before rebuild network work, Session Runtime advances provider generation and
the per-session serialized control authority asks Interaction Controller to
advance playback epoch. The Adapter only binds and validates the resulting
values. Rebuild drops old queued PCM, rejects old-generation events, and
reconstructs only locally committed dialogue, bounded session summary, and the
current active task public projection. It preserves the browser Connect and
local journal but never survives a new Connect.

### Delivery-aware assistant history

Every provisional assistant item begins as `PENDING` and reaches exactly one
terminal `FULL|TRUNCATED|NOT_STARTED delivery disposition`.

- `FULL` requires `PLAYBACK_FINISHED` plus final `PLAYBACK_COMMITTED` coverage
  of the authorized audio span.
- `NOT_STARTED` applies when playback never begins because of deadline, epoch,
  rebuild, interruption-before-start, queue, or arbitration failure. The
  unheard provider assistant item is deleted with acknowledgement and its text
  is absent from delivered local/provider history.
- `TRUNCATED` applies after playback starts but does not fully complete. Local
  history records the actual stop offset when known; the full provider item is
  deleted. Without independently verified word-level alignment, no textual
  prefix is claimed as fully delivered. An unknown stop offset retains no text
  prefix and forces provider-context rebuild.

Undelivered suffixes never become shared conversational facts. The same rule
applies to provider-native fast PCM and SlowTask-derived TTS. A native
audio-pending foreground commit must start playback within 1,000 ms or become
`NOT_STARTED`.

### Provider auto-cancel and local barge-in convergence

Provider cancellation and local playback truncation are separate asynchronous
operations. In `server_vad`/`smart_turn`,
`input_audio_buffer.speech_started` while a response is active automatically
interrupts that response with
`response.done(status=cancelled,
status_details.reason=turn_detected)`. The Session Adapter may send
`response.cancel` only while the same response is still active and no
auto-cancel terminal has been observed; successful explicit cancellation ends
with `status_details.reason=client_cancelled`. Auto-cancel and explicit cancel
must converge to one response terminal. If automatic cancellation wins the
race, a later explicit cancel may produce a non-terminal
`invalid_request_error`; it is not a second response terminal and cannot
advance another authority chain.

The local Interaction Controller does not wait for that terminal. It advances
the playback epoch, clears queued PCM, and emits the existing interrupt and
truncate chain independently. A cancelled provider terminal proves only that
the current provider Response became terminal; the provider session generation
and WebSocket remain active unless cleanup policy separately triggers rebuild.
It does not prove browser playback stopped. Old-epoch deltas after cancellation
are discarded. Cross-response,
cross-content, or old-generation deltas fail correlation and may taint/rebuild
provider context.

### Canonical events and replay

This accepted decision defines exactly nine canonical additions synchronized
into ADR-002. Every event also carries the ADR-002 minimum envelope and
applicable context-binding fields.

| New event | Owner | Required fields | Causal predecessor | Replay meaning | Redaction boundary |
| --- | --- | --- | --- | --- | --- |
| `ROUTE_EVIDENCE_OUTPUT_EMITTED` | Route Evidence Adapter | `adapter_id`, `adapter_type=route_evidence`, `adapter_request_id`, `turn_id`, `utterance_id`, `final_asr_event_id`, `context_projection_event_id`, `route_hint`, `task_focus_hint`, `foreground_act_hint`, `ack_kind`, `risk_class`, `risk_tags`, `evidence_uncertainty`, `confidence`, `schema_name`, `normalization_status`, `output_mode` | A final `ASR_TRANSCRIPT_OUTPUT_EMITTED` caused by the same committed turn, plus its `MODEL_CONTEXT_PROJECTION_EMITTED` | Replays the non-authoritative route evidence consumed by the local Router without rerunning a model; it must precede the consuming `ROUTER_DECISION_EMITTED` | Metadata, enums, confidence, and bounded refs only; no raw prompt, PCM, provider body, secret, credential, or unredacted transcript |
| `CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED` | Route Evidence Adapter | `adapter_id`, `adapter_type=route_evidence`, `adapter_request_id`, `turn_id`, `utterance_id`, `qwen_response_id`, `candidate_transcript_digest`, `context_projection_event_id`, `decision=SAFE|UNSAFE|UNCERTAIN`, `semantic_categories`, `prohibited_flags`, `confidence`, `schema_name`, `normalization_status`, `output_mode` | Complete correlated candidate transcript plus the candidate-safety `MODEL_CONTEXT_PROJECTION_EMITTED` | Replays independent candidate-safety evidence; its transcript digest must equal the later candidate event and release token, and it never substitutes for Gate authority | Digest, enums, bounded categories/flags, confidence, and refs only; no candidate text, raw PCM, prompt, provider body, secret, credential, or raw task state |
| `MODEL_CONTEXT_PROJECTION_EMITTED` | Context Assembler | `projection_id`, `target_role=route_evidence|candidate_safety|fast_candidate|composer`, `source_event_ids`, `context_snapshot_id`, `source_event_seq`, `provider_session_generation`, `active_task_ref` optional, `plan_version` optional, `task_event_seq` optional, `pending_confirmation_ref` optional, `projection_ref`, `policy_version`, `redaction_status`, `output_mode` | Current reducer/journal snapshot whose terminal sequence is `source_event_seq` | Replays which immutable, versioned, bounded projection a model role consumed and permits stale-snapshot rejection without rebuilding raw prompts | Refs and bounded metadata only; no raw prompt, raw provider payload, PCM, secret, credential, raw tool output, private reasoning, or unredacted real-user text |
| `SLOW_TO_FAST_HANDOFF_EMITTED` | Slow-to-Fast Bridge | `handoff_id`, `kind`, `delivery_mode`, `task_id`, `plan_version`, `task_event_seq`, `source_event_ids`, `facts_ref`, `must_say_fields_ref`, `forbidden_claims_ref`, `priority`, `expiry_status`, `redaction_status` | One or more canonical current-plan progress, clarification, confirmation, commitment, degraded, or failure source events | Replays the validated handoff candidate and its immutable current-plan fact boundary without rerunning SlowTask or Composer | Sanitized refs, enums, identity, and bounded policy metadata only; no raw Slow LLM reasoning, raw tool output, raw web evidence, provider body, secret, credential, or stale unadopted evidence |
| `SLOW_TO_FAST_HANDOFF_DISPOSITIONED` | Response Arbiter / Slow-to-Fast Bridge | `handoff_id`, `disposition=QUEUED|COALESCED|SELECTED|STALE|EXPIRED|CANCELLED|DISCARDED`, `response_arbitration_event_id` optional, `replacement_handoff_id` optional, `current_task_id` optional, `current_plan_version` optional, `current_task_event_seq` optional, `reason` | The referenced `SLOW_TO_FAST_HANDOFF_EMITTED`; selection also follows the applicable `RESPONSE_ARBITRATION_DECIDED` | Replays every handoff lifecycle outcome; only `SELECTED` can cause a Composer context projection, while coalesced/stale/expired/cancelled/discarded handoffs cannot speak | IDs, enums, current-version metadata, and bounded reason only; no handoff facts, raw text, PCM, provider body, secret, credential, or raw task/tool content |
| `RESPONSE_ARBITRATION_DECIDED` | Per-session Response Arbiter | `arbitration_id`, `selected_source_type=user_fast|confirmation|clarification|progress|final|none`, `selected_source_event_id` optional, `superseded_source_event_ids`, `provider_session_generation`, `playback_epoch`, `interaction_state_version`, `decision_reason` | A user fast candidate/output request, current handoff, interrupt, or delivery cancellation condition that requires selection, coalescing, supersession, or cancellation | Replays which user-facing source won, which sources were superseded, and why; it records material delivery decisions rather than every in-memory queue operation | IDs, enums, versions, epoch, and bounded reason only; no response text, raw audio, provider payload, secret, credential, or raw task/tool content |
| `PROVIDER_CONTEXT_STATE_CHANGED` | Qwen Realtime Adapter / Session Runtime | `adapter_id`, `provider_session_generation`, `from_state=CLEAN|CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED`, `to_state=CLEAN|CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED`, `reason`, `source_event_ids`, `cleanup_item_count` optional, `delete_ack_count` optional, `cleanup_outcome` optional, `dropped_audio_frame_count` optional, `output_mode` | Provider cleanup request/ack, correlation or shadow failure, rebuild transition, Connect close, or equivalent causal source event | Replays the ingress-readiness barrier, bounded frame-drop window, generation advance, cleanup outcome, and whether provider-backed turns were eligible | Bounded counts, opaque refs, enums, and reason only; no microphone frames, raw PCM, deleted item content, provider body, session secret, credential, or authorization header |
| `CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED` | Independent ASR Adapter / Candidate Audio Verifier | `adapter_id`, `adapter_type=asr`, `adapter_request_id`, `turn_id`, `utterance_id`, `qwen_response_id`, `candidate_transcript_digest`, `candidate_pcm_manifest_digest`, `audio_format_ref`, `decoded_duration_ms`, `independent_transcript_ref`, `normalized_transcript_digest`, `exact_numbers_entities_units_match`, `equivalence=MATCH|MISMATCH|UNCERTAIN`, `output_mode` | A complete PCM manifest and candidate transcript; in live use it follows release/complete PCM and is not a predecessor of that turn's Gate | Replays qualification or non-blocking live shadow outcome; only qualification `MATCH` counts toward promotion, while a live non-match disables later native PCM without changing the already-delivered turn | Digests, duration, format ref, bounded transcript ref, equivalence metadata, and output mode only; never PCM, raw independent transcript, raw provider payload, secret, credential, or unredacted real-user text |
| `ASSISTANT_DELIVERY_DISPOSITIONED` | Delivery Reconciler / Talker Runtime | `assistant_item_ref`, `source_output_event_id`, `release_token_ref` optional, `playback_span_id` optional, `from_status=PENDING`, `to_status=FULL|TRUNCATED|NOT_STARTED`, `actual_stop_offset_ms` optional, `delivery_offset_status=KNOWN|UNKNOWN|NOT_APPLICABLE`, `provider_item_cleanup_status=NOT_REQUIRED|ACKNOWLEDGED|TAINTED`, `source_event_ids` | Playback finish/commit for `FULL`; truncate or delivery failure for `TRUNCATED`; start deadline, arbitration, epoch, rebuild, interruption-before-start, or queue failure for `NOT_STARTED` | Replays the single terminal delivery outcome for each provisional assistant item and determines exactly what may enter delivered local/provider history | Opaque item/token/span refs, status, offsets, cleanup metadata, and causal IDs only; never assistant/provider payload, raw audio, PCM, transcript body, secret, credential, or undelivered suffix |

The following existing event schemas receive backward-compatible amendments
for the parallel topology:

| Existing event | Amendment |
| --- | --- |
| `ASR_TRANSCRIPT_OUTPUT_EMITTED` | For a Qwen Realtime provider-backed turn, add `provider_session_generation`, opaque `qwen_input_item_ref`, and `qwen_input_content_index`. Emission remains causally after `TURN_INGRESS_COMMITTED` and the correlated provider transcription final; raw provider IDs and transcript bodies stay outside the shareable event. |
| `FAST_INTERACTION_OUTPUT_EMITTED` | For parallel topology, owner is the local Fast Interaction Orchestrator. Add `fast_interaction_topology`, separate Qwen candidate adapter/request provenance, route-evidence event/request provenance, candidate-safety event/request provenance, optional audio-shadow provenance, `context_snapshot_id`, `provider_session_generation`, and normalization status. |
| `FOREGROUND_REPLY_CANDIDATE_EMITTED` | Remains caused by the composite Fast Interaction output. Add `fast_interaction_topology`, exact `qwen_response_id`, `qwen_output_item_id`, `qwen_output_index`, `qwen_content_index`, `candidate_transcript_digest`, `candidate_pcm_manifest_digest`, audio format/duration, provider generation, context snapshot, and optional shadow event ref. Its transcript digest must equal the candidate-safety evidence digest. |
| `FOREGROUND_ACT_GATE_PASSED` | Add `fast_interaction_topology`, candidate-check policy version and individual results, provider generation, context snapshot, immutable `release_token_ref`, and the separate route/candidate-safety evidence refs. Pass remains deterministic and authoritative only inside the Fast Foreground Gate. |
| `FOREGROUND_ACT_GATE_FAILED` | Add the same topology, policy-result, generation, snapshot, evidence, correlation/digest-check, and optional release-token metadata needed to replay the fail-closed reason and downgrade/discard path. |
| `FOREGROUND_OUTPUT_COMMITTED` | Add `fast_interaction_topology` and the exact unchanged `release_token_ref`; native PCM uses `user_visible_channel=audio_pending`, which is authorization rather than hearing evidence. |
| `PLAYBACK_SPAN_STARTED` | For provider-native PCM, add `release_token_ref`, provider session generation, response/output-item/output-index/content-index correlation, and playback epoch; Talker must validate them before first-byte output. |
| `PLAYBACK_COMMITTED` | Add `release_token_ref` when provider-native PCM is used and preserve the actual delivery offset semantics needed for `FULL` or `TRUNCATED` reconciliation. |
| `PLAYBACK_FINISHED` | Add `release_token_ref` when provider-native PCM is used and bind the final offset to the delivery disposition chain. |
| `TTS_TRUNCATED` | Add optional `release_token_ref`, delivery-reconciliation identity, and causal linkage to the terminal assistant delivery disposition and any required provider-context cleanup. |

Existing atomic-single-call events and historical fixtures remain valid. A
missing `fast_interaction_topology` means legacy `atomic_single_call`; new
parallel events set it to `speculative_candidate_parallel_route`. The
compatibility default does not infer new route-evidence, candidate-safety,
provider-generation, transcript-digest, or PCM-manifest provenance into
historical data.

Replay uses recorded refs, decisions, digests, dispositions, and state changes;
it never reruns Qwen, Route Evidence, ASR verification, Composer, SlowTask,
tools, or TTS. Reducers remain deterministic and must not depend on network,
wall clock, randomness, or async scheduling order.

### Capability declarations and degradation

ADR-011 synchronization after acceptance must add `route_evidence` as an
adapter type. Its capability matrix declares route schema, task focus,
foreground act hint, ACK kind, risk tags, candidate-safety schema, prohibited
claim detection, confidence, strict JSON validation, route latency targets,
and timeout/retry policy.

The ASR capability matrix declares independent candidate-output audio
verification support, supported PCM formats/rates/channels, verification
latency, equivalence policy version, and real/mock/fallback/degraded status.

The Qwen role/session capabilities independently declare smart-turn semantic
boundary and streaming ASR support, response cancellation, text/audio response
support, provider item creation/deletion acknowledgement, manual idle response,
one-active-response restriction, quarantine, native-audio release, typed
provider-context readiness, context rebuild/rehydration, distinct fast and
Composer role-profile IDs, and real/mock/fallback/degraded status.

Documentation support, implementation support, provider-free verification, and
real-live verification are separate capability facts. Missing required
capability fails closed or selects an explicit text/TTS/template fallback. A
mock, fallback, or degraded capability cannot be reported as real.

### Validation and promotion gates

Governance validation requires human acceptance before implementation,
canonical-event synchronization into ADR-002, capability synchronization into
ADR-011 and derived specifications, register synchronization only after human
acceptance, and consistency across ADR-001/003/009/012/013/015/017. The
historical Slice 3A.2.1 evidence remains non-authorizing.

Provider-free contract tests must drive a protocol-faithful
`ScriptedFakeQwenWire` through the same Session Adapter used by the later Real
transport. They cover the handshake
`session.created -> session.update -> session.updated`, provider defaults
versus matching updated ID/configuration, mandatory generation-unique server
event IDs, multiple audio appends without per-frame acknowledgement,
ASR-final-first and response-first legal schedules, interleaved transcript/PCM
deltas, both assistant-item/output-item orders and exact ID join, ambient and
`turn_invalid` with zero commit/route/output authority, one-active-response
enforcement, provider auto-cancel versus explicit-cancel convergence including
a late non-terminal invalid-request error, late cancelled-response deltas,
wrong response/output-item/output-index/content-index correlation, extra
output/content/function-call rejection, missing terminal, delete-ack failure,
rebuild generation fencing, and Fake/Real transport conformance.

The same tests cover pre-commit speculation cleanup, one
Router/Gate/output terminal per committed turn, all routes and task-focus
modes, candidate-safety fail-closed outcomes, immutable digest and correlation
failures, quarantine overflow, release-token mismatches, barge-in between
authorization and playback, stale handoffs, arbitration/coalescing, provider
cleanup/rebuild, frame drop without replay,
`FULL|TRUNCATED|NOT_STARTED`, and deterministic replay/state digests. Slice
3B.1 is provider-free, reports `output_mode=mock`, never connects to Qwen, and
never plays provider PCM.

Slice 3B.2 replaces only `ScriptedFakeQwenWire` with the real Qwen WebSocket
transport while retaining the same Session Adapter, Pump, normalized
projections, correlation, quarantine, Router, and Gate boundaries. Real Qwen,
Route Evidence, and Candidate Safety behavior begin in shadow/qualification;
provider PCM remains inaudible.

Route Evidence promotion requires a separately developed corpus and a locked
80-case human-adjudicated holdout with at least ten cases for each
authoritative route and at least ten each for active-task patch/control and
ambiguity. A real adapter must achieve at least 95% exact route accuracy, at
least 95% exact task-focus accuracy, 100% recall for patch, confirmation,
cancel/switch, non-assistant, and high-risk-to-slow/clarify cases, and zero
critical violations.

Candidate-safety promotion requires at least 200 synthetic/redacted development
texts plus a separate locked holdout of at least 200 texts, split into at least
100 eligible and 100 prohibited candidates. It requires zero
unsafe/prohibited candidates classified `SAFE`, at least 90% of eligible
candidates classified `SAFE`, and schema-valid or explicit fail-closed handling
for every sample.

Native-PCM promotion additionally requires at least 100 locked
transcript/PCM pairs, including at least 60 matches and 40 mismatches. It
requires zero mismatches classified `MATCH` and at least 95% of true pairs
classified `MATCH`. During live qualification, every released native-PCM turn
receives the same non-blocking shadow verification.

Real-device acceptance requires repeated low-risk fast, complex-task, patch,
ignore/ambiguity, slow-progress, slow-final, barge-in, and rebuild scenarios;
at least ten barge-in attempts; and a session of at least 30 minutes and 50
committed turns. Any critical violation, leaked PCM, missing required event,
missing verification record, provider/browser crash, or timeout fails the
sample rather than being excluded.

Development SLOs use Event Journal monotonic time and truthful capability mode:

- adjudicated speech onset to speech-start evidence: P95 no more than 150 ms;
- barge-in candidate to truncate request: P95 no more than 250 ms;
- adjudicated last speech to speech-end evidence: P95 no more than 900 ms;
- final ASR to route evidence: P95 no more than 300 ms, with a 700 ms hard
  deadline;
- committed turn to first non-zero browser playback commit for fast output:
  P95 no more than 800 ms;
- SlowTask created to first grounded progress playback commit: P95 no more than
  2 seconds;
- distinct grounded progress playback markers: every 5-10 seconds while work
  remains active.

Complete candidate buffering, candidate-safety evidence, exact online
correlation/digests, and the 2,000 ms candidate cap remain on the online
critical path. Independent PCM back-transcription latency is measured and
reported separately. Failure to meet the online SLO with all safety conditions
intact leaves provider-native PCM disabled; the implementation may not recover
latency by releasing an unapproved prefix.

## Alternatives Considered

1. Keep the Slice 3A.2.1 dual-session topology as the final architecture. This
   avoids same-session cleanup complexity but duplicates provider context and
   cannot validate the approved single-session interaction design.
2. Wait for route classification and then call a separate fast answer model.
   This is simpler to reason about but adds the second answer-model round trip
   that the speculative parallel topology is intended to remove.
3. Let Qwen decide route and release its own candidate. This reduces local
   coordination but violates Local Router and Gate authority and cannot provide
   independent candidate-safety evidence.
4. Make independent PCM back-transcription a per-turn online Gate prerequisite.
   This adds another serial latency dependency and is unnecessary when exact
   provider correlation/digests and independently qualified PCM behavior are
   enforced. Qualification plus non-blocking shadow verification is preferred.
5. Treat provider conversation history as authoritative memory. This simplifies
   rehydration but allows cleanup drift or provider state to override local
   journal/task/confirmation truth.
6. Let Qwen directly render slow-system facts as native audio. This is natural
   but would bypass text-level truthfulness and coverage checks. Phase one
   therefore uses text-only Composer output followed by existing checks and
   TTS.

## Consequences

Positive consequences:

- one logical session with one active transport generation can preserve a
  natural audio-native foreground while route classification runs in parallel;
- independent route and candidate-safety evidence remain auditable without
  displacing local authority;
- complete candidate quarantine and immutable release tokens preserve
  Gate-before-leak across async delivery;
- session-only local context and provider cleanup/rebuild prevent provider
  history from becoming hidden authority;
- SlowTask progress and final commitments can share the conversational session
  while retaining SlowTask fact ownership and Composer checks;
- delivery-aware history prevents unheard or interrupted suffixes from
  contaminating later context;
- replay can reconstruct evidence, routing, Gate, handoff, provider readiness,
  playback, and delivery outcomes without model calls or raw PCM.

Costs and risks:

- the per-session runtime must coordinate quarantine, two evidence operations,
  exact provider correlation, serialized release, playback-token validation,
  provider item cleanup, and delivery reconciliation;
- complete candidate buffering may make the 800 ms fast target difficult;
- provider protocol support does not prove live capability; each model,
  endpoint, region, account, prompt/profile, and policy version requires
  qualification;
- non-blocking shadow mismatch can only disable future playback, not retract
  current audio;
- provider cleanup failure intentionally drops recovery-window utterances;
- canonical schemas, capability profiles, replay reducers, datasets, and
  long-session acceptance add substantial validation work.

## Impacted Modules

- Qwen Realtime Transport contract, `RealQwenWebSocketTransport`, and
  protocol-faithful `ScriptedFakeQwenWire`
- Qwen Realtime Session Adapter / single Session Pump and its Duplex, ASR,
  Fast Candidate, and Composer projections
- Interaction Controller
- CandidateQuarantine
- Context Assembler and Session Memory
- Route Evidence Adapter
- Candidate Audio Verifier / ASR Adapter
- Fast Interaction Orchestrator
- Local Router and TaskFocusState
- Fast Foreground Gate and release-token/outbox boundary
- Response Arbiter
- SlowTask Runtime and Slow-to-Fast Bridge
- Thinker-as-Composer, ProgressTruthfulnessCheck, and
  CommitmentCoverageCheck
- ACK Template Catalog
- TTS Adapter and Talker
- Event Journal, reducers, Trace, and Replay
- Adapter Registry and capability profiles
- Evaluation harness, locked corpora, real-device runner, and governance tests
- Provider context cleanup, rebuild, and delivery-history reconciliation

## Validation Method

Slice 3B.0 established this accepted governance artifact and synchronized its
register, canonical-event, capability, and cross-ADR amendments. Its recorded
validation checks:

1. scope, authority statements, event additions, compatibility amendments,
   capability declarations, promotion gates, and redaction boundaries match
   the approved source design;
2. exactly nine new canonical events are defined with owner, required fields,
   causal predecessor, replay meaning, and redaction boundary;
3. existing atomic-single-call events and historical fixtures remain valid,
   with the explicit topology compatibility default;
4. raw provider WebSocket events remain adapter-local rather than becoming
   provider-specific canonical events;
5. Markdown whitespace passes `git diff --check`;
6. runtime, real-model qualification, and native-PCM enablement remain separate
   later-slice gates.

Later slices must satisfy the provider-free, dataset, live-device,
long-session, critical-violation, security, and SLO gates in the Decision
section before enabling the corresponding capability. Passing document review
does not claim any runtime capability, native PCM enablement, real model
qualification, or durable memory.

## Open Questions

None for Slice 3B.0. Later production privacy, durable memory, multiple active
SlowTasks, streaming-prefix playback, and real side effects require later ADRs.
