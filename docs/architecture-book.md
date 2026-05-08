# Architecture Book / 架构书

Source of truth: frozen ADR Baseline v0.4 from `AGENTS.md` and `docs/adr/*.md`。

本文档把 accepted architecture decisions 编译成 implementation-facing specification。标注 ADR ID 的语句来自 frozen baseline；标注为 `spec detail, derived from ADR baseline` 的语句是从 ADR baseline 派生的实现规格，不新增架构能力。

## 1. Executive Summary / 执行摘要

voice-agent MVP 是一个 event-driven live voice loop，具备严格模块边界、replayable state、adapter-mediated model access、sandbox-only demo tools。MVP-0 证明 turn ingress、interrupt/truncate、event journal、trace/replay、mock adapter boundaries。MVP-1 增加 single active SlowTask、UserPatch evidence packs、plan versioning、stale result handling。MVP-2 增加 progressive demo tools、UI state patches、demo destructive actions 的 confirmation、Thinker-as-Composer、coverage/truthfulness checks。MVP-3 只把 mocks 替换为 real adapters，不新增架构能力。[ADR-001, ADR-002, ADR-003, ADR-004, ADR-005, ADR-009, ADR-011, ADR-012, ADR-016]

所有 critical state transitions 必须写入 per-session append-only event journal。Replay 从 recorded events 重建 state，默认不重跑真实模型或工具。[ADR-002, ADR-010]

任何业务模块不得直接调用 external model endpoints。ASR、Thinker、Composer、Slow LLM、TTS、Duplex model、Embedding/RAG 都必须通过 adapters，并声明 capability matrix 与 output mode labels。[ADR-011, AGENTS.md]

## 2. System Goals and Non-Goals / 系统目标与非目标

### Goals / 目标

- 证明 audio/text ingress 通过 canonical events 和 Interaction Controller。[ADR-001, ADR-002, ADR-012]
- 支持 truncate-only barge-in，并保留 playback offsets 和 replayable causal links。[ADR-003]
- 以 per-session event journal 作为 trace、replay、plan version consistency、SLO measurement 的基础。[ADR-002]
- 保持 Router 是 post-commit gate，而不是 deep semantic interpreter。[ADR-006, ADR-008]
- 保持 SlowTask 是 complex task state、confirmation state、resolved arguments、stale evidence、SemanticCommitment 的 owner。[ADR-004, ADR-007, ADR-008, ADR-016]
- MVP 工具保持在 demo sandbox 内，并通过 Tool Executor 执行。[ADR-005, ADR-016]
- 确保 Composer 不能改写 SemanticCommitment facts，不能编造 progress。[ADR-009, ADR-013]
- Trace/replay 对本地调试有用，同时阻止 raw audio、raw trace、secrets、PII、unredacted real user input 进入 shareable fixtures 或 GitHub。[ADR-010, ADR-015, AGENTS.md]

### Non-Goals / 非目标

- MVP-0 不要求 real ASR、real Thinker、real Slow LLM、real TTS、SlowTask、tools、true semantic_close、true assistant-directedness、pause/resume。[ADR-012]
- MVP-1 不要求 real Tool Executor、real external tools、real Slow LLM reasoning、multiple active SlowTasks 或超出 ADR-016 MVP confirmation state 的高级 confirmation。[ADR-012]
- MVP-2 不允许 real external writes、payment、booking、deletion、production privacy、production auth。[ADR-005, ADR-012]
- MVP-3 不得在集成 real adapters 时新增 architecture capability。[ADR-012]
- Multi active SlowTask、pause/resume、production privacy、real side-effect tools 是 post-MVP，必须先有后续 ADR。[ADR-012, ADR-015, ADR-016]

## 3. Frozen ADR Baseline Summary / 冻结 ADR 基线摘要

| ADR | accepted decision summary |
| --- | --- |
| ADR-001 | 拆分 Duplex realtime gate、deterministic Interaction Controller、post-commit semantic routing。 |
| ADR-002 | 建立 per-session append-only event journal、timing model、canonical event registry、replay foundation。 |
| ADR-003 | 使用 truncate-only barge-in，保留 playback reference、`BARGE_IN_CANDIDATE`、`TTS_TRUNCATE_REQUESTED`、`TTS_TRUNCATED`。 |
| ADR-004 | SlowTask events 绑定 `task_id`、`plan_version`、`task_event_seq`；stale ToolResult 不能推进 current plan，除非显式 adopted/rebased。 |
| ADR-005 | MVP tools 通过 demo backend sandbox 和 progressive Tool Executor protocol 运行；阻断真实外部副作用。 |
| ADR-006 | 支持 single active SlowTask，并由 Router-owned TaskFocusState 负责 post-commit task focus classification。 |
| ADR-007 | UserPatch 是 evidence pack，不是 semantic mutation 或 task patch conclusion。 |
| ADR-008 | ASR/Thinker differences 作为 multi-source evidence；SlowTask 拥有 ambiguity/conflict resolution。 |
| ADR-009 | SemanticCommitment 是 complex-task fact source；Composer 只做 spoken realization，并受 coverage checks 约束。 |
| ADR-010 | 定义 debug-first、repo-safe trace/replay policy 和 fixture boundaries。 |
| ADR-011 | 要求所有 model access 通过 adapters，并具备 capability matrices、health events、degradation/output-mode labels。 |
| ADR-012 | 定义 MVP-0 到 MVP-3 vertical slices 和 development SLOs。 |
| ADR-013 | progress feedback 必须 grounded in actual state events，并通过 ProgressTruthfulnessCheck。 |
| ADR-014 | webSearch 标记为 `UNTRUSTED_WEB_EVIDENCE`；只能放在 evidence，不得进入 instruction context。 |
| ADR-015 | 通过 `AGENTS.md` 建立 repo-level governance 和不可违反的 implementation rules。 |
| ADR-016 | 定义 SlowTask lifecycle、confirmation ownership、tool authorization gate、cancellation、retry、stale handling。 |

