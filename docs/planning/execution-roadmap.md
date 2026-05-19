# 执行路线 Roadmap：System Spine + Model Spikes

## Status

accepted planning baseline, updated with current implementation status。

本文档是执行路线设计，不是新的架构决策，不替代 ADR，不授权扩大 MVP scope。实现时仍以 `AGENTS.md`、`stage_b_adr_register.md`、`docs/adr/*.md` 和 `docs/specs/*.md` 为准。

历史说明：本文最初创建时只产出规划文档，不创建 `src/` 或 `tests/`。当前仓库已经按本文的 System Spine 路线完成 MVP-0 walking skeleton、MVP-1 SlowTask/UserPatch mock/replay spine 和 MVP-2 deterministic demo/replay acceptance；本文现在用于记录路线、当前进展和后续阶段边界。

## Source of Truth

- `AGENTS.md`
- `stage_b_adr_register.md`
- `docs/project-overview.md`
- `docs/architecture-book.md`
- `docs/adr-traceability-matrix.md`
- `docs/implementation/mvp0-backlog.md`
- `docs/implementation/mvp1-backlog.md`
- `docs/implementation/mvp2-closeout.md`
- `docs/implementation/mvp2-closeout.zh.md`
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/mvp0-acceptance-scenarios.md`
- `docs/specs/mvp1-acceptance-scenarios.md`
- `docs/specs/mvp2-acceptance-scenarios.md`
- `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
- `docs/adr/ADR-002 Event Journal, Timing Model, and Replay Foundation.md`
- `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
- `docs/adr/ADR-004 SlowTask Plan Versioning and Stale Result Policy.md`
- `docs/adr/ADR-005 Demo Tool Sandbox, Progressive Tool Invocation, and Side Effect Policy.md`
- `docs/adr/ADR-006 Router Task Focus and Single Active SlowTask MVP.md`
- `docs/adr/ADR-008 ASR Thinker Evidence Fusion and SlowTask-led Conflict Resolution.md`
- `docs/adr/ADR-009 SemanticCommitment and Thinker-as-Composer Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/adr/ADR-012 MVP Vertical Slice and Development SLOs.md`
- `docs/adr/ADR-014 webSearch Evidence Boundary for Demo Tools.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`

## Context

当前仓库是 live 态语音 Agent 的架构基线、Python control-plane、MVP-0 本地实现、MVP-1 mock/replay 实现和 MVP-2 deterministic demo/replay acceptance 仓库。它已经有 accepted ADR、architecture book、event registry、state reducers、replay spec、model adapter capability spec、MVP-0 / MVP-1 backlog、MVP-2 closeout、MVP-0 / MVP-1 / MVP-2 synthetic replay fixtures 和 acceptance runners。

目标系统不是传统 `ASR -> LLM -> TTS` 级联，而是：

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

这个系统最硬的风险不在某个单模型是否可用，而在实时 turn ingress、interrupt/truncate、event journal、replay、adapter boundary、plan_version、stale evidence、tool sandbox 和 Composer fact boundary 是否被从一开始守住。

## Decision

采用双泳道路线：

1. **System Spine**
   自顶向下实现 MVP-0 / MVP-1 control-plane spine。先用 faithful mock 打通 Event Journal、Replay、Interaction Controller、Router skeleton、Mock Adapter、Talker playback、Barge-in / Truncate 因果链，再验证 single active SlowTask、UserPatch、plan_version、stale evidence、confirmation 和 mock SemanticCommitment。

2. **Model Spikes**
   自底向上并行做真实模型能力探针，但不接入主流程。每个 spike 只回答模型能力问题，并沉淀 capability matrix、risk report 和 adapter profile 输入。

两条泳道的交汇点是 **Adapter Contract Hardening**：System Spine 给出真实事件、replay、状态和 SLO 需求；Model Spikes 给出候选模型能力缺口。只有二者对齐后，MVP-3 才能把 mock adapter 替换为 real adapter。

## Rationale

### 为什么不能纯自底向上

纯自底向上会优先实现 ASR、Thinker、Slow LLM、TTS、VAD 等单模块，再尝试拼系统。这会带来以下风险：

- 真实模型调用容易绕过 ADR-011 adapter boundary。
- ASR / Thinker 可能在 `TURN_INGRESS_COMMITTED` 前被调用，破坏 ADR-001。
- 早期行为没有 Event Journal，不满足 ADR-002 和 ADR-012 的 replay 要求。
- 模型能力会被误当成架构能力，例如 streaming、timestamps、cancellation、structured JSON、TTS truncate。
- 各模块单测通过后，仍可能无法解释 barge-in 到 truncate 的 causality。
- ToolResult / UserPatch / SemanticCommitment 若没有 `task_id + plan_version + task_event_seq`，后续很难补救。

### 为什么不能纯自顶向下

纯自顶向下只做 mock skeleton，也有明显盲区：

- faithful mock 可以证明边界，但不能证明真实模型支持这些边界。
- Mock TTS 可以瞬间 truncate，但真实 TTS 可能只返回完整 audio blob。
- Mock Slow LLM 可以稳定 JSON，但真实模型可能 schema drift 或字段缺失。
- Mock Thinker 可以输出 emotion/audio caption/semantic_close，但真实候选未必支持。
- 到 MVP-3 才发现模型能力缺口，会导致 adapter contract 大改或 scope 漂移。

### 为什么采用 System Spine + Model Spikes

System Spine 保护架构事实：所有关键状态迁移必须进 event journal，所有 slice 必须能 replay/eval，所有 mock 都必须标注为 mock。

Model Spikes 保护能力事实：候选模型必须逐项回答 capability matrix 字段，不能把 demo 成功当成 runtime integration 成功。

两者结合后，项目可以先证明 live loop 的骨架，再把真实模型逐步接入 adapter，而不是让 provider-specific 行为倒逼架构改形。

## Timeline Coupling

| 时间点 | System Spine 产物 | Model Spikes 产物 | 当前状态 | 互相校验方式 |
| --- | --- | --- | --- | --- |
| Phase 0 | planning docs、MVP-0 plan 准备 | spike plan 准备 | 已完成 | 确认模型探针不接主流程。 |
| Phase 1 | MVP-0 event/replay/mock skeleton | ASR/TTS/Duplex 初步能力证据 | System Spine 已完成；model spikes 未接主流程 | 检查 mock 是否声明了真实候选不支持的能力。 |
| Phase 2 | System Spine 继续按 MVP backlog 走 | ASR/Thinker/Slow LLM/TTS/VAD/RAG reports | 待推进 | 所有发现进入 capability/risk，不进入 runtime。 |
| Phase 3 | adapter events、degradation、validation gate | 候选 capability profiles | 待推进 | 形成 `adapter-capability-profiles.md`。 |
| Phase 4 | MVP-1 SlowTask mock + replay | Slow LLM structured JSON 风险 | System Spine 已完成；model spike 风险仍待实测 | 校验 plan_version/stale policy 是否能承受真实模型失败。 |
| Phase 5 | MVP-2 tools/composer/checks + replay/eval | Thinker/Composer/web evidence 风险 | System Spine 已完成 deterministic demo/replay acceptance | 校验 Composer 不改写事实，webSearch 只进 evidence。 |
| Phase 6 | MVP-3 real adapter replacement | model selection shortlist | planning next；real adapter runtime 未实现 | 只替换 adapter，不新增架构能力。 |

## Phase Roadmap

### Phase 0: repo / doc / spec readiness

**当前状态**

已完成。Roadmap、model spike plan、MVP-0 walking skeleton plan 和项目入口文档已存在；本次更新修正了“尚未实现”的过时描述。

**目标**

让仓库进入可执行路线状态，明确后续文档、任务顺序、scope gate 和 review gate。

**不做什么**

- 不创建 `src/`。
- 不创建 `tests/`。
- 不实现 runtime。
- 不接真实模型。
- 不新增架构能力。

**主要产物**

- `docs/planning/execution-roadmap.md`
- `docs/research/model-spike-plan.md`
- `docs/planning/mvp0-walking-skeleton-plan.md`
- `docs/project-overview.md`

**涉及文档 / ADR**

- `AGENTS.md`
- `stage_b_adr_register.md`
- ADR-001 / ADR-002 / ADR-003 / ADR-011 / ADR-012 / ADR-015

**文件或目录状态**

- 当前创建：`docs/planning/`
- 当前创建：`docs/research/`
- 当前也已存在：`src/`、`tests/`，它们来自后续 MVP-0 implementation slices。

**验证方式**

- `git diff --check`
- `git status --short`
- 人工检查：无 ADR 冲突、无 MVP scope 扩大、无实现代码。

**Replay / eval 要求**

本阶段不需要 runtime replay fixture，但必须把后续每个 MVP slice 的 replay/eval gate 写清楚。

**完成标准**

- Roadmap 和 model spike plan 分别提交。
- 用户审阅并拍板是否进入 MVP-0 implementation plan。

**主要风险**

- 规划文档写成事实 ADR。
- 文档暗示可绕过 adapter。
- 误把 spike 结果当成 MVP runtime 验收。

### Phase 1: MVP-0 walking skeleton

**当前状态**

已完成。当前 main 已实现 Slice 0-9，并通过 `./scripts/test -q`。MVP-0 仍保持 mock-only：没有真实模型、SlowTask、tools、Composer coverage 或 frontend UI patching。

**目标**

按 `docs/implementation/mvp0-backlog.md` 的 Slice 0-9，实现一条 MVP-0 walking skeleton：

```text
Access Layer
  -> Event Journal
  -> Duplex mock/rule
  -> Interaction Controller
  -> mock ASR / mock Thinker
  -> Router FAST_ONLY / IGNORE skeleton
  -> mock Talker / Playback
  -> Barge-in / Truncate
  -> deterministic Replay
