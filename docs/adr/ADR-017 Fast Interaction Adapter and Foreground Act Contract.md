# ADR-017 Fast Interaction Adapter and Foreground Act Contract

## Status

accepted

## Context

当前快慢系统语音链路已经能做到：

Access Layer / local wav / browser draft audio -> ASR Adapter -> LALM Thinker Adapter -> Router -> metadata-only route summary。

但 `FAST_ONLY` 现在只是路由结果，不是真正的快系统直接回答。调试台仍会出现类似 "real fast answer is not implemented" 的占位。如果在 `FAST_ONLY` 后再追加一次 `FastReplyAdapter` 模型调用，虽然能补上答案，但会增加一次模型 round trip，违背快系统的核心目标：低延迟前台响应。

因此快系统需要在一次模型调用中同时产出 route evidence、foreground act 和 candidate reply。模型应被训练和 prompt 成习惯这样做，但系统不能把正确性寄托在模型自觉上：

> 训练模型习惯这样做，但由 runtime 保证必须这样做。

本 ADR 定义 Fast Interaction Adapter、foreground act、reply candidate 和 Fast Foreground Gate 的边界，使低风险快答可以真正展示，同时复杂任务、active SlowTask patch、ignore、ambiguous、工具和确认状态仍由既有 ADR 边界保护。

## Decision

引入 `Fast Interaction Adapter` 作为 post-commit fast-system adapter role。

它可以复用底层 Thinker / LALM provider，但必须拥有独立的 role contract、prompt profile、output schema、adapter capability matrix 和 event journal output。复用 provider 不等于复用权限：`fast_interaction` role 不能继承 SlowTask、Composer、Tool Executor 或 Router 的职责。

Fast Interaction Adapter 的一次调用可以同时输出：

- `route_hint`
- `route_prelude`
- `foreground_act`
- `reply_candidate` 或 streaming `reply_delta`
- `final_fast_evidence`

Router / runtime gate 决定最终展示、丢弃、模板兜底或交给慢系统。Fast Interaction Adapter 输出的是证据和候选，不是最终系统动作。

### 1. Fast Interaction Adapter responsibilities

Fast Interaction Adapter 负责：

- 在 `TURN_INGRESS_COMMITTED` 之后，对一个已接受的 turn 做低延迟前台理解。
- 产出 Router 可消费的 route evidence，而不是最终 `RouterDecision`。
- 产出 foreground act suggestion，而不是最终用户可见动作。
- 在同一次调用中产出可选 `reply_candidate` / `reply_delta`，避免 `FAST_ONLY` 后二次模型调用。
- 对输出 schema 做 adapter-side validation；无效输出必须进入 ADR-002 adapter failure / validation events，不得静默传给 Router 或 gate。
- 标注 output mode：`real` / `mock` / `fallback` / `degraded`。
- 标注风险、置信度、provenance、redaction status 和 capability snapshot reference。

Fast Interaction Adapter 不负责：

- turn ingress、barge-in、truncate 或 assistant-directedness 的 pre-commit 决策，这些仍属于 ADR-001 Duplex / Interaction Controller。
- 最终 RouterDecision；Router 仍是 `FAST_ONLY` / `SPAWN_SLOW_TASK` / `PATCH_ACTIVE_SLOW_TASK` / `IGNORE` 的 owner。
- SlowTask 事实解释、plan_version advance、UserPatch interpretation、confirmation state、tool authorization 或 cancel。
- 复杂任务的最终结论、resolved arguments、SemanticCommitment 或 Composer coverage。
- 工具调用、外部副作用、支付、预订、删除、外部通信或 demo backend UI patch。

### 2. Output contract

Fast Interaction Adapter output 至少包含：

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
- `reply_candidate` optional
- `reply_delta_stream_ref` optional
- `final_fast_evidence_ref`
- `risk_tags`
- `confidence`
- `schema_name`
- `normalization_status`
- `output_mode=real|mock|fallback|degraded`
- `trace_redaction_level`

`route_hint` 是非权威路由提示，可包含：

- `router_decision_candidate`
- `task_focus_candidate`
- `complexity_hint`
- `task_like`
- `assistant_directedness_hint`
- `evidence_uncertainty`
- `risk_class`
- `confidence`