## 4. Module Ownership / 模块所有权

| Module | Responsibilities | Non-responsibilities | Owned state |
| --- | --- | --- | --- |
| Access Layer | 接收 user text/audio，发出 input/audio span events。[ADR-001, ADR-002] | 不 commit turns，不 route semantics，不决定 interrupts。[ADR-001] | Input span metadata；不拥有 turn。 |
| Duplex / Realtime Audio Controller | pre-ASR realtime audio facts、directedness/semantic-close candidates、barge-in candidates。[ADR-001, ADR-003] | 不 commit turns，不解释 tasks，不做 final tool/SlowTask decisions。[ADR-001] | Realtime audio candidate state；echo/barge-in 所需 playback reference。 |
| Interaction Controller | deterministic turn ingress 和 playback interruption policy applier。[ADR-001] | 不是 semantic model；不 cancel SlowTasks，不 authorize tools。[ADR-001, ADR-016] | `InteractionState`。 |
| Event Journal | per-session append-only fact record、causal index、timing model、replay source。[ADR-002] | 不是 global blocking message bus。[ADR-002] | Event sequence、envelope metadata、redaction level metadata。 |
| ASR Adapter | normalize ASR output 或 mock transcript/text projection。[ADR-011] | 不拥有 semantic truth 或 turn ingress。[ADR-001, ADR-008] | Adapter request/output metadata and capability status。 |
| Thinker / Fast System | foreground support、lightweight replies、SemanticFrame hints、emotion/audio caption/intent/slot hints。[ADR-008, ADR-009] | 不仲裁 ASR/Thinker conflicts，不拥有 complex-task commitments。[ADR-008, ADR-009] | Adapter output metadata；不拥有 SlowTask state。 |
| Router | post-commit FAST_ONLY/SPAWN/PATCH/IGNORE decisions 和 TaskFocusState。[ADR-006] | 不解释 final UserPatch semantics，不 cancel tasks，不 rewrite goals，不 authorize tools，不选择 ASR/Thinker winner。[ADR-006, ADR-008, ADR-016] | `TaskFocusState`。 |
| UserPatch Pipeline | 为 active SlowTask 构造 evidence packs。[ADR-007] | 不直接 mutate task goals、slots、constraints 或 plan version。[ADR-007] | Patch envelope and evidence refs。 |
| SlowTask Runtime | complex task state、plan version、task_event_seq、evidence review、confirmations、stale evidence、SemanticCommitment。[ADR-004, ADR-008, ADR-016] | 不拥有 turn ingress、Router focus 或 direct tool execution。[ADR-001, ADR-006, ADR-016] | `SlowTaskState`、confirmation state、current plan、resolved arguments、stale evidence。 |
| Tool Executor | manifest validation、argument/provenance validation、authorization、idempotency、sandbox execution、UI patches、tool result normalization。[ADR-005, ADR-016] | 不直接 mutate SlowTask state，不执行 blocked real side-effect tools。[ADR-005, ADR-016] | `ToolExecutionState` and tool execution metadata。 |
| Thinker-as-Composer | 将 SemanticCommitment/progress 转换成带 style/persona 的 SpokenPlan。[ADR-009, ADR-013] | 不能 rewrite facts、authorize tools、infer confirmations 或 invent progress。[ADR-009, ADR-013, ADR-016] | SpokenPlan draft metadata；不拥有 facts。 |
| Coverage / Truthfulness Checkers | playback 前检查 Commitment coverage 和 progress truthfulness。[ADR-009, ADR-013] | 不创造 task facts 或 tool state。[ADR-009, ADR-013] | Check result metadata。 |
| Talker / Playback | TTS 或 mock playback、playback progress、playback commitment、truncate execution。[ADR-003] | 不合成 facts，不 commit semantics，不决定 barge-in policy。[ADR-001, ADR-003] | `PlaybackState`、playback offsets and span ids。 |
| Trace / Replay Runtime | local replay、shareable fixture export boundary、state digest、replay markers。[ADR-002, ADR-010] | 默认 replay 不重跑真实 models/tools，不在 shareable fixtures 存 raw audio。[ADR-010] | Replay run state and fixture/export metadata。 |
| Adapter Registry | startup capability snapshot 和 adapter health/degradation events。[ADR-011] | 不隐藏 unsupported capabilities 或 provider-specific schema failures。[ADR-011] | `AdapterHealthState` and capability snapshot refs。 |
| Privacy / Redaction | redact/block secrets，并 enforce trace domain boundaries。[ADR-010, ADR-015] | 不允许 raw secrets 进入任何 trace domain。[ADR-010] | `TracePrivacyState`, redaction audit metadata。 |

## 5. Control Plane vs Data Plane / 控制面与数据面

Control plane events 是 state and policy decisions：session lifecycle、adapter capability snapshots、turn ingress events、Router decisions、TaskFocusState updates、SlowTask lifecycle events、plan version events、confirmation events、tool authorization events、coverage/truthfulness checks、trace/replay markers、privacy/redaction events。[ADR-002, ADR-004, ADR-006, ADR-009, ADR-010, ADR-011, ADR-016]

Data plane artifacts 是 referenced payloads：audio chunks、audio refs、text refs、ASR/Thinker frame refs、evidence refs、result refs、UI patch refs、SpokenPlan text/audio refs、replay fixture refs。Event payloads 应优先使用 refs 和 redacted summaries，而不是 raw sensitive inline data。[ADR-002, ADR-007, ADR-010]

Spec detail, derived from ADR baseline: control plane events 必须足以 replay state reducers，且不要求 raw data plane payloads。Data plane refs 在 shareable fixtures 中可以缺失，只要 redacted summaries 保留 state transition semantics。

