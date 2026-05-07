# Model Adapter Capability Contract

Source of truth: frozen ADR Baseline v0.4. This document carries P1-B-004. It is a spec detail, derived from ADR baseline.

All model services must be accessed through adapters. Business modules must not call provider endpoints directly. [ADR-011, AGENTS.md]

## 1. Capability Matrix Schema

Every adapter declares a capability matrix at startup and healthcheck time. [ADR-011]

Required adapter identity fields:

| Field | Required | Meaning |
| --- | --- | --- |
| `adapter_id` | yes | Stable adapter id. |
| `adapter_type` | yes | ASR, Thinker, Composer, Slow LLM, TTS/Talker, Duplex model, Embedding/RAG, Mock. |
| `provider` | yes | Provider or `mock`. |
| `model_name` | yes | Model/deployment name or mock profile. |
| `deployment_mode` | yes | `mock`, `local`, `remote_api`, `self_hosted`, or equivalent. |
| `endpoint` | yes | Endpoint ref, not credential-bearing URL. |
| `health_status` | yes | Current health. |
| `capability_version` | yes | Capability schema version. |
| `latency_class` | yes | Declared latency class. |
| `error_model` | yes | Error taxonomy/ref. |
| `timeout_policy` | yes | Timeout policy/ref. |
| `retry_policy` | yes | Retry policy/ref. |
| `output_mode` | yes | `real`, `mock`, `fallback`, or `degraded`. |

Required capability fields:

| Capability | Type | Required | Meaning |
| --- | --- | --- | --- |
| `supports_streaming_input` | boolean | yes | Adapter can consume streaming input. |
| `supports_streaming_output` | boolean | yes | Adapter can produce streaming output. |
| `supports_audio_input` | boolean | yes | Adapter accepts audio input. |
| `supports_audio_output` | boolean | yes | Adapter emits audio output. |
| `supports_audio_timestamps` | boolean | yes | Adapter can provide timing offsets. |
| `supports_structured_json` | boolean | yes | Adapter can produce validated structured JSON. |
| `supports_tool_calling` | boolean | yes | Adapter can produce tool-call-like structured intent, if allowed. |
| `supports_cancellation` | boolean | yes | Adapter supports request/tool cancellation. |
| `supports_emotion` | boolean | yes | Adapter can infer emotion. |
| `supports_audio_caption` | boolean | yes | Adapter can produce audio captions. |
| `supports_tts` | boolean | yes | Adapter can synthesize speech. |
| `supports_tts_truncate` | boolean | yes | Talker/TTS can stop playback for truncate flow. |
| `supports_tts_pause_resume` | boolean | yes | Pause/resume support; not required in MVP. |
| `supports_semantic_close` | boolean | yes | Adapter/Duplex model can infer semantic close. |
| `supports_assistant_directedness` | boolean | yes | Adapter/Duplex model can infer assistant-directedness. |
| `latency_class` | enum/ref | yes | Development latency category or measured bucket. |
| `max_audio_seconds` | integer/null | yes | Maximum input audio duration. |
| `max_context_tokens` | integer/null | yes | Maximum context tokens. |
| `max_output_tokens` | integer/null | yes | Maximum output tokens. |
| `expected_first_token_latency_ms` | integer/null | yes | Expected first-token latency. |
| `expected_first_audio_latency_ms` | integer/null | yes | Expected first-audio latency. |

Mock-specific fields:

- `mocked=true` for capabilities simulated by mock behavior.
- `mock_profile_ref` for deterministic fixture behavior.
- `target_architecture_validation=false` when the mock lacks required real interface evidence, such as playback reference for barge-in. [ADR-003, ADR-011]

## 2. Startup Capability Snapshot

