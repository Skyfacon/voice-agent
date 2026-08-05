# Qwen Audio Realtime Single-Session Fast/Slow Interaction Design

Date: 2026-07-25 (+0800)

Amended: 2026-07-26 (+0800), protocol-level WebSocket and Slice 3B.1 Fake
boundary clarified

Status: design approved by user; ADR-018 accepted on 2026-07-25; runtime,
real-model qualification, and provider-native PCM promotion remain
unimplemented

Repository: `/Users/a123/voice-agent`

## 1. Decision Summary

Phase one will use:

- one logical Qwen Audio Realtime session per browser Connect, with at most one
  active provider WebSocket transport generation at a time;
- one serialized sender and one receive Session Pump per provider generation;
- one shared Qwen Realtime Session Adapter consumed by both the provider-free
  `ScriptedFakeQwenWire` and the later real WebSocket transport;
- one stateless small-text `Route Evidence Adapter`, with separate
  `classify_route` and `classify_candidate_safety` operations;
- route classification invoked in parallel with Qwen candidate generation,
  followed by candidate-safety classification as soon as the complete
  candidate transcript is available;
- independent ASR back-transcription for pre-promotion qualification and
  non-blocking live shadow verification, never as a per-turn playback gate;
- the existing local deterministic Router as the only owner of
  `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, and `IGNORE`;
- the existing deterministic Fast Foreground Gate as the only owner of
  candidate release;
- a local `Context Assembler` as the source of Router, Qwen, and SlowTask
  context projections;
- a structured `SlowToFastHandoff` for SlowTask progress, clarification,
  confirmation, and final results;
- session-only memory and one active SlowTask; durable cross-session memory is
  explicitly deferred.

The user-facing fast path is speculative but not audible before approval:

```text
user audio
  -> Qwen smart_turn evidence
  -> Interaction Controller local turn commit
       -> final ASR
       -> Route Evidence Adapter.classify_route
  -> Qwen candidate text+PCM -> bounded CandidateQuarantine
       -> complete transcript
       -> Route Evidence Adapter.classify_candidate_safety
       -> complete PCM + immutable correlation/digests
       \-> independent ASR shadow verification after/beside delivery
  -> Fast Interaction Orchestrator joins recorded evidence
       -> Local Router
       -> Fast Foreground Gate compare-and-authorize
            -> FAST_ONLY: release the completed bounded Qwen candidate
            -> SPAWN/PATCH: discard candidate, then use a safe dynamic ACK
            -> IGNORE: discard and remain silent
            -> AMBIGUOUS/degraded: discard and use controlled clarification
```

The arrows describe local authorization dependencies, not provider wire order.
Provider ASR and Response events may interleave.

Qwen remains the audio-native conversational Thinker. The small text model is
not a second answer generator and is not the authoritative Router. It produces
structured route and candidate-safety evidence only.

## 2. Governance Position

This design extends accepted ADR-017 through accepted ADR-018 and the existing
Qwen Realtime experiment. It must not be implemented as an ordinary Slice 3A
bug fix.

Slice 3A.2.1 remains a dual-session, provider-audio-disabled recovery hotfix.
Nothing in this design retroactively authorizes single-session behavior or
provider-native playback in that slice.

Governance status:

1. ADR-018, `Single-session Qwen Realtime, Parallel Route Evidence, and
   Slow-to-Fast Context Projection`, was accepted by explicit human review on
   2026-07-25.
2. Its canonical-event, capability, register, AGENTS.md, and cross-ADR
   amendments are the authoritative architecture boundary.
3. The existing Qwen proposal and Slice 0-3A.2.1 acceptance records remain
   historical experiment evidence and do not authorize Slice 3B behavior.
4. This design remains the detailed source specification beneath ADR-018; it
   does not itself prove runtime behavior, real model support, or native-PCM
   readiness.

## 3. Goals

Phase one must demonstrate:

1. One browser Connect creates one logical Qwen Audio Realtime Voice session,
   with at most one active physical WebSocket generation at a time.
2. Qwen `smart_turn` supplies real speech-start, speech-stop, semantic turn
   boundary, ASR, response generation, and provider cancellation evidence.
3. Qwen produces the user-facing low-risk fast answer candidate.
4. A small text model classifies route/task focus in parallel and independently
   verifies the completed Qwen candidate transcript before release.
5. Local Router and Gate remain authoritative and replayable.
6. Provider text and PCM remain inaudible until final local route and Gate
   approval.
7. Slow routes receive truthful, dynamically selected safe acknowledgements.
8. SlowTask progress and final results can be projected into the same Qwen
   session and expressed naturally.
9. SlowTask facts, confirmation, plan version, tool authority, and lifecycle
   remain locally authoritative.
10. A user can interrupt Qwen or SlowTask-derived playback and immediately
    start another turn.
11. All critical decisions and playback state are journaled without persisting
    raw PCM.

## 4. Non-Goals

Phase one does not include:

- durable cross-session memory;
- multiple concurrent active SlowTasks;
- pause/resume of SlowTask or assistant playback;
- true external writes, payment, booking, deletion, or communication;
- arbitrary provider-native audio for SlowTask final facts before coverage
  validation;
- raw ReAct reasoning or chain-of-thought transfer to Qwen;
- production privacy, authentication, or retention policy;
- speculative audio playback before final Gate approval;
- automatic model or prompt promotion without a locked evaluation gate.

Closing the browser Connect session discards session memory. A transport rebuild
inside the same Connect session may rehydrate from local committed state, but a
new Connect starts a new conversation.

## 5. Architecture and Authority

### 5.1 Components

| Component | Responsibility | Must not do |
| --- | --- | --- |
| Qwen Realtime Transport | Implement provider wire `open/send/recv/close`; use `ScriptedFakeQwenWire` in 3B.1 and the real Qwen WebSocket transport from 3B.2 | Normalize provider semantics, emit canonical events, decide routes/Gates, log raw payloads, or expose credentials |
| Session Runtime | Allocate/advance the local provider generation and own one active transport handle across Connect/rebuild | Parse provider events, decide routes/Gates, or expose the local generation to Transport |
| Qwen Realtime Session Adapter / Pump | Bind/validate the runtime generation; own the single serialized sender/receiver, event state machine, exact correlation, normalized Duplex/ASR/Fast Candidate/Composer projections, cancellation, delete acknowledgement, and rebuild requests | Allocate provider generation, commit turns, decide routes, mutate SlowTask, authorize tools, bypass playback gates, or let each projection read the socket independently |
| Interaction Controller | Apply deterministic ingress, interruption, and truncate policy | Interpret task semantics or accept confirmation |
| CandidateQuarantine | Hold response-scoped provider text and PCM until release/discard | Persist PCM or emit user-visible output |
| Context Assembler | Build versioned, bounded context projections from local authoritative state | Treat provider conversation history as authoritative memory |
| Route Evidence Adapter | Independently classify route/task focus and the completed Qwen candidate's semantic safety through two stateless operations | Generate user answers or emit `ROUTER_DECISION_EMITTED` |
| Candidate Audio Verifier | Qualify a model/profile before native-PCM promotion and shadow-check live PCM without blocking playback | Persist PCM, generate an answer, or become a per-turn Gate dependency |
| Fast Interaction Orchestrator | Join separately recorded Qwen, route, and candidate-safety provenance into the normalized Fast Interaction contract | Call an external model, decide route, or release output |
| Local Router | Emit the authoritative RouterDecision and TaskFocusState update | Generate spoken answers or interpret UserPatch |
| Fast Foreground Gate | Deterministically compare current state and recorded evidence, then authorize, discard, or downgrade foreground output | Trust Qwen or the evidence model as final authority |
| SlowTask Runtime | Own task lifecycle, plan version, confirmation, evidence review, and SemanticCommitment | Drive playback directly |
| Slow-to-Fast Bridge | Normalize current-plan progress/commitments into controlled Qwen Composer input | Forward raw ReAct reasoning, raw tool output, or stale state |
| ACK Template Catalog | Select deterministic, truthful slow/patch/clarify text | Claim unsupported task progress |
| Composer Checks | Validate progress truthfulness or commitment coverage | Accept the same model's self-attestation |
| TTS Adapter / Talker | Synthesize approved text and own playback spans/offsets/truncate | Play unapproved PCM or infer semantic confirmation |

### 5.2 Logical roles in one Qwen session

The logical Qwen session, through its current active connection generation,
exposes four logical projections:

1. `duplex_projection`
   - speech start/stop;
   - smart-turn validity;
   - barge-in candidate;
   - semantic-close and directedness hints when available;
   - response cancellation capability.

2. `asr_projection`
   - transcript delta for local UX;
   - final transcript/evidence ref;
   - provider item correlation.

3. `fast_candidate_projection`
   - bounded assistant transcript candidate;
   - bounded provider-native PCM candidate;
   - response/item identity and output timing;
   - no route authority.

4. `composer_projection`
   - consumes a sanitized runtime handoff;
   - produces text-only SpokenPlan candidates in phase one;
   - uses a separate role-profile ID and schema despite sharing the connection.

Provider reuse does not merge permissions. Every projection declares its own
capabilities, prompt-profile ID, output mode, normalization schema, and source
refs.

### 5.3 WebSocket transport and event mapping

Qwen Audio Realtime is one persistent event stream per active provider
generation, not an atomic `run_turn() -> result` RPC. A normal `smart_turn`
voice turn sends many `input_audio_buffer.append` events and receives
independent Session, Duplex, ASR, conversation-item, Response, transcript,
PCM, cleanup, and error events.

The provider-free and real transports implement one contract:

```python
class QwenRealtimeTransport(Protocol):
    async def open(self) -> None: ...
    async def send(self, event: Mapping[str, object]) -> None: ...
    async def recv(self) -> Mapping[str, object]: ...
    async def close(self) -> None: ...
