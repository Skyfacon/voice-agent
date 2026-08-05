# ADR-013 Truthful Progress Feedback

## Status

accepted

## Context

live 语音 Agent 需要在长任务执行时提供中间态反馈，让用户感知系统一直在工作。Thinker-as-Composer 可以把 SlowTask 中间状态融合成自然语音反馈，保持人设和语气一致。

但进度反馈很容易变成安抚式幻觉。例如系统实际只是在等待工具返回，却说“快好了”；工具失败后仍说“已经查到了”；尚未执行 demo action 却说“我已经处理完了”。这会破坏用户信任，也会影响 trace/replay 的可验证性。

因此，进度反馈必须由真实状态事件驱动，不能由 Composer 或 Thinker 自行编造。

## Decision

Progress feedback must be grounded in actual state events.

Thinker-as-Composer 只能基于以下事件或状态生成进度话术：

- `PLANNING_STARTED`
- `PLANNING_RESTARTED`
- `WAITING_FOR_SLOT`
- `TOOL_MANIFEST_LOADED`
- `TOOL_ARGUMENTS_PARTIAL`
- `TOOL_ARGUMENTS_READY`
- `TOOL_EXECUTION_STARTED`
- `TOOL_PROGRESS_UPDATED`
- `TOOL_CALL_RETRYING`
- `WAITING_FOR_TOOL`
- `TOOL_UI_STATE_PATCHED`
- `WAITING_FOR_USER_CONFIRMATION`
- `FINALIZING`
- `SLOWTASK_DEGRADED`
- `SLOWTASK_FAILED`
- `SEMANTIC_COMMITMENT_EMITTED`

以上名称均是 ADR-002 canonical event registry 中的 journal event name，不是自由文本标签。若实现只持有 enum state 而没有对应 journal event，不得把它作为 spoken progress 的事实依据。

Thinker-as-Composer 可以表达：

- 当前正在规划
- 正在等待某个工具结果
- 正在搜索 / 查询 / 读取
- 正在整理结果
- 需要用户补充信息
- 已完成 demo UI state patch
- 工具失败，正在重试或降级
- 当前需要确认
- 最终结果已准备好

Thinker-as-Composer 不允许无证据表达：

- “快好了”
- “马上完成”
- “已经找到了”但没有 tool result
- “已经完成”但没有 final commitment 或 UI state patch
- “正在处理你的请求”但没有 active task/progress event
- “我已经执行了”但只是 dry-run 或 preview
- “不用担心，没问题”这类无事实依据的风险安抚

Progress feedback 必须绑定：

- `progress_event_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `source_state_event_ids`
- `progress_type`
- `truthfulness_level`
- `spoken_plan_id` if spoken
- `created_by_event_id`

`truthfulness_level` 至少包括：

- `STATE_GROUNDED`
- `ESTIMATE_WITH_BASIS`
- `STYLE_ONLY_ACK`
- `UNSUPPORTED_BLOCKED`

MVP 默认只允许：

- `STATE_GROUNDED`
- `STYLE_ONLY_ACK`

`ESTIMATE_WITH_BASIS` 作为未来能力保留，例如基于工具返回进度百分比或历史平均耗时预测。没有明确依据时不得使用。

SlowTask progress cadence：

- SlowTask first progress feedback: <= 2s
- SlowTask progress cadence: every 5-10s when still working
- 不应重复播报完全相同内容
- 如果状态未变化，可以使用简短 grounded acknowledgement，例如“我还在等查询结果”
- 如果用户正在说话或 assistant 被打断，应尊重 InteractionState，不强行播报

Progress feedback 与 SpokenPlan：

- Thinker-as-Composer 负责把 progress event 转成 SpokenPlan。
- SpokenPlan 必须保留 progress_type 和 source_state_event_ids。
- MVP-2 默认使用独立 `ProgressTruthfulnessCheck` 阻止 unsupported progress；最终 SemanticCommitment 表达仍使用 `CommitmentCoverageCheck`。实现可以共享校验库，但 journal event 必须能区分 `COMMITMENT_COVERAGE_CHECK_PASSED` / `FAILED` 和 `PROGRESS_TRUTHFULNESS_CHECK_PASSED` / `FAILED`。
- ProgressTruthfulnessCheck 通过时必须记录 `PROGRESS_TRUTHFULNESS_CHECK_PASSED`，该事件必须引用 `spoken_plan_id`，并由 Talker 的 `PLAYBACK_SPAN_STARTED.approved_check_event_id` 或 playback causal chain 引用。
- Talker 只能播放已通过 ProgressTruthfulnessCheck 的 progress SpokenPlan；失败时必须记录 `PROGRESS_TRUTHFULNESS_CHECK_FAILED` 且不得播放。

## Alternatives Considered

1. 允许 Thinker 自由生成安抚式进度。
   表达自然，但容易编造状态。

2. 只在最终结果时回复，不做中间反馈。
   最安全，但长任务体验差，不符合产品目标。

3. 所有进度都模板化。
   安全但僵硬，可以用于高风险状态，低风险 demo 不必完全模板化。

4. 由 Router 生成进度反馈。
   Router 不负责慢任务状态和表达，不适合作为进度话术来源。

## Consequences

正向结果：

- 用户感知到系统在工作，但不会被虚假进度误导。
- replay 可以验证每句话对应的状态来源。
- Thinker-as-Composer 仍可保留人设风格，但不能编造事实。
- 工具失败、等待、降级都能被诚实表达。
- 与 development SLO 的 progress cadence 可统一度量。

代价：

- 需要定义 progress event schema。
- Thinker-as-Composer 的表达自由度受限。
- 某些状态反馈可能比“快好了”更克制。
- 需要额外 ProgressTruthfulnessCheck 或并入 CoverageCheck。

## Impacted Modules

- SlowTask
- Tool Executor
- Thinker-as-Composer
- SpokenPlan
- CommitmentCoverageCheck / ProgressTruthfulnessCheck
- Talker
- Interaction / Turn Controller
- Event Journal
- Trace / Replay
- Evaluation Harness
- Frontend Demo

## Validation Method

MVP-2 必须验证：

1. SlowTask 开始规划后可产生 grounded progress。
2. Tool execution started 后可以表达正在执行。
3. Waiting for tool 时可以表达等待结果。
4. Tool failure 后不得表达成功。
5. Dry-run / preview 不得表达为真实完成。
6. `TOOL_UI_STATE_PATCHED` 后才可表达 demo UI action 已完成。
7. 无 active task 时不得生成任务进度反馈。
8. progress feedback 必须绑定 source_state_event_ids。
9. unsupported progress phrase 被 check 阻止。
10. replay 能验证 progress spoken text 与状态事件对应。
11. progress cadence 可以被 event journal 统计。
12. progress safety pass 记录为 `PROGRESS_TRUTHFULNESS_CHECK_PASSED` 并可追溯到 playback。
13. progress safety failure 记录为 `PROGRESS_TRUTHFULNESS_CHECK_FAILED`，不得复用 commitment coverage failure 混淆原因。

## Open Questions

- “我先看一下”这类低承诺 filler 是否归为 `STYLE_ONLY_ACK`？
- frontend 是否也展示 progress event，还是只用于语音反馈？
- 重复等待状态下，最多多久播报一次避免打扰？

## ADR-018 Accepted Addendum

`SlowToFastHandoffV1` binds `task_id`, `plan_version`, and `task_event_seq`.
Only current grounded progress can produce a handoff. Coalescing cannot
manufacture progress. Response Arbiter disposition is replayable.
