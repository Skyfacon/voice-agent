# ADR-008 ASR / Thinker Evidence Fusion and SlowTask-led Conflict Resolution

## Status

accepted

## Context

ASR 是 text projection 辅助链路，不是唯一语义真相。Thinker 负责语音原生理解、情绪、audio caption、intent/slot hint、SemanticFrame 等。两者可能给出不同的信息，但这种差异不应过早被 Router 或系统规则裁决为“冲突”。

对于复杂任务，最终语义解释权属于 Slow Agent / SlowTask。系统更应该把 ASR、Thinker、Duplex、LiveContext、UserPatch 等证据完整、带来源地交给慢系统，由慢系统结合任务上下文判断：

- 是否真的存在影响任务的歧义或冲突
- 是否可以基于上下文消解
- 是否需要追问用户
- 是否可以形成 resolved arguments
- 是否可以继续执行工具或生成 SemanticCommitment

因此，ASR / Thinker 差异应被建模为 evidence fusion 问题，而不是 Router 层的 conflict arbitration 问题。

## Decision

采用 multi-source evidence pack + SlowTask-led ambiguity/conflict resolution。

ASR、Thinker、Router、UserPatch pipeline 的职责是保留和传递证据，不做最终冲突裁决。

进入 SlowTask 的 evidence 至少应包括：

- ASR final transcript or text projection
- ASR n-best if available
- transcript_hint
- Thinker SemanticFrame
- utterance_summary
- audio_summary
- audio_caption
- emotion
- intent_hint
- slot_hints
- task_like
- complexity_hint
- confidence
- Duplex / Interaction events
- LiveContext
- turn history
- TaskFocusState
- UserPatch authoritative evidence
- UserPatch non-authoritative hypothesis

关键字段必须携带 provenance metadata：

- `field_name`
- `field_value`
- `source`
- `source_event_id`
- `confidence`
- `evidence_ref`
- `normalized_value`
- `alternatives`

`source` 可包括：

- `asr`
- `thinker`
- `user_text`
- `duplex`
- `router`
- `slow_agent`
- `tool_result`
- `frontend_context`
- `live_context`

Router 的职责：

- 不判断 ASR 与 Thinker 谁对。
- 不产出最终 conflict verdict。
- 不选择字段 winner。
- 可以保守标注 `evidence_uncertainty`、`low_confidence_input`、`needs_slowtask_review_candidate`。
- 对复杂任务或 active SlowTask patch，将 evidence pack 交给 SlowTask。
- 对轻量 FAST_ONLY 场景，避免承诺不确定关键字段。

SlowTask 的职责：

- 审阅多源 evidence。
- 判断是否存在影响任务的歧义、冲突或缺槽。
- 基于上下文消解可消解的不一致。
- 对不可消解或高影响歧义发起澄清。
- 形成 resolved arguments。
- 在进入工具执行或 SemanticCommitment 前记录解析依据。

SlowTask 应输出结构化内部事件：

- `EVIDENCE_REVIEWED`
- `AMBIGUITY_DETECTED`
- `AMBIGUITY_RESOLVED`
- `CLARIFICATION_REQUESTED`
- `ARGUMENTS_RESOLVED`
- `ARGUMENT_RESOLUTION_PROVENANCE`
- `INSUFFICIENT_EVIDENCE_FOR_ACTION`

这些事件均为 ADR-002 canonical MVP-1 / MVP-2 event registry 的一部分，必须携带 `task_id`、`plan_version`、`task_event_seq` 和 source evidence references。

Tool Executor guardrail：

Tool Executor 不解决 ASR/Thinker 差异，但必须阻止关键参数未解析的执行。

对于 demo tool 和 future real tool，执行前必须检查：

- 是否存在 SlowTask 明确给出的 resolved arguments
- 必要参数是否完整
- 参数是否绑定 provenance
- 当前 `plan_version` 是否匹配
- 是否满足该 tool 的确认策略
- 是否符合 ADR-005 side effect policy
- 是否满足 ADR-016 tool authorization gate

如果缺少 resolved arguments 或关键参数不明确，Tool Executor 必须拒绝执行，并记录：

- `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`
- blocking reason
- missing or ambiguous fields