```

Only Session Runtime allocates and advances the local
`provider_session_generation` before physical open/reopen. The Transport never
sees it. The Session Adapter constructs client events, reads server events,
binds them to the current generation, adds monotonic `provider_event_seq`, and
normalizes the stream. `ScriptedFakeQwenWire` must wait for
`session.update` before emitting `session.updated`, accept multiple audio
append events without per-frame acknowledgement, and emit provider-shaped
server events one at a time. It must not emit `route.proposed`,
`RouterDecision`, Gate results, or canonical events.

Provider events map as follows:

| Provider event family | Projection or internal consumer | Canonical boundary |
| --- | --- | --- |
| `session.created`, `session.updated` | Bootstrap/readiness state | Session/capability/provider-context facts only |
| `input_audio_buffer.speech_started` | Duplex speech-start and possible barge-in evidence | Existing speech-start/barge-in chain |
| input transcription `delta`, `completed`, `failed` | ASR assembly by input item/content | Final ASR only after the local commit join |
| ambient transcription `delta`, `completed` | Temporary-ID non-turn observation | No conversation-item binding, committed turn, Route Evidence, Router, Gate, or output |
| `speech_stopped(reason=turn_invalid)` | Retract candidate ingress | Rejected ingress only; no route/output authority |
| `conversation.item.created`, `conversation.item.deleted` | Item inventory and cleanup acknowledgement | Aggregated provider-context/delivery facts |
| `response.created`, output-item/content-part lifecycle | Open and correlate CandidateQuarantine | No user-visible effect |
| assistant transcript `delta`, `done` | Candidate transcript assembler | Complete candidate refs/digest only |
| audio `delta`, `done` | In-memory PCM manifest assembler | Metadata/digest only; never raw PCM |
| `response.done` | Completed/cancelled/failed terminal | Candidate or cleanup terminal; never Gate/playback proof |
| provider error/disconnect | Fail-closed transport/session state | Existing adapter failure/degraded and provider-context events |

Raw provider events are not canonical Event Journal events. Raw provider
payloads, transcripts, PCM, session secrets, and credentials never enter a
shareable trace. The Journal records only normalized refs, digests, enums,
bounded counts, authoritative decisions, and material lifecycle outcomes.

### 5.4 Core invariants

The implementation must preserve:

```text
audible(QwenFastPCM)
  => RouterDecision == FAST_ONLY
  && task_focus == FOREGROUND_CHAT
  && foreground_act == ANSWER
  && route_evidence.risk_class == LOW
  && route_evidence.confidence >= configured_threshold
  && candidate_safety_evidence.decision == SAFE
  && candidate_safety_evidence.confidence >= configured_threshold
  && candidate_policy_checks == PASSED
  && candidate_transcript_digest == release_token.candidate_transcript_digest
  && candidate_pcm_manifest_digest == release_token.candidate_pcm_manifest_digest
  && provider_response_item_correlation == EXACT
  && FastForegroundGate == PASSED
  && provider_session_generation == release_token.provider_session_generation
  && context_snapshot_id == release_token.context_snapshot_id
  && turn/utterance/response/playback_epoch are current
```

```text
spoken(SlowProgress)
  => current task_id/plan_version/task_event_seq
  && source progress event exists
  && ProgressTruthfulnessCheck == PASSED
```

```text
spoken(SlowFinal)
  => source SemanticCommitment is current
  && CommitmentCoverageCheck == PASSED
```

```text
RouteEvidenceOutput
  != RouterDecision
  != UserPatchInterpretation
  != ConfirmationDecision
```

```text
QwenProviderContext
  != EventJournal
  != TaskState
  != authoritative Memory
```

## 6. Context and Session Memory

### 6.1 Authoritative sources

The Context Assembler reads only:

- per-session Event Journal;
- current InteractionState reducer output;
- current TaskFocusState reducer output;
- current SlowTask reducer output;
- committed local conversation items;
- an in-memory Session Memory store;
- versioned persona and response-style configuration.

The Qwen provider history is a cache/projection. It is never read back as the
sole source of current task state, confirmation, plan version, or memory.

### 6.2 Memory layers

Phase one supports:

1. `TurnMemory`
   - current audio/turn/utterance IDs;
   - ASR evidence;
   - current provider response and playback epoch;
   - expires when the turn is terminal.

2. `TaskMemory`
   - current single active task;
   - lifecycle state;
   - plan version and task event sequence;
   - goal summary, missing slots, confirmation state, and latest progress;
   - expires or becomes terminal summary when the task ends.

3. `SessionMemory`
   - committed recent dialogue;
   - a bounded local conversation summary;
   - session-local style hints and preferences;
   - discarded when the Connect session ends.

There is no durable user-memory store in this phase.

### 6.3 ContextSnapshotV1

Every model request uses an immutable versioned snapshot:

```text
ContextSnapshotV1
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

Any authoritative task or confirmation change after snapshot construction
invalidates a request whose result could mutate task state or authorize
playback. A result may not silently rebind to a newer snapshot.

### 6.4 Bounded projections

Default Router projection limits:

- current transcript: 2,000 Unicode characters;
- at most four recent committed user/assistant items;
- recent-dialogue summaries: 2,000 characters total;
- active-task public summary: 1,000 characters;
- at most five session-memory hints, 1,000 characters total;
- total serialized request: 8,192 characters;
- no raw provider prompt, PCM, credentials, raw web content, or raw tool body.

Default Qwen session settings:

- `max_history_turns=10`;
- one current task projection item at most;
- one ephemeral runtime-handoff item at most;
- committed user/assistant conversation items only;
- local session summary capped at 2,000 characters;
- no cross-session rehydration.

Limits are versioned policy values and may be tuned only through evaluation.

## 7. Router Design

### 7.1 Naming and authority

The small text model is named `Route Evidence Adapter`, not `Router`.

It is a stateless model adapter. It may use HTTP or another provider-supported
transport; it does not require its own conversational WebSocket. Provider/model
selection is an implementation choice governed by capability and evaluation
gates, not an architectural dependency.

### 7.2 RouteEvidenceRequestV1

```text
RouteEvidenceRequestV1
  adapter_request_id
  turn_id
  utterance_id
  final_asr_event_id
  transcript_ref
  asr_confidence optional
  duplex_hints_ref optional
  qwen_semantic_hints_ref optional
  context_snapshot_id
  active_task_public_snapshot optional
  last_assistant_act
  expected_user_response optional
  policy_version
```

The `classify_route` operation does not receive:

- Qwen's candidate answer text;
- raw PCM;
- raw SlowTask internal reasoning;
- tool credentials or authorization state beyond a bounded public enum;
- full conversation history;
- durable memory.

### 7.3 RouteEvidenceOutputV1

```text
RouteEvidenceOutputV1
  route_hint:
    FAST_ONLY | SPAWN_SLOW_TASK | PATCH_ACTIVE_SLOW_TASK | IGNORE
  task_focus_hint:
    ACTIVE_TASK_PATCH
    | FOREGROUND_CHAT
    | NEW_TASK_CANDIDATE
    | CANCEL_OR_PAUSE_CANDIDATE
    | NON_ASSISTANT
    | AMBIGUOUS
  foreground_act_hint:
    ANSWER | ACK_SLOW | ACK_PATCH | SILENCE | CLARIFY
  ack_kind:
    CHAT
    | SEARCH_ACCEPTED
    | COMPARE_ACCEPTED
    | PLAN_ACCEPTED
    | PATCH_RECEIVED
    | CLARIFY_NEEDED
    | WAITING_CONFIRMATION
    | SILENCE
  risk_class: LOW | MEDIUM | HIGH | UNKNOWN
  risk_tags
  evidence_uncertainty: LOW | MEDIUM | HIGH
  confidence
  schema_version
  output_mode
```

