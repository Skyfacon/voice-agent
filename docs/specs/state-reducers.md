# State Reducers

Source of truth: frozen ADR Baseline v0.4. This document carries P1-B-002. It is a spec detail, derived from ADR baseline.

Reducers reconstruct runtime state from the canonical event journal. They are deterministic policy/state reducers, not semantic model invocations.

## 1. Reducer Principles

- Reducers consume events ordered by `event_seq` within one session. [ADR-002]
- Reducers MUST NOT call external models, tools, adapters, or clocks during deterministic replay. [ADR-002, ADR-010]
- Reducers MUST use event payloads, causal links, and refs already present in the journal. [ADR-002]
- Reducers MUST be idempotent over a replayed event stream: applying the same ordered stream yields the same state digest. [ADR-002]
- Reducers MUST ignore events outside their ownership unless the event is listed as an input event. [ADR-001, ADR-006, ADR-016]
- Reducers MUST never treat `PLAYBACK_COMMITTED` as semantic acknowledgement or user confirmation. [ADR-001, ADR-002]
- SlowTask-related reducers MUST respect `task_id`, `plan_version`, and `task_event_seq`. [ADR-004, ADR-016]
- Terminal states are sticky unless a future ADR explicitly defines a recovery path. [ADR-016]

## 2. Replay Order

1. Sort by `event_seq` ascending. [ADR-002]
2. Validate the common event envelope.
3. Validate event-specific required fields from `docs/specs/event-registry.md`.
4. Route each event to matching reducers.
5. Apply reducer transition rules.
6. Record ignored or late-event diagnostics in replay metadata, not as new runtime events.
7. Produce a state digest after the final event.

Spec detail, derived from ADR baseline: replay may materialize intermediate snapshots after every event or after configured checkpoints, but final state must be equivalent to full event replay.

## 3. Deterministic Reducer Requirements

- No random ids, timestamps, model calls, network calls, or tool calls may be generated during deterministic replay.
- Missing refs are treated as unavailable payloads, not an instruction to fetch from external systems.
- If an event references an unavailable data-plane artifact, the reducer preserves the ref and marks dependent detail as unavailable.
- Schema validation failures stop strict deterministic replay or mark degraded replay depending on replay mode in `replay-spec.md`.

## 4. Snapshot vs Event Replay Policy

- Event replay is the normative source for correctness. [ADR-002]
- Snapshots may be used as performance optimization only if they include `last_event_seq`, `event_schema_version`, and a state digest over reducer-owned fields.
- A snapshot is valid only when replaying events after `last_event_seq` yields the same final digest as full replay.
- Shareable fixtures should prefer short event streams over opaque snapshots unless the fixture is specifically testing snapshot migration.

## 5. Late Event Handling

Late means an event arrives after a reducer has already seen an event that makes the late event ineligible to affect current state.

- Old-plan ToolResult is not a generic late event; it is handled by stale evidence policy. [ADR-004, ADR-016]
- Terminal SlowTask events are late for task advancement and may be recorded as stale/debug only. [ADR-016]
- Playback progress after `TTS_TRUNCATED` or `PLAYBACK_FINISHED` is ignored for current playback state unless explicitly causally linked as a correction event by a future ADR.
- Adapter health events remain applicable to AdapterHealthState even after individual request failure events.

## 6. Terminal State Rules

- `SlowTaskState` terminal states: `COMPLETED`, `CANCELLED`, `FAILED`. [ADR-016]
- `PlaybackState` terminal span states: `TRUNCATED`, `FINISHED`.
- `InteractionState.turn_phase` terminal per turn is `TURN_COMMITTED`, `WAITING_USER`, or later response phase depending on playback chain; a new turn can open only with a new `turn_id`.
- Once a SlowTask is terminal, UserPatch, ToolResult, confirmation, and tool events cannot advance that task. [ADR-016]
- Terminal-state evidence may still be retained for debug/replay if redaction permits. [ADR-010]

## 7. Reducer Specifications

### InteractionState

