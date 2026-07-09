# ADR-009 SemanticCommitment and Thinker-as-Composer Contract

## Status

accepted

## Context

Slow Agent / SlowTask 负责复杂任务的最终语义解释和 SemanticCommitment。系统还需要把快系统轻量输出、慢系统中间状态、确认项和最终结果转成 SpokenPlan，再交给 Talker 表达。

为了保持语音 Agent 的人设、语气、风格和情绪一致性，MVP 允许由快系统 Thinker / LALM 承担 Composer role。也就是说，Thinker 不仅可以负责前台承接和轻量回复，也可以在 Composer role 下，把 SlowTask 的中间结果和最终 SemanticCommitment 融合成适合 spoken delivery 的 SpokenPlan。

但这只是实现复用，不是职责合并。Thinker 在 Composer role 下不能重新解释复杂任务事实，不能覆盖 SlowTask 的语义承诺，也不能改写工具状态、风险提示、确认状态或关键事实。

因此需要明确：SemanticCommitment 是复杂任务最终事实源；Thinker-as-Composer 只做 spoken realization 和风格融合。

## Decision

Composer 是一个架构角色，不要求独立模型或独立服务。MVP 可以由 Thinker / LALM 实现 Composer role。

同一个 Thinker / LALM 在系统中至少有两种 role：

1. `Thinker-as-Fast-System`
   负责前台承接、闲聊、轻问答、语音理解 hint、SemanticFrame、情绪/audio caption/intent hint/slot hint。

2. `Thinker-as-Composer`
   负责消费 SlowTask progress events、SemanticCommitment、InteractionState、response_style_hint、persona/style config，输出 SpokenPlan。

二者可复用同一个模型服务，但必须在调用契约、输入范围、输出 schema 和权限边界上区分。

ADR-017 进一步把低延迟前台回答收束为 `Fast Interaction Adapter` role。该 role 可以复用 Thinker / LALM provider，但必须使用独立 prompt profile 和 schema，在一次调用中输出 route evidence、foreground act 和 candidate reply。低风险 foreground reply 可以绕过 SemanticCommitment，但必须先通过 ADR-017 Fast Foreground Gate；未通过 gate 的 candidate 不得进入 SpokenPlan、Talker 或用户可见 UI。

复杂任务、工具结果、confirmation prompt、current-plan facts 和 SlowTask progress 仍由本 ADR 的 SemanticCommitment / Thinker-as-Composer / coverage check 边界保护。Fast foreground reply 不得改写或替代 SemanticCommitment。

SemanticCommitment 是复杂任务最终事实源，至少包含：