Unknown fields, invalid enums, malformed JSON, oversized output, timeout, or
confidence outside `[0,1]` fail validation and never become a RouterDecision.

### 7.4 CandidateSafetyEvidenceV1

The same small-text adapter exposes a separate stateless
`classify_candidate_safety` operation. It receives the completed candidate
transcript, not PCM, and is independently prompted and evaluated from Qwen:

```text
CandidateSafetyEvidenceRequestV1
  adapter_request_id
  turn_id
  utterance_id
  qwen_response_id
  candidate_ref
  candidate_transcript_digest
  context_snapshot_id
  route_evidence_event_id optional
  task_focus_state_ref
  active_task_public_snapshot optional
  policy_version
```

```text
CandidateSafetyEvidenceOutputV1
  decision: SAFE | UNSAFE | UNCERTAIN
  semantic_categories
  prohibited_claims_detected
  external_freshness_required
  active_task_fact_detected
  tool_or_execution_claim_detected
  confirmation_or_control_claim_detected
  high_risk_domain_detected
  confidence
  schema_version
  output_mode
```

This operation may begin after the correlated complete assistant transcript
event, while provider PCM is still accumulating. It must finish before the
Gate. It never sees raw PCM, raw tool bodies, private SlowTask reasoning, or
credentials.

`SAFE` is non-authoritative evidence. Invalid schema, timeout, `UNCERTAIN`,
confidence below threshold, or any prohibited flag forces Gate failure.

### 7.5 CandidateAudioShadowVerificationV1

The existing ASR Adapter boundary adds an independent
`shadow_verify_candidate_audio` operation:

```text
CandidateAudioShadowVerificationV1
  adapter_request_id
  turn_id
  utterance_id
  qwen_response_id
  candidate_transcript_digest
  candidate_pcm_manifest_digest
  audio_format_ref
  decoded_duration_ms
  independent_transcript_ref
  normalized_transcript_digest
  exact_numbers_entities_units_match
  equivalence: MATCH | MISMATCH | UNCERTAIN
  output_mode
```

Before native PCM promotion, every qualification sample must complete this
operation with playback disabled. During phase-one live qualification, every
released native-PCM turn is verified asynchronously in shadow. The result does
not delay or authorize that turn.

PCM is passed by an in-memory ref and is destroyed after playback/discard plus
shadow-verification completion or timeout. The verification event stores
digests and bounded refs only. Qwen cannot serve as its own audio verifier.

A live shadow `MISMATCH`, digest disagreement, or `UNCERTAIN` result is a
critical capability violation: disable provider-native PCM for all subsequent
turns in the Connect session, taint/rebuild provider context, and fall back to
approved text plus TTS/template output. It cannot retract audio already played.

### 7.6 Commit boundary and parallel execution

Provider `smart_turn` may begin generating a Qwen response before the local
control plane has completed turn commit. That activity is provider-local
speculation only:

- it remains inside CandidateQuarantine;
- it cannot emit a consumable foreground candidate or Fast Interaction output;
- it cannot start route or candidate-safety classification;
- it is cancelled and deleted if Interaction Controller rejects or holds the
  turn.

At `response.created`, Quarantine binds only response-level provider
generation/response/candidate/epoch state plus optional provisional ingress or
input-item refs. It binds canonical `turn_id`, `utterance_id`, and the
fast-candidate `context_snapshot_id` exactly once only after
`TURN_INGRESS_COMMITTED`. Ambient, invalid, held, or rejected ingress never
receives these authoritative bindings.

The provider stream is not one total order. The implementation may require only
these causal partial orders:

```text
speech_started < speech_stopped|turn_invalid
ASR delta* < ASR completed|failed
response.created < response output events < response.done
ambient delta* < ambient completed
```

It must not require `ASR completed < response.created`; assistant transcript
and PCM deltas may interleave. Assistant `conversation.item.created` and
`response.output_item.added` may also arrive in either order; their item IDs
must join before candidate eligibility.

Canonical final ASR is a local join:

```text
ASR_TRANSCRIPT_OUTPUT_EMITTED
  requires:
    TURN_INGRESS_COMMITTED
    and normalized provider transcription.completed
```

If provider ASR final arrives first, the Session Adapter holds it until local
commit. If local commit arrives first, it waits for the correlated provider
final. Qwen Response events may already be entering CandidateQuarantine during
either wait.

After the join:

1. The Route Evidence request starts immediately from final ASR plus its
   bounded context projection.
2. Qwen's automatically generated assistant response continues into
   quarantine without waiting for Route Evidence.
3. The route call does not wait for the Qwen candidate to complete.
4. Candidate-safety classification begins only after the complete correlated
   candidate transcript is available.
5. The Fast Interaction Orchestrator joins only events bound to the same
   committed turn, context snapshot, and provider generation.
6. The local Router runs when valid route evidence is available or the route
   deadline expires.
7. Default route-evidence P95 target is 300 ms from final ASR.
8. Default hard route deadline is 700 ms from final ASR.
9. Deadline, timeout, or invalid output uses a controlled
   clarification/ignore policy and discards the Qwen candidate.

The two small-text operations are adjudication, not answer generation. Route
classification remains parallel with Qwen generation; candidate-safety
classification occupies only the post-transcript tail and may overlap remaining
PCM generation. Audio shadow verification starts after complete PCM but never
blocks the current turn's Gate or playback.

Ambient `delta`/`completed` uses a standalone temporary item ID that never binds
to a conversation item, local turn, or active input item. It never emits
`TURN_INGRESS_COMMITTED`. A
`speech_stopped(reason=turn_invalid)` retracts the candidate ingress and emits
no Route Evidence, Router, Gate, or output authority chain. Any provider
assistant output observed for ambient, invalid, rejected, or held ingress
remains quarantined and must be cancelled/deleted; unproven cleanup taints and
rebuilds provider context. If a provisional speech-start already stopped local
playback, a later invalid-turn result never resumes the old playback.

## 8. Qwen Fast Candidate and Audio Gate

### 8.1 Candidate scope

Phase-one Qwen native-audio release is limited to complete, short, low-risk
answers in these categories:

- casual conversation;
- basic arithmetic;
- short definitions and explanations not requiring current external facts;
- one-sentence translation or rephrasing of user-provided text;
- low-risk local conversational response outside an active task.

The following are not eligible:

- current weather, prices, news, schedules, or other fresh external facts;
- medical, legal, financial, or safety-critical guidance;
- tool status or claims of execution;
- active-task facts, confirmation, cancellation, or task switching;
- complex planning or multi-step work;
- webSearch/RAG/tool-result claims;
- ambiguous references or unresolved key fields.

### 8.2 Candidate completeness

Phase one does not stream unapproved audio to the user.

- Qwen is instructed to keep eligible fast replies to one short sentence.
- Candidate transcript limit: 80 Unicode scalar values.
- Candidate decoded-audio duration limit: 2,000 ms.
- Candidate must reach a correlated terminal `response.done(status=completed)`.
- Candidate PCM and transcript must be complete and mutually correlated before
  the Gate can release them.
- Candidate must contain exactly one assistant `message` output item and one
  `audio` content part. `function_call`, extra output/content, or mismatch
  among assistant `conversation.item.created`, output/content lifecycle,
  delta/done events, and `response.done.output[]` fails closed.
- Quarantine computes an immutable normalized-transcript digest and an ordered
  PCM-manifest digest covering chunk order, byte length, audio format, sample
  rate, channel count, and decoded duration.
- Every PCM delta accepted by the single receive Pump must bind to the same
  exact provider session generation, response ID, output item ID, output index,
  and content index as the completed transcript. Every accepted provider event
  must carry a non-empty, generation-unique event ID; local manifest sequence
  records observed order.
  Duplicate event IDs, deltas after terminal, cross-lifecycle or
  cross-identity deltas, missing required terminals, and late-generation data
  make the candidate ineligible. Without a provider chunk ordinal or
  end-to-end checksum, the Adapter does not claim detection of an arbitrary
  omitted or permuted intermediate delta.
- The promoted model/profile/correlation implementation must already have
  passed Section 18.3 audio-equivalence qualification.
- Prefix-only or partial candidates are never eligible.
- Streaming prefix release is deferred to a future ADR.

The first-audible SLO must be met through provider speed and parallel Router
execution, not by relaxing gate-before-leak.

### 8.3 Candidate quarantine

The existing bounded defaults remain the initial policy:

- 32 text deltas;
- 8,192 text characters;
- 96 audio chunks;
- 768,000 PCM bytes.

PCM remains memory-only. Overflow, missing transcript/audio correlation, wrong
response identity, late epoch, or terminal mismatch discards the candidate and
marks the path degraded.