## 6. Runtime Event Flow / 运行时事件流

Canonical high-level flow:

1. Session Runtime 记录 `SESSION_STARTED` 和 `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`。[ADR-002, ADR-011]
2. Access Layer 记录 text 或 audio ingress。[ADR-001, ADR-002]
3. Duplex 在 ASR/Thinker 前分析 audio ingress，并发出 realtime facts/candidates。Text bypasses Duplex but not Interaction Controller。[ADR-001]
4. Interaction Controller 打开、接受/拒绝/hold、commit turns。只有 `TURN_INGRESS_COMMITTED` 才进入 ASR/Thinker/Router。[ADR-001]
5. ASR/Thinker adapters 发出带 output mode labels 的 mock/real/fallback/degraded frames。[ADR-002, ADR-011]
6. Router 发出 post-commit decision，并在需要时更新 TaskFocusState。[ADR-006]
7. Fast output 可进入 Composer/Talker；slow work 进入 SlowTask 和 UserPatch/plan-version lifecycle。[ADR-006, ADR-009, ADR-016]
8. Tool Executor 在 MVP-2 处理 progressive tool events 和 UI patches。[ADR-005, ADR-016]
9. SemanticCommitment 或 progress events 通过 Composer 形成 SpokenPlan，再经 coverage/truthfulness checks 后进入 Talker playback。[ADR-009, ADR-013]
10. Trace / Replay 从 recorded events 重建 state，并产生 replay markers/state digest。[ADR-002, ADR-010]

## 7. Audio Input Path / 音频输入路径

**Responsibilities / 职责**

Access Layer 创建 `AUDIO_SPAN_STARTED`、可选 `AUDIO_CHUNK_RECEIVED`、`AUDIO_SPAN_ENDED`；Duplex 发出 speech 和 candidate events；Interaction Controller 决定 ingress。[ADR-001, ADR-002]

**Non-responsibilities / 非职责**

Audio path 不允许 ASR/Thinker 决定首次 ingress commit，也不允许 Access Layer route semantics。[ADR-001]

**Owned state / 拥有状态**

Access Layer 拥有 audio span metadata；Duplex 拥有 realtime candidate state；Interaction Controller 拥有 committed turn state。[ADR-001]

**Input events / 输入事件**

`AUDIO_SPAN_STARTED`, `AUDIO_CHUNK_RECEIVED`, `AUDIO_SPAN_ENDED`, `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`, `LOW_CONFIDENCE_INGRESS`。[ADR-002]

**Output events / 输出事件**

`TURN_OPENED`, `TURN_HELD`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_INGRESS_COMMITTED`；commit 后才允许 mock/real ASR and Thinker frame events。[ADR-001, ADR-002]

**Invariants / 不变量**

- 没有 `TURN_INGRESS_COMMITTED`，不得为 audio span 产生 ASRFrame/SemanticFrame。[ADR-001, ADR-002]
- Audio spans 使用 `audio_span_id`；默认不存 raw audio。[ADR-007, ADR-010]
- Directedness 和 semantic_close 在 MVP-0 可 mock/rule-based，但必须 honest labeling。[ADR-011, ADR-012]

**Failure modes / 失败模式**

- Low confidence directedness 或 semantic close 导致 hold/reject，而不是 speculative semantic routing。[ADR-001]
- 默认 replay 缺失 raw audio 时，只重建 event state，不重跑 audio inference。[ADR-010]
- unsupported timestamps 或 semantic_close capability 必须显式 degrade。[ADR-011]

**Validation / replay scenarios / 验证与回放场景**

- Audio start opens a turn and sets `turn_phase=COLLECTING_INPUT`。[ADR-001]
- Audio end with accepted policy emits `TURN_INGRESS_COMMITTED`。[ADR-001]
- Audio rejected or held never enters ASR/Thinker。[ADR-001, ADR-002]

## 8. Text Input Path / 文本输入路径

**Responsibilities / 职责**

Access Layer 记录 `TEXT_INPUT_RECEIVED`；Interaction Controller open、accept、commit turn。[ADR-001, ADR-002]

**Non-responsibilities / 非职责**

Text input 不经过 Duplex，不得创建 synthetic `audio_span_id`。Access Layer 不得 bypass Interaction Controller 直接进入 Router。[ADR-001, ADR-002]

**Owned state / 拥有状态**

`input_span_id`、`text_span_id`、`input_modality=text`、redacted text/text refs 属于 input metadata；turn state 属于 Interaction Controller。[ADR-001, ADR-002]

**Input events / 输入事件**

`TEXT_INPUT_RECEIVED`；可选 policy-triggered text-during-playback interrupt path。[ADR-002]

**Output events / 输出事件**

`TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_COMMITTED`；若 policy 中断 playback，则可选 `INTERRUPT_CANDIDATE` 和 `TTS_TRUNCATE_REQUESTED`。[ADR-001, ADR-002]

**Invariants / 不变量**

- Text ingress 的 `audio_span_id=null`。[ADR-001, ADR-002]
- Text ingress 使用 `directedness=ASSUMED_DIRECTED` 和 `semantic_close=ASSUMED_CLOSED`。[ADR-001, ADR-002]
- Text ingress 必须能通过 canonical interaction events replay。[ADR-002]

**Failure modes / 失败模式**

- Text arrives during playback 时，只有 Interaction Controller policy 能决定是否 interrupt。[ADR-001]
- Raw text 必须按照 trace domain 使用 redacted 字段或 refs。[ADR-007, ADR-010]

**Validation / replay scenarios / 验证与回放场景**

- Text path 必须发出 `TEXT_INPUT_RECEIVED` -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`。[ADR-001, ADR-002, ADR-012]

