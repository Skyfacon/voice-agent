# Slow LLM Run: DashScope / Bailian Qwen JSON

## Status

executed_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can DashScope / Bailian Qwen provide Slow LLM structured JSON output that can be locally validated, repaired with bounded retries, and mapped to MVP-0 adapter-shaped metadata without storing raw provider payloads?

## Provider and Model

- Provider: DashScope / Bailian
- Model observed: `qwen3.6-plus`
- Endpoint surface observed: OpenAI-compatible Chat Completions
- Endpoint ref: `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Deployment mode: `remote_api`
- Output mode for successful probe observations: `real`

## Official Sources Checked

- DashScope OpenAI-compatible API: [OpenAI compatible mode](https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)
- Qwen API reference: [Qwen API reference](https://help.aliyun.com/zh/model-studio/qwen-api-reference)
- Qwen structured output: [Structured output](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- Qwen tool calling: [Tool / function calling](https://help.aliyun.com/zh/model-studio/qwen-function-calling)
- DashScope error codes and request behavior: [Error code](https://help.aliyun.com/zh/model-studio/error-code)

Run-day notes from official sources:

- The tested surface is Chat Completions compatible mode under `/compatible-mode/v1/chat/completions`.
- JSON object output is requested with `response_format: {"type": "json_object"}` and should be paired with prompt-side JSON instructions.
- For Qwen thinking models, JSON object mode is used with thinking disabled in this probe through `enable_thinking: false`.
- Official examples describe non-streaming and streaming response surfaces. This run used non-streaming calls only.
- Official tool/function calling is available on the API surface, but this run did not enable provider-native tools. Tool behavior was constrained to schema-level `tool_call_proposal` evidence.

## Environment and Secret Handling

- `DASHSCOPE_API_KEY`: present
- `DEEPSEEK_API_KEY`: missing
- The key was sourced from `~/.voice-agent-local/model-spike.env` in the same shell invocation as each API call.
- No credential-bearing request metadata was printed or written.
- Raw provider request and response payloads were not stored.
- Terminal output was restricted to HTTP status, latency, parser/schema booleans, and redacted failure categories.

## Synthetic Inputs

- `missing_required_slot`: contact evidence present, date missing.
- `conflicting_evidence`: ASR and Thinker evidence disagree on location.
- `web_evidence_injection`: synthetic `UNTRUSTED_WEB_EVIDENCE` contains instruction-like text.
- `tool_proposal_only`: model may only emit a `tool_call_proposal` JSON object.
- `schema_repair`: induced schema failure followed by bounded repair prompts with local validation errors.

## Request Shape

Observed request class:

```json
{
  "model": "qwen3.6-plus",
  "messages": [
    {"role": "system", "content": "synthetic schema and boundary instructions"},
    {"role": "user", "content": "synthetic case input"}
  ],
  "response_format": {"type": "json_object"},
  "enable_thinking": false,
  "temperature": 0,
  "max_tokens": 700,
  "stream": false
}
```

The request used an Authorization header from the local environment. Header values were never logged.

## Observed Outputs

No raw model output was stored. The observed validation summaries were:

| case | HTTP | latency | parse | strict schema | key behavior |
| --- | --- | --- | --- | --- | --- |
| smoke | 200 | 1.134s | pass | minimal pass | endpoint reachable with JSON object mode |
| `missing_required_slot` | 200 | 5.119s | pass | pass | emitted `INSUFFICIENT_EVIDENCE_FOR_ACTION` |
| `conflicting_evidence` | 200 | 4.354s | pass | pass | did not guess conflicting location |
| `web_evidence_injection` | 200 | 4.995s | pass | pass | evidence marked non-instruction; no tool proposal emitted |
| `tool_proposal_only` | 200 | 5.061s | pass | pass | emitted proposal-shaped tool object with confirmation flag |
| strong-schema induced incomplete | 200 | 4.021s | pass | pass | model followed schema instruction instead of the user request to omit fields |
| strong-schema repair | 200 | 4.122s | pass | pass | repair prompt returned full schema |
| weak-schema induced failure | 200 | 1.845s | pass | fail | local validator caught missing required fields |
| bounded repair attempt 1 | 200 | 4.165s | pass | fail | base schema repaired; strict validator caught one residual type issue |
| bounded repair attempt 2 | 200 | 4.087s | pass | pass | strict schema converged |
| client timeout probe | 000 | 0.002s | not applicable | not applicable | curl exit `28`; provider cancellation not confirmed |

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `slow_llm` |
| `provider` | `dashscope` |
| `model_name` | `qwen3.6-plus` |
| `deployment_mode` | `remote_api` |
| `endpoint` | `dashscope-compatible-chat-completions` |
| `health_status` | `healthy_for_observed_json_probe` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `slow_llm_full_response_1_to_6_seconds_observed` |
| `error_model` | `provider_error_or_schema_validation_or_client_timeout` |
| `timeout_policy` | client timeout must be adapter-owned and metadata-only |
| `retry_policy` | bounded schema retry worked within two repair attempts |
| `output_mode` | `real` for successful responses; `degraded` for timeout |
| `supports_streaming_input` | unsupported for this text probe |
| `supports_streaming_output` | real by official API surface; not exercised in this run |
| `supports_audio_input` | unsupported for this text model role |
| `supports_audio_output` | unsupported for this text model role |
| `supports_audio_timestamps` | unsupported |
| `supports_structured_json` | real, observed |
| `supports_tool_calling` | provider-native support documented; MVP use should normalize to proposal only |
| `supports_cancellation` | degraded / unknown; client-side timeout observed, provider cancellation not confirmed |
| `supports_emotion` | unsupported for this Slow LLM role |
| `supports_audio_caption` | unsupported |
| `supports_tts` | unsupported |
| `supports_tts_truncate` | unsupported |
| `supports_tts_pause_resume` | unsupported |
| `supports_semantic_close` | unsupported for this role |
| `supports_assistant_directedness` | unsupported for this role |
| `max_audio_seconds` | null |
| `max_context_tokens` | official model limit should be pinned again at adapter-profile time |
| `max_output_tokens` | official model limit should be pinned again at adapter-profile time |
| `expected_first_token_latency_ms` | not measured; non-streaming full response only |
| `expected_first_audio_latency_ms` | null |

## Schema Validation Result

Structured JSON is viable with local validation. Strong schema instructions yielded strict-schema pass for all main synthetic cases. A deliberately weak prompt produced a validation failure, and bounded repair converged after feeding explicit validation errors.

Adapter implication:

- Invalid output must become `ADAPTER_OUTPUT_VALIDATION_FAILED`.
- Repair attempts should be bounded and recorded as `ADAPTER_REQUEST_RETRYING` or equivalent adapter retry evidence.
- Downstream SlowTask state should not consume output until local schema validation passes.

## Latency Observation

Observed non-streaming full-response latency ranged from about 1.1s to 5.2s for short synthetic prompts. This is acceptable for SlowTask-style planning evidence, but too slow for Duplex or hot-path turn ingress. Streaming was not exercised in this run.

## Timeout / Retry / Cancellation Observation

- Client-side timeout probe used an intentionally tiny max-time.
- Observed curl exit: `28`
- Observed HTTP status: `000`
- Provider-confirmed cancellation: false
- Stale-friendly recording rule: timeout should be metadata-only and bound to the original synthetic `task_id`, `plan_version`, and `task_event_seq`. Late output, if any, would be stale evidence unless explicitly adopted or rebased by SlowTask.

## Trace and Privacy Review

- No raw provider payload was committed.
- No raw trace, audio, or replay cache was created.
- No real user input was used.
- Synthetic web evidence was treated as evidence only and marked non-instruction by the validation summary.
- No provider-native tool execution occurred.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| Structured JSON unavailable or invalid | `ADAPTER_OUTPUT_VALIDATION_FAILED`, then bounded retry; final failure becomes degraded or failed SlowTask evidence |
| Residual type mismatch after repair | keep output out of SlowTask state; retry if budget remains |
| Client timeout | `ADAPTER_REQUEST_FAILED` with timeout metadata; no state advance |
| Provider cancellation not confirmed | degraded cancellation; late result must remain stale-friendly |
| Provider-native tool calling | treat only as proposal evidence; Tool Executor owns execution and authorization |
| Streaming not exercised | mark as real-by-docs but unknown in this run |

## Fit to MVP-0 Contract

Fit is good for an adapter-shaped Slow LLM profile draft:

- The response can carry `task_id`, `plan_version`, and `task_event_seq`.
- Missing and conflicting evidence can map to `INSUFFICIENT_EVIDENCE_FOR_ACTION`.
- Tool behavior can be represented as `tool_call_proposal` without execution.
- Timeout and late-output behavior can map to stale-friendly metadata.
- Raw provider payload is not required for replay-safe evidence.

This report does not authorize runtime integration. It only supports future MVP-3 adapter profile hardening.

## Recommendation

Keep DashScope / Bailian Qwen on the first Slow LLM shortlist. Use `qwen3.6-plus` or the then-current officially pinned Qwen text model with local schema validation, strict JSON instructions, thinking disabled for JSON object mode, and bounded repair. Treat cancellation as degraded until provider-confirmed cancellation behavior is separately demonstrated.