```

**不做什么**

- 不接真实 ASR / Thinker / Slow LLM / TTS。
- 不实现 SlowTask。
- 不实现 UserPatch plan_version flow。
- 不实现工具调用。
- 不实现 Composer coverage。
- 不实现 pause/resume。
- 不实现真实 semantic_close / assistant-directedness。

**主要产物**

- Event envelope 和 append-only journal。
- Mock adapter capability snapshot。
- MVP-0 deterministic reducers。
- Text ingress through Interaction Controller。
- Audio span + mock Duplex accept path。
- Mock ASR / Thinker after commit。
- Router FAST_ONLY / IGNORE skeleton。
- Mock Talker playback progress。
- `BARGE_IN_CANDIDATE -> INTERRUPT_CANDIDATE -> TTS_TRUNCATE_REQUESTED -> TTS_TRUNCATED`。
- MVP-0 synthetic replay fixtures。
- MVP-0 acceptance runner。

**涉及文档 / ADR**

- ADR-001 / ADR-002 / ADR-003 / ADR-010 / ADR-011 / ADR-012 / ADR-015
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/mvp0-acceptance-scenarios.md`
- `docs/implementation/mvp0-backlog.md`

**文件或目录状态**

以下路径原本是后续实现目标，当前已经随 MVP-0 Slice 0-9 落地：

