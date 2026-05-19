# Model Spike Slow LLM Current-Plan / Stale Metadata Hardening 2026-05-18

## 0. Status

- Status: `research_only_slow_llm_current_plan_stale_metadata_hardening`
- Date: 2026-05-18
- Lane: model spike research
- Contract snapshot: observed `main@275437e`
- Historical evidence snapshot: 2026-05-11/12 Slow LLM artifacts remain historical `main@61e6afc` unless explicitly re-mapped.

本文只做 research-only hardening。它不实现 runtime adapter，不连接真实 provider，不运行真实麦克风或播放设备，不采集真实用户录音，不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`，也不承诺任何 MVP3 runtime behavior。

## 1. 当前分支 / git 状态 / observed main snapshot

本线程只读观察到的本地状态：

```text
git status --short --branch
## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]
 M docs/research/model-spike-integration-ledger.md
?? docs/research/model-spike-adapter-profile-hardening-checklist-2026-05-12.md
?? docs/research/model-spike-composer-checker-event-mapping-2026-05-18.md
?? docs/research/model-spike-count-reconciliation-2026-05-18.md
?? docs/research/model-spike-mainline-sync-2026-05-17.md
?? docs/research/model-spike-mainline-sync-2026-05-18.md
?? docs/research/model-spike-mvp3-readiness-review-2026-05-18.md
?? docs/research/model-spike-phase-summary-2026-05-11.md
?? docs/research/model-spike-phase-summary-2026-05-12.md
?? docs/research/model-spike-tool-executor-event-mapping-2026-05-18.md
?? docs/research/profiles/
?? docs/research/spikes/...
?? tools/
```

Interpretation:

- 当前工作分支符合线程要求：`research/model-spikes`。
- 工作区已有既存 research lane 修改和未跟踪 research/tooling artifacts；本文只新增本文件。
- 这些既存 artifacts 不在本线程内归因、清理或回退。

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

本 hardening 实际只读观察到的 `main` 是 `main@275437e`，与用户给定检查目标一致。无需在本文中把 `main@275437e` 视为过期值。

相对旧 research 文档中的 baselines：

| Prior baseline | 当前观察 | 对本 hardening 的影响 |
| --- | --- | --- |
| `main@61e6afc` | 2026-05-11/12 Slow LLM real run 和 dry-run plan 的历史 contract snapshot。 | 旧 evidence 可继续引用，但必须标 `historical_contract_snapshot=main@61e6afc`，不能自动证明 current-main integration。 |
| `main@f325483` | 2026-05-18 sync addendum 观察到的 ToolExecutionState / DemoToolExecutor skeleton baseline。 | 仍是有用中间同步点，但本文件必须升级到 `main@275437e`。 |
| `main@ced2077` | 旧 Tool Executor mapping 和 count reconciliation 观察到的 Slice 3 UI patch replay baseline。 | 本文件必须覆盖后续 Slice 4 demo tools / webSearch contract signal。 |
| `main@275437e` | 本线程实际观察值，包含 MVP2 slice4 demo tools merge。 | 本文件以它作为 current contract snapshot。 |

当前 main 合同要点：

- `docs/specs/event-registry.md` 要求 SlowTask / Tool events 在 task-relevant 情况下绑定 `task_id`、`plan_version`、`task_event_seq`。
- `USER_PATCH_RECEIVED` 使用 pre-advance `plan_version`，并带 `observed_plan_version`。
- `USER_PATCH_INTERPRETED` 带 `observed_plan_version` 和 `interpreted_against_plan_version`。
- `PLAN_VERSION_ADVANCED.plan_version` 必须等于 `to_plan_version`。
- `TOOL_RESULT_RECEIVED` 保留 result 原始 `plan_version`。
- old-plan result 默认走 `TOOL_RESULT_MARKED_STALE` -> `STALE_EVIDENCE_RECORDED`，只有 `STALE_EVIDENCE_ADOPTED` 后才可复用。
- MVP1 replay 有 minimal marker variant，MVP2 replay 有 progressive Tool Executor variant。
- `TOOL_EXECUTION_STARTED`、`TOOL_UI_STATE_PATCHED`、`TOOL_RESULT_RECEIVED` 是 Tool Executor-owned lifecycle，不是 model/provider output。
- `SEMANTIC_COMMITMENT_EMITTED` 是 SlowTask-owned current-plan fact source。
- `SPOKEN_PLAN_EMITTED` 是 Composer-owned candidate realization，coverage/truthfulness pass/fail 是 Checker-owned。
- `PLAYBACK_SPAN_STARTED.approved_check_event_id` 是 checked speech 进入 playback 的关键 replay gate。
- `webSearch` 必须是 `UNTRUSTED_WEB_EVIDENCE`，content 只能进入 evidence 区。

Observed caveat:

- `docs/implementation/mvp2-backlog.md` 仍含有部分历史状态语言，称 Tool Executor / Composer / checker runtime 尚未实现。
- 但 `main@275437e` commit history 和只读 grep 已显示 MVP2 ToolExecutionState、DemoToolExecutor、UI patch、demo tools 相关 fixtures/tests 已进入 main。
- 本文件按 current canonical specs 和 observed `main@275437e` surface 做 mapping；Composer/checker runtime 仍不得写成已证明完成。

## 3. 本 hardening 的范围和非目标

In scope:

- 将 2026-05-11/12 Slow LLM Qwen / DeepSeek / retry dry-run evidence 映射到 observed `main@275437e` 的 current-plan、tool lifecycle、stale result、Composer/checker playback gating contract。
- 明确 Slow LLM provider/model output、SlowTask-owned events、Tool Executor-owned events、Checker-owned events 的边界。
- 给后续 MVP3 Slow LLM adapter planning 提供 metadata checklist、No-Go mapping 和 approval gates。
- 保留 evidence label：`observed_real`、`observed_degraded`、`synthetic_eval`、`unknown`、`unsupported`。

Out of scope:

- 不实现 runtime Slow LLM adapter。
- 不接真实 DashScope、DeepSeek 或任何 provider。
- 不运行真实 webSearch、真实 demo tools、真实外部写操作或 UI/backend mutation。
- 不新增 canonical event name，不改 ADR、specs、tests 或 runtime。
- 不把 synthetic dry-run / full_synthetic case count 升级为 real provider capability。
- 不让 model self-attestation 替代 Checker pass。
- 不新增 raw audio、raw trace、local replay cache、secret、真实用户输入或 large raw web content。

## 4. Slow LLM evidence inventory

| Evidence area | Source | Evidence label | Current-main interpretation |
| --- | --- | --- | --- |
| observed real JSON / schema validation | `slow-llm-dashscope-qwen-json-run-2026-05-11.md` | `observed_real` | Qwen `qwen3.6-plus` 在 metadata-only real run 中产出 JSON object，local parse/schema validation pass。只能作为 adapter output evidence，不能直接推进 SlowTask state。 |
| bounded repair | Qwen run + profile addendum | `observed_real` | 弱 schema induced failure 被 local validator 捕获，bounded repair 第 2 次 strict-schema pass。Future adapter 可规划 bounded retry metadata，但最终有效输出仍需 SlowTask review。 |
| insufficient evidence / missing slot | Qwen run | `observed_real` | model 输出了 `INSUFFICIENT_EVIDENCE_FOR_ACTION`-compatible behavior，没有猜 date。映射到 SlowTask evidence review/clarification planning hint，不是 provider-owned journal event。 |
| conflict preservation | Qwen run | `observed_real` | ASR/Thinker conflict 未被模型折叠成 field winner。可支撑 ambiguity preservation policy hint，不支撑 resolved argument。 |
| tool proposal shape | Qwen run + retry eval | `observed_real_for_proposal_shape` | schema-level `tool_call_proposal` 带 confirmation flag。只能进入 proposal evidence；Tool Executor owns manifest、ready args、authorization、execution、UI patch、result。 |
| web evidence boundary | Qwen run + retry eval | `observed_real` for boundary shape, `synthetic_eval` for retry matrix | synthetic `UNTRUSTED_WEB_EVIDENCE` 保持 evidence-only，未进入 instruction。后续 prompt 必须保留 evidence-only placement。 |
| timeout / retry / cancellation / late result | Qwen run + retry eval plan/tool | timeout `observed_degraded`; retry/stale mostly `synthetic_eval`; provider cancel `unknown` | client timeout observed as curl exit 28 / HTTP 000。不得伪造成 provider-confirmed cancellation。late / stale / adoption matrix 主要来自 synthetic harness。 |
| DeepSeek deferred comparison | `slow-llm-deepseek-json-run-2026-05-11.md` | `unknown_runtime` | `DEEPSEEK_API_KEY` missing，未执行。只能作为 docs-shaped comparison candidate；不能支撑 observed capability 或 MVP3 readiness。 |

Slow LLM retry eval harness inventory:

- `SMOKE_CASES`: 5 cases，summary 中 observations=5。
- `FULL_SYNTHETIC_CASES`: 21 cases，profile/ledger 中作为 full_synthetic count。
- Harness writes synthetic metadata under `/private/tmp/voice-agent-slow-llm-retry-eval/` by default。
- `live-run` fails closed；provider probing disabled without separate approval。
- Observation shape includes `task_binding`, `adapter_result`, `slowtask_effect`, `tool_boundary`, `privacy`, `boundary_assertions`。
- Harness is not runtime events and must not be imported by `src/voice_agent`。

## 5. current-plan required metadata matrix

| Field | Required owner / event surface | Slow LLM hardening rule |
| --- | --- | --- |
| `task_id` | SlowTask / Tool Executor / task-bound events | Slow LLM observation may carry it as request binding metadata. It does not let provider own task state. |
| `plan_version` | SlowTask / Tool Executor events | Provider output must preserve original request/result plan. Current-plan use requires comparison to SlowTask current plan at arrival. |
| `observed_plan_version` | `USER_PATCH_RECEIVED`, `USER_PATCH_INTERPRETED` | Needed when model evidence is interpreted after user patch. It is not the same as the result's original `plan_version`. |
| `interpreted_against_plan_version` | `USER_PATCH_INTERPRETED` | SlowTask-owned interpretation field. Model output can be evidence, but cannot set authoritative interpretation. |
| `task_event_seq` | All SlowTask-relevant events | Assigned at journal append/accept boundary. Provider output must not be trusted as authoritative sequence. |
| `tool_call_id` | Tool Executor lifecycle and stale events | Slow LLM may propose a tool-like action, but Tool Executor / owner binds actual `tool_call_id`. |
| `idempotency_key` | write/action tool execution and UI patch | Tool Executor-owned. Model/provider text must not allocate replay authority keys. |
| `resolved_arguments_ref` | `ARGUMENTS_RESOLVED`, `TOOL_ARGUMENTS_READY` | Comes from SlowTask current-plan argument resolution and provenance, not direct model text. |
| `provenance_ref` | `ARGUMENTS_RESOLVED`, `TOOL_ARGUMENTS_READY` | Slow LLM evidence can contribute refs; SlowTask/Tool Executor validate and own accepted provenance. |
| `confirmation_id` | SlowTask confirmation events and Tool authorization | Provider "confirmed" wording is not `confirmation_id`, not `CONFIRMATION_ACCEPTED`, and not authorization. |
| `result_plan_version` | `TOOL_RESULT_MARKED_STALE` | Must equal original result's `plan_version` when old-plan output arrives. |
| `current_plan_version` | `TOOL_RESULT_MARKED_STALE` | Must equal SlowTask current plan when stale marking occurs. |
| `source_tool_result_event_id` | `STALE_EVIDENCE_RECORDED`, `STALE_EVIDENCE_ADOPTED` | Required to trace stale evidence to the original ToolResult-like event/ref. |
| `stale_evidence_ref` | `STALE_EVIDENCE_RECORDED`, `STALE_EVIDENCE_ADOPTED` | Redacted/minimal ref only. No raw provider payload. |
| `adopted_from_plan_version` | `STALE_EVIDENCE_ADOPTED` | Required if stale evidence is reused. Must name original plan. |
| `adopted_scope` | `STALE_EVIDENCE_ADOPTED` | Required bounded scope. No unbounded reuse of old output. |
| `source_commitment_id` | `SPOKEN_PLAN_EMITTED`, coverage checks | Composer/checker input only after SlowTask emits current-plan `SEMANTIC_COMMITMENT_EMITTED`. |
| `source_progress_event_ids` | `SPOKEN_PLAN_EMITTED`, truthfulness checks | Progress speech must cite actual recorded progress/tool/stale/adopt events. Model narration alone is insufficient. |

Minimum additional adapter-planning metadata:

- `adapter_request_id`
- `adapter_id`
- `adapter_type=slow_llm`
- `output_mode=real | mock | fallback | degraded`
- `parse_status`
- `schema_status`
- `final_validation_status`
- `retry_count`
- `retry_reason`
- `timeout_ms`
- `provider_cancel_confirmed`
- `raw_provider_body_stored=false`
- `may_advance_current_task=false` unless SlowTask owner emits current-plan event

## 6. Slow LLM output type 到 current-main events 的映射表

| Slow LLM output / condition | Evidence label | May map to current-main events | Required owner transition | No-Go mapping |
| --- | --- | --- | --- | --- |
| valid structured JSON | `observed_real` if local validation passes | Adapter output metadata; later `EVIDENCE_REVIEWED`, `ARGUMENTS_RESOLVED` only if SlowTask accepts | Adapter validates; SlowTask reviews and emits current-plan events | No direct `ARGUMENTS_RESOLVED`, `SEMANTIC_COMMITMENT_EMITTED`, `TOOL_ARGUMENTS_READY`, or state mutation by provider output. |
| malformed JSON / validation failure | `synthetic_eval` for malformed; `observed_real` for weak-schema failure detection | `ADAPTER_OUTPUT_VALIDATION_FAILED`; optional bounded retry metadata | Adapter / schema validator owns failure and retry metadata | No downstream SlowTask consumption; no repair by silent guess; no commitment. |
| bounded repair success | `observed_real` for Qwen prior run | `ADAPTER_REQUEST_RETRYING`-compatible metadata, then valid adapter output evidence | Adapter owns retry count/reason; SlowTask later reviews final valid output | No duplicate state transition per attempt; no unlimited retry. |
| missing required fields | `observed_real` for Qwen missing-slot behavior | `EVIDENCE_REVIEWED`, `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `CLARIFICATION_REQUESTED`, `WAITING_FOR_SLOT` after SlowTask review | SlowTask owns missing/ambiguous decision | No guessed args; no `TOOL_ARGUMENTS_READY`; no execution. |
| conflict / ambiguity | `observed_real` for conflict preservation | `EVIDENCE_REVIEWED`, `AMBIGUITY_DETECTED`, possibly `CLARIFICATION_REQUESTED` | SlowTask owns resolution or clarification | No provider-selected winner as current fact. |
| tool proposal | `observed_real_for_proposal_shape` | Potential input to `TOOL_ARGUMENTS_PARTIAL`; after SlowTask `ARGUMENTS_RESOLVED`, Tool Executor may emit `TOOL_ARGUMENTS_READY` | SlowTask owns resolved args; Tool Executor owns tool lifecycle | No `TOOL_EXECUTION_AUTHORIZED`, `TOOL_EXECUTION_STARTED`, `TOOL_UI_STATE_PATCHED`, `TOOL_RESULT_RECEIVED`, or `CONFIRMATION_ACCEPTED`. |
| tool-like provider output | docs/provider-native support may be `docs_only_unobserved` for DeepSeek, Qwen run kept disabled | Normalize to proposal evidence only | Adapter strips/provider-normalizes; Tool Executor decides later | No provider-native tool execution; no external side effect. |
| timeout | `observed_degraded` for Qwen client timeout | `ADAPTER_REQUEST_FAILED` with timeout metadata; optional retry metadata if policy allows | Adapter owns failure; SlowTask may degrade/fail/wait separately | No provider cancellation success; no task completion. |
| retryable failure | `synthetic_eval` unless observed live | `ADAPTER_REQUEST_RETRYING`; final valid output or `ADAPTER_REQUEST_FAILED` | Adapter owns retry budget and failure category | No unbounded retry; no duplicate tool proposal/current-plan update. |
| provider cancellation unknown | `unknown` | `ADAPTER_OUTPUT_DEGRADED` / failure metadata noting unsupported or unconfirmed cancellation | Adapter capability matrix records unknown/degraded | No `TOOL_EXECUTION_CANCELLED(cancel_status=success)`; no success claim from client close. |
| late result | Mostly `synthetic_eval`; same-plan live behavior unknown | If tool-like result: `TOOL_RESULT_RECEIVED` with original plan then stale chain if old-plan; if adapter output: stale/debug metadata until SlowTask review | Tool Executor or Adapter records original binding; SlowTask decides stale/adopt | No current-plan advance before `STALE_EVIDENCE_ADOPTED`; no terminal task revival. |
| web evidence | Qwen boundary `observed_real`; standalone webSearch/RAG count `unknown` | webSearch Tool path only after Tool Executor: `TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)`; then `EVIDENCE_REVIEWED` | Tool Executor owns webSearch ToolResult; SlowTask owns evidence review | No instruction placement, no policy mutation, no raw large web content, no trusted upgrade. |

