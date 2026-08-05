# MVP6.3 Live Fast Interaction Adapter / Real Fast Answer Design

## Status

Design document only. This document does not implement runtime code, call
providers, read credentials, add provider SDKs, create raw audio artifacts,
persist provider bodies, change accepted ADRs, or change deterministic replay.

MVP6.3 is the first live-provider follow-up to the MVP6.2 provider-free Fast
Foreground skeleton. It keeps ADR-017's core principle:

```text
Train the model to behave this way, but make the runtime guarantee it.
```

This document was corrected after the initial MVP6.3 draft. The first draft made
`ASR transcript -> text Fast Interaction model` the primary live path. That is
not the intended product architecture for the multimodal voice fast foreground.
The corrected MVP6.3 primary path is audio-native:

```text
browser/local audio
-> Live audio-native Fast Interaction adapter
-> Router / Fast Foreground Gate
-> gated real fast answer or deterministic fallback
```

ASR transcript input remains useful as a fallback, degraded mode, replay aid, and
debug comparison path, but it is not the MVP6.3 primary live fast answer path.
MVP6.3 should reduce latency by optimizing the audio-native call path, model
profile, prompt/schema size, streaming behavior, timeout policy, and measurement
surface rather than by replacing the voice-native frontend with a pure text LLM.

## Source Contracts

MVP6.3 is governed by:

- `AGENTS.md`
- `stage_b_adr_register.md`
- ADR-001 Duplex / Interaction Controller
- ADR-002 Event Journal / canonical event registry
- ADR-006 Router Task Focus / single active SlowTask
- ADR-007 UserPatch Evidence Pack
- ADR-008 ASR / Thinker evidence fusion
- ADR-009 SemanticCommitment / Thinker-as-Composer
- ADR-010 Trace / Replay Debug Policy
- ADR-011 Model Adapter Capability Contract
- ADR-012 MVP Vertical Slice and Development SLOs
- ADR-013 Truthful Progress Feedback
- ADR-014 webSearch evidence boundary
- ADR-015 Repository Governance
- ADR-016 SlowTask lifecycle / confirmation state
- ADR-017 Fast Interaction Adapter and Foreground Act Contract
- `docs/implementation/mvp6.2-fast-foreground-design.md`
- `docs/implementation/mvp6-local-debug-console.md`
- `docs/implementation/mvp6-streaming-fast-reply-design-note.md`

ADR-017 already defines the required fast foreground event names. MVP6.3 should
not add new canonical events unless an implementation slice first updates the
accepted ADR registry and derived event specs.

## 1. Current Problem Recap

MVP6.2 makes `FAST_ONLY` replayable and gateable, but it is still provider-free
by design. Its fake Fast Interaction adapter can prove event order, candidate
buffering, gate pass/fail, template fallback, debug console display, and replay
safety. It does not prove that the live system can produce a real fast answer.

The current live recording path still relies on ASR plus audio-native LALM
Thinker evidence. Router waits for the evidence needed to emit `FAST_ONLY`.
When the Thinker path uses the current heavy audio-native profile, provider HTTP
latency can approach or exceed the approval timeout budget, currently around
30000 ms in the local debug approval flow. That means a user can say a simple
foreground request such as "给我讲一个恐怖故事吧", but the UI may only show a
route summary, a placeholder, or a template clarify/ack rather than a real story
candidate.

The fix is not to silently convert the fast foreground into a text-only LLM path.
That would lower the first experiment's latency while moving away from the
voice-native multimodal architecture. MVP6.3 instead creates a live
audio-native Fast Interaction path and instruments the existing Thinker path
well enough to see where the 30s is spent:

- request construction and audio payload preparation;
- provider request send and first token / first chunk wait;
- provider generation / full response receive;
- stream or response decode;
- schema parse and validation;
- event emission and gate-ready time.

Continuing to push this into MVP6.2 would mix two different proof points:

- MVP6.2 proves provider-free ADR-017 control-plane correctness.
- MVP6.3 proves live Fast Interaction adapter behavior and latency.

Keeping them separate preserves the MVP0-MVP6 development pattern: first prove
the deterministic skeleton, then opt into live provider behavior behind an
explicit adapter, approval, timeout, and replay boundary.

## 2. MVP6.3 Scope

MVP6.3 introduces a live audio-native Fast Interaction Adapter that consumes the
current turn audio ref plus safe turn/task metadata and emits, in one model call:

- `route_hint`
- `route_prelude`
- `foreground_act`
- `reply_candidate`
- `final_fast_evidence`
- `confidence`
- `risk_tags`
- `risk_class`
- `output_mode=real|degraded|fallback`