`route_prelude` 是给 Router / gate / replay 使用的短结构化摘要，不是用户可见文本。它可以解释模型为什么认为输入是轻问答、复杂任务、active task patch、ignore 或 ambiguous，但不得包含系统指令、provider raw prompt、未脱敏用户全文或 secret。

`foreground_act` 是模型对前台动作的建议，最终由 Fast Foreground Gate 批准或降级。

`reply_candidate` 是候选前台文本，只有 gate 通过后才能展示。它必须是短、低风险、不可执行副作用的候选表达。

`reply_delta` 是 streaming 场景下的候选片段。它在 gate 通过前只能进入 buffer，不得展示、朗读或发送到 UI。

`final_fast_evidence` 是 normalized evidence ref，用于 replay 和 Router / SlowTask 辅助理解。它可以包括 ASR transcript ref、semantic summary ref、route hint provenance、confidence summary 和 redaction metadata。它不是 SlowTask 的最终事实源。

### 3. Foreground act protocol

`foreground_act` 至少包含以下枚举：

| act | 语义 | candidate policy |
| --- | --- | --- |
| `ANSWER` | 简单问题、闲聊、一句话翻译、轻解释、低风险本地上下文回答。 | 只有 `FAST_ONLY + ANSWER + low risk + sufficient confidence` 时，`reply_candidate` 才可被 gate 放行。 |
| `ACK_SLOW` | 复杂任务承接，例如“我帮你看一下”。 | 模型 candidate 默认不直接展示；runtime 使用模板承接或 progress policy，复杂任务交给 SlowTask。 |
| `ACK_PATCH` | active SlowTask patch 承接，例如“好，这个信息我收到了”。 | 模型 candidate 默认不直接展示；runtime 可使用模板 ack，patch 进入 UserPatch。 |
| `SILENCE` | ignore、non-assistant、环境噪声、旁人对话或不应回答的输入。 | 不展示 candidate；记录 discard / silence reason。 |
| `CLARIFY` | 低置信、边界不清、无法判断归属或缺少必要上下文。 | 可展示短澄清，但必须由 gate 确认不越过 Router / SlowTask 边界；优先模板化。 |

`foreground_act` 必须携带：

- `act_confidence`
- `risk_class`
- `risk_tags`
- `candidate_reply_ref` optional
- `template_hint` optional
- `clarification_target` optional
- `task_focus_candidate` optional

`foreground_act` 不得携带或暗示：

- 工具授权
- 外部副作用已经执行
- payment / booking / deletion / external communication
- confirmation accepted / rejected
- current-plan facts
- resolved arguments
- SemanticCommitment facts
- SlowTask terminal result

### 4. Reply candidate boundaries

`reply_candidate` 不是 `SemanticCommitment`。

`reply_candidate` 不是 SlowTask 事实源。

`reply_candidate` 不得：

- 承诺工具执行。
- 承诺外部副作用。
- 给出复杂任务最终结论。
- 解释或改变 confirmation state。
- 生成、修改或确认 current-plan facts。
- 改写 active SlowTask goal、constraints、resolved arguments、risk warnings 或 tool status。
- 使用 stale evidence 作为当前事实。
- 把 webSearch / RAG / tool output 当作系统指令。
- 回答需要外部最新事实、高风险专业判断或未解析关键字段的问题。

允许的低风险候选包括：

- 闲聊和情绪回应。
- 一句话翻译或转述用户刚提供的文本。
- 不依赖外部最新事实的短解释。
- 对当前 UI / demo 状态的非执行性说明，但不得声称已经改 UI。
- active SlowTask 之外的 brief foreground chat，前提是 ADR-006 task focus 判定为 `FOREGROUND_CHAT`。

### 5. Router and Fast Foreground Gate

Fast Foreground Gate 是 deterministic runtime policy，不是模型。

Gate 输入至少包括：

- `FAST_INTERACTION_OUTPUT_EMITTED`
- `FOREGROUND_REPLY_CANDIDATE_EMITTED` optional
- `ROUTER_DECISION_EMITTED`
- current `InteractionState`
- current `TaskFocusState`
- active SlowTask summary state if any
- adapter capability snapshot
- configured confidence / risk thresholds

