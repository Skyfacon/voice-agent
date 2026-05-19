# Slow LLM Qwen MVP3 Adapter Profile Draft 2026-05-18

## 1. 当前分支 / git 状态 / observed main snapshot

本文件是 research-only 的 Qwen-only MVP3 Slow LLM adapter profile draft。

只读观察：

- 当前工作区：`/Users/a123/voice-agent-research-spikes`
- 当前分支：`research/model-spikes`
- `git status --short --branch`：`## research/model-spikes...origin/research/model-spikes [ahead 18, behind 3]`
- 观察到已有未提交 research/spike 文件和 `docs/research/model-spike-integration-ledger.md` 修改；这些不是本文新增的 protected runtime/spec/ADR/test 改动。
- `git rev-parse --short main`：`605367f`
- `git log --oneline -12 main` 顶部：
  - `605367f Merge pull request #25 from Skyfacon/mvp2/slice6-thinker-as-composer`
  - `bf0945b fix: enforce composer source provenance`
  - `6175815 feat: add MVP2 thinker-as-composer replay`
  - `e4311cf Merge pull request #24 from Skyfacon/mvp2/slice5-demo-destructive-confirmation`
  - `275437e Merge pull request #23 from Skyfacon/mvp2/slice4-demo-tools`

本文的 observed main snapshot 使用实际只读观察值：`main@605367f`。

## 2. 当前 main contract delta

本轮 profile draft 以 `main@605367f` 为 contract snapshot，不再沿用上一份 planning 中观察到的 `main@e4311cf`，也不回退到早期 stale/current-plan hardening 文档中的 `main@275437e`。

相对 `main@275437e`，当前 main 至少包含：

- MVP2 demo destructive confirmation / authorization replay slice。
- Thinker-as-Composer replay slice。
- Composer source provenance hardening。

相对上一份 Slow LLM MVP3 adapter planning 的 `main@e4311cf`，当前 main 新增了 slice6 相关 contract 变化：

- `SPOKEN_PLAN_EMITTED` 已有更明确的 source provenance、coverage check、truthfulness check、`text_ref`、`emotion`、`speaking_style`、`interruptible`、`priority`、`source`、`output_mode` 等字段约束。
- `SpokenPlanState` 已进入 state reducer 视野，replay 需要验证 spoken plan 的 source commitment / progress provenance。
- Composer 只拥有 spoken candidate realization；Checker 仍拥有 pass/fail；playback 必须依赖已批准 check。

对 Qwen Slow LLM profile 的直接影响：

- Qwen provider/model output 仍只能作为 upstream evidence，不能直接生成或拥有 `SPOKEN_PLAN_EMITTED`。
- Qwen output 可以支持 SlowTask 后续生成 `SemanticCommitment` 的 evidence，但不拥有 SlowTask event、Tool Executor event、Checker event 或 playback 决策。
- 因当前 branch 相对 remote `origin/research/model-spikes` 同时 ahead/behind，进入 runtime implementation 或主线合龙前需要另行 sync/rebase/merge 审查；本文 research-only draft 不执行 sync。

## 3. Profile status：`qwen_only_selected_target_research_profile`

Profile status：`qwen_only_selected_target_research_profile`

含义：

- Qwen3.6 Plus 是 MVP3 Slow LLM selected target。
- 本 profile 用于收口 Qwen-only adapter planning，作为后续 prompt/eval hardening 与 runtime adapter implementation plan 的输入。
- 本 profile 仍不是 runtime integration approval。
- 本 profile 不批准真实 provider 接入到 runtime，不批准新增 canonical event name，不批准跳过 SlowTask / Tool Executor / Composer / Checker 边界。

## 4. 范围和非目标

范围：

- 将上一份 Slow LLM MVP3 adapter planning 收口为 Qwen-only profile draft。
- 明确 Qwen3.6 Plus 在 MVP3 Slow LLM adapter 中应承担的 provider/model 职责。
- 明确 adapter-owned metadata、SlowTask-owned event、Tool Executor-owned event、Checker-owned event 的边界。
- 为下一步 Qwen prompt/eval hardening plan 提供 profile 输入。

非目标：

