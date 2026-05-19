# Qwen Slow LLM Runtime Adapter Implementation Plan 2026-05-18

## 1. 当前分支 / git 状态 / observed main snapshot

本文是 research-to-runtime handoff 的 Qwen Slow LLM runtime adapter implementation plan。它只规划后续实现，不实现 runtime adapter，不连接真实 Qwen provider，不运行 live eval，不修改 runtime/spec/ADR/test。

只读观察：

- 工作区：`/Users/a123/voice-agent-research-spikes`
- 当前分支：`research/model-spikes`
- `git status --short --branch`：`## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]`
- 工作区已有既存 research lane 修改和未跟踪文件，包括 `M docs/research/model-spike-integration-ledger.md`、多个 `docs/research/*` / `docs/research/spikes/*` / `docs/research/profiles/` artifacts，以及未跟踪 `tools/`。
- 本线程只新增本文，不归因、不清理、不回退既存 research artifacts。
- `git rev-parse --short main`：`605367f`
- `git log --oneline -12 main` 顶部为：
  - `605367f Merge pull request #25 from Skyfacon/mvp2/slice6-thinker-as-composer`
  - `bf0945b fix: enforce composer source provenance`
  - `6175815 feat: add MVP2 thinker-as-composer replay`
  - `e4311cf Merge pull request #24 from Skyfacon/mvp2/slice5-demo-destructive-confirmation`
  - `fb275c0 fix: tighten destructive confirmation replay gates`
  - `580a4c4 feat: add MVP2 destructive demo confirmations`
  - `275437e Merge pull request #23 from Skyfacon/mvp2/slice4-demo-tools`
  - `954dd07 feat: add MVP2 demo tools`
  - `ced2077 Merge pull request #22 from Skyfacon/mvp2/slice3-tool-ui-state-patch`
  - `0d2870f fix: harden MVP2 UI patch replay validation`
  - `6f6e549 feat: add MVP2 tool UI state replay`
  - `f325483 Merge pull request #21 from Skyfacon/mvp2/slice2-demo-tool-executor-skeleton`

Observed main snapshot：`main@605367f`。

## 2. 当前 main contract delta

本文读取的 current main contract 是 `main@605367f`。较早 research 文档中的 `main@ced2077`、`main@275437e`、`main@e4311cf` 和 historical `main@61e6afc` 都只作为历史观察或输入背景。

相对 `main@275437e`：

- main 已包含 MVP2 demo destructive confirmation replay gate。`DEMO_DESTRUCTIVE_ACTION` 必须经 current-plan `CONFIRMATION_ACCEPTED` 才能进入 `TOOL_EXECUTION_AUTHORIZED` / `TOOL_EXECUTION_STARTED`。
- provider/model output 中的 "confirmed"、"safe"、`confirmation_required=false` 或类似字段不能成为确认或授权事实。

相对 `main@e4311cf`：

- main 已包含 Thinker-as-Composer replay slice 和 Composer source provenance hardening。
- `SPOKEN_PLAN_EMITTED` 的 current registry required fields 包括 `source_events`、`source_progress_event_ids`、`coverage_check_required`、`truthfulness_check_required`、`text_ref`、`emotion`、`speaking_style`、`interruptible`、`priority`、`source`、`output_mode`。
- `SpokenPlanState` reducer 要求 source commitment / progress provenance；Composer output 只是 unchecked draft。

对 Qwen Slow LLM runtime adapter implementation planning 的 delta：

- Qwen provider/model output 只能是 upstream evidence object，不能直接成为 Event Journal event。
- Adapter-owned metadata 覆盖 provider request/result、parse/schema validation、bounded repair、retry/failure/degraded labels。
- SlowTask-owned events 覆盖 evidence review、missing/conflict resolution、plan_version advance、stale/adopt/rebase、confirmation、SemanticCommitment 和 terminal state。
- Tool Executor-owned events 覆盖 tool manifest、partial/ready args、authorization、execution、progress、UI patch、ToolResult、failure/retry/cancel。
- Composer/Checker/playback-owned events 覆盖 `SPOKEN_PLAN_EMITTED`、coverage/truthfulness pass/fail 和 `PLAYBACK_SPAN_STARTED`。
- Deterministic replay 不得重跑 Qwen provider、真实 tools、webSearch、网络、时钟或随机数。

