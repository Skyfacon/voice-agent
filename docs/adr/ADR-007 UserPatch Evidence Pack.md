# ADR-007 UserPatch Evidence Pack

## Status

accepted

## Context

在 active SlowTask 运行期间，用户可以边说边补充约束、纠正参数、确认信息、取消或表达反馈。快系统和 Router 需要把这些输入送到慢系统，但不能把自己的浅层理解包装成最终任务语义。

原架构要求：快系统不要直接发送 `constraint_update`、`goal_rewrite`、`slot_patch` 等强语义事件，只发送 UserPatch。Slow Agent 结合当前 task context 决定它究竟是 slot update、constraint update、goal rewrite、confirmation、cancel、feedback 还是 irrelevant message。

因此 UserPatch 必须被定义为 evidence pack，不是结论包。

## Decision

UserPatch 是 SlowTask 的输入证据包，用于携带用户新增输入的原始证据、可追溯来源和非权威假设。

UserPatch 必须绑定：

- `patch_id`
- `event_id`
- `session_id`
- `conversation_id`
- `task_id`
- `plan_version`
- `task_event_seq`
- `turn_id`
- `utterance_id`
- `caused_by_event_id`
- `created_at_monotonic_ms`
- `created_at_wall_clock_ms`

UserPatch 的 `plan_version` 语义必须遵守 ADR-004：

- `USER_PATCH_RECEIVED` 绑定 patch 到达时 SlowTask 的 current `plan_version`，即 pre-advance version。
- UserPatch 是 evidence pack，不是新 plan。
- `USER_PATCH_INTERPRETED` against `observed_plan_version` / `interpreted_against_plan_version` 解释。
- 只有 SlowTask 判定该 patch materially changes task state 时，才产生 `PLAN_VERSION_ADVANCED`。
- irrelevant / foreground chat / non-task patch 不 advance `plan_version`。

UserPatch 分为两层：authoritative evidence 和 non-authoritative hypothesis。

authoritative evidence 包括：

- `raw_text` if available
- `audio_span_id`
- `asr_nbest`
- `transcript_hint`
- `source_event_ids`
- `turn_id`
- `utterance_id`
- `input_modality`
- `language_hint`
- `audio_timing`
- `provenance`

non-authoritative hypothesis 包括：

- `semantic_summary`
- `audio_summary`
- `patch_hint`
- `candidate_patch_types`
- `emotion`
- `confidence`
- `task_focus`
- `task_focus_confidence`
- `router_reason`

字段语义：

- `raw_text`: 用户文本输入或 ASR/前端提供的原始文本；如果是语音输入，不能把单一 ASR transcript 当作唯一事实源。
- `audio_span_id`: 指向被 `TURN_INGRESS_COMMITTED` 接受的 audio span。
- `asr_nbest`: ASR 多候选文本和置信度；可为空。
- `transcript_hint`: 用于检索、debug、参数抽取的辅助文本，不是最终语义事实。
- `semantic_summary`: Thinker / Router 产生的简短摘要，是 hypothesis。
- `patch_hint`: Router / Thinker 给 Slow Agent 的浅层提示，不能作为最终任务解释。
- `candidate_patch_types`: 可包含 `slot_update_candidate`、`constraint_update_candidate`、`goal_rewrite_candidate`、`confirmation_candidate`、`cancel_candidate`、`switch_task_candidate`、`feedback_candidate`、`irrelevant_candidate`，但都不是最终分类。
- `provenance`: 标注每个关键字段来源，例如 user_text、asr、thinker、router、duplex、frontend。

Slow Agent 收到 UserPatch 后，必须显式产生 canonical `USER_PATCH_INTERPRETED` 内部解释事件。该事件至少包含：

- `patch_id`
- `task_id`
- `observed_plan_version`
- `interpreted_against_plan_version`
- `interpretation_type`
- `materially_changes_task`
- `interpretation_reason`
- `source_evidence_refs`

`interpretation_type` 至少包括：

- `slot_update`
- `constraint_update`
- `goal_rewrite`
- `confirmation`
- `cancel`
- `switch_task`
- `feedback`
- `irrelevant`

只有 SlowTask 内部解释事件才能推进 task state 或触发 plan_version 变化。UserPatch 自身不能直接修改任务目标、槽位、约束或状态。

Trace / privacy 默认策略：