The Fast Interaction output remains evidence and candidate text. Router owns the
final `FAST_ONLY` / `SPAWN_SLOW_TASK` / `PATCH_ACTIVE_SLOW_TASK` / `IGNORE`
decision. Fast Foreground Gate owns final display, discard, template fallback,
or silence policy.

MVP6.3 scope includes:

- A distinct live audio-native Fast Interaction adapter type/profile/schema.
- A fast audio-native profile that may reuse the same provider/model family as
  the current LALM Thinker, but does not reuse the LALM Thinker role contract.
- ASR transcript text/ref as a secondary fallback/degraded/debug input, not the
  primary live fast answer input.
- An explicit `asr_observation_enabled` branch for the local debug console. It
  consumes the same committed turn audio in parallel, emits the existing ASR
  event, and supplies the displayed Question plus local-only QA history. It is
  distinct from `allow_fast_interaction_asr_text_fallback` and never becomes a
  prerequisite or input for the audio-native Fast Interaction call.
- One Fast Interaction model call per turn for route evidence plus foreground
  candidate. No post-Router answer model call.
- Runtime integration behind explicit provider mode and approval gate.
- Debug console display of the real gated candidate when gate passes, otherwise
  deterministic fallback/template/silence.
- QA history metadata for latency, route, gate decision, fallback/discard
  reason, output mode, and safe refs.
- TTFT and latency waterfall metadata for the audio-native Fast Interaction /
  Thinker call path.
- Provider-free tests with fake/injected transports; no network in tests.
- Replay and acceptance coverage using recorded events/refs only.

The target user-visible improvement is that low-risk `FAST_ONLY + ANSWER`
inputs can show real fast answer text in the debug console when the live adapter
is explicitly enabled and the runtime gate passes.

## 3. Non-Goals

MVP6.3 does not implement:

- Real TTS, audio playback, audio-native TTS, or spoken delivery markers.
- A production-grade audio-native model selection benchmark.
- Text-only Fast Interaction as the primary live fast answer path.
- Tool calling, external side effects, payments, bookings, deletions, or
  external communication.
- SlowTask fact mutation by the fast path.
- Fast reply as `SemanticCommitment`.
- A post-Router `FastReplyAdapter`.
- Router-owned complex task reasoning.
- New RouterDecision values.
- Multi active SlowTask, pause/resume, or production privacy policy.
- Deterministic replay that reruns ASR, Thinker, Fast Interaction, Slow LLM,
  TTS, tools, network, clock, random, or env secret reads.
- Committed raw audio, raw prompt, provider request body, provider response
  body, diagnostics, secrets, local replay cache, or unredacted real user input.

If any slice needs one of these, stop and update/create an ADR before
implementation.

## 4. Adapter Design

The live Fast Interaction Adapter is an independent adapter role:

```text
adapter_type = fast_interaction
role_contract = live_fast_interaction_audio_native_v1
prompt_profile = mvp6.3.fast_interaction.audio_native.v1
schema_name = voice_agent.fast_interaction.output.v1
```

It may reuse the existing DashScope OpenAI-compatible transport pattern used by
the LALM Thinker live transport, but only at the transport hygiene layer:

- opaque credential handle;
- safe provider URL ref;
- injected opener/transport in tests;
- audio-capable request construction through the adapter boundary;
- structured JSON response format or structured text envelope parsed by the
  adapter;
- adapter-side schema validation;
- streaming first-chunk / first-token timing when the provider supports it;
- timeout and retry categories converted to ADR-002 adapter events;
- process-local redacted model I/O debug, if enabled.

It must not reuse the LALM Thinker adapter contract as-is. Even if both roles use
the same underlying provider/model family, the Fast Interaction role requires a
separate request builder, prompt profile, output schema, capability declaration,
safe refs, validation errors, and output event chain.

Acceptable implementation shapes:

- dedicated `fast_interaction` adapter backed by an audio-capable multimodal
  model;
- dedicated `fast_interaction` adapter backed by an optimized audio-native
  Thinker profile on the same provider family;
- explicit ASR-text fallback adapter profile used only when the audio-native
  profile is unavailable, timed out, or disabled, and always labeled
  `output_mode=degraded|fallback`.

### Input Contract

First-version input:

- `turn_id`
- `utterance_id`
- `input_modality=audio`
- `audio_span_id`
- `audio_frame_ref` or `audio_payload_ref`
- optional `asr_output_event_id`
- optional `asr_frame_ref`
- optional `text_ref` or redacted transcript text for degraded/debug fallback
- optional short safe conversation/task focus summary
- current active SlowTask summary metadata, if any
- adapter capability snapshot ref