- 不实现 runtime adapter。
- 不接真实 provider。
- 不运行真实 microphone、playback device、webSearch 或 demo tools。
- 不新增 canonical event name。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 不提交 raw audio、raw trace、local replay cache、secret、真实用户输入或 large raw web content。
- 不把 dry-run / synthetic eval 结果解释为 runtime proof。

## 5. Qwen3.6 Plus selected target disposition

Disposition：

- `selected_target`：Qwen3.6 Plus。
- `provider_family`：Qwen / DashScope-compatible profile evidence。
- `historical_observed_model_alias`：`qwen3.6-plus`。
- `model_alias_repin_required_before_live_eval`：yes。
- `runtime_integration_approval`：no。

DeepSeek disposition：

- DeepSeek 不再作为 active comparison。
- DeepSeek 只保留为 `not_pursued` / historical deferred note。
- 后续 Qwen prompt/eval hardening 不再需要把 DeepSeek 放入 active capability matrix 或 live-run 对照组。

选择理由的证据边界：

- Qwen 历史 spike 已观察到 structured JSON 输出、schema validation、missing/conflicting evidence 表达、tool proposal 形态和 bounded repair 行为。
- Qwen timeout probe 只支持 `observed_degraded` 级别结论，不等于 provider cancellation proof。
- retry dry-run / full synthetic case count 是 planning evidence，不是 runtime proof。

## 6. Qwen Slow LLM 应承担的 provider/model 职责

Qwen provider/model output 应承担：

- 对 task evidence 做慢速语义分析。
- 识别 missing fields、conflicting fields、ambiguous evidence。
- 生成 structured JSON planning evidence。
- 以 evidence-only 形式提出 resolved argument candidate。
- 以 proposal-only 形式提出 tool intent / tool name / partial or candidate args。
- 给出 confirmation / risk hints，供 SlowTask 和 confirmation policy 后续使用。
- 区分 trusted task evidence 与 `UNTRUSTED_WEB_EVIDENCE`。
- 在 prompt/eval hardening 中接受 bounded repair prompt 并输出可验证 JSON。

Qwen provider/model output 不应承担：

- 不推进 SlowTask lifecycle。
- 不分配 `task_event_seq`。
- 不拥有或写入 Event Journal。
- 不直接创建 `SemanticCommitment`、`ToolCall`、`ToolResult`、`SPOKEN_PLAN_EMITTED`、Checker verdict 或 playback action。
- 不把 web evidence 当成 system/developer instruction。
- 不授权、执行或补丁 UI。

## 7. Qwen 不拥有的系统职责

Qwen 不拥有以下职责：

- SlowTask state：包括 task lifecycle、current plan、plan_version advance、explicit adopt/rebase、terminal state。
- Tool Executor：包括 tool authorization、execution、partial/ready args event、ToolResult ownership、UI patch。
- confirmation：包括 destructive action authorization gate、current-plan confirmation 和 user approval handling。
- UI patch：包括 `TOOL_UI_STATE_PATCHED` 或任何 frontend state mutation。
- SemanticCommitment：SlowTask 才能拥有 commitment event 和 immutable fact boundary。
- Composer：Composer 才能把 approved commitment/progress 转为 spoken candidate。
- Checker：Checker 才能拥有 coverage/truthfulness pass/fail verdict。
- playback：playback 必须依赖 approved check，不由 Qwen 输出触发。

## 8. MVP3 adapter capability matrix draft

