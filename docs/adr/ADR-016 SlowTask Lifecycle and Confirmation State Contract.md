# ADR-016 SlowTask Lifecycle and Confirmation State Contract

## Status

accepted

## Context

ADR-004 定义了 `plan_version` 和 stale result policy。ADR-006 定义了 single active SlowTask 和 Router focus。ADR-007 定义了 UserPatch 是 evidence。ADR-005 定义了 demo tool side-effect policy。

这些 ADR 已经确定方向，但仍留下三个实现关键边界：

- SlowTask 状态迁移已有命名，但还没有明确 legal input/output event transitions。
- cancel / pause / confirmation candidates 涉及多个参与者，但 confirmation state 还没有唯一 owner。
- Tool Executor 的 authorization、cancellation、failure、retry、stale handling 需要在 MVP-1 / MVP-2 实现前统一契约。

本 ADR 在不扩大 MVP scope 的前提下关闭这些边界。

## Decision

### 1. Runtime ownership

SlowTask Runtime 拥有：

- `SlowTaskState`
- current `plan_version`
- `task_event_seq`
- current task goal / constraints / resolved arguments
- `confirmation_state`
- `stale_evidence`
- adopted / rebased evidence metadata
- terminal task outcome

Router 只拥有 `TaskFocusState` 和 post-commit routing decisions。Router 可以标注 `task_focus=CANCEL_OR_PAUSE_CANDIDATE`、`ACTIVE_TASK_PATCH`、`AMBIGUOUS` 等，但不得直接 cancel SlowTask、authorize tool、advance `plan_version` 或把 UserPatch 解释成最终任务语义。

Interaction / Turn Controller 拥有 turn ingress 和 playback interruption state。它可以产生 `INTERRUPT_CANDIDATE` / `TTS_TRUNCATE_REQUESTED`，但不拥有 SlowTask cancel、confirmation 或 tool authorization。

Tool Executor 拥有 `ToolExecutionState`、tool manifest validation、argument validation、idempotency、demo backend calls、UI state patch execution、retry/cancel interaction with adapters、tool result normalization。它不得直接 mutate SlowTask state；它只把 tool events 写入 journal。

Composer 只拥有 spoken realization。它可以表达 confirmation prompt 或 progress update，但不能决定 confirmation 是否 accepted。

### 2. MVP SlowTask states

MVP SlowTask states:

- `CREATED`
- `WAITING_FOR_SLOT`
- `PLANNING`
- `EXECUTING`
- `WAITING_FOR_USER_CONFIRMATION`
- `COMPLETED`
- `CANCELLED`
- `FAILED`

MVP 中没有单独 `REPLANNING` state。Replanning 通过 `PLAN_VERSION_ADVANCED` 加 `PLANNING_RESTARTED` / `TASK_REPLANNED` 表达，然后回到 `PLANNING`。

Terminal states:

- `COMPLETED`
- `CANCELLED`
- `FAILED`

一旦 terminal，UserPatch、ToolResult、confirmation event 都不得推进该 task。Late evidence 只能作为 stale/debug 记录。

### 3. State transition table