### 8.4 Deterministic candidate checks inside the Gate

Candidate policy is not a new authority or state machine. It is a versioned set
of deterministic checks executed inside the existing Fast Foreground Gate:

- current turn, utterance, ASR, response, and playback epoch;
- valid Route Evidence schema;
- valid Candidate Safety Evidence schema;
- exact provider generation, response ID, output item ID, output index, and
  content index correlation plus matching immutable transcript/PCM-manifest
  digests;
- currently promoted native-PCM capability with no shadow mismatch;
- `risk_class=LOW` and confidence at or above the versioned threshold;
- candidate-safety `decision=SAFE`, no prohibited flags, and confidence at or
  above the versioned threshold;
- eligible route/focus/act combination;
- low-risk domain allowlist;
- candidate length and completion;
- prohibited tool, confirmation, task-state, external-current, and high-risk
  categories;
- adapter/capability health;
- no active stale task or confirmation mismatch;
- no quarantine overflow or tainted provider context.

Qwen prompt compliance or either model's self-label cannot by itself pass the
Gate. Gate pass records the candidate-check policy version and every check
result in the existing Gate event.

### 8.5 Release and discard

`FAST_ONLY + FOREGROUND_CHAT + ANSWER`:

- Gate may pass only when every deterministic check passes;
- create one immutable `ForegroundReleaseTokenV1`;
- commit one foreground output through the serialized boundary below;
- enqueue buffered PCM with the original release token;
- let Talker validate the token immediately before starting playback;
- retain the Qwen assistant item provisionally until delivery reconciliation.

`SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`, ambiguity, or failure:

- permanently discard candidate text/PCM;
- request provider response cancellation if still active;
- delete uncommitted provider assistant output items;
- require delete acknowledgement;
- taint and rebuild the Qwen session if cleanup cannot be proven.

The committed user input remains in local conversation history.

### 8.6 Serialized compare-and-authorize boundary

`ForegroundReleaseTokenV1` binds:

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

One per-session serialized append boundary:

1. re-reads current reducer state;
2. compares every token field with current state and recorded evidence;
3. appends Gate pass and `FOREGROUND_OUTPUT_COMMITTED` with the same release
   token;
4. inserts a local playback-outbox entry carrying that unchanged token before
   leaving the serialized event-loop critical section.

There is no network await, model call, clock read, or token re-stamping between
the final comparison, journal append, and local outbox insertion. Browser
delivery occurs later, but Talker performs the same
generation/turn/response/playback-epoch comparison before emitting
`PLAYBACK_SPAN_STARTED` or writing the first PCM byte. A mismatch retires the
outbox item, records a `RESPONSE_ARBITRATION_DECIDED` cancellation plus the
applicable interrupt/degraded event, and emits no playback event. An
`audio_pending` foreground commit is an authorization record, not evidence of
hearing. Thus a barge-in, rebuild, or new turn between authorization and
playback cannot make old PCM audible.

## 9. Dynamic Safe ACKs

### 9.1 Template selection

ACK text is owned by a versioned local template catalog:

```text
template_id = select(
  route,
  task_focus,
  ack_kind,
  response_style,
  mutation_outcome,
  policy_version,
  turn_id
)
```

Selection is deterministic. Replay must select the same template ID without
randomness or a model call.

### 9.2 Permitted variation

Templates may vary by:

- search, compare, planning, or general task acceptance;
- patch received versus clarification required;
- concise, warm, or formal response style;
- whether a task mutation has actually succeeded.

Templates do not interpolate raw user text, dates, amounts, names, locations,
or unresolved slots in phase one.

### 9.3 Truthful ordering

`ACK_SLOW` and `ACK_PATCH` are postconditions:

- `ACK_SLOW` may commit only after the canonical SlowTask spawn chain succeeds.
- `ACK_PATCH` may commit only after the UserPatch mutation/interpretation path
  reaches its defined successful acknowledgement boundary.
- partial or failed mutation uses clarification/degraded text, never a success
  ACK.

Immediate ACKs are `STYLE_ONLY_ACK`. Phrases such as "正在查询" require an
actual current-plan progress event and a passed ProgressTruthfulnessCheck.

### 9.4 Audio

Dynamic ACK text uses the existing approved TTS Adapter and Talker path.
Pre-generated variants are allowed only when they are versioned, mapped
one-to-one to template IDs, and expose normal playback/truncate metadata.

## 10. Slow-to-Fast Handoff

### 10.1 Handoff sources

Allowed handoff sources are:

- canonical SlowTask progress events;
- `CLARIFICATION_REQUESTED`;
- `CONFIRMATION_REQUIRED` and authoritative confirmation outcomes;
- current `SEMANTIC_COMMITMENT_EMITTED`;
- current degraded/failed task states.

Raw Slow LLM text is not a handoff source.

### 10.2 SlowToFastHandoffV1

```text
SlowToFastHandoffV1
  handoff_id
  kind:
    PROGRESS | CLARIFICATION | CONFIRMATION | FINAL | DEGRADED | FAILED
  delivery_mode:
    CONTEXT_ONLY | SPEAK_WHEN_IDLE
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

Every handoff is validated against current reducer state immediately before
provider injection. Stale, terminal-incompatible, superseded, expired, or
unbound handoffs are discarded with metadata-only evidence.

### 10.3 Context injection

For Qwen Audio Realtime:

1. Build a sanitized `composer_projection` from the handoff.
2. Insert one ephemeral `system/input_text` conversation item carrying the
   versioned `RUNTIME_HANDOFF_V1` envelope and Composer role-profile ID.
3. Use `response.create` with `modalities=["text"]` while the session is idle.
4. Capture the complete text output as a SpokenPlan candidate.
5. Run ProgressTruthfulnessCheck or CommitmentCoverageCheck.
6. On pass, synthesize through the existing TTS Adapter and Talker.
7. On failure, retry once with the same immutable facts or use a deterministic
   fallback template.
8. Delete the ephemeral runtime-handoff item and require acknowledgement.
9. Delete the generated Composer assistant item after the approved text is
   captured. If later delivery reconciliation marks playback `FULL`, create a
   committed assistant history item from the approved SpokenPlan; otherwise do
   not inject the full text as delivered history.

If provider item cleanup cannot be proven, rebuild the Qwen session from local
committed conversation and current context projections.

### 10.4 Delivery arbitration

One per-session Response Arbiter enforces:

1. User speech/interrupt has highest priority.
2. A user-turn fast response outranks queued progress.
3. Confirmation/clarification outranks ordinary progress.
4. Final result outranks stale or repetitive progress.
5. Only one provider response may be active.
6. `SPEAK_WHEN_IDLE` waits while the user is speaking or another response is
   active.
7. Repeated progress of the same type is coalesced to the newest current-plan
   handoff.
8. Progress cadence remains 5-10 seconds after first grounded feedback.

New user speech interrupts the current provider Response and local playback,
then invalidates any not-yet-committed handoff response. The provider session
generation/WebSocket remains active unless cleanup policy separately triggers
a rebuild. Provider ingress resumes only after the Section 11.5
context-readiness barrier returns to `CLEAN`.

## 11. Provider Context Lifecycle

### 11.1 Bootstrap

On Connect:

- create one logical Qwen session and provider generation;
- establish one active Qwen WebSocket and start exactly one receive Pump;
- wait for `session.created`, then send one serialized `session.update` with
  audio/text capability, voice, `smart_turn`, `max_history_turns=10`, and the
  versioned global role contract;
- treat `session.created` as provider defaults rather than final configuration;
- require every allowlisted server event to carry a non-empty,
  generation-unique `event_id`;
- require `session.updated` to preserve `session.created.session.id` and reflect
  the requested turn mode, modalities, voice, input-transcription, tool, and
  role/profile configuration before accepting microphone frames;
- keep provider context non-`CLEAN` on missing/duplicate event ID,
  session/configuration mismatch, or update error;
- inject current session summary only if this is a transport rebuild inside the
  same Connect session;
- inject current active-task public snapshot when one exists.

### 11.2 Persistent provider items

Provider history may retain only:

- committed user turns;
- assistant turns whose delivery status is `FULL`;
- bounded interruption markers for `TRUNCATED` assistant turns;
- one current active-task public projection;
- bounded session summary items.

### 11.3 Ephemeral provider items

The following must be deleted after use:

- runtime handoff instructions;
- discarded Qwen assistant candidates;
- superseded active-task projections;
- failed Composer attempts;
- diagnostic/control items.

Deletion requires provider acknowledgement. Missing confirmation taints the
provider context.

### 11.4 Rebuild

Rebuild:

- has Session Runtime advance provider generation and the serialized control
  authority ask Interaction Controller to advance playback epoch before
  awaiting network work; the Adapter only binds/validates them;
- drops old queued PCM and never replays microphone frames;
- rejects old-generation provider events;
- reconstructs only locally committed dialogue, session summary, and current
  active-task projection;
- preserves the browser Connect session and local Event Journal;
- does not restore anything after the Connect session ends.

### 11.5 Provider context readiness barrier

The adapter exposes one authoritative ingress-readiness enum to the local
runtime:

```text
provider_context_state:
  CLEAN
  | CLEANUP_PENDING
  | TAINTED
  | REBUILDING
  | CLOSED
