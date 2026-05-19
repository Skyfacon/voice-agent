# Model Spike Slow LLM MVP3 Adapter Profile Planning 2026-05-18

## 0. Status

- Status: `research_only_mvp3_slow_llm_adapter_profile_planning`
- Date: 2026-05-18
- Lane: model spike research
- Actual observed main snapshot in this thread: `main@e4311cf`
- Prior Slow LLM hardening input snapshot: observed `main@275437e`
- Historical Slow LLM provider evidence snapshot: 2026-05-11/12 artifacts remain historical `main@61e6afc` unless explicitly re-mapped.

本文只做 research-only MVP3 Slow LLM adapter profile planning。它不是 runtime integration approval，不实现 runtime adapter，不连接真实 provider，不运行真实 webSearch / demo tools / microphone / playback device，不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`，也不新增 runtime 行为承诺。

## 1. 当前分支 / git 状态 / observed main snapshot

本线程只读观察到的分支和工作区状态：

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
?? docs/research/model-spike-slow-llm-current-plan-stale-metadata-hardening-2026-05-18.md
?? docs/research/model-spike-tool-executor-event-mapping-2026-05-18.md
?? docs/research/profiles/
?? docs/research/spikes/...
?? tools/
```

Interpretation:

- 当前工作分支符合线程要求：`research/model-spikes`。
- 工作区已有既存 research lane 修改和未跟踪 research/tooling artifacts；本线程只新增本文。
- 这些既存 artifacts 不在本线程内归因、清理、回退或合并。

Observed main:

```text
git rev-parse --short main
e4311cf
```

Observed `main` top commits:

```text
e4311cf Merge pull request #24 from Skyfacon/mvp2/slice5-demo-destructive-confirmation
fb275c0 fix: tighten destructive confirmation replay gates
580a4c4 feat: add MVP2 destructive demo confirmations
275437e Merge pull request #23 from Skyfacon/mvp2/slice4-demo-tools
954dd07 feat: add MVP2 demo tools
ced2077 Merge pull request #22 from Skyfacon/mvp2/slice3-tool-ui-state-patch
0d2870f fix: harden MVP2 UI patch replay validation
6f6e549 feat: add MVP2 tool UI state replay
f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton
a52585b fix: harden MVP2 tool executor policy gates
2c7a567 feat: add MVP2 demo tool executor skeleton
5741ae3 Merge pull request #20 from Skyfacon/mvp2/slice1-tool-execution-state
```

## 2. 当前 main contract delta

本 planning 的实际只读观察值是 `main@e4311cf`，不是上一份 Slow LLM current-plan / stale metadata hardening 中的 `main@275437e`。

| Snapshot | 含义 | 对本 planning 的影响 |
| --- | --- | --- |
| `main@61e6afc` | 2026-05-11/12 Qwen / DeepSeek / retry planning 的历史基线。 | 旧 evidence 可继续引用，但必须标为 historical evidence，不能自动证明 current-main integration。 |
| `main@275437e` | 上一份 Slow LLM hardening 的 observed main，包含 MVP2 slice4 demo tools / webSearch boundary。 | 仍是直接输入，但本文件必须补上之后的 destructive confirmation delta。 |
| `main@e4311cf` | 本线程实际观察到的 main，包含 MVP2 slice5 demo destructive confirmation。 | 本文件以它作为 current contract snapshot；Slow LLM tool-like output 必须更明确地停在 proposal/partial args，不能越过 current-plan confirmation gate。 |

相对 `275437e` 的新增 contract signal：

- `580a4c4` / `fb275c0` / `e4311cf` 让 `DEMO_DESTRUCTIVE_ACTION` 的 current-plan confirmation / replay gate 更具体。
- Missing、rejected、stale、superseded confirmation 必须 block `TOOL_EXECUTION_STARTED`。
- Provider/model output 中的 "confirmed"、"safe to execute"、`confirmation_required=false` 等字段都不能成为 `CONFIRMATION_ACCEPTED` 或 `TOOL_EXECUTION_AUTHORIZED`。

是否需要另行 sync：

- 对本文：不阻塞。本文已直接读取 `main@e4311cf` 上的 contract 文件，并把 `e4311cf` 写为 observed snapshot。
- 对既存 5/18 research docs：建议另开 research-only sync/update thread，如果项目希望 `model-spike-tool-executor-event-mapping-*`、`composer-checker-*`、`slow-llm-current-plan-*` 都成为最新入口。