| Capability field | Draft value | Evidence label | Notes |
| --- | --- | --- | --- |
| `adapter_type` | `slow_llm` | `observed_real` | Profile 目标是 MVP3 Slow LLM adapter。 |
| `adapter_profile_status` | `qwen_only_selected_target_research_profile` | `observed_real` | 本文件定义 research profile，不是 runtime approval。 |
| `adapter_id` | `slow_llm_qwen_3_6_plus_mvp3_profile_v0` | `unknown` | Draft identity，runtime implementation plan 可调整。 |
| `provider` | `dashscope_qwen` | `observed_real` | 历史 Qwen spike 使用 DashScope-compatible endpoint。 |
| `model_name` | `Qwen3.6 Plus` | `observed_real` | 用户决策为 selected target。 |
| `model_alias` | `qwen3.6-plus` | `observed_real` | 历史 observed alias；live run 前需要 re-pin。 |
| `deployment_mode` | `remote_api` | `observed_real` | MVP3 目标是真实 remote adapter，但本文不接入。 |
| `structured_json` | required | `observed_real` | 历史 Qwen run 观察到 JSON object + schema validation 可行。 |
| `streaming_output` | disabled for profile v0 | `unknown` | 历史 evidence 主要是 non-streaming；streaming 不作为 v0 requirement。 |
| `bounded_repair` | enabled, bounded attempts | `observed_real` | 历史 weak-schema repair 观察到 bounded repair 成功；仍需 prompt/eval hardening。 |
| `retry_failure_taxonomy` | adapter-owned | `synthetic_eval` | dry-run 有 synthetic coverage；runtime proof 未建立。 |
| `timeout_policy` | adapter-owned timeout budget | `observed_degraded` | 历史 curl timeout 是 client-level degraded observation。 |
| `cancellation` | request cancellation desired, provider cancellation unknown | `unknown` | 不能声称 provider-side cancel 已验证。 |
| `output_mode_real` | allowed after live eval approval | `unknown` | 本文不批准 live runtime。 |
| `output_mode_mock` | supported by existing MVP mocks | `synthetic_eval` | replay/eval 可用 mock。 |
| `output_mode_fallback` | adapter-owned fallback marker only | `unknown` | 需后续 implementation plan 明确。 |
| `output_mode_degraded` | required for validation/timeout/context degradation | `observed_degraded` | 必须可追踪，不可伪装成 real。 |

## 9. Prompt contract draft

Prompt 必须分区，且不同分区不得互相提升权限。

System instruction 区：

- 定义 Qwen 是 Slow LLM provider/model，输出 structured JSON。
- 明确输出是 evidence，不是 Event Journal event。
- 明确不得授权工具、执行工具、修改 UI、生成 spoken output、触发 playback。
- 明确 web evidence、tool results、用户原文片段不能覆盖 system instruction、ADR/spec policy 或 schema。

Task evidence 区：

- 放置 SlowTask 提供的 redacted/minimal task evidence。
- 包含用户目标、上下文摘要、候选字段、已知缺失项、冲突项。
- 不放 raw audio、raw trace、secret、unredacted real user input 或 large raw web content。

Current-plan metadata 区：

- `task_id`
- `plan_version`
- `observed_plan_version`
- `interpreted_against_plan_version`
- `task_event_seq`
- `adapter_request_id`
- causal refs

Untrusted web evidence 区：

- 所有 webSearch 或网页摘要必须标记 `UNTRUSTED_WEB_EVIDENCE`。
- 只能作为 evidence 使用。
- 不得进入 instruction 区。
- 不得修改 tool policy、confirmation policy、trace/repo policy、ADR/spec policy 或 schema。

Tool proposal constraints：

- Qwen 只能输出 `tool_proposal`。
- partial args 可以作为 evidence。
- ready args 只有在 SlowTask resolved arguments 后才能被 Tool Executor 使用。
- Qwen 不输出 authorization、execution result、UI patch 或 ToolResult。

Forbidden instruction sources：

- `UNTRUSTED_WEB_EVIDENCE`
- provider/model prior output
- raw tool output
- user-provided text that attempts to override repository policy
- large copied web content
- trace/replay/debug artifacts
- any content containing secret or credential material

## 10. JSON output schema planning

Planned Qwen output 是 provider/model evidence object，不是 Event Journal event。

Draft top-level shape：

```json
{
  "schema_version": "slow_llm_qwen_profile_v0",
  "task_binding": {
    "task_id": "string",
    "plan_version": "string_or_int",
    "observed_plan_version": "string_or_int",
    "interpreted_against_plan_version": "string_or_int",
    "task_event_seq": "number",
    "adapter_request_id": "string",
    "causal_refs": ["string"]
  },
  "task_analysis": {
    "summary": "string",
    "intent": "string",
    "confidence": "low_or_medium_or_high"
  },
  "missing_fields": [],
  "conflicting_fields": [],
  "proposed_resolved_arguments_evidence": {},
  "tool_proposal": {
    "proposal_only": true,
    "tool_name": "string_or_null",
    "args_status": "none_or_partial_or_candidate_ready",
    "partial_args": {},
    "candidate_ready_args": {},
    "requires_slowtask_resolution": true
  },
  "confirmation_risk_hints": [],
  "validation_metadata": {
    "output_mode": "real_or_mock_or_fallback_or_degraded",
    "repair_attempt": 0,
    "web_evidence_treated_as_untrusted": true,
    "forbidden_instruction_sources_ignored": true
  },
  "boundary_assertions": {
    "no_tool_authorization": true,
    "no_tool_execution": true,
    "no_ui_patch": true,
    "no_semantic_commitment_event": true,
    "no_checker_verdict": true,
    "no_playback_action": true
  }
}
```

