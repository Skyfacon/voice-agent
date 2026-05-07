# 任务：设计 live 态语音 Agent 整体系统方案（planning only，不写实现代码）

## 0. 重要约束

本轮任务只做系统设计和规划，不写业务实现代码，不创建可运行服务，不生成工程文件。

请先基于本文完成一份完整 planning 文档。如果你认为信息不足，请先列出假设和需要确认的问题，不要直接发散实现。

请输出：

1. 系统架构设计文档
2. 模块职责拆解
3. 控制面 / 数据面设计
4. 核心事件与数据结构 schema
5. 快慢系统协同逻辑
6. Router 决策规则
7. SlowTask 生命周期
8. 状态机图
9. 时序图
10. MVP 里程碑计划
11. 风险清单和验证场景

---

# 1. 背景

我要设计研发一个端到端的 live 态语音对话 Agent。它是原手机语音对话助手的升级版本，目标是从单纯闲聊助手，升级为兼备闲聊、实时语音交互、复杂任务执行能力的语音 Agent。

该 Agent 的产品定义是：

> 面向高实时、低注意力占用、多轮连续打断、边说边做场景的实时语音操作态。

它需要支持：

1. 闲聊伙伴能力：接住用户闲聊、陪伴、轻问答
2. 复杂任务能力：具备 ReAct 式 Agent 能力，可以调用工具、RAG、网页检索、系统 API 完成复杂任务
3. 全双工交互能力：支持随时打断、接续、拒识、非对助手讲话判断
4. 渐进式任务补全：用户可以边说边补充约束，系统能持续更新慢系统任务
5. 中间态反馈：长任务执行时，用户能感知 Agent 一直在工作

---

# 2. 核心架构原则

本系统不是 ASR-LLM-TTS 的简单级联，而是：

> Duplex 前置控制 + Thinker 前台承接 + Router 门控慢系统 + Slow Agent 复杂求解 + Talker 会话表达

关键原则：

1. Duplex 是前置实时控制层，不与 Thinker / ASR 并列。
2. Duplex 是时序真相源。目标架构中，它负责 speech start/end、semantic close candidate、assistant-directedness、barge-in、hold/continue/accept/reject、commit boundary。
3. MVP 阶段 Duplex 只要求实现或模拟 speech_start、speech_end、interrupt，其它能力作为目标架构预留。
4. Thinker = LALM，是快系统核心，负责语音原生理解、前台会话承接、附和、短确认、中间反馈、情绪和 audio caption 抽取。
5. Talker = 情感 TTS，是表达层，消费 spoken plan / Thinker token，负责流式情感语音合成、可打断、可续播。
6. Slow Agent LLM 是慢系统核心，负责 deep reasoning、planning、ReAct、tool、RAG、复杂任务执行和最终语义承诺。
7. 慢系统不是默认后台并发运行，必须由 Router 显式唤醒。
8. 复杂任务一旦进入慢系统，最终语义承诺权归慢系统。
9. 快系统在慢系统运行期间只负责前台会话承接和增量补料，不替慢系统抢最终答案。
10. 快慢边界不是按模型大小划分，而是按交互预算和求解闭环深度划分。

---

# 3. 当前模型选型

所有核心模型组件尽量使用开源模型或开源可部署组件。

## 3.1 Thinker 候选

Qwen3-Omni。

注意：

- 本系统里的 Thinker / Talker 是系统架构命名。
- Qwen3-Omni 自身也可能包含 thinker / talker 组件。
- MVP 中 Qwen3-Omni 优先作为系统级 Thinker 使用，主要消费其音频理解、文本语义、情绪、audio caption、任务复杂度提示等输出。
- Talker 在系统架构上应保持独立服务接口，后续可以选择独立 TTS，也可以评估是否复用 Qwen3-Omni 的 speech output，但接口不能耦合死。

## 3.2 Slow Agent LLM 候选

GLM5.1。

慢系统不是工具/RAG专用层，而是复杂语义承诺层，负责：

- 复杂逻辑推理
- 多步 planning
- ReAct loop
- tool / RAG
- 高风险确认
- 长上下文总结
- 最终结构化结果输出

## 3.3 ASR

ASR 是 text projection 辅助链路，不是唯一语义真相。

ASR 用于：

- 转写
- 检索辅助
- 参数抽取
- trace/debug/eval
- 和 Thinker 形成互补

## 3.4 Talker

Talker 是情感 TTS 服务，负责把 spoken plan 转成可打断、可续播、情绪可控的语音。

---

# 4. 系统分层

请按以下层次设计。

## 4.1 接入层

负责：

- WebSocket 长连接
- session 生命周期
- 音频上下行
- 用户文本输入
- 环境上下文输入
- 服务端会话 ID 管理

## 4.2 感知层

当前 MVP 只考虑：

- 持续用户音频流
- 用户文本态输入
- 环境上下文：时间、地点、是否车载、设备类型等