## 7. stale result mapping

### MVP1 minimal marker variant

MVP1 minimal fixture shape:

```text
TOOL_CALL_STARTED(tool_call_id=C1, task_id=T, plan_version=N, task_event_seq=A)
USER_PATCH_RECEIVED(task_id=T, plan_version=N, observed_plan_version=N, task_event_seq=B)
USER_PATCH_INTERPRETED(task_id=T, plan_version=N, observed_plan_version=N, interpreted_against_plan_version=N, materially_changes_task=true)
PLAN_VERSION_ADVANCED(task_id=T, plan_version=N+1, from_plan_version=N, to_plan_version=N+1)
TOOL_RESULT_RECEIVED(tool_call_id=C1, task_id=T, plan_version=N, task_event_seq=R)
TOOL_RESULT_MARKED_STALE(tool_call_id=C1, task_id=T, plan_version=N+1, result_plan_version=N, current_plan_version=N+1)
STALE_EVIDENCE_RECORDED(task_id=T, plan_version=N+1, source_tool_result_event_id=...)
optional STALE_EVIDENCE_ADOPTED(...)
```

Rules:

- `TOOL_CALL_STARTED` is a marker, not execution.
- `TOOL_RESULT_RECEIVED.plan_version=N` remains original result binding.
- `TOOL_RESULT_MARKED_STALE.plan_version=N+1` reflects current plan at stale marking.
- `task_event_seq` must be monotonic and must not be reused from the old tool call.
- Without `STALE_EVIDENCE_ADOPTED`, stale output cannot update resolved arguments, confirmation state, tool readiness, SemanticCommitment, or terminal state.

