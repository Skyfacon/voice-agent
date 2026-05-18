# 状态 Reducer 规格

Source of truth: frozen ADR Baseline v0.4。本文件承载 P1-B-002，是从 ADR baseline 派生的实现规格，不新增架构能力。

Reducer 负责从 canonical event journal 重建运行状态。Reducer 是 deterministic state reducer，不是语义模型，不调用外部工具。

## 1. Reducer 原则

- Reducer 按 session 内 `event_seq` 顺序消费事件。`created_wall_clock_ms` 不作为严格排序依据。
- Deterministic replay 中，Reducer 不得调用外部模型、工具、adapter、网络、时钟或随机数。
- Reducer 只使用 journal 已记录的 payload、causal links 和 refs。
- 对同一 ordered event stream，Reducer 必须产出同一 state digest。
- Reducer 只处理自己 ownership 内的事件，其他事件应忽略或作为 replay diagnostics。
- `PLAYBACK_COMMITTED` 永远不能被当成 semantic acknowledgement 或 user confirmation。
- SlowTask 相关 reducer 必须尊重 `task_id`、`plan_version`、`task_event_seq`。
- Terminal states 除非未来 ADR 定义恢复路径，否则必须 sticky。

## 2. Replay 顺序

1. 按 `event_seq` 升序排序。
2. 校验 common event envelope。
3. 校验 `docs/specs/event-registry.md` 中 event-specific required fields。
4. 分发到相关 reducer。
5. 执行 reducer transition rules。
6. 将 ignored / late-event diagnostics 写入 replay metadata，而不是新增 runtime event。
7. 最终输出 state digest。

实现可以按事件生成中间 snapshot，但最终状态必须等价于完整 event replay。

## 3. Deterministic Reducer 要求

- 不生成随机 id、timestamp、model output、tool result。
- 缺失 data-plane ref 时，标记 unavailable，不外部 fetch。
- schema validation failure 在 strict deterministic replay 中应 fail；在 degraded replay 中可记录 degraded diagnostics。
- Digest 不得包含 raw audio、raw text、secret、raw web content 或 tool credential payload。

## 4. Snapshot vs Event Replay

- Event replay 是 correctness 的规范来源。
- Snapshot 只能作为性能优化。
- Snapshot 必须包含 `last_event_seq`、`event_schema_version` 和 reducer-owned state digest。
- 从 snapshot 后继续 replay 的最终 digest 必须等于 full replay。
- GitHub/shareable fixture 应优先使用短 event stream，避免 opaque snapshot。

## 5. Late Event Policy

- old-plan ToolResult 不是普通 late event，必须走 ADR-004 / ADR-016 stale evidence policy。
- terminal SlowTask 后到达的 UserPatch、ToolResult、confirmation 不得推进 task。
- `TTS_TRUNCATED` 或 `PLAYBACK_FINISHED` 后，同一 playback span 的 late `PLAYBACK_PROGRESS` 不得改变 current playback state。
- Adapter health events 可继续更新 `AdapterHealthState`，不受单个 request terminal failure 限制。

## 6. Terminal State Rules

- `SlowTaskState` terminal states: `COMPLETED`, `CANCELLED`, `FAILED`。
- `PlaybackState` terminal span states: `TRUNCATED`, `FINISHED`。
- 每个 turn 的 `InteractionState.turn_phase` 在 commit 后不可被同一 turn 的 late input 反向修改。
- 新 turn 必须使用新的 `turn_id`。
- terminal SlowTask 只能保留 late evidence 用于 debug/stale，不得推进当前任务。

## 7. Reducer Specifications

### InteractionState