- `src/voice_agent/events/`
- `src/voice_agent/state/`
- `src/voice_agent/replay/`
- `src/voice_agent/access/`
- `src/voice_agent/duplex/`
- `src/voice_agent/interaction/`
- `src/voice_agent/understanding/`
- `src/voice_agent/router/`
- `src/voice_agent/talker/`
- `src/voice_agent/adapters/`
- `src/voice_agent/privacy/`
- `tests/fixtures/replay/mvp0/`
- `tests/events/`
- `tests/state/`
- `tests/replay/`
- `tests/interaction/`
- `tests/duplex/`
- `tests/understanding/`
- `tests/router/`
- `tests/talker/`
- `tests/slo/`
- `tests/acceptance/`

**验证方式**

- 单元测试覆盖 envelope、journal、reducers、text/audio ingress、Router ordering、playback、truncate。
- MVP-0 acceptance runner 覆盖：
  - `MVP0-TEXT-INGRESS-001`
  - `MVP0-AUDIO-INGRESS-001`
  - `MVP0-BARGE-IN-TRUNCATE-001`
  - `MVP0-MOCK-ADAPTER-CAPABILITY-001`
  - `MVP0-LOCAL-TRACE-SAFETY-001`

**Replay / eval 要求**

- deterministic replay 重建 `InteractionState`、`PlaybackState`、`AdapterHealthState`、`TracePrivacyState`。
- replay 不得调用模型、工具、网络、时钟或随机数。
- fixture 必须 synthetic / redacted / minimal。

**完成标准**