### MVP2 progressive Tool Executor variant

MVP2 progressive shape:

```text
TOOL_EXECUTION_STARTED(tool_call_id=C1, task_id=T, plan_version=N, task_event_seq=A)
USER_PATCH_RECEIVED(task_id=T, plan_version=N, observed_plan_version=N, task_event_seq=B)
USER_PATCH_INTERPRETED(task_id=T, plan_version=N, interpreted_against_plan_version=N, materially_changes_task=true)
PLAN_VERSION_ADVANCED(task_id=T, plan_version=N+1, from_plan_version=N, to_plan_version=N+1)
optional TOOL_EXECUTION_CANCEL_REQUESTED(tool_call_id=C1, task_id=T, plan_version=N+1)
TOOL_RESULT_RECEIVED(tool_call_id=C1, task_id=T, plan_version=N, task_event_seq=R)
TOOL_RESULT_MARKED_STALE(tool_call_id=C1, task_id=T, plan_version=N+1, result_plan_version=N, current_plan_version=N+1)
STALE_EVIDENCE_RECORDED(task_id=T, plan_version=N+1, source_tool_result_event_id=...)
optional STALE_EVIDENCE_ADOPTED(...)
```

Rules:

- `tool_call_id` links execution, result, stale marker, and adoption source.
- Tool Executor records lifecycle/result; SlowTask owns stale marking and adoption/rebase.
- Old `plan_version` default stale when `result_plan_version < current_plan_version`。
- `STALE_EVIDENCE_ADOPTED` 前不得推进 current plan。
- Unsupported cancellation 不得伪造成 success。If provider/tool cancellation is unknown or unsupported, record degraded/unknown metadata and handle any late output through stale policy.