| current state | input / guard | required output events | next state |
| --- | --- | --- | --- |
| none | `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` | `SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED(to_state=CREATED)`, `PLANNING_STARTED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| `CREATED` | initial goal accepted | `PLANNING_STARTED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| `PLANNING` | evidence sufficient and no tool needed | `EVIDENCE_REVIEWED`, `ARGUMENTS_RESOLVED` if applicable, `FINALIZING` | `PLANNING` until commitment |
| `PLANNING` | required slot / critical argument missing | `EVIDENCE_REVIEWED`, `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `CLARIFICATION_REQUESTED`, `WAITING_FOR_SLOT`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_SLOT)` | `WAITING_FOR_SLOT` |
| `WAITING_FOR_SLOT` | relevant UserPatch arrives | `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`; if material, `PLAN_VERSION_ADVANCED`, `PLANNING_RESTARTED`, `TASK_REPLANNED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` or unchanged |
| any non-terminal | UserPatch materially changes goal / constraints / risk | `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, optional `TOOL_EXECUTION_CANCEL_REQUESTED`, `PLANNING_RESTARTED`, `TASK_REPLANNED`, `SLOWTASK_STATE_CHANGED(to_state=PLANNING)` | `PLANNING` |
| any non-terminal | UserPatch interpreted as `switch_task` | `USER_PATCH_INTERPRETED(interpretation_type=switch_task)`, `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)`, `WAITING_FOR_USER_CONFIRMATION`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)` | `WAITING_FOR_USER_CONFIRMATION` |
| `PLANNING` | ready to call tool and policy allows | `ARGUMENTS_RESOLVED`, `TOOL_MANIFEST_LOADED`, `TOOL_ARGUMENTS_READY`, optional `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `WAITING_FOR_TOOL`, `SLOWTASK_STATE_CHANGED(to_state=EXECUTING)` | `EXECUTING` |
| `PLANNING` | tool action requires confirmation | `CONFIRMATION_REQUIRED`, `WAITING_FOR_USER_CONFIRMATION`, `SLOWTASK_STATE_CHANGED(to_state=WAITING_FOR_USER_CONFIRMATION)` | `WAITING_FOR_USER_CONFIRMATION` |
| `WAITING_FOR_USER_CONFIRMATION` | UserPatch interpreted as confirmation | `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_ACCEPTED`, then authorized action or planning continuation, optional `SLOWTASK_STATE_CHANGED(to_state=PLANNING or EXECUTING)` | `PLANNING` or `EXECUTING` |
| `WAITING_FOR_USER_CONFIRMATION` | UserPatch interpreted as rejection / cancel / timeout | `USER_CONFIRMATION_RECEIVED`, `CONFIRMATION_REJECTED`; optional `SLOWTASK_CANCEL_REQUESTED`, optional `SLOWTASK_STATE_CHANGED(to_state=PLANNING or CANCELLED)` | `PLANNING` or `CANCELLED` |
| `EXECUTING` | current-plan ToolResult arrives | `TOOL_RESULT_RECEIVED`, `EVIDENCE_REVIEWED`; then `FINALIZING`, `PLAN_VERSION_ADVANCED`, `SLOWTASK_DEGRADED`, or `SLOWTASK_FAILED`; `SLOWTASK_STATE_CHANGED` if leaving `EXECUTING` | `PLANNING`, `EXECUTING`, or `FAILED` |
| any non-terminal | old-plan ToolResult arrives | `TOOL_RESULT_RECEIVED`, `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED` | unchanged |
| any non-terminal | SlowTask explicitly adopts/rebases stale evidence | `STALE_EVIDENCE_ADOPTED`, then current-plan `EVIDENCE_REVIEWED` / `ARGUMENTS_RESOLVED` as applicable | unchanged or `PLANNING` |
| any non-terminal | retryable current-plan tool failure | `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, optional `SLOWTASK_DEGRADED` | `EXECUTING` |
| any non-terminal | unrecoverable tool/model failure | `TOOL_EXECUTION_FAILED` or adapter failure event, `SLOWTASK_FAILED`, `SLOWTASK_STATE_CHANGED(to_state=FAILED)` | `FAILED` |
| any non-terminal | UserPatch interpreted as explicit cancel | `USER_PATCH_INTERPRETED(interpretation_type=cancel)`, `SLOWTASK_CANCEL_REQUESTED`, optional `TOOL_EXECUTION_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, `SLOWTASK_STATE_CHANGED(to_state=CANCELLED)` | `CANCELLED` |
| `PLANNING` or `EXECUTING` | final current-plan result ready | `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_STATE_CHANGED(to_state=COMPLETED)` | `COMPLETED` |

每个改变 `SlowTaskState` 的 transition 都必须 emit `SLOWTASK_STATE_CHANGED`。

### 4. Confirmation state contract

`confirmation_state` 由 SlowTask Runtime 拥有。

`CONFIRMATION_REQUIRED` 必须包含：

- `confirmation_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `confirmation_scope`
- `required_for_event_id`
- `prompt_ref`
- `expires_at_monotonic_ms` optional

MVP allowed `confirmation_scope`:

- `DEMO_DESTRUCTIVE_ACTION`
- `TASK_CANCEL`
- `SWITCH_TASK`
- `RISK_ACKNOWLEDGEMENT`
- `FINAL_ARGUMENT_CONFIRMATION`

User confirmation 不得从 raw text 直接接受。它必须经过正常 ingress、Router focus、UserPatch construction、`USER_PATCH_INTERPRETED`。然后 SlowTask 产生：

- `USER_CONFIRMATION_RECEIVED` + `CONFIRMATION_ACCEPTED`
- 或 `USER_CONFIRMATION_RECEIVED` + `CONFIRMATION_REJECTED`

如果 pending confirmation 期间 `plan_version` advance，则该 confirmation 对执行无效。SlowTask 必须 emit `CONFIRMATION_REJECTED(rejection_reason=plan_version_superseded)`，或用新的 `CONFIRMATION_REQUIRED` supersede。

MVP switch-task 使用 cancel-then-spawn：

1. Router 将 new-task candidate 作为 UserPatch control evidence 交给 active SlowTask。
2. SlowTask 拥有 `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)`。
3. accepted 后，SlowTask 通过 `SLOWTASK_CANCEL_REQUESTED(cancel_reason=switch_task_accepted)` 和 `SLOWTASK_CANCELLED` 取消当前 task。
4. 只有 active SlowTask terminal 后，Router 才可为 preserved new-task candidate emit 后续 `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)`。
5. rejected 时，active SlowTask 继续；new-task candidate 不得更新当前 task goal / constraints。

