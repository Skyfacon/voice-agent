# Slow LLM Capability Spike

## Status

evidence_report

## Date

2026-05-09

## Scope

This report evaluates Slow LLM candidates for SlowTask planning, ReAct-style reasoning, structured output, schema retry, long context, and tool-call normalization. It intentionally does not prioritize speech capability.

## Architecture Role

Slow LLM supports SlowTask planning, evidence synthesis, argument resolution, confirmation proposals, and SemanticCommitment drafting. It operates behind a model adapter and must bind outputs to `task_id`, `plan_version`, and `task_event_seq` where applicable. It may propose tool calls, but Tool Executor remains the only execution and authorization path.

## ADR Constraints

- ADR-008: SlowTask resolves ASR/Thinker conflicts and emits semantic commitments through controlled events.
- ADR-009: Composer cannot rewrite SlowTask facts; Slow LLM planning facts need coverage and truthfulness checks before speech.
- ADR-011: every provider/model must declare capability matrix, output mode, fallback/degraded behavior, and retry semantics.
- ADR-014: webSearch/RAG evidence is untrusted evidence and cannot enter instruction space.
- ADR-016: old plan results cannot advance current task without explicit adopt/rebase.

## Candidate Shortlist

- Qwen3 Instruct / Thinking family: primary open/open-weight and DashScope-aligned candidate for structured planning, long context, and tool-use experiments.
- DeepSeek current API models: strong API candidate with OpenAI-compatible surface, long context, JSON output, and tool-call support per official API docs.
- GLM-4.5 family: candidate for API structured planning and Chinese reasoning; exact schema/tool/cancellation details require endpoint-level verification.
- Kimi K2: candidate for long-context/tool reasoning, but exact current structured JSON and deployment details should be verified from official docs/model cards before use.
- DashScope/Bailian Qwen via OpenAI-compatible Chat Completions or native DashScope API: operationally attractive first integration path for Qwen models.

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
| degradation_notes | excellent alignment with DashScope; validate JSON/schema locally | strong API candidate; verify current names and quotas | promising but source details need adapter trial | promising but current official details need verification | only for schema repair or tiny fallback, not primary reasoning |

## Candidate Comparison

Qwen3 is the best first aligned candidate because official materials describe long context, tool use, open-weight deployment, and DashScope/OpenAI-compatible serving options. DeepSeek is a strong API alternative because official API docs describe OpenAI-compatible usage, long context, JSON output, and tool-call support. GLM-4.5 and Kimi K2 are useful comparison candidates, but this pass leaves several operational fields unknown until endpoint-level verification.

Slow LLM should be judged primarily on structured JSON reliability, schema recovery, plan quality, and stale-result behavior. Voice capability is irrelevant for this role.

## Recommended MVP Usage

Use Qwen3 via DashScope/Bailian as the first SlowTask planning candidate when operational access is available. Keep DeepSeek as a second API candidate for structured planning. Consider self-hosted Qwen3-30B-A3B or similar on A100 for offline tests if latency and memory budgets allow. Defer GLM-4.5 and Kimi K2 to comparison runs after their current structured-output and tool-call contracts are verified.

## API / Deployment Notes

DashScope offers OpenAI-compatible Chat Completions, OpenAI Responses-style API, and native DashScope APIs; the adapter should pick one surface and record it. Model-side tool calls can be accepted as proposals only. The project Tool Executor must validate authorization, confirmation, sandbox policy, and canonical events before any demo tool effect is represented.

## Latency and Resource Notes

SlowTask can tolerate higher latency than Duplex/ASR partials, but user-facing progress and cancellation must remain responsive. Long-context models can be costly and should receive compact evidence snapshots rather than raw traces. Self-host Qwen3-class models may be A100-suitable depending on size/quantization; exact memory and throughput require local measurement.

## Schema / Structured Output Notes

Structured JSON should be enforced by adapter validation:

- request schema-constrained JSON when provider supports it;
- parse and validate locally;
- retry with validation errors as evidence-free repair prompts;
- fall back to a smaller JSON-repair path or mock/degraded result;
- never let malformed JSON update task state.

Schema failures should produce explicit degraded evidence, not silent free-text parsing.

## Cancellation / Timeout / Retry Notes

Provider cancellation is usually weaker than local task cancellation. The adapter should close streams on cancel/timeout, but late responses must remain bound to the original `task_id`, `plan_version`, and `task_event_seq`. Old results go to stale evidence unless SlowTask explicitly adopts/rebases them. Retries must use a stable evidence snapshot and must not generate new hidden instructions.

## Trace and Privacy Notes

Do not store full raw provider prompts when they include user-sensitive content. Store redacted evidence summaries, schema name/version, model id, output mode, validation status, and provider request id when safe. Authorization headers, cookies, API keys, and tool credentials must never enter trace.

## Degradation Proposal

- If structured JSON fails after bounded retry, emit a degraded planning failure with validation errors.
- If tool-call format is unsupported, ask for plain JSON `tool_call_proposal` and normalize locally.
- If long context is unavailable, summarize evidence through deterministic reducers before calling the model.
- If provider times out, keep current plan version unchanged and optionally use mock/fallback plan for demo replay.

## Risks

- Treating model-side tool calling as execution would violate Tool Executor boundaries.
- Letting late completions update current state would violate ADR-016.
- Large contexts can accidentally include untrusted web evidence in instruction space.
- Provider-specific JSON modes may differ and create portability issues.
- Reasoning traces can leak private prompt/evidence content if logged.

## Suggested Follow-up Experiments

- Run schema-constrained planning prompts across Qwen3, DeepSeek, GLM-4.5, and Kimi K2.
- Test invalid JSON repair with fixed synthetic evidence.
- Simulate cancellation and plan_version changes while completions are in flight.
- Compare model-side tool-call proposals against local Tool Executor authorization gates.
- Measure cost/latency for compact evidence snapshots vs long raw context.

## Recommendation

Prioritize Qwen3 through DashScope/Bailian or self-hosted Qwen3 for SlowTask planning, with DeepSeek as the first alternate API candidate. Optimize for schema validity, retry behavior, and plan_version stale policy rather than speech features. Keep model-side tool calls as proposals that must pass through Tool Executor.