The adapter should prefer refs and metadata. It may read local audio only inside
the approved live adapter boundary and must not store or export raw audio, local
wav paths, provider bodies, prompt dumps, secrets, or unredacted real input in
committed artifacts.

### Output Contract

The normalized adapter output contains:

- `fast_interaction_output_id`
- `adapter_id`
- `adapter_type=fast_interaction`
- `adapter_request_id`
- `turn_id`
- `utterance_id`
- `input_modality`
- `source_event_ids`
- `route_hint`
- `route_prelude`
- `foreground_act`
- `reply_candidate` optional but expected for low-risk answer paths
- `final_fast_evidence_ref`
- `risk_tags`
- `risk_class`
- `confidence`
- `schema_name`
- `normalization_status=normalized`
- `output_mode=real|mock|fallback|degraded`
- `trace_redaction_level`

`route_hint` and `route_prelude` are non-authoritative evidence. They can help
Router choose conservatively, but they do not become Router decisions.

`reply_candidate` is a candidate foreground text. It is not user-facing until
Fast Foreground Gate passes and `FOREGROUND_OUTPUT_COMMITTED` is emitted.

`final_fast_evidence_ref` is a normalized evidence ref for replay/debug and
optional SlowTask evidence packs. It is not a SlowTask fact source and cannot
become resolved arguments, confirmation state, tool status, or a
SemanticCommitment.

### Capability Matrix

The live profile must declare the ADR-011 fields plus Fast Interaction support:

- `supports_fast_interaction_output=true`
- `supports_audio_input=true`
- `supports_asr_text_fallback=true|false`
- `supports_route_hint=true`
- `supports_route_prelude=true`
- `supports_foreground_act=true`
- `supports_reply_candidate=true`
- `supports_provider_stream_timing=true|false`
- `supports_reply_delta_streaming=false` for UI display in the first MVP6.3
  slice; the adapter may buffer provider streaming internally for TTFT
  measurement and final schema validation
- `supports_final_fast_evidence=true`
- `supports_structured_json=true`
- `supports_schema_validation=true`
- `supports_risk_tags=true`
- `supports_confidence=true`
- `supports_ttft_observation=true|false`
- `max_reply_candidate_tokens`
- `expected_first_candidate_latency_ms`
- `expected_final_gate_ready_latency_ms`
- `timeout_policy`
- `retry_policy`
- `output_mode=real|mock|fallback|degraded`

If the provider cannot produce a safe candidate, the adapter must emit degraded
or fallback metadata. The runtime may use template fallback, but template output
must not be mislabeled as a real model candidate.

## 5. Runtime Data Flow

MVP6.3 first-version primary live flow:

```text
local wav / browser draft audio
-> local-only audio gate
-> TURN_INGRESS_COMMITTED
-> Live audio-native Fast Interaction Adapter using audio ref
-> FAST_INTERACTION_OUTPUT_EMITTED
-> optional FOREGROUND_REPLY_CANDIDATE_EMITTED
-> Router consumes route evidence
-> ROUTER_DECISION_EMITTED
-> TASK_FOCUS_STATE_UPDATED when needed
-> Fast Foreground Gate validates candidate
-> FOREGROUND_ACT_GATE_PASSED or FOREGROUND_ACT_GATE_FAILED
-> FOREGROUND_OUTPUT_COMMITTED or FOREGROUND_OUTPUT_DISCARDED
-> debug console response and local QA history metadata
```

ASR remains part of the live voice system, but it should not define the primary
fast answer architecture. In the complete QA debug profile it is an observation
branch, not a dependency:

```text
TURN_INGRESS_COMMITTED(audio)
├── Live audio-native Fast Interaction Adapter
│   └── Router -> Fast Foreground Gate -> committed/fallback Answer
└── ASR Adapter with asr_observation_enabled=true
    └── ASR_TRANSCRIPT_OUTPUT_EMITTED -> displayed Question / local QA history
```

The two provider calls start from the same committed turn and may execute in
parallel. Provider I/O may be concurrent, but canonical event appends remain
serialized through one per-session journal boundary. Fast Interaction output is
eligible for Router and gate processing as soon as it is ready; ASR completion
must not delay or change that decision. The debug response may join both branches
before returning a complete QA pair, but latency metadata must preserve the
independent fast-answer-ready time.

The observation profile requires a coordinator callback owned by the runtime.
Before the ASR observation event may be appended, the shared journal must already
contain `ROUTER_DECISION_EMITTED`, one foreground gate decision, and one final
foreground commit/discard event. A missing callback, a callback that writes a
different journal, or a callback that does not finalize foreground output fails
closed. Ordinary ASR observation exceptions become metadata-only adapter failure
events and cannot invalidate an already committed Fast Answer.

