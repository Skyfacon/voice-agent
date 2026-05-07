# Voice Agent Project Overview

本文档面向新加入的 human developer 和 agentic coding agent，用来快速理解当前 `voice-agent` 项目“想做什么、现在有什么、接下来应该怎么落地”。它不是 ADR 的替代品。架构决策仍以 `stage_b_adr_register.md`、`AGENTS.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

## 1. 当前结论

`voice-agent` 目前是一个 **live 态语音 Agent 的架构基线和 MVP 规划仓库**，还不是一个可运行的应用或服务。

仓库当前包含：

- 16 个 accepted ADR，覆盖 Duplex、Interaction Controller、Event Journal、Replay、SlowTask、Tool Executor、Composer、Adapter、webSearch evidence boundary 等核心边界。
- 一份 implementation-facing 的 `docs/architecture-book.md`。
- 事件注册表、状态 reducer、replay、adapter capability、MVP-0 验收场景等规格文档。
- MVP-0 implementation backlog，明确后续要创建的 `src/voice_agent/...` 和 `tests/...` 文件。
- `.gitignore` 已覆盖 local debug / trace / replay / raw audio / env secret 目录。

仓库当前不包含：

- `src/` 实现代码。
- `tests/` 测试代码。
- 可运行服务入口。
- 前端 demo。
- 真实模型 adapter。
- demo tool backend。
- `.git` 元数据。当前目录看起来不是一个已初始化的 Git working tree，或者只是拷贝出来的文档包。

因此，本项目现在最准确的阶段描述是：

> Stage B ADR baseline frozen / implementation planning ready, MVP-0 not implemented yet.

## 2. 项目要解决的问题

项目目标是设计并实现一个端到端的实时语音 Agent，从传统“ASR -> LLM -> TTS”的级联系统，升级为支持实时打断、低注意力占用、边说边做、复杂任务执行和可回放调试的 live voice agent。

产品定义可以概括为：

> 面向高实时、低注意力占用、多轮连续打断、边说边做场景的实时语音操作态 Agent。

它最终要同时支持：

- 闲聊和轻问答。
- 语音原生理解、情绪和 audio caption。
- 全双工交互，包括 speech start/end、barge-in、truncate、拒识、非对助手讲话判断。
- Router 门控快慢系统。
- SlowTask 复杂任务执行，包含 planning、ReAct、tool/RAG/webSearch、确认、取消和最终语义承诺。
- 渐进式工具调用和前端 UI state patch。
- 每个关键状态都能通过 event journal replay。

## 3. 核心架构一句话

本系统不是简单级联，而是：

```text
Access Layer
  -> Duplex / Realtime Conversation Gate
  -> Interaction Controller
  -> ASR Adapter + Thinker Adapter
  -> Router
  -> Fast reply or SlowTask
  -> SemanticCommitment
  -> Thinker-as-Composer
  -> Coverage / Truthfulness Checks
  -> Talker / Playback