`main:docs/implementation/mvp2-backlog.md` 仍保留部分历史开工语言；本文以 `main@605367f` 的 specs、acceptance scenarios 和 observed commit history 解释 current contract。

## 3. Plan status：`qwen_runtime_adapter_implementation_plan_research_handoff`

Plan status：`qwen_runtime_adapter_implementation_plan_research_handoff`

含义：

- Qwen3.6 Plus 是 selected Slow LLM target。
- 本文把已完成的 Qwen-only prompt/eval hardening plan 转成后续 runtime adapter implementation 的 handoff plan。
- 本文仍不是 runtime implementation approval。
- 本文仍不是 live provider approval。
- 本文不授权真实 DashScope/Qwen call，不授权 live eval，不授权 provider/model alias 当日 re-pin。
- 本文不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 本文不新增 canonical event name。

## 4. 范围和非目标

范围：

- 规划后续 Qwen Slow LLM runtime adapter 的 module boundary、file/module layout、metadata ownership、failure taxonomy、bounded repair、timeout/retry/cancellation、stale result handling、tool proposal normalization、web evidence boundary 和隐私 artifact policy。
- 把 research prompt/schema hardening 输入转成 implementation-ready checklist。
- 定义后续实现线程开始前的 human approval gates 和 Go / No-Go checklist。

非目标：

- 本文不是 runtime implementation approval。
- 本文不是 live provider approval。
- 不实现 adapter。
- 不接真实 Qwen provider。
- 不运行 live Qwen eval。
- 不运行真实 webSearch、demo tools、麦克风或播放设备。
- 不新增 runtime 行为承诺。
- 不新增 canonical event name。
- 不要求保存 raw provider body。
- 不要求使用真实用户输入。
- 不提交 raw provider body、raw audio、raw trace、local replay cache、secret、真实用户输入或 large raw web content。

## 5. Qwen3.6 Plus selected target recap

Qwen3.6 Plus 是 selected Slow LLM target，但本文仍不是 runtime implementation approval，也不是 live provider approval。

Selected target recap：

- `selected_target`：Qwen3.6 Plus。
- historical observed model alias：`qwen3.6-plus`。
- historical provider surface：DashScope-compatible Chat Completions。
- historical successful surface：non-streaming JSON object mode、local schema validation、missing slot preservation、conflict preservation、tool proposal shape、bounded repair。
- historical degraded surface：client timeout observed；provider-confirmed cancellation unknown。
- future live work：任何 live run 前必须 human-approved provider/model alias re-pin。

DeepSeek 只作为 `not_pursued` historical note：

- DeepSeek 不再 active compare。
- DeepSeek 不进入 active capability matrix。
- DeepSeek 不作为 live-run 对照组。
- DeepSeek 旧 note 不能支撑 Qwen runtime capability claim。

## 6. Adapter module boundary draft

### adapter identity / capability matrix

Draft identity：

- `adapter_id`：`slow_llm_qwen_3_6_plus_runtime_v0`，后续实现线程可按 registry 命名规范调整。
- `adapter_type`：`slow_llm`。
- `provider`：`dashscope_qwen` 或等价 credential-free provider id。
- `model_name`：`Qwen3.6 Plus`。
- `model_alias`：live run 前重新 re-pin；不得把 historical `qwen3.6-plus` 当作未来事实。
- `deployment_mode`：`remote_api` for future approved implementation；本线程不启用。
- `output_mode`：每个 output 明确 `real|mock|fallback|degraded`。

Capability matrix draft 必须覆盖：