## 8. SemanticCommitment mapping

Slow LLM may be upstream evidence for SlowTask, but it does not own `SEMANTIC_COMMITMENT_EMITTED`。

Canonical current-plan chain:

```text
validated Slow LLM evidence
-> EVIDENCE_REVIEWED(task_id=T, plan_version=N)
-> optional AMBIGUITY_DETECTED / INSUFFICIENT_EVIDENCE_FOR_ACTION / ARGUMENTS_RESOLVED
-> FINALIZING(task_id=T, plan_version=N, source_events=[...])
-> SEMANTIC_COMMITMENT_EMITTED(commitment_id=K, task_id=T, plan_version=N, source_events=[...])
```

Rules:

- SlowTask owns `SEMANTIC_COMMITMENT_EMITTED`。
- Commitment must be current-plan only。
- If adopted stale evidence contributes to commitment, `source_events` must include `STALE_EVIDENCE_ADOPTED` and commitment metadata must preserve:
  - `stale_evidence_ref`
  - `source_tool_result_event_id`
  - `adopted_from_plan_version`
  - `adopted_scope`
  - adoption reason/mode where available
- Slow LLM validated JSON may support `source_events` or evidence refs, but cannot directly emit commitment。
- No-Go: Slow LLM output as `SEMANTIC_COMMITMENT_EMITTED`。
- No-Go: unadopted stale output as commitment fact。
- No-Go: malformed/invalid output as commitment source。