Gate 规则：

1. 只有 `router_decision=FAST_ONLY`、`foreground_act=ANSWER`、`risk_class=LOW`、`confidence >= configured_threshold` 且 candidate schema valid 时，`reply_candidate` 才能通过。
2. `SPAWN_SLOW_TASK` 时，candidate answer 必须 discard；前台输出只能是模板化 `ACK_SLOW`、合法 progress feedback 或后续 SlowTask / Composer 输出。
3. `PATCH_ACTIVE_SLOW_TASK` 时，candidate answer 必须 discard；前台输出只能是模板化 `ACK_PATCH`、合法 clarification 或后续 SlowTask progress。
4. `IGNORE` 时，candidate answer 必须 discard；`SILENCE` 默认不输出，除非产品策略允许轻量拒识模板。
5. `AMBIGUOUS` 或 `task_focus=AMBIGUOUS` 时，candidate answer 必须 discard；只能输出短澄清或保持 silence。
6. active SlowTask 场景下，只有 `task_focus=FOREGROUND_CHAT` 且 Router 产生 `FAST_ONLY` 时，低风险 `ANSWER` 才可放行；`ACTIVE_TASK_PATCH`、`NEW_TASK_CANDIDATE`、`CANCEL_OR_PAUSE_CANDIDATE`、`AMBIGUOUS` 不得放行 candidate answer。
7. 任何涉及工具、副作用、确认、取消、任务切换、current-plan facts、resolved arguments、风险提示或复杂任务最终结果的 candidate 必须失败。
8. Gate pass / fail、最终 commit / discard 必须进入 event journal。

Gate pass 只表示候选文本可以作为前台低风险输出展示；它不表示用户已经听见、理解或确认。若需要 TTS，后续 Talker playback 仍必须通过 playback events 记录 delivery marker。

### 6. Streaming policy

如果 adapter 支持 streaming：

- `reply_delta` 可以在 adapter 内部或 runtime foreground buffer 中累积。
- final RouterDecision 和 gate 通过前，不得向用户展示、朗读或发送任何 answer delta。
- route 不是 `FAST_ONLY` 时，必须丢弃 buffered answer。
- foreground act 不是 `ANSWER` 时，必须丢弃 buffered answer。
- gate fail 时，必须记录 discard reason，并可提交模板化承接 / 澄清输出。
- replay 使用已记录的 candidate / delta refs 和 gate events，不得重跑模型。

Streaming 的目的只是隐藏模型内部生成延迟，不改变安全边界。任何“边生成边说”的产品行为都需要先证明 final gate 可以在内容泄露前完成；否则必须继续 buffer。

### 7. Event Journal and Replay

ADR-002 canonical event registry 增加以下 foreground events：

- `FAST_INTERACTION_OUTPUT_EMITTED`
- `FOREGROUND_REPLY_CANDIDATE_EMITTED`
- `FOREGROUND_ACT_GATE_PASSED`
- `FOREGROUND_ACT_GATE_FAILED`
- `FOREGROUND_OUTPUT_COMMITTED`
- `FOREGROUND_OUTPUT_DISCARDED`

事件粒度取舍：

- `FAST_INTERACTION_OUTPUT_EMITTED` 记录 adapter 的一次 structured output。
- `FOREGROUND_REPLY_CANDIDATE_EMITTED` 单独记录 candidate / buffered delta ref，避免把可被 discard 的文本混入最终输出事件。
- gate pass / fail 分开记录，便于 replay 解释 policy 决策。
- committed / discarded 分开记录，便于区分“模型生成过但被拦截”和“用户最终看到 / 听到的内容”。

Replay 要求：

- replay 必须能重建候选生成、gate pass/fail、最终展示、丢弃或降级路径。
- replay 不得重新调用 Fast Interaction Adapter、ASR、Thinker、Slow LLM、TTS 或工具。
- shareable replay / GitHub fixture 不得包含 raw audio、raw prompt、provider body、secret、unredacted real user input 或 large raw webSearch content。
- local debug 可以保存更详细 refs，但必须受 ADR-010 redaction/export gate 约束。
- `FOREGROUND_OUTPUT_COMMITTED` 必须引用 gate pass event，或引用 gate fail 后的模板 fallback policy event / reason。
- `FOREGROUND_OUTPUT_DISCARDED` 必须引用 candidate event 和 discard reason。