当前 main contract 要点：

- `docs/specs/model-adapter-capabilities.md` 要求每个 adapter 声明 identity、capability matrix、timeout/retry/error/output mode，并用 adapter events 表达 health/failure/validation/degradation。
- `docs/specs/event-registry.md` 已列 `ADAPTER_REQUEST_RETRYING`、`ADAPTER_REQUEST_FAILED`、`ADAPTER_OUTPUT_VALIDATION_FAILED`、`ADAPTER_OUTPUT_DEGRADED`，这些是现有 event names，不是本文新增。
- `USER_PATCH_RECEIVED`、`USER_PATCH_INTERPRETED`、`PLAN_VERSION_ADVANCED`、`TOOL_RESULT_MARKED_STALE`、`STALE_EVIDENCE_RECORDED`、`STALE_EVIDENCE_ADOPTED` 对 `task_id`、`plan_version`、`observed_plan_version`、`interpreted_against_plan_version`、`task_event_seq` 有 current-main required-field 约束。
- `TOOL_ARGUMENTS_READY`、`TOOL_EXECUTION_AUTHORIZED`、`TOOL_EXECUTION_STARTED`、`TOOL_UI_STATE_PATCHED`、`TOOL_RESULT_RECEIVED` 是 Tool Executor-owned lifecycle，不是 Slow LLM provider output。
- `SEMANTIC_COMMITMENT_EMITTED` 是 SlowTask-owned current-plan fact source。
- `SPOKEN_PLAN_EMITTED` 是 Composer-owned spoken candidate，coverage/truthfulness pass/fail 是 Checker-owned，checked playback 需要 `PLAYBACK_SPAN_STARTED.approved_check_event_id`。
- `webSearch` ToolResult 必须是 `UNTRUSTED_WEB_EVIDENCE`，内容只能进入 evidence 区，不能进入 instruction 区。
- Deterministic replay 不得重跑真实 Slow LLM、webSearch、demo tools、网络、时钟或随机数。

Observed caveat:

- `main:docs/implementation/mvp2-backlog.md` 仍含开工入口和部分历史状态语言；本 planning 按 current canonical specs、acceptance scenarios 和 observed `main@e4311cf` commit history 解释。
- 本 planning 不声称 Composer/checker runtime、real adapters 或真实 provider integration 已完成。

## 3. 本 planning 的范围和非目标

In scope:

- 将 Qwen、DeepSeek、Slow LLM retry dry-run evidence 转成 MVP3 Slow LLM adapter profile planning 输入。
- 规划 capability matrix、validation/retry/failure/cancellation policy、current-plan metadata、stale result handling、Tool Executor boundary、Composer/checker boundary、web evidence boundary。
- 明确 Slow LLM provider/model output 与 Adapter-owned metadata、SlowTask-owned event、Tool Executor-owned event、Checker-owned event 的边界。
- 保留 evidence labels：`observed_real`、`observed_degraded`、`synthetic_eval`、`unknown`、`unsupported`。

Out of scope:

- 不实现 runtime Slow LLM adapter。
- 不接真实 DashScope、DeepSeek 或任何 provider。
- 不重新查官方 provider docs，不联网安装，不运行 live provider probe。
- 不运行真实麦克风、播放设备、真实 webSearch、真实 demo tools 或真实外部副作用。
- 不新增 canonical event name，不改 ADR、specs、tests 或 runtime。
- 不把 synthetic dry-run / full_synthetic count 升级为 provider runtime proof。
- 不把本文作为 runtime integration approval 或 MVP3 implementation ticket。

## 4. Slow LLM candidate disposition

### Qwen

Decision: `primary_harden_next_for_planning_only`

