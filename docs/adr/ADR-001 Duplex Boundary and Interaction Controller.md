# ADR-001 Duplex Boundary and Interaction Controller

## Status

accepted

## Context

原设计把 Duplex 定义为前置实时控制层和时序真相源，同时提到 speech start/end、semantic close、assistant-directedness、barge-in、hold/continue/accept/reject、commit boundary。

这里需要避免两种误解：

1. Duplex 不是弱化版 VAD。目标架构里的 Duplex 可以具备全双工实时语义能力，例如语义判停、拒识、assistant-directedness、barge-in 判断。
2. Interaction / Turn Controller 不是另一个语义理解模型，也不应依赖 ASRFrame / SemanticFrame 来决定首次入口 commit，因为 ASRFrame / SemanticFrame 只有在音频被接受进入语义链路之后才会产生。

因此需要把实时入口控制、交互状态管理、任务语义理解三个边界拆清楚。

## Decision

将相关职责拆成三类边界：

### 1. Duplex / Realtime Conversation Gate

Duplex 负责 pre-ASR / pre-Thinker 的实时入口判断和全双工控制。它可以输出低层事实、实时 verdict 和候选判断：

- speech_start
- speech_end
- vad
- playback overlap
- echo_likelihood
- vad_confidence
- barge_in_confidence
- barge-in / interrupt candidate
- semantic_close / semantic_close_candidate
- assistant_directedness / directedness_candidate
- reject / hold / accept candidate

Duplex 可以拥有实时语义判停和拒识能力，但它的语义能力只服务于实时入口控制，不负责任务语义理解、工具决策、慢任务语义解释或最终答案承诺。

### 2. Interaction / Turn Controller

Interaction / Turn Controller 是 deterministic state reducer / policy applier，不是语义模型。

它消费：

- DuplexEvent
- 当前 InteractionState
- 当前 TaskFocusState
- 当前 SlowTask 摘要状态
- Talker playback 状态
- 系统配置策略

它不依赖 ASRFrame / SemanticFrame 来决定首次入口 commit。

它负责把 Duplex 的实时 verdict / candidate 和当前系统状态转成系统级交互事件，例如：

- `TURN_OPENED`
- `TURN_INGRESS_ACCEPTED`
- `TURN_INGRESS_REJECTED`
- `TURN_HELD`
- `TURN_INGRESS_COMMITTED`
- `INTERRUPT_CANDIDATE`
- `TTS_TRUNCATE_REQUESTED`
- `WAITING_USER`
- `WAITING_CONFIRMATION`

Task cancel / pause candidates are not Interaction Controller events in MVP. They are post-commit `task_focus=CANCEL_OR_PAUSE_CANDIDATE` metadata owned by Router and interpreted by SlowTask per ADR-006 / ADR-016.

只有当 Interaction / Turn Controller 产生 `TURN_INGRESS_COMMITTED` 后，对应 audio span 才进入 ASR / Thinker，生成 ASRFrame / SemanticFrame。

Interaction Controller 是 turn ingress 的唯一 owner：

- Duplex 不得 commit turn，只能产生实时 audio / directedness / semantic_close / barge-in candidate。
- Router 不得拥有 turn state，只能在 `TURN_INGRESS_COMMITTED` 后做 post-commit routing。
- Thinker / ASR 不得拥有 turn state，也不得决定首次 ingress commit。
- Access Layer 可以接收 audio/text，但不能直接产生 semantic routing 结果。

### MVP-0 InteractionState

MVP-0 `InteractionState` 至少包含：

- `turn_phase`
  - `IDLE`
  - `COLLECTING_INPUT`
  - `HOLDING_INPUT`
  - `TURN_COMMITTED`
  - `RESPONDING`
  - `INTERRUPTING`
  - `WAITING_USER`
- `playback_phase`
  - `NOT_PLAYING`
  - `PLAYING`
  - `TRUNCATE_REQUESTED`
  - `TRUNCATED`
  - `FINISHED`
- `directedness`
  - `ASSUMED_DIRECTED`
  - `DIRECTED`
  - `NOT_DIRECTED`
  - `UNKNOWN`
- `semantic_close`
  - `ASSUMED_CLOSED`
  - `CLOSED`
  - `NOT_CLOSED`
  - `UNKNOWN`
- `current_turn_id`
- `current_input_span_id`
- `current_audio_span_id`
- `current_text_span_id`
- `current_playback_span_id`
- `last_ingress_outcome`
- `last_interaction_event_id`

Ingress outcomes are:

- `ACCEPTED`
- `HELD`
- `REJECTED`
- `COMMITTED`

### MVP-0 Interaction Transition Table