## 9. Tool Executor mapping

Slow LLM tool proposal 何时只能是 proposal evidence:

- Provider output contains action/tool-like shape but lacks current-plan resolved args/provenance.
- Missing fields, ambiguity, or confirmation requirement remains unresolved.
- Provider-native tool calling surface is observed or docs-described but not normalized by Tool Executor.
- Output came from old plan, terminal task, retry failure, or unvalidated payload.

When it may support `TOOL_ARGUMENTS_PARTIAL`:

- The proposal has a recognized tool intent and partial structured arguments.
- Missing fields are explicit and safe metadata.
- `task_id`, `plan_version`, `task_event_seq`, and `tool_call_id` are bound by owner/journal path.
- Tool Executor can record `partial_arguments_ref` and `missing_fields` without execution.

When it may support `TOOL_ARGUMENTS_READY`:

- SlowTask has already emitted current-plan `ARGUMENTS_RESOLVED` with `resolved_arguments_ref` and `provenance_ref`.
- Tool manifest permits the tool and side-effect class.
- Required confirmation state, if any, is satisfied or preview/confirmation flow is still pending.
- Tool Executor validates current `task_id`, `plan_version`, `task_event_seq`, provenance, and idempotency requirements.

Why Slow LLM output cannot map to authorization / execution / UI patch / result:

- `TOOL_EXECUTION_AUTHORIZED` requires Tool Executor policy allow or current-plan `CONFIRMATION_ACCEPTED`。
- `TOOL_EXECUTION_STARTED` is actual sandbox execution start and requires authorization/current-plan gates。
- `TOOL_UI_STATE_PATCHED` is the only demo UI/backend mutation path and requires `ui_patch_id`, `idempotency_key`, `patch_ref` from Tool Executor/backend path。
- `TOOL_RESULT_RECEIVED` is normalized Tool Executor result metadata with trust/source labels。
- Provider text lacks manifest validation, side-effect gate, idempotency, confirmation authority, replayable patch refs, and result normalization authority。

## 10. Composer/checker/playback implications

Core implications:

- Old-plan / stale result 不得被说成 current fact。
- Progress speech 必须引用 `source_progress_event_ids`。
- SemanticCommitment-derived speech must reference `source_commitment_id`。
- `SPOKEN_PLAN_EMITTED` is a candidate, not a pass event。
- `approved_check_event_id` on `PLAYBACK_SPAN_STARTED` must reference the passed coverage/truthfulness check event or an equivalent replayable causal chain。
- Model self-attestation such as `coverage_passed=true` or "我已经检查过" 不得替代 Checker pass。

Valid speech chain:

```text
SEMANTIC_COMMITMENT_EMITTED or progress source event
-> SPOKEN_PLAN_EMITTED
-> COMMITMENT_COVERAGE_CHECK_PASSED or PROGRESS_TRUTHFULNESS_CHECK_PASSED
-> PLAYBACK_SPAN_STARTED(approved_check_event_id=<passed check event id>)
```

Progress wording examples by source:

| Speech claim | Required source event |
| --- | --- |
| "正在重新规划" | `PLANNING_RESTARTED` or `TASK_REPLANNED` |
| "还缺字段，需要确认" | `WAITING_FOR_SLOT` / `CLARIFICATION_REQUESTED` |
| "正在等工具返回" | `WAITING_FOR_TOOL` or `TOOL_PROGRESS_UPDATED` |
| "界面已更新" | `TOOL_UI_STATE_PATCHED` |
| "工具已返回结果" | current-plan `TOOL_RESULT_RECEIVED`; if old-plan, require stale/adopt chain before current-fact wording |
| "最终事实已确定" | current-plan `SEMANTIC_COMMITMENT_EMITTED` plus required coverage pass before playback |