| Evidence surface | Label | Planning interpretation |
| --- | --- | --- |
| Non-streaming JSON object output on DashScope-compatible Chat Completions | `observed_real` | 可作为 Slow LLM structured JSON planning input，但必须经过 adapter parse/schema validation。 |
| Local strict schema validation | `observed_real` | Adapter 必须先验证；无 valid output 不得进入 SlowTask review。 |
| Weak-schema validation failure detection | `observed_real` | Invalid output 应映射为 `ADAPTER_OUTPUT_VALIDATION_FAILED`。 |
| Bounded schema repair converged after two attempts | `observed_real` | 可规划 bounded repair；retry budget、retry reason、attempt count 必须记录。 |
| Missing slot preserved as insufficient evidence | `observed_real` | 可作为 SlowTask `INSUFFICIENT_EVIDENCE_FOR_ACTION` planning hint，不能直接生成 resolved args。 |
| ASR/Thinker conflict preserved | `observed_real` | 可作为 ambiguity planning hint，不能让 provider 选 field winner。 |
| Tool proposal shape with confirmation flag | `observed_real` for proposal shape | 只能进入 proposal/partial-args evidence；Tool Executor owns ready/authorization/execution/UI/result。 |
| Synthetic untrusted web evidence stayed evidence-only | `observed_real` for observed boundary shape | 支持 prompt boundary planning；不支持真实 webSearch readiness。 |
| Client timeout probe | `observed_degraded` | 可规划 timeout/failure metadata；不能证明 provider cancellation。 |
| Streaming structured JSON | `unknown` | API/docs surface 不等于 usable streaming JSON proof；partial chunks 不得推进 state。 |
| Provider transient failure / rate limit taxonomy | `unknown` | 后续 approved live/profile thread 才能 re-pin。 |
| Provider-confirmed cancellation | `unknown` | 不得从 client timeout / abort 推断 success。 |

Qwen 是当前 Slow LLM profile planning 的最强候选，但仍不是 runtime-ready adapter。

### DeepSeek

Decision: `comparison_deferred_unknown_runtime`

| Evidence surface | Label | Planning interpretation |
| --- | --- | --- |
| DeepSeek live run | `unknown` | `DEEPSEEK_API_KEY` missing，未执行 provider call。 |
| JSON mode / streaming / tools by docs-shaped notes | `unknown` | 只能作为 future comparison shape，不能标 `observed_real`。 |
| Timeout / retry / cancellation | `unknown` | 无 live evidence，不得用于 MVP3 readiness。 |
| Tool/function calling | `unknown` | 即使未来 observed，也只能 normalize 成 proposal evidence。 |

DeepSeek 只保留为后续同矩阵对照候选。本文不从 DeepSeek 推导任何 real capability。

### provider/model alias re-pin requirement

所有 provider/model alias、endpoint behavior、limits、pricing/quotas、streaming surface、tool calling fields、error taxonomy 都是 temporally unstable。后续任何 human-approved live hardening 或 MVP3 integration thread 必须在执行当日重新 re-pin：

- provider name
- model alias / deployment name
- endpoint ref
- max context / output limits
- JSON mode behavior
- streaming behavior
- cancellation / timeout semantics
- provider error classes / rate limit classes

本文没有联网复查，也没有 live provider call；因此不会把 2026-05-11 alias 直接写成未来 integration fact。

## 5. MVP3 Slow LLM adapter capability matrix planning

### identity fields

| Field | Planning value | Owner / rule |
| --- | --- | --- |
| `adapter_id` | e.g. `slow_llm_qwen_remote_profile_v0` | Adapter Registry owns stable id；本文不创建 runtime id。 |
| `adapter_type` | `slow_llm` | Required by capability contract。 |
| `provider` | `dashscope` for Qwen planning; `deepseek` comparison deferred | No secret-bearing value。 |
| `model_name` | `qwen3.6-plus` observed historically; re-pin required | Future run day must re-pin official/current alias。 |
| `deployment_mode` | `remote_api` for Qwen observed; `remote_api_planned` for DeepSeek | Remote API does not authorize runtime integration。 |
| `endpoint` | credential-free endpoint ref only | No keys, tokens, auth headers, cookies, signed URLs。 |
| `health_status` | `unknown_until_healthcheck`; historical Qwen JSON probes were healthy for observed cases | Startup/runtime healthcheck requires future approval。 |
| `capability_version` | planning profile version | Not a runtime capability snapshot。 |
| `latency_class` | `slowtask_background_full_response` for Qwen observed non-streaming 1-6s cases | Not Duplex hot path。 |
| `error_model` | validation / timeout / provider failure / cancellation unknown taxonomy | Must be adapter-owned。 |
| `timeout_policy` | adapter-owned timeout with `timeout_ms` and final failure path | Timeout cannot mean cancellation success。 |
| `retry_policy` | bounded schema repair; provider retry unknown | Retry budget must be explicit。 |
| `output_mode` | `real`, `mock`, `fallback`, `degraded` per output | Replay-visible; no silent fallback。 |