- `supports_structured_json=true` only after future implementation validates it；planning 中保持 draft。
- `supports_tool_calling=true` 只能表示 provider/model 可输出 tool-call-like intent；执行权仍属于 Tool Executor。
- `supports_streaming_output=false` for v0 unless future approved thread proves assembled streaming JSON usable。
- `supports_cancellation=unknown` until provider-confirmed cancellation is proven；不得伪造 success。
- `timeout_policy`、`retry_policy`、`error_model` 必须为 adapter-owned metadata/ref。

### request builder

Request builder 后续实现应只负责构造 provider request，不拥有 SlowTask state。

Draft responsibilities：

- 输入 redacted/minimal/synthetic-safe task evidence refs。
- 输入 current-plan request binding：`task_id`、`plan_version`、`observed_plan_version`、`interpreted_against_plan_version`、`task_event_seq`、`adapter_request_id`、causal refs。
- 放置 `UNTRUSTED_WEB_EVIDENCE` 到 evidence-only section。
- 注入 JSON-only、boundary assertions、tool proposal-only、no event ownership 的 system prompt。
- 不包含 secrets、authorization headers、cookies、raw audio、raw trace、local replay cache、raw provider body、unredacted real user input 或 large raw web content。

### response parser

Response parser 后续实现应只把 provider/model output 尝试解析成单个 JSON object。

Draft rules：

- fenced JSON、natural-language wrapper、multiple top-level objects、truncated JSON、invalid encoding 都是 parse failure。
- parse failure 后不得做 schema-derived field extraction。
- parser 不推断 missing fields，不修正 enums，不接受 provider prose 作为 structured output。

### schema validator

Schema validator 后续实现应验证 Qwen output evidence schema。

Draft rules：

- required top-level fields、task binding、validation metadata、boundary assertions 必须存在。
- invalid enum、missing required field、wrong type、forbidden ownership claim 都是 schema failure。
- `boundary_assertions` 缺失或任一 false 均 fail。
- provider/model output 中任何等价于 event ownership 的字段都 fail closed。

### bounded repair controller

Bounded repair controller 后续实现应只处理 parse/schema repair，不处理 business state。

Draft policy：

- max repair attempts draft：2。
- repair prompt 输入只包括 schema/version、minimal validation error list、redacted/minimal invalid-output summary、原始 request metadata 和必要 evidence refs。
- 不输入 raw provider body、raw request body with secrets、raw audio、raw trace、unredacted real user input 或 large raw web content。
- repair 成功后仍只产生 validated evidence candidate，仍需 SlowTask review。
- repair exhausted 走 adapter-owned validation failure/degraded/failure metadata，不推进 current plan。

### retry/timeout/cancellation wrapper

Wrapper 后续实现应包住 provider call 和 bounded repair。

Draft policy：

- retryable parse/schema failure 可走 bounded repair。
- retryable provider failure / timeout 需要 explicit retry budget；当前 provider failure taxonomy 仍是 unknown gap。
- final timeout 或 final provider failure 映射到 existing adapter failure/degraded events 的 metadata，不新建 event。
- cancellation unsupported/unknown 时，不得声明 provider cancellation success；late output 按 stale/current-plan comparator 处理。

### output metadata wrapper

Output metadata wrapper 后续实现应把 provider/model output 和 adapter validation result 分离。

Draft wrapper fields：

- `adapter_id`
- `adapter_type=slow_llm`
- `adapter_request_id`
- `provider`
- `model_name`
- `model_alias_observed_at_request`
- `output_mode`
- `parse_status`
- `schema_status`
- `final_validation_status`
- `retry_count`
- `retry_reason`
- `timeout_ms`
- `provider_cancel_confirmed=true|false|unknown`
- `raw_provider_body_stored=false`
- `may_advance_current_task=false`

### stale/current-plan comparator

Comparator 后续实现应比较 adapter result binding 与 SlowTask current state。

Draft rules：

- 比较 `task_id`、request `plan_version`、provider echo、`interpreted_against_plan_version`、arrival-time current plan 和 terminal state。
- same-plan non-terminal result 也只是 reviewable evidence；adapter layer 仍 `may_advance_current_task=false`。
- old-plan result 默认 stale evidence，必须等 SlowTask explicit adopt/rebase。
- terminal-task late result 只允许 debug/stale/ignored metadata，不 reopen task。