| input event | owner | guard / policy | state update | output event |
| --- | --- | --- | --- | --- |
| `AUDIO_SPAN_STARTED` / `SPEECH_START_DETECTED` | Interaction Controller | audio span belongs to current session | `turn_phase=COLLECTING_INPUT`, set `current_audio_span_id`, set `directedness=UNKNOWN`, set `semantic_close=UNKNOWN` | `TURN_OPENED` |
| `AUDIO_SPAN_ENDED` / `SPEECH_END_DETECTED` | Interaction Controller | directedness is `DIRECTED` or policy allows assumed directed; semantic_close is `CLOSED` or policy allows assumed closed | `last_ingress_outcome=ACCEPTED` | `TURN_INGRESS_ACCEPTED`, then `TURN_INGRESS_COMMITTED` |
| `AUDIO_SPAN_ENDED` / `SPEECH_END_DETECTED` | Interaction Controller | semantic_close is `NOT_CLOSED` | `turn_phase=HOLDING_INPUT`, `last_ingress_outcome=HELD` | `TURN_HELD` |
| `TEXT_INPUT_RECEIVED` | Interaction Controller | text ingress is accepted by access/session policy | create `turn_id`, set `current_input_span_id`, set `current_text_span_id`, set `current_audio_span_id=null`, set `directedness=ASSUMED_DIRECTED`, set `semantic_close=ASSUMED_CLOSED`; final reducer state after commit is `turn_phase=TURN_COMMITTED`, `last_ingress_outcome=COMMITTED` | `TURN_OPENED`, then `TURN_INGRESS_ACCEPTED`, then `TURN_INGRESS_COMMITTED` |
| `BARGE_IN_CANDIDATE` | Interaction Controller | assistant playback is active and confidence / echo policy allows further interruption evaluation | keep or set `playback_phase=PLAYING` | `INTERRUPT_CANDIDATE` |
| `INTERRUPT_CANDIDATE` | Interaction Controller | policy decides interruption should stop current playback | `turn_phase=INTERRUPTING`, `playback_phase=TRUNCATE_REQUESTED` | `TTS_TRUNCATE_REQUESTED` |
| `TTS_TRUNCATE_REQUESTED` | Interaction Controller | request emitted to Talker | `playback_phase=TRUNCATE_REQUESTED` | no additional ingress event |
| `TTS_TRUNCATED` | Interaction Controller | Talker confirms truncate | `playback_phase=TRUNCATED`; if user input is still collecting, keep `turn_phase=COLLECTING_INPUT` | no additional ingress event |
| `TURN_INGRESS_COMMITTED` | Interaction Controller | accepted input is ready for semantic chain | `turn_phase=TURN_COMMITTED`, `last_ingress_outcome=COMMITTED` | audio/text span may enter ASR / Thinker |
| `LOW_CONFIDENCE_INGRESS` | Interaction Controller | directedness or semantic_close confidence below configured threshold | set `directedness=UNKNOWN` or `semantic_close=UNKNOWN`; conservative policy applies | `TURN_HELD` or `TURN_INGRESS_REJECTED` |
| `NON_ASSISTANT_CANDIDATE` | Interaction Controller | candidate confidence meets rejection policy | `turn_phase=WAITING_USER`, `directedness=NOT_DIRECTED`, `last_ingress_outcome=REJECTED` | `TURN_INGRESS_REJECTED` |

### Text Input Ingress Policy

Text input 不经过 Duplex，但不能绕过 Interaction Controller。

Text path:

Access Layer -> `TEXT_INPUT_RECEIVED` -> Interaction Controller -> `TURN_OPENED` -> `TURN_INGRESS_ACCEPTED` -> `TURN_INGRESS_COMMITTED`

Audio path:

Access Layer -> AudioChunk / AudioSpan -> Duplex / Realtime Audio Controller -> Interaction Controller -> `TURN_INGRESS_COMMITTED`

Text input rules:

- 不生成 synthetic `audio_span_id`。
- `audio_span_id = null`。
- 使用 `input_span_id` 或 `text_span_id` 绑定文本输入。
- `input_modality = text`。
- `directedness = ASSUMED_DIRECTED`。
- `semantic_close = ASSUMED_CLOSED`。
- 如果 text input arrives during assistant playback，是否 interrupt 由 Interaction Controller policy 决定，不由 Access Layer 直接决定。

### 3. Post-Commit Semantic Routing

ASRFrame / SemanticFrame 只参与 post-commit 阶段：

- Router 决定 FAST_ONLY / SPAWN_SLOW_TASK / PATCH_ACTIVE_SLOW_TASK / IGNORE
- TaskFocusState 更新
- ASR / Thinker 字段级冲突处理
- UserPatch evidence pack 构造
- SlowTask plan_version 更新
- SemanticCommitment 生成

也就是说：