```

Only `CLEAN` may accept microphone frames that can become a committed provider
turn. While any deletion acknowledgement is pending, the state is
`CLEANUP_PENDING`. Missing/invalid acknowledgement advances it to `TAINTED`,
then `REBUILDING`.

During `CLEANUP_PENDING`, `TAINTED`, or `REBUILDING`:

- microphone frames are dropped at the provider ingress boundary;
- dropped frames are counted with bounded/coalesced metadata;
- frames are never queued or replayed;
- Interaction Controller cannot commit a new provider-backed turn;
- the UI exposes one bounded recovering/listen-paused state;
- after `CLEAN`, the user must start or repeat a fresh utterance.

Provider auto-generation observed outside `CLEAN` is quarantined, cancelled,
and cannot create control-plane events. This barrier favors losing a recovery
window utterance over allowing a new turn to consume contaminated context.

## 12. Interrupt and Playback

Qwen provider cancellation and local playback truncation are distinct.

When user speech is accepted as a barge-in candidate:

1. Duplex emits candidate evidence with playback reference.
2. Interaction Controller emits the canonical interrupt/truncate request.
3. Interaction Controller advances playback epoch through the per-session
   serialized control boundary.
4. Browser/Talker clears the current PCM queue.
5. The Session Adapter accepts provider automatic interruption
   (`response.done(status=cancelled,
   status_details.reason=turn_detected)`) or sends
   `response.cancel` only while the same response remains active and no
   auto-cancel terminal has been observed.
6. Successful explicit cancellation ends with
   `status_details.reason=client_cancelled`. Automatic and explicit
   cancellation converge to one response terminal. If automatic cancellation
   wins, a later explicit cancel may return a non-terminal
   `invalid_request_error`; it cannot advance a second authority chain.
7. Late old-epoch PCM is discarded, and cross-response/content/generation
   deltas fail correlation.
8. Talker reports actual stop offset through `TTS_TRUNCATED`.
9. The new input remains under normal Interaction Controller ingress policy.

Provider `response.done(status=cancelled)` is cleanup evidence, not proof that
the local player already stopped.

Phase-one real-device acceptance requires playback-reference echo/AEC evidence
or must be explicitly labeled degraded/mock.

### 12.1 Delivery-aware history reconciliation

Local and provider conversation projections distinguish:

```text
assistant_delivery_status:
  PENDING | FULL | TRUNCATED | NOT_STARTED