## 7. Prompt/schema assets needed before implementation

后续实现前需要冻结或确认的 prompt/schema assets：

- Qwen Slow LLM system prompt text，含 evidence-only、JSON-only、no event ownership、tool proposal-only、web evidence untrusted、no Composer/Checker/playback ownership。
- Task evidence prompt template，使用 redacted/minimal/synthetic refs。
- Current-plan metadata prompt template，要求 echo request binding，但 echo 不是 authority。
- `UNTRUSTED_WEB_EVIDENCE` prompt template，保持 evidence-only placement。
- Qwen output JSON schema file draft，覆盖 task binding、task analysis、missing/conflicting fields、proposed argument evidence、tool proposal、confirmation/risk hints、validation metadata、boundary assertions。
- Bounded repair prompt template，禁止 raw provider body 和 untrusted evidence instruction promotion。
- Adapter validation assertion list，覆盖 parse/schema/enum/required/ownership/stale mismatch。

这些 assets 应在后续 approved implementation thread 中作为 implementation input；本线程不创建 schema file、不改 specs、不改 runtime。

## 8. Adapter-owned metadata vs SlowTask-owned events

Adapter-owned metadata：

- provider request/result correlation。
- parse status。
- schema validation status。
- bounded repair attempts。
- retry/failure/degraded labels。
- timeout and cancellation capability metadata。
- output mode：`real|mock|fallback|degraded`。
- provider/model alias observed at request time。
- `raw_provider_body_stored=false` artifact assertion。
- task binding echo comparison result。

SlowTask-owned events：

- `EVIDENCE_REVIEWED`
- `AMBIGUITY_DETECTED`
- `AMBIGUITY_RESOLVED`
- `INSUFFICIENT_EVIDENCE_FOR_ACTION`
- `CLARIFICATION_REQUESTED`
- `ARGUMENTS_RESOLVED`
- `ARGUMENT_RESOLUTION_PROVENANCE`
- `PLAN_VERSION_ADVANCED`
- `TASK_REPLANNED`
- `CONFIRMATION_REQUIRED`
- `CONFIRMATION_ACCEPTED`
- `CONFIRMATION_REJECTED`
- `SLOWTASK_DEGRADED`
- `SLOWTASK_FAILED`
- `SEMANTIC_COMMITMENT_EMITTED`
- stale/adopt/rebase chain：`TOOL_RESULT_MARKED_STALE`、`STALE_EVIDENCE_RECORDED`、`STALE_EVIDENCE_ADOPTED`

Boundary rule：

- Qwen provider/model output may support SlowTask evidence review。
- Qwen provider/model output cannot emit, allocate, advance, adopt, cancel, confirm, complete, fail, or reopen SlowTask events。
- Adapter validation success means "valid evidence candidate"，not current-plan fact。

## 9. Adapter-owned metadata vs Tool Executor-owned events

Adapter-owned metadata：

- `tool_proposal` parse/schema validated as proposal evidence。
- tool intent / args status normalized into evidence fields。
- confirmation/risk hints kept as hints。
- provider-native tool-like output stripped or normalized into proposal-only structure。

Tool Executor-owned events：

- `TOOL_MANIFEST_LOADED`
- `TOOL_CALL_STARTED`
- `TOOL_ARGUMENTS_PARTIAL`
- `TOOL_ARGUMENTS_READY`
- `TOOL_PREVIEW_AVAILABLE`
- `TOOL_EXECUTION_AUTHORIZED`
- `TOOL_EXECUTION_STARTED`
- `TOOL_PROGRESS_UPDATED`
- `TOOL_UI_STATE_PATCHED`
- `TOOL_RESULT_RECEIVED`
- `TOOL_EXECUTION_FAILED`
- `TOOL_CALL_RETRYING`
- `TOOL_EXECUTION_CANCEL_REQUESTED`
- `TOOL_EXECUTION_CANCELLED`
- `TOOL_EXECUTION_BLOCKED_INSUFFICIENT_ARGUMENTS`