ASR-text Fast Interaction remains a separate fallback profile:

```text
TURN_INGRESS_COMMITTED(audio)
-> ASR_TRANSCRIPT_OUTPUT_EMITTED
-> Fast Interaction input_mode=asr_text_fallback
```

That fallback is serial by definition and must be labeled
`output_mode=degraded|fallback`. Enabling QA observation alone must never select
it.

The fast path may use an optimized audio-native Thinker profile, but it should
not wait for the current heavy Thinker profile before the foreground candidate
can be gated. The design goal is to split the audio-native path into a fast
foreground profile and a slower deliberative/background profile, not to replace
voice-native reasoning with a text-only model.

For complex task and patch routes:

- Fast Interaction may still emit route evidence and a candidate.
- Router may emit `SPAWN_SLOW_TASK` or `PATCH_ACTIVE_SLOW_TASK`.
- Gate must discard any answer candidate.
- Runtime may commit template `ACK_SLOW`, template `ACK_PATCH`, clarification,
  or silence according to existing MVP6.2 policy.
- SlowTask/UserPatch boundaries remain ADR-006/007/016 compliant.

## 6. Latency And Thinker Waterfall Strategy

MVP6.3 must make the audio-native bottleneck visible before replacing or
rewiring it. The debug surface should answer two questions for every live run:

1. How long did it take from requesting the Thinker / Fast Interaction provider
   until the first token or first stream chunk was observed?
2. How long did each step take from adapter invocation to full validated event
   emission?

The shared timing vocabulary applies to both the new audio-native Fast
Interaction adapter and the existing audio-native LALM Thinker path. Fast
Interaction fields use the `fast_interaction_` prefix; the current Thinker path
uses the `thinker_` prefix.

### Required timing fields

- `fast_interaction_input_mode=audio_native|asr_text_fallback|mock`
- `fast_interaction_adapter_request_id`
- `fast_interaction_timeout_ms`
- `fast_interaction_timed_out`
- `fast_interaction_output_mode`
- `fast_interaction_fallback_reason`
- `fast_interaction_adapter_start_offset_ms`
- `fast_interaction_audio_prepare_ms`
- `fast_interaction_request_build_ms`
- `fast_interaction_provider_request_start_offset_ms`
- `fast_interaction_provider_ttft_ms`
- `fast_interaction_provider_full_response_ms`
- `fast_interaction_provider_first_chunk_offset_ms`
- `fast_interaction_provider_full_response_offset_ms`
- `fast_interaction_provider_generation_ms`
- `fast_interaction_stream_decode_ms`
- `fast_interaction_parse_validate_emit_ms`
- `fast_interaction_adapter_event_emit_offset_ms`
- `fast_interaction_total_ms`
- `thinker_adapter_start_offset_ms`
- `thinker_audio_prepare_ms`
- `thinker_request_build_ms`
- `thinker_provider_request_start_offset_ms`
- `thinker_provider_ttft_ms`
- `thinker_provider_full_response_ms`
- `thinker_provider_first_chunk_offset_ms`
- `thinker_provider_full_response_offset_ms`
- `thinker_provider_generation_ms`
- `thinker_stream_decode_ms`
- `thinker_parse_validate_emit_ms`
- `thinker_adapter_event_emit_offset_ms`
- `thinker_total_ms`
- `thinker_timing_mode=streaming|non_streaming`
- `thinker_ttft_available=true|false`
- `thinker_ttft_source=provider_stream_chunk|provider_token_delta|not_available`

`*_provider_ttft_ms` is measured from provider request send start to the first
provider token/delta/chunk that proves the model has begun responding. If the
provider path is non-streaming, TTFT must not be invented; set
`*_ttft_available=false` and record only full-response timing.

`*_provider_request_start_offset_ms`, `*_provider_first_chunk_offset_ms`,
`*_provider_full_response_offset_ms`, and `*_adapter_event_emit_offset_ms` are
offsets from turn ingress. They make concurrent ASR / Fast Interaction /
Thinker runs comparable without relying on wall-clock timestamps in replay.

`*_provider_full_response_ms` is measured from provider request send start to
the last response byte / final stream event / SDK full-response completion.
`*_provider_generation_ms` is derived when TTFT exists:

```text
provider_generation_ms = provider_full_response_ms - provider_ttft_ms
```

`*_parse_validate_emit_ms` covers provider response decode, schema parse,
adapter normalization, validation, and append/emit of the normalized adapter
event. If implementation needs more detail during experiments, it may expose
local-only subfields such as `json_parse_ms`, `schema_validate_ms`, and
`journal_append_ms`, but those fields must remain metadata-only and must not
include raw response text.

