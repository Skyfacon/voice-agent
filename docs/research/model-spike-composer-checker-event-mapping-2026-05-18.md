# Model Spike Composer / Checker Event Mapping 2026-05-18

## 0. Status

- Status: `research_only_composer_checker_event_mapping`
- Date: 2026-05-18
- Lane: model spike research
- Contract snapshot: observed `main@275437e`
- Historical evidence snapshot: 2026-05-11/12 Thinker / Composer artifacts remain historical `main@61e6afc` unless explicitly re-mapped.

本文只做 research-only mapping。它不实现 runtime adapter，不连接真实 provider，不运行真实麦克风或播放设备，不采集真实用户录音，不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`，也不承诺任何 MVP3 runtime behavior。

## 1. 当前分支 / git 状态 / observed main snapshot

只读观察到的本地状态：

```text
git status --short --branch
## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]
 M docs/research/model-spike-integration-ledger.md
?? docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md
?? docs/research/model-spike-count-reconciliation-2026-05-18.md
?? docs/research/model-spike-mainline-sync-2026-05-17.md
?? docs/research/model-spike-mainline-sync-2026-05-18.md
?? docs/research/model-spike-mvp3-readiness-review-2026-05-18.md
?? docs/research/model-spike-tool-executor-event-mapping-2026-05-18.md
?? docs/research/profiles/
?? docs/research/spikes/...
?? tools/
```

Interpretation:

- 当前工作分支符合线程要求：`research/model-spikes`。
- 工作区已有既存 research lane 修改和未跟踪 research/tooling artifacts；本文只新增本文件。
- 这些既存 artifacts 不在本线程内归因或清理。

Observed main:

```text
git rev-parse --short main
275437e
```

Observed `main` top commits:

```text
275437e Merge pull request #23 from Skyfacon/mvp2/slice4-demo-tools
954dd07 feat: add MVP2 demo tools
ced2077 Merge pull request #22 from Skyfacon/mvp2/slice3-tool-ui-state-patch
0d2870f fix: harden MVP2 UI patch replay validation
6f6e549 feat: add MVP2 tool UI state replay
f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton
a52585b fix: harden MVP2 tool executor policy gates
2c7a567 feat: add MVP2 demo tool executor skeleton
5741ae3 Merge pull request #20 from Skyfacon/mvp2/slice1-tool-execution-state
de71948 feat: add MVP2 tool execution replay state
ac1b43f Merge pull request #19 from Skyfacon/mvp2/slice0-replay-safety
0cdb7c8 test: add MVP2 replay safety skeleton
```

## 2. 当前 main contract delta

本线程实际只读观察到的 `main` 是 `main@275437e`，不是 `main@ced2077`。

相对 `ced2077` 的新增 delta：

| Delta | 只读观察 | 对本 mapping 的影响 |
| --- | --- | --- |
| `954dd07` | Adds MVP2 demo tools: `memo`, `alarm`, `flashlight`, `weather`, `webSearch` fixtures/tests and demo backend/manifest work. | Progress/result speech mapping 必须把 `TOOL_PROGRESS_UPDATED`、`TOOL_UI_STATE_PATCHED`、`TOOL_RESULT_RECEIVED` 当作更具体的 observed source events。 |
| `275437e` | Merges slice4 demo tools. | `webSearch` 的 `UNTRUSTED_WEB_EVIDENCE` result boundary 已有 current-main fixture/test signal；仍不代表 real webSearch provider approval。 |

Composer/checker contract observation:

- `main:docs/specs/event-registry.md` 已列出 `SPOKEN_PLAN_EMITTED`、`COMMITMENT_COVERAGE_CHECK_*`、`PROGRESS_TRUTHFULNESS_CHECK_*` canonical events。
- `main:docs/specs/mvp2-acceptance-scenarios.md` 已要求 coverage / truthfulness pass gate playback，failed check blocks playback。
- `main:src/voice_agent/state/playback_state.py` 已记录 `PLAYBACK_SPAN_STARTED.approved_check_event_id`，并把 passed check events 纳入 playback reducer input surface。
- 只读搜索未观察到 `src/voice_agent/composer/`、`src/voice_agent/checks/`，也未观察到 Composer/checker events 在 `src/voice_agent/events/registry.py` runtime definitions 中注册。

结论：

- 本 mapping 使用实际 observed `main@275437e`。
- `main@275437e` 已超过 `ced2077`，旧 `model-spike-tool-executor-event-mapping-2026-05-18.md` 中 `contract_snapshot=main@ced2077` 若要成为最新同步入口，需要另开 research-only sync/update thread。
- 对本线程来说，这不是 blocker；它只让 progress/tool result source event 更具体。
- Composer/checker 仍应写成 canonical contract / acceptance skeleton / playback reducer surface mapping，不能写成 runtime checker 已实现或可直接集成。

## 3. 本 mapping 的范围和非目标

In scope:

- 将 2026-05-11/12 Thinker / Composer research evidence 映射到 current-main MVP2 Composer/checker/playback gating contract。
- 明确 Composer model/provider output、SlowTask/Tool source events、Checker-owned pass/fail events、Talker playback events 的边界。
- 为后续 Slow LLM current-plan/stale metadata hardening 和 MVP3 planning 提供输入。
- 保留 evidence label：`observed_real`、`observed_degraded`、`synthetic_eval`、`unknown`、`unsupported`。

Out of scope:

- 不实现 Composer runtime、checker runtime、real model adapter、real TTS adapter 或 playback device integration。
- 不修改 canonical event registry、ADR、specs、tests 或 runtime。
- 不新增 MVP-relevant event name。
- 不把 synthetic dry-run 升级成 runtime proof。
- 不让 model self-attestation 替代 checker pass。
- 不让 webSearch/RAG evidence 进入 instruction 区或修改 policy。

## 4. Composer/checker canonical event inventory

| Event | Owner | Required / relevant fields | Mapping note |
| --- | --- | --- | --- |
| `SEMANTIC_COMMITMENT_EMITTED` | SlowTask Runtime | `commitment_id`, `task_id`, `plan_version`, `task_event_seq`, `source_events`; optional `commitment_ref` | 复杂任务事实源。Composer 只能引用，不能改写。 |
| `SPOKEN_PLAN_EMITTED` | Composer | `spoken_plan_id`, `source_progress_event_ids`, `coverage_check_required`; optional `source_commitment_id`, `truthfulness_check_required` | 只是 spoken realization candidate；不是 checker pass，不是 playback。 |
| `COMMITMENT_COVERAGE_CHECK_PASSED` | Coverage Checker | `spoken_plan_id`, `source_commitment_id`, `checked_fields`, `check_result_ref` | Checker-owned pass event；不是 Composer 自证。 |
| `COMMITMENT_COVERAGE_CHECK_FAILED` | Coverage Checker | `spoken_plan_id`, `source_commitment_id`, `failure_reasons` | 必须阻止对应 SpokenPlan playback。 |
| `PROGRESS_TRUTHFULNESS_CHECK_PASSED` | ProgressTruthfulnessCheck | `spoken_plan_id`, `source_progress_event_ids`, `truthfulness_level`, `check_result_ref` | Progress speech 的 pass gate。 |
| `PROGRESS_TRUTHFULNESS_CHECK_FAILED` | ProgressTruthfulnessCheck | `spoken_plan_id`, `source_progress_event_ids`, `failure_reasons` | 必须阻止对应 progress speech playback。 |
| `PLAYBACK_SPAN_STARTED` | Talker | `playback_span_id`, one of `audio_ref` / `tts_stream_ref`; optional `spoken_plan_id`, `approved_check_event_id` | 当 check required 时，`approved_check_event_id` 必须指向 passed check event 或等价可 replay causal chain。 |

Progress source events that may ground progress speech:

| Source event | Owner | Progress wording allowed only if... |
| --- | --- | --- |
| `PLANNING_STARTED` / `PLANNING_RESTARTED` | SlowTask Runtime | 只能说正在规划/重新规划，不能说已执行工具或已完成。 |
| `WAITING_FOR_SLOT` | SlowTask Runtime | 只能说还缺字段/需要澄清。 |
| `WAITING_FOR_TOOL` | SlowTask Runtime | 只能说正在等某个 tool call；必须绑定 `tool_call_id`。 |
| `TOOL_PROGRESS_UPDATED` | Tool Executor | 只能表达对应 progress type，不能提前说 result/UI 已完成。 |
| `TOOL_UI_STATE_PATCHED` | Tool Executor | 可以表达 demo UI/backend state 已按 patch 改变；仍不得描述为真实外部系统副作用。 |
| `TOOL_RESULT_RECEIVED` | Tool Executor | 可以表达工具返回了 normalized result；old-plan result 还要通过 stale/adopt policy。 |
| `WAITING_FOR_USER_CONFIRMATION` | SlowTask Runtime | 可以表达正在等确认；不能说已确认。 |
| `FINALIZING` | SlowTask Runtime | 可以表达正在收尾/整理最终承诺；不能创造未在 source 中存在的 result。 |
| `SLOWTASK_FAILED` | SlowTask Runtime | 可以表达失败/降级原因；不能掩盖 failure。 |

## 5. Required field matrix

| Field | Event / owner | Requiredness for mapping | Rule |
| --- | --- | --- | --- |
| `spoken_plan_id` | `SPOKEN_PLAN_EMITTED`, all check events, optional playback link | Required for every SpokenPlan and check event. | Allocated by Composer boundary; checks and playback must reference the same id. |
| `source_commitment_id` | `SPOKEN_PLAN_EMITTED` optional; coverage pass/fail required | Required for SemanticCommitment-derived speech. | Must reference `SEMANTIC_COMMITMENT_EMITTED.commitment_id`; model cannot invent a commitment. |
| `source_progress_event_ids` | `SPOKEN_PLAN_EMITTED`, progress truthfulness pass/fail | Required by registry for SpokenPlan and truthfulness checks. | Must contain actual recorded source events; empty/fictional ids make progress speech unsupported. |
| `coverage_check_required` | `SPOKEN_PLAN_EMITTED` | Required. | `true` for SemanticCommitment-derived speech and any speech carrying protected commitment facts. |
| `truthfulness_check_required` | `SPOKEN_PLAN_EMITTED` | Optional in registry; required by policy when progress claims exist. | `true` whenever speech claims state/progress/tool/UI/result status. |
| `checked_fields` | `COMMITMENT_COVERAGE_CHECK_PASSED` | Required on pass. | Must include the protected fields actually checked, such as immutable facts, must-say fields, resolved arguments, risk warnings, confirmation state, tool status, stale/adopted metadata, and untrusted-evidence attribution when present. |
| `check_result_ref` | Coverage pass and truthfulness pass | Required on pass. | Ref must be redacted/minimal and owned by checker; Composer output text is not a check result. |
| `failure_reasons` | Coverage fail and truthfulness fail | Required on fail. | Must be safe metadata; failures block playback for the candidate. |
| `truthfulness_level` | `PROGRESS_TRUTHFULNESS_CHECK_PASSED` | Required on pass. | Current spec examples include `STATE_GROUNDED` and `STYLE_ONLY_ACK`; any broader enum needs later checker policy/spec work, not model invention. |
| `approved_check_event_id` | `PLAYBACK_SPAN_STARTED` | Optional in registry; mandatory when checks are required. | Must point to passed check event or equivalent replayable causal chain. A failed check or Composer self-report is invalid. |
| `playback_span_id` | `PLAYBACK_SPAN_STARTED` | Required. | Talker-owned playback state id; Composer/checker do not own it. |
| `audio_ref` / `tts_stream_ref` | `PLAYBACK_SPAN_STARTED` | One of required. | Must not point to raw audio committed to repo; refs must satisfy trace/replay privacy rules. |

## 6. Thinker/Composer evidence 到 Composer/checker events 的映射表

| Evidence / case | Evidence label | May map to | Upstream evidence only | Forbidden / No-Go mapping |
| --- | --- | --- | --- | --- |
| Composer immutable facts | `observed_real_shape_degraded_safety` for prior parseable shape; `synthetic_eval` for boundary matrix | `SPOKEN_PLAN_EMITTED(source_commitment_id=..., coverage_check_required=true)` then coverage pass/fail | Candidate text, protected-field diff inputs, style realization hints | No Composer-owned `SEMANTIC_COMMITMENT_EMITTED`; no self-attested coverage pass. |
| must-say fields | `synthetic_eval` | Coverage check `checked_fields` includes `must_say_fields`; pass may gate playback | Must-say source list and candidate spoken realization | No omission hidden by tone/style; no playback if must-say missing. |
| missing must-say failure | `synthetic_eval` | `COMMITMENT_COVERAGE_CHECK_FAILED(failure_reasons=[missing_must_say...])` | Failure diagnostics for regeneration/planning | No `PLAYBACK_SPAN_STARTED` for failed candidate. |
| risk warning preservation | `synthetic_eval` | Coverage pass only if `risk_warnings` are preserved; otherwise coverage fail | Risk warning refs from SemanticCommitment | No softening/removal of risk warnings; no changing warning severity. |
| confirmation state preservation | `synthetic_eval` | SpokenPlan may express source-bound pending/accepted/rejected state; coverage checks protected field | `CONFIRMATION_REQUIRED`, `WAITING_FOR_USER_CONFIRMATION`, `CONFIRMATION_ACCEPTED`, `CONFIRMATION_REJECTED` source refs | No inferring acceptance from raw user text; no pending -> accepted rewrite. |
| stale evidence rejection | `synthetic_eval` | Coverage pass only if unadopted stale evidence is excluded or explicitly labeled as stale/non-current | `TOOL_RESULT_MARKED_STALE`, `STALE_EVIDENCE_RECORDED`, optional `STALE_EVIDENCE_ADOPTED` | No stale result as current fact without `STALE_EVIDENCE_ADOPTED`. |
| demo/dry-run status truthfulness | `synthetic_eval`; current demo tool fixtures are observed main contract evidence | Progress truthfulness check with source events and truthfulness level | demo/sandbox/dry-run labels, tool manifest/source metadata | No describing demo sandbox as real external side effect. |
| webSearch attribution / degraded expression | Thinker boundary `observed_real` for untrusted separation; dedicated suite count `unknown`; webSearch tool fixture observed on `main@275437e` | SpokenPlan may cite/attribute untrusted evidence; coverage/truthfulness checks verify attribution/degraded wording | `TOOL_RESULT_RECEIVED(trust_level=UNTRUSTED_WEB_EVIDENCE)`, source refs, redaction status | No web content as instruction; no policy mutation; no raw large web content. |
| tool progress/result speech | Tool source events observed on current main; model spike evidence remains planning hint | `SPOKEN_PLAN_EMITTED(source_progress_event_ids=[...], truthfulness_check_required=true)` then truthfulness pass/fail | `WAITING_FOR_TOOL`, `TOOL_PROGRESS_UPDATED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, stale/adopt chain | No "already done" before result/UI patch; no model text as tool result; no unadopted old-plan result as current. |

