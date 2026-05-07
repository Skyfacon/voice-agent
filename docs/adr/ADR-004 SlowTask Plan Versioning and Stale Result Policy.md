# ADR-004 SlowTask Plan Versioning and Stale Result Policy

## Status

accepted

## Context

SlowTask 会接收用户增量 UserPatch、执行 ToolCall、等待 ToolResult，并最终输出 SemanticCommitment。用户补充、工具失败、目标变化、风险变化都会触发重新规划并更新 `plan_version`。如果工具结果和用户补充并发到达，旧 plan 的结果可能污染当前任务。

## Decision

所有 SlowTask 相关关键事件必须绑定：

- `task_id`
- `plan_version`
- `task_event_seq`
- `caused_by_event_id`

适用事件包括：

- `UserPatch`
- `ToolCall`
- `ToolResult`
- `SlowTaskInternalUpdate`
- `SemanticCommitment`
- `PlanVersionAdvanced`
- `ConfirmationRequired` / `ConfirmationAccepted` / `ConfirmationRejected`
- `ToolExecutionCancelRequested` / `ToolExecutionCancelled`

`task_event_seq` 是 task 内单调递增序号，用于补充 session-level `event_seq`，保证单个 SlowTask 内可重放、可审计。

SlowTask lifecycle、confirmation ownership、tool authorization gate、cancel / retry / failure transition 由 ADR-016 统一定义；本文只定义 `plan_version` 一致性和 stale evidence policy。

UserPatch plan_version semantics：

1. `USER_PATCH_RECEIVED` 绑定 patch 到达时 SlowTask 的 current `plan_version`，即 pre-advance version。
2. UserPatch 本身是 evidence pack，不是新 plan，也不能直接修改 task goal、slot、constraint 或 task state。
3. `USER_PATCH_INTERPRETED` 必须 against `observed_plan_version` / `interpreted_against_plan_version` 解释。
4. 只有当 patch materially changes task state 时，才产生 `PLAN_VERSION_ADVANCED`。
5. 并不是每个 UserPatch 都必然 advance `plan_version`。
6. irrelevant / foreground chat / non-task patch 不 advance `plan_version`。

固定事件顺序：

1. `USER_PATCH_RECEIVED(plan_version=N)`
2. `USER_PATCH_INTERPRETED(interpreted_against_plan_version=N)`
3. optional `PLAN_VERSION_ADVANCED(from_plan_version=N, to_plan_version=N+1)`
4. optional canonical `TASK_REPLANNED(plan_version=N+1)` / `PLANNING_RESTARTED(plan_version=N+1)`

当 UserPatch interpretation、tool_error、goal_changed、risk_changed 触发重规划时：

- 生成 `PLAN_VERSION_ADVANCED`
- 记录 `from_plan_version`
- 记录 `to_plan_version`
- 记录 `planning_reason`
- 若由 UserPatch 触发，记录 `caused_by_user_patch_event_id`
- 更新 current `plan_version`
- 使用 `supersedes_event_id` 指向被废弃或替代的规划事件

旧 `plan_version` 的 `ToolResult` 默认处理为：

- 标记 `TOOL_RESULT_MARKED_STALE`
- 写入 `stale_evidence`
- 不得自动推进 current plan
- 不得直接生成新的 SemanticCommitment

如果 Slow Agent 判断旧结果仍可复用，必须显式 adopt / rebase，并记录：

- canonical `STALE_EVIDENCE_ADOPTED`
- `adopted_from_plan_version`
- `adoption_mode=adopt_or_rebase`
- `adoption_reason`
- `adopted_by_event_id`
- adopted evidence 的范围

in-flight ToolCall 策略：

