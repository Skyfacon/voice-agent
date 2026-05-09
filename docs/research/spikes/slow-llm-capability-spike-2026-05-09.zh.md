# Slow LLM 能力探针

## Status

evidence_report

## Date

2026-05-09

## Scope

本文评估 Slow LLM 候选在 SlowTask planning、ReAct-style reasoning、structured output、schema retry、long context 与 tool-call normalization 上的能力。本文刻意不以 speech capability 为重点。

## Architecture Role

Slow LLM 支持 SlowTask planning、evidence synthesis、argument resolution、confirmation proposals 与 SemanticCommitment drafting。它运行在 model adapter 后，输出必须在适用时绑定 `task_id`、`plan_version` 与 `task_event_seq`。它可以提出 tool call，但 Tool Executor 仍是唯一 execution 与 authorization path。

## ADR Constraints

- ADR-008：SlowTask 处理 ASR/Thinker conflicts，并通过受控事件发出 semantic commitments。
- ADR-009：Composer 不能改写 SlowTask facts；Slow LLM planning facts 在进入 speech 前需要 coverage 与 truthfulness checks。
- ADR-011：每个 provider/model 都必须声明 capability matrix、output mode、fallback/degraded behavior 与 retry semantics。
- ADR-014：webSearch/RAG evidence 是 untrusted evidence，不能进入 instruction space。
- ADR-016：旧 plan results 不能推进 current task，除非显式 adopt/rebase。

## Candidate Shortlist

- Qwen3 Instruct / Thinking family：structured planning、long context 与 tool-use experiments 的 primary open/open-weight and DashScope-aligned candidate。
- DeepSeek current API models：强 API candidate；官方 API docs 提供 OpenAI-compatible surface、long context、JSON output 与 tool-call support。
- GLM-4.5 family：API structured planning 与中文 reasoning 候选；exact schema/tool/cancellation details 需要 endpoint-level verification。
- Kimi K2：long-context/tool reasoning 候选；current structured JSON 与 deployment details 需要从 official docs/model cards 再验证。
- DashScope/Bailian Qwen via OpenAI-compatible Chat Completions or native DashScope API：Qwen models 的 first integration path，操作上较有吸引力。

## Official Sources Checked

- Qwen3 GitHub: https://github.com/QwenLM/Qwen3
- Aliyun Qwen API reference: https://help.aliyun.com/zh/model-studio/qwen-api-reference/
- DeepSeek API pricing/model page: https://api-docs.deepseek.com/quick_start/pricing
- GLM-4.5 official docs: https://docs.bigmodel.cn/cn/guide/models/text/glm-4.5
- Kimi K2 model card entry point: https://huggingface.co/moonshotai/Kimi-K2-Instruct
- Moonshot platform docs entry point: https://platform.moonshot.ai/docs

## Capability Matrix Assessment

| field | Qwen3 via DashScope/self-host | DeepSeek API current | GLM-4.5 | Kimi K2 | local small fallback |
| --- | --- | --- | --- | --- | --- |
| adapter_type | slow_llm | slow_llm | slow_llm | slow_llm | slow_llm |
| provider | Qwen / Alibaba | DeepSeek | Zhipu / BigModel | Moonshot | project_local |
| model_name | Qwen3-235B-A22B_or_30B-A3B | deepseek-v4-flash_or_v4-pro | GLM-4.5 | Kimi-K2-Instruct | small_json_repair_model |
| deployment_mode | api_or_self_hosted | api | api_or_self_hosted_unknown | api_or_self_hosted_unknown | self_hosted |
| supports_streaming_input | unsupported | unsupported | unknown | unknown | unsupported |
| supports_streaming_output | real | real | unknown | unknown | degraded |
| supports_audio_input | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_audio_output | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_audio_timestamps | not_applicable | not_applicable | not_applicable | not_applicable | not_applicable |
| supports_structured_json | degraded | real | unknown | unknown | degraded |
| supports_tool_calling | real | real | unknown | unknown | unsupported |
| supports_cancellation | degraded | degraded | unknown | unknown | degraded |
| supports_emotion | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_audio_caption | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_tts | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | degraded | degraded | unknown | unknown | unsupported |
| supports_assistant_directedness | degraded | degraded | unknown | unknown | unsupported |
| max_audio_seconds | not_applicable | not_applicable | not_applicable | not_applicable | not_applicable |
| max_context_tokens | real_256k_to_1m_claimed_for_qwen3_paths | real_1m_claimed | unknown | unknown | unknown |
| max_output_tokens | degraded_16k_to_32k_examples | real_384k_claimed | unknown | unknown | unknown |
| expected_first_token_latency_ms | unknown | unknown | unknown | unknown | unknown |
| expected_first_audio_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable | not_applicable |
| output_mode | real_or_fallback | real | unknown | unknown | fallback |
| degradation_notes | 与 DashScope 对齐好；JSON/schema 仍需 local validation | 强 API candidate；需验证 current names 与 quotas | promising，但 source details 需要 adapter trial | promising，但 current official details 需要 verification | 只用于 schema repair 或 tiny fallback，不作为 primary reasoning |

