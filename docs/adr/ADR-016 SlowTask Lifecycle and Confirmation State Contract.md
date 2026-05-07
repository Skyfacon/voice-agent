# ADR-016 SlowTask Lifecycle and Confirmation State Contract

## Status

accepted

## Context

ADR-004 defines `plan_version` and stale result policy. ADR-006 defines single active SlowTask and Router focus. ADR-007 defines UserPatch as evidence. ADR-005 defines demo tool side-effect policy. Together they establish the direction, but they leave three implementation-critical seams underspecified:

- SlowTask state transitions are named, but not yet expressed as legal input/output event transitions.
- cancel / pause / confirmation candidates have multiple participants, but no single owner of confirmation state.
- Tool Executor authorization, cancellation, failure, retry, and stale handling need one contract before MVP-1 / MVP-2 implementation.

This ADR closes those contracts without expanding MVP scope.

## Decision

### 1. Runtime ownership

SlowTask Runtime owns:

- `SlowTaskState`
- current `plan_version`
- `task_event_seq`
- current task goal / constraints / resolved arguments
- `confirmation_state`
- `stale_evidence`
- adopted / rebased evidence metadata
- terminal task outcome

Router owns only `TaskFocusState` and post-commit routing decisions. Router may label `task_focus=CANCEL_OR_PAUSE_CANDIDATE`, `ACTIVE_TASK_PATCH`, `AMBIGUOUS`, etc., but it must not directly cancel a SlowTask, authorize a tool, advance `plan_version`, or interpret a UserPatch as final task semantics.

Interaction / Turn Controller owns turn ingress and playback interruption state. It may create `INTERRUPT_CANDIDATE` / `TTS_TRUNCATE_REQUESTED`, but it does not own SlowTask cancel, confirmation, or tool authorization.

Tool Executor owns `ToolExecutionState`, tool manifest validation, argument validation, idempotency, demo backend calls, UI state patch execution, retry/cancel interaction with adapters, and tool result normalization. It must not mutate SlowTask state directly; it reports tool events into the journal.

Composer owns spoken realization only. It may express a confirmation prompt or progress update after coverage / truthfulness checks, but it does not decide whether confirmation was accepted.

### 2. MVP SlowTask states

MVP SlowTask states remain:

- `CREATED`
- `WAITING_FOR_SLOT`
- `PLANNING`
- `EXECUTING`
- `WAITING_FOR_USER_CONFIRMATION`
- `COMPLETED`
- `CANCELLED`
- `FAILED`

There is no separate `REPLANNING` state in MVP. Replanning is represented by `PLAN_VERSION_ADVANCED` plus `PLANNING_RESTARTED` / `TASK_REPLANNED`, then state `PLANNING`.

Terminal states are `COMPLETED`, `CANCELLED`, and `FAILED`. Once terminal, no UserPatch, ToolResult, or confirmation event may advance the task. Late evidence may be recorded as stale evidence for debug only.

### 3. State transition table

