# Slow LLM Run: DeepSeek JSON

## Status

not_executed_key_missing

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can the current DeepSeek text API provide Slow LLM structured JSON output comparable to the DashScope Qwen probe?

## Provider and Model

- Provider: DeepSeek
- Model: not executed because `DEEPSEEK_API_KEY` was missing.
- Candidate names checked from official docs on the run date: current DeepSeek chat/reasoner aliases and current model list pages should be pinned at execution time.
- Endpoint surface planned: OpenAI-compatible Chat Completions.
- Endpoint ref planned: `https://api.deepseek.com/chat/completions`

## Official Sources Checked

- DeepSeek API docs entry point: [DeepSeek API Docs](https://api-docs.deepseek.com/)
- Chat completion API: [Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion)
- Models and pricing: [Pricing / models](https://api-docs.deepseek.com/quick_start/pricing)
- Function calling guide: [Function Calling](https://api-docs.deepseek.com/guides/function_calling)
- JSON output guide: [JSON Output](https://api-docs.deepseek.com/guides/json_mode)

Run-day notes from official sources:

- DeepSeek exposes an OpenAI-compatible Chat Completions surface.
- The chat completion API includes `response_format`, `stream`, `tools`, and `tool_choice` style request fields.
- JSON output requires request-side JSON instructions in addition to JSON response mode.
- Function calling is an API output format and still requires caller-side validation and execution ownership.
- This run did not find provider-confirmed cancellation behavior sufficient to mark cancellation real.

## Environment and Secret Handling

- `DASHSCOPE_API_KEY`: present
- `DEEPSEEK_API_KEY`: missing
- No DeepSeek API call was attempted.
- No credential-bearing request metadata was printed or written.
- No raw provider payload was created.

## Synthetic Inputs

Planned cases, not executed:

- `missing_required_slot`
- `conflicting_evidence`
- `web_evidence_injection`
- `tool_proposal_only`
- `schema_repair`

## Request Shape

Planned request class, not executed:

```json
{
  "model": "official-current-deepseek-text-model",
  "messages": [
    {"role": "system", "content": "synthetic schema and boundary instructions"},
    {"role": "user", "content": "synthetic case input"}
  ],
  "response_format": {"type": "json_object"},
  "temperature": 0,
  "max_tokens": 700,
  "stream": false
}
```

If executed later, the Authorization header must be sourced from local environment only and never logged.

## Observed Outputs

No live provider outputs were observed. This candidate remains `unknown_runtime` for this run.

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `slow_llm` |
| `provider` | `deepseek` |
| `model_name` | unknown for this run; pin official current model at execution time |
| `deployment_mode` | `remote_api` planned |
| `endpoint` | `deepseek-chat-completions` planned |
| `health_status` | `not_executed_key_missing` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | unknown |
| `error_model` | key missing; provider behavior unobserved |
| `timeout_policy` | unknown |
| `retry_policy` | unknown |
| `output_mode` | unknown |
| `supports_streaming_input` | unsupported for text Chat Completions role |
| `supports_streaming_output` | official API surface supports streaming; unobserved here |
| `supports_audio_input` | unsupported for this Slow LLM role |
| `supports_audio_output` | unsupported for this Slow LLM role |
| `supports_audio_timestamps` | unsupported |
| `supports_structured_json` | official API surface documents JSON output; unobserved here |
| `supports_tool_calling` | official API surface documents tool/function calling; unobserved here |
| `supports_cancellation` | unknown / degraded until tested |
| `supports_emotion` | unsupported for this role |
| `supports_audio_caption` | unsupported |
| `supports_tts` | unsupported |
| `supports_tts_truncate` | unsupported |
| `supports_tts_pause_resume` | unsupported |
| `supports_semantic_close` | unsupported for this role |
| `supports_assistant_directedness` | unsupported for this role |
| `max_audio_seconds` | null |
| `max_context_tokens` | unknown in this report |
| `max_output_tokens` | unknown in this report |
| `expected_first_token_latency_ms` | unknown |
| `expected_first_audio_latency_ms` | null |

## Schema Validation Result

Not executed. JSON output remains official-doc-supported but not observed in this environment. It must not be marked real for this repository until a live probe passes local validation.

## Latency Observation

Not executed.

## Timeout / Retry / Cancellation Observation

Not executed. Treat timeout, retry, and cancellation as unknown. Later DeepSeek probe should mirror the DashScope run:

- full-response JSON validation for all synthetic cases
- induced schema failure
- bounded repair with validation errors
- client-side timeout with provider cancellation explicitly marked unconfirmed unless DeepSeek confirms it

## Trace and Privacy Review

- No DeepSeek raw payload exists from this run.
- No local trace, replay cache, or provider response file was created.
- No real user input was used.
- Missing key status is safe to commit because it contains no secret value.

## Degradation Mapping

| condition | mapping |
| --- | --- |
| Key missing | `not_executed_key_missing`; no provider call |
| Structured JSON unobserved | `unknown_runtime`; cannot support MVP-3 profile yet |
| Tool calling unobserved | docs-only evidence; must normalize to proposal evidence when tested |
| Cancellation unobserved | degraded / unknown |

## Fit to MVP-0 Contract

DeepSeek remains a plausible comparison candidate by official API shape, but this run provides no live adapter-shaped evidence. It cannot yet fill an observed MVP-0 Slow LLM capability profile.

## Recommendation

Defer DeepSeek live comparison until `DEEPSEEK_API_KEY` is present. When available, rerun the same synthetic cases and local validator used for DashScope, then compare strict-schema pass rate, bounded repair convergence, latency bucket, and timeout behavior.