| 字段 | 规格 |
| --- | --- |
| owned_by | Interaction Controller。 |
| input_events | `TEXT_INPUT_RECEIVED`, `AUDIO_SPAN_STARTED`, `AUDIO_SPAN_ENDED`, `SPEECH_START_DETECTED`, `SPEECH_END_DETECTED`, `DIRECTEDNESS_CANDIDATE`, `SEMANTIC_CLOSE_CANDIDATE`, `NON_ASSISTANT_CANDIDATE`, `LOW_CONFIDENCE_INGRESS`, `TURN_OPENED`, `TURN_HELD`, `TURN_INGRESS_ACCEPTED`, `TURN_INGRESS_REJECTED`, `TURN_INGRESS_COMMITTED`, `BARGE_IN_CANDIDATE`, `INTERRUPT_CANDIDATE`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, `WAITING_USER`。 |
| output_state | `turn_phase`, `playback_phase`, `directedness`, `semantic_close`, `current_turn_id`, `current_input_span_id`, `current_audio_span_id`, `current_text_span_id`, `current_playback_span_id`, `last_ingress_outcome`, `last_interaction_event_id`。 |
| invariant_rules | Text input 必须 `audio_span_id=null`、`directedness=ASSUMED_DIRECTED`、`semantic_close=ASSUMED_CLOSED`；无 `TURN_INGRESS_COMMITTED` 不得进入 ASR/Thinker；Interaction Controller 是 turn ingress commit 唯一 owner。 |
| ignored_events | Router、SlowTask、Tool、Adapter、Composer、Trace 事件，除列出的 playback/truncate 事件外。 |
| late_event_policy | 非当前 span/turn 的 late candidate 不改变 current committed turn；不匹配 playback span 的 late truncate 只进入 diagnostics。 |
| terminal_state_policy | per-turn commit final；同一 playback span 在 `TRUNCATED` / `FINISHED` 后 terminal。 |
| replay_validation | MVP-0 text/audio/barge-in scenarios 必须重建 expected InteractionState。 |

### TaskFocusState

| 字段 | 规格 |
| --- | --- |
| owned_by | Router。 |
| input_events | `ROUTER_DECISION_EMITTED`, `TASK_FOCUS_STATE_UPDATED`，以及 Router state snapshot 引用的 SlowTask terminal summary。 |
| output_state | `active_task_id`, `foreground_mode`, `side_conversation_allowed`, `default_patch_policy`, `ambiguous_input_policy`, `last_focus_decision`, `last_focus_confidence`, `last_focus_event_id`。 |
| invariant_rules | MVP 只允许一个 active non-terminal SlowTask；RouterDecision 限于 `FAST_ONLY`, `SPAWN_SLOW_TASK`, `PATCH_ACTIVE_SLOW_TASK`, `IGNORE`；Router 不 cancel、不 pause、不 authorize tool、不解释最终 UserPatch 语义。 |
| late_event_policy | 更早 turn 的 Router decision 不覆盖更新的 `last_focus_*`；replay 以 `event_seq` 为准。 |
| terminal_state_policy | active task 终态后，只有 Router-owned `TASK_FOCUS_STATE_UPDATED` 可清理 `active_task_id`；reducer 不从 SlowTask terminal event 自行推断。 |
| replay_validation | MVP-1 覆盖 active patch、foreground chat、new-task candidate、cancel/pause candidate、ambiguous、non-assistant。 |

### SlowTaskState