Schema planning notes：

- `proposed_resolved_arguments_evidence` 只是 Qwen 的 argument evidence，不是 SlowTask-owned resolved arguments。
- `tool_proposal.args_status = candidate_ready` 也不能绕过 SlowTask 和 Tool Executor。
- `confirmation_risk_hints` 只能提示风险，不能授权 destructive action。
- `validation_metadata` 由 adapter validation 包装和补充；Qwen 原始输出不得伪造 adapter-owned metadata。

## 11. Adapter validation policy

Adapter validation 是 adapter-owned，不是 Qwen-owned。

Parse failure：

- JSON parse 失败时，记录 adapter validation failure evidence。
- 可进入 bounded repair，repair prompt 必须只包含最小必要错误信息和原始输出的 redacted/minimal representation。
- 不得把 parse failure 直接推进 current plan。

Schema failure：

- 必填字段缺失、类型错误、枚举错误、boundary assertion 缺失时，标记 schema validation failure。
- 可进入 bounded repair。
- 若 repair 后仍失败，输出 degraded/failure metadata，不生成 SlowTask commitment。

Malformed JSON：

- 包括 fenced text、自然语言包裹、截断 JSON、重复顶层对象。
- 处理路径同 parse failure。

Bounded repair：

- attempt count 必须有限。
- repair request 必须保留相同 `task_id`、`plan_version`、`adapter_request_id` 或明确 repair child id。
- repair 成功也只产生 provider/model evidence，仍需 SlowTask 消费。

Repair exhausted：

- 标记 `ADAPTER_OUTPUT_VALIDATION_FAILED` 或 adapter-owned failure/degraded path，具体 runtime event 只能使用 current main 已存在的 canonical event。
- 不新增 event name。
- 不推进 current plan。

Invalid / missing / conflicting fields：

- invalid fields 不得被静默纠正为事实。
- missing fields 应进入 `missing_fields` evidence。
- conflicting fields 应进入 `conflicting_fields` evidence。
- 冲突未消解前不得输出可被 Tool Executor 当作 authorized ready args 的结果。

## 12. Current-plan metadata contract

Qwen prompt input 和 adapter-wrapped output 必须携带 current-plan metadata：

- `task_id`：SlowTask-owned task identity。
- `plan_version`：当前 SlowTask plan version。
- `observed_plan_version`：adapter request 发起时观察到的 plan version。
- `interpreted_against_plan_version`：Qwen 输出声明其解释所基于的 plan version。
- `task_event_seq`：SlowTask current-plan event sequence reference；Qwen 不分配新 sequence。
- `adapter_request_id`：adapter-owned request identity。
- causal refs：指向触发 adapter request 的 prior events/evidence refs。

Result/current-plan comparison：

- Adapter 接收 Qwen output 后，必须把 `interpreted_against_plan_version` 与当前 SlowTask plan version 比较。
- 比较通过只说明 output 没有 stale-plan mismatch，不代表可以绕过 validation、confirmation、Tool Executor 或 Checker。
- 比较失败默认进入 stale/late result policy。

## 13. Stale / late result policy

Same-plan late output：

- 如果 task 仍 active，且 `interpreted_against_plan_version` 等于当前 plan version，可继续进入 validation and SlowTask review。
- 仍不能直接生成 ToolResult、UI patch、spoken output 或 playback。

Old-plan late output：

- 如果 `interpreted_against_plan_version` 旧于当前 plan version，默认记录为 stale evidence。
- 不得推进 current task。
- 不得被 Tool Executor 当作 ready args。