## 7. Domain-specific mapping boundaries

| Domain | 可映射到哪些 Composer/checker events | 只能作为 upstream evidence 的部分 | Forbidden / No-Go mapping | Evidence label |
| --- | --- | --- | --- | --- |
| Thinker SemanticFrame | None directly to checker pass; after SlowTask emits commitment/progress, may indirectly inform `SPOKEN_PLAN_EMITTED`. | Intent hints, slot hints, uncertainty, ASR/Thinker conflict, emotion/audio-caption hints, web evidence separation. | Thinker output as SemanticCommitment, resolved arguments, confirmation, checker pass, playback approval. | `observed_real`, `observed_degraded`, `synthetic_eval`, `unknown`, `unsupported` by field. |
| Thinker-as-Composer | `SPOKEN_PLAN_EMITTED` candidate only. | Spoken realization, ordering, style, persona, pace, low-risk phrasing. | Coverage pass/fail, truthfulness pass/fail, playback span start, fact ownership. | Prior shape `observed_real_shape_degraded_safety`; boundary checks `synthetic_eval`; self-attestation `unsupported`. |
| SlowTask / SemanticCommitment | `SEMANTIC_COMMITMENT_EMITTED` source for `SPOKEN_PLAN_EMITTED`; source for coverage checks. | Commitment refs, immutable facts, must-say fields, resolved arguments, risk warnings, confirmation/tool/stale metadata. | Composer rewriting SlowTask facts; old-plan commitment without adoption. | Current-main mock/replay contract observed; model spike old evidence historical. |
| Tool Executor / demo tools | Progress source events for `SPOKEN_PLAN_EMITTED`; truthfulness checks; webSearch attribution checks. | Tool manifest, progress refs, UI patch refs, result refs, trust/source labels. | Model/provider output as `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, or current-plan adoption. | Current main tool source events observed; model spike tool proposals are proposal-only. |
| webSearch / RAG | Source evidence for attributed/degraded `SPOKEN_PLAN_EMITTED`; coverage/truthfulness verifies untrusted label. | Query, source refs, short redacted/synthetic summaries, `UNTRUSTED_WEB_EVIDENCE`. | Instruction placement, policy mutation, direct UI/backend action, large raw content. | Standalone readiness `unknown`; boundary shape `observed_real` / `synthetic_eval`; real MVP2 external fetch `unsupported` without approval. |
| TTS / Talker | `PLAYBACK_SPAN_STARTED` after approved check; playback state only. | `audio_ref` / `tts_stream_ref`, playback offsets, truncate chain metadata. | TTS provider output as checker pass; playback committed as user acknowledgement; raw audio in repo. | TTS provider synthesis historical `observed_real` / `observed_degraded`; gating chain here is contract/planning. |
| ASR / Duplex / VAD | None directly to Composer/checker pass. | Transcript/timing, speech boundary, barge-in evidence for Interaction/Talker flows. | ASR/VAD as semantic truth, confirmation, progress truthfulness approval, or playback approval. | ASR/VAD evidence labels remain field-specific and historical unless re-run. |

## 8. SemanticCommitment-derived speech mapping

Canonical chain:

```text
SEMANTIC_COMMITMENT_EMITTED(commitment_id=C, task_id=T, plan_version=N, task_event_seq=S)
-> SPOKEN_PLAN_EMITTED(
     spoken_plan_id=P,
     source_commitment_id=C,
     coverage_check_required=true,
     source_progress_event_ids=[... if any progress context is spoken ...]
   )