Boundary rule：

- Qwen can propose a tool and candidate args as evidence。
- `candidate_ready_args` still is not `TOOL_ARGUMENTS_READY`。
- Tool Executor owns manifest validation、current-plan binding、idempotency、authorization、execution、UI patch、normalized result、tool failure/retry/cancel。
- `DEMO_DESTRUCTIVE_ACTION` requires current-plan confirmation；Qwen "safe/confirmed" wording is not confirmation。

## 10. Adapter-owned metadata vs Composer/Checker/playback events

Adapter-owned metadata：

- validated evidence candidate that may later inform SlowTask commitment。
- no spoken text ownership。
- no checker verdict ownership。
- no playback ownership。

Composer/Checker/playback-owned events：

- Composer owns `SPOKEN_PLAN_EMITTED` candidate only。
- Coverage Checker owns `COMMITMENT_COVERAGE_CHECK_PASSED` / `COMMITMENT_COVERAGE_CHECK_FAILED`。
- ProgressTruthfulnessCheck owns `PROGRESS_TRUTHFULNESS_CHECK_PASSED` / `PROGRESS_TRUTHFULNESS_CHECK_FAILED`。
- Talker/playback owns `PLAYBACK_SPAN_STARTED` and must reference `approved_check_event_id` when checks are required。

Boundary rule：

- Qwen provider/model output cannot emit spoken plan、coverage pass/fail、truthfulness pass/fail、playback start、audio refs、tts stream refs 或 approved check ids。
- Qwen cannot rewrite `immutable_facts`、`must_say_fields`、resolved arguments、tool status、risk warnings、confirmation state、stale/adopted metadata。

## 11. Proposed runtime file/module layout draft

本文不修改文件，只规划后续 approved implementation thread 的 possible layout。

Proposed layout draft：

- `src/voice_agent/adapters/slow_llm/`
  - `__init__.py`
  - `qwen_adapter.py`：adapter orchestration shell。
  - `qwen_capabilities.py`：capability matrix builder。
  - `qwen_prompts.py`：prompt asset assembly from approved templates。
  - `qwen_request.py`：request builder and metadata binding。
  - `qwen_response.py`：parser and normalized evidence object。
  - `qwen_schema.py` or `schemas/slow_llm_qwen_output.schema.json`：local output schema validation。
  - `qwen_repair.py`：bounded repair controller。
  - `qwen_retry.py`：retry/timeout/cancellation wrapper。
  - `qwen_metadata.py`：adapter-owned output metadata wrapper。
  - `qwen_staleness.py`：arrival-time stale/current-plan comparator。

Possible tests in a later thread：

- `tests/adapters/test_slow_llm_qwen_request_builder.py`
- `tests/adapters/test_slow_llm_qwen_response_parser.py`
- `tests/adapters/test_slow_llm_qwen_schema_validation.py`
- `tests/adapters/test_slow_llm_qwen_bounded_repair.py`
- `tests/adapters/test_slow_llm_qwen_timeout_retry_cancel.py`
- `tests/adapters/test_slow_llm_qwen_stale_metadata.py`

This layout is a draft only；it does not authorize file creation or edits in this thread。

## 12. Required tests/replay/eval plan draft

后续 implementation thread 才能新增测试；本线程不新增测试。

Draft test/replay/eval plan：

- Unit tests for request builder：verifies prompt sections, redaction boundaries, no secrets, current-plan metadata included, web evidence evidence-only。
- Unit tests for parser：single JSON object only；malformed/fenced/multiple object cases fail。
- Unit tests for schema validator：required fields, enums, boundary assertions, forbidden ownership claims。
- Unit tests for bounded repair：success within max attempts, exhausted failure, repair prompt excludes raw provider body。
- Unit tests for timeout/retry/cancellation wrapper：timeout final failure, retry metadata, cancellation unknown unsupported path。
- Unit tests for stale/current-plan comparator：same-plan, old-plan, terminal-late, metadata mismatch。
- Tool proposal normalization tests：provider-native/tool-like output becomes proposal-only evidence。
- Replay fixture tests：synthetic/redacted/minimal only；no real provider call；deterministic replay does not rerun Qwen。
- Eval cases can reuse the existing spike taxonomy from `tools/model_spikes/slow_llm_retry_eval/` as planning reference only；do not import spike harness into runtime。