At session startup, Session Runtime / Adapter Registry MUST record:

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`

`ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` includes:

- `capability_snapshot_ref`
- `adapter_ids`
- `adapter_types`
- `deployment_modes`
- `output_modes`

Spec detail, derived from ADR baseline: the snapshot ref must resolve to matrices for all configured adapters in the session. Replay uses the snapshot to distinguish real/mock/fallback/degraded state without probing adapters.

## 3. Adapter Health Events

Canonical health and error events from ADR-002 / ADR-011:

- `ADAPTER_HEALTHCHECK_FAILED`
- `ADAPTER_REQUEST_RETRYING`
- `ADAPTER_REQUEST_FAILED`
- `ADAPTER_OUTPUT_VALIDATION_FAILED`
- `ADAPTER_OUTPUT_DEGRADED`

Frame/output events must carry `output_mode=real|mock|fallback|degraded` or reference a capability snapshot that contains that mode. [ADR-011]

## 4. Adapter Error Events

Error events must include enough structured fields for replay and debugging:

| Event | Required fields |
| --- | --- |
| `ADAPTER_HEALTHCHECK_FAILED` | `adapter_id`, `adapter_type`, `health_status`, `failure_reason`, `output_mode` |
| `ADAPTER_REQUEST_RETRYING` | `adapter_id`, `adapter_type`, `adapter_request_id`, `retry_count`, `retry_reason`, optional `timeout_ms` |
| `ADAPTER_REQUEST_FAILED` | `adapter_id`, `adapter_type`, `adapter_request_id`, `failure_reason`, `retryable`, optional `timeout_ms`, `output_mode` |
| `ADAPTER_OUTPUT_VALIDATION_FAILED` | `adapter_id`, `adapter_type`, `adapter_request_id`, `schema_name`, `failure_reasons`, `output_mode` |
| `ADAPTER_OUTPUT_DEGRADED` | `adapter_id`, `adapter_type`, optional `adapter_request_id`, `degraded_reason`, optional `missing_capability`, optional `fallback_adapter_id`, `output_mode` |

Secret-bearing request bodies, headers, tokens, cookies, credentials, and authorization headers must never be logged in adapter events. [ADR-010, ADR-011]

## 5. Timeout / Retry / Cancellation Policy

Spec detail, derived from ADR baseline:

- Each adapter declares `timeout_policy` and `retry_policy` in its matrix. [ADR-011]
- Retryable timeout/failure emits `ADAPTER_REQUEST_RETRYING`.
- Final failure emits `ADAPTER_REQUEST_FAILED`.
- Provider output schema failure emits `ADAPTER_OUTPUT_VALIDATION_FAILED`; downstream modules must not consume invalid output silently. [ADR-011]
- If adapter supports cancellation and SlowTask plan advances or cancellation is accepted, cancellation flow may emit `TOOL_EXECUTION_CANCEL_REQUESTED` / `TOOL_EXECUTION_CANCELLED` for tool adapters, or adapter-specific request failure/degradation events for model requests. [ADR-004, ADR-016]
- If adapter does not support cancellation, do not fake cancellation success; wait for result and apply stale policy if the plan advanced. [ADR-004, ADR-016]

## 6. Degradation Decision Table

| Missing / failed capability | Affected module | Required behavior | Required event |
| --- | --- | --- | --- |
| No streaming ASR input/output | ASR Adapter, Interaction chain | Use final transcript/text projection only; label output mode. | `ADAPTER_OUTPUT_DEGRADED` if scenario expected streaming |
| No audio timestamps | ASR/Thinker/Duplex | Omit exact model timing; preserve event timing and mark timestamp source unavailable. | `ADAPTER_OUTPUT_DEGRADED` when timing was required |
| No emotion | Thinker | Set emotion unavailable; do not default to neutral unless predicted. | `ADAPTER_OUTPUT_DEGRADED` when emotion expected |
| No audio caption | Thinker | Set audio caption unavailable; keep ASR/other evidence. | `ADAPTER_OUTPUT_DEGRADED` when caption expected |
| No semantic_close | Duplex/Thinker | Use Duplex mock/rule-based or Interaction conservative policy; label mock/degraded. | `ADAPTER_OUTPUT_DEGRADED` or mock frame event |
| No assistant-directedness | Duplex/Thinker | Use assumed/unknown policy per Interaction Controller; do not silently accept as directed unless text policy applies. | `ADAPTER_OUTPUT_DEGRADED` when expected |
| No structured JSON for Slow LLM | Slow LLM Adapter, SlowTask | Parser/validator retry if configured; then fail task or fallback mock/degraded path. | `ADAPTER_OUTPUT_VALIDATION_FAILED`, optional `ADAPTER_REQUEST_RETRYING`, `ADAPTER_OUTPUT_DEGRADED`, `SLOWTASK_FAILED` |
| No tool calling | Thinker/Slow LLM | Do not rely on provider-native tool calls; use system schema/SlowTask structured output or block. | `ADAPTER_OUTPUT_DEGRADED` if provider tool calling expected |
| No cancellation | Tool/Model Adapter | Do not fake success; wait for result and apply stale policy after plan advance. | No fake cancel; stale chain when result returns |
| No TTS | Talker | Use mock TTS only if MVP allows; label mock/degraded; real playback validation unavailable. | `ADAPTER_OUTPUT_DEGRADED` or mock playback events |
| No TTS truncate | Talker, Interaction | Barge-in target validation cannot pass; block target validation or mark degraded. | `ADAPTER_OUTPUT_DEGRADED`; MVP-0 scenario fails target criterion if truncate required |
| No TTS pause/resume | Talker | Acceptable in MVP; pause/resume remains non-goal. | none unless feature requested |
| Context too long | Thinker/Slow LLM/Composer | Truncate/summarize through approved context policy; if impossible, fail/degrade. | `ADAPTER_OUTPUT_DEGRADED` or `ADAPTER_REQUEST_FAILED` |
| Audio exceeds max seconds | ASR/Thinker/Duplex | Segment or reject/degrade according to adapter contract; preserve span refs. | `ADAPTER_OUTPUT_DEGRADED` or `ADAPTER_REQUEST_FAILED` |

## 7. Capability Missing Behavior Options

Allowed behavior labels:

- `mock_fallback`: use mock adapter and label output as mock.
- `disable_scenario`: scenario cannot validate target architecture and must be skipped or failed with clear reason.
- `degrade_to_text_only`: continue with text projection only.
- `require_confirmation`: require user confirmation when risk is elevated or evidence is degraded.
- `block_feature`: refuse to run a feature whose required capability is absent.
- `record_degradation_event`: emit `ADAPTER_OUTPUT_DEGRADED` or related event.

Rules:

- Required capability absent for a safety-critical path should `block_feature` or `disable_scenario`.
- Required capability absent for a quality-only path may `degrade_to_text_only` or `mock_fallback`.
- Any fallback/degradation must be replay-visible. [ADR-011, ADR-012]
- Mock fallback cannot be counted as real capability validation. [ADR-011, ADR-012]

## 8. Capability Profiles by MVP Slice

### MVP-0

Required:

- ASR mock capability matrix.
- Thinker mock capability matrix.
- Slow Agent mock capability matrix if present.
- TTS mock capability matrix with playback progress and truncate behavior.
- Tool mock capability matrix if tools are stubbed.
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` at session startup. [ADR-002, ADR-011, ADR-012]