- Duplex 决定“这段实时输入是否像是对系统说的、是否结束、是否打断”。
- Interaction / Turn Controller 决定“在当前状态下，系统是否接受这段输入、是否打开/提交 turn、是否中断输出”。
- Thinker / ASR / Router / SlowTask 决定“这段已提交输入是什么意思、应该快答还是慢任务、是否 patch active task”。

## Commit Boundary Definition

本文档中的 commit boundary 必须拆分为至少三种：

1. `TURN_INGRESS_COMMITTED`
   表示一段用户输入被系统接受为面向助手的 turn 输入，可以进入 ASR / Thinker。

2. `TASK_SEMANTIC_COMMITTED`
   表示 Slow Agent 对复杂任务产生 SemanticCommitment，成为任务最终事实源。MVP event journal 中该边界由 canonical `SEMANTIC_COMMITMENT_EMITTED` event 表达。

3. `PLAYBACK_COMMITTED`
   表示系统认为某段 audio 已输出到 user-facing playback device 的指定 `playback_offset_ms`。它不是用户已经认知听见或理解的保证，也不是 semantic acknowledgement marker。

ADR-001 只定义第一类和它与 Duplex / Interaction Controller 的边界。后两类在后续 ADR 中细化。

## Alternatives Considered

1. Duplex 拥有全部实时和交互职责。
   优点是模块少；缺点是 Duplex 会变成隐式总控，把音频入口、交互状态和任务语义混在一起。

2. Duplex 只做 VAD，把 semantic_close 和 assistant-directedness 交给 Thinker。
   优点是 Duplex 简单；缺点是会削弱全双工能力，且 Thinker/ASR 在入口 commit 后才运行，无法承担 pre-commit 拒识和语义判停。

3. Interaction / Turn Controller 依赖 ASRFrame / SemanticFrame 做入口 commit。
   该方案被拒绝，因为它存在时序循环：只有 commit 后才会生成 ASRFrame / SemanticFrame。

## Consequences

正向结果：

- 保留 Duplex 的全双工实时智能能力，不把它降级成 VAD。
- 避免 ASR / Thinker 与入口 commit 形成循环依赖。
- Interaction / Turn Controller 保持可测试、可 replay、可解释。
- Router 继续保持 post-commit 快慢系统门控职责。
- semantic_close / assistant-directedness 可以先 mock 或 rule-based，之后替换成更强 Duplex 能力。

代价：

- 需要明确区分 Duplex candidate、Duplex verdict、Interaction finalized event。
- InteractionState / TaskFocusState 必须成为一等状态。
- 需要在 event journal 中记录 pre-commit audio events 和 post-commit semantic events 的因果关系。

## Impacted Modules

- Duplex / Realtime Conversation Gate
- Interaction / Turn Controller
- Event Journal
- Access Layer
- ASR Adapter
- Thinker Adapter
- Router
- TaskFocusState
- InteractionState
- SlowTask
- Talker
- Trace / Replay
- Evaluation Harness

## Validation Method

MVP-0 replay 场景必须验证：

1. 用户开始说话时，Duplex 产生 `speech_start`，Interaction Controller 更新 `turn_phase=COLLECTING_INPUT`。
2. 用户说话结束且 Duplex 判定可接受时，Interaction Controller 产生 `TURN_INGRESS_COMMITTED`。
3. 只有 `TURN_INGRESS_COMMITTED` 后，对应 audio span 才进入 mock ASR / mock Thinker。
4. Talker 播放期间用户插话，Duplex 产生 `BARGE_IN_CANDIDATE`，Interaction Controller 基于 playback 状态和 policy 产生 `INTERRUPT_CANDIDATE` 与 `TTS_TRUNCATE_REQUESTED`。
5. Duplex 判定 reject 或 low directedness 时，Interaction Controller 产生 `TURN_INGRESS_REJECTED`，该 audio span 不进入 ASR / Thinker。
6. Duplex 判定 semantic_close=false 或 hold 时，Interaction Controller 产生 `TURN_HELD`，不提交 turn。
7. 所有 finalized Interaction events 都记录 `caused_by_event_id`，可 replay 重建 InteractionState。
8. 文本输入必须产生 `TEXT_INPUT_RECEIVED`，再由 Interaction Controller 产生 `TURN_OPENED`、`TURN_INGRESS_ACCEPTED` 和 `TURN_INGRESS_COMMITTED`，不得由 Access Layer 直接进入 Router。

## Open Questions

- MVP-0 中音频路径的 `semantic_close` 和 `assistant_directedness` 是默认 mock、rule-based，还是全部置为 unknown？
- `TURN_INGRESS_REJECTED` 是否需要保留 redacted trace，还是只保留 metadata？
- Duplex 输出是否区分 candidate 与 verdict，例如 `semantic_close_candidate` vs `semantic_close_verdict`？
- Interaction / Turn Controller 对低置信度 directedness 的默认策略是 reject、hold，还是 ask clarification？