- Text input 走 `TEXT_INPUT_RECEIVED -> TURN_OPENED -> TURN_INGRESS_ACCEPTED -> TURN_INGRESS_COMMITTED`。
- Audio input 走 audio span + Duplex events + Interaction commit。
- Mock ASR / Thinker 只在 `TURN_INGRESS_COMMITTED` 后输出。
- Router 只在 post-commit 做 FAST_ONLY / IGNORE。
- Playback 有唯一 `playback_span_id` 和 `playback_offset_ms`。
- Barge-in 到 truncate 因果链可 replay，且三个 offset 不混淆。
- 所有 mock capability 和 SLO 结果标注 mock。

**主要风险**

- Access Layer 直接进入 Router。
- ASR/Thinker 抢在 Interaction commit 前运行。
- `PLAYBACK_COMMITTED` 被误当成用户已理解。
- mock capability 被当成 real capability。
- fixture 泄露 raw audio / raw trace / secret / unredacted real input。

### Phase 2: model capability spikes

**目标**

隔离验证候选模型能力，产出 capability matrix、risk report、selection evidence。

**不做什么**

- 不接入主 runtime。
- 不让业务模块直接调 provider endpoint。
- 不提交 raw audio / raw trace / secrets / unredacted real input。
- 不把 webSearch 或 RAG 内容当 instruction。

**主要产物**

- `docs/research/model-spike-plan.md`
- 后续：`docs/research/spikes/*.md`
- 后续：`docs/research/model-selection.md`

**涉及文档 / ADR**

- ADR-003 / ADR-008 / ADR-009 / ADR-010 / ADR-011 / ADR-012 / ADR-014
- `docs/specs/model-adapter-capabilities.md`

**预计文件或目录**

- `docs/research/spikes/`
- `docs/research/model-selection.md`

**验证方式**

- 每个 spike 有问题清单、合成输入、capability matrix、risk report。
- 当前模型信息、API 行为、license、部署方式必须在执行 spike 时查官方来源并记录日期。

**Replay / eval 要求**

- Spike 本身不是 runtime replay。
- 可把 spike case 后续转成 synthetic / redacted eval case。

**完成标准**

- ASR、Thinker、Slow LLM、TTS、Duplex/VAD、Embedding/RAG 至少有明确执行计划。
- MVP-3 候选 shortlist 不再依赖口头印象。

**主要风险**

- spike 演变成平行 runtime。
- raw provider trace 或音频样本误提交。
- 将 spike success 当成 adapter integration success。

### Phase 3: adapter contract hardening

**目标**

把 System Spine 的事件需求和 Model Spikes 的能力结果收敛成可执行 adapter profiles、validation rules、degradation rules。

**不做什么**

- 不接真实模型进主流程。
- 不新增架构边界。
- 不隐藏 unsupported capability。
- 不让无 truncate 能力的 TTS 通过 barge-in target validation。

**主要产物**

- `docs/specs/adapter-capability-profiles.md`
- `docs/research/model-selection.md`
- adapter health / timeout / retry / validation failure / degradation event gate。

**涉及文档 / ADR**