| 字段 | 规格 |
| --- | --- |
| owned_by | SlowTask Runtime。 |
| input_events | `SLOWTASK_CREATED`, `SLOWTASK_STATE_CHANGED`, `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED`, `PLAN_VERSION_ADVANCED`, `TASK_REPLANNED`, `PLANNING_STARTED`, `PLANNING_RESTARTED`, `WAITING_FOR_SLOT`, `WAITING_FOR_TOOL`, `WAITING_FOR_USER_CONFIRMATION`, evidence events, tool result/stale events, confirmation/cancel events, `FINALIZING`, `SEMANTIC_COMMITMENT_EMITTED`, `SLOWTASK_DEGRADED`, `SLOWTASK_FAILED`。 |
| output_state | state in `CREATED`, `WAITING_FOR_SLOT`, `PLANNING`, `EXECUTING`, `WAITING_FOR_USER_CONFIRMATION`, `COMPLETED`, `CANCELLED`, `FAILED`; current `plan_version`; current `task_event_seq`; goal/constraints refs; resolved arguments refs; confirmation_state; stale_evidence refs; adopted evidence metadata; terminal outcome。 |
| invariant_rules | 所有状态变化必须有 `SLOWTASK_STATE_CHANGED`；`plan_version` 只能通过 `PLAN_VERSION_ADVANCED` 前进；UserPatch 是 evidence，不是直接 mutation；SemanticCommitment 只能基于 current plan；stale evidence 未被 `STALE_EVIDENCE_ADOPTED` 前不得推进 current plan。 |
| late_event_policy | old-plan `TOOL_RESULT_RECEIVED` 必须被标记 stale；terminal 后 late UserPatch/confirmation/ToolResult 不得推进。 |
| terminal_state_policy | `COMPLETED`, `CANCELLED`, `FAILED` sticky。 |
| replay_validation | MVP-1 replay create、planning、waiting slot、replanning、stale result、completed/cancelled/failed；MVP-2 replay confirmation/tool authorization/cancel/retry。 |

### ToolExecutionState

| 字段 | 规格 |
| --- | --- |
| owned_by | Tool Executor。 |
| input_events | `TOOL_MANIFEST_LOADED`, `TOOL_CALL_STARTED`, `TOOL_ARGUMENTS_PARTIAL`, `TOOL_ARGUMENTS_READY`, `TOOL_PREVIEW_AVAILABLE`, `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_CALL_RETRYING`, `TOOL_EXECUTION_CANCEL_REQUESTED`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`。 |
| output_state | tool manifest metadata by `tool_name`; per-`tool_call_id` lifecycle status; task binding history (`task_id`, `plan_version`, `task_event_seq`); latest tool-owned `task_event_seq` by `task_id`; partial / ready argument refs; preview refs; authorization metadata; execution start metadata including explicit `authorization_event_id` or `caused_by_event_id` fallback; progress refs; UI patch refs; result refs; failure / retry / cancel / blocked metadata。 |
| invariant_rules | Reducer 只 consume recorded journal events；不得执行工具、调用 demo backend、调用网络、读取 clock/random、应用 UI patch 或 fetch refs。所有带 `tool_call_id` 的 tool events 必须归档到对应 call record；task-bound events 必须保留原始 `task_id`、`plan_version`、`task_event_seq`，且 tool-owned events 在同一 `task_id` 内必须严格递增。`TOOL_UI_STATE_PATCHED` 只记录 `ui_patch_id`、`idempotency_key`、`patch_ref`；`TOOL_RESULT_RECEIVED` 只记录 `result_status`、`result_ref`、trust/source metadata。Replay validation 负责校验 `DEMO_DESTRUCTIVE_ACTION` start 有 current-plan `CONFIRMATION_ACCEPTED` 授权链；reducer 本身不执行授权决策。 |
| stale_policy | `ToolExecutionState` 不判断 old-plan result 是否可推进 current plan，也不得更新 SlowTask current plan；旧 `TOOL_RESULT_RECEIVED` 的 stale / adopt / rebase policy 仍由 `SlowTaskState` 根据 `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED`, `STALE_EVIDENCE_ADOPTED` 处理。 |
| late_event_policy | 同一 `tool_call_id` 的 recorded events 按 replay 顺序归档，并保留每个事件自己的 plan binding；plan advance 后的 cancel request 或 old-plan result 不会被 reducer 改写成 current-plan fact。 |
| terminal_state_policy | `TOOL_RESULT_RECEIVED`, `TOOL_EXECUTION_FAILED`, `TOOL_EXECUTION_CANCELLED`, `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS` 只更新该 call 的 recorded lifecycle status；本 slice 不实现 retry scheduler、cancel runtime 或 executor terminal enforcement。 |
| replay_validation | MVP-2 Slice 1 replay 必须重建 manifest、partial args、blocked insufficient args、ready args、preview、authorization、started、progress、UI patch refs、result refs、failure、retry、cancel metadata，且 deterministic replay 不执行任何 tool/runtime。`TOOL_EXECUTION_STARTED` 必须能绑定 recorded `TOOL_MANIFEST_LOADED`，且不得用 started-event `tool_name` 覆盖既有 `TOOL_CALL_STARTED` binding；manifest `side_effect_class` 必须属于 MVP allowlist (`READ_ONLY`, `DRY_RUN`, `SANDBOX_WRITE`, `DEMO_DESTRUCTIVE_ACTION`)；真实外部副作用 class 必须拒绝。`TOOL_EXECUTION_CANCEL_REQUESTED` 必须晚于造成它的 SlowTask plan advance / cancel decision。 |

### DemoUIState

| 字段 | 规格 |
| --- | --- |
| owned_by | Tool Executor / Replay Runtime。 |
| input_events | `TOOL_UI_STATE_PATCHED`。 |
| output_state | frontend-visible demo backend namespaces；per-namespace applied `ui_patch_id` list；operation counts；latest patch id；per-patch `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `idempotency_key`, `patch_ref`, parsed synthetic namespace / operation。 |
| invariant_rules | 只 consume recorded `TOOL_UI_STATE_PATCHED` canonical fields；不得执行 demo backend、调用 frontend、调用网络、读取真实文件 payload、fetch `patch_ref`、读取 clock/random。`patch_ref` 只能作为 safe structured ref / synthetic substitute 解析为最小 replay state；不得从 `TOOL_RESULT_RECEIVED` 推断 demo UI mutation。重复 `ui_patch_id` 必须绑定同一 `idempotency_key` 和 `patch_ref`。 |
| late_event_policy | Replay 按 `event_seq` 顺序应用 patch；同一 `ui_patch_id` 的重复幂等记录不重复计数。 |
| terminal_state_policy | Demo UI replay state 不自行推断工具终态；工具终态仍由 `ToolExecutionState` 记录。 |
| replay_validation | MVP-2 Slice 3 replay 必须从 `TOOL_UI_STATE_PATCHED.patch_ref` / synthetic substitute 重建最小 demo UI/backend state，且无 patch event 时即使有 successful `TOOL_RESULT_RECEIVED` 也不得产生 demo state mutation。 |