`*_total_ms` is adapter invocation start to adapter output/failure/degraded event
emitted. This is the number that tells whether the candidate was actually ready
for Router and Fast Foreground Gate.

### End-to-end debug waterfall

The debug console and QA history should preserve a compact waterfall:

```text
turn_ingress_ms
audio_ref_ready_ms
asr_provider_http_ms
asr_normalize_emit_ms
asr_provider_request_start_offset_ms
asr_adapter_event_emit_offset_ms
fast_interaction_provider_request_start_offset_ms
fast_interaction_audio_prepare_ms
fast_interaction_request_build_ms
fast_interaction_provider_ttft_ms
fast_interaction_provider_full_response_ms
fast_interaction_parse_validate_emit_ms
fast_interaction_total_ms
thinker_provider_request_start_offset_ms
thinker_provider_ttft_ms
thinker_provider_full_response_ms
thinker_parse_validate_emit_ms
thinker_total_ms
router_ms
foreground_gate_ms
foreground_output_finalize_ms
fast_answer_ready_offset_ms
qa_pair_ready_offset_ms
total_server_ms
```

Unavailable timing values are represented as `null`, never fabricated as zero.
`router_ms` measures Router work only, `foreground_gate_ms` measures the
deterministic gate decision, and `foreground_output_finalize_ms` measures the
subsequent commit/discard/fallback finalization boundary.

ASR and Thinker may run in parallel with Fast Interaction, so the waterfall
should include both absolute offsets from turn ingress and duration fields where
possible. This lets experiments distinguish:

- `provider_calls_parallel=true` means the provider calls were submitted through
  the explicit parallel I/O boundary;
- `provider_calls_overlapped` records whether their measured execution windows
  actually overlapped (instant fake calls may legitimately report `false`);

- audio preparation / encoding overhead;
- request construction and client-side body build overhead;
- provider queue or server wait before first token;
- generation time after first token;
- stream decode overhead;
- schema parsing and validation overhead;
- event journal and gate overhead.

### Timeout and fail-closed policy

The Fast Interaction timeout must be smaller than the slow Thinker path, but it
must be chosen after observing TTFT and full-response distributions. If Fast
Interaction times out, the runtime fails closed:

- emit adapter failure/degraded metadata as appropriate;
- do not show partial provider text;
- do not treat timeout as a low-risk answer;
- use template fallback, clarification, silence, or slow-system handoff based on
  Router/runtime policy;
- record latency and failure reason in debug metadata/history.

Live latency claims must be tagged as `real`, `degraded`, or `fallback`. Mock
latency remains useful for control-plane tests but must not be presented as live
provider performance.

## 7. Event / Replay Strategy

MVP6.3 uses existing ADR-017 canonical events:

- `FAST_INTERACTION_OUTPUT_EMITTED`
- `FOREGROUND_REPLY_CANDIDATE_EMITTED`
- `FOREGROUND_ACT_GATE_PASSED`
- `FOREGROUND_ACT_GATE_FAILED`
- `FOREGROUND_OUTPUT_COMMITTED`
- `FOREGROUND_OUTPUT_DISCARDED`

No new MVP-relevant event name is required for the first design. Adapter timeout
or validation failure should use existing ADR-002 adapter events:

- `ADAPTER_REQUEST_RETRYING`
- `ADAPTER_REQUEST_FAILED`
- `ADAPTER_OUTPUT_VALIDATION_FAILED`
- `ADAPTER_OUTPUT_DEGRADED`

Replay requirements:

- Replay uses recorded adapter output refs, candidate refs, Router decision,
  gate event, committed output, and discard events.
- Replay never reruns the Fast Interaction provider.
- Replay never reruns the Thinker provider to recompute timing. TTFT and
  waterfall values are recorded metadata and replayed as recorded.
- Replay never reconstructs behavior from raw prompt, provider body, env secret,
  local wav path, or raw audio.
- Shareable replay / GitHub fixtures are synthetic, redacted, or metadata-only.
- Forbidden ASR payload checks are recursive, so nested raw transcript or
  provider payload fields are rejected as well as top-level fields.
- Debug history/API may include display text only after safety validation.
- History/API must not contain raw prompt, provider body, secret, credential,
  raw audio, local path, diagnostics, local replay cache, or unredacted real
  input.
- Timing metadata may be persisted only as scalar durations, offsets,
  mode/source labels, and event/request ids. It must not include provider
  headers that contain secrets, raw token text, raw deltas, raw audio, local
  paths, request bodies, response bodies, or prompt dumps.