### 8. Adapter capability requirements

Fast Interaction Adapter 必须声明独立 capability matrix。除 ADR-011 通用字段外，至少声明：

- `supports_fast_interaction_output`
- `supports_route_hint`
- `supports_route_prelude`
- `supports_foreground_act`
- `supports_reply_candidate`
- `supports_reply_delta_streaming`
- `supports_final_fast_evidence`
- `supports_structured_json`
- `supports_schema_validation`
- `supports_risk_tags`
- `supports_confidence`
- `max_reply_candidate_tokens`
- `expected_first_candidate_latency_ms`
- `expected_final_gate_ready_latency_ms`

Adapter output 必须标注：

- `real`
- `mock`
- `fallback`
- `degraded`

如果 provider 只能给 route evidence、不能给 safe candidate reply，则 runtime 可以使用 template fallback，但必须记录 `ADAPTER_OUTPUT_DEGRADED` 或 capability snapshot 中的缺失能力。不得把 template fallback 冒充 real model candidate。

### 9. Relationship to existing ADRs

ADR-001:

- Fast Interaction Adapter 运行在 `TURN_INGRESS_COMMITTED` 之后，不参与 pre-commit Duplex / Interaction Controller 决策。

ADR-002:

- 本 ADR 新增 canonical foreground events，并要求 replay 使用记录值，不重跑模型。

ADR-006:

- Router 仍保持快慢系统门控和 TaskFocusState owner。
- active SlowTask 中的 patch 与 side chat 必须保持边界：只有 `FOREGROUND_CHAT + FAST_ONLY + ANSWER` 可以放行低风险 candidate。

ADR-007:

- active SlowTask patch 仍进入 UserPatch evidence pack。`reply_candidate` 不得替代 UserPatch，也不得成为 patch interpretation。

ADR-008:

- ASR / Thinker / Fast Interaction 差异仍是 evidence fusion，不是 Router 层字段仲裁。
- Fast reply 不参与复杂任务事实仲裁；复杂任务仍由 SlowTask-led conflict resolution 负责。

ADR-009:

- 低风险 foreground reply 可以绕过 SemanticCommitment，但必须通过 Fast Foreground Gate。
- 复杂任务结果、progress、confirmation prompt 和 tool status 仍由 SemanticCommitment / progress events / Thinker-as-Composer / coverage checks 负责。

ADR-011:

- Fast Interaction Adapter 是独立 adapter type，必须声明 capability matrix、role contract、prompt profile 和 schema。

ADR-013:

- `ACK_SLOW` / `ACK_PATCH` 模板承接不能编造 SlowTask progress。真实 progress feedback 仍需 ProgressTruthfulnessCheck。

ADR-014:

- webSearch 仍是 untrusted evidence。Fast Interaction Adapter 不得把 webSearch result 当作 instruction，也不得基于 untrusted web content 直接生成高置信 current answer，除非后续 ADR 定义专门的低风险搜索前台 gate。

ADR-016:

- confirmation、cancel、switch task、tool authorization 仍由 SlowTask Runtime / Tool Executor 拥有。Fast Interaction Adapter 只能建议 `ACK_PATCH` / `CLARIFY` 等前台动作，不能接受确认或授权工具。

### 10. Non-goals

本 ADR 不实现：

- 真实 TTS。
- 工具调用。
- 外部副作用。
- payment / booking / deletion / external communication。
- Router 复杂任务 reasoning。
- Fast reply 改写 SlowTask facts。
- 多 active SlowTask。
- pause / resume。
- 生产隐私策略。
- 立即后训练。

本 ADR 允许后续 SFT / distillation / preference tuning 固化该协议，但 runtime gate 仍必须保留；不能因为模型训练过就移除 gate。

## Alternatives Considered

1. `FAST_ONLY` 后追加 `FastReplyAdapter`。
   该方案职责直观，但会为快答增加第二次模型请求，破坏 first acknowledgement latency 和快系统目标。

