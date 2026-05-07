# ADR-006 Router Task Focus and Single Active SlowTask MVP

## Status

accepted

## Context

MVP 阶段 Router 只做快慢系统门控，不做复杂任务 reasoning。系统同时支持闲聊、轻问答、复杂任务和慢任务运行中的用户补充，因此在存在 active SlowTask 时，不能简单地把所有新输入都 patch 到当前任务。

用户可能在慢任务期间：

- 补充当前任务约束
- 闲聊或问轻量问题
- 发起另一个复杂任务
- 取消、暂停或修改当前任务
- 对旁人说话
- 说出无法判断归属的话

如果 Router 缺少 task focus 分类，active SlowTask 会被无关输入污染。

## Decision

MVP 只支持 single active SlowTask。

同一 session 中最多只有一个 active SlowTask 处于非终态：

- `CREATED`
- `WAITING_FOR_SLOT`
- `PLANNING`
- `EXECUTING`
- `WAITING_FOR_USER_CONFIRMATION`

终态包括：

- `COMPLETED`
- `CANCELLED`
- `FAILED`

Router 在有 active SlowTask 时，必须先做 `task_focus` 分类，再产生 RouterDecision。

`TaskFocusState` 成为一等状态，至少包含：

- `active_task_id`
- `foreground_mode`
- `side_conversation_allowed`
- `default_patch_policy`
- `ambiguous_input_policy`
- `last_focus_decision`
- `last_focus_confidence`
- `last_focus_event_id`

`task_focus` 分类包括：

- `ACTIVE_TASK_PATCH`
- `FOREGROUND_CHAT`
- `NEW_TASK_CANDIDATE`
- `CANCEL_OR_PAUSE_CANDIDATE`
- `NON_ASSISTANT`
- `AMBIGUOUS`

分类语义：

- `ACTIVE_TASK_PATCH`
  当前输入明显是在补充、修正、确认或回应 active SlowTask。

- `FOREGROUND_CHAT`
  当前输入是闲聊、轻问答、情绪反馈或与 active SlowTask 无关的短交互。

- `NEW_TASK_CANDIDATE`
  当前输入疑似新的复杂任务，但当前已有 active SlowTask。

- `CANCEL_OR_PAUSE_CANDIDATE`
  当前输入疑似取消、暂停、停止、别做了、换一个等控制意图。

- `NON_ASSISTANT`
  当前输入不应进入任务链路。若 Duplex 已在 pre-commit 阶段拒识，则不会到 Router；此分类主要用于 post-commit 低置信情况、文本输入或后续兼容。

- `AMBIGUOUS`
  当前输入无法可靠判断归属。

默认产品行为：

- 明显闲聊 / 轻问答：brief response，不 patch active task。
- 明显任务补充：发送 UserPatch。
- 疑似新复杂任务：不自动替换 active SlowTask；作为 `NEW_TASK_CANDIDATE` control evidence 进入 active SlowTask 的 UserPatch，由 SlowTask 按 ADR-016 拥有 `SWITCH_TASK` confirmation。
- 疑似取消/暂停：作为 `CANCEL_OR_PAUSE_CANDIDATE` metadata 进入 UserPatch evidence pack，由 SlowTask 按 ADR-016 解释并拥有 confirmation / cancellation state。Interaction Controller 不负责 SlowTask cancel。
- 无法判断：不要 patch，先澄清。
- 非助手输入：忽略或轻量拒识，不进入 SlowTask。

RouterDecision 仍保持 MVP 原集合：

- `FAST_ONLY`
- `SPAWN_SLOW_TASK`
- `PATCH_ACTIVE_SLOW_TASK`
- `IGNORE`

需要澄清、切换任务确认、取消确认等场景，不通过新增 RouterDecision 扩展复杂 reasoning，而是由 Router 产出保守决策和 focus metadata：

- `FAST_ONLY` + clarification prompt request
- `PATCH_ACTIVE_SLOW_TASK` + `task_focus=NEW_TASK_CANDIDATE` + switch-task candidate metadata
- `PATCH_ACTIVE_SLOW_TASK` + `task_focus=CANCEL_OR_PAUSE_CANDIDATE` + control candidate metadata
- `IGNORE` + non-assistant / rejected metadata

Router 不负责最终解释 cancel、goal rewrite、slot update、switch task 或 user confirmation。对于 active task 相关输入，它只构造 UserPatch evidence pack，最终语义解释和 confirmation ownership 属于 SlowTask。