Local debug `model_io` may remain process-local and explicitly unsaved. If the
debug page exposes it for manual live runs, it must be redacted, local-only,
not written to QA history, not written to replay fixtures, and safe-response
validated before display.

## 8. Gate Policy

Fast Foreground Gate remains deterministic runtime policy. A real candidate may
be shown only when all of these are true:

```text
router_decision = FAST_ONLY
foreground_act = ANSWER
risk_class = LOW
confidence >= configured_threshold
candidate schema valid
candidate boundary safe
active SlowTask policy allows foreground side chat, if a task is active
```

Candidate boundary safety means the candidate does not:

- claim a tool ran;
- claim an external side effect happened;
- accept/reject confirmation;
- mutate current-plan facts;
- rewrite SlowTask goal, constraints, resolved arguments, tool status, risk
  warnings, confirmation state, or SemanticCommitment facts;
- use stale evidence as current fact;
- rely on webSearch / RAG / tool output as instruction;
- answer high-risk professional, latest-fact, external-action, or unresolved
  critical-field questions.

Gate failure policy:

- `SPAWN_SLOW_TASK`: discard candidate answer; optional template `ACK_SLOW` or
  lawful progress path only.
- `PATCH_ACTIVE_SLOW_TASK`: discard candidate answer; optional template
  `ACK_PATCH` / clarification; UserPatch remains evidence-only.
- `IGNORE`: discard candidate answer; default silence unless product policy
  allows a safe rejection template.
- `AMBIGUOUS` or `task_focus=AMBIGUOUS`: discard candidate answer; short
  clarification or silence only.
- active SlowTask with `ACTIVE_TASK_PATCH`, `NEW_TASK_CANDIDATE`,
  `CANCEL_OR_PAUSE_CANDIDATE`, or `AMBIGUOUS`: discard candidate answer and
  preserve ADR-006/007/016 ownership.

Gate pass only means the candidate can be displayed as low-risk foreground text.
It is not SemanticCommitment, not playback delivery, and not user confirmation.
The debug/API projection must additionally prove that the committed
`output_ref` exactly matches the emitted `candidate_ref`. Template fallback text
is resolved only from the runtime template catalog after validating the
committed `output_ref`, `output_basis`, `fallback_policy_ref`, and
`fallback_reason`; route-based UI hardcoding is not an authority source.

## 9. Debug Console And History

MVP6.3 extends the MVP6 debug console response/history with safe metadata:

- `question_source=asr_transcript|credential_filter|unavailable`
- `question_text` from the normalized ASR transcript for local-only display
- `answer_display` from `FOREGROUND_OUTPUT_COMMITTED` or deterministic fallback
- `qa_status=complete|question_unavailable|answer_fallback|redacted|failed`
- `asr_observation_enabled`
- `asr_output_mode`
- `fast_interaction_output_mode`
- `fast_interaction_input_mode`
- `fast_interaction_adapter_id`
- `fast_interaction_adapter_request_id`
- `fast_interaction_output_event_id`
- `foreground_candidate_event_id`
- `foreground_act`
- `foreground_risk_class`
- `foreground_risk_tags`
- `foreground_confidence`
- `foreground_gate_decision`
- `foreground_gate_event_id`
- `foreground_gate_failure_reason`
- `foreground_output_event_id`
- `foreground_candidate_ref`
- `foreground_output_ref`
- `foreground_output_basis`
- `foreground_discard_event_id`
- `foreground_fallback_reason`
- `foreground_fallback_policy_ref`
- `fast_interaction_adapter_start_offset_ms`
- `fast_interaction_provider_request_start_offset_ms`
- `fast_interaction_provider_first_chunk_offset_ms`
- `fast_interaction_provider_full_response_offset_ms`
- `fast_interaction_adapter_event_emit_offset_ms`
- `fast_interaction_audio_prepare_ms`
- `fast_interaction_request_build_ms`
- `fast_interaction_provider_ttft_ms`
- `fast_interaction_provider_full_response_ms`
- `fast_interaction_provider_generation_ms`
- `fast_interaction_stream_decode_ms`
- `fast_interaction_parse_validate_emit_ms`
- `foreground_gate_ms`
- `foreground_output_finalize_ms`
- `fast_interaction_total_ms`
- `fast_interaction_timed_out`
- `thinker_adapter_start_offset_ms`
- `thinker_provider_request_start_offset_ms`
- `thinker_provider_first_chunk_offset_ms`
- `thinker_provider_full_response_offset_ms`
- `thinker_adapter_event_emit_offset_ms`
- `thinker_provider_ttft_ms`
- `thinker_provider_full_response_ms`
- `thinker_provider_generation_ms`
- `thinker_parse_validate_emit_ms`
- `thinker_total_ms`
- `thinker_timing_mode`
- `thinker_ttft_available`
- `thinker_ttft_source`