- 如果 adapter 支持 cancellation，则在 plan_version advance 后发送 `TOOL_EXECUTION_CANCEL_REQUESTED`。
- 如果 adapter 不支持 cancellation，则等待结果返回后按 stale_result_policy 处理。
- Tool Executor 必须用 `TOOL_EXECUTION_CANCELLED(cancel_status=...)` 记录 cancellation 结果。
- 不支持 cancellation 时不得伪造 cancellation success；旧结果返回后必须进入 stale_result_policy。
- cancellation 失败不自动推进 current plan；SlowTask 必须显式决定是 `SLOWTASK_DEGRADED`、`SLOWTASK_FAILED`、继续等待旧结果，还是触发 `PLAN_VERSION_ADVANCED(planning_reason=tool_cancel_failed)`。

SemanticCommitment 只能基于 current `plan_version` 输出。若 commitment 使用了 adopted stale evidence，必须在 commitment metadata 中标记来源。

## Alternatives Considered

1. 最新结果覆盖当前状态。
   实现简单，但旧 ToolResult 可能污染新计划，风险不可接受。

2. plan_version advance 后直接丢弃旧结果。
   安全，但浪费可复用证据，也不利于 debug。

3. 锁住 SlowTask，等待所有 in-flight ToolCall 完成后才接收 UserPatch。
   一致性简单，但破坏 live 补料体验。

4. 允许 Slow Agent 自然语言判断是否复用旧结果，不结构化记录。
   灵活，但 replay 和审计无法验证。

## Consequences

正向结果：

- 用户补充不会被旧工具结果覆盖。
- replay 能解释每次计划变更和旧结果处理。
- 不支持 cancellation 的 adapter 仍可安全接入。
- stale evidence 可以被显式复用，但不会偷渡进 current plan。

代价：

- SlowTask 状态机和 event schema 更复杂。
- Tool executor 必须知道发起调用时的 `plan_version`。
- Slow Agent adoption/rebase 需要结构化输出，不只是自然语言解释。
- 测试需要覆盖并发 UserPatch 与 ToolResult 的交错顺序。

## Impacted Modules

- SlowTask
- Slow Agent Adapter
- Tool Executor
- UserPatch Pipeline
- Router
- Event Journal
- Trace / Replay
- SemanticCommitment
- Model Adapter Capability Contract

## Validation Method

MVP-1 必须验证：

1. `USER_PATCH_RECEIVED` 绑定 patch 到达时的 current `plan_version`，即 pre-advance version。
2. `USER_PATCH_INTERPRETED` against observed `plan_version` 解释。
3. 只有 materially changes task state 的 patch 才触发 `PLAN_VERSION_ADVANCED`。
4. irrelevant / foreground chat / non-task patch 不推进 `plan_version`。
5. `PLAN_VERSION_ADVANCED` 必须记录 `from_plan_version`、`to_plan_version`、`planning_reason`，若由 UserPatch 触发还必须记录 `caused_by_user_patch_event_id`。
6. ToolCall 绑定发起时的 `plan_version`。
7. 旧 `plan_version` 的 ToolResult 返回后进入 `stale_evidence`。
8. stale ToolResult 不推进 SlowTask current state。
9. Slow Agent 显式 adopt / rebase 旧结果时，必须产生 `STALE_EVIDENCE_ADOPTED`，记录 `adopted_from_plan_version`、`adoption_mode`、`adoption_reason` 和 `adopted_scope`。
10. SemanticCommitment 的 `plan_version` 必须等于 current `plan_version`。
11. replay 后 SlowTask current state、stale_evidence、adopted evidence 与原运行一致。
12. adapter 支持 cancellation 时，plan_version advance 后产生 `TOOL_EXECUTION_CANCEL_REQUESTED` 和对应 `TOOL_EXECUTION_CANCELLED`。
13. adapter 不支持 cancellation 时，不产生 fake cancelled success；旧 ToolResult 返回后按 stale policy 处理。

## Open Questions

- `task_event_seq` 是由 SlowTask runtime 分配，还是由 event journal 派生？
- stale_evidence 的默认保留范围和 TTL 是多少？
- adopted stale evidence 是否允许跨多个 plan_version 继续传递？