## 9. Interaction Controller and Turn Ingress / 交互控制器与 turn ingress

**Responsibilities / 职责**

Deterministically reduce Duplex/text/access events plus current `InteractionState`、`TaskFocusState` summary、SlowTask summary、playback state、policy，输出 finalized interaction events。[ADR-001]

**Non-responsibilities / 非职责**

它不是 semantic model，不使用 ASRFrame/SemanticFrame 做首次 ingress commit，不拥有 SlowTask cancel/confirmation/tool authorization。[ADR-001, ADR-016]

**Owned state / 拥有状态**

`InteractionState`，包含 `turn_phase`、`playback_phase`、`directedness`、`semantic_close`、current turn/input/audio/text/playback span ids、last ingress outcome、last interaction event id。[ADR-001]

**Input events / 输入事件**

access/audio/text events、Duplex candidate/verdict events、`BARGE_IN_CANDIDATE`、`TTS_TRUNCATED`、playback status、policy state。[ADR-001, ADR-002]

**Output events / 输出事件**

`TURN_OPENED`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_HELD`, `TURN_INGRESS_COMMITTED`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `WAITING_USER`。Confirmation 等待由 SlowTask/ADR-016 的 `WAITING_FOR_USER_CONFIRMATION` 和 `CONFIRMATION_REQUIRED` 表达，不新增额外等待事件名。[ADR-001, ADR-002, ADR-016]

**Invariants / 不变量**

- Interaction Controller 是 turn ingress commit 的唯一 owner。[ADR-001]
- 所有 finalized interaction events 必须带足够 replay 的 causal links。[ADR-001, ADR-002]
- `PLAYBACK_COMMITTED` 是 delivery marker，不是 semantic acknowledgement。[ADR-001, ADR-002]

**Failure modes / 失败模式**

- Low-confidence ingress 变成 hold/reject，而不是 speculative semantic routing。[ADR-001]
- Missing playback state prevents target barge-in validation。[ADR-003]

**Validation / replay scenarios / 验证与回放场景**

- Replay 从 interaction 和 playback events 重建 `InteractionState`。[ADR-002]
- Text 和 audio paths 都必须经过 Interaction Controller 才能到 Router。[ADR-001, ADR-002]

## 10. Duplex / Realtime Audio Controller / 实时音频控制器

**Responsibilities / 职责**

pre-ASR speech start/end、VAD、playback overlap、echo likelihood、barge-in confidence、assistant-directedness candidate、semantic_close candidate、reject/hold/accept candidates。[ADR-001, ADR-003]

**Non-responsibilities / 非职责**

不 commit turns，不决定 task semantics，不 route tools，不拥有 SlowTask，不产生 final answers。[ADR-001]

**Owned state / 拥有状态**

Realtime audio analysis state、playback reference association、candidate confidence state。[ADR-001, ADR-003]

**Input events / 输入事件**

`AUDIO_SPAN_STARTED`, `AUDIO_CHUNK_RECEIVED`, `AUDIO_SPAN_ENDED`, playback reference/progress events。[ADR-002, ADR-003]

**Output events / 输出事件**

`SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `BARGE_IN_CANDIDATE`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`。[ADR-002]

**Invariants / 不变量**

- Barge-in judgment 必须保留 playback reference interface；无 playback reference 的 barge-in 只能算 demo mock。[ADR-003]
- Duplex semantic capability 只服务 realtime ingress，不是 task semantic authority。[ADR-001]

**Failure modes / 失败模式**

- Echo mistaken for user speech 会造成 false barge-in；必须通过 replay/eval 度量。[ADR-003, ADR-012]
- Unsupported semantic_close 或 directedness 必须显式 mock/rule-based/degraded。[ADR-011]

**Validation / replay scenarios / 验证与回放场景**

- Speech start/end 和 barge-in candidate chain 必须能 replay 到 Interaction decisions。[ADR-001, ADR-003]

## 11. Barge-in and TTS Truncate Flow / 打断与 TTS 截断

**Responsibilities / 职责**

检测 overlap，把它转换为 interrupt policy，发出 truncate request，并记录 actual truncation。[ADR-003]

**Non-responsibilities / 非职责**

MVP 不支持 pause/resume、semantic-clause resume、multi-track recovery、model-side cancellation guarantees。[ADR-003, ADR-012]

**Owned state / 拥有状态**

Duplex 拥有 candidate facts；Interaction Controller 拥有 interrupt decision and truncate request；Talker 拥有 playback/truncate execution。[ADR-001, ADR-003]

**Input events / 输入事件**

`PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `BARGE_IN_CANDIDATE`。[ADR-002, ADR-003]

**Output events / 输出事件**

`INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, final playback offset events。[ADR-002, ADR-003]

**Invariants / 不变量**

- 必须区分三类 offset：candidate-time `BARGE_IN_CANDIDATE.playback_offset_ms`、request-time `TTS_TRUNCATE_REQUESTED.cutoff_playback_offset_ms`、Talker-confirmed `TTS_TRUNCATED.actual_stop_offset_ms`。[ADR-003]
- `TTS_TRUNCATE_REQUESTED` 必须携带 `playback_span_id`、cutoff offset、causal link。[ADR-003]
- Talker 必须暴露 playback progress 和 unique `playback_span_id`。[ADR-003]

**Failure modes / 失败模式**

- Missing playback reference 会导致 target architecture validation fail。[ADR-003, ADR-011]
- TTS adapter without truncate capability 不能通过 barge-in target validation，必须记录 degradation。[ADR-011]

**Validation / replay scenarios / 验证与回放场景**

- Barge-in to truncate command latency target <= 250ms，且可从 journal events 计算。[ADR-003, ADR-012]
- Replay reconstructs causal chain from candidate to truncate。[ADR-003]

## 12. Thinker / ASR / Understanding Bundle / 理解组件

**Responsibilities / 职责**

ASR 提供 text projection；Thinker/Fast System 提供 SemanticFrame、audio/utterance summaries、emotion/audio caption/intent/slot hints、foreground replies、task-like/complexity hints。[ADR-008, ADR-009, ADR-011]

**Non-responsibilities / 非职责**

ASR 不是 sole semantic truth；Thinker 不拥有 SlowTask facts；Router 不得选择 ASR/Thinker winner。[ADR-008]

**Owned state / 拥有状态**

Adapter output refs、confidence/provenance metadata、output mode labels。[ADR-008, ADR-011]

**Input events / 输入事件**

`TURN_INGRESS_COMMITTED` and committed span refs。[ADR-001, ADR-002]

**Output events / 输出事件**

`MOCK_ASR_FRAME_EMITTED`, `MOCK_THINKER_FRAME_EMITTED`, real/fallback/degraded adapter output events, evidence refs。[ADR-002, ADR-011]

**Invariants / 不变量**

- 所有 model access 必须通过 adapters。[ADR-011, AGENTS.md]
- Outputs 必须能区分 real/mock/fallback/degraded。[ADR-011, ADR-012]
- 进入 SlowTask evidence 的 key fields 必须带 provenance。[ADR-008]

**Failure modes / 失败模式**

- Schema validation failure becomes `ADAPTER_OUTPUT_VALIDATION_FAILED`；unsupported capability becomes degradation/fail-fast event。[ADR-011]
- FAST_ONLY replies 必须避免对不确定 critical fields 作出 commitment。[ADR-008]

**Validation / replay scenarios / 验证与回放场景**

- MVP-0 只在 commit 后使用 mock ASR/Thinker。[ADR-002, ADR-012]
- Evidence fusion scenarios preserve ASR n-best and Thinker summary conflicts for SlowTask review。[ADR-007, ADR-008]

## 13. Router and TaskFocus Policy / Router 与任务焦点策略

**Responsibilities / 职责**

Post-commit gate to `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`；active SlowTask 存在时分类 task focus。[ADR-006]

**Non-responsibilities / 非职责**

不解释 final UserPatch semantics，不 cancel/pause tasks，不 authorize tools，不 rewrite goals，不仲裁 ASR/Thinker conflicts。[ADR-006, ADR-008, ADR-016]

**Owned state / 拥有状态**

`TaskFocusState`，包含 active task id、foreground mode、side conversation policy、default patch policy、ambiguous input policy、last focus decision/confidence/event id。[ADR-006]

**Input events / 输入事件**

`TURN_INGRESS_COMMITTED`、可用 ASR/Thinker evidence、current TaskFocusState、active SlowTask summary。[ADR-006]

**Output events / 输出事件**

`ROUTER_DECISION_EMITTED`, `TASK_FOCUS_STATE_UPDATED`, UserPatch construction trigger when patching active task。[ADR-002, ADR-006]

**Invariants / 不变量**

- MVP 只支持一个 active non-terminal SlowTask。[ADR-006]
- Ambiguous input 默认不得 patch active task；obvious foreground chat stays FAST_ONLY。[ADR-006]
- active task 存在时的 new task candidate 通过 UserPatch control evidence 和 SlowTask confirmation，而不是 automatic replacement。[ADR-006, ADR-016]

**Failure modes / 失败模式**

- Misrouting 会污染 active SlowTask；patch misrouting rate 必须可度量。[ADR-006, ADR-012]
- `NON_ASSISTANT` post-commit input 不得进入 SlowTask。[ADR-006]

**Validation / replay scenarios / 验证与回放场景**

- Replay 从 `ROUTER_DECISION_EMITTED` 和 `TASK_FOCUS_STATE_UPDATED` 重建 TaskFocusState。[ADR-002, ADR-006]

## 14. SlowTask Lifecycle / 慢任务生命周期

**Responsibilities / 职责**

拥有 SlowTaskState、current plan version、task_event_seq、goal/constraints/resolved arguments、confirmation state、stale/adopted evidence、terminal outcome、evidence review、ambiguity resolution、SemanticCommitment。[ADR-004, ADR-008, ADR-016]

**Non-responsibilities / 非职责**

不拥有 ingress、Router focus、direct tool execution、spoken realization。[ADR-001, ADR-006, ADR-016]

**Owned state / 拥有状态**

`SlowTaskState`、current `plan_version`、`task_event_seq`、task goal/constraints、resolved arguments、confirmation state、stale evidence、adopted/rebased evidence metadata、terminal outcome。[ADR-016]

**Input events / 输入事件**

`ROUTER_DECISION_EMITTED(SPAWN_SLOW_TASK)`, `USER_PATCH_RECEIVED`, `TOOL_RESULT_RECEIVED`, tool failure/cancel events, adapter failures, stale evidence events, confirmation-related UserPatch interpretations。[ADR-002, ADR-004, ADR-016]

**Output events / 输出事件**

`SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED`, `EVIDENCE_REVIEWED`, `AMBIGUITY_DETECTED`, `AMBIGUITY_RESOLVED`, `CLARIFICATION_REQUESTED`, `ARGUMENTS_RESOLVED`, `PLAN_VERSION_ADVANCED`, `TASK_REPLANNED`, `CONFIRMATION_REQUIRED`, `SLOWTASK_CANCEL_REQUESTED`, `SLOWTASK_CANCELLED`, `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_DEGRADED`, `SLOWTASK_FAILED`。[ADR-002, ADR-008, ADR-016]

**Invariants / 不变量**

- Every SlowTask state transition emits `SLOWTASK_STATE_CHANGED`。[ADR-016]
- Terminal states are `COMPLETED`, `CANCELLED`, `FAILED`；terminal tasks cannot be advanced by late UserPatch/ToolResult/confirmation。[ADR-016]
- SemanticCommitment 必须使用 current `plan_version`，若使用 stale evidence 必须记录 adopted stale evidence sources。[ADR-004]

**Failure modes / 失败模式**

- Old plan ToolResult becomes stale evidence，且不能推进 state，除非 explicitly adopted/rebased。[ADR-004, ADR-016]
- Pending confirmation 在 plan_version advance 后 invalid，必须 rejected 或 superseded。[ADR-016]
- Missing critical evidence causes clarification or insufficient-evidence events。[ADR-008, ADR-016]

**Validation / replay scenarios / 验证与回放场景**

- MVP-1 必须 replay create、planning、waiting-slot、replanning、completed、cancelled、failed、stale-result paths。[ADR-012, ADR-016]

## 15. UserPatch and Plan Versioning / 用户补丁与计划版本

**Responsibilities / 职责**

UserPatch pipeline 捕获 active SlowTask 的 authoritative evidence 和 non-authoritative hypotheses；SlowTask 根据 observed plan version 解释它。[ADR-004, ADR-007]

**Non-responsibilities / 非职责**

UserPatch 本身不是 plan、state mutation、goal rewrite、slot patch、confirmation 或 cancel。[ADR-007]

**Owned state / 拥有状态**

Patch id/envelope、source event refs、authoritative evidence refs、non-authoritative hypothesis fields、redaction metadata。[ADR-007]

**Input events / 输入事件**

Router patch decision、committed turn evidence、ASR/Thinker/Duplex/TaskFocus evidence。[ADR-006, ADR-007, ADR-008]

**Output events / 输出事件**

`USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, optional `PLAN_VERSION_ADVANCED`, optional `TASK_REPLANNED` / `PLANNING_RESTARTED`。[ADR-002, ADR-004, ADR-007]