The console display may show:

- the normalized ASR Question from the parallel observation branch;
- the real gated reply candidate for `FAST_ONLY + ANSWER + LOW risk`;
- template `ACK_SLOW` for slow task spawn;
- template `ACK_PATCH` for active task patch;
- template clarification for ambiguous input;
- silence/no output for ignore.

When the user keeps `Save QA history locally` enabled, local ignored history may
store the normalized ASR Question and the exact runtime-approved displayed
Answer. It must never store raw audio, raw prompt, provider request/response
bodies, candidate text that was discarded, local paths, authorization data, or
secrets. Shareable fixtures and committed artifacts remain synthetic or
redacted.

Before Question or Answer text enters the response or local history, a shared
credential detector checks common API-key, JWT, private-key, authorization, and
credential-assignment shapes. Suspect text is replaced by a safe local
placeholder/status (`question_status=redacted`, `answer_status=redacted`,
`qa_status=redacted`) and the original text is not persisted.

## 10. Implementation Slices Proposal

### Slice 1: Design doc + tests outline

Create this design document, review it against ADRs, and outline tests for the
live Fast Interaction adapter, gate integration, replay safety, debug metadata,
and timeout/fallback paths.

Checks:

- `rg -n "MVP6\\.3|Fast Interaction|fast_interaction|foreground" docs/implementation/mvp6.3-live-fast-interaction-design.md`
- `git diff --check -- docs/implementation/mvp6.3-live-fast-interaction-design.md`

### Slice 2: Timing contract for audio-native Thinker / Fast Interaction

Add metadata-only timing dataclasses / helpers and tests for TTFT, full-response,
parse/validate/emit, and total adapter duration. This slice should not change
runtime behavior or call providers.

Likely targets:

- `src/voice_agent/adapters/lalm_thinker_profile.py`
- `src/voice_agent/adapters/fast_interaction_contract.py`
- `src/voice_agent/adapters/fast_interaction_profile.py`
- `tests/adapters/test_lalm_thinker_profile.py`
- `tests/adapters/test_fast_interaction_capability.py`
- `tests/adapters/test_fast_interaction_contract.py`

Tests should cover TTFT availability, non-streaming `ttft_available=false`,
derived generation timing, metadata-only redaction, and replay-safe scalar
fields.

### Slice 3: Capability / profile / schema for audio-native Fast Interaction

Add the audio-native adapter capability/profile/schema surface without live
network calls.

Likely targets:

- `src/voice_agent/adapters/fast_interaction_contract.py`
- `src/voice_agent/adapters/fast_interaction_profile.py`
- `tests/adapters/test_fast_interaction_capability.py`
- `tests/adapters/test_fast_interaction_contract.py`

Tests should cover required capability fields, schema validation, output mode,
risk/confidence metadata, audio input support, ASR-text fallback labeling, and
safe ref/redaction constraints.

### Slice 4: Audio-native live transport with fake/injected transport tests

Implement a live audio-native adapter transport that can reuse the existing
OpenAI-compatible transport hygiene pattern, but only through an injected
transport/opener in tests. Default tests must not use network.

Likely targets:

- `src/voice_agent/adapters/fast_interaction_live_transport.py`
- `src/voice_agent/adapters/fast_interaction_runtime_adapter.py`
- `tests/adapters/test_fast_interaction_live_transport.py`
- `tests/adapters/test_fast_interaction_runtime_adapter.py`

Tests should cover request construction without raw audio, timeout/failure
categories, streaming TTFT capture, non-streaming TTFT unavailable, validation
failure, redacted process-local model I/O, and no secret or provider body in
metadata.

### Slice 5: Runtime integration behind explicit provider mode / approval gate

Thread audio-native Fast Interaction into the MVP5/MVP6 route runner behind
explicit provider mode and approval. It must not run by default and must not run
after Router as a second answer call.

Likely targets:

- `src/voice_agent/runtime/mvp5_live_voice_evidence.py`
- `src/voice_agent/runtime/mvp5_real_voice_e2e_smoke.py`
- `src/voice_agent/runtime/mvp5_live_router_runner.py`
- `src/voice_agent/runtime/mvp6_debug_console_api.py`
- `tests/runtime/test_mvp6_debug_console_runs.py`
- `tests/runtime/test_mvp5_live_route_results.py`

Tests should prove provider-free defaults, approval/credential gating, timeout
fail-closed behavior, audio-native primary input, ASR-text fallback labeling,
and no post-Router FastReplyAdapter call.

