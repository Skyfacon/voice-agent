# 快慢双系统语音 Agent

> 实时接住用户，后台推进任务，并让每一次承诺都有据可查。

![快慢双系统语音 Agent](assets/presentation/01-hero-fast-slow-agent.png)

`voice-agent` 关注的不是“把语音接到大模型上”，而是实时语音 Agent 的控制面：当用户打断、补充约束、修改意图，或工具结果延迟返回时，系统仍然能够保持交互不断线、任务状态一致、执行边界清晰。

**核心判断：快系统负责响应，慢系统负责承诺。**

我们设想的最终形态，是一个真正的实时任务副驾驶：它能在用户说话时保持在线，在复杂任务中持续吸收新约束，在需要行动时主动确认，在完成之后还能解释每一步为什么发生。用户感受到的是自然流动的语音协作，系统内部运行的是一套快慢协同、事实可追踪、行动可治理的 Agent 控制面。

## 1. 设计命题

传统语音助手常被组织成一条串行链路：

```text
Speech -> ASR -> LLM -> TTS
```

这条链路适合短问答，但很难支撑真实任务型语音交互：

- 用户可能在助手播报时插话，系统需要先处理实时交互时序。
- 用户可能在任务进行中继续补充约束，系统需要持续任务状态。
- 工具结果可能属于旧计划，系统需要判断它能否推进当前任务。
- 最终回答听起来可以自然，但事实来源必须可验证。

`voice-agent` 的目标是把语音助手从级联模型链路，升级为一个可追踪、可确认、可回放的实时任务控制面。

## 2. 系统总览

![实时语音 Agent 控制平面架构](assets/presentation/03-fast-slow-architecture.png)

这张图里最重要的不是模块数量，而是职责所有权：

- **Duplex / Interaction Controller** 先处理实时输入、打断、截断和 turn commit。
- **Router** 只做快慢路径分流，不直接改写复杂任务事实。
- **SlowTask** 拥有复杂任务事实、计划版本、证据审查、确认状态和最终语义承诺。
- **Composer** 负责把事实说自然，但不能改写事实。
- **Event Journal** 是关键状态迁移的事实来源，支撑 replay、审计和评估。

<details>
<summary>查看 Mermaid 技术版架构图</summary>

```mermaid
flowchart LR
    User["用户语音 / 文本"]
    Access["Access Layer<br/>输入 span metadata"]
    Duplex["Duplex<br/>speech / barge-in / directedness"]
    IC["Interaction Controller<br/>turn ingress / truncate policy"]
    ASR["ASR Adapter"]
    Thinker["Fast Thinker"]
    Router{"Router"}
    Fast["快系统输出<br/>短答 / 澄清 / 前台承接"]
    Slow["SlowTask<br/>任务事实 / plan_version / evidence"]
    Tool["Tool Executor<br/>授权 / sandbox / UI patch"]
    Commit["SemanticCommitment<br/>最终事实承诺"]
    Composer["Composer<br/>spoken realization"]
    Talker["Talker / Playback"]
    Journal[("Event Journal<br/>append-only source of truth")]
    Replay["Replay / Eval"]

    User --> Access
    Access --> Duplex
    Access --> IC
    Duplex --> IC
    IC -->|"TURN_INGRESS_COMMITTED"| ASR
    IC -->|"TURN_INGRESS_COMMITTED"| Thinker
    ASR --> Router
    Thinker --> Router
    Router -->|"FAST_ONLY"| Fast
    Router -->|"SPAWN / PATCH"| Slow
    Slow --> Tool
    Tool --> Slow
    Slow --> Commit
    Fast --> Composer
    Commit --> Composer
    Composer --> Talker
    Talker --> User

    Access -.-> Journal
    Duplex -.-> Journal
    IC -.-> Journal
    Router -.-> Journal
    Slow -.-> Journal
    Tool -.-> Journal
    Commit -.-> Journal
    Composer -.-> Journal
    Talker -.-> Journal
    Journal --> Replay
```

</details>

## 3. 快慢双系统

快慢之分不是“小模型 vs 大模型”，而是两种不同责任边界。

| 系统 | 目标 | 典型职责 | 不应该做什么 |
| --- | --- | --- | --- |
| 快系统 | 低延迟、不中断、前台体验 | 打断处理、短回应、澄清、轻问答、Router 分流 | 不对复杂任务作最终事实承诺 |
| 慢系统 | 高后果、可验证、任务推进 | 计划、证据、工具、确认、stale result、SemanticCommitment | 不绕过授权边界直接执行动作 |

快系统让用户感到系统一直在线；慢系统保证真正的任务事实不被抢跑。两者之间由 Router 显式分流，而不是让模型文本隐式决定系统行为。

## 4. 任务如何流动

![实时语音任务 Agent 的任务变化处理流程](assets/presentation/04-task-flow-storyboard.png)

这条链路体现了项目最核心的状态观：