### SpokenPlanState

| 字段 | 规格 |
| --- | --- |
| owned_by | Composer / Replay Runtime。 |
| input_events | `SPOKEN_PLAN_EMITTED`。 |
| output_state | per-`spoken_plan_id` draft metadata；`task_id`, `plan_version`, `task_event_seq`; source commitment/progress ids；coverage/truthfulness required flags；synthetic/redacted `text_ref`; emotion/style/priority；`output_mode`; symbolic commitment metadata such as `immutable_fields`, `must_say_fields`, `forbidden_rewrite_fields`。 |
| invariant_rules | Reducer 只 consume recorded journal events；不得调用 Composer runtime、模型、TTS、tool、网络、clock/random 或 fetch `text_ref`。Composer output 只是 unchecked draft；不得改变 SlowTask-owned facts、resolved arguments、tool status、risk warnings、confirmation state、stale/adopted evidence metadata。 |
| replay_validation | Replay 必须验证 source commitment/progress event exists and precedes `SPOKEN_PLAN_EMITTED`；`task_id` / `plan_version` match；commitment-derived speech has matching `source_commitment_id`, `coverage_check_required=true`, and exact symbolic metadata preservation for `immutable_fields` / `must_say_fields` / `forbidden_rewrite_fields`；progress-derived speech has matching `source_progress_event_ids`, `truthfulness_check_required=true`, and MVP truthfulness level in `STATE_GROUNDED` / `STYLE_ONLY_ACK`。 |

### PlaybackState