### deployment mode

- Qwen planning target: `remote_api`, because 2026-05-11 metadata-only run used DashScope-compatible Chat Completions.
- DeepSeek planning target: `remote_api_planned`, but runtime status remains `unknown`.
- Mock/fallback modes remain available for deterministic replay and local eval.
- Adapter events and capability snapshots must not include credential-bearing endpoints or headers.

### structured JSON

- Qwen structured JSON is `observed_real` only for historical non-streaming short synthetic cases and local validation.
- Adapter must parse JSON, run schema validation, and record failure before SlowTask consumption.
- Provider "JSON mode" is not enough; the accepted unit is validated adapter output metadata.
- Invalid output never creates `ARGUMENTS_RESOLVED`, `SEMANTIC_COMMITMENT_EMITTED`, `TOOL_ARGUMENTS_READY`, `TOOL_EXECUTION_STARTED`, or `PLAYBACK_SPAN_STARTED`。

### streaming output

- Qwen and DeepSeek streaming surfaces are not validated as usable structured JSON in this lane.
- Planning label: `unknown` or `degraded` until final assembled output validates.
- Partial streaming chunks may be useful for latency telemetry, but must not update current-plan facts, tool readiness, commitment, or speech truthfulness.

### bounded repair

- Qwen bounded repair has `observed_real` evidence for schema repair convergence after two repair attempts in one historical run.
- Planning policy: bounded repair can retry parse/schema failures, but each attempt must record `adapter_request_id` or attempt linkage, `retry_count`, `retry_reason`, final validation status, and output mode.
- Repair prompts must use validation metadata, not raw sensitive provider bodies.
- Repair exhausted becomes adapter failure/degraded metadata and blocks downstream consumption.

### cancellation

- Qwen provider-confirmed cancellation is `unknown`.
- Client timeout / abort is local adapter control metadata, not provider cancellation success.
- If cancellation unsupported or unknown, adapter must not emit success-like cancellation semantics; late output is handled by current-plan/stale policy.

### retry/failure taxonomy

Planning categories:

- `parse_failed`
- `schema_validation_failed`
- `retry_budget_exhausted`
- `client_timeout`
- `client_abort_unconfirmed`
- `retryable_provider_failure`
- `non_retryable_provider_failure`
- `provider_cancellation_unconfirmed`
- `context_limit_degraded`
- `model_alias_or_endpoint_unavailable`

Only validation failure and historical client timeout have direct Qwen evidence. Provider transient failures, rate limits, alias changes, and cancellation remain gaps unless future human-approved live runs observe them.

### timeout policy

- Adapter declares timeout policy in capability matrix.
- On retryable timeout: emit `ADAPTER_REQUEST_RETRYING`-compatible metadata with `retry_count`, `retry_reason`, optional `timeout_ms`。
- On final timeout: emit `ADAPTER_REQUEST_FAILED` with `failure_reason`, `retryable=false` or budget state, `timeout_ms`, and `output_mode=degraded`。
- Timeout never advances SlowTask state by itself.

### output modes: real / mock / fallback / degraded

| Mode | Meaning for Slow LLM planning |
| --- | --- |
| `real` | Future live adapter output after provider call and local validation. Historical Qwen evidence can be cited as `observed_real` only for the observed surface. |
| `mock` | Deterministic mock/synthetic fixture output used by replay/eval; not provider proof. |
| `fallback` | Explicit fallback adapter/template output, replay-visible and capability-labeled. |
| `degraded` | Timeout, validation failure, unknown cancellation, context degradation, unsupported streaming, or reduced evidence quality. |

## 6. Adapter output validation policy