- ADR-002 / ADR-010 / ADR-011 / ADR-012
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`

**预计文件或目录**

- `docs/specs/adapter-capability-profiles.md`
- 后续实现：`src/voice_agent/adapters/`
- 后续测试：`tests/adapters/`

**验证方式**

- 每个 profile 覆盖 required capability fields。
- 每个 unsupported capability 显式选择 `block_feature`、`disable_scenario`、`degrade_to_text_only`、`mock_fallback`、`require_confirmation` 或 `record_degradation_event`。

**Replay / eval 要求**

- adapter health、degradation、schema validation failure、retry/failure 都必须可 replay 或可 eval。

**完成标准**

- 真实 adapter 进入主流程前必须有 profile。
- 系统能区分 `real` / `mock` / `fallback` / `degraded`。

**主要风险**

- profile 过度 provider-specific。
- adapter docs 与代码漂移。
- schema validation 缺失导致 bad output 偷渡 downstream。

### Phase 4: MVP-1 SlowTask mock

**当前状态**

已完成。当前 checkout 已有 `MVP1Router`、`TaskFocusState`、`SlowTaskState`、`MockSlowTaskRuntime`、`UserPatchEvidencePackRuntime`、plan_version advance、stale evidence with/without adoption、waiting-slot、cancel/switch confirmation、failed terminal stickiness、mock SemanticCommitment、MVP-1 deterministic fixtures 和 acceptance runner。该阶段仍保持 mock-only：没有真实 Slow LLM、真实 Tool Executor、demo tools、Composer、frontend UI patch 或真实 adapter integration。

**目标**

实现 SlowTask mock、single active SlowTask、TaskFocusState、UserPatch evidence pack、`plan_version`、`task_event_seq`、stale ToolResult policy、mock SemanticCommitment。

**不做什么**

- 不实现真实 Slow LLM reasoning。
- 不实现真实工具执行。
- 不支持多个 active SlowTask。
- 不支持 pause/resume。
- 不接受 stale ToolResult 推进 current plan，除非有 `STALE_EVIDENCE_ADOPTED`。

**主要产物**

- `TaskFocusState`
- UserPatch pipeline
- SlowTask mock state machine
- plan_version advance
- stale evidence chain
- mock SemanticCommitment
- MVP-1 replay fixtures

**涉及文档 / ADR**

- ADR-004 / ADR-006 / ADR-007 / ADR-008 / ADR-011 / ADR-012 / ADR-016
- `docs/specs/event-registry.md`
- `docs/specs/state-reducers.md`
- `docs/specs/replay-spec.md`

**文件或目录状态**

- `src/voice_agent/slowtask/`
- `src/voice_agent/user_patch/`
- `tests/slowtask/`
- `tests/user_patch/`
- `tests/fixtures/replay/mvp1/`

**验证方式**

- Router focus tests。
- UserPatch evidence tests。
- SlowTask transition table tests。
- plan_version / stale ToolResult tests。
- SemanticCommitment current-plan tests。

**Replay / eval 要求**

- replay 重建 `TaskFocusState` 和 `SlowTaskState`。
- stale ToolResult case 必须覆盖 with / without adoption。
- eval 统计 patch misrouting、ambiguity detection、wrong resolution。

**完成标准**

- single active SlowTask 可运行并可 replay。
- material patch advance plan_version。
- irrelevant / foreground chat 不 advance plan_version。
- old-plan ToolResult 默认进入 stale evidence。

**主要风险**

- Router 开始解释最终任务语义。
- UserPatch 直接改 task goal / constraints。
- confirmation / cancel 绕过 SlowTask ownership。

### Phase 5: MVP-2 demo tools and Composer coverage

**当前状态**

已完成 deterministic demo/replay acceptance。当前 main 已覆盖 demo sandbox tools、progressive Tool Executor events、`TOOL_UI_STATE_PATCHED` replay、demo destructive confirmation gates、webSearch evidence boundary、Thinker-as-Composer、CommitmentCoverageCheck、ProgressTruthfulnessCheck、MVP-2 fixtures 和 acceptance runner。该阶段仍不是产品服务、真实 frontend demo、真实 model adapter、真实 TTS、真实工具或真实外部 side-effect integration。

**目标**

证明 demo sandbox tool、progressive tool invocation、UI state patch、light confirmation、Thinker-as-Composer、CommitmentCoverageCheck、ProgressTruthfulnessCheck。

**不做什么**

- 不做真实外部写操作。
- 不做 payment / booking / deletion。
- 不让前端根据模型文本直接改 UI。
- 不让 Composer 改写 SemanticCommitment facts。
- 不让 webSearch 进入 instruction 区。

**主要产物**

- demo tool manifests。
- Tool Executor progressive protocol。
- demo backend sandbox。
- `TOOL_UI_STATE_PATCHED`。
- `DEMO_DESTRUCTIVE_ACTION` confirmation gate。
- Composer role contract。
- Coverage / truthfulness checks。
- webSearch prompt-injection synthetic eval case。

**涉及文档 / ADR**

- ADR-005 / ADR-008 / ADR-009 / ADR-010 / ADR-013 / ADR-014 / ADR-016
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`

**文件或目录状态**

- `src/voice_agent/tools/`
- `src/voice_agent/demo_backend/`
- `src/voice_agent/composer/`
- `src/voice_agent/checks/`
- `tests/tools/`
- `tests/composer/`
- `tests/fixtures/replay/mvp2/`

**验证方式**