No-Go:

- No playback after `COMMITMENT_COVERAGE_CHECK_FAILED` or `PROGRESS_TRUTHFULNESS_CHECK_FAILED`。
- No tool proposal spoken as executed。
- No demo sandbox result spoken as real external side effect。
- No untrusted web evidence spoken as policy or instruction。

## 11. webSearch / untrusted evidence implications

Required labels and placement:

- webSearch result must carry `trust_level=UNTRUSTED_WEB_EVIDENCE`。
- Source type should be `EXTERNAL_READ_UNTRUSTED` for webSearch-like evidence。
- Prompt placement must keep web content in evidence-only area, never instruction area。
- Retry prompts must not accidentally move untrusted evidence into instruction context。
- Search/web content cannot mutate tool policy, confirmation policy, trace/replay policy, repo policy, ADR policy, or AGENTS rules。
- No raw large web content should be committed. Use refs, redacted summaries, synthetic snippets, source ids, redaction status。

Mapping:

```text
TOOL_RESULT_RECEIVED(source_type=EXTERNAL_READ_UNTRUSTED, trust_level=UNTRUSTED_WEB_EVIDENCE)
-> EVIDENCE_REVIEWED(task_id=T, plan_version=N)
-> optional ARGUMENTS_RESOLVED / SEMANTIC_COMMITMENT_EMITTED with attribution/degraded metadata
-> SPOKEN_PLAN_EMITTED
-> coverage/truthfulness check verifies attribution and untrusted label
-> PLAYBACK_SPAN_STARTED only after pass
```

No-Go:

- No webSearch as instruction。
- No webpage/search result policy mutation。
- No direct memo/alarm/flashlight/weather action from web evidence。
- No promotion from `UNTRUSTED_WEB_EVIDENCE` to `TRUSTED_DEMO_TOOL_RESULT` by model wording。
- No large raw web content in replay fixtures or research docs。

## 12. evidence label 表

| Label | Meaning | Slow LLM examples | Use in this hardening |
| --- | --- | --- | --- |
| `observed_real` | Directly observed in metadata-only real-provider/local run. | Qwen validated JSON, local schema validation, bounded repair, missing slot preservation, conflict preservation, web boundary shape, tool proposal shape. | Can support bounded planning claim for that observed surface only. |
| `observed_degraded` | Directly observed but target behavior incomplete or degraded. | Qwen client timeout; cancellation not provider-confirmed. | Can support failure/degradation policy, not success capability. |
| `synthetic_eval` | Spike-local deterministic synthetic harness only. | 21-case retry/stale/cancel/tool/web matrix, explicit stale adoption shape, malformed JSON, retry budget exhausted. | Supports event-shape and owner-boundary planning, not real provider readiness. |
| `unknown` | No reliable observed evidence. | Provider-confirmed cancellation, live late-result behavior, streaming structured JSON usability, provider-side transient failure taxonomy, current model alias/limits until re-pin. | Keep as explicit gap; design degraded/fallback behavior only. |
| `unsupported` | Outside Slow LLM role or forbidden by contract. | Audio input/output, TTS, semantic close, assistant directedness, tool execution, UI patch, confirmation acceptance, Checker pass ownership. | Must be No-Go reliance in adapter planning. |

## 13. 对后续 MVP3 Slow LLM adapter planning 的输入

Planning inputs that are safe to carry forward:

- Qwen is still the strongest Slow LLM candidate for structured JSON planning evidence, with local validation and bounded repair.
- Adapter output must be gated by parse/schema validation before SlowTask review.
- Adapter capability matrix must include real / mock / fallback / degraded labels and explicitly mark cancellation, streaming JSON, provider failures, and numeric limits.
- Every accepted observation needs task binding metadata: `task_id`, `plan_version`, `task_event_seq`, `adapter_request_id`, causal refs。
- Tool-like output remains proposal evidence and must pass through SlowTask argument/provenance review plus Tool Executor policy gates。
- Old-plan output defaults stale; adoption/rebase must be explicit and bounded。
- Composer/checker planning must require source event ids, `source_commitment_id`, `source_progress_event_ids`, and `approved_check_event_id` gate。
- webSearch/RAG planning must keep evidence-only placement and `UNTRUSTED_WEB_EVIDENCE` label。