- 用户补充不是直接改任务，而是先进入 UserPatch evidence。
- 计划变化通过 `plan_version` 显式推进。
- 旧计划工具结果默认进入 stale evidence。
- 最终回答来自 SemanticCommitment，而不是 Composer 临场发挥。

<details>
<summary>查看事件时序版</summary>

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant IC as Interaction Controller
    participant R as Router
    participant S as SlowTask
    participant T as Tool Executor
    participant C as Composer
    participant J as Event Journal

    U->>IC: 提出复杂请求
    IC->>J: TURN_INGRESS_COMMITTED
    IC->>R: committed turn + ASR/Thinker evidence
    R->>J: ROUTER_DECISION_EMITTED: SPAWN_SLOW_TASK
    R->>S: 创建慢任务
    S->>J: SLOWTASK_CREATED, PLANNING_STARTED
    S->>T: current-plan tool request
    T->>J: TOOL_EXECUTION_STARTED
    U->>IC: 补充约束或修正
    IC->>R: new committed turn
    R->>J: ROUTER_DECISION_EMITTED: PATCH_ACTIVE_SLOW_TASK
    R->>S: UserPatch evidence
    S->>J: USER_PATCH_RECEIVED, PLAN_VERSION_ADVANCED
    T-->>S: old-plan ToolResult
    S->>J: TOOL_RESULT_MARKED_STALE, STALE_EVIDENCE_RECORDED
    S->>J: SEMANTIC_COMMITMENT_EMITTED
    S->>C: commitment facts
    C->>J: SPOKEN_PLAN_EMITTED + checks
```

</details>

## 5. 可信执行边界

![语音 Agent 安全推进机制](assets/presentation/05-trust-boundaries.png)

一个能办事的语音 Agent，需要把“模型输出”转化成可治理的系统行为。

| 边界 | 设计要求 |
| --- | --- |
| Adapter boundary | ASR、Thinker、Slow LLM、TTS 等外部模型必须通过 adapter，并声明 capability matrix。 |
| Event Journal | 关键状态迁移必须写入 per-session append-only event journal。 |
| Plan binding | ToolCall、ToolResult、UserPatch、SemanticCommitment 必须绑定 `task_id`、`plan_version`、`task_event_seq`。 |
| Stale policy | 旧计划结果不得推进当前任务，除非 SlowTask 显式 adopt/rebase。 |
| Tool authorization | 工具执行必须经过授权边界，高风险动作先预览、再确认、再执行。 |
| Composer contract | Composer 只做表达融合，不得改写 immutable facts、tool status、risk warnings。 |
| Replay discipline | 默认 replay 不重跑真实模型、真实工具、网络、时钟或随机数。 |

这些边界让系统不仅“会说”，还知道自己什么时候不能说、不能做、不能把旧证据当成当前事实。

## 6. 工程原则：让愿景可落地

这个蓝图不依赖某一个“万能模型”突然解决所有问题，而是把实时语音 Agent 拆成可替换、可验证、可治理的系统边界。模型可以变，工具可以变，业务场景可以变，但控制面需要长期稳定。

| 原则 | 目标形态 |
| --- | --- |
| 模型能力插件化 | ASR、Thinker、Slow LLM、TTS 都通过 adapter 接入，能力差异通过 capability matrix 显式表达。 |
| 状态事实账本化 | 关键状态进入 Event Journal，让系统能解释自己如何理解、如何行动、如何承诺。 |
| 复杂任务有 owner | SlowTask 持有任务事实、计划版本和证据，不让多轮语音补充变成 prompt 漂移。 |
| 行动经过授权边界 | Tool Executor 负责确认、授权、幂等、风险等级和执行结果，模型不能用一句话直接驱动外部动作。 |
| 表达和事实分离 | Composer 让回答更自然，但不能改写事实、风险提示、工具状态或确认结果。 |
| 回放成为基础能力 | Replay 不只是调试工具，而是评估、审计、复盘和持续改进的底座。 |

最终我们希望构建的不是一个“更会聊天”的语音助手，而是一个可以逐步接入真实工具、真实任务和真实业务约束的任务型 Agent 操作系统。

## 7. 演进路线

```mermaid
flowchart LR
    P1["实时交互底座<br/>turn / interrupt / playback"]
    P2["慢任务系统<br/>UserPatch / plan_version"]
    P3["工具执行闭环<br/>authorization / result / UI patch"]
    P4["真实模型接入<br/>ASR / Thinker / Slow LLM / TTS"]
    P5["真实语音体验<br/>streaming mic / full-duplex / real TTS"]
    P6["生产级 Agent<br/>privacy / eval / audit / external tools"]

    P1 --> P2 --> P3 --> P4 --> P5 --> P6
```

演进的关键不是把功能堆得更满，而是让实时交互、慢任务推理、工具执行、语义承诺和回放评估在同一套控制面上持续生长。

## 一句话总结

`voice-agent` 的核心是一个实时语音任务 Agent 控制面：快系统保持交互不断线，慢系统治理任务事实和执行承诺，Event Journal 让系统在事后仍然说得清每一步为什么发生。