- 至少 3 个 demo tool 通过 progressive protocol。
- `DEMO_DESTRUCTIVE_ACTION` 无 current-plan `CONFIRMATION_ACCEPTED` 时被阻止。
- `TOOL_UI_STATE_PATCHED` 可 replay。
- CoverageCheck 阻止 immutable facts / must-say fields 被改写。
- ProgressTruthfulnessCheck 阻止虚假进度。
- webSearch 标记为 `UNTRUSTED_WEB_EVIDENCE`。

**Replay / eval 要求**

- replay tool manifest、partial args、authorization、execution、progress、UI patch、result、failure、retry、cancel。
- replay `SEMANTIC_COMMITMENT_EMITTED -> SPOKEN_PLAN_EMITTED -> CHECK -> PLAYBACK`。

**完成标准**

- demo tools 展示“边说边做”，但只操作 sandbox。
- Composer 只做 spoken realization。
- Tool Executor 是 UI patch 和 tool execution 的唯一入口。

**主要风险**

- demo tool 变成真实外部副作用工具。
- UI 被模型文本直接驱动。
- Composer 变成第二个事实源。
- webSearch 污染 policy。

### Phase 6: MVP-3 real adapter integration

**当前状态**

可进入 Phase 0 planning / contract work，但不应直接接 provider endpoint。当前还缺 `docs/specs/adapter-capability-profiles.md`、真实 adapter output-mode contract tests、real/fallback/degraded replay gates、real adapter runtime assembly gate，以及真实 adapter 并发/迟到回调进入 Event Journal 的 serialization contract。

**目标**

在不新增架构能力的前提下，把 mock adapter 替换为真实 ASR、Thinker、Slow LLM、TTS adapter。

**不做什么**

- 不新增多个 active SlowTask。
- 不新增 pause/resume。
- 不新增真实外部副作用工具。
- 不新增生产隐私策略。
- 不绕过 adapter。

**主要产物**

- real ASR adapter。
- real Thinker adapter。
- real Slow LLM adapter with structured JSON validation。
- real TTS / Talker adapter。
- healthcheck / timeout / retry / failure / degradation events。
- updated model selection and capability profiles。

**涉及文档 / ADR**

