# ADR-012 MVP Vertical Slice and Development SLOs

## Status

accepted

## Context

live 语音 Agent 的完整目标包括全双工、实时语音理解、闲聊、复杂任务、SlowTask、UserPatch、工具调用、前端 demo 状态、trace/replay、模型 adapter、自部署模型等。若 MVP 同时追求全部能力，很容易每个模块都半真半 mock，最后无法证明任何关键架构假设。

Stage A 已确认第一阶段最先证明：

> event-driven live loop + interrupt + trace/replay + module boundary

而不是先证明完整复杂任务能力，也不是先追求真实模型下的完整 live 体验。

因此需要明确 MVP vertical slices 和 development SLO，防止范围漂移。

## Decision

MVP 拆分为四个 vertical slices：

### MVP-0: Event-driven live loop skeleton

目标：证明模块边界、事件驱动、interrupt/truncate、trace/replay。

Scope:

- mock audio/text input through canonical ingress events (`TEXT_INPUT_RECEIVED` for text; `AUDIO_SPAN_STARTED` / `AUDIO_SPAN_ENDED` plus Duplex events for audio)
- DuplexEvent
- Interaction / Turn Controller
- per-session event journal
- Router
- mock Thinker
- mock TTS / Talker
- playback_span_id / playback_offset_ms
- interrupt / truncate
- local replay
- basic frontend demo loop if available
- text input must go through Interaction Controller as `TEXT_INPUT_RECEIVED` -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`; it does not pass through Duplex and does not create a synthetic `audio_span_id`

不要求：

- 真实 ASR
- 真实 Thinker
- 真实 Slow LLM
- 真实 TTS
- SlowTask
- tool calling
- semantic_close 真能力
- assistant-directedness 真能力
- pause/resume

### MVP-1: SlowTask mock and UserPatch consistency

目标：证明慢任务生命周期、UserPatch evidence pack、plan_version、一致性和 stale result policy。

Scope:

- single active SlowTask
- TaskFocusState
- UserPatch evidence pack
- SlowTask mock
- plan_version advance
- task_event_seq
- SlowTask lifecycle transition table per ADR-016
- stale ToolResult policy mock
- SemanticCommitment mock
- ASR/Thinker evidence fusion mock
- replay SlowTask state

不要求：

- 真实 Tool Executor
- 真实外部工具
- 真实 Slow LLM reasoning
- 多 active SlowTask
- 高级 confirmation flow beyond ADR-016 MVP confirmation state

### MVP-2: Demo tools, confirmation-light, and Composer coverage

目标：证明网页 demo 工具链、渐进式工具调用、前端 UI patch、SemanticCommitment 到 SpokenPlan 的事实保护。

Scope:

- demo backend sandbox
- progressive tool invocation
- 手电筒 / 备忘录 / 天气 / 闹钟 / webSearch mock or demo API
- `TOOL_UI_STATE_PATCHED`
- `DEMO_DESTRUCTIVE_ACTION` light confirmation
- Tool authorization gate per ADR-016
- Thinker-as-Composer
- CommitmentCoverageCheck
- ProgressTruthfulnessCheck
- truthful progress feedback
- replay tool progress and frontend state

不要求：

- 真实外部写操作
- payment / booking / deletion real side effects
- production-grade privacy
- production-grade auth

### MVP-3: Real adapter integration without new architecture

目标：接入真实 ASR / Thinker / Slow LLM / TTS adapter，但不新增架构能力。

Scope:

- ASR final transcript or text projection
- Thinker basic SemanticFrame
- Thinker-as-Composer SpokenPlan or fallback
- Slow LLM structured JSON output
- TTS basic audio synthesis
- HTTP/WebSocket healthcheck
- adapter capability matrix
- timeout / retry / structured error events
- self-hosted endpoint config where applicable

不要求：

- 新增多任务并发
- 新增真实外部副作用工具
- 新增 pause/resume
- 新增生产隐私策略
- 新增目标架构 full duplex semantic model

Development SLO targets:

- speech_start detection latency: <= 150ms
- barge-in to TTS truncate command: <= 250ms
- speech_end after silence: 500-800ms configurable
- first acknowledgement latency: <= 800ms
- TTS first audio after spoken plan: <= 800ms
- SlowTask first progress feedback: <= 2s
- SlowTask progress cadence: every 5-10s when still working
- false barge-in rate: must be measurable in replay
- patch misrouting rate: must be measurable in eval

这些 SLO 是 development SLO，不是最终产品承诺。若 mock 或 adapter 不具备真实能力，SLO 结果必须标注 mock / degraded / real。

Scope control rules:

1. 每个 MVP slice 必须能独立 demo 和 replay。
2. 不允许为了 MVP-0 偷偷实现 MVP-2 的工具体系。
3. 不允许为了 MVP-2 引入真实外部副作用工具。
4. MVP-3 只替换 adapter，不新增架构能力。
5. 每个 slice 完成前，必须有 replay scenario 或 eval case。
6. 未被 event journal 记录的行为，不算该 slice 验证通过。
7. mock 能力必须标记为 mock，不能冒充 real capability。

## Alternatives Considered

1. 一个大 MVP 同时实现所有能力。
   风险高，难以定位失败原因，也无法验证架构边界。

2. 先做完整复杂任务能力，再做 live loop。
   会偏离 live 语音 Agent 的核心风险：实时中断、turn、trace/replay。

3. 先接真实模型，再搭 mock skeleton。
   真实模型不确定性会掩盖架构问题，调试成本高。

4. 先做纯文本 Agent。
   实现简单，但无法验证 audio timing、barge-in、playback commitment 等关键问题。

## Consequences

正向结果：

- 每个阶段都有明确可验证目标。
- 先证明最核心 live loop 风险。
- mock 和真实 adapter 的能力边界清楚。
- demo 工具和真实外部工具被隔离。
- SLO 可用于开发调试和回归评估。

代价：

- 完整产品能力会被推迟。
- 一些用户可见能力在早期是 mock。
- 需要维护 slice-by-slice replay/eval。
- MVP-3 不能顺手加新架构能力，可能需要额外纪律。

## Impacted Modules

- 全系统
- Event Journal
- Duplex
- Interaction / Turn Controller
- Router
- Thinker
- Talker
- SlowTask
- UserPatch Pipeline
- Tool Executor
- Demo Backend
- Frontend Demo
- Model Adapters
- Trace / Replay
- Evaluation Harness
- Repository Governance

## Validation Method

MVP-0 完成条件：

1. mock input 到 mock TTS 的 live loop 可运行。
2. interrupt/truncate 可触发并记录。
3. replay 能重建 InteractionState。
4. SLO 指标至少能被计算。
5. 所有 mock capability 被标记。

MVP-1 完成条件：

1. SlowTask mock 生命周期可 replay。
2. UserPatch 绑定 task_id / plan_version / task_event_seq。
3. plan_version advance 可 replay。
4. stale ToolResult 不推进 current plan。
5. TaskFocusState 能防止明显误 patch。

MVP-2 完成条件：

1. 至少 3 个 demo tool 可通过 progressive protocol 调用。
2. 前端状态 patch 可 replay。
3. `DEMO_DESTRUCTIVE_ACTION` 有 light confirmation。
4. Thinker-as-Composer 输出 SpokenPlan。
5. CoverageCheck 能阻止关键事实改写。
6. truthful progress feedback 不编造状态。

MVP-3 完成条件：

1. 真实 adapter capability matrix 可读取。
2. ASR / Thinker / Slow LLM / TTS 至少各接入一个真实或远程 endpoint。
3. adapter failure / timeout / retry 可通过 `ADAPTER_REQUEST_FAILED` / `ADAPTER_REQUEST_RETRYING` 等 canonical events 记录。
4. 真实 adapter 接入不新增架构能力。
5. mock 与 real 输出在 trace 中可区分。

## Open Questions

- MVP-0 是否需要前端页面，还是 CLI/local replay 先足够？
- MVP-2 至少 3 个 demo tool 选哪几个作为首批？
- webSearch 在 MVP-2 是 mock 还是真实搜索 API？
- SLO 是否在本地 Mac 上计算，还是只记录指标不设硬 gate？
- MVP-3 是否必须包含 Qwen3-Omni 和 GLM5.1，还是允许先接更易用的替代 endpoint？
- 每个 MVP slice 是否需要单独 demo script / replay fixture？