### 5. Tool authorization and side-effect gate

Tool Executor 在 emit `TOOL_EXECUTION_STARTED` 前必须检查：

- tool manifest 已加载，并匹配 `tool_manifest_version`
- `task_id`, `plan_version`, `task_event_seq` 匹配 current SlowTask state
- required arguments 完整，且有 provenance
- side effect policy 被 ADR-005 允许
- stale evidence 未被使用，除非已被 SlowTask adopted / rebased
- required confirmation 有 current-plan `CONFIRMATION_ACCEPTED`
- write/action 有 `idempotency_key`

MVP 中：

- `READ_ONLY`, `DRY_RUN`, low-risk `SANDBOX_WRITE` 可由 policy authorize，无需显式 confirmation。
- `DEMO_DESTRUCTIVE_ACTION` 必须引用 current-plan `CONFIRMATION_ACCEPTED`。
- `EXTERNAL_WRITE`, `EXTERNAL_COMMUNICATION`, `BOOKING_OR_PAYMENT`, real `DELETION` 保持 blocked。

`TOOL_CALL_STARTED` 是 MVP-1 minimal tool-call marker。MVP-2 progressive execution 使用 `TOOL_EXECUTION_STARTED`。如果二者都 emit，必须共享 `tool_call_id`，且 `TOOL_CALL_STARTED` 只是 summary marker，不是第二次执行。

参数缺失或 ambiguous 时，Tool Executor 必须 emit `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`，不得执行工具。

### 6. Tool failure, retry, cancellation, and stale handling

Tool failure:

- Tool Executor emit `TOOL_EXECUTION_FAILED`。
- retryable 时可 emit `TOOL_CALL_RETRYING`。
- SlowTask 决定是否产生 `PLAN_VERSION_ADVANCED`、`SLOWTASK_DEGRADED`、`SLOWTASK_FAILED` 或用户澄清。

Tool cancellation:

- plan_version advance 或 task cancellation accepted 时，SlowTask 决定是否 cancel in-flight tool calls。
- adapter 支持 cancellation 时，emit `TOOL_EXECUTION_CANCEL_REQUESTED`。
- Tool Executor emit `TOOL_EXECUTION_CANCELLED(cancel_status=...)`。
- adapter 不支持 cancellation 时，不得伪造成功；等待 result 并按 stale policy 处理。

Stale result:

- Tool Executor 用原始 `plan_version` 记录 `TOOL_RESULT_RECEIVED`。
- SlowTask 对 old-plan result emit `TOOL_RESULT_MARKED_STALE` 和 `STALE_EVIDENCE_RECORDED`。
- stale evidence 不得改变 current task state，除非 SlowTask emit `STALE_EVIDENCE_ADOPTED` 并记录 adopt/rebase metadata。

## Consequences

正向结果：

- SlowTask lifecycle 可 replay，不需要从自然语言日志推断隐藏状态。
- Router、Interaction Controller、SlowTask、Tool Executor、Composer 的 ownership 不重叠。
- confirmation 和 cancel 不再在多个模块之间漂浮。
- demo destructive actions 有明确 authorization gate。
- retry/cancel/stale behavior 可一致评估。

代价：

- MVP-1 / MVP-2 event 更冗长。
- Tool Executor 必须知道 current-plan 和 confirmation metadata。
- User confirmation 必须经过 UserPatch interpretation，不能走 raw text shortcut。

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

MVP-1 必须验证：

1. SlowTask state replay 覆盖 create、planning、waiting slot、replanning、completed、cancelled、failed。
2. every state transition emits `SLOWTASK_STATE_CHANGED`。
3. UserPatch confirmation / cancel 通过 `USER_PATCH_INTERPRETED` 进入，不走 raw text shortcut。
4. material UserPatch 在 replanning 前 advance `plan_version`。
5. old-plan ToolResult 被 marked stale，且不推进 current state。

MVP-2 必须验证：

1. `DEMO_DESTRUCTIVE_ACTION` 缺 current-plan `CONFIRMATION_ACCEPTED` 时不能执行。
2. resolved arguments 或 provenance 缺失时，Tool Executor blocks execution。
3. tool retry、failure、cancellation-supported、cancellation-unsupported paths 都可 replay。
4. `TOOL_EXECUTION_STARTED` 不得为 blocked real external side-effect classes emit。
5. pending confirmation 在 `plan_version` advance 后 rejected 或 superseded。
6. `SWITCH_TASK` confirmation 使用 cancel-then-spawn，未 accepted 时不得 mutate active task。

## Open Questions

- Confirmation timeout duration 是 product policy，可保持 configurable。
- Future pause/resume task switching 需要 post-MVP ADR。