MVP switch-task path:

1. Router detects `NEW_TASK_CANDIDATE` while an active SlowTask exists.
2. Router emits `ROUTER_DECISION_EMITTED(router_decision=PATCH_ACTIVE_SLOW_TASK, task_focus=NEW_TASK_CANDIDATE)` and `TASK_FOCUS_STATE_UPDATED`.
3. UserPatch includes the new-task candidate as non-authoritative control evidence, not as an immediate goal rewrite.
4. SlowTask may emit `CONFIRMATION_REQUIRED(confirmation_scope=SWITCH_TASK)` if switching is plausible.
5. If accepted, MVP switch uses cancel-then-spawn: the active SlowTask moves through ADR-016 cancellation events, then a subsequent `ROUTER_DECISION_EMITTED(router_decision=SPAWN_SLOW_TASK)` may create the new task from the preserved UserPatch evidence pack / `source_evidence_refs`.
6. If rejected, the active SlowTask continues; the candidate is recorded as rejected control evidence and must not alter current task constraints.

MVP 不支持真正 pause/resume SlowTask。`CANCEL_OR_PAUSE_CANDIDATE` 中的 pause 语义只能触发 SlowTask 澄清、拒绝、取消确认或后续 ADR 定义的 future behavior；不得静默实现 background pause/resume。

## Alternatives Considered

1. 有 active SlowTask 时默认全部 patch。
   实现简单，但会污染慢任务，是主要失败模式。

2. Router 直接判断 cancel、goal rewrite、slot update、新任务切换。
   看似智能，但会让 Router 做复杂 reasoning，破坏职责边界。

3. MVP 支持多个并发 active SlowTask。
   更接近长期能力，但会显著增加 task focus、语音指代、打断、确认和 replay 复杂度。

4. 慢任务运行时禁止闲聊和轻问答。
   简单但体验僵硬，不符合 live 语音 Agent 的前台承接目标。

## Consequences

正向结果：

- active SlowTask 不会轻易被闲聊或旁路输入污染。
- Router 保持门控职责，不变成语义任务解释器。
- MVP 可以避免多任务并发带来的焦点复杂度。
- 用户在慢任务期间仍可进行短前台对话。
- 新复杂任务切换成为显式确认，而不是隐式覆盖。

代价：

- Router 需要维护 TaskFocusState。
- 某些真实多任务场景在 MVP 中不能并发执行。
- `AMBIGUOUS` 会增加澄清轮次。
- 需要设计 brief response 与 active SlowTask progress feedback 的优先级。

## Impacted Modules

- Router
- TaskFocusState
- Interaction / Turn Controller
- Thinker
- ASR Adapter
- SlowTask
- UserPatch Pipeline
- Composer
- Event Journal
- Trace / Replay
- Evaluation Harness

## Validation Method

MVP-1 必须验证：

1. 无 active SlowTask 时，复杂任务可触发 `SPAWN_SLOW_TASK`。
2. 有 active SlowTask 时，明显补充约束触发 `PATCH_ACTIVE_SLOW_TASK`。
3. 有 active SlowTask 时，明显闲聊触发 `FAST_ONLY`，且不生成 UserPatch。
4. 有 active SlowTask 时，疑似新复杂任务不会自动 spawn，而是进入 active SlowTask UserPatch control evidence，并由 SlowTask 触发 `CONFIRMATION_REQUIRED(SWITCH_TASK)`。
5. 有 active SlowTask 时，疑似取消/暂停不会直接取消，而是生成 control candidate。
6. `AMBIGUOUS` 输入不会 patch active task。
7. `NON_ASSISTANT` 输入不会进入 SlowTask。
8. replay 能通过 `ROUTER_DECISION_EMITTED` 和 `TASK_FOCUS_STATE_UPDATED` 重建 TaskFocusState 和每次 focus decision。
9. patch misrouting rate 必须能在 eval 中统计。

## Open Questions

- `foreground_mode` 的枚举是否先定义为 `IDLE` / `FAST_RESPONSE` / `SLOWTASK_ACTIVE` / `WAITING_CONFIRMATION`？
- brief response 是否允许打断 SlowTask progress feedback，还是 progress feedback 优先？
- switch-task confirmation prompt 的口语化模板由 Composer 统一生成，还是 SlowTask 提供更完整 `prompt_ref`？
- `AMBIGUOUS` 的澄清话术由 Router metadata 驱动，还是交给 Composer 统一生成？