| Field | Spec |
| --- | --- |
| owned_by | Interaction Controller. [ADR-001] |
| input_events | `TEXT_INPUT_RECEIVED`, `AUDIO_SPAN_STARTED`, `AUDIO_SPAN_ENDED`, `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`, `LOW_CONFIDENCE_INGRESS`, `TURN_OPENED`, `TURN_HELD`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_INGRESS_COMMITTED`, `BARGE_IN_CANDIDATE`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, `WAITING_USER`. |
| output_state | `turn_phase`, `playback_phase`, `directedness`, `semantic_close`, `current_turn_id`, `current_input_span_id`, `current_audio_span_id`, `current_text_span_id`, `current_playback_span_id`, `last_ingress_outcome`, `last_interaction_event_id`. [ADR-001] |
| invariant_rules | Text input sets `audio_span_id=null`, `directedness=ASSUMED_DIRECTED`, `semantic_close=ASSUMED_CLOSED`; no ASR/Thinker chain before `TURN_INGRESS_COMMITTED`; Interaction Controller is unique owner of turn ingress commit. [ADR-001, ADR-002] |
| ignored_events | Router, SlowTask, Tool, Adapter, Composer, and Trace events except playback/truncate events listed above. |
| late_event_policy | Late `SPEECH_*` or candidate events for a different span do not alter current committed turn; late `TTS_TRUNCATED` without matching `playback_span_id` is ignored for current playback phase. |
| terminal_state_policy | Per-turn commit is final for that turn; new input requires a new `turn_id` or new span. `TTS_TRUNCATED` sets playback phase to `TRUNCATED`; later playback progress on same span is ignored unless ordered before truncate. |
| replay_validation | MVP-0 text and audio acceptance scenarios must reconstruct expected InteractionState; rejected/held spans must not produce semantic chain events. [ADR-001, ADR-002, ADR-012] |

### TaskFocusState

| Field | Spec |
| --- | --- |
| owned_by | Router. [ADR-006] |
| input_events | `ROUTER_DECISION_EMITTED`, `TASK_FOCUS_STATE_UPDATED`, SlowTask terminal summaries as referenced by Router state snapshots. |
| output_state | `active_task_id`, `foreground_mode`, `side_conversation_allowed`, `default_patch_policy`, `ambiguous_input_policy`, `last_focus_decision`, `last_focus_confidence`, `last_focus_event_id`. [ADR-006] |
| invariant_rules | Single active non-terminal SlowTask only; Router decisions are limited to `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`; Router does not cancel, pause, switch, authorize tools, or interpret final UserPatch semantics. [ADR-006, ADR-016] |
| ignored_events | UserPatch interpretation, tool execution, confirmation, playback, adapter, and trace events unless summarized by Router-owned state update. |
| late_event_policy | Router decisions for old turns do not alter `last_focus_*` if a later Router decision already exists; replay preserves event order rather than wall-clock order. |
| terminal_state_policy | When active SlowTask reaches `COMPLETED`, `CANCELLED`, or `FAILED`, the next Router-owned update may clear `active_task_id`; reducer must not infer clearing from SlowTask terminal event unless `TASK_FOCUS_STATE_UPDATED` records it. |
| replay_validation | MVP-1 must reconstruct obvious patch, foreground chat, new-task candidate, cancel/pause candidate, ambiguous, and non-assistant cases. [ADR-006, ADR-012] |

### SlowTaskState

| Field | Spec |
| --- | --- |
| owned_by | SlowTask Runtime. [ADR-016] |
| input_events | `SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED`, `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, `TASK_REPLANNED`, `PLANNING_STARTED`, `PLANNING_RESTARTED`, `WAITING_FOR_SLOT`, `WAITING_FOR_TOOL`, `WAITING_FOR_USER_CONFIRMATION`, `EVIDENCE_REVIEWED`, `AMBIGUITY_DETECTED`, `AMBIGUITY_RESOLVED`, `CLARIFICATION_REQUESTED`, `ARGUMENTS_RESOLVED`, `ARGUMENT_RESOLUTION_PROVENANCE`, `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `TOOL_RESULT_RECEIVED`, `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED`, `STALE_EVIDENCE_ADOPTED`, `CONFIRMATION_REQUIRED`, `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_ACCEPTED`, `CONFIRMATION_REJECTED`, `SLOWTASK_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_DEGRADED`, `SLOWTASK_FAILED`. |
| output_state | Current state in `CREATED`, `WAITING_FOR_SLOT`, `PLANNING`, `EXECUTING`, `WAITING_FOR_USER_CONFIRMATION`, `COMPLETED`, `CANCELLED`, `FAILED`; current `plan_version`; current `task_event_seq`; current goal/constraints refs; resolved arguments refs; confirmation_state; stale_evidence refs; adopted evidence metadata; terminal outcome. [ADR-016] |
| invariant_rules | Every state transition must have `SLOWTASK_STATE_CHANGED`; `plan_version` advances only through `PLAN_VERSION_ADVANCED`; UserPatch is evidence, not direct mutation; SemanticCommitment only from current plan; stale evidence cannot advance current plan unless `STALE_EVIDENCE_ADOPTED` exists. [ADR-004, ADR-007, ADR-016] |
| ignored_events | Interaction, Duplex, Playback, Adapter, and Router events except those causally referenced by SlowTask events. |
| late_event_policy | Old-plan `TOOL_RESULT_RECEIVED` is marked via `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`; late UserPatch/confirmation after terminal state cannot advance task. |
| terminal_state_policy | `COMPLETED`, `CANCELLED`, and `FAILED` are terminal. No UserPatch, ToolResult, confirmation, or tool event may advance terminal task. Late evidence may be debug/stale only. [ADR-016] |
| replay_validation | MVP-1 must replay create, planning, waiting slot, replanning, stale result, completed, cancelled, and failed paths. MVP-2 must replay confirmation/tool authorization/cancel/retry paths. [ADR-012, ADR-016] |

### PlaybackState

| Field | Spec |
| --- | --- |
| owned_by | Talker / Playback. [ADR-003] |
| input_events | `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `PLAYBACK_FINISHED`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, `COMMITMENT_COVERAGE_CHECK_PASSED`, `PROGRESS_TRUTHFULNESS_CHECK_PASSED`. |
| output_state | Current `playback_span_id`, playback phase `NOT_PLAYING`, `PLAYING`, `TRUNCATE_REQUESTED`, `TRUNCATED`, `FINISHED`; latest `playback_offset_ms`; latest committed offset; approved check event id; actual stop offset. |
| invariant_rules | Playback for SemanticCommitment-derived speech requires coverage check pass; progress speech requires truthfulness check pass; `PLAYBACK_COMMITTED` is delivery marker only; truncate keeps candidate offset, request cutoff, and actual stop offset distinct. [ADR-002, ADR-003, ADR-009, ADR-013] |
| ignored_events | Input, Router, UserPatch, SlowTask, Tool, Adapter, and Trace events except approved check events and truncate request. |
| late_event_policy | `PLAYBACK_PROGRESS` after `TTS_TRUNCATED` or `PLAYBACK_FINISHED` on same span is ignored for latest offset; a `TTS_TRUNCATED` for unknown span is ignored for current state but retained in replay diagnostics. |
| terminal_state_policy | `TRUNCATED` and `FINISHED` terminate the current playback span. New playback requires new `playback_span_id`. |
| replay_validation | MVP-0 barge-in scenario must reconstruct playback offsets and truncate state; SLO calculation uses monotonic timestamps and playback offsets. [ADR-003, ADR-012] |