- `commitment_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `source_events`
- `task_status`
- `final_result`
- `key_facts`
- `immutable_facts`
- `must_say_fields`
- `forbidden_rewrite_fields`
- `risk_warnings`
- `need_confirmation`
- `confirmation_prompt`
- `resolved_arguments`
- `tool_result_refs`
- `demo_tool_status`
- `untrusted_evidence_refs`
- `response_style_hint`
- `allowed_style_transformations`
- `created_by_event_id`

Thinker-as-Composer 的输入必须受控，允许消费：

- SemanticCommitment
- SlowTask progress events
- truthful progress state
- resolved arguments
- tool status
- demo tool UI state
- confirmation state
- InteractionState
- TaskFocusState summary
- user emotion / speaking style hint
- persona / style config
- response_style_hint

`confirmation state` is owned by SlowTask Runtime per ADR-016. Thinker-as-Composer may express `CONFIRMATION_REQUIRED` prompts and accepted / rejected confirmation outcomes, but it must not infer confirmation directly from raw user text or authorize a tool.

Thinker-as-Composer 不应直接自由消费未筛选的 raw tool output、未归因 webSearch 文本或旧 plan_version stale evidence。若需要使用这些内容，必须通过 SemanticCommitment 或 SlowTask progress event 归一化后进入。

SpokenPlan 至少包含：

- `spoken_plan_id`
- `source_commitment_id`
- `source_progress_event_ids`
- `source_fast_foreground_output_id` optional
- `source_events`
- `text`
- `emotion`
- `speaking_style`
- `interruptible`
- `priority`
- `source`
- `immutable_fields`
- `coverage_check_required`

Thinker-as-Composer 允许：

- 保持统一人设和风格
- 调整口语表达
- 缩短或分段
- 调整语气、节奏、情绪
- 融合当前对话语境和用户情绪
- 将结构化结果转成自然语音
- 组织中间状态和最终结果的表达顺序
- 对低风险事实做轻微口语化

Thinker-as-Composer 不允许：

- 修改 `immutable_facts`
- 删除 `must_say_fields`
- 改写 `forbidden_rewrite_fields`
- 改变关键数字、日期、地点、人名、联系人、状态、否定词
- 删除风险提示
- 把待确认内容说成已执行
- 把 demo dry-run 说成真实外部操作已完成
- 把 demo backend action 说成真实设备 / 真实外部系统已执行
- 把 untrusted external evidence 说成系统事实
- 使用 stale_evidence 作为当前事实，除非已被 SlowTask adopt/rebase
- 重新规划工具调用或改变 resolved arguments

Thinker-as-Composer 输出 SpokenPlan 后，必须执行 `CommitmentCoverageCheck`。即使 Composer 由 Thinker/LALM 实现，也不能依赖同一个模型的自我声明作为验证机制。

`CommitmentCoverageCheck` 必须检查：

- `must_say_fields` 是否覆盖
- `immutable_facts` 是否保留
- `forbidden_rewrite_fields` 是否被改写
- key numbers / dates / locations / names 是否一致
- risk warning 是否保留
- `source_commitment_id` 是否一致
- demo tool / dry-run 状态是否被正确表达
- confirmation required 的内容是否仍保持待确认语义
- untrusted external content 是否被正确 attribution 或降格表达
- stale evidence 是否未被直接表达为 current fact

高风险内容优先模板化，低风险内容可以自然口语化。

若 CoverageCheck 失败：

- 不得发送给 Talker
- 记录 `COMMITMENT_COVERAGE_CHECK_FAILED`
- Thinker-as-Composer 必须重试生成或退回模板化表达
- 多次失败后进入 degraded response

若 CoverageCheck 通过：

- 必须记录 `COMMITMENT_COVERAGE_CHECK_PASSED`
- `COMMITMENT_COVERAGE_CHECK_PASSED` 必须引用 `spoken_plan_id`
- Talker 的 `PLAYBACK_SPAN_STARTED.approved_check_event_id` 必须引用该通过事件或其 `check_result_ref`
- Talker 只能播放已通过检查的 SemanticCommitment-derived SpokenPlan

对于 ADR-017 已通过 Fast Foreground Gate 的低风险 fast foreground output，系统可以直接展示文本，或将其包装成 `SPOKEN_PLAN_EMITTED(source=fast_foreground)` 交给 Talker。该路径不需要 `CommitmentCoverageCheck`，但必须保留 `FOREGROUND_ACT_GATE_PASSED` / `FOREGROUND_OUTPUT_COMMITTED` 因果链，且不得表达复杂任务事实、tool status、confirmation state 或 current-plan facts。

## Alternatives Considered

1. Composer 作为独立模型 / 独立服务。
   职责清晰，但可能造成人设和语气不一致，也增加系统复杂度。可以作为后续演进，不作为 MVP 强制要求。

2. Thinker 直接自由融合 SlowTask 输出和上下文，不做 CoverageCheck。
   表达自然，但会把事实权威悄悄转移回快系统，风险不可接受。

3. Slow Agent 直接输出最终口语文本，不设 Composer role。
   减少一层，但会混合 reasoning 和表达职责，也难以统一 Talker style control。

4. Talker 直接消费 SemanticCommitment。
   Talker 应负责语音合成，不应承担结构化事实到口语表达的转换。

5. Composer 完全模板化。
   最安全，但表达僵硬，不利于 live 语音 Agent 的人设一致性和自然交互。

## Consequences

正向结果：

- 复用 Thinker/LALM 保持语音 Agent 的人设和风格一致。
- 慢系统事实权威不转移给快系统。
- 高风险内容仍有结构化覆盖检查。
- 复杂任务结果、中间状态、用户情绪可以自然融合表达。
- replay 可以审计 SemanticCommitment / progress event 到 SpokenPlan 到 CoverageCheck 到 playback 的链路。

代价：

- 同一模型承担两个 role，需要严格区分 prompt、schema 和权限。
- CoverageCheck 变得更重要，不能省略。
- Thinker-as-Composer 的输入必须被过滤和结构化，不能随意塞上下文。
- 高风险内容可能需要模板化，牺牲一部分自然度。

## Impacted Modules

- Thinker / LALM Adapter
- Thinker-as-Fast-System
- Thinker-as-Composer
- SlowTask
- Slow Agent
- SemanticCommitment
- SpokenPlan
- CommitmentCoverageCheck
- Talker
- Event Journal
- Trace / Replay
- Tool Executor
- Demo Tool Sandbox
- Untrusted External Content Boundary
- Evaluation Harness

## Validation Method

MVP-2 必须验证：

1. SlowTask 输出 SemanticCommitment，而不是任意长文本。
2. Thinker-as-Composer 输出 SpokenPlan 必须带 `source_commitment_id`。
3. Thinker-as-Composer 不得修改 `immutable_facts`。
4. `must_say_fields` 缺失时 CoverageCheck 失败。
5. 关键数字、日期、地点、人名变化时 CoverageCheck 失败。
6. `need_confirmation=true` 时，SpokenPlan 不得表达为已执行。
7. demo dry-run 工具结果不得表达为真实外部操作完成。
8. demo backend action 不得表达为真实设备或真实外部系统操作。
9. webSearch / external evidence 必须被 attribution 或降格表达。
10. CoverageCheck 失败时不得调用 Talker。
11. CoverageCheck 通过时必须记录 `COMMITMENT_COVERAGE_CHECK_PASSED`，且 Talker playback 可追溯到该通过事件。
12. 同一个 Thinker 服务在 fast-system role 和 composer role 下使用不同 role contract。
13. replay 能重建 SemanticCommitment / progress event 到 SpokenPlan 到 CoverageCheck 到 playback chain。

## Open Questions

- CoverageCheck MVP 是规则/模板检查，还是 LLM judge + rule hybrid？
- Thinker-as-Composer 是否需要独立 prompt profile / adapter method？
- `immutable_facts` 是否只支持结构化字段，还是也支持短文本 span？
- 低风险闲聊 / 轻问答绕过 SemanticCommitment 的条件由 ADR-017 Fast Foreground Gate 定义；开放点只剩 fast foreground output 是否总是包装成 SpokenPlan。
- Composer 多次失败后的 degraded response 模板如何定义？
- `must_say_fields` 是否允许在多段 SpokenPlan 中分步覆盖？