该 blocked event 不得被视为 tool failure retry；它是 SlowTask 缺证据 / 缺参数路径，后续必须由 `CLARIFICATION_REQUESTED`、`ARGUMENTS_RESOLVED` 或 task failure/degraded event 解释。

关键字段包括但不限于：

- 时间 / 日期 / 时区
- 地点 / 目的地 / 出发地
- 金额 / 价格 / 数量
- 人名 / 联系人 / 收件人
- 账号 / 身份 / 公司 / 组织
- 订单 / 票务 / 预订参数
- 发送 / 删除 / 提交 / 支付 / 下单 / 取消
- 用户确认、否认、取消、改口类话语
- 任何高 side_effect 工具的关键参数

对于 webSearch / RAG / ToolResult 等外部内容，其证据仍需 provenance，但不可信边界由 ADR-014 进一步定义。

## Alternatives Considered

1. Router 做字段级 conflict detection 和 arbitration。
   被拒绝。Router 只做快慢系统门控，不应变成语义仲裁器。

2. 系统规则检测所有关键字段冲突并强制确认。
   安全但过度机械，会打断很多可由上下文自然消解的场景。

3. 永远信 Thinker。
   保留语音理解优势，但可能过度推断，且无法解释 ASR 差异。

4. 永远信 ASR。
   便于文本处理，但违背 ASR 辅助链路定位，且无法利用语音原生理解。

5. 不保留多源 evidence，只传 SlowTask 一个综合文本。
   接口简单，但 SlowTask 无法判断歧义来源，replay 和 eval 也失去依据。

## Consequences

正向结果：

- 符合“复杂任务最终语义权归慢系统”的架构原则。
- Router 保持简单门控，不做复杂 reasoning。
- SlowTask 可以用上下文自然消解歧义，减少不必要追问。
- 工具执行仍有硬 guardrail，避免未解析关键参数造成误操作。
- replay 可以审计 SlowTask 如何从 evidence 到 resolved arguments。

代价：

- SlowTask prompt / structured output 要更强。
- Tool Executor 需要检查 resolved arguments，而不是直接执行模型给出的原始字段。
- 若 SlowTask 能力不足，可能漏判歧义，因此 eval 必须覆盖。
- 轻量 FAST_ONLY 场景仍需谨慎，不能承诺不确定关键字段。

## Impacted Modules

- ASR Adapter
- Thinker Adapter
- SemanticFrame
- ASRFrame
- UserPatch Pipeline
- Router
- SlowTask
- Tool Executor
- Confirmation Flow
- Composer
- Event Journal
- Trace / Replay
- Evaluation Harness
- Untrusted External Content Boundary

## Validation Method

MVP-1 / MVP-2 必须验证：

1. ASRFrame、SemanticFrame、UserPatch 都能携带 provenance。
2. Router 不选择 ASR/Thinker winner。
3. Router 可标注 uncertainty，但不产出最终 conflict verdict。
4. SlowTask 收到完整 evidence pack。
5. SlowTask 能产生 `EVIDENCE_REVIEWED`。
6. 明显歧义场景下，SlowTask 能产生 `CLARIFICATION_REQUESTED`。
7. 可由上下文消解的差异，SlowTask 能产生 `AMBIGUITY_RESOLVED`。
8. 工具执行前必须存在 `ARGUMENTS_RESOLVED` 或等价 current-plan resolved arguments。
9. 缺少关键参数时，Tool Executor 产生 `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`。
10. resolved arguments 必须包含 provenance。
11. blocked insufficient arguments 不能产生 `TOOL_EXECUTION_STARTED`。
12. replay 能重建 evidence 到 ambiguity decision 到 resolved arguments / clarification 的路径。
13. eval 能统计 ambiguity detection、clarification rate、wrong resolution rate。

## Open Questions

- MVP-1 中 SlowTask ambiguity resolution 是 mock rule-based，还是由 Slow LLM structured output 实现？
- FAST_ONLY 轻问答中是否需要一个简化版 uncertainty guardrail？
- provenance 是否需要字段级 normalized value，例如日期统一成 ISO format？
- SlowTask 漏判歧义时，eval 如何标注 wrong resolution？