| Condition | Adapter policy | Downstream policy |
| --- | --- | --- |
| parse failure | Record parse failure; do not run schema validation on invalid JSON body except safe diagnostics. | No SlowTask review, no tool readiness, no commitment。 |
| schema validation failure | Emit `ADAPTER_OUTPUT_VALIDATION_FAILED` with `schema_name`, `failure_reasons`, `output_mode` and safe `invalid_output_ref` only if redacted/minimal. | No downstream consumption before repair success。 |
| bounded repair | Emit `ADAPTER_REQUEST_RETRYING` for retryable validation failure with count/reason. | Only final valid output may become evidence for SlowTask review。 |
| repair exhausted | Emit final degraded/failure metadata, usually `ADAPTER_REQUEST_FAILED` or validation failure plus exhausted budget. | Block current-plan advance; SlowTask may later degrade/fail through its own events。 |
| malformed JSON | Treat as parse failure; no schema-derived assumptions. | No field extraction, no partial resolved args, no tool proposal。 |
| invalid fields | Treat as schema validation failure or unsupported field category. | No silent coercion into current facts。 |
| missing fields | If output is valid and explicitly marks missing evidence, adapter may pass it as evidence. | SlowTask owns `INSUFFICIENT_EVIDENCE_FOR_ACTION`, `CLARIFICATION_REQUESTED`, `WAITING_FOR_SLOT`。 |
| conflicting fields | Preserve conflict metadata as evidence. | SlowTask owns `AMBIGUITY_DETECTED`, `AMBIGUITY_RESOLVED`, `ARGUMENTS_RESOLVED`。 |
| conflicting tool/confirmation claims | Treat provider claims as proposal evidence only. | SlowTask/Tool Executor own confirmation and authorization。 |

Adapter-owned validation stops at "valid evidence candidate". SlowTask-owned events decide whether anything can affect current plan.

## 7. Current-plan metadata contract

| Metadata | Required planning rule |
| --- | --- |
| `task_id` | Required for task-bound Slow LLM request/result metadata. Provider output may echo it, but journal append/owner boundary validates it. |
| `plan_version` | Required original request/result binding. Adapter result keeps the plan it was requested against. |
| `observed_plan_version` | Required when model evidence is interpreted around a UserPatch. It names the plan observed by patch receipt/interpretation, not provider authority. |
| `interpreted_against_plan_version` | SlowTask-owned interpretation metadata. Slow LLM cannot set final interpretation. |
| `task_event_seq` | Required for SlowTask-relevant events; assigned at journal append/accept boundary. Provider output must not be trusted as authoritative sequence. |
| `adapter_request_id` | Required adapter-owned request correlation id; used for retry/failure/validation events and late-result comparison. |
| causal refs | Required safe refs to source evidence/events; no raw provider body, no secrets, no raw user input. |
| result/current plan comparison | At arrival, compare `result.plan_version` with SlowTask current plan and terminal state before any use. |

Minimum adapter planning metadata:

```json
{
  "adapter_id": "slow_llm_qwen_remote_profile_v0",
  "adapter_type": "slow_llm",
  "adapter_request_id": "adapter_req_...",
  "task_id": "task_...",
  "plan_version": 3,
  "task_event_seq": 17,
  "causal_source_refs": ["event_ref://..."],
  "parse_status": "pass",
  "schema_status": "pass",
  "final_validation_status": "pass",
  "retry_count": 0,
  "retry_reason": null,
  "timeout_ms": null,
  "provider_cancel_confirmed": "unknown",
  "output_mode": "real",
  "raw_provider_body_stored": false,
  "may_advance_current_task": false
}
```

`may_advance_current_task=false` remains the default until SlowTask owner emits current-plan events.

## 8. stale / late result policy

### same-plan late output

If result arrives late but `result.plan_version == current_plan_version` and task is non-terminal:

- Adapter may record validated output metadata.
- SlowTask may review it as evidence through `EVIDENCE_REVIEWED` or related events.
- It still cannot directly create resolved arguments, SemanticCommitment, tool readiness, confirmation acceptance, or playback.

### old-plan late output

If `result.plan_version < current_plan_version`:

- Preserve original result binding.
- Treat as stale by default.
- Tool-like result path must use `TOOL_RESULT_MARKED_STALE -> STALE_EVIDENCE_RECORDED` before any optional adoption.
- Adapter-only result should remain stale/debug evidence until SlowTask emits an explicit adoption/rebase event or equivalent accepted metadata path.

### terminal-task late output

If task is `COMPLETED`, `CANCELLED`, or `FAILED` at arrival:

- Late output is debug/stale metadata only.
- It must not reopen terminal task, advance plan, resolve args, accept confirmation, emit commitment, or start tools.

### stale evidence record

Stale evidence record must include:

- `stale_evidence_ref`
- `source_tool_result_event_id` or adapter-result source ref
- original `result_plan_version`
- current `current_plan_version`
- `task_id`
- current-plan `plan_version`
- fresh `task_event_seq`
- stale reason