-> COMMITMENT_COVERAGE_CHECK_PASSED(spoken_plan_id=P, source_commitment_id=C, checked_fields=[...], check_result_ref=...)
-> PLAYBACK_SPAN_STARTED(spoken_plan_id=P, approved_check_event_id=<coverage pass event id>, audio_ref or tts_stream_ref=...)
```

Failure branch:

```text
SPOKEN_PLAN_EMITTED(...)
-> COMMITMENT_COVERAGE_CHECK_FAILED(failure_reasons=[...])
-> no PLAYBACK_SPAN_STARTED for that SpokenPlan
```

Mapping rules:

- Composer 只能实现 spoken realization：措辞、排序、分段、语气、persona/style、低风险口语化。
- `immutable_facts` 必须逐项覆盖或保持不变；不能改数字、日期、地点、人名、联系人、状态值、否定语义。
- `must_say_fields` 必须被 coverage checker 验证；缺失时 coverage failed。
- `resolved_arguments` 必须按 SlowTask owner-provided refs 表达，不能从 model text 重新推断。
- Risk warnings 必须保留，不得弱化为普通提示。
- Confirmation state 必须按 SlowTask source 表达；pending 不能说成 accepted。
- Tool status 必须按 Tool Executor / SlowTask source 表达；proposal 不能说成 execution。
- Stale/adopted evidence metadata 必须保留：未 adopted 的 stale evidence 不得表达为 current fact；已 adopted 的 stale evidence 必须可追溯到 `STALE_EVIDENCE_ADOPTED`。
- Coverage check gate playback：SemanticCommitment-derived speech 未通过 `COMMITMENT_COVERAGE_CHECK_PASSED` 前不得进入 Talker playback。

## 9. Progress speech mapping

Canonical chain:

```text
progress source event(s)
-> SPOKEN_PLAN_EMITTED(
     spoken_plan_id=P,
     source_progress_event_ids=[source event ids],
     coverage_check_required=false or true if commitment facts are included,
     truthfulness_check_required=true
   )