Planning inputs that remain insufficient:

- DeepSeek comparison is deferred and `unknown_runtime`。
- Client timeout does not prove provider cancellation。
- Synthetic stale/adoption cases do not prove real late-result behavior。
- Full_synthetic count 21 does not prove provider runtime readiness。
- Provider-native tool calling docs do not authorize Tool Executor bypass。
- Current model aliases, limits, pricing/quotas, endpoint behavior are temporally unstable and must be re-pinned on any future approved live run day。

## 14. Go / No-Go checklist

| Decision | Status | Reason |
| --- | --- | --- |
| Use observed `main@275437e` as this hardening snapshot | Go | This thread's read-only `git rev-parse --short main` returned `275437e`。 |
| Reuse 2026-05-11/12 Qwen evidence | Go with labels | Must preserve historical `main@61e6afc` and case-specific evidence labels。 |
| Treat Qwen validated JSON as adapter planning evidence | Conditional Go | Only after local validation and SlowTask review; no direct state mutation。 |
| Treat bounded repair as bounded retry planning input | Conditional Go | Retry count/reason/budget must be recorded; final invalid output blocks downstream。 |
| Treat missing/conflict behavior as SlowTask evidence hint | Conditional Go | SlowTask owns insufficiency, ambiguity, resolution, and clarification events。 |
| Treat Slow LLM tool proposal as Tool Executor input | Conditional Go | Only as proposal/partial args or after owner-validated resolved args/provenance。 |
| Treat Slow LLM output as `TOOL_EXECUTION_AUTHORIZED` or `TOOL_EXECUTION_STARTED` | No-Go | Tool Executor and confirmation/policy gates own these events。 |
| Treat Slow LLM output as `TOOL_UI_STATE_PATCHED` or `TOOL_RESULT_RECEIVED` | No-Go | UI patch and normalized result are Tool Executor-owned。 |
| Use old-plan result in current plan before `STALE_EVIDENCE_ADOPTED` | No-Go | Violates current-plan / stale evidence policy。 |
| Treat unsupported cancellation as successful cancellation | No-Go | Client timeout/abort does not prove provider cancellation or tool cancellation success。 |
| Treat Slow LLM output as `SEMANTIC_COMMITMENT_EMITTED` | No-Go | SlowTask owns SemanticCommitment。 |
| Treat model self-attestation as coverage/truthfulness pass | No-Go | Checker-owned pass event and playback gate are required。 |
| Treat web evidence as instruction or policy input | No-Go | webSearch is `UNTRUSTED_WEB_EVIDENCE` and evidence-only。 |
| Start MVP3 runtime adapter implementation from this doc | No-Go | This is research-only hardening, not integration approval。 |

## 15. human approval gates

Human approval is required before:

- Editing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`。
- Updating accepted ADRs, canonical specs, event registry, or replay spec。
- Implementing runtime Slow LLM adapter or any other runtime adapter。
- Connecting real DashScope, DeepSeek, webSearch, RAG, demo tool, or external provider endpoint。
- Running real microphone, playback device, provider live probes, or real external tools。
- Installing dependencies or fetching packages over network。
- Capturing, storing, or committing raw audio, generated audio, raw provider payload, raw debug trace, local replay cache, secrets, cookies, credentials, authorization headers, real user input, unredacted tool results, or large raw web content。
- Promoting synthetic/full_synthetic dry-run counts into real provider readiness。
- Treating webSearch/RAG content as trusted instruction or policy source。
- Syncing/rebasing/merging the research branch in a way that changes working tree contents。

## 16. Summary

At observed `main@275437e`, Slow LLM hardening must be stricter than the historical 2026-05-11/12 evidence shape:

- Slow LLM provider output is evidence, not SlowTask state。
- SlowTask owns current-plan interpretation, plan advance, stale/adopt, confirmation, final facts, and `SEMANTIC_COMMITMENT_EMITTED`。
- Tool Executor owns tool arguments readiness, authorization, execution, progress, UI patch, result, failure, retry, and cancellation result。
- Checker owns coverage/truthfulness pass/fail; Talker playback must reference passed checks through `approved_check_event_id` when required。
- webSearch remains `UNTRUSTED_WEB_EVIDENCE`, evidence-only, redacted/minimal。
- The safe MVP3 planning next step is an adapter profile/planning thread, not runtime implementation。