No raw provider body is required or allowed for replay.

### explicit adopt/rebase

Only SlowTask can adopt/rebase stale evidence into current-plan use. Adoption must be explicit, replayable, and bounded.

### adoption metadata required before current-plan use

Minimum required adoption metadata:

- `stale_evidence_ref`
- `source_tool_result_event_id` or equivalent adapter-result source ref
- `adopted_from_plan_version`
- current `plan_version`
- `adoption_mode=adopt_or_rebase`
- `adoption_reason`
- `adopted_scope`
- `adopted_by_event_id`
- source events included in later `SEMANTIC_COMMITMENT_EMITTED` if adopted evidence affects final facts

Without adoption, stale evidence cannot update resolved arguments, confirmation state, tool readiness, SemanticCommitment, terminal state, or spoken current facts.

## 9. Tool Executor boundary

Slow LLM may produce tool-like structure only as proposal evidence.

Allowed planning path:

```text
validated Slow LLM proposal evidence
-> optional TOOL_ARGUMENTS_PARTIAL after Tool Executor / owner binding
-> SlowTask ARGUMENTS_RESOLVED with provenance
-> TOOL_ARGUMENTS_READY
-> optional TOOL_PREVIEW_AVAILABLE
-> current-plan confirmation / authorization gates
-> TOOL_EXECUTION_STARTED
-> TOOL_UI_STATE_PATCHED / TOOL_RESULT_RECEIVED
```

Boundary rules:

- Tool proposal only: provider-native tool call or schema-level tool object is evidence, not execution.
- Partial args: missing fields may support `TOOL_ARGUMENTS_PARTIAL` after Tool Executor binds `tool_call_id`, `task_id`, `plan_version`, `task_event_seq`, `partial_arguments_ref`, `missing_fields`。
- Ready args only after SlowTask resolved arguments: `TOOL_ARGUMENTS_READY` requires current-plan `resolved_arguments_ref` and `provenance_ref`。
- No authorization ownership: Slow LLM cannot emit `TOOL_EXECUTION_AUTHORIZED` or `CONFIRMATION_ACCEPTED`。
- No execution ownership: Slow LLM cannot emit `TOOL_EXECUTION_STARTED`。
- No UI patch ownership: Slow LLM cannot emit `TOOL_UI_STATE_PATCHED` or mutate frontend/demo backend from text。
- No ToolResult ownership: Slow LLM output is not `TOOL_RESULT_RECEIVED`; Tool Executor owns normalized result refs, trust/source labels, failure/retry/cancel metadata。
- Destructive demo actions: `DEMO_DESTRUCTIVE_ACTION` requires current-plan confirmation; provider "confirmation flag" is not accepted confirmation。

## 10. SemanticCommitment / Composer / checker boundary

Slow LLM is upstream evidence only.

Canonical ownership:

- Slow LLM adapter owns provider request/result metadata, validation, retry, failure, degradation labels.
- SlowTask owns evidence review, ambiguity/insufficiency, resolved arguments, confirmation state, stale/adoption, terminal task state, and `SEMANTIC_COMMITMENT_EMITTED`。
- Composer owns `SPOKEN_PLAN_EMITTED` candidate realization only.
- Checker owns `COMMITMENT_COVERAGE_CHECK_PASSED/FAILED` and `PROGRESS_TRUTHFULNESS_CHECK_PASSED/FAILED`。
- Talker owns `PLAYBACK_SPAN_STARTED` and must reference an approved check when checks are required.

Valid commitment/speech chain:

```text
validated Slow LLM evidence
-> EVIDENCE_REVIEWED
-> optional ARGUMENTS_RESOLVED / INSUFFICIENT_EVIDENCE_FOR_ACTION / AMBIGUITY_DETECTED
-> FINALIZING
-> SEMANTIC_COMMITMENT_EMITTED
-> SPOKEN_PLAN_EMITTED
-> COMMITMENT_COVERAGE_CHECK_PASSED or PROGRESS_TRUTHFULNESS_CHECK_PASSED
-> PLAYBACK_SPAN_STARTED(approved_check_event_id=...)
```

No-Go:

- Slow LLM output as `SEMANTIC_COMMITMENT_EMITTED`。
- Slow LLM output as checker pass/fail。
- Composer self-attestation as coverage/truthfulness pass。
- Playback of SemanticCommitment facts without approved coverage check。
- Progress speech that says a tool executed, UI patched, or result arrived before Tool Executor source events exist。
- Unadopted stale evidence spoken as current fact。