### AdapterHealthState

| Field | Spec |
| --- | --- |
| owned_by | Adapter Registry / Adapter Runtime. [ADR-011] |
| input_events | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `ADAPTER_HEALTHCHECK_FAILED`, `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, `ADAPTER_OUTPUT_VALIDATION_FAILED`, `ADAPTER_OUTPUT_DEGRADED`, `MOCK_ASR_FRAME_EMITTED`, `MOCK_THINKER_FRAME_EMITTED`, adapter output events with `output_mode`. |
| output_state | Capability snapshot ref; per-adapter health status; deployment mode; output mode; missing capabilities; retry/failure counters; latest degradation reason. |
| invariant_rules | Unsupported capabilities are explicit; mock/fallback/degraded/real outputs are distinguishable; schema validation failures do not silently pass downstream; adapter events must not log secrets. [ADR-011] |
| ignored_events | Interaction, Router, SlowTask, Tool, Playback, and Trace events except when they reference adapter degradation as source. |
| late_event_policy | Health events are applied in event_seq order; older health failures do not override later snapshot/health status if a later event supersedes them. |
| terminal_state_policy | Adapter health has no terminal state for the session unless session ends; individual request failures are terminal for that request. |
| replay_validation | MVP-0 mock capability case reconstructs capability snapshot and output modes; MVP-3 adapter failures/retries/degradations are replayable. [ADR-011, ADR-012] |

### TracePrivacyState

| Field | Spec |
| --- | --- |
| owned_by | Trace / Replay Runtime and Privacy / Redaction policy. [ADR-010] |
| input_events | `SESSION_STARTED`, `TRACE_WRITE_DEGRADED`, `TRACE_SECRET_REDACTION_APPLIED`, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`, `REPLAY_STARTED`, `REPLAY_COMPLETED`, events carrying `trace_redaction_level`. |
| output_state | Trace domain configuration, redaction counters, blocked-write counters, latest degraded storage target, replay mode, fixture safety status. |
| invariant_rules | Secrets never enter trace raw; raw audio is local debug opt-in only; shareable/GitHub fixtures are synthetic/redacted/minimal and exclude raw audio, raw trace, secrets, unredacted real user input, and large raw web content. [ADR-010, ADR-015] |
| ignored_events | Runtime semantic events except their `trace_redaction_level` and redaction/export metadata. |
| late_event_policy | Redaction/block events apply to the referenced payload/event regardless of later runtime state; replay records diagnostics if the referenced payload is absent from fixture. |
| terminal_state_policy | Replay run terminal status comes from `REPLAY_COMPLETED`; trace privacy state otherwise persists until `SESSION_ENDED`. |
| replay_validation | MVP-0 local trace safety case verifies raw audio disabled by default, secrets redacted/blocked, and shareable fixture boundaries. [ADR-010, ADR-012] |

## 8. State Digest Format

Spec detail, derived from ADR baseline:

State digest fields:

- `digest_schema_version`
- `source_session_id`
- `last_event_seq`
- `event_schema_version_range`
- `interaction_state_hash`
- `task_focus_state_hash`
- `slowtask_state_hash`
- `playback_state_hash`
- `adapter_health_state_hash`
- `trace_privacy_state_hash`
- `overall_digest`

Hashes are computed over canonical JSON-like normalized state: stable key order, no wall-clock display formatting, no raw secret/audio/text payloads.