All Python tests in a later implementation thread should use `./scripts/test` per repo rule, unless human explicitly approves another path。

## 13. Failure taxonomy

Failure categories for future adapter-owned handling:

- parse failure：output is not one JSON object, fenced, wrapped, truncated, duplicated, or invalid encoding。
- schema failure：JSON parse succeeds but required schema/type/boundary validation fails。
- malformed JSON：parse failure subtype；no schema-derived extraction。
- invalid enum：unexpected enum value for sufficiency/confidence/args_status/risk/output mode/etc。
- missing required field：missing task binding, validation metadata, boundary assertions, required analysis fields。
- forbidden ownership claim：provider/model claims tool authorization/execution/UI patch/ToolResult/SemanticCommitment/SpokenPlan/checker/playback/terminal state/plan advance。
- stale metadata mismatch：task binding echo differs from adapter request, interpreted plan mismatches arrival current plan, or terminal state at arrival。
- timeout：client/adapter timeout; does not prove provider cancellation。
- provider cancellation unknown：client abort or unsupported cancellation cannot be recorded as provider success。
- repair exhausted：bounded repair attempts consumed without valid evidence candidate。

No taxonomy item creates new canonical event names。Future implementation must map only to existing adapter events or SlowTask/Tool Executor/Checker-owned events through their owners。

## 14. Bounded repair implementation plan

Draft repair flow for later implementation:

1. Parse provider output。
2. If parse succeeds, run schema validation。
3. If parse/schema failure is repairable and safe, create repair request with:
   - original request metadata
   - schema name/version
   - minimal validation error list
   - redacted/minimal invalid-output summary
   - same evidence refs
   - same `UNTRUSTED_WEB_EVIDENCE` section only as evidence, if needed
4. Run at most 2 repair attempts。
5. Validate final repaired output from scratch。
6. On success, wrap as validated evidence candidate with repair metadata。
7. On exhausted budget, emit adapter-owned failure/degraded metadata and block downstream consumption。

Unsafe repair should fail closed：

- forbidden ownership claim
- policy override attempt
- secret-bearing output
- web evidence moved into instruction-like fields
- raw provider body required for repair

## 15. Timeout / retry / cancellation implementation plan

Draft timeout policy：

- Adapter declares timeout budget in capability matrix。
- Timeout produces adapter-owned degraded/failure metadata with `timeout_ms`。
- Timeout does not advance SlowTask state and does not prove provider cancellation。

Draft retry policy：

- Bounded repair covers parse/schema retry。
- Provider retry taxonomy remains unknown until approved live work observes rate-limit/transient errors。
- Retry budget must be explicit and replay-visible。
- Final failure must be adapter-owned and must not silently fallback as real output。

Draft cancellation policy：

- `supports_cancellation=unknown` until provider-confirmed cancellation is proven。
- If SlowTask plan advances or task cancels while request is in flight, adapter may try local abort only if future implementation supports it。
- Local abort means `provider_cancel_confirmed=unknown` unless provider gives explicit confirmation。
- Any late output after abort/timeout/plan advance goes through stale/current-plan comparator。

## 16. Stale / late result implementation plan

Draft arrival-time checks：

- Verify `adapter_request_id` matches known request。
- Verify provider echo of `task_id` / `plan_version` / `observed_plan_version` / `interpreted_against_plan_version` / `task_event_seq` exactly matches request metadata。
- Read current SlowTask plan/version/terminal summary through approved owner boundary in future implementation。
- Compare result plan against current plan at arrival。

Cases：