Terminal-task late output：

- 如果 task 已 terminal，late output 默认只能作为 stale evidence 或 ignored evidence。
- 不得 reopen task，除非后续有明确新 task / explicit rebase flow。

Explicit adopt/rebase requirements：

- 只有 SlowTask 可以 explicit adopt/rebase stale evidence。
- adopt/rebase 前必须记录旧 plan、新 plan、adoption reason、human/system approval context 和 causal refs。
- adoption metadata 完整前，stale Qwen output 不能进入 current-plan use。

## 14. Tool Executor boundary

Qwen output 对 Tool Executor 的边界：

- proposal only：Qwen 只能提出 tool proposal。
- partial args：Qwen 可以指出 partial args、missing args、conflicts。
- ready args only after SlowTask resolved arguments：即使 Qwen 产出 candidate ready args，也必须由 SlowTask 解析并生成 current-plan resolved arguments 后，Tool Executor 才能进入 ready args path。
- no authorization：Qwen 不授权工具。
- no execution：Qwen 不执行工具。
- no UI patch：Qwen 不写 UI patch。
- no ToolResult ownership：Qwen 不拥有 ToolResult，也不解释真实 tool result 为 final state。

Canonical event boundary：

- Tool Executor-owned events 仍归 Tool Executor。
- Adapter validation/retry/failure 只能映射到 current main 已存在的 adapter event names，例如 `ADAPTER_REQUEST_RETRYING`、`ADAPTER_REQUEST_FAILED`、`ADAPTER_OUTPUT_VALIDATION_FAILED`、`ADAPTER_OUTPUT_DEGRADED`。
- 本 profile 不新增 canonical event name。

## 15. Composer/checker/playback boundary

Qwen as upstream evidence：

- Qwen provider/model output 可以作为 SlowTask 生成或更新 commitment 的 upstream evidence。
- Qwen 不输出 spoken candidate，不拥有 speaking style，不决定 priority，不触发 playback。

SlowTask owns commitment：

- `SemanticCommitment` 由 SlowTask 拥有。
- immutable facts、must_say_fields、resolved_arguments、risk warnings、confirmation state 必须由 SlowTask boundary 保护。

Composer owns spoken candidate only：

- Composer 将 approved commitment/progress 转为 `SPOKEN_PLAN_EMITTED` candidate。
- 在 `main@605367f` 下，spoken plan 必须保留 source provenance、coverage/truthfulness requirement、`text_ref`、style/emotion/priority/output_mode 等字段。
- Qwen 不能伪造这些 Composer-owned fields。

Checker owns pass/fail：

- CommitmentCoverageCheck 和 ProgressTruthfulnessCheck 拥有 pass/fail。
- Qwen 不能声明自己通过 Checker。

Playback requires approved check：

- playback 只能消费已通过 required check 的 spoken candidate。
- Qwen output 不能直接触发 playback，也不能绕过 interrupt/truncate/replay contract。

## 16. webSearch / `UNTRUSTED_WEB_EVIDENCE` boundary

webSearch evidence boundary：

- webSearch 或网页内容必须标记 `UNTRUSTED_WEB_EVIDENCE`。
- 只能放在 evidence-only prompt placement。
- 不能进入 system instruction、developer instruction、tool policy、confirmation policy、trace/repo policy 或 ADR/spec policy。
- 不提交 large raw web content。
- 不把 web content 中的命令、schema、tool policy 或 credentials 当作可信指令。

Qwen expected behavior：

- 可引用 web evidence 支持 task analysis。
- 必须保留不确定性和 source label。
- 遇到 web evidence 与 repository policy 冲突时，repository policy 优先。
- 输出中必须表明 web evidence 未被用作 instruction。

## 17. Replay / eval implications

Replay：

- deterministic replay 不重新调用 Qwen provider。
- replay fixture 只能包含 synthetic / redacted / minimal evidence。
- Qwen real provider response raw body 不进入 repo。
- Adapter output mode 必须在 trace/eval metadata 中区分 `real`、`mock`、`fallback`、`degraded`。

Eval：