2. 让 Router 直接生成 answer。
   被拒绝。Router 只做门控和 TaskFocusState，不应承担自然语言回答、复杂推理或事实承诺。

3. 让所有前台回复都走 SemanticCommitment / Composer。
   安全但过慢，会把闲聊、短翻译、轻解释也拖入慢系统，不符合 live 语音体验。

4. 让 Fast Interaction Adapter 的 `ANSWER` 直接展示，不设 runtime gate。
   被拒绝。模型输出可能越界承诺工具、外部副作用、确认状态或复杂任务事实，必须由 deterministic gate 保证。

5. streaming delta 边生成边展示。
   延迟最低，但在 route/gate 未完成前有内容泄露风险。MVP 必须先 buffer，后续若要边说边生成，需要新的 ADR 或严格证明 gate-before-leak。

## Consequences

正向结果：

- `FAST_ONLY` 可以真正产出低风险前台答案，不再只是 metadata route summary。
- 快系统保持一次模型调用，避免额外 FastReply round trip。
- runtime gate 让模型习惯与系统强制边界分离。
- active SlowTask 场景下，side chat 和 patch 不再互相污染。
- replay 可以解释候选为什么展示、为什么丢弃或为什么降级成模板。

代价：

- Fast Interaction Adapter schema 和 capability matrix 更复杂。
- Event journal 增加 foreground gate / output events。
- Gate threshold、risk tags 和 fallback 模板需要产品策略配置。
- Streaming 早期只能 buffer，不能充分利用 token-level 低延迟。

## Impacted Modules

- Fast Interaction Adapter
- Thinker / LALM Adapter provider reuse
- Router
- Fast Foreground Gate
- Interaction / Turn Controller
- TaskFocusState
- SlowTask
- UserPatch Pipeline
- Composer
- Talker
- Event Journal
- Trace / Replay
- Adapter Registry
- Evaluation Harness
- Debug Console

## Validation Method

必须用 replay / eval 验证：

1. 简单闲聊或轻问答产生 `FAST_INTERACTION_OUTPUT_EMITTED`、`FOREGROUND_REPLY_CANDIDATE_EMITTED`、`ROUTER_DECISION_EMITTED(router_decision=FAST_ONLY)`、`FOREGROUND_ACT_GATE_PASSED`、`FOREGROUND_OUTPUT_COMMITTED`。
2. 复杂任务产生 `SPAWN_SLOW_TASK` 时，模型 candidate 被 `FOREGROUND_OUTPUT_DISCARDED`，前台只输出模板 `ACK_SLOW` 或等待 SlowTask progress。
3. active SlowTask patch 产生 `PATCH_ACTIVE_SLOW_TASK` 时，candidate answer 被 discard，patch 进入 UserPatch，前台最多模板 `ACK_PATCH`。
4. active SlowTask side chat 产生 `task_focus=FOREGROUND_CHAT` 且 `FAST_ONLY + ANSWER` 时，低风险 candidate 可通过 gate，且不生成 UserPatch。
5. `IGNORE` / `SILENCE` 路径不展示 candidate。
6. `AMBIGUOUS` 或低 confidence 路径不展示 answer candidate，只允许短澄清或 silence。
7. streaming `reply_delta` 在 final route/gate 前不会展示；非 `FAST_ONLY` route 会丢弃 buffer。
8. replay 使用记录的 adapter output、candidate refs、gate decision 和 committed/discarded output，不重跑模型。
9. shareable trace / GitHub fixture 不包含 raw audio、raw prompt、provider body、secret 或 unredacted real user input。
10. adapter capability snapshot 能区分 real / mock / fallback / degraded fast interaction output。

## Open Questions

- `risk_class=LOW` 的默认阈值和 risk taxonomy 是否由配置文件定义，还是另写 policy ADR？
- committed fast foreground output 是否总是包装成 `SPOKEN_PLAN_EMITTED(source=fast_foreground)` 再交给 Talker，还是文本 UI 可以直接消费 `FOREGROUND_OUTPUT_COMMITTED`？
- Fast Foreground Gate 的第一版 confidence threshold 是否按语言、输入 modality 或 active SlowTask state 分桶？
- 低风险 webSearch 前台摘要是否需要单独 gate，还是一律交给 SlowTask / Composer？