| current state | input / guard | required output events | next state |
| --- | --- | --- | --- |
| none | `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` | `SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED(to_state=CREATED)`, `PLANNING_STARTED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| `CREATED` | initial goal accepted | `PLANNING_STARTED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| `PLANNING` | evidence is sufficient and no tool is needed | `EVIDENCE_REVIEWED`, `ARGUMENTS_RESOLVED` if applicable, `FINALIZING` | `PLANNING` until commitment |
| `PLANNING` | required slot / critical argument missing | `EVIDENCE_REVIEWED`, `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `CLARIFICATION_REQUESTED`, `WAITING_FOR_SLOT`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_SLOT)` | `WAITING_FOR_SLOT` |
| `WAITING_FOR_SLOT` | relevant UserPatch arrives | `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`; if material, `PLAN_VERSION_ADVANCED`, `PLANNING_RESTARTED`, `TASK_REPLANNED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` or unchanged if irrelevant |
| any non-terminal | UserPatch materially changes task goal / constraints / risk | `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, optional `TOOL_EXECUTION_CANCEL_REQUESTED`, `PLANNING_RESTARTED`, `TASK_REPLANNED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| any non-terminal | UserPatch interpreted as `switch_task` from `NEW_TASK_CANDIDATE` control evidence | `USER_PATCH_INTERPRETED(interpretation_type=switch_task)`, `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)`, `WAITING_FOR_USER_CONFIRMATION`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)` | `WAITING_FOR_USER_CONFIRMATION` |
| `PLANNING` | ready to call a tool and policy allows | `ARGUMENTS_RESOLVED`, `TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_READY`, optional `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `WAITING_FOR_TOOL`, `SLOWTASK_STATE_CHANGED(to_state=EXECUTING)` | `EXECUTING` |
| `PLANNING` | tool action requires confirmation | `CONFIRMATION_REQUIRED`, `WAITING_FOR_USER_CONFIRMATION`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)` | `WAITING_FOR_USER_CONFIRMATION` |
| `WAITING_FOR_USER_CONFIRMATION` | UserPatch interpreted as confirmation | `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_ACCEPTED`, then authorized action or planning continuation, `SLOWTASK_STATE_CHANGED(to_state=PLANNING or EXECUTING)` if state changes | `PLANNING` or `EXECUTING` |
| `WAITING_FOR_USER_CONFIRMATION` | UserPatch interpreted as rejection / cancel / timeout | `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_REJECTED`; optional `SLOWTASK_CANCEL_REQUESTED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING or CANCELLED)` if state changes | `PLANNING` or `CANCELLED` |
| `EXECUTING` | current-plan ToolResult arrives | `TOOL_RESULT_RECEIVED`, `EVIDENCE_REVIEWED`; then `FINALIZING`, `PLAN_VERSION_ADVANCED`, `SLOWTASK_DEGRADED`, or `SLOWTASK_FAILED` depending on result; `SLOWTASK_STATE_CHANGED` if leaving `EXECUTING` | `PLANNING`, `EXECUTING`, or `FAILED` |
| any non-terminal | old-plan ToolResult arrives | `TOOL_RESULT_RECEIVED`, `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED` | unchanged |
| any non-terminal | SlowTask explicitly adopts or rebases stale evidence into current plan | `STALE_EVIDENCE_ADOPTED`, then current-plan `EVIDENCE_REVIEWED` / `ARGUMENTS_RESOLVED` as applicable | unchanged or `PLANNING` if adoption changes the plan |
| any non-terminal | Tool failure is retryable and current-plan | `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, optional `SLOWTASK_DEGRADED` | `EXECUTING` |
| any non-terminal | Tool/model failure is unrecoverable | `TOOL_EXECUTION_FAILED` or adapter failure event, `SLOWTASK_FAILED`, `SLOWTASK_STATE_CHANGED(to_state=FAILED)` | `FAILED` |
| any non-terminal | UserPatch interpreted as explicit cancel | `USER_PATCH_INTERPRETED(interpretation_type=cancel)`, `SLOWTASK_CANCEL_REQUESTED`, optional `TOOL_EXECUTION_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, `SLOWTASK_STATE_CHANGED(to_state=CANCELLED)` | `CANCELLED` |
| `PLANNING` or `EXECUTING` | final current-plan result is ready | `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)` | `COMPLETED` |

Every transition that changes `SlowTaskState` must emit `SLOWTASK_STATE_CHANGED`.

### 4. Confirmation state contract

`confirmation_state` is owned by SlowTask Runtime.

`CONFIRMATION_REQUIRED` must include:

- `confirmation_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `confirmation_scope`
- `required_for_event_id`
- `prompt_ref`
- `expires_at_monotonic_ms` optional

Allowed `confirmation_scope` values for MVP:

- `DEMO_DESTRUCTIVE_ACTION`
- `TASK_CANCEL`
- `SWITCH_TASK`
- `RISK_ACKNOWLEDGEMENT`
- `FINAL_ARGUMENT_CONFIRMATION`

User confirmation is not accepted from raw text directly. It must enter through normal ingress, Router focus, UserPatch construction, and `USER_PATCH_INTERPRETED`. SlowTask then emits either `USER_CONFIRMATION_RECEIVED` + `CONFIRMATION_ACCEPTED` or `USER_CONFIRMATION_RECEIVED` + `CONFIRMATION_REJECTED`.

If `plan_version` advances while a confirmation is pending, the pending confirmation is invalid for execution. SlowTask must emit `CONFIRMATION_REJECTED(rejection_reason=plan_version_superseded)` or supersede it with a new `CONFIRMATION_REQUIRED`.

For MVP, `SWITCH_TASK` confirmation uses cancel-then-spawn:

- Router must first send the new-task candidate as UserPatch control evidence per ADR-006.
- SlowTask owns `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)`.
- If accepted, SlowTask cancels the current task with `SLOWTASK_CANCEL_REQUESTED(cancel_reason=switch_task_accepted)` and `SLOWTASK_CANCELLED`; any supported in-flight tools follow the normal cancellation path.
- Only after the active SlowTask is terminal may Router emit a subsequent `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` for the preserved new-task candidate from the UserPatch evidence pack / `source_evidence_refs`.
- If rejected, the active SlowTask continues and the new-task candidate must not update current task goal / constraints.

### 5. Tool authorization and side-effect gate