**Invariants / 不变量**

- `USER_PATCH_RECEIVED.plan_version` is the pre-advance current plan version。[ADR-004, ADR-007]
- Not every UserPatch advances plan_version。[ADR-004, ADR-007]
- Secret-like content must be redacted or blocked before journal write。[ADR-007, ADR-010]

**Failure modes / 失败模式**

- Router misclassification becomes non-authoritative evidence，不得未经 interpretation 直接 mutate SlowTask。[ADR-006, ADR-007]
- Shareable replay 不能包含 unredacted real user input。[ADR-007, ADR-010]

**Validation / replay scenarios / 验证与回放场景**

- Replay reconstructs UserPatch -> interpretation -> optional plan advance causal chain。[ADR-004, ADR-007]

## 16. Tool Risk and Side Effect Policy / 工具风险与副作用策略

**Responsibilities / 职责**

Tool Executor 通过 adapters/manifests 运行所有 tools，验证 current plan、arguments、provenance、side-effect class、confirmation、idempotency，并 emit progressive tool events。[ADR-005, ADR-016]

**Non-responsibilities / 非职责**

Slow Agent 可以 propose tool calls，但不能直接调用 external services；Tool Executor 不能直接 mutate SlowTask state。[ADR-005, ADR-016]

**Owned state / 拥有状态**

ToolExecutionState、manifest version、authorization event refs、idempotency keys、retry/cancel state、UI patch refs。[ADR-005, ADR-016]

**Input events / 输入事件**

`ARGUMENTS_RESOLVED`, `CONFIRMATION_ACCEPTED`, `TOOL_MANIFEST_LOADED`, SlowTask current plan metadata, tool adapter responses。[ADR-005, ADR-016]

**Output events / 输出事件**

`TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`。[ADR-002, ADR-005, ADR-016]

**Invariants / 不变量**

- MVP allows `READ_ONLY`, `DRY_RUN`, `SANDBOX_WRITE`, confirmed `DEMO_DESTRUCTIVE_ACTION`；blocks `EXTERNAL_WRITE`, `EXTERNAL_COMMUNICATION`, `BOOKING_OR_PAYMENT`, real `DELETION`。[ADR-005, ADR-016]
- `DEMO_DESTRUCTIVE_ACTION` requires current-plan `CONFIRMATION_ACCEPTED`。[ADR-005, ADR-016]
- Frontend UI state changes only through `TOOL_UI_STATE_PATCHED`。[ADR-005, AGENTS.md]
- webSearch is evidence, not instruction。[ADR-014]

**Failure modes / 失败模式**

- Missing resolved arguments/provenance emits `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`；no execution starts。[ADR-008, ADR-016]
- Tool failure/retry/cancel 必须 journaled，并由 SlowTask interpret。[ADR-016]
- Old plan result is stale and cannot advance current state。[ADR-004, ADR-016]

**Validation / replay scenarios / 验证与回放场景**

- MVP-2 replays progressive tool call、UI patch、demo destructive confirmation、blocked real side-effect、stale result cases。[ADR-005, ADR-012, ADR-016]

## 17. SemanticCommitment and Composer Contract / 语义承诺与表达合成契约

**Responsibilities / 职责**

SlowTask emits SemanticCommitment；Thinker-as-Composer converts approved facts/progress into SpokenPlan；checkers verify coverage/truthfulness。[ADR-009, ADR-013]

**Non-responsibilities / 非职责**

Composer cannot modify immutable facts、delete must-say fields、authorize tools、infer confirmation、treat dry-run as execution、or use unadopted stale evidence as current fact。[ADR-009, ADR-013, ADR-016]

**Owned state / 拥有状态**

SlowTask owns SemanticCommitment；Composer owns SpokenPlan drafts；Coverage/Truthfulness checkers own check result metadata。[ADR-009, ADR-013]

**Input events / 输入事件**

`SEMANTIC_COMMITMENT_EMITTED`, SlowTask progress events, tool status, confirmation state, InteractionState summary, TaskFocusState summary, persona/style config。[ADR-009, ADR-013]