- same-plan non-terminal：validated evidence may enter SlowTask review；adapter still cannot advance current task。
- old-plan late：record stale/debug metadata; SlowTask owner must decide stale record/adopt/rebase path。
- terminal-task late：ignore or keep debug/stale metadata; no reopen。
- metadata mismatch：fail validation or mark stale/mismatch; no downstream use。

No-Go：

- no current-plan advance from adapter output。
- no stale evidence reuse before `STALE_EVIDENCE_ADOPTED` or equivalent accepted SlowTask-owned path。
- no terminal revival。

## 17. Tool proposal normalization plan

Draft normalization:

- Accept only a schema-defined `tool_proposal` object。
- Normalize provider-native/tool-like fields into proposal-only evidence。
- Preserve `args_status=none|partial|candidate_ready|blocked`。
- Preserve missing args, conflicting args, source evidence refs, risk hints。
- Strip or fail any field that claims execution, authorization, ToolResult, UI patch, idempotency key, confirmation acceptance, or external side effect。

Downstream boundary:

- `partial` may later support `TOOL_ARGUMENTS_PARTIAL` only after Tool Executor/owner binding。
- `candidate_ready` may later support `TOOL_ARGUMENTS_READY` only after SlowTask `ARGUMENTS_RESOLVED` and Tool Executor validation。
- Qwen output never allocates `tool_call_id` as authority, `idempotency_key`, `authorization_event_id`, `ui_patch_id`, `patch_ref`, or `result_ref`。

## 18. webSearch / `UNTRUSTED_WEB_EVIDENCE` boundary plan

Draft boundary:

- webSearch evidence must be labeled `UNTRUSTED_WEB_EVIDENCE`。
- Source type should be `EXTERNAL_READ_UNTRUSTED` when represented as ToolResult evidence。
- web content goes to evidence-only prompt placement。
- web content cannot modify schema, tool policy, confirmation policy, trace/replay policy, repo policy, ADR/spec policy, AGENTS rules, adapter behavior, or runtime strategy。
- retry/repair prompts must preserve untrusted label and must not move snippets into instruction space。

Artifact policy:

- no real webSearch in this thread。
- no large raw web content。
- future fixtures must use synthetic/redacted/minimal source refs, short summaries, redaction status, and injection-risk metadata。

## 19. Privacy / artifact / redaction plan

Future implementation must preserve these artifact rules:

- Do not store raw provider body by default。
- Do not commit provider request/response body。
- Do not store API keys、tokens、cookies、credentials、authorization headers、signed URLs or session secrets。
- Do not use real user input in tests/eval fixtures。
- Do not store raw audio, generated audio, raw trace, local replay cache, unredacted tool result, or large raw web content。
- Shareable/GitHub fixtures must be synthetic/redacted/minimal。
- Adapter events must contain credential-free endpoint refs only。
- Replay must not re-run provider, tools, webSearch, network, clock, random, microphone, or playback device。
- `raw_provider_body_stored=false` should be asserted in adapter-owned metadata when applicable。

Before creating trace/cache/audio/replay artifact directories in any later thread, `.gitignore` or equivalent exclusion must already cover them。

## 20. Capability matrix draft with `real` / `mock` / `fallback` / `degraded`

| Capability field | Draft value | Evidence / mode note |
| --- | --- | --- |
| `adapter_type` | `slow_llm` | contract-required identity。 |
| `adapter_id` | `slow_llm_qwen_3_6_plus_runtime_v0` | draft only；not created in this thread。 |
| `provider` | `dashscope_qwen` | credential-free provider id only。 |
| `model_name` | `Qwen3.6 Plus` | selected target；alias re-pin required before live eval。 |
| `deployment_mode` | `remote_api` | future approved implementation only。 |
| `supports_structured_json` | draft true for target | historical observed surface；future implementation must validate。 |
| `supports_streaming_output` | draft false for v0 | streaming JSON usability remains unknown。 |
| `supports_tool_calling` | proposal-only | does not authorize execution。 |
| `supports_cancellation` | unknown/degraded | provider-confirmed cancellation not proven。 |
| `timeout_policy` | adapter-owned | timeout does not imply cancellation success。 |
| `retry_policy` | bounded repair + explicit provider retry budget | provider transient taxonomy unknown。 |
| `output_mode=real` | future live validated output only | requires human-approved implementation and live path。 |
| `output_mode=mock` | deterministic mock/synthetic fixture output | replay/eval only；not provider proof。 |
| `output_mode=fallback` | explicit fallback output | replay-visible；must not masquerade as real。 |
| `output_mode=degraded` | timeout/validation/cancellation/context/unsupported capability | must be explicit and replay-visible。 |