## Candidate Comparison

Qwen3 是最合适的第一 aligned candidate，因为官方材料描述了 long context、tool use、open-weight deployment 与 DashScope/OpenAI-compatible serving options。DeepSeek 是强 API alternative，因为官方 API docs 描述了 OpenAI-compatible usage、long context、JSON output 与 tool-call support。GLM-4.5 与 Kimi K2 是有价值的 comparison candidates，但本轮仍将多个 operational fields 保持 unknown，直到 endpoint-level verification 完成。

Slow LLM 应主要用 structured JSON reliability、schema recovery、plan quality 与 stale-result behavior 来评价。Voice capability 与此角色无关。

## Recommended MVP Usage

当 operational access 可用时，优先使用 Qwen3 via DashScope/Bailian 作为 SlowTask planning candidate。DeepSeek 作为 structured planning 的第二 API candidate。若 latency 与 memory budget 允许，可考虑 A100 上 self-hosted Qwen3-30B-A3B 或类似模型做 offline tests。GLM-4.5 与 Kimi K2 在 current structured-output 与 tool-call contracts 验证后再进入 comparison runs。

## API / Deployment Notes

DashScope 提供 OpenAI-compatible Chat Completions、OpenAI Responses-style API 与 native DashScope APIs；adapter 应选择一个 surface，并记录它。Model-side tool calls 只能作为 proposals 接收。项目 Tool Executor 必须验证 authorization、confirmation、sandbox policy 与 canonical events，之后才能表示任何 demo tool effect。

## Latency and Resource Notes

SlowTask 可容忍比 Duplex/ASR partial 更高的 latency，但 user-facing progress 与 cancellation 仍必须响应。Long-context models 应接收 compact evidence snapshots，而不是 raw traces。Self-host Qwen3-class models 是否适合 A100 取决于 size/quantization；exact memory 与 throughput 需要本地测量。

## Schema / Structured Output Notes

Structured JSON 应由 adapter validation 强制：

- provider 支持时请求 schema-constrained JSON；
- 本地 parse 与 validate；
- 使用 validation errors 做 evidence-free repair prompts；
- fallback 到更小的 JSON-repair path 或 mock/degraded result；
- malformed JSON 绝不更新 task state。

Schema failures 应产生显式 degraded evidence，而不是 silent free-text parsing。

## Cancellation / Timeout / Retry Notes

Provider cancellation 往往弱于 local task cancellation。Adapter 应在 cancel/timeout 时关闭 streams，但 late responses 必须绑定原始 `task_id`、`plan_version` 与 `task_event_seq`。旧结果进入 stale evidence，除非 SlowTask 显式 adopt/rebase。Retries 必须使用稳定 evidence snapshot，且不得产生新的 hidden instructions。

## Trace and Privacy Notes

当 provider prompts 包含用户敏感内容时，不要保存完整 raw prompt。保存 redacted evidence summaries、schema name/version、model id、output mode、validation status 与安全的 provider request id。Authorization headers、cookies、API keys 与 tool credentials 绝不进入 trace。

## Degradation Proposal

- Structured JSON 在 bounded retry 后仍失败时，发出带 validation errors 的 degraded planning failure。
- 如果 tool-call format unsupported，请求 plain JSON `tool_call_proposal` 并本地 normalize。
- 如果 long context unavailable，先通过 deterministic reducers 总结 evidence，再调用模型。
- 如果 provider timeout，保持 current plan version 不变，并可选用 mock/fallback plan 支持 demo replay。

## Risks

- 把 model-side tool calling 当作 execution 会违反 Tool Executor boundaries。
- 允许 late completions 更新 current state 会违反 ADR-016。
- Large contexts 可能意外把 untrusted web evidence 放进 instruction space。
- Provider-specific JSON modes 可能不同，带来 portability issues。
- Reasoning traces 如果记录，可能泄露 private prompt/evidence content。

## Suggested Follow-up Experiments

- 在 Qwen3、DeepSeek、GLM-4.5 与 Kimi K2 上跑 schema-constrained planning prompts。
- 用固定 synthetic evidence 测 invalid JSON repair。
- 在 completion in-flight 时模拟 cancellation 与 plan_version changes。
- 比较 model-side tool-call proposals 与 local Tool Executor authorization gates。
- 测 compact evidence snapshots 与 long raw context 的 cost/latency。

## Recommendation

SlowTask planning 优先 Qwen3 through DashScope/Bailian 或 self-hosted Qwen3；DeepSeek 作为第一 alternate API candidate。优化重点是 schema validity、retry behavior 与 plan_version stale policy，而不是 speech features。Model-side tool calls 只能作为 proposals，并必须通过 Tool Executor。