**Output events / 输出事件**

`SPOKEN_PLAN_EMITTED`, `COMMITMENT_COVERAGE_CHECK_PASSED`, `COMMITMENT_COVERAGE_CHECK_FAILED`, `PROGRESS_TRUTHFULNESS_CHECK_PASSED`, `PROGRESS_TRUTHFULNESS_CHECK_FAILED`。[ADR-002, ADR-009, ADR-013]

**Invariants / 不变量**

- Talker 只能在 coverage check passes 后播放 SemanticCommitment-derived speech。[ADR-009]
- Talker 只能在 progress truthfulness check passes 后播放 progress speech。[ADR-013]
- Progress must be grounded in actual state events。[ADR-013]

**Failure modes / 失败模式**

- Coverage/truthfulness failure blocks playback，并要求 retry、template fallback 或 degraded response。[ADR-009, ADR-013]
- Unsupported progress language is blocked。[ADR-013]

**Validation / replay scenarios / 验证与回放场景**

- Replay reconstructs SemanticCommitment/progress -> SpokenPlan -> check -> playback causal chain。[ADR-009, ADR-013]

## 18. Talker / Playback Control / 播放控制

**Responsibilities / 职责**

只为 approved SpokenPlan/output 启动 playback，报告 progress and committed offsets，执行 truncate，并 emit playback events。[ADR-003, ADR-009, ADR-013]

**Non-responsibilities / 非职责**

Talker 不创建 SemanticCommitment，不执行 coverage checks，不决定 barge-in policy。[ADR-003, ADR-009]

**Owned state / 拥有状态**

`PlaybackState`、current `playback_span_id`、offsets、approval check ref、truncate state。[ADR-003]

**Input events / 输入事件**

approved SpokenPlan/check pass events、`TTS_TRUNCATE_REQUESTED`、TTS adapter output。[ADR-003, ADR-009, ADR-013]

**Output events / 输出事件**

`PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `PLAYBACK_FINISHED`, `TTS_TRUNCATED`。[ADR-002, ADR-003]

**Invariants / 不变量**

- `PLAYBACK_COMMITTED` only a playback delivery marker, not proof of user comprehension or semantic acknowledgement。[ADR-001, ADR-002]
- Playback started for checked content must reference approved check event or check result。[ADR-009, ADR-013]
- Truncate support is required for target barge-in validation。[ADR-003, ADR-011]

**Failure modes / 失败模式**

- Missing truncate capability causes degraded/fail validation event。[ADR-011]
- Playback progress too sparse may reduce replay/SLO fidelity；progress frequency remains an ADR open question。[ADR-003]

**Validation / replay scenarios / 验证与回放场景**

- Replay verifies playback offset chain and truncate offsets。[ADR-003]

## 19. Trace / Replay / Privacy / 追踪、回放与隐私

**Responsibilities / 职责**

Record local debug traces、enforce export boundaries、replay events into state reducers、produce replay markers and state digest、redact/block secrets。[ADR-002, ADR-010]

**Non-responsibilities / 非职责**

Default replay 不重跑 real models/tools；shareable fixtures 不包含 raw audio、raw trace、secrets、PII、unredacted tool results、large raw web content。[ADR-010]

**Owned state / 拥有状态**

Replay run state、trace domain metadata、redaction/export status、state digest metadata。[ADR-010]

**Input events / 输入事件**

full event journal、redaction/export requests、replay requests。[ADR-002, ADR-010]

**Output events / 输出事件**

`REPLAY_STARTED`, `REPLAY_COMPLETED`, `TRACE_WRITE_DEGRADED`, `TRACE_SECRET_REDACTION_APPLIED`, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`。[ADR-002, ADR-010]

**Invariants / 不变量**

- Secrets never enter trace in raw form。[ADR-010, AGENTS.md]
- Raw audio is local debug opt-in only and never GitHub/shareable。[ADR-010, ADR-015]
- Shareable fixtures must be synthetic、redacted、or minimal。[ADR-010, ADR-015]

**Failure modes / 失败模式**

- Redaction failure blocks write/export and records blocked event。[ADR-010]
- Async persistence failure records degraded trace state。[ADR-002]

**Validation / replay scenarios / 验证与回放场景**

- MVP-0 local trace safety case verifies defaults、redaction、replay of InteractionState。[ADR-010, ADR-012]

## 20. Model Adapter Capability Contract / 模型适配器能力契约

**Responsibilities / 职责**

Adapter Registry records startup capability snapshot；adapters normalize provider output，report health、timeouts、retries、validation failures、degradations、output mode。[ADR-011]

**Non-responsibilities / 非职责**

Business modules 不能依赖 provider-specific APIs 或 hidden capabilities。[ADR-011]

**Owned state / 拥有状态**

Capability matrix、adapter health、error/retry policy、deployment mode、output mode refs。[ADR-011]

**Input events / 输入事件**

session startup、healthcheck requests、adapter requests、provider responses/errors/timeouts。[ADR-011]

**Output events / 输出事件**

`ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `ADAPTER_HEALTHCHECK_FAILED`, `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, `ADAPTER_OUTPUT_VALIDATION_FAILED`, `ADAPTER_OUTPUT_DEGRADED`, adapter frame/output events。[ADR-002, ADR-011]

**Invariants / 不变量**

- Unsupported capabilities 必须显式表达，不能 silently assumed。[ADR-011]
- Mock outputs 必须标记 mock，不能计作 real target validation。[ADR-011, ADR-012]
- Adapter must not log secrets。[ADR-011]

**Failure modes / 失败模式**

- No TTS truncate capability blocks target barge-in validation。[ADR-011]
- No structured JSON in Slow LLM triggers parser/validator retry then failure or fallback。[ADR-011]
- No emotion means unavailable, not neutral。[ADR-011]