Not required:

- Real ASR / Thinker / Slow LLM / TTS.
- Real semantic_close / assistant-directedness.
- Real pause/resume.

### MVP-1

Required:

- SlowTask mock / Slow Agent mock structured outputs for lifecycle, UserPatch interpretation, plan_version, stale policy, and SemanticCommitment mock.
- Capability labels for mock vs degraded outputs.

### MVP-2

Required:

- Tool adapter/executor capability for progressive demo protocol.
- Composer role capability or template fallback.
- Coverage/truthfulness check support.

### MVP-3

Required:

- At least one real/remote endpoint for ASR, Thinker, Slow LLM, and TTS where selected.
- HTTP/WebSocket healthcheck.
- Timeout/retry/error events.
- Structured JSON validation for Slow LLM.
- TTS basic audio synthesis.
- No new architecture capability while integrating. [ADR-012]

## 9. Validation Requirements

- MVP-0 mock capability case verifies all mocks declare matrices honestly and startup snapshot is replayable. [ADR-011, ADR-012]
- Adapter failure paths verify `ADAPTER_HEALTHCHECK_FAILED`, `ADAPTER_REQUEST_RETRYING`, `ADAPTER_REQUEST_FAILED`, and `ADAPTER_OUTPUT_VALIDATION_FAILED`. [ADR-011]
- No unsupported capability may be silently used. [ADR-011]
- Adapter outputs must be real/mock/fallback/degraded distinguishable in trace/replay. [ADR-011, ADR-012]
- Adapter events must not write secrets to trace. [ADR-010, ADR-011]