- trace 默认保存 `audio_span_id`，不默认保存 raw audio。
- raw audio 仅 dev/debug opt-in，且有 TTL 和脱敏策略。
- redacted transcript 可以默认开启。
- UserPatch 中的敏感字段必须支持 redaction。

Redaction boundary：

- secret-like content 必须在写入 event journal / local debug trace 前 redaction 或 blocked；不得以 raw payload 进入任何 trace 域。
- PII / raw user text 可以只在 `LOCAL_DEBUG_TRACE` 中通过 `text_ref` 或 `trace_redaction_level=local_debug` 保存；shareable replay / GitHub fixture 必须使用 `redacted_text`、summary、synthetic text 或 metadata-only。
- UserPatch event envelope 中应优先记录 `evidence_ref` / `text_ref` / `redacted_text`，而不是无条件内联 raw transcript。
- Export to `SHAREABLE_REPLAY` / `GITHUB_ALLOWED` 必须执行 ADR-010 export gate；字段级 redaction status 必须可审计。

## Alternatives Considered

1. 快系统直接发送 `constraint_update`、`goal_rewrite`、`slot_patch`。
   速度快，但会把 Thinker/Router 的浅层判断提升为语义权威，容易污染 SlowTask。

2. UserPatch 只包含 raw_text，不包含 summary/hint。
   最安全，但会让 Slow Agent 每次都从零理解，降低效率，也浪费 Thinker 的语音理解能力。

3. UserPatch 只包含 semantic_summary，不保留 raw evidence。
   接口轻，但 debug、replay 和冲突仲裁无法成立。

4. Router 直接决定 UserPatch 的最终类型。
   会让 Router 越界做复杂 reasoning，与 ADR-006 冲突。

## Consequences

正向结果：

- 保留 Thinker / Router 的辅助价值，但不转移语义权威。
- SlowTask 可以基于 raw evidence 和当前任务上下文做最终解释。
- ASR 错误、Thinker 误解、Router 误判都可在 trace 中被审计。
- UserPatch 能与 ADR-004 plan_version policy 对齐。
- patch misrouting 和 patch misinterpretation 可以分开评估。

代价：

- UserPatch schema 比单纯文本消息更复杂。
- SlowTask 必须输出结构化 patch interpretation。
- Trace/redaction 需要字段级处理。
- 部分低风险场景会显得“手续多”，但这换来一致性和可 replay。

## Impacted Modules

- UserPatch Pipeline
- Router
- Thinker
- ASR Adapter
- Duplex / Realtime Conversation Gate
- Interaction / Turn Controller
- SlowTask
- Event Journal
- Trace / Replay
- Privacy / Redaction Policy
- Evaluation Harness

## Validation Method

MVP-1 必须验证：

1. active SlowTask 期间用户补充输入会生成 UserPatch。
2. `USER_PATCH_RECEIVED` 绑定 `task_id`、`plan_version`、`task_event_seq`，其中 `plan_version` 是 patch 到达时的 pre-advance current version。
3. UserPatch 同时携带 authoritative evidence 和 non-authoritative hypothesis。
4. `semantic_summary` / `patch_hint` 不会直接修改 SlowTask 状态。
5. SlowTask 必须先产生 `USER_PATCH_INTERPRETED`，再推进状态或 plan_version。
6. 并不是每个 UserPatch 都触发 `PLAN_VERSION_ADVANCED`；irrelevant / foreground chat / non-task patch 不推进 plan_version。
7. materially changes task state 的 patch 触发 `PLAN_VERSION_ADVANCED` 时，必须记录 `from_plan_version`、`to_plan_version`、`planning_reason`、`caused_by_user_patch_event_id`。
8. ASR n-best 和 Thinker summary 冲突时，UserPatch 能保留双方来源。
9. replay 能重建 UserPatch 到 SlowTask interpretation 的因果链。
10. raw audio 默认不进入 trace，只记录 `audio_span_id`。
11. patch misrouting rate 和 patch interpretation error 能在 eval 中区分统计。
12. secret-like UserPatch field 在 journal write 前被 redacted 或 blocked。
13. shareable replay 中的 UserPatch 不包含 unredacted real user input。

## Open Questions

- `raw_text` 在语音输入场景中是否应仅用于用户手动文本，还是允许放 ASR top-1？
- `asr_nbest` 最大保留多少条候选？
- `candidate_patch_types` 是否允许多个并存并带置信度？
- SlowTask interpretation event 是否必须每次都记录 material-change 判断的结构化 reason？