Tool Executor must check all of the following before emitting `TOOL_EXECUTION_STARTED`:

- tool manifest is loaded and matches `tool_manifest_version`
- `task_id`, `plan_version`, `task_event_seq` match current SlowTask state
- required arguments are complete and have provenance
- side effect policy is allowed by ADR-005
- stale evidence has not been used unless adopted / rebased by SlowTask
- required confirmation has a current-plan `CONFIRMATION_ACCEPTED`
- `idempotency_key` is present for any write/action

For MVP, `READ_ONLY`, `DRY_RUN`, and low-risk `SANDBOX_WRITE` may be authorized by policy without explicit confirmation. `DEMO_DESTRUCTIVE_ACTION` must reference current-plan `CONFIRMATION_ACCEPTED`. `EXTERNAL_WRITE`, `EXTERNAL_COMMUNICATION`, `BOOKING_OR_PAYMENT`, and real `DELETION` remain blocked.

`TOOL_CALL_STARTED` is the MVP-1 minimal tool-call marker. MVP-2 progressive execution must use `TOOL_EXECUTION_STARTED`. If both are emitted for compatibility, they must share `tool_call_id`, and `TOOL_CALL_STARTED` is only a summary marker, not a second execution.

If arguments are missing or ambiguous, Tool Executor must emit `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` and must not execute the tool.

### 6. Tool failure, retry, cancellation, and stale handling

Tool failure:

- Tool Executor emits `TOOL_EXECUTION_FAILED`.
- If retryable, Tool Executor may emit `TOOL_CALL_RETRYING`.
- SlowTask decides whether failure causes `PLAN_VERSION_ADVANCED`, `SLOWTASK_DEGRADED`, `SLOWTASK_FAILED`, or user clarification.

Tool cancellation:

- When `plan_version` advances or task cancellation is accepted, SlowTask must decide whether in-flight tool calls should be cancelled.
- If adapter supports cancellation, emit `TOOL_EXECUTION_CANCEL_REQUESTED`.
- Tool Executor must emit `TOOL_EXECUTION_CANCELLED` with `cancel_status`.
- If adapter does not support cancellation, do not fake cancellation; wait for result and apply stale result policy.

Stale result:

- Tool Executor records `TOOL_RESULT_RECEIVED` with the original `plan_version`.
- SlowTask marks old-plan results with `TOOL_RESULT_MARKED_STALE` and `STALE_EVIDENCE_RECORDED`.
- Stale evidence cannot alter current task state unless SlowTask emits canonical `STALE_EVIDENCE_ADOPTED` with adopt / rebase metadata per ADR-004.

## Consequences

Positive:

- SlowTask lifecycle is replayable without inferring hidden state from prose.
- Router, Interaction Controller, SlowTask, Tool Executor, and Composer have non-overlapping state ownership.
- confirmation and cancel no longer float between Router, Interaction Controller, and SlowTask.
- demo destructive actions have a concrete authorization gate.
- tool retry/cancel/stale behavior can be evaluated consistently.

Cost:

- MVP-1 / MVP-2 events become more verbose.
- Tool Executor must know current-plan and confirmation metadata.
- User confirmation requires normal UserPatch interpretation instead of direct text shortcuts.

## Impacted Modules

- SlowTask Runtime
- Router
- TaskFocusState
- UserPatch Pipeline
- Tool Executor
- Demo Backend
- Interaction / Turn Controller
- Composer
- Event Journal
- Trace / Replay
- Evaluation Harness

## Validation Method

MVP-1 must verify:

1. SlowTask state replay matches runtime state across create, planning, waiting slot, replanning, completed, cancelled, and failed paths.
2. every state transition emits `SLOWTASK_STATE_CHANGED`.
3. UserPatch confirmation / cancel enters through `USER_PATCH_INTERPRETED`, not raw text shortcuts.
4. material UserPatch advances `plan_version` before replanning.
5. old-plan ToolResult is marked stale and does not advance current state.

MVP-2 must verify:

1. `DEMO_DESTRUCTIVE_ACTION` cannot execute without current-plan `CONFIRMATION_ACCEPTED`.
2. Tool Executor blocks execution when resolved arguments or provenance are missing.
3. tool retry, failure, cancellation-supported, and cancellation-unsupported paths are all replayable.
4. `TOOL_EXECUTION_STARTED` is never emitted for blocked real external side-effect classes.
5. pending confirmation is rejected or superseded when `plan_version` advances.
6. `SWITCH_TASK` confirmation uses cancel-then-spawn and does not mutate the active task unless accepted.

## Open Questions

- Confirmation timeout duration is product policy and can remain configurable.
- Future pause/resume task switching requires a post-MVP ADR.