## 11. webSearch / untrusted evidence boundary

Required boundary:

- webSearch result must carry `trust_level=UNTRUSTED_WEB_EVIDENCE`。
- Source type should be `EXTERNAL_READ_UNTRUSTED` for webSearch-like evidence。
- Web/search content goes into evidence-only prompt placement, never instruction placement。
- Retry prompts must not move untrusted content into instruction space。
- Web evidence cannot mutate tool policy, confirmation policy, trace/replay policy, repo policy, ADR policy, AGENTS rules, or runtime strategy。
- No raw large web content may be committed; use refs, redacted summaries, synthetic snippets, source ids, and redaction status。

Slow LLM planning implication:

- Qwen's historical synthetic injection case supports an `observed_real` boundary shape only for "model did not treat synthetic web evidence as instruction" in that run.
- It does not prove real webSearch provider readiness, source quality, freshness, or safety.
- Any future webSearch ToolResult must be Tool Executor-owned before SlowTask evidence review.

No-Go:

- No webSearch as instruction。
- No webpage/search result policy mutation。
- No web evidence directly triggering memo/alarm/flashlight/weather actions。
- No model wording that upgrades `UNTRUSTED_WEB_EVIDENCE` into `TRUSTED_DEMO_TOOL_RESULT`。

## 12. Adapter event mapping candidates

本文不新增 event names。以下都是 `main@e4311cf` contract 中已有 adapter events 的 planning mapping candidates。

| Existing event | When to use | Required boundary |
| --- | --- | --- |
| `ADAPTER_REQUEST_RETRYING` | Retryable parse/schema/provider/timeout condition within bounded retry policy. | Include `adapter_id`, `adapter_type`, `adapter_request_id`, `retry_count`, `retry_reason`, optional `timeout_ms`; no state advance。 |
| `ADAPTER_REQUEST_FAILED` | Final timeout, provider failure, retry budget exhausted, alias/endpoint unavailable, non-retryable failure. | Include failure reason, retryable flag, output mode; SlowTask may later degrade/fail through SlowTask-owned events。 |
| `ADAPTER_OUTPUT_VALIDATION_FAILED` | Provider output parsed/schema checked and failed validation. | Include schema name, failure reasons, safe invalid output ref only if redacted/minimal; block downstream consumption。 |
| `ADAPTER_OUTPUT_DEGRADED` | Missing/unsupported capability, fallback/degraded output, unknown cancellation, context limit degradation, streaming JSON unavailable. | Include degraded reason, missing capability or fallback id if relevant; replay-visible output mode。 |

No new event names are proposed. If runtime later needs an MVP-relevant event beyond the registry, it must update ADR-002 and specs first in a separate approved thread.

## 13. Replay / eval implications

Deterministic replay:

- Does not rerun Qwen, DeepSeek, Slow LLM providers, webSearch, tools, demo backend, network, clocks, or random sources.
- Consumes recorded events/refs, safe metadata, synthetic fixtures, or redacted/minimal substitutes.
- Must not generate missing provider output or infer state from absent data-plane refs.

Fixtures/eval:

- Shareable/GitHub artifacts must be synthetic/redacted/minimal.
- No raw audio, raw trace, local replay cache, secrets, unredacted real user input, unredacted sensitive ToolResult, provider request/response body, or large raw web content.
- `full_synthetic=21` in `tools/model_spikes/slow_llm_retry_eval` is planning evidence for event shape and boundary checks, not runtime proof.
- The smoke dry-run summary had 5 observations; full_synthetic has 21 case definitions. These are different case sets and must not be mixed.
- Re-eval replay is explicit opt-in only and cannot masquerade regenerated output as original runtime fact.

## 14. Evidence label table