- ADR-001 / ADR-002 / ADR-003 / ADR-004 / ADR-009 / ADR-010 / ADR-011 / ADR-012 / ADR-016
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`
- `docs/specs/adapter-capability-profiles.md`
- `docs/research/model-selection.md`

**预计文件或目录**

- `src/voice_agent/adapters/`
- `tests/adapters/`
- `tests/fixtures/replay/mvp3/`
- `tests/eval/` 或 ADR-approved eval directory。

**验证方式**

- 每个 real adapter 有 healthcheck 和 capability snapshot。
- Slow LLM / Composer structured output 有 schema validation。
- timeout / retry / failure / degradation 均记录 canonical events。
- trace 不记录 secrets。

**Replay / eval 要求**

- 默认 replay 不重跑真实模型。
- adapter output 标记 `real` / `fallback` / `degraded`。
- re-eval replay 必须显式 opt-in，并标记 regenerated output。

**完成标准**

- ASR / Thinker / Slow LLM / TTS 至少各接一个真实 adapter。
- 所有真实输出、fallback、degradation 可在 trace/replay 中区分。
- MVP-3 没有新增架构能力。

**主要风险**

- provider schema 泄漏到业务模块。
- unsupported streaming / timestamps / cancellation / truncate 被静默假设。
- real trace 泄露 secrets 或 unredacted user data。

## First Tasks

当前状态：ROAD-001 到 ROAD-004 已完成；MVP0-001 到 MVP0-010 已完成；MVP-1 mock/replay closeout 已完成；MVP-2 deterministic demo/replay acceptance 已完成。

| task id range | 当前状态 | 证据 |
| --- | --- | --- |
| ROAD-001..004 | 已完成 | Roadmap、model spike plan、project overview update、MVP-0 walking skeleton plan 均已存在。 |
| ROAD-005 | 可选/未单独落地 | 当前已有 `.gitignore`、`.worktrees/` exclusion 和 branch history；如需要更正式 workflow，可后续补 `docs/planning/development-workflow.md`。 |
| MVP0-001..010 | 已完成 | `src/voice_agent/`、`tests/`、`tests/fixtures/replay/mvp0/manifest.index.json` 已存在；`./scripts/test -q` 通过。 |
| MVP1-000..010 | 已完成 | `src/voice_agent/slowtask/`、`src/voice_agent/user_patch/`、`tests/slowtask/`、`tests/user_patch/`、`tests/fixtures/replay/mvp1/manifest.index.json` 和 `tests/acceptance/test_mvp1_acceptance_scenarios.py` 已存在。 |
| MVP2-000..008 | 已完成 | `src/voice_agent/tools/`、`src/voice_agent/demo_backend/`、`src/voice_agent/composer/`、`src/voice_agent/checks/`、`tests/fixtures/replay/mvp2/manifest.index.json` 和 `tests/acceptance/test_mvp2_acceptance_scenarios.py` 已存在。 |

后续优先任务应从 Phase 2 model capability spikes、Phase 3 adapter contract hardening，或 Phase 6 MVP-3 Phase 0 planning / contract PR 中选择。不要在同一 PR 中直接接真实 provider endpoint。

## Directory and Document Recommendations

当前已创建：

- `docs/planning/execution-roadmap.md`
- `docs/research/model-spike-plan.md`
- `docs/planning/mvp0-walking-skeleton-plan.md`
- `src/voice_agent/`
- `tests/`
- `tests/fixtures/replay/mvp0/`
- `tests/fixtures/replay/mvp1/`
- `tests/fixtures/replay/mvp2/`
- `src/voice_agent/slowtask/`
- `src/voice_agent/user_patch/`
- `src/voice_agent/tools/`
- `src/voice_agent/demo_backend/`
- `src/voice_agent/composer/`
- `src/voice_agent/checks/`

后续建议创建：

- `docs/research/model-selection.md`
- `docs/research/spikes/`
- `docs/specs/adapter-capability-profiles.md`
- `tests/fixtures/replay/mvp3/` for adapter output/failure/degraded replay once MVP-3 planning defines the contract。

当前仍不应提交：

- `diagnostics/`
- `traces/`
- `replays/local/`
- `audio/raw/`

## Validation Method

执行路线自检：

| 检查项 | 结果 |
| --- | --- |
| 是否和 accepted ADR 冲突 | 否。路线以 ADR-001/002/003/011/012/016 为硬约束。 |
| 是否扩大 MVP scope | 否。MVP-0 到 MVP-3 范围沿用 ADR-012。 |
| 是否把 mock 当成 real capability | 否。mock 必须标注 mock；spike 不算 runtime validation。 |
| 是否遗漏 replay/eval | 否。除 Phase 0 外，每个阶段都有 replay/eval gate。 |
| 是否允许模型绕过 adapter | 否。真实模型只能通过 adapter 进入 runtime。 |
| 是否让 webSearch 进入 instruction 区 | 否。webSearch 只作为 `UNTRUSTED_WEB_EVIDENCE`。 |
| 是否允许真实外部副作用工具 | 否。MVP 工具仅限 demo sandbox。 |
| 当前是否已有实现代码 | 是。MVP-0 local walking skeleton、MVP-1 mock/replay spine 和 MVP-2 deterministic demo/replay acceptance 已实现；本文不把它升级为服务、真实 frontend、真实工具或真实模型集成。 |

## Consequences

正向结果：

- 最早验证 live voice agent 的核心风险：turn、interrupt、truncate、replay。
- mock 与 real 能力界限清楚。
- 模型选型不会倒逼业务模块绕过 adapter。
- MVP slice 有清晰 replay/eval 出口。

代价：

- 前期文档和 fixture 纪律较重。
- 完整产品体验会晚于一个“快速模型 demo”。
- 每个阶段都需要维护 mock/degraded/real 标签。

## Open Questions

- MVP-3 Phase 0 是否先以文档/spec PR 补 `adapter-capability-profiles.md`，再进入代码实现？
- MVP-3 首批真实 adapter 是否允许用最容易接入的候选，而不是最理想候选？
- 真实 adapter 并发/迟到回调是否通过单线程 dispatcher 进入 Event Journal，还是先补明确 async serialization boundary？
- Runtime assembly gate 应先支持 mock/real/fallback/degraded profile injection，还是先只做配置和 contract tests？
- 是否需要在真实 frontend demo 前先单独规划 frontend scope，而不是回填到 MVP-2 或 MVP-3？