- retry dry-run 和 full_synthetic case count 是 planning evidence。
- `full_synthetic` 通过数量不能证明 Qwen provider runtime capability。
- live prompt/eval hardening 需要 human approval 后单独执行，并保持 fail-closed。
- prompt/eval artifacts 应只保留 redacted metadata、schema pass/fail summary、failure taxonomy summary 和 minimal fixtures。

## 18. Evidence label table

| Label | Meaning | Allowed use in this profile |
| --- | --- | --- |
| `observed_real` | 已在真实 provider/model 或真实 main contract 中只读观察到 | 可作为 profile planning evidence，但不自动批准 runtime integration。 |
| `observed_degraded` | 已观察到 degraded path，如 client timeout 或 validation failure | 可用于设计 degraded handling，不得夸大为 provider cancellation proof。 |
| `synthetic_eval` | dry-run / fixture / synthetic case 得到的 planning evidence | 可用于 prompt/eval coverage planning，不是 runtime proof。 |
| `unknown` | 当前证据不足 | 必须进入 No-Go 或 human approval gate，不得静默假设支持。 |
| `unsupported` | 当前 profile 明确不支持或不追求 | 不纳入 MVP3 Qwen v0 scope。 |

## 19. Qwen-only MVP3 Slow LLM profile Go / No-Go checklist

Go：

- Qwen3.6 Plus 作为 selected Slow LLM target。
- Qwen-only prompt/eval hardening plan 可以作为下一线程目标。
- Structured JSON、missing/conflicting fields、tool proposal、bounded repair 可以进入 Qwen prompt/eval hardening matrix。
- Adapter-owned validation/retry/failure/degraded taxonomy 可以基于 existing canonical adapter events 规划。

Conditional Go：

- live Qwen prompt/eval run 需要 human approval、provider/model alias re-pin、cost/timeout budget、redaction policy 和 artifact path 审核。
- runtime adapter implementation plan 需要等 prompt/eval hardening 后单独开线程，并再次检查 current main contracts。

No-Go：

- 不再 active compare DeepSeek。
- 不从本 profile 直接开始 runtime provider integration。
- 不由 Qwen 输出 Tool Executor-owned event、ToolResult、UI patch、SemanticCommitment、Checker verdict 或 playback action。
- 不接受 stale/old-plan Qwen output 推进 current task，除非 SlowTask explicit adopt/rebase 且 adoption metadata 完整。
- 不新增 canonical event name。
- 不提交 raw provider body、raw audio、raw trace、local replay cache、secret、真实用户输入或 large raw web content。

## 20. Human approval gates before prompt/eval live run

在任何 live Qwen prompt/eval run 前，human 必须明确批准：

- provider/model alias re-pin：确认 Qwen3.6 Plus 当前可调用 alias、endpoint profile 和 deployment mode。
- credential handling：API key / token 只通过 local environment 或 secret store，绝不写入 repo、trace、prompt artifact。
- artifact policy：只允许 redacted/minimal metadata、schema summary、failure taxonomy summary；不保存 raw provider response body。
- input policy：不使用真实用户隐私输入，不采集 raw audio，不使用 real microphone/playback。
- tool/web policy：不运行真实 demo tools，不运行真实 webSearch。
- timeout/retry budget：明确 max attempts、timeout、cost guard、fail-closed behavior。
- output directory：live eval 输出使用 local-only ignored path，或只提交 synthetic/redacted/minimal fixture。

这些 gate 通过后，也只批准 prompt/eval hardening，不自动批准 runtime adapter integration。

## 21. Recommended next thread：Qwen prompt/eval hardening plan

推荐下一线程：

`Qwen prompt/eval hardening plan`

建议目标：

- 以本 profile 为输入，设计 Qwen-only prompt sections、JSON schema、validation assertions、bounded repair prompts 和 redacted eval matrix。
- 移除 DeepSeek active comparison case，只保留 historical `not_pursued` note。
- 明确 live-run human approval gate 与 fail-closed artifact policy。
- 输出 research-only prompt/eval hardening plan，之后再进入 runtime adapter implementation plan。

仍需保持：

- 不接 runtime provider。
- 不修改 `src/voice_agent/`、`tests/`、`docs/adr/`、`docs/specs/`。
- 不新增 canonical event。
- 不把 planning/eval evidence 解释为 runtime integration approval。