### Slice 6: Debug console response / history / latency fields

Expose safe response/history fields for Fast Interaction, foreground gate, and
Thinker latency waterfall.

Likely targets:

- `src/voice_agent/runtime/mvp6_debug_console_api.py`
- `src/voice_agent/runtime/mvp6_debug_console_history.py`
- `src/voice_agent/runtime/mvp6_debug_console_static.py`
- `tests/runtime/test_mvp6_debug_console_history.py`
- `tests/runtime/test_mvp6_debug_console_static.py`

Tests should reject unsafe keys/markers, preserve metadata-only latency fields,
show real gated output only after gate pass, record fallback/discard reasons,
and display TTFT/full-response timing without raw provider I/O.

### Slice 7: Replay / acceptance / golden cases

Add deterministic synthetic coverage for:

- real-mode metadata shape using injected fake transport;
- audio-native primary path;
- ASR-text degraded/fallback path;
- Thinker TTFT and full-response metadata replay;
- timeout fallback;
- schema validation failure;
- `FAST_ONLY + ANSWER + LOW` pass;
- slow task spawn discard/template;
- active task patch discard/template;
- ambiguous/no-answer;
- replay not rerunning provider;
- fixture safety export.

Likely targets:

- `tests/replay/test_mvp5_live_route_replay.py`
- `tests/acceptance/test_mvp6_acceptance_scenarios.py`
- `tests/runtime/test_mvp6_routing_golden_eval.py`
- `tests/fixtures/replay/mvp6/`

### Slice 8: Manual live debug flow docs

Document an explicit local-only flow for humans to opt into live Fast
Interaction. The doc should specify approval packet fields, timeout, max
provider calls, credential env var name, audio-native profile selection, TTFT
waterfall interpretation, output mode labels, expected history fields, and
safety exclusions.

Likely targets:

- `docs/implementation/mvp6.3-live-fast-interaction-manual-debug.md`
- optional approval packet template that contains no secret and is clearly
  local-only / not committed.

## 11. Test Outline

Default verification remains provider-free:

- Contract tests for audio-native capability/profile/schema.
- Timing tests for TTFT, full response, derived generation time, and
  non-streaming TTFT unavailability.
- Transport tests using fake/injected opener only, including streaming timing.
- Runtime tests proving no Fast Interaction call after Router.
- Gate tests for pass, discard, fallback, ambiguous, ignore, and active SlowTask
  boundaries.
- Debug console response/history tests for safe metadata and latency waterfall
  fields.
- Replay tests proving recorded refs/events are used and provider is not rerun.
- Fixture/export safety tests for raw audio, raw prompt, provider body, local
  paths, diagnostics, secrets, and unredacted real input.

Python tests must use `./scripts/test`, not direct `pytest`.

## 12. Open Decisions

1. Should MVP6.3 implement the audio-native fast path as a dedicated
   `fast_interaction` adapter backed by a different audio-capable model, or as a
   dedicated `fast_interaction` adapter backed by an optimized fast profile of
   the current audio-native Thinker provider/model family?

2. What are the initial live Fast Interaction confidence threshold and risk-tag
   allowlist for `FAST_ONLY + ANSWER` display?

3. What is the initial Fast Interaction timeout? It should be chosen after
   observing audio-native TTFT and full-response distributions, and must be
   smaller than the slow deliberative Thinker path.

4. Which provider streaming mode gives reliable TTFT: SDK stream, SSE chunks, or
   response headers plus stream callbacks?

5. When audio-native Fast Interaction times out, should ASR-text fallback run
   automatically under explicit provider mode, or only when a separate fallback
   flag is enabled?

6. How much process-local, unsaved `model_io` should the debug page expose for
   live manual debugging?

7. Should `IGNORE` produce explicit `FOREGROUND_OUTPUT_COMMITTED` with
   `output_basis=silence_policy`, or only candidate discard with no visible
   output?

8. Should the first live profile allow only non-streaming complete candidates,
   or buffer streaming deltas internally while still displaying only after final
   route/gate pass?

## ADR Stop Conditions

Stop and update/create an ADR before implementation if a slice requires:

- a second model request after Router for answer generation;
- displaying streaming deltas before final route and gate pass;
- real TTS, audio playback, or Talker delivery claims;
- new RouterDecision values or Router-owned complex reasoning;
- Fast Interaction output becoming SemanticCommitment or SlowTask fact source;
- direct provider calls outside adapters;
- provider calls during deterministic replay;
- real external tools or side effects;
- production privacy policy;
- raw audio, raw prompt, provider body, diagnostics, secrets, local replay
  cache, local paths, or unredacted real user input in committed artifacts.