**Validation / replay scenarios / 验证与回放场景**

- MVP-0 records mock capability snapshot；MVP-3 records real adapter capability and failures without adding architecture capability。[ADR-011, ADR-012]

## 21. MVP-0 / MVP-1 / MVP-2 / MVP-3 Scope / MVP 范围

### MVP-0

Proves event-driven live loop skeleton: mock audio/text ingress、Duplex events、Interaction Controller、event journal、Router、mock Thinker、mock TTS/Talker、playback offsets、interrupt/truncate、local replay、optional basic frontend loop。[ADR-012]

### MVP-1

Adds single active SlowTask、TaskFocusState、UserPatch、mock SlowTask lifecycle、plan_version、task_event_seq、stale ToolResult mock、SemanticCommitment mock、ASR/Thinker evidence fusion mock、SlowTask replay。[ADR-012]

### MVP-2

Adds demo backend sandbox tools、progressive invocation、at least three demo tools、`TOOL_UI_STATE_PATCHED`、demo destructive light confirmation、ADR-016 tool authorization gate、Thinker-as-Composer、CommitmentCoverageCheck、ProgressTruthfulnessCheck、truthful progress、tool/frontend state replay。[ADR-005, ADR-009, ADR-012, ADR-013, ADR-016]

### MVP-3

Integrates real adapters for ASR、Thinker、Slow LLM、TTS via capability contract and health/error events, without adding new architecture capability。[ADR-011, ADR-012]

## 22. Validation and Replay Strategy / 验证与回放策略

- 每个 MVP slice 完成前必须有 replay 或 eval scenarios。[ADR-012, AGENTS.md]
- MVP-0 scenarios 在 `docs/specs/mvp0-acceptance-scenarios.md` 中定义。[ADR-012]
- Event schemas 在 `docs/specs/event-registry.md` 中定义；reducers 在 `docs/specs/state-reducers.md` 中定义。这些是 ADR-002 派生的 spec details。[ADR-002]
- Replay modes and fixture boundaries 在 `docs/specs/replay-spec.md` 中定义。这些是 ADR-002 和 ADR-010 派生的 spec details。[ADR-002, ADR-010]
- Adapter capability and degradation mapping 在 `docs/specs/model-adapter-capabilities.md` 中定义。这是 ADR-011 派生的 spec detail。[ADR-011]
- Development SLOs 必须从 event timestamps 计算，并标注 mock/degraded/real。[ADR-012]

## 23. New ADR Required / 需要新 ADR 的情况

本 compilation pass 未在 frozen ADR baseline 内发现 P0 / P1-A contradiction。

实现以下内容为事实前，必须新增或更新 ADR：

- 把 non-canonical prompt labels，例如 `SEMANTIC_COMMITMENT_CREATED`, `SPOKEN_PLAN_CREATED`, `STALE_TOOL_RESULT_RECORDED` 当作新的 journal event names，而不是映射到 ADR-002 canonical events。[ADR-002]
- Multi active SlowTask、pause/resume SlowTask、pause/resume TTS、real external side-effect tools、production privacy policy、production auth。[ADR-012, ADR-015, ADR-016]
- 任何未在 ADR-002 注册的 MVP-relevant event name。[ADR-002, ADR-015]

## 24. Open Questions / 待定问题

以下是 frozen ADR open questions 的延续，作为 non-blocking questions。它们不是本文档的 implementation backlog items。

- MVP-0 directedness/semantic_close default: mock, rule-based, or unknown。[ADR-001]
- `TURN_INGRESS_REJECTED` trace retention level。[ADR-001]
- Candidate vs verdict naming for Duplex outputs beyond current registry。[ADR-001]
- Low-confidence directedness default policy。[ADR-001]
- Event journal file format, flush policy, and session/conversation sequence scope。[ADR-002]
- Playback progress frequency、truncate actual-stop offset reporting、Composer awareness of already-played text/token span、echo_likelihood mock defaults。[ADR-003]
- `task_event_seq` allocator、stale_evidence TTL、cross-version stale evidence propagation。[ADR-004]
- Demo backend source-of-truth boundaries、tool preview requirement、webSearch mock vs real API、manifest load timing、UI patch granularity。[ADR-005]
- `foreground_mode` enum、progress vs foreground priority、switch-task prompt ownership、ambiguity clarification wording。[ADR-006]
- UserPatch raw_text use in audio input、ASR n-best limit、multiple candidate patch types、structured interpretation reason requirement。[ADR-007]
- SlowTask ambiguity resolver implementation mode、FAST_ONLY uncertainty guardrail、normalized provenance values、wrong-resolution eval labeling。[ADR-008]
- CoverageCheck implementation method、Composer prompt/profile separation、immutable fact representation、FAST_ONLY SpokenPlan bypass、degraded response template、multi-part must-say coverage。[ADR-009]
- Trace storage format、raw audio opt-in scope、shareable export timing、secret detection method、local cleanup、gitignore coverage verification。[ADR-010]
- Capability static vs probed source、frontend capability display、structured JSON retry count、Fast/Composer adapter profile sharing、latency representation、adapter compatibility suite。[ADR-011]
- MVP-0 frontend requirement、MVP-2 first demo tools、webSearch mode、SLO hard gate、MVP-3 model endpoint choices、slice demo/replay fixture split。[ADR-012]
- Progress filler classification、frontend progress display、repeated waiting cadence。[ADR-013]
- webSearch mock vs real API、snippet length、source URL requirement、synthetic prompt-injection eval count、attribution template。[ADR-014]
- Trace/audio/replay directory configurability、ADR register content scope、AGENTS.md language style。[ADR-015]
- Confirmation timeout product policy and future pause/resume ADR。[ADR-016]