| 字段 | 规格 |
| --- | --- |
| owned_by | Talker / Playback。 |
| input_events | `PLAYBACK_SPAN_STARTED`, `PLAYBACK_PROGRESS`, `PLAYBACK_COMMITTED`, `PLAYBACK_FINISHED`, `TTS_TRUNCATE_REQUESTED`, `TTS_TRUNCATED`, coverage/truthfulness passed events。 |
| output_state | current `playback_span_id`; phase `NOT_PLAYING`, `PLAYING`, `TRUNCATE_REQUESTED`, `TRUNCATED`, `FINISHED`; latest `playback_offset_ms`; latest committed offset; approved check event id; actual stop offset。 |
| invariant_rules | SemanticCommitment-derived speech 需要 coverage pass；progress speech 需要 truthfulness pass；`PLAYBACK_COMMITTED` 只是 delivery marker；candidate offset、request cutoff、actual stop offset 必须保持区分。 |
| late_event_policy | 同一 span 在 `TTS_TRUNCATED` 或 `PLAYBACK_FINISHED` 后的 `PLAYBACK_PROGRESS` 不更新 latest offset。 |
| terminal_state_policy | `TRUNCATED` 和 `FINISHED` 终止当前 playback span；新播放需要新 `playback_span_id`。 |
| replay_validation | MVP-0 barge-in scenario 必须重建 playback offsets 和 truncate state。 |

### AdapterHealthState

| 字段 | 规格 |
| --- | --- |
| owned_by | Adapter Registry / Adapter Runtime。 |
| input_events | `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`, `ADAPTER_HEALTHCHECK_FAILED`, `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, `ADAPTER_OUTPUT_VALIDATION_FAILED`, `ADAPTER_OUTPUT_DEGRADED`, mock/real adapter output events。 |
| output_state | capability snapshot ref；per-adapter health；deployment mode；output mode；missing capabilities；retry/failure counters；latest degradation reason。 |
| invariant_rules | unsupported capability 显式记录；mock/fallback/degraded/real 可区分；schema validation failure 不得静默 downstream；adapter events 不得记录 secrets。 |
| replay_validation | MVP-0 重建 mock capability snapshot 和 output modes；MVP-3 adapter failure/retry/degradation 可 replay。 |

### TracePrivacyState

| 字段 | 规格 |
| --- | --- |
| owned_by | Trace / Replay Runtime and Privacy / Redaction policy。 |
| input_events | `SESSION_STARTED`, `TRACE_WRITE_DEGRADED`, `TRACE_SECRET_REDACTION_APPLIED`, `TRACE_WRITE_BLOCKED_SECRET_DETECTED`, `REPLAY_STARTED`, `REPLAY_COMPLETED`, events carrying `trace_redaction_level`。 |
| output_state | trace domain config；redaction counters；blocked-write counters；latest degraded storage target；replay mode；fixture safety status。 |
| invariant_rules | secrets 不得 raw 进入 trace；raw audio 仅 local debug opt-in；shareable/GitHub fixtures 必须 synthetic/redacted/minimal，排除 raw audio、raw trace、secrets、unredacted real input、large raw web content。 |
| terminal_state_policy | replay run terminal status 来自 `REPLAY_COMPLETED`；trace privacy state 持续到 `SESSION_ENDED`。 |
| replay_validation | MVP-0 local trace safety case 验证 raw audio 默认关闭、secret redacted/blocked、shareable fixture boundary。 |

## 8. State Digest Format

State digest 至少包含：

- `digest_schema_version`
- `source_session_id`
- `last_event_seq`
- `event_schema_version_range`
- `interaction_state_hash`
- `task_focus_state_hash`
- `slowtask_state_hash`
- `tool_execution_state_hash`
- `demo_ui_state_hash`
- `spoken_plan_state_hash`
- `playback_state_hash`
- `adapter_health_state_hash`
- `trace_privacy_state_hash`
- `overall_digest`

Hash 基于 canonical normalized state 计算：stable key order，不包含 raw secret/audio/text/web/tool credential payload。