-> PROGRESS_TRUTHFULNESS_CHECK_PASSED(
     spoken_plan_id=P,
     source_progress_event_ids=[source event ids],
     truthfulness_level=STATE_GROUNDED or STYLE_ONLY_ACK,
     check_result_ref=...
   )
-> PLAYBACK_SPAN_STARTED(spoken_plan_id=P, approved_check_event_id=<truthfulness pass event id>, ...)
```

Progress source event requirements:

- Every progress claim must cite one or more recorded `source_progress_event_ids`。
- Source events must bind current `task_id` / `plan_version` / `task_event_seq` when task-related。
- If source is old-plan result, speech must wait for stale marking and adoption before current-fact wording。
- Progress speech must not use raw provider/tool/web payload as unchecked source。

`truthfulness_level` guidance:

| Level | Allowed use | Not allowed |
| --- | --- | --- |
| `STATE_GROUNDED` | The spoken wording directly matches recorded state, tool, UI patch, result, failure, waiting, or finalizing events. | Claims stronger completion than the source event proves. |
| `STYLE_ONLY_ACK` | Short acknowledgement without state progress claim, such as saying the system will work on it. | "Already done", "I updated it", "the tool finished", or any factual state claim. |

Wording gates:

- "正在处理 / 正在查 / 等工具返回" 类 wording requires `WAITING_FOR_TOOL` or `TOOL_PROGRESS_UPDATED`。
- "界面已更新 / 备忘录已创建 / 手电筒已切换" 类 wording requires `TOOL_UI_STATE_PATCHED` for that state mutation。
- "工具已完成 / 查到了结果" 类 wording requires `TOOL_RESULT_RECEIVED` with appropriate result status and current-plan/stale policy。
- `TOOL_UI_STATE_PATCHED` 前不得声称 UI 已变更。
- `TOOL_RESULT_RECEIVED` 前不得声称工具已完成。
- `CONFIRMATION_ACCEPTED` 前不得声称用户已确认。
- `SEMANTIC_COMMITMENT_EMITTED` 前不得声称复杂任务最终事实已确定。
- `SLOWTASK_FAILED` must be spoken truthfully as failure/degraded state, not as success.

## 10. Playback gating mapping

Playback gate contract:

- `PLAYBACK_SPAN_STARTED.approved_check_event_id` must reference the relevant passed checker event when `coverage_check_required=true` or `truthfulness_check_required=true`。
- Failed coverage/truthfulness check must block playback for the candidate SpokenPlan。
- Model self-attestation, model JSON field such as `coverage_passed=true`, or provider prose cannot replace checker-owned pass events。
- Talker owns `playback_span_id`, `audio_ref` / `tts_stream_ref`, progress, committed, finished, truncate request/result state。

Mixed speech caveat:

- If one SpokenPlan combines SemanticCommitment facts and progress claims, both coverage and truthfulness gates are required.
- Current contract allows `approved_check_event_id` as one field or an equivalent causal chain. Until implementation chooses a concrete chain, a mixed candidate should not start playback unless both pass events are replayably linked to the same `spoken_plan_id`。
- Do not invent a merged pass/fail event name without ADR-002 and registry update.

Observed main caveat:

- `PlaybackState` stores `approved_check_event_id` and accepts passed check event names as playback reducer inputs.
- Runtime Composer/checker implementation and full gate enforcement were not observed on `main@275437e`; this document maps contract obligations, not completed runtime behavior.

## 11. webSearch / untrusted evidence expression

Required expression rules:

- webSearch result must be labeled `UNTRUSTED_WEB_EVIDENCE`。
- Speech must use attribution or degraded expression, such as "根据搜索结果/网页证据显示..." rather than asserting as system-owned fact when source remains untrusted。
- webSearch content goes into evidence area only, not instruction area。
- Raw large web content must not be stored in committed fixtures or this research doc。
- Web instructions cannot mutate tool policy, confirmation policy, trace/replay policy, repo policy, ADR policy, or AGENTS rules。

Mapping:

```text
TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)
-> EVIDENCE_REVIEWED(...)
-> optional SEMANTIC_COMMITMENT_EMITTED(... with attribution/degraded metadata ...)
-> SPOKEN_PLAN_EMITTED(...)
-> coverage/truthfulness check verifies attribution/degraded expression
-> PLAYBACK_SPAN_STARTED only after pass
```

No-Go:

- No webSearch result as instruction。
- No policy mutation from webpage/search text。
- No direct memo/alarm/flashlight/weather action from webSearch。
- No promotion from untrusted web evidence to trusted demo tool result by Composer wording。

## 12. 对后续 Slow LLM current-plan/stale metadata hardening 的输入

Slow LLM hardening should record, at minimum:

- `contract_snapshot=main@275437e` or newer.
- `historical_contract_snapshot=main@61e6afc` for reused 2026-05-11/12 evidence.
- Whether an output is proposal, resolved-argument evidence, progress source, stale evidence, checker input, or unsupported.
- `task_id`, `plan_version`, `task_event_seq`, `tool_call_id` when tool/progress related.
- Original `result_plan_version` and current `current_plan_version` for late ToolResult-like evidence.
- `source_progress_event_ids` for progress speech.
- `source_commitment_id` for commitment-derived speech.
- `trust_level` and `source_type` for web/external evidence.
- `may_advance_current_task=false` unless SlowTask owner emits current-plan event.
- `may_playback=false` unless required checker pass event exists and Talker references it.

Hardening No-Go:

- Slow LLM output as `COMMITMENT_COVERAGE_CHECK_PASSED` or `PROGRESS_TRUTHFULNESS_CHECK_PASSED`。
- Slow LLM output as `PLAYBACK_SPAN_STARTED`。
- Late old-plan result spoken as current without `STALE_EVIDENCE_ADOPTED`。
- Tool proposal spoken as executed.
- webSearch evidence spoken as policy/instruction.

## 13. 对后续 MVP3 planning 的输入

MVP3 planning may use this mapping for:

- Composer adapter/profile shape: output is SpokenPlan candidate only.
- Checker design inputs: protected-field diff, must-say coverage, risk warning preservation, confirmation-state preservation, stale/adopted metadata verification, webSearch attribution verification.
- Progress truthfulness design: source event id requirements and allowed wording levels.
- Playback gate design: `PLAYBACK_SPAN_STARTED.approved_check_event_id` and dual-gate handling for mixed speech.
- Adapter capability matrix fields: Composer/checker support must be separate from model self-report.

MVP3 planning must not use this mapping as:

- Runtime adapter approval.
- Proof that Qwen-Omni Composer is safe for playback.
- Proof that current main has implemented Composer/checker runtime.
- Approval to call real providers, real webSearch, microphone, playback devices, or external tools.
- Approval to edit `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/` in this research thread.

## 14. Go / No-Go checklist

| Decision | Status | Reason |
| --- | --- | --- |
| Use `main@275437e` as this mapping snapshot | Go | Actual read-only observed main is newer than `ced2077` and includes slice4 demo tools. |
| Reuse 2026-05-11/12 Thinker/Composer evidence | Go with labels | Must preserve historical `main@61e6afc` and evidence label. |
| Treat Composer output as `SPOKEN_PLAN_EMITTED` candidate | Conditional Go | Only as candidate with source refs and required check flags. |
| Treat Composer output as checker pass/fail | No-Go | Coverage/truthfulness pass/fail is checker-owned. |
| Treat model self-attestation as playback approval | No-Go | `approved_check_event_id` must reference passed checker event or replayable causal chain. |
| Speak SemanticCommitment-derived facts before coverage pass | No-Go | Coverage check gates playback. |
| Speak progress/result/UI state without source event ids | No-Go | Progress truthfulness requires recorded source events. |
| Say UI changed before `TOOL_UI_STATE_PATCHED` | No-Go | UI mutation is Tool Executor-owned and replayed from patch refs. |
| Say tool completed before `TOOL_RESULT_RECEIVED` | No-Go | Tool completion/result must be Tool Executor-owned. |
| Express unadopted stale evidence as current fact | No-Go | Requires `STALE_EVIDENCE_ADOPTED`. |
| Use webSearch evidence with attribution/degraded expression | Conditional Go | Must remain `UNTRUSTED_WEB_EVIDENCE`, evidence-only, redacted/minimal. |
| Runtime Composer/checker implementation from this doc | No-Go | Research-only mapping does not authorize implementation. |

## 15. Human approval gates

Human approval is required before:

- Editing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`。
- Updating accepted ADRs or canonical event registry/specs。
- Implementing runtime Composer/checker/model adapters。
- Connecting any real provider endpoint。
- Running real microphone, playback-device, real webSearch, or external tool experiments。
- Capturing, storing, or committing raw audio, generated audio, raw provider body, raw trace, local replay cache, secrets, cookies, credentials, auth headers, real user input, or large raw web content。
- Promoting synthetic/dry-run Composer evidence into runtime integration readiness。
- Treating webSearch/RAG as trusted instruction or policy input。
- Syncing/rebasing/merging the research branch in a way that changes the working tree。

## 16. Summary

At observed `main@275437e`, the safe mapping is:

- SlowTask owns `SEMANTIC_COMMITMENT_EMITTED` and current-plan facts.
- Composer owns only `SPOKEN_PLAN_EMITTED` candidate realization.
- Coverage Checker owns `COMMITMENT_COVERAGE_CHECK_PASSED` / `FAILED`.
- ProgressTruthfulnessCheck owns `PROGRESS_TRUTHFULNESS_CHECK_PASSED` / `FAILED`.
- Talker owns `PLAYBACK_SPAN_STARTED`, and checked speech must be tied to `approved_check_event_id`.
- Tool progress/result/UI speech must be grounded in actual Tool Executor / SlowTask events.
- webSearch remains `UNTRUSTED_WEB_EVIDENCE`, evidence-only, attributed/degraded in speech.

Recommended next threads:

1. Slow LLM current-plan/stale metadata hardening against `main@275437e`.
2. Research-only sync addendum updating older `ced2077` Tool Executor wording to `main@275437e` slice4 demo tools, if the project wants a standalone sync record.
3. MVP3 Composer/checker planning only after human approval, still without runtime/provider integration until an explicit integration lane exists.
