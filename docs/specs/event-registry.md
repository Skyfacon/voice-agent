# Canonical Event Registry

Source of truth: frozen ADR Baseline v0.4. This document carries P1-B-001. It is a spec detail, derived from ADR baseline, unless an item explicitly quotes an ADR decision.

ADR-002 is the canonical source for MVP event names. This document does not create new event names outside ADR-002.

## 1. Event Envelope Schema

Every event MUST include the common envelope fields from ADR-002:

| Field | Required | Meaning |
| --- | --- | --- |
| `event_id` | yes | Globally unique event id. |
| `event_seq` | yes | Strictly increasing sequence within a session. |
| `event_schema_version` | yes | Envelope plus payload schema version. |
| `session_id` | yes | Session id. |
| `conversation_id` | yes | Conversation id. |
| `source_module` | yes | Module that emitted the event. |
| `created_monotonic_ms` | yes | Runtime monotonic timestamp for ordering/SLOs. |
| `created_wall_clock_ms` | yes | Wall clock timestamp for display/audit only. |
| `caused_by_event_id` | yes except root | Immediate causal source event. |
| `supersedes_event_id` | optional | Event superseded or invalidated by this event. |
| `trace_redaction_level` | yes | Trace/export sensitivity class. |

Common context binding fields are required only when relevant to the event:

- `turn_id`
- `utterance_id`
- `input_span_id`
- `text_span_id`
- `audio_span_id`
- `playback_span_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `audio_sample_offset`
- `playback_offset_ms`

## 2. Event Naming Conventions

- Event names are uppercase snake case. [ADR-002]
- Candidate events describe module-local or pre-final policy evidence, for example `BARGE_IN_CANDIDATE`. [ADR-001, ADR-003]
- Interaction finalized events describe deterministic policy outputs, for example `TURN_INGRESS_COMMITTED`. [ADR-001]
- Playback events describe delivery and control markers, not semantic acknowledgement. [ADR-001, ADR-002]
- SlowTask events must bind `task_id`, `plan_version`, `task_event_seq`, and causal links when task-relevant. [ADR-004, ADR-016]
- Tool execution events must use current-plan metadata and canonical progressive tool names. [ADR-005, ADR-016]
- Adapter and trace events must not expose secrets. [ADR-010, ADR-011]

## 3. ID / Ref Conventions

Spec detail, derived from ADR baseline:

- `*_id` fields identify runtime entities and events.
- `*_ref` fields identify payloads that may be external to the journal payload, redacted, or fixture-substituted.
- `event_id`, `session_id`, `conversation_id`, `turn_id`, `utterance_id`, `task_id`, `tool_call_id`, `patch_id`, `confirmation_id`, `commitment_id`, `spoken_plan_id`, `replay_id`, and adapter ids MUST be stable within replay.
- `input_span_id`, `text_span_id`, `audio_span_id`, and `playback_span_id` bind data-plane spans to control-plane events.
- `idempotency_key` is required for write/action tool execution. [ADR-005, ADR-016]

## 4. event_schema_version Policy

Spec detail, derived from ADR baseline:

- Baseline schema version starts at `1.0`.
- Additive optional fields MAY increment minor version.
- Removing fields, changing requiredness, or changing payload semantics requires a new major version and replay migration plan.
- MVP-relevant new event names require an ADR-002 update before implementation. [ADR-002, ADR-015]
- Replay fixtures MUST declare the schema version range they were produced from.

## 5. Required Common Fields

Every event row below inherits the envelope fields in section 1. The table `required_fields` column lists event-specific payload/context fields in addition to the envelope.

## 6. Required / Optional Field Notation

- `required_fields`: fields that MUST be present when the event is emitted.
- `optional_fields`: fields that MAY be absent or null.
- A field listed as `x or y` means at least one of the alternatives must be present.
- A field listed with a literal, for example `input_modality=text`, must have that value.

## 7. Canonical Registry

| event_name | event_family | source_module | payload_owner | required_fields | optional_fields | causal_links | state_reducer_target | required_in_mvp0 | replay_required | privacy_redaction_notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `SESSION_STARTED` | Session events | Session Runtime | Session Runtime | `session_id`, `conversation_id`, `runtime_config_ref`, `capability_snapshot_ref` | - | root event | AdapterHealthState, TracePrivacyState | true | true | metadata only; config refs must not contain secrets |
| `SESSION_ENDED` | Session events | Session Runtime | Session Runtime | `session_id`, `end_reason` | - | final runtime/user/system event | none | false | true | metadata only |
| `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` | Session events | Adapter Registry / Session Runtime | Adapter Registry | `capability_snapshot_ref`, `adapter_ids`, `adapter_types`, `deployment_modes`, `output_modes` | `capability_version` | session startup or registry refresh | AdapterHealthState | true | true | endpoint refs must not include credentials |
| `TEXT_INPUT_RECEIVED` | Input events | Access Layer | Access Layer | `input_span_id`, `text_span_id`, `input_modality=text`, `redacted_text` or `text_ref`, `directedness=ASSUMED_DIRECTED`, `semantic_close=ASSUMED_CLOSED` | `language_hint` | user text ingress | InteractionState | true when text input is used | true | shareable fixtures use redacted/synthetic text |
| `LOW_CONFIDENCE_INGRESS` | Input events | Interaction Controller | Interaction Controller | `input_span_id` or `audio_span_id`, `confidence_fields`, `ingress_reason` | `policy_ref` | Duplex candidate or text policy check | InteractionState | true when exercised | true | metadata; avoid raw utterance |
| `AUDIO_SPAN_STARTED` | Audio span events | Access Layer | Access Layer | `audio_span_id`, `input_modality=audio`, `audio_sample_offset`, `audio_format_ref` | `input_span_id` | mic/audio ingress | InteractionState | true for audio path | true | no raw audio inline |
| `AUDIO_CHUNK_RECEIVED` | Audio span events | Access Layer | Access Layer | `audio_span_id`, `chunk_index`, `audio_sample_offset`, `chunk_duration_ms` | `audio_chunk_ref` | `AUDIO_SPAN_STARTED` | none | false | false | raw chunk refs local debug only |
| `AUDIO_SPAN_ENDED` | Audio span events | Access Layer | Access Layer | `audio_span_id`, `audio_sample_offset`, `duration_ms`, `end_reason` | - | audio ingress end | InteractionState | true for audio path | true | no raw audio inline |
| `PLAYBACK_SPAN_STARTED` | Playback events | Talker | Talker | `playback_span_id`, `audio_ref` or `tts_stream_ref` | `spoken_plan_id`, `approved_check_event_id` | approved response/SpokenPlan/check | PlaybackState | true | true | audio refs local or generated; no secrets |
| `PLAYBACK_PROGRESS` | Playback events | Talker | Talker | `playback_span_id`, `playback_offset_ms` | `progress_basis` | `PLAYBACK_SPAN_STARTED` | PlaybackState | true | true | metadata only |
| `PLAYBACK_COMMITTED` | Playback events | Talker | Talker | `playback_span_id`, `playback_offset_ms`, `commit_basis` | - | playback progress or finish | PlaybackState | true | true | delivery marker only, not semantic acknowledgement |
| `PLAYBACK_FINISHED` | Playback events | Talker | Talker | `playback_span_id`, `final_playback_offset_ms` | `finish_reason` | playback completion | PlaybackState | false | true | metadata only |
| `TTS_TRUNCATE_REQUESTED` | Playback events | Interaction Controller | Interaction Controller | `playback_span_id`, `cutoff_playback_offset_ms`, `interrupt_candidate_event_id` | `audio_span_id` | `INTERRUPT_CANDIDATE` | InteractionState, PlaybackState | true for interrupt path | true | metadata only |
| `TTS_TRUNCATED` | Playback events | Talker | Talker | `playback_span_id`, `actual_stop_offset_ms`, `truncate_request_event_id` | `final_playback_offset_ms` | `TTS_TRUNCATE_REQUESTED` | InteractionState, PlaybackState | true for interrupt path | true | metadata only |
| `SPEECH_START_DETECTED` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `audio_sample_offset`, `vad_confidence` | `detection_basis` | `AUDIO_SPAN_STARTED` or audio analysis | InteractionState | true for audio path | true | no raw audio inline |
| `SPEECH_END_DETECTED` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `audio_sample_offset`, `vad_confidence`, `silence_duration_ms` | `detection_basis` | audio analysis or `AUDIO_SPAN_ENDED` | InteractionState | true for audio path | true | no raw audio inline |
| `BARGE_IN_CANDIDATE` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, `barge_in_confidence` | `playback_reference_ref` | speech/playback overlap | InteractionState | true for interrupt path | true | no raw audio; playback ref metadata only in shareable fixture |
| `DIRECTEDNESS_CANDIDATE` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `directedness`, `directedness_confidence` | `evidence_ref` | audio analysis | InteractionState | false | true when emitted | no raw audio |
| `SEMANTIC_CLOSE_CANDIDATE` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `semantic_close`, `semantic_close_confidence` | `evidence_ref` | audio analysis | InteractionState | false | true when emitted | no raw audio |
| `NON_ASSISTANT_CANDIDATE` | Duplex events | Duplex / Realtime Audio Controller | Duplex | `audio_span_id`, `directedness=NOT_DIRECTED`, `directedness_confidence` | `evidence_ref` | directedness analysis | InteractionState | false | true when emitted | no raw audio |
| `TURN_OPENED` | Interaction events | Interaction Controller | Interaction Controller | `turn_id`, `input_span_id` or `audio_span_id`, `turn_phase=COLLECTING_INPUT`, `input_modality` | `text_span_id` | `TEXT_INPUT_RECEIVED` or `SPEECH_START_DETECTED` | InteractionState | true | true | text redacted by source event |
| `TURN_HELD` | Interaction events | Interaction Controller | Interaction Controller | `turn_id`, `ingress_outcome=HELD`, `semantic_close`, `directedness` | `hold_reason` | `SEMANTIC_CLOSE_CANDIDATE` or policy | InteractionState | true when exercised | true | metadata only |
| `TURN_INGRESS_ACCEPTED` | Interaction events | Interaction Controller | Interaction Controller | `turn_id`, `input_span_id` or `audio_span_id`, `ingress_outcome=ACCEPTED` | `text_span_id` | text ingress or Duplex accepted candidate | InteractionState | true | true | metadata only |
| `TURN_INGRESS_REJECTED` | Interaction events | Interaction Controller | Interaction Controller | `turn_id`, `input_span_id` or `audio_span_id`, `ingress_outcome=REJECTED`, `reject_reason` | `text_span_id` | `NON_ASSISTANT_CANDIDATE` or low confidence policy | InteractionState | true when exercised | true | metadata-only in shareable fixtures |
| `TURN_INGRESS_COMMITTED` | Interaction events | Interaction Controller | Interaction Controller | `turn_id`, `utterance_id`, `input_modality`, `input_span_id` or `text_span_id` or `audio_span_id`, `directedness`, `semantic_close`, `ingress_outcome=COMMITTED` | - | `TURN_INGRESS_ACCEPTED` or text policy | InteractionState | true | true | refs only; no raw audio/text required |
| `INTERRUPT_CANDIDATE` | Interaction events | Interaction Controller | Interaction Controller | `playback_span_id`, `playback_offset_ms`, `policy_reason`, `confidence_summary` | `audio_span_id` | `BARGE_IN_CANDIDATE` or text-during-playback policy | InteractionState | true for interrupt path | true | metadata only |
| `WAITING_USER` | Interaction events | Interaction Controller | Interaction Controller | `wait_reason` | `turn_id` | response end, held input, clarification, confirmation state | InteractionState | false | true when emitted | metadata only |
| `ROUTER_DECISION_EMITTED` | Router events | Router | Router | `turn_id`, `utterance_id`, `router_decision` | `task_focus`, `confidence`, `evidence_uncertainty` | `TURN_INGRESS_COMMITTED` and available ASR/Thinker frames | TaskFocusState | true | true | evidence refs redacted by source |
| `TASK_FOCUS_STATE_UPDATED` | Router events | Router | Router | `active_task_id` optional, `foreground_mode`, `side_conversation_allowed`, `default_patch_policy`, `ambiguous_input_policy`, `last_focus_decision`, `last_focus_confidence`, `router_decision_event_id` | - | `ROUTER_DECISION_EMITTED` | TaskFocusState | false | true | metadata only |
| `ADAPTER_HEALTHCHECK_FAILED` | Model adapter events | Adapter Registry / Adapter | Adapter Registry | `adapter_id`, `adapter_type`, `health_status`, `failure_reason`, `output_mode` | `endpoint_ref` | startup or periodic healthcheck | AdapterHealthState | false | true | no endpoint credentials |
| `ADAPTER_REQUEST_RETRYING` | Model adapter events | Adapter | Adapter | `adapter_id`, `adapter_type`, `adapter_request_id`, `retry_count`, `retry_reason` | `timeout_ms` | retryable adapter failure or timeout | AdapterHealthState | false | true | no request body secrets |
| `ADAPTER_REQUEST_FAILED` | Model adapter events | Adapter | Adapter | `adapter_id`, `adapter_type`, `adapter_request_id`, `failure_reason`, `retryable`, `output_mode` | `timeout_ms` | final adapter failure | AdapterHealthState | false | true | no provider secret payload |
| `ADAPTER_OUTPUT_VALIDATION_FAILED` | Model adapter events | Adapter / Schema Validator | Adapter | `adapter_id`, `adapter_type`, `adapter_request_id`, `schema_name`, `failure_reasons`, `output_mode` | `invalid_output_ref` | provider output schema validation failure | AdapterHealthState | false | true | invalid refs local/redacted only |
| `ADAPTER_OUTPUT_DEGRADED` | Model adapter events | Adapter / Runtime | Adapter Registry | `adapter_id`, `adapter_type`, `degraded_reason`, `output_mode` | `adapter_request_id`, `missing_capability`, `fallback_adapter_id` | unsupported capability, fallback, degraded output | AdapterHealthState | false | true | metadata only |
| `MOCK_ASR_FRAME_EMITTED` | Model adapter events | ASR Adapter | ASR Adapter | `turn_id`, `utterance_id`, `input_modality`, `asr_frame_ref`, `output_mode=mock` | `audio_span_id`, `text_span_id` | `TURN_INGRESS_COMMITTED` | none | true | true | fixture may use synthetic transcript |
| `MOCK_THINKER_FRAME_EMITTED` | Model adapter events | Thinker Adapter | Thinker Adapter | `turn_id`, `utterance_id`, `semantic_frame_ref`, `output_mode=mock` | `input_modality` | `TURN_INGRESS_COMMITTED` | none | true | true | fixture may use synthetic semantic frame |
| `SLOWTASK_CREATED` | SlowTask events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `initial_goal_ref` | `source_evidence_refs` | `ROUTER_DECISION_EMITTED` spawn decision | SlowTaskState | false | true | goal refs redacted/synthetic in shareable fixtures |
| `SLOWTASK_STATE_CHANGED` | SlowTask events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `from_state`, `to_state`, `reason` | - | SlowTask transition input | SlowTaskState | false | true | metadata only |
| `USER_PATCH_RECEIVED` | SlowTask events | UserPatch Pipeline | UserPatch Pipeline | `patch_id`, `task_id`, `plan_version`, `task_event_seq`, `observed_plan_version`, `evidence_ref` | `turn_id`, `utterance_id` | Router patch decision | SlowTaskState | false | true | evidence refs redacted/synthetic for shareable replay |
| `USER_PATCH_INTERPRETED` | SlowTask events | SlowTask Runtime | SlowTask Runtime | `patch_id`, `task_id`, `interpreted_against_plan_version`, `interpretation_type`, `materially_changes_task` | `interpretation_reason`, `source_evidence_refs` | `USER_PATCH_RECEIVED` | SlowTaskState | false | true | no raw user text required |
| `PLAN_VERSION_ADVANCED` | SlowTask events | SlowTask Runtime | SlowTask Runtime | `task_id`, `from_plan_version`, `to_plan_version`, `planning_reason` | `caused_by_user_patch_event_id` | material patch/tool/risk change | SlowTaskState | false | true | metadata only |
| `TASK_REPLANNED` | SlowTask events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `planning_reason` | `superseded_plan_version` | `PLAN_VERSION_ADVANCED` or initial planning | SlowTaskState | false | true | metadata only |
| `EVIDENCE_REVIEWED` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `evidence_refs`, `review_result` | - | SlowTask review | SlowTaskState | false | true | refs redacted by source |
| `AMBIGUITY_DETECTED` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `ambiguous_fields`, `source_evidence_refs` | - | `EVIDENCE_REVIEWED` | SlowTaskState | false | true | no raw sensitive field values in shareable fixtures |
| `AMBIGUITY_RESOLVED` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `resolved_fields`, `resolution_reason`, `source_evidence_refs` | - | `AMBIGUITY_DETECTED` or `EVIDENCE_REVIEWED` | SlowTaskState | false | true | redacted values for shareable fixtures |
| `CLARIFICATION_REQUESTED` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `missing_or_ambiguous_fields`, `clarification_prompt_ref` | - | `AMBIGUITY_DETECTED` or insufficient evidence | SlowTaskState | false | true | prompt refs only |
| `ARGUMENTS_RESOLVED` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `resolved_arguments_ref`, `provenance_ref` | - | `EVIDENCE_REVIEWED` or `AMBIGUITY_RESOLVED` | SlowTaskState | false | true | resolved args redacted/minimized for shareable fixtures |
| `ARGUMENT_RESOLUTION_PROVENANCE` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `field_provenance_refs` | - | `ARGUMENTS_RESOLVED` | SlowTaskState | false | true | refs only |
| `INSUFFICIENT_EVIDENCE_FOR_ACTION` | SlowTask evidence events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `blocking_fields`, `source_evidence_refs` | - | evidence review before action | SlowTaskState | false | true | metadata only |
| `PLANNING_STARTED` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `planning_reason` | - | `SLOWTASK_CREATED` or `TASK_REPLANNED` | SlowTaskState | false | true | metadata only |
| `PLANNING_RESTARTED` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `restart_reason` | - | `PLAN_VERSION_ADVANCED` or tool/risk change | SlowTaskState | false | true | metadata only |
| `WAITING_FOR_SLOT` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `missing_fields` | - | `CLARIFICATION_REQUESTED` | SlowTaskState | false | true | metadata only |
| `WAITING_FOR_TOOL` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `tool_call_id` | - | `TOOL_EXECUTION_STARTED` | SlowTaskState | false | true | metadata only |
| `WAITING_FOR_USER_CONFIRMATION` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `confirmation_id` | - | `CONFIRMATION_REQUIRED` | SlowTaskState | false | true | metadata only |
| `FINALIZING` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `source_events` | - | resolved arguments/tool result before commitment | SlowTaskState | false | true | refs only |
| `SLOWTASK_DEGRADED` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `degraded_reason` | `capability_or_tool_ref` | adapter/tool unavailable or degraded | SlowTaskState, AdapterHealthState | false | true | metadata only |
| `SLOWTASK_FAILED` | SlowTask progress events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `failure_reason` | - | unrecoverable failure | SlowTaskState | false | true | metadata only |
| `CONFIRMATION_REQUIRED` | Confirmation events | SlowTask Runtime | SlowTask Runtime | `confirmation_id`, `task_id`, `plan_version`, `task_event_seq`, `confirmation_scope`, `required_for_event_id`, `prompt_ref` | `expires_at_monotonic_ms` | risky semantic/tool/action/user authorization need | SlowTaskState | false | true | prompt refs redacted/synthetic |
| `USER_CONFIRMATION_RECEIVED` | Confirmation events | SlowTask Runtime | SlowTask Runtime | `confirmation_id`, `patch_id`, `task_id`, `plan_version`, `task_event_seq`, `confirmation_signal` | - | `USER_PATCH_INTERPRETED` confirmation/rejection/cancel | SlowTaskState | false | true | no raw text required |
| `CONFIRMATION_ACCEPTED` | Confirmation events | SlowTask Runtime | SlowTask Runtime | `confirmation_id`, `task_id`, `plan_version`, `task_event_seq`, `accepted_scope`, `authorization_ref` | - | `USER_CONFIRMATION_RECEIVED` | SlowTaskState | false | true | authorization ref must not expose secrets |
| `CONFIRMATION_REJECTED` | Confirmation events | SlowTask Runtime | SlowTask Runtime | `confirmation_id`, `task_id`, `plan_version`, `task_event_seq`, `rejection_reason` | - | `USER_CONFIRMATION_RECEIVED` or timeout/cancel/superseded | SlowTaskState | false | true | metadata only |
| `SLOWTASK_CANCEL_REQUESTED` | Cancellation events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `cancel_reason` | `source_user_patch_event_id` | `USER_PATCH_INTERPRETED` cancel/control semantics | SlowTaskState | false | true | metadata only |
| `SLOWTASK_CANCELLED` | Cancellation events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `cancel_reason`, `inflight_tool_policy` | - | accepted cancel and cleanup/cancel events | SlowTaskState | false | true | metadata only |
| `TOOL_EXECUTION_CANCEL_REQUESTED` | Cancellation events | SlowTask Runtime | SlowTask Runtime | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `cancel_reason` | - | plan advance or task cancellation | SlowTaskState, ToolExecutionState | false | true | metadata only |
| `TOOL_CALL_STARTED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `tool_name`, `idempotency_key` | `tool_adapter_id` | current-plan SlowTask action | ToolExecutionState | false | true | no sensitive args inline |
| `TOOL_MANIFEST_LOADED` | Tool events | Tool Executor | Tool Executor | `tool_name`, `tool_adapter_id`, `tool_manifest_version`, `side_effect_class` | `risk_class` | tool preparation | ToolExecutionState | false | true | manifest refs only |
| `TOOL_ARGUMENTS_PARTIAL` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `partial_arguments_ref`, `missing_fields` | - | incomplete SlowTask proposed tool call | ToolExecutionState | false | true | args refs redacted |
| `TOOL_ARGUMENTS_READY` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `resolved_arguments_ref`, `provenance_ref` | - | `ARGUMENTS_RESOLVED` or validated current-plan request | ToolExecutionState | false | true | args refs redacted/minimized |
| `TOOL_PREVIEW_AVAILABLE` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `preview_ref`, `requires_confirmation` | - | ready arguments for previewable action | ToolExecutionState | false | true | preview redacted for shareable fixtures |
| `TOOL_EXECUTION_AUTHORIZED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `authorization_basis` | `confirmation_id` | policy allow or `CONFIRMATION_ACCEPTED` | ToolExecutionState | false | true | authorization ref no secrets |
| `TOOL_EXECUTION_STARTED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `idempotency_key` | `authorization_event_id` | `TOOL_EXECUTION_AUTHORIZED` or allowed read-only action | ToolExecutionState | false | true | no raw secret/tool credential |
| `TOOL_PROGRESS_UPDATED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `progress_type`, `progress_ref` | - | in-flight tool execution | ToolExecutionState | false | true | refs redacted |
| `TOOL_UI_STATE_PATCHED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `ui_patch_id`, `idempotency_key`, `patch_ref` | - | demo backend/UI state mutation | ToolExecutionState | false | true | demo state patch redacted/minimal in shareable fixture |
| `TOOL_RESULT_RECEIVED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `result_status`, `result_ref` | `trust_level`, `source_type` | tool execution completion | ToolExecutionState, SlowTaskState | false | true | result refs redacted/minimized for shareable fixtures |
| `TOOL_EXECUTION_FAILED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `failure_reason`, `retryable` | - | tool execution failure | ToolExecutionState | false | true | no credential payload |
| `TOOL_CALL_RETRYING` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `retry_count`, `retry_reason` | - | retryable tool failure | ToolExecutionState | false | true | metadata only |
| `TOOL_EXECUTION_CANCELLED` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `cancel_request_event_id`, `cancel_status` | - | `TOOL_EXECUTION_CANCEL_REQUESTED` | ToolExecutionState | false | true | metadata only |
| `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` | Tool events | Tool Executor | Tool Executor | `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `blocking_fields`, `source_event_id` | - | missing resolved arguments/provenance | ToolExecutionState, SlowTaskState | false | true | metadata only |
| `TOOL_RESULT_MARKED_STALE` | Tool events | SlowTask Runtime | SlowTask Runtime | `tool_call_id`, `task_id`, `result_plan_version`, `current_plan_version`, `stale_reason` | - | old-plan `TOOL_RESULT_RECEIVED` | SlowTaskState | false | true | metadata only |
| `STALE_EVIDENCE_RECORDED` | Tool events | SlowTask Runtime | SlowTask Runtime | `task_id`, `stale_evidence_ref`, `source_tool_result_event_id` | - | `TOOL_RESULT_MARKED_STALE` | SlowTaskState | false | true | stale refs redacted/minimized |
| `STALE_EVIDENCE_ADOPTED` | Tool events | SlowTask Runtime | SlowTask Runtime | `task_id`, `plan_version`, `task_event_seq`, `stale_evidence_ref`, `source_tool_result_event_id`, `adopted_from_plan_version`, `adoption_mode=adopt_or_rebase`, `adoption_reason`, `adopted_scope`, `adopted_by_event_id` | - | explicit SlowTask adoption/rebase | SlowTaskState | false | true | adopted refs redacted/minimized |
| `SEMANTIC_COMMITMENT_EMITTED` | Commitment / Composer events | SlowTask Runtime | SlowTask Runtime | `commitment_id`, `task_id`, `plan_version`, `task_event_seq`, `source_events` | `commitment_ref` | current-plan completion/confirmation state | SlowTaskState | false | true | commitment refs redacted/minimized in shareable fixtures |
| `SPOKEN_PLAN_EMITTED` | Commitment / Composer events | Composer | Composer | `spoken_plan_id`, `source_progress_event_ids`, `coverage_check_required` | `source_commitment_id`, `truthfulness_check_required` | SemanticCommitment, progress event, or fast output | none | false | true | spoken text redacted/synthetic as needed |
| `COMMITMENT_COVERAGE_CHECK_PASSED` | Commitment / Composer events | Coverage Checker | Coverage Checker | `spoken_plan_id`, `source_commitment_id`, `checked_fields`, `check_result_ref` | - | `SPOKEN_PLAN_EMITTED` | none | false | true | check refs no raw secrets |
| `COMMITMENT_COVERAGE_CHECK_FAILED` | Commitment / Composer events | Coverage Checker | Coverage Checker | `spoken_plan_id`, `source_commitment_id`, `failure_reasons` | - | `SPOKEN_PLAN_EMITTED` | none | false | true | failure refs no raw sensitive values in shareable fixtures |
| `PROGRESS_TRUTHFULNESS_CHECK_PASSED` | Commitment / Composer events | Coverage Checker / ProgressTruthfulnessCheck | Truthfulness Checker | `spoken_plan_id`, `source_progress_event_ids`, `truthfulness_level`, `check_result_ref` | - | `SPOKEN_PLAN_EMITTED` for progress | none | false | true | no raw sensitive content |
| `PROGRESS_TRUTHFULNESS_CHECK_FAILED` | Commitment / Composer events | Coverage Checker / ProgressTruthfulnessCheck | Truthfulness Checker | `spoken_plan_id`, `source_progress_event_ids`, `failure_reasons` | - | `SPOKEN_PLAN_EMITTED` for progress | none | false | true | no raw sensitive content |
| `REPLAY_STARTED` | Trace / replay events | Replay Runtime | Replay Runtime | `replay_id`, `source_trace_ref`, `replay_mode` | `fixture_ref` | replay request | all reducers | true for replay run | true | source refs obey fixture boundary |
| `REPLAY_COMPLETED` | Trace / replay events | Replay Runtime | Replay Runtime | `replay_id`, `result_status`, `state_digest` | `failure_summary_ref` | replay completion | all reducers | true for replay run | true | digest no raw sensitive content |
| `TRACE_WRITE_DEGRADED` | Trace / replay events | Event Journal / Trace Runtime | Trace Runtime | `storage_target`, `degraded_reason` | - | persistence/redaction/export issue | TracePrivacyState | true when trace write degrades | true | metadata only |
| `TRACE_SECRET_REDACTION_APPLIED` | Trace / replay events | Event Journal / Trace Runtime | Trace Runtime | `event_id` or `payload_ref`, `redaction_reason`, `redacted_fields` | - | pre-write or export secret redaction | TracePrivacyState | false | true | MUST NOT include raw secret value |
| `TRACE_WRITE_BLOCKED_SECRET_DETECTED` | Trace / replay events | Event Journal / Trace Runtime | Trace Runtime | `source_module`, `blocked_payload_ref`, `secret_kind`, `blocking_reason` | - | detected secret cannot be safely redacted | TracePrivacyState | false | true | MUST NOT include raw secret value |

## 8. Required Relationship Clarifications

These mappings make the requested relationships explicit while preserving ADR-002 canonical naming.

| Relationship label | Canonical event or event chain | Meaning |
| --- | --- | --- |
| `BARGE_IN_CANDIDATE` | `BARGE_IN_CANDIDATE` | Duplex reports speech/playback overlap with echo, VAD, and barge-in confidence. |
| `INTERRUPT_CANDIDATE` | `INTERRUPT_CANDIDATE` | Interaction Controller converts candidate plus playback/policy state into interrupt candidate. |
| `TTS_TRUNCATE_REQUESTED` | `TTS_TRUNCATE_REQUESTED` | Interaction Controller requests Talker truncate at latest known playback offset. |
| `TTS_TRUNCATED` | `TTS_TRUNCATED` | Talker confirms truncate with actual stop offset. |
| `PLAYBACK_COMMITTED` | `PLAYBACK_COMMITTED` | Talker reports likely emitted playback offset; not semantic acknowledgement. |
| `TURN_INGRESS_COMMITTED` | `TURN_INGRESS_COMMITTED` | Interaction Controller commits accepted input to ASR/Thinker/Router chain. |
| `USER_PATCH_RECEIVED` | `USER_PATCH_RECEIVED` | UserPatch evidence pack arrives bound to current pre-advance plan_version. |
| `USER_PATCH_INTERPRETED` | `USER_PATCH_INTERPRETED` | SlowTask interprets patch against observed plan_version. |
| `PLAN_VERSION_ADVANCED` | `PLAN_VERSION_ADVANCED` | SlowTask advances plan when material change requires replanning. |
| `TOOL_RESULT_RECEIVED` | `TOOL_RESULT_RECEIVED` | Tool Executor reports tool result with original plan binding. |
| `STALE_TOOL_RESULT_RECORDED` | `TOOL_RESULT_RECEIVED` -> `TOOL_RESULT_MARKED_STALE` -> `STALE_EVIDENCE_RECORDED` | Non-canonical label mapped to ADR-002/ADR-004 stale result chain. |
| `SEMANTIC_COMMITMENT_CREATED` | `SEMANTIC_COMMITMENT_EMITTED` | Non-canonical label mapped to ADR-002 canonical commitment event. |
| `SPOKEN_PLAN_CREATED` | `SPOKEN_PLAN_EMITTED` | Non-canonical label mapped to ADR-002 canonical composer event. |

If `*_CREATED` or `STALE_TOOL_RESULT_RECORDED` must become journal event names, ADR-002 must be updated first. [ADR-002, ADR-015]