```

An assistant item is not `FULL` merely because Qwen generation,
`FOREGROUND_OUTPUT_COMMITTED`, or TTS synthesis completed. `FULL` requires
`PLAYBACK_FINISHED` and a final `PLAYBACK_COMMITTED` offset covering the
authorized audio span.

Every `PENDING` item must terminate:

- for native fast PCM, `PLAYBACK_SPAN_STARTED` must occur within 1,000 ms of
  `FOREGROUND_OUTPUT_COMMITTED(audio_pending)`;
- epoch mismatch, rebuild, user interruption before start, queue failure, or
  start-deadline expiry produces `NOT_STARTED`;
- `NOT_STARTED` deletes the provider assistant item, requires deletion
  acknowledgement, emits `ASSISTANT_DELIVERY_DISPOSITIONED`, and retains no
  assistant text in local/provider delivered history;
- deletion failure taints and rebuilds provider context;
- after playback starts, normal completion produces `FULL`, and interruption or
  delivery failure produces `TRUNCATED`.

On `TTS_TRUNCATED`:

1. local history records the actual stop offset and `TRUNCATED`;
2. the full provider assistant item is deleted;
3. without verified audio-to-text alignment, no textual prefix is claimed as
   fully delivered;
4. a bounded `ASSISTANT_DELIVERY_TRUNCATED_V1` system projection may state only
   that the response was interrupted and its delivery status/offset;
5. with independently verified word-level alignment, a delivered-prefix ref may
   be included, but never text after the actual stop offset;
6. deletion or replacement-creation failure taints and rebuilds provider
   context.

If playback fails after start without a trustworthy stop offset, status is
`TRUNCATED` with `delivery_offset_status=UNKNOWN`; no delivered text prefix is
retained and provider context is rebuilt.

The same rule applies to native fast PCM and SlowTask-derived TTS. Subsequent
Qwen, Router, and SlowTask projections cannot treat undelivered suffixes as
shared conversational facts.

## 13. Event Journal Amendments

ADR-002 carries the following accepted additions and existing-schema
amendments.

### 13.1 ROUTE_EVIDENCE_OUTPUT_EMITTED

Required fields:

```text
adapter_id
adapter_type=route_evidence
adapter_request_id
turn_id
utterance_id
final_asr_event_id
context_projection_event_id
route_hint
task_focus_hint
foreground_act_hint
ack_kind
risk_class
risk_tags
evidence_uncertainty
confidence
schema_name
normalization_status
output_mode
```

The event is non-authoritative and must causally precede the local
`ROUTER_DECISION_EMITTED` that consumes it.

### 13.2 CANDIDATE_SAFETY_EVIDENCE_OUTPUT_EMITTED

Required fields:

```text
adapter_id
adapter_type=route_evidence
adapter_request_id
turn_id
utterance_id
qwen_response_id
candidate_transcript_digest
context_projection_event_id
decision=SAFE|UNSAFE|UNCERTAIN
semantic_categories
prohibited_flags
confidence
schema_name
normalization_status
output_mode
```

This is independently generated evidence, not Gate authority. It must bind to
the exact candidate transcript digest later recorded by
`FOREGROUND_REPLY_CANDIDATE_EMITTED`.

### 13.3 MODEL_CONTEXT_PROJECTION_EMITTED

Required fields:

```text
projection_id
target_role=route_evidence|candidate_safety|fast_candidate|composer
source_event_ids
context_snapshot_id
source_event_seq
provider_session_generation
active_task_ref optional
plan_version optional
task_event_seq optional
pending_confirmation_ref optional
projection_ref
policy_version
redaction_status
output_mode
```

The event records refs and bounded metadata, not raw prompts, PCM, secrets, or
unredacted provider bodies.

### 13.4 SLOW_TO_FAST_HANDOFF_EMITTED

Required fields:

```text
handoff_id
kind
delivery_mode
task_id
plan_version
task_event_seq
source_event_ids
facts_ref
must_say_fields_ref
forbidden_claims_ref
priority
expiry_status
redaction_status
```

The event records a validated current-plan handoff candidate. It never contains
raw Slow LLM reasoning or raw tool output.

### 13.5 SLOW_TO_FAST_HANDOFF_DISPOSITIONED

Required fields:

```text
handoff_id
disposition=QUEUED|COALESCED|SELECTED|STALE|EXPIRED|CANCELLED|DISCARDED
response_arbitration_event_id optional
replacement_handoff_id optional
current_task_id optional
current_plan_version optional
current_task_event_seq optional
reason
```

Every handoff reaches at least one recorded disposition, and only `SELECTED`
may causally produce a Composer context projection.

### 13.6 RESPONSE_ARBITRATION_DECIDED

Required fields:

```text
arbitration_id
selected_source_type=user_fast|confirmation|clarification|progress|final|none
selected_source_event_id optional
superseded_source_event_ids
provider_session_generation
playback_epoch
interaction_state_version
decision_reason
```

This records only decisions that select, coalesce, supersede, or cancel
user-facing delivery. It does not duplicate every in-memory queue operation.

### 13.7 PROVIDER_CONTEXT_STATE_CHANGED

Required fields:

```text
adapter_id
provider_session_generation
from_state=CLEAN|CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED
to_state=CLEAN|CLEANUP_PENDING|TAINTED|REBUILDING|CLOSED
reason
source_event_ids
cleanup_item_count optional
delete_ack_count optional
cleanup_outcome optional
dropped_audio_frame_count optional
output_mode
```

Repeated recovery-period frame drops are coalesced into bounded counts; raw
audio and provider payloads are never recorded.

### 13.8 CANDIDATE_AUDIO_SHADOW_VERIFICATION_EMITTED

Required fields:

```text
adapter_id
adapter_type=asr
adapter_request_id
turn_id
utterance_id
qwen_response_id
candidate_transcript_digest
candidate_pcm_manifest_digest
audio_format_ref
decoded_duration_ms
independent_transcript_ref
normalized_transcript_digest
exact_numbers_entities_units_match
equivalence=MATCH|MISMATCH|UNCERTAIN
output_mode
```

The event contains no PCM and is never a per-turn Gate prerequisite. Only
qualification samples with `MATCH` count toward promotion. A live shadow
non-match triggers capability disable/degrade for subsequent turns.

### 13.9 ASSISTANT_DELIVERY_DISPOSITIONED

Required fields:

```text
assistant_item_ref
source_output_event_id
release_token_ref optional
playback_span_id optional
from_status=PENDING
to_status=FULL|TRUNCATED|NOT_STARTED
actual_stop_offset_ms optional
delivery_offset_status=KNOWN|UNKNOWN|NOT_APPLICABLE
provider_item_cleanup_status=NOT_REQUIRED|ACKNOWLEDGED|TAINTED
source_event_ids
```

Every provisional assistant item has exactly one terminal delivery disposition.
`FULL` must reference playback finish/commit; `TRUNCATED` must reference truncate
or delivery failure; `NOT_STARTED` must reference the start-deadline,
arbitration, epoch, or queue failure.

### 13.10 Existing event schema amendments

The design continues to use:

- `FAST_INTERACTION_OUTPUT_EMITTED`;
- `FOREGROUND_REPLY_CANDIDATE_EMITTED`;
- `ROUTER_DECISION_EMITTED`;
- foreground Gate pass/fail;
- foreground commit/discard;
- SlowTask/UserPatch/progress/SemanticCommitment events;
- SpokenPlan and truthfulness/coverage checks;
- TTS synthesis and playback/truncate events.

For the parallel topology:

- provider-backed `ASR_TRANSCRIPT_OUTPUT_EMITTED` carries
  `provider_session_generation`, opaque `qwen_input_item_ref`, and
  `qwen_input_content_index`, and remains causally after both local turn commit
  and the correlated provider transcription final;
- `FAST_INTERACTION_OUTPUT_EMITTED` is owned by the local Fast Interaction
  Orchestrator, not either model adapter;
- its schema includes separate Qwen candidate adapter/request provenance, route
  evidence event/request provenance, candidate-safety event/request provenance,
  optional candidate-audio shadow-verification provenance, context snapshot,
  provider generation, and normalization status;
- `FOREGROUND_REPLY_CANDIDATE_EMITTED` remains caused by that composite event
  and carries `qwen_response_id`, `qwen_output_item_id`,
  `qwen_output_index`, `qwen_content_index`, separate
  transcript/PCM-manifest digests, audio format/duration, and optional
  candidate-audio shadow-verification event; its transcript digest must match
  the candidate-safety event;
- Gate pass/fail includes the candidate-check policy version, individual
  deterministic check results, provider generation, context snapshot, and
  immutable release token ref;
- `FOREGROUND_OUTPUT_COMMITTED` includes the same release token ref and
  `user_visible_channel=audio_pending`;
- playback events include the release token ref for provider-native PCM;
- `TTS_TRUNCATED` causally triggers delivery-aware history reconciliation and,
  when required, provider context state changes.

The composite event preserves separate provenance and never pretends that route
evidence and the candidate came from one provider call.

## 14. Adapter Capability Amendments

ADR-011 carries `route_evidence` as an accepted adapter type with:

- `supports_route_schema`;
- `supports_task_focus`;
- `supports_foreground_act_hint`;
- `supports_ack_kind`;
- `supports_risk_tags`;
- `supports_candidate_safety_schema`;
- `supports_prohibited_claim_detection`;
- `supports_confidence`;
- `supports_strict_json_validation`;
- expected P50/P95 route latency;
- timeout and retry policy.

The ASR Adapter capability matrix carries:

- `supports_candidate_output_audio_shadow_verification`;
- supported PCM formats/rates/channels;
- expected verification P50/P95 latency;
- normalization/equivalence policy version;
- real/mock/fallback/degraded verification status.

The Qwen Realtime role capabilities must independently declare:

- smart-turn speech/semantic boundary support;
- streaming ASR support;
- provider response cancellation;
- text/audio response support;
- provider item create/delete and deletion acknowledgement;
- manual response creation while idle;
- one-active-response restriction;
- candidate quarantine;
- provider-native audio release support;
- context rebuild/rehydration;
- typed provider-context readiness;
- fast-role and composer-role prompt-profile IDs;
- real/mock/fallback/degraded verification status.

Protocol documentation, implementation support, provider-free verification,
and real-live verification remain separate capability fields.

## 15. ADR Amendments

### ADR-017

Add two supported topologies:

1. `atomic_single_call`
   - original route evidence + act + reply candidate in one provider call.

2. `speculative_candidate_parallel_route`
   - Qwen creates the candidate;
   - Route Evidence Adapter classifies in parallel;
   - the composite Fast Interaction output preserves separate provenance;
   - final Router/Gate still precede all audible output.

The parallel topology is not the rejected "FAST_ONLY then call FastReply"
alternative because answer generation begins before the Router finishes and
does not require a second answer-model round trip.

### ADR-001 and ADR-003

Clarify:

- provider smart-turn response generation before `TURN_INGRESS_COMMITTED` is
  quarantined speculation and has no control-plane authority;
- Route Evidence and normalized Fast Interaction output occur only after local
  turn commit;
- Gate-to-playback uses an immutable generation/snapshot/epoch-bound release
  token;
- truncated assistant output is reconciled in local and provider history using
  actual playback delivery markers.

### ADR-009

Clarify that same-provider role reuse may share a physical session only when:

- fast and composer role profiles are explicit;
- input projections and source events are distinct;
- slow facts remain immutable;
- phase-one Composer output is text-only before checks and TTS.

### ADR-012

Add a Post-ADR-017 / MVP6.x vertical slice, provisionally named Slice 3B,
without changing the MVP-3 completion definition. Every use of `3B` in this
document is shorthand for Post-ADR-017 / MVP6.x work, not MVP-3.

### ADR-013

Bind Slow-to-Fast progress handoffs and Response Arbiter disposition to the
existing grounded-progress and ProgressTruthfulnessCheck contract. Coalescing
must never synthesize progress that lacks a current source event.

### ADR-015 and AGENTS.md

Add review blockers for:

- treating Route Evidence as Router authority;
- treating provider context as authoritative memory;
- playing provider PCM before Gate/Coverage approval;
- injecting stale/raw/untrusted SlowTask material into Qwen;
- adding cross-session durable memory inside phase one.

## 16. Failure Policy

| Failure | Required behavior |
| --- | --- |
| Route timeout/invalid schema | Discard Qwen candidate; controlled clarification or ignore |
| Candidate-safety timeout/unsafe/uncertain | Gate fails; discard Qwen candidate; route-specific safe fallback |
| Online response/item/content/digest correlation failure | Gate fails; discard PCM/text; taint/rebuild context |
| Qualification audio mismatch/uncertain/timeout | Native-PCM profile is not promoted |
| Live shadow audio mismatch/uncertain/timeout | Record critical violation; disable native PCM for subsequent turns; taint/rebuild and fall back |
| Qwen candidate timeout/missing terminal | No fast answer; controlled clarification or template fallback |
| Quarantine overflow | Discard candidate, mark degraded, clean provider context |
| Route/task snapshot becomes stale | Discard result; never rebind to current task |
| Candidate policy reject | Discard candidate; follow route-specific fallback |
| Provider output cleanup unconfirmed | Taint and rebuild Qwen session |
| User audio during non-CLEAN provider context | Drop/count/coalesce; never replay or commit; request fresh utterance after recovery |
| Slow handoff stale/expired | Metadata-only discard |
| User speaks during handoff generation/playback | Cancel generation, truncate playback, retire handoff response |
| Composer check fails | Retry once, then deterministic safe template |
| TTS lacks truncate | Target barge-in acceptance fails or is explicitly degraded |
| Browser delivery ambiguous | Preserve one semantic output identity; recovery is metadata-only |
| Playback does not start within 1,000 ms of audio-pending commit | Mark `NOT_STARTED`; delete item with acknowledgement or rebuild |
| Journal append failure before mutation | No mutation or success ACK |
| Partial SlowTask mutation | Reconcile from journal; no blind retry and no success ACK |

## 17. Security and Privacy

- No raw PCM is written to the Event Journal, trace, replay fixture, or repo.
- Raw audio remains local opt-in only under existing repository policy.
- API keys, headers, workspace credentials, provider session secrets, and tool
  credentials never enter context projections or traces.
- Raw ReAct reasoning and chain-of-thought are never transferred.
- Raw webSearch/RAG text remains evidence, never a system instruction.
- Context projections prefer refs, bounded summaries, enums, and redacted text.
- Provider item/response IDs remain opaque adapter-local correlation data.
- Shareable fixtures are synthetic, redacted, and minimal.

## 18. Validation Strategy

### 18.1 Document gates

- ADR-018 is accepted before implementation.
- Every new canonical event appears in ADR-002.
- The ADR register matches file statuses and links.
- ADR-001/003/009/013/017/018 agree on turn commit, output approval,
  interruption, progress, and delivery-history order.
- Historical Slice 3A documents remain clearly non-authorizing evidence.

### 18.2 Routing dataset gate

Before prompt/profile promotion:

- complete human review/adjudication of the existing 80 draft routing cases;
- freeze those 80 cases as a locked holdout and use a separate development set
  of at least 80 cases;
- ensure the locked holdout has at least ten cases for each authoritative route
  and at least ten each for active-task patch/control and ambiguity;
- run a real Route Evidence Adapter, not oracle-derived evidence;
- record model/profile/version and context policy;
- require route exact accuracy >=95% and task-focus exact accuracy >=95%;
- require 100% recall for patch, confirmation, cancel/switch, non-assistant, and
  high-risk-to-slow/clarify cases;
- require zero critical violations on the locked holdout;
- report route accuracy, task-focus accuracy, patch misrouting, ambiguity,
  confirmation/control mistakes, and weighted error cost.

A critical routing violation is:

- allowing fast output for a high-risk, tool, confirmation, cancel, switch, or
  current-task-fact turn;
- spawning a task for an active-task patch or mutating the active task for a
  foreground chat/new task without the required confirmation boundary;
- outputting to a `NON_ASSISTANT`/`IGNORE` turn;
- letting invalid/uncertain evidence advance Router authority.

Any corpus edit, prompt/profile change, model change, or context-policy change
invalidates the qualification and requires a fresh locked run.

### 18.3 Candidate-safety and audio-equivalence dataset gate

Before Qwen native PCM can be enabled:

- create a synthetic/redacted development set of at least 200 candidate texts;
- lock a separate holdout of at least 200 texts: at least 100 eligible low-risk
  answers and 100 prohibited answers;
- include at least 20 prohibited examples each for high-risk advice, fresh
  external facts, tool/execution claims, confirmation/control claims, and
  active-task/current-plan facts;
- include adversarial paraphrases, negation, indirect claims, code-switching,
  prompt-injection text, and malformed/oversized outputs;
- require 0 unsafe/prohibited candidates classified `SAFE`;
- require >=90% of eligible candidates classified `SAFE`;
- require 100% schema-valid or explicit fail-closed handling;
- rerun qualification for any candidate prompt, safety prompt/profile, model,
  threshold, allowlist, or context-policy change.

Deterministic lexical/schema checks and independent Candidate Safety Evidence
must both pass. The independent classifier does not replace the Gate.

Candidate-audio qualification additionally requires a locked set of at least
100 synthetic or provider-generated transcript/PCM pairs:

- at least 60 true matches;
- at least 40 mismatches covering substituted numbers/names/negation/units,
  intentionally permuted decoded audio, truncation, extra speech, wrong format,
  and corrupted manifests;
- zero mismatches classified `MATCH`;
- >=95% of true pairs classified `MATCH`;
- during phase-one live qualification, every released native-PCM turn performs
  the same verification asynchronously in shadow, without delaying Gate or
  playback.

### 18.4 Provider-free contract tests

Cover:

- protocol handshake
  `session.created -> session.update -> session.updated`;
- `session.created` defaults versus matching updated session ID/configuration,
  plus mandatory generation-unique server `event_id`;
- multiple `input_audio_buffer.append` events without per-frame
  acknowledgement;
- one serialized sender and one receive Pump per provider generation;
- Fake/Real transport contract conformance through the same Session Adapter;
- ASR-final-before-response and response-before-ASR-final legal schedules;
- interleaved assistant transcript and PCM deltas;
- both orders of assistant `conversation.item.created` and
  `response.output_item.added`, with exact item-ID join;
- ambient and `turn_invalid` with zero committed turn, Route Evidence, Router,
  Gate, or output authority;
- illegal `response.create` while a `smart_turn` turn/response is active;
- one-active-response enforcement;
- provider auto-cancel and explicit-cancel race convergence, including a late
  non-terminal `invalid_request_error`;
- cancelled terminal followed by late output deltas;
- wrong response, output-item, output-index, or content-index identity;
- extra output/content, `function_call`, and `response.done.output[]` mismatch;
- missing response terminal and missing delete acknowledgement;
- old-generation events after rebuild;
- candidate-before-route and route-before-candidate scheduling;
- provider speculation before local turn commit and rejection cleanup;
- one Router/Gate/output terminal per turn;
- all four routes plus ambiguity/clarification;
- active-task side chat, patch, new-task, cancel, and confirmation;
- candidate-safety safe/unsafe/uncertain/timeout/malformed outcomes;
- candidate audio match/mismatch/uncertain/timeout, digest mismatch,
  intentionally permuted decoded audio for the independent equivalence
  verifier, corrupt format, and duration overflow;
- template selection and post-mutation ACK ordering;
- route timeout/schema failure;
- quarantine overflow and late-epoch discard;
- release-token mismatch at every compare-and-authorize field;
- barge-in/rebuild between Gate pass, output commit, queue insertion, and
  playback start;
- stale handoff and plan-version advance;
- progress coalescing and response arbitration;
- provider-context cleanup barrier, frame drop/coalescing, and no replay;
- full/truncated/not-started delivery reconciliation;
- reconnect rehydration and provider-item cleanup failure;
- deterministic replay/state digest.

### 18.5 Real live acceptance

Each of scenarios 1-8 must pass three consecutive real-device repetitions with
zero critical violation:

1. Low-risk definition question:
   - real smart turn and final ASR;
   - real Route Evidence;
   - exact online response/item/content/digest correlation;
   - real independent candidate-audio shadow result eventually matches;
   - Gate pass;
   - zero PCM before Gate;
   - one Qwen native-audio playback after Gate.

2. Complex task:
   - Qwen candidate discarded;
   - SlowTask spawn succeeds;
   - dynamic `ACK_SLOW` follows mutation;
   - zero leaked provider candidate PCM.

3. Active-task patch:
   - patch route and UserPatch binding;
   - candidate discarded;
   - ACK only after successful mutation/interpretation boundary.

4. Ignore and ambiguity:
   - silence or controlled clarification;
   - zero task mutation and candidate leak.

5. Slow progress:
   - current-plan handoff;
   - Qwen text Composer;
   - truthfulness pass;
   - TTS/Talker playback.

6. Slow final:
   - current SemanticCommitment;
   - coverage pass;
   - final playback;
   - key facts unchanged.

7. Barge-in:
   - user speaks during Qwen and SlowTask-derived playback;
   - local truncate and provider cancellation;
   - late PCM dropped;
   - next turn accepted.

8. Transport rebuild:
   - no microphone PCM replay;
   - local committed session context rehydrated;
   - no durable state after a new Connect.

Additionally:

- execute at least ten real barge-in attempts across native fast and
  SlowTask-derived playback, all with a truncate terminal and zero old-epoch
  playback after the measured stop offset;
- complete one session lasting at least 30 minutes and 50 committed turns,
  including at least ten FAST_ONLY, ten SPAWN/PATCH combined, five
  IGNORE/AMBIGUOUS, five progress/final handoffs, and one transport rebuild;
- observe zero provider candidate PCM on every non-fast, unsafe, stale,
  invalid, timeout, or superseded turn;
- verify every released native PCM manifest/digest online and independently
  back-transcribe it in non-blocking shadow;
- observe zero duplicate Router, Gate, SlowTask, UserPatch, or playback terminal
  for one identity;
- verify every slow final with machine comparison of all `must_say_fields`,
  immutable values, confirmation state, risk warnings, and demo/tool status;
- verify every progress utterance has at least one current-plan grounded source
  event and no unsupported progress claim.

Any critical violation fails the run; averages cannot hide it. A provider or
browser crash, timeout, dropped required event, or missing verification record
counts as a failed sample, not an exclusion.

### 18.6 SLOs

Development targets:

- adjudicated acoustic speech onset to `SPEECH_START_DETECTED`: P95 <=150 ms;
- `BARGE_IN_CANDIDATE` to `TTS_TRUNCATE_REQUESTED`: P95 <=250 ms;
- adjudicated acoustic last-speech sample to `SPEECH_END_DETECTED`: P95
  <=900 ms total; a local/server-VAD fallback uses a 500-800 ms silence
  configuration, while `smart_turn` reports observed provider endpointing
  latency because it does not expose that local silence setting;
- `ASR_TRANSCRIPT_OUTPUT_EMITTED` to
  `ROUTE_EVIDENCE_OUTPUT_EMITTED`: P95 <=300 ms;
- Route Evidence hard deadline: 700 ms;
- `TURN_INGRESS_COMMITTED` to first non-zero browser
  `PLAYBACK_COMMITTED` for fast output: P95 <=800 ms;
- `SLOWTASK_CREATED` to first non-zero browser `PLAYBACK_COMMITTED` for a
  grounded progress SpokenPlan: P95 <=2 s;
- consecutive non-zero browser `PLAYBACK_COMMITTED` markers for distinct
  grounded progress SpokenPlans: 5-10 s while work remains active.

All latency uses the per-session Event Journal monotonic clock. Acoustic onset
and last-speech points are human-adjudicated sample offsets mapped to that clock.
Audible output ends at a Talker/browser `PLAYBACK_COMMITTED` delivery marker,
not server send or queue time. P95 requires at least 30 eligible real samples;
timeouts and failed samples remain in the denominator and are also reported
separately.

Complete transcript and PCM buffering, independent candidate-safety evidence,
exact response/item/content/digest correlation, and the 2,000 ms
candidate-audio cap remain on the online critical path. Independent PCM
back-transcription runs outside that latency path; its P50/P95 and outcome are
reported separately. If the <=800 ms fast target is not met under the online
constraints, Slice 3B.4 fails promotion and provider-native PCM remains
disabled. The SLO cannot be recovered by streaming an unapproved prefix.

Results must identify real, mock, fallback, or degraded capability.

## 19. Proposed Delivery Slices

These are Post-ADR-017 / MVP6.x slices. They are not MVP-3 work.

### Slice 3B.0: Governance

- write/accept ADR-018;
- amend ADR-002/009/011/012/015/017;
- update AGENTS.md and register after acceptance;
- add schema fixtures and document consistency checks.

### Slice 3B.1: Provider-free parallel topology

- use the focused design in
  `docs/superpowers/specs/2026-07-26-qwen-slice3b1-protocol-faithful-fake-design.md`;
- implement protocol-faithful `ScriptedFakeQwenWire`, not an aggregate
  `run_turn()` result;
- drive the same serialized Qwen Session Adapter/Pump and exact correlation
  state intended for the real transport;
- require the real handshake shape, multiple audio appends without per-frame
  acknowledgement, and synthetic/redacted deterministic server-event scripts;
- cover normal partial-order permutations, ambient, `turn_invalid`, barge-in,
  late delta, missing terminal, wrong IDs/indexes, delete-ack failure, and
  rebuild-generation scenarios;
- keep the Fake Route Evidence Adapter and Candidate Safety operations
  separate from Qwen;
- add Context Assembler, composite Fast Interaction output,
  CandidateQuarantine, fake audio verifier, digests, release token, templates,
  and deterministic replay/state-digest coverage;
- expose one deterministic provider-free CLI scenario runner whose stable
  result contract can be reused by the later page demo;
- report `output_mode=mock`, perform no network/credential access, and never
  play provider PCM.

### Slice 3B.2: Real Qwen transport and evidence shadow

- replace only `ScriptedFakeQwenWire` with the real Qwen WebSocket transport;
- preserve the same Session Adapter/Pump, normalized projections, correlation,
  quarantine, Router, and Gate boundaries;
- real small text model;
- real independent candidate-audio qualification/shadow adapter;
- no effect on local Router/Gate;
- model-evaluated routing, candidate-safety, and audio-equivalence corpora;
- latency and schema qualification;
- provider-native PCM remains inaudible.

### Slice 3B.3: Enforced route with audio still quarantined

- Route Evidence affects Local Router;
- provider-native PCM remains inaudible;
- verify all route/task mutation/cardinality paths.

### Slice 3B.4: FAST_ONLY native-audio release

- complete bounded candidate;
- independent Candidate Safety Evidence and Gate checks;
- qualified model/profile plus exact online correlation and non-blocking shadow;
- serialized release token;
- Talker playback spans;
- real barge-in/truncate;
- no leakage on non-fast routes.

### Slice 3B.5: Slow-to-Fast Composer bridge

- current-plan handoff;
- Qwen text-only Composer in the same session;
- truthfulness/coverage checks;
- TTS/Talker playback;
- progress/final interruption.

### Slice 3B.6: Human-present phase-one acceptance

- multi-turn route matrix;
- active SlowTask interactions;
- progress/final handoff;
- long-session stability;
- reconnect within Connect;
- SLO and critical-violation report.

No later slice may compensate for an earlier failed safety or replay gate by
silently broadening authority.

## 20. Acceptance Criteria

Phase one is complete only when:

- one Qwen Voice session remains usable across the accepted multi-turn run;
- real smart-turn/ASR/barge-in evidence is demonstrated;
- both real Route Evidence operations are evaluated on their locked,
  human-reviewed/synthetic-redacted corpora and meet Section 18 thresholds;
- Local Router and Gate produce exactly one terminal chain per turn;
- eligible FAST_ONLY turns produce audible Qwen native audio only after the
  qualified model/profile and generation/snapshot/epoch/digest-bound Gate
  release;
- all non-fast/ambiguous/failed turns leak zero Qwen candidate PCM;
- dynamic ACKs are deterministic and truthful;
- active-task patch/confirmation/cancel boundaries remain owned by SlowTask;
- current SlowTask progress/final results can be expressed through the same
  Qwen session's text Composer path and approved TTS/Talker path;
- replay reconstructs route, candidate, Gate, handoff, checks, playback, and
  interrupt state without rerunning a model;
- no raw audio, raw trace, secret, raw ReAct reasoning, or unredacted real user
  input is committed;
- closing Connect removes session memory and a new Connect starts clean;
- provider context is `CLEAN` before accepting a provider-backed turn, and
  recovery frames are never replayed;
- truncated assistant output is not retained as fully delivered context;
- every provisional assistant item terminates as `FULL`, `TRUNCATED`, or
  `NOT_STARTED`, with acknowledged cleanup/rebuild when it was not fully
  delivered;
- all real-live counts and thresholds in Section 18.5 pass;
- phase-one live shadow verification covers every released native-PCM turn with
  zero mismatch/uncertain result;
- all results truthfully identify real/mock/fallback/degraded modes.

## 21. External Protocol Assumptions

This design was checked on 2026-07-25 and protocol-amended on 2026-07-26
against the official Alibaba Cloud
Qwen-Audio Realtime documentation:

- [Qwen-Audio Realtime user guide](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-user-guides)
- [Qwen-Audio Realtime WebSocket API](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime-websocket-api)
- [Qwen-Audio Realtime client events](https://help.aliyun.com/zh/model-studio/fun-audiochat-client-events)
- [Qwen-Audio Realtime server events](https://help.aliyun.com/zh/model-studio/qwen-audio-realtime-server-events)

The provider contract currently documents:

- one Session per active persistent duplex WebSocket with `smart_turn`;
- `session.created -> session.update -> session.updated` bootstrap;
- a mandatory server `event_id` on every event, provider defaults in
  `session.created`, and the full applied configuration in `session.updated`;
- repeated `input_audio_buffer.append` without a per-frame acknowledgement;
- independently streamed speech-start/stop, ASR, response transcript, PCM,
  response lifecycle, item cleanup, and error events on the same connection;
- automatic audio commit and response generation for a normal valid
  `smart_turn` voice turn;
- ambient transcription `delta`/`completed` with a standalone temporary item
  ID, plus `speech_stopped(reason=turn_invalid)` paths that do not trigger a
  normal response;
- assistant `conversation.item.created` at response start, multiple possible
  output items/function calls, and full output inventory in `response.done`;
- `max_history_turns` in the range 1-50;
- `conversation.item.create` for `system`, `user`, and `assistant` text items;
- `conversation.item.delete` with a server deletion acknowledgement;
- manual `response.create` while a `smart_turn` session is waiting for the next
  user turn;
- per-response `modalities=["text"]`;
- automatic interruption on new speech in `server_vad`/`smart_turn`, plus
  explicit `response.cancel`; terminals distinguish
  `status_details.reason=turn_detected|client_cancelled`.

`input_audio_buffer.commit` is not the normal client control point for
`smart_turn`; it belongs to push-to-talk semantics. `response.create` is used
only in protocol-permitted idle/manual/Composer cases. The runtime does not
assume ASR final precedes `response.created`, does not impose a fixed order
between transcript and PCM deltas, and does not infer provider internals from
the fact that these events share one Session.

These are protocol assumptions, not locally proven capabilities. Slice 3B.0
must record documentation support, and Slice 3B.2/3B.4/3B.5 must separately
qualify live behavior for the selected model, region, endpoint, and account.
Any provider contract drift must disable the affected role or mark it degraded;
it must not weaken local authority, Gate, context-cleanup, or replay rules.