后续可预留屏幕/视觉上下文接口，但 MVP 不强制实现。

## 4.3 前置实时控制层：Duplex

Duplex 是前置控制层，位于 Thinker / ASR 之前，是时序真相源。

### MVP 阶段只要求实现或模拟

- speech_start
- speech_end
- interrupt

### 目标架构预留

- assistant-directedness：判断当前语音是否是对助手说话
- semantic_close：判断语义是否闭合
- hold / continue / accept / reject
- Talker truncate / pause / resume

Duplex 不负责生成语义回复。它只负责决定当前音频是否进入语义链路，以及是否需要打断当前 Talker。

注意：MVP 中如果没有能力真实实现 assistant-directedness 或 semantic_close，可以在设计中标注为 mock / rule-based / future extension，不要把它们作为第一阶段硬依赖。

## 4.4 快系统：System 1 / Thinker

核心是 Thinker = LALM。

目标架构中 Thinker 支持流式语音理解。MVP 阶段允许 Thinker 接收 Duplex 切分后的完整 utterance 音频片段，而不是强制流式。

### 负责

- 语音理解：目标架构流式，MVP 可按完整 utterance 处理
- 前台会话承接
- 附和、短确认、低延迟反馈
- 中间进度反馈
- 情绪识别
- audio caption
- 环境线索提取
- 意图候选生成：intent_hint，可选，仅为浅层 hint
- 槽位候选生成：slot_hints，可选，仅为浅层 hint
- 任务复杂度 hint
- 为 Router 提供 SemanticFrame
- 慢系统运行期间，将用户补充转成 UserPatch，而不是强语义的 constraint_update / goal_rewrite / slot_patch

### 快系统允许独立完成

- 闲聊
- 简单问答
- 简单 AQA / SER / S2TT
- 低风险轻任务
- 中间态反馈

### 快系统不允许独立完成

- 复杂逻辑推理最终结论
- 高风险决策
- 工具执行结果承诺
- 正式分析报告
- 慢系统任务的最终答案

注意：intent_hint 和 slot_hints 只是浅层候选，不是最终任务语义。慢系统负责权威任务理解和最终语义承诺。

## 4.5 Router

Router 不做复杂任务 reasoning，只做快慢系统门控。

### 输入

- DuplexEvent
- SemanticFrame
- ASRFrame
- LiveContext
- 当前 SlowTask 状态
- 风险等级
- 用户环境状态

### MVP 阶段 RouterDecision 只包含

- FAST_ONLY
- SPAWN_SLOW_TASK
- PATCH_ACTIVE_SLOW_TASK
- IGNORE

### Router 决策维度

1. 交互紧迫度
2. 语音原生依赖度
3. 认知深度
4. 承诺/风险等级
5. 意图成熟度
6. 是否已有活跃 SlowTask

### Router 职责

1. 判断是否由快系统直接处理
2. 判断是否创建新的 SlowTask
3. 判断当前输入是否应作为 UserPatch 送入已有 SlowTask
4. 判断是否忽略

复杂的 cancel、goal rewrite、ask clarification 等，不由 Router 深度判断，而由慢系统结合任务上下文判断。Router 可以在 UserPatch 中携带浅层 patch_hint，但该 hint 不能作为最终任务语义结论。

## 4.6 慢系统：System 2 / Slow Agent

核心是 Slow Agent LLM，例如 GLM5.1。

### 负责

- deep reasoning
- ReAct loop
- planning
- tool calling
- RAG
- memory retrieval
- 多步任务执行
- 任务状态维护
- 用户增量 UserPatch 接收
- 用户补充后的 plan_version 更新
- final semantic commitment

慢系统被唤醒后，应创建 SlowTaskSession。

### SlowTask 状态

MVP 阶段 SlowTask 状态包括：

- CREATED
- WAITING_FOR_SLOT
- PLANNING
- EXECUTING
- WAITING_FOR_USER_CONFIRMATION
- COMPLETED
- CANCELLED
- FAILED

不单独设置 REPLANNING。

如果发生用户补充、工具失败或目标变化，仍进入 PLANNING 状态，但更新：

- plan_version
- planning_reason：initial | user_patch | tool_error | goal_changed | risk_changed

### UserPatch 输入

快系统不要直接给慢系统发送 constraint_update / goal_rewrite / slot_patch 这类强语义事件。快系统只发送 UserPatch。

UserPatch 包含：

- task_id
- raw_text
- audio_summary
- semantic_summary
- patch_hint，可选
- emotion，可选
- confidence
- turn_id
- timestamp

慢系统收到 UserPatch 后，结合当前 task context 判断它属于：

- slot update
- constraint update
- goal rewrite
- user confirmation
- user cancel
- user feedback
- irrelevant message

这些是慢系统内部解释结果，不是快系统直接决定。

慢系统最终输出 SemanticCommitment，而不是随意长文本。