## 21. Human approval gates before any actual runtime implementation

Human must explicitly approve before any later thread:

- edits `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- creates runtime Qwen adapter files。
- registers adapter capability snapshot in runtime。
- adds or updates tests/replay fixtures。
- changes accepted ADRs or canonical specs。
- adds any MVP-relevant event name。
- changes Tool Executor / SlowTask / Composer / Checker boundaries。
- installs dependencies or fetches packages。
- syncs/rebases/merges branch contents beyond the approved scope。

This approval is separate from live provider approval。

## 22. Human approval gates before any live Qwen eval

Human must explicitly approve before live Qwen eval:

- provider/model alias re-pin on the run day。
- credential handling path：environment/secret store only, never repo/trace/prompt artifacts。
- cost and timeout budget。
- max retry/repair attempts。
- artifact path and retention policy。
- no raw provider body storage policy。
- input policy：synthetic/redacted/minimal only；no real user private input。
- no raw audio, no microphone, no playback device。
- no real webSearch or demo tool execution。
- output summary policy：schema pass/fail, failure taxonomy, redacted/minimal metadata only。

Live eval approval would approve only live prompt/eval work, not automatic runtime integration。

## 23. Go / No-Go checklist for starting implementation in a later thread

Go：

- current main contract rechecked in that later thread。
- human explicitly approves runtime implementation scope。
- Qwen prompt/schema assets are approved or included as implementation inputs。
- no new canonical event name is needed。
- adapter output remains evidence-only。
- capability matrix distinguishes `real|mock|fallback|degraded`。
- bounded repair, timeout, retry, cancellation unknown, stale comparison, privacy policy are included in the implementation plan。

Conditional Go：

- live provider support only after separate live Qwen eval approval and alias re-pin。
- provider retry/error taxonomy only after observed or approved provider-doc/live evidence。
- streaming JSON only after separately proven assembled structured output validity。

No-Go：

- start runtime implementation from this document without human approval。
- connect real Qwen provider without live approval。
- treat dry-run/full_synthetic counts as runtime proof。
- use DeepSeek as active comparison。
- accept provider/model output as SlowTask event。
- accept provider/model output as Tool Executor authorization/execution/UI patch/ToolResult。
- accept provider/model output as Composer/Checker/playback ownership。
- use old-plan output in current plan before SlowTask adopt/rebase。
- treat timeout/client abort as provider cancellation success。
- treat webSearch content as instruction。
- commit raw provider body、raw audio、raw trace、local replay cache、secret、real user input、large raw web content。

## 24. Recommended next thread：actual runtime adapter implementation, only after human approval

Recommended next thread：

`Qwen Slow LLM actual runtime adapter implementation`

Only start it after human approval for runtime implementation scope。

Suggested scope for that future thread：

- Re-check `git status --short --branch` and current `main` commit。
- Re-read current `main:docs/specs/model-adapter-capabilities.md`、`event-registry.md`、`replay-spec.md`、`state-reducers.md`、MVP acceptance scenarios。
- Implement Qwen Slow LLM adapter behind adapter boundary only。
- Add focused tests through `./scripts/test`。
- Keep live provider calls disabled unless separately approved。
- Preserve event ownership: Adapter validates/wraps evidence；SlowTask owns facts；Tool Executor owns tools；Composer/Checker/playback own speech gates。

This document should be treated as a handoff plan, not an implementation approval or live provider approval。