| Label | Meaning | Slow LLM examples | Allowed planning use |
| --- | --- | --- | --- |
| `observed_real` | Directly observed in metadata-only real-provider/local run. | Qwen validated JSON, strict local validation, bounded repair, missing slot preservation, conflict preservation, tool proposal shape, synthetic web evidence boundary shape. | Supports bounded planning claim for that exact observed surface only. |
| `observed_degraded` | Directly observed but incomplete or below target behavior. | Qwen client timeout / HTTP 000 / curl exit 28; provider cancellation not confirmed. | Supports degradation/failure policy, not success capability. |
| `synthetic_eval` | Spike-local deterministic synthetic harness only. | 21-case retry/stale/cancel/tool/web/context matrix; stale adoption shape; malformed JSON; retry budget exhausted. | Supports schema/event-shape/owner-boundary planning, not real provider readiness. |
| `unknown` | No reliable observed evidence in this lane. | DeepSeek live behavior, provider-confirmed cancellation, streaming JSON usability, live late-result behavior, provider failure/rate taxonomy, current aliases/limits. | Must remain explicit gap; only fallback/degraded behavior may be planned. |
| `unsupported` | Outside Slow LLM role or forbidden by contract. | Audio input/output, TTS, semantic close, assistant directedness, tool execution, UI patch, confirmation acceptance, Checker pass, playback. | Must be No-Go reliance in adapter planning. |

## 15. MVP3 adapter planning Go / No-Go checklist

| Decision | Status | Reason |
| --- | --- | --- |
| Use `main@e4311cf` as current planning snapshot | Go | This thread's read-only `git rev-parse --short main` returned `e4311cf`。 |
| Reuse Qwen 2026-05-11/12 evidence | Conditional Go | Must keep historical snapshot and exact evidence labels。 |
| Treat Qwen as primary Slow LLM profile candidate | Conditional Go | Strongest structured JSON evidence, but still planning-only and not runtime-ready。 |
| Treat DeepSeek as real capability candidate | No-Go | Live run did not execute; key missing; runtime behavior unknown。 |
| Require provider/model alias re-pin before live work | Go | Alias/limits/endpoints are unstable and were not rechecked here。 |
| Plan structured JSON validation and bounded repair | Conditional Go | Adapter-owned validation/retry only; SlowTask review required before current-plan use。 |
| Treat client timeout as cancellation success | No-Go | Provider-confirmed cancellation is unknown。 |
| Allow partial streaming JSON to update state | No-Go | Streaming JSON usability unvalidated; final validation required。 |
| Use old-plan output in current plan before adoption | No-Go | Requires explicit SlowTask adopt/rebase metadata。 |
| Use Slow LLM tool proposal as partial args input | Conditional Go | Only after Tool Executor / owner binding and validation。 |
| Use Slow LLM output as tool authorization/execution/UI patch/result | No-Go | Tool Executor owns these events。 |
| Use Slow LLM output as SemanticCommitment | No-Go | SlowTask owns commitment。 |
| Use model self-check as coverage/truthfulness pass | No-Go | Checker owns pass/fail; playback requires approved check。 |
| Treat web evidence as instruction or policy input | No-Go | Must remain `UNTRUSTED_WEB_EVIDENCE` and evidence-only。 |
| Start MVP3 runtime adapter from this document | No-Go | This file is not integration approval。 |

## 16. Human approval gates

Human approval is required before:

- Editing `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`。
- Updating ADRs, canonical event registry, replay spec, reducer spec, or acceptance scenarios。
- Implementing runtime Slow LLM adapter or adapter registry integration。
- Connecting real DashScope, DeepSeek, webSearch, RAG, demo tool, external provider endpoint, microphone, or playback device。
- Running provider live probes, official-source re-pin with network, dependency install, or package fetch。
- Capturing, storing, or committing raw audio, generated audio, raw provider body, raw trace, local replay cache, secrets, cookies, credentials, authorization headers, real user input, unredacted tool results, or large raw web content。
- Promoting synthetic/full_synthetic dry-run counts into real provider readiness。
- Treating webSearch/RAG content as trusted instruction or policy source。
- Merging, rebasing, syncing, or otherwise changing the research branch outside docs/research-only scope。

## 17. Recommended next thread after this planning doc

Recommended next thread:

`research-only Slow LLM MVP3 adapter profile draft against main@e4311cf`

Suggested scope:

- Create a profile draft under `docs/research/profiles/` only.
- Convert this planning matrix into a concrete Qwen-first adapter capability profile.
- Include DeepSeek as `comparison_deferred_unknown_runtime` only.
- Keep `provider/model alias re-pin required` as a future human-approved live-run gate.
- Define synthetic/redacted replay/eval fixture candidates, but do not add runtime code or mainline specs.

Do not proceed directly to runtime integration. The next safe move is a profile draft / eval fixture planning thread, not provider wiring.