## 4.7 表达层

表达层包括：

- Spoken Response Composer
- Talker = Emotional TTS

Spoken Response Composer 负责把以下内容转成 spoken plan：

1. 快系统轻量输出
2. 慢系统 SemanticCommitment
3. 中间进度反馈
4. 待用户确认项

Talker 负责：

- 流式 TTS
- 情绪语音
- 可打断
- 可续播
- 语速、停顿、强调控制

Talker 不负责做语义决策。

---

# 5. 必须设计的核心数据结构

请设计以下 schema，可以用 JSON Schema / TypeScript interface / Python Pydantic 任一形式表达：

1. DuplexEvent
2. ASRFrame
3. SemanticFrame
4. LiveContext
5. RouterDecision
6. SlowTask
7. UserPatch
8. SlowTaskInternalUpdate
9. ToolCall
10. ToolResult
11. SemanticCommitment
12. SpokenPlan
13. TTSControlEvent

特别注意：

## SemanticFrame 需要包含

- turn_id
- utterance_summary
- transcript_hint，可选
- emotion，可选
- audio_caption，可选
- intent_hint，可选
- slot_hints，可选
- task_like
- complexity_hint
- confidence

## UserPatch 需要包含

- task_id
- turn_id
- raw_text
- audio_summary
- semantic_summary
- patch_hint，可选
- emotion，可选
- confidence
- timestamp

## SemanticCommitment 需要包含

- task_id
- task_status
- final_result
- key_facts
- must_say_fields
- forbidden_rewrite_fields
- need_confirmation
- risk_level
- response_style_hint

## SpokenPlan 需要包含

- text
- emotion
- speaking_style
- interruptible
- priority
- source
- immutable_fields

---

# 6. 必须输出的图

请用 Mermaid 输出：

1. 总架构图
2. 控制面 / 数据面分离图
3. 快慢系统协同时序图
4. SlowTask 生命周期状态机
5. Router 决策树

---

# 7. 必须覆盖的测试 / 验收场景

请区分 MVP 必测场景和目标架构预留场景。

## 7.1 MVP 必测场景

1. 简单闲聊，快系统直答
2. 简单问答，快系统直答
3. 用户 speech_start / speech_end 被正确识别或模拟
4. 用户打断 Talker，触发 interrupt
5. 复杂任务触发慢系统
6. 慢系统执行时用户追加约束，形成 UserPatch
7. 慢系统收到 UserPatch 后更新 plan_version
8. 慢系统发现缺槽，要求用户补充
9. 工具失败后慢系统重试或降级
10. 慢系统返回最终结果，快系统/Composer 只做 spoken realization，不改关键事实
11. 情绪识别影响 Talker 回复语气
12. ASR 错误时，Thinker 语音理解和上下文能辅助纠偏，或至少在 trace 中体现差异

## 7.2 目标架构预留场景

1. 用户停顿但语义未闭合，Duplex 输出 hold / semantic_close=false
2. 用户对旁人讲话，系统基于 assistant-directedness 拒识
3. 车载 / 低注意力场景，回复必须短
4. Talker pause / resume，而不只是 truncate
5. 用户改口导致慢系统内部判断 goal rewrite
6. 用户取消导致慢系统内部判断 cancel

---

# 8. 开发环境

我的开发环境：

1. MacBook Pro 2020，M1 芯片，作为个人 PC，可使用 Codex / Superpowers / vibe coding 工具。
2. 公司 8 卡 A100 Linux 服务器，不能使用 vibe coding 工具，但可以部署 ASR、TTS、Qwen3-Omni 等模型服务。GLM5.1 仍需要调用接口，是通的。

开发模式：

## 阶段 1

在个人 PC 上先通过 API 调用方式开发和验证整体流程。ASR、TTS、Thinker、Slow LLM 都通过 HTTP/WebSocket API 访问。

## 阶段 2

把代码 git push 到 GitHub 个人仓。

## 阶段 3

在 A100 Linux 服务器 git pull，通过配置切换到自部署模型服务进行调试。

因此，设计中必须包含：

- 模型服务抽象接口
- API adapter
- local/self-hosted adapter
- 配置化 endpoint
- mock service，用于本地无模型时联调
- 日志与 trace 设计
- session replay 设计

---

# 9. 交付物要求

请输出一个完整的 planning 文档，包含：

1. Executive Summary
2. Architecture Overview
3. Module Responsibilities
4. Target Architecture vs Phase 1 MVP Scope
5. Control Plane vs Data Plane
6. Event Flow
7. Data Schema
8. Router Decision Logic
9. SlowTask Lifecycle
10. Model Service Interfaces
11. Development Milestones
12. MVP Scope
13. Non-MVP Future Extensions
14. Test and Evaluation Plan
15. Risks and Open Questions

请不要写实现代码。
请不要直接创建项目。
请先完成设计，必要时列出你需要我确认的问题。