```

关键思想是：

- **Duplex** 负责 pre-ASR 的实时入口控制，不负责最终任务语义。
- **Interaction Controller** 是 deterministic policy applier，唯一拥有 turn ingress commit。
- **ASR / Thinker / Slow LLM / TTS 等模型必须经过 adapter**，业务模块不得直接调用 provider endpoint。
- **Router** 只做 post-commit 快慢系统门控，不做复杂 reasoning。
- **SlowTask** 拥有复杂任务事实、plan_version、confirmation、stale evidence 和 SemanticCommitment。
- **Composer** 只做 spoken realization，不得改写 SlowTask 事实。
- **Event Journal** 是关键状态的事实来源，replay 默认不重跑真实模型或工具。

## 4. 当前文档结构

| 路径 | 作用 |
| --- | --- |
| `AGENTS.md` | 仓库治理入口，列出不可违反的工程规则和 code review P0/P1 checklist。 |
| `stage_b_adr_register.md` | Accepted ADR register，列出 `docs/adr/` 下的 ADR 文件。 |
| `docs/adr/*.md` | 16 个 accepted ADR 的实际位置。 |
| `docs/architecture-book.md` | 把 accepted ADR 汇总成实现导向架构书。 |
| `docs/adr-traceability-matrix.md` | ADR 到模块、事件、状态对象、replay/eval 的追踪矩阵。 |
| `docs/specs/event-registry.md` | Canonical event registry 和 event envelope schema。 |
| `docs/specs/state-reducers.md` | Deterministic reducer 规范，用事件重建运行状态。 |
| `docs/specs/replay-spec.md` | deterministic / degraded / re-eval replay 规范。 |
| `docs/specs/model-adapter-capabilities.md` | Adapter capability matrix、degradation 和 output mode 规范。 |
| `docs/specs/mvp0-acceptance-scenarios.md` | MVP-0 必须通过的验收场景。 |
| `docs/implementation/mvp0-backlog.md` | MVP-0 从 repo safety 到 acceptance runner 的分片实施 backlog。 |
| `voice_agent_planning_prompt_final.md` | 最初的 planning-only 任务说明和产品/架构背景。 |

## 5. 模块边界概览

| 模块 | 拥有什么 | 不做什么 |
| --- | --- | --- |
| Access Layer | 文本/音频输入、span 元数据、session ingress。 | 不做语义路由，不直接进入 Router。 |
| Duplex | speech start/end、barge-in candidate、directedness/semantic_close candidate、playback overlap。 | 不 commit turn，不解释复杂任务。 |
| Interaction Controller | `InteractionState`、turn open/hold/reject/commit、playback interrupt policy。 | 不使用 ASR/Thinker 决定首次 commit，不取消 SlowTask。 |
| Event Journal | per-session append-only event stream、event_seq、因果链、trace redaction level。 | 不是全局阻塞消息总线。 |
| ASR Adapter | transcript / text projection，mock 或 real output。 | 不是唯一语义真相。 |
| Thinker / Fast System | 前台承接、轻答、SemanticFrame hints、情绪/audio caption/slot hints。 | 不拥有复杂任务最终事实。 |
| Router | `TaskFocusState`、FAST_ONLY / SPAWN / PATCH / IGNORE。 | 不 cancel task，不 authorize tool，不改 plan_version。 |
| UserPatch Pipeline | 把用户补充构造成 evidence pack。 | 不直接改任务 goal / constraints。 |
| SlowTask Runtime | `SlowTaskState`、plan_version、task_event_seq、confirmation、stale evidence、SemanticCommitment。 | 不直接执行工具，不拥有 turn ingress。 |
| Tool Executor | manifest、参数/provenance 校验、authorization、sandbox execution、UI patch、ToolResult normalization。 | 不直接 mutate SlowTask state，不执行真实外部副作用。 |
| Thinker-as-Composer | 把 commitment/progress 变成 SpokenPlan。 | 不改 immutable facts，不编造进度，不确认工具。 |
| Coverage / Truthfulness Checkers | CommitmentCoverageCheck 和 ProgressTruthfulnessCheck。 | 不创造新事实。 |
| Talker / Playback | TTS/mock playback、progress、commit marker、truncate。 | 不做语义承诺。 |
| Trace / Replay | deterministic replay、fixture export boundary、state digest。 | 默认不重跑真实模型、真实工具或 webSearch。 |
| Adapter Registry | capability snapshot、adapter health/degradation events。 | 不隐藏 unsupported capability。 |
| Privacy / Redaction | trace/export 安全边界、secret redaction/block。 | 不允许 raw secrets 进入 trace。 |

## 6. 运行时主链路

```mermaid
sequenceDiagram
    participant User
    participant Access as Access Layer
    participant Duplex
    participant IC as Interaction Controller
    participant Journal as Event Journal
    participant ASR as ASR Adapter
    participant Thinker
    participant Router
    participant SlowTask
    participant Composer
    participant Talker

    User->>Access: text or audio input
    Access->>Journal: TEXT_INPUT_RECEIVED or AUDIO_SPAN_*
    Access->>Duplex: audio only
    Duplex->>Journal: SPEECH_* / BARGE_IN_CANDIDATE
    Duplex->>IC: realtime candidates
    IC->>Journal: TURN_OPENED / ACCEPTED / COMMITTED
    Journal->>ASR: after TURN_INGRESS_COMMITTED
    Journal->>Thinker: after TURN_INGRESS_COMMITTED
    ASR->>Journal: ASR frame event
    Thinker->>Journal: Thinker frame event
    Router->>Journal: ROUTER_DECISION_EMITTED
    alt FAST_ONLY
        Thinker->>Composer: fast spoken plan or foreground reply
    else SPAWN or PATCH SlowTask
        Router->>SlowTask: post-commit routing evidence
        SlowTask->>Journal: SlowTask / UserPatch / PlanVersion / Tool / Commitment events
        SlowTask->>Composer: SemanticCommitment or progress event
    end
    Composer->>Journal: SPOKEN_PLAN_EMITTED
    Composer->>Journal: coverage/truthfulness check result
    Talker->>Journal: PLAYBACK_SPAN_STARTED / PROGRESS / COMMITTED
    User-->>Duplex: barge-in during playback
    Duplex->>Journal: BARGE_IN_CANDIDATE
    IC->>Journal: INTERRUPT_CANDIDATE / TTS_TRUNCATE_REQUESTED
    Talker->>Journal: TTS_TRUNCATED
```

## 7. Event Journal 和 Replay 是系统地基

项目非常强调“没有 journal 记录，就不算通过 MVP slice 验证”。

每个 event 都必须带 common envelope，例如：

- `event_id`
- `event_seq`
- `event_schema_version`
- `session_id`
- `conversation_id`
- `source_module`
- `created_monotonic_ms`
- `created_wall_clock_ms`
- `caused_by_event_id`
- `trace_redaction_level`

关键上下文字段按需绑定：

- `turn_id`
- `utterance_id`
- `input_span_id`
- `text_span_id`
- `audio_span_id`
- `playback_span_id`
- `task_id`
- `plan_version`
- `task_event_seq`

Replay 分三种模式：

- `deterministic replay`: 默认模式，只用 recorded events / refs 重建状态，不重跑模型、工具、网络、时钟或随机数。
- `degraded replay`: 对缺失 data-plane refs 的 shareable fixture 做降级重建。
- `re_eval replay`: 显式 opt-in，才允许重跑 mock evaluator 或批准的 eval adapter，且结果必须标成 re-eval output。

MVP-0 主要 reducer 目标：

- `InteractionState`
- `PlaybackState`
- `AdapterHealthState`
- `TracePrivacyState`
- 最小/inert `TaskFocusState`

MVP-1/MVP-2 会加入 SlowTask、ToolExecutionState、coverage/truthfulness 等更复杂 replay。

## 8. MVP 分层路线

### MVP-0: event-driven live loop skeleton

目标是先证明 live loop 最硬的骨架：

- text/audio ingress 走 canonical events。
- Duplex mock/rule speech start/end 和 barge-in。
- Interaction Controller commit turn。
- mock ASR / mock Thinker 只能在 `TURN_INGRESS_COMMITTED` 后输出。
- Router 做最小 FAST_ONLY/IGNORE。
- mock Talker playback progress 和 truncate。
- deterministic replay 可重建状态。
- mock capability 必须标注为 mock。

明确不做：

- 真实 ASR / Thinker / Slow LLM / TTS。
- SlowTask。
- 工具调用。
- pause/resume。
- 真 semantic_close / assistant-directedness。

### MVP-1: SlowTask mock and UserPatch consistency

目标是证明复杂任务状态一致性：

- single active SlowTask。
- UserPatch evidence pack。
- `plan_version` advance。
- `task_event_seq`。
- stale ToolResult policy。
- SlowTask lifecycle。
- SemanticCommitment mock。
- ASR/Thinker evidence fusion mock。

### MVP-2: demo tools and Composer coverage

目标是证明“边说边做”的 demo 工具链：

- demo backend sandbox。
- progressive tool invocation。
- 至少手电筒、备忘录、天气、闹钟、webSearch 中的若干 demo tools。
- `TOOL_UI_STATE_PATCHED` replay 前端状态。
- `DEMO_DESTRUCTIVE_ACTION` 轻确认。
- Thinker-as-Composer。
- CommitmentCoverageCheck。
- ProgressTruthfulnessCheck。
- truthful progress feedback。

### MVP-3: real adapter integration

目标是替换真实 adapter，但不新增架构能力：

- real ASR / Thinker / Slow LLM / TTS 至少各接一个 endpoint。
- adapter capability matrix。
- healthcheck、timeout、retry、structured error events。
- mock / real / fallback / degraded output 在 trace 中可区分。

## 9. MVP-0 backlog 当前落地计划

`docs/implementation/mvp0-backlog.md` 已经把 MVP-0 切成 10 个 slice：

| Slice | 目标 |
| --- | --- |
| 0 | Repo safety 和 runtime skeleton。 |
| 1 | Event envelope 和 append-only journal。 |
| 2 | Capability snapshot 和 mock adapter contracts。 |
| 3 | Deterministic state reducers 和 replay core。 |
| 4 | Text ingress through Interaction Controller。 |
| 5 | Audio span 和 mock Duplex accept path。 |
| 6 | Mock understanding 和 Router FAST_ONLY skeleton。 |
| 7 | Mock Talker playback progress。 |
| 8 | Barge-in candidate to truncate flow。 |
| 9 | MVP-0 replay fixtures 和 acceptance runner。 |

Backlog 预期实现形态像一个 Python package：

- `src/voice_agent/...`
- `tests/...`
- `tests/fixtures/replay/mvp0/...`

这些文件目前尚未创建。

## 10. 必须守住的工程红线

以下规则来自 `AGENTS.md` 和 accepted ADR，是后续实现时的 P0/P1 级约束：

- 外部模型调用必须走 adapter，业务模块不能直连 provider endpoint。
- 关键状态迁移必须写入 per-session append-only event journal。
- 新增 MVP-relevant event name 前必须更新 ADR-002 / canonical registry。
- ToolCall、ToolResult、UserPatch、SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq`。
- old `plan_version` 的 ToolResult 默认只能进入 stale evidence，不能推进 current task。
- Composer 不得改写 SemanticCommitment facts。
- MVP 工具只能运行在 demo sandbox，不能真实外部写、支付、预订、删除或外部通信。
- 前端 UI 状态变化必须通过 Tool Executor 和 `TOOL_UI_STATE_PATCHED`。
- webSearch 是 untrusted evidence，不是 instruction。
- Raw audio、raw debug trace、local replay cache、secret、unredacted real user input、large raw web content 不得提交。
- 每个 MVP slice 完成前必须有 replay scenario 或 eval case。
- 不得静默扩大 MVP scope，尤其 MVP-3 只允许替换 adapter。

## 11. 当前值得注意的问题

1. **没有 Git repository metadata。** 当前目录执行 `git status` 会失败。这不影响读文档，但会影响后续分支、diff、commit、PR 工作流。

2. **当前还没有实现代码。** 所有 `src/voice_agent`、`tests`、fixture 和 runner 都还停留在 backlog 设计中。

3. **open questions 还没有全部产品化。** 例如 MVP-0 是否需要前端、playback progress 频率、semantic_close/assistant_directedness mock 策略、MVP-2 工具集合、webSearch mock 还是真 API、CoverageCheck 实现方式等。

4. **MVP-0 scope 很窄。** 这是有意设计。不要在 MVP-0 顺手做真实模型、真实工具、SlowTask 或 Composer coverage，否则会破坏 ADR-012 的 slice 验证目标。

## 12. 推荐下一步

如果要开始实现，建议严格从 `docs/implementation/mvp0-backlog.md` 的 Slice 0 开始：

1. 初始化 Git 仓库或确认真实仓库根目录。
2. 创建最小 Python package skeleton 和测试目录。
3. 先写 fixture safety tests，确保 `.gitignore` 和 synthetic fixture 规则生效。
4. 再实现 event envelope、registry validator、append-only journal。
5. 每个 slice 都同步添加 synthetic replay fixture 和 deterministic replay/eval assertion。

优先级上，不建议先接真实 Qwen3-Omni / GLM / TTS endpoint。这个项目的设计纪律是先用 mock skeleton 验证 live-loop 边界，再在 MVP-3 替换真实 adapters。
