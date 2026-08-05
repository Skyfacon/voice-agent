# Model Adapter Capability Contract / 模型 Adapter 能力契约

Source of truth: frozen ADR Baseline v0.4。本文件承载 P1-B-004，是从 ADR baseline 派生的实现规格。

所有模型服务必须通过 adapter 访问。业务模块不得直接调用 provider endpoint。

## 1. Capability Matrix Schema

每个 adapter 在 startup 和 healthcheck 时都必须声明 capability matrix。

### Adapter identity fields

| 字段 | 必填 | 含义 |
| --- | --- | --- |
| `adapter_id` | yes | 稳定 adapter id。 |
| `adapter_type` | yes | ASR, Thinker, Composer, Slow LLM, TTS/Talker, Duplex model, Embedding/RAG, Mock。 |
| `provider` | yes | provider 或 `mock`。 |
| `model_name` | yes | 模型/部署名或 mock profile。 |
| `deployment_mode` | yes | `mock`, `local`, `remote_api`, `self_hosted` 或等价值。 |
| `endpoint` | yes | endpoint ref，不得是带 credential 的 URL。 |
| `health_status` | yes | 当前健康状态。 |
| `capability_version` | yes | capability schema version。 |
| `latency_class` | yes | 延迟类别。 |
| `error_model` | yes | error taxonomy/ref。 |
| `timeout_policy` | yes | timeout policy/ref。 |
| `retry_policy` | yes | retry policy/ref。 |
| `output_mode` | yes | `real`, `mock`, `fallback`, `degraded`。 |
| `role_contract` | Fast Interaction yes; others optional empty string | Adapter role contract identifier；Fast Interaction 必须独立于 Thinker / Composer。 |
| `prompt_profile` | Fast Interaction yes; others optional empty string | Adapter prompt profile identifier；不得包含 raw prompt/provider body。 |

### Required capability fields

| Capability | Type | Required | Meaning |
| --- | --- | --- | --- |
| `supports_streaming_input` | boolean | yes | 是否消费 streaming input。 |
| `supports_streaming_output` | boolean | yes | 是否产生 streaming output。 |
| `supports_audio_input` | boolean | yes | 是否接受 audio input。 |
| `supports_audio_output` | boolean | yes | 是否输出 audio。 |
| `supports_audio_timestamps` | boolean | yes | 是否提供 timing offsets。 |
| `supports_structured_json` | boolean | yes | 是否输出可验证 structured JSON。 |
| `supports_tool_calling` | boolean | yes | 是否输出 tool-call-like structured intent；执行权仍属于 Tool Executor。 |
| `supports_cancellation` | boolean | yes | 是否支持 request/tool cancellation。 |
| `supports_emotion` | boolean | yes | 是否识别或控制 emotion。 |
| `supports_audio_caption` | boolean | yes | 是否产生 audio captions。 |
| `supports_tts` | boolean | yes | 是否合成 speech。 |
| `supports_tts_truncate` | boolean | yes | TTS/Talker 是否支持 truncate flow。 |
| `supports_tts_pause_resume` | boolean | yes | pause/resume；MVP 非必需。 |
| `supports_semantic_close` | boolean | yes | 是否能推断 semantic close。 |
| `supports_assistant_directedness` | boolean | yes | 是否能推断 assistant-directedness。 |
| `supports_fast_interaction_output` | boolean | yes | 是否能产出 ADR-017 Fast Interaction normalized output。 |
| `supports_route_hint` | boolean | yes | 是否能产出非权威 route hint evidence。 |
| `supports_route_prelude` | boolean | yes | 是否能产出给 Router / gate / replay 使用的短结构化摘要。 |
| `supports_foreground_act` | boolean | yes | 是否能产出 foreground act suggestion。 |
| `supports_reply_candidate` | boolean | yes | 是否能产出 gate 前候选前台回复。 |
| `supports_reply_delta_streaming` | boolean | yes | 是否能产出 buffered reply delta stream；gate 通过前不得展示。 |
| `supports_final_fast_evidence` | boolean | yes | 是否能产出 final fast evidence ref。 |
| `supports_schema_validation` | boolean | yes | 是否在 adapter 侧执行输出 schema/contract validation。 |
| `supports_risk_tags` | boolean | yes | 是否能产出 risk tags / risk metadata。 |
| `supports_confidence` | boolean | yes | 是否能产出 confidence metadata。 |
| `supports_asr_text_fallback` | boolean | yes | Fast Interaction 是否支持从 ASR text projection 降级输入；非 Fast Interaction adapter 必须为 `false`。 |
| `supports_provider_stream_timing` | boolean | yes | 是否能记录 provider streaming timing metadata，且只以 sanitized metadata 写入事件。 |
| `supports_ttft_observation` | boolean | yes | 是否能观察 provider time-to-first-token/chunk timing；不可用时必须显式为 `false`。 |
| `latency_class` | enum/ref | yes | development latency bucket 或 measured bucket。 |
| `max_audio_seconds` | integer/null | yes | 最大音频输入长度。 |
| `max_context_tokens` | integer/null | yes | 最大上下文长度。 |
| `max_output_tokens` | integer/null | yes | 最大输出长度。 |
| `expected_first_token_latency_ms` | integer/null | yes | 预期 first-token latency。 |
| `expected_first_audio_latency_ms` | integer/null | yes | 预期 first-audio latency。 |
| `max_reply_candidate_tokens` | integer/null | yes | Fast Interaction reply candidate 最大 token budget。 |
| `expected_first_candidate_latency_ms` | integer/null | yes | Fast Interaction first candidate 预期延迟。 |
| `expected_final_gate_ready_latency_ms` | integer/null | yes | Fast Interaction final gate-ready evidence 预期延迟。 |

Mock-specific fields:

- 被 mock 行为模拟的能力必须标 `mocked=true`。
- 使用 `mock_profile_ref` 指向 deterministic fixture behavior。
- 当 mock 缺少目标架构真实接口证据时，例如 barge-in 没有 playback reference，必须 `target_architecture_validation=false`。

### Fast Interaction live profile note

MVP6.3 live Fast Interaction profile is capability/profile metadata only. It
declares `adapter_type=fast_interaction`, `output_mode=real`, a safe provider URL
ref such as `provider-url://dashscope/openai-compatible-chat-completions`, and a
safe config ref such as `config://runtime/fast-interaction/dashscope`. It must
not include credentials, provider request/response bodies, raw prompts, raw
audio, diagnostics, traces, or local replay cache.

The initial MVP6.3 profile is audio-native live Fast Interaction. It supports
safe audio refs as primary input, ASR text only as explicit fallback, route hint,
route prelude, foreground act, reply candidate, final fast evidence, structured
JSON, schema validation, risk tags, confidence, provider stream timing metadata,
and TTFT observation. It explicitly sets
`supports_reply_delta_streaming=false`, so `supports_reply_delta_streaming` must
appear in `unsupported_capabilities`.

Example values:

| Field | MVP6.3 live Fast Interaction value |
| --- | --- |
| `adapter_id` | `mvp63_fast_interaction_runtime` |
| `adapter_type` | `fast_interaction` |
| `provider` | `dashscope_bailian` |
| `model_name` | `qwen3.5-omni-flash` |
| `deployment_mode` | `remote_api` |
| `capability_version` | `mvp6.3.fast-interaction.runtime.v1` |
| `latency_class` | `remote_api_http_audio_native_fast_interaction` |
| `role_contract` | `live_fast_interaction_audio_native_v1` |
| `prompt_profile` | `mvp6.3.fast_interaction.audio_native.v1` |
| `supports_audio_input` | `true` |
| `supports_fast_interaction_output` | `true` |
| `supports_route_hint` | `true` |
| `supports_route_prelude` | `true` |
| `supports_foreground_act` | `true` |
| `supports_reply_candidate` | `true` |
| `supports_reply_delta_streaming` | `false` |
| `supports_final_fast_evidence` | `true` |
| `supports_schema_validation` | `true` |
| `supports_risk_tags` | `true` |
| `supports_confidence` | `true` |
| `supports_asr_text_fallback` | `true` |
| `supports_provider_stream_timing` | `true` |
| `supports_ttft_observation` | `true` |
| `max_reply_candidate_tokens` | `220` |
| `expected_first_candidate_latency_ms` | `1200` |
| `expected_final_gate_ready_latency_ms` | `1600` |

## 2. Startup Capability Snapshot

Session startup 必须记录：

- `SESSION_STARTED`
- `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`

`ADAPTER_CAPABILITY_SNAPSHOT_RECORDED` 至少包含：

- `capability_snapshot_ref`
- `adapter_ids`
- `adapter_types`
- `deployment_modes`
- `output_modes`

Replay 使用 snapshot 区分 real / mock / fallback / degraded，不得在 replay 中重新 probe adapters。

## 3. Adapter Health Events

Canonical health/error/degradation events:

- `ADAPTER_HEALTHCHECK_FAILED`
- `ADAPTER_REQUEST_RETRYING`
- `ADAPTER_REQUEST_FAILED`
- `ADAPTER_OUTPUT_VALIDATION_FAILED`
- `ADAPTER_OUTPUT_DEGRADED`
- `ASR_TRANSCRIPT_OUTPUT_EMITTED`
- `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED`
- `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED`
- `TTS_SYNTHESIS_OUTPUT_EMITTED`

Frame/output events 必须携带 `output_mode=real|mock|fallback|degraded`，或引用包含该 mode 的 capability snapshot。

## 4. Adapter Error Events

| Event | Required fields |
| --- | --- |
| `ADAPTER_HEALTHCHECK_FAILED` | `adapter_id`, `adapter_type`, `health_status`, `failure_reason`, `output_mode` |
| `ADAPTER_REQUEST_RETRYING` | `adapter_id`, `adapter_type`, `adapter_request_id`, `retry_count`, `retry_reason`, optional `timeout_ms` |
| `ADAPTER_REQUEST_FAILED` | `adapter_id`, `adapter_type`, `adapter_request_id`, `failure_reason`, `retryable`, optional `timeout_ms`, `output_mode` |
| `ADAPTER_OUTPUT_VALIDATION_FAILED` | `adapter_id`, `adapter_type`, `adapter_request_id`, `schema_name`, `failure_reasons`, `output_mode` |
| `ADAPTER_OUTPUT_DEGRADED` | `adapter_id`, `adapter_type`, optional `adapter_request_id`, `degraded_reason`, optional `missing_capability`, optional `fallback_adapter_id`, `output_mode` |
| `ASR_TRANSCRIPT_OUTPUT_EMITTED` | `adapter_id`, `adapter_type=asr`, `adapter_request_id`, `turn_id`, `utterance_id`, `input_modality=audio`, `audio_span_id`, `asr_frame_ref`, `text_ref`, `transcript_finality=final`, `timestamp_status`, `streaming_status`, `output_mode=real/fallback/degraded` |
| `THINKER_SEMANTIC_FRAME_OUTPUT_EMITTED` | `adapter_id`, `adapter_type=thinker`, `adapter_request_id`, `turn_id`, `utterance_id`, `input_modality`, `semantic_frame_schema`, `normalization_status=normalized`, `semantic_frame_ref`, `semantic_summary_ref`, `semantic_close_status`, `assistant_directedness_status`, `emotion_status`, `audio_caption_status`, `output_mode=real/fallback/degraded` |
| `SLOW_LLM_STRUCTURED_OUTPUT_EMITTED` | `adapter_id`, `adapter_type=slow_llm`, `adapter_request_id`, `task_id`, `plan_version`, `task_event_seq`, `schema_name=voice_agent.slowtask.structured_output.v1`, `normalization_status=normalized`, `slow_llm_output_ref`, `structured_output_ref`, `validation_result_ref`, `output_mode=real/fallback/degraded` |
| `TTS_SYNTHESIS_OUTPUT_EMITTED` | `adapter_id`, `adapter_type=tts`, `adapter_request_id`, `spoken_plan_id`, `approved_check_event_id`, `normalization_status=normalized`, `audio_ref` or `tts_stream_ref`, `audio_format_ref`, `synthesis_result_ref`, `truncate_status=supported/unsupported_blocked`, `output_mode=real/fallback/degraded` |

任何 request body、headers、tokens、cookies、credentials、authorization headers 都不得写入 adapter events。

## 5. Timeout / Retry / Cancellation Policy

- 每个 adapter 声明 `timeout_policy` 和 `retry_policy`。
- retryable timeout/failure 记录 `ADAPTER_REQUEST_RETRYING`。
- final failure 记录 `ADAPTER_REQUEST_FAILED`。
- provider output schema validation failure 记录 `ADAPTER_OUTPUT_VALIDATION_FAILED`，下游不得静默消费 invalid output。
- TTS synthesis success output 记录 `TTS_SYNTHESIS_OUTPUT_EMITTED`，且只包含 safe normalized audio refs / metadata；safe ref 检查必须覆盖 URL-decoded refs；不得写入 raw audio bytes、provider payload 或 provider-specific schema。
- MVP-3 approved playback 必须通过 `tts_output_event_id` 或唯一 safe ref match 绑定到 prior `TTS_SYNTHESIS_OUTPUT_EMITTED`，不得播放绕过 TTS adapter contract 的 arbitrary refs。
- TTS 缺少 truncate capability 时，必须记录 `ADAPTER_OUTPUT_DEGRADED`，并以 `truncate_status=unsupported_blocked` 阻断 barge-in target validation；不得静默通过。
- adapter 支持 cancellation 时，plan advance 或 task cancel 可触发 cancel path。
- adapter 不支持 cancellation 时，不得伪造 cancel success；等待结果返回后按 stale policy 处理。

## 6. Degradation Decision Table

| 缺失 / 失败能力 | 影响模块 | Required behavior | Required event |
| --- | --- | --- | --- |
| 无 streaming ASR | ASR, Interaction chain | 使用 final transcript/text projection；标注 output mode。 | `ADAPTER_OUTPUT_DEGRADED` if streaming expected |
| 无 audio timestamps | ASR/Thinker/Duplex | 保留 event timing，标记 model timing unavailable。 | `ADAPTER_OUTPUT_DEGRADED` when timing required |
| 无 emotion | Thinker | emotion unavailable；不得默认 neutral，除非模型真的预测 neutral。 | `ADAPTER_OUTPUT_DEGRADED` when expected |
| 无 audio caption | Thinker | audio caption unavailable；保留其他 evidence。 | `ADAPTER_OUTPUT_DEGRADED` when expected |
| 无 semantic_close | Duplex/Thinker | 使用 mock/rule/conservative policy；标注 mock/degraded。 | `ADAPTER_OUTPUT_DEGRADED` or mock event |
| 无 assistant-directedness | Duplex/Thinker | 使用 assumed/unknown policy；不得静默认为 directed。 | `ADAPTER_OUTPUT_DEGRADED` when expected |
| Slow LLM 无 structured JSON | Slow LLM, SlowTask | parser/validator retry；仍失败则 fail task 或 fallback/degraded。 | validation/retry/degraded/failure events |
| 无 tool calling | Thinker/Slow LLM | 不依赖 provider-native tool calls；改用 system schema 或 block。 | `ADAPTER_OUTPUT_DEGRADED` if expected |
| 无 cancellation | Tool/Model Adapter | 不伪造成功；等待结果并按 stale policy。 | stale chain when result returns |
| 无 TTS | Talker | 仅 MVP 允许 mock TTS；标注 mock/degraded。 | degraded or mock playback events |
| 无 TTS truncate | Talker, Interaction | barge-in target validation 不能通过，必须 block/degrade。 | `ADAPTER_OUTPUT_DEGRADED` |
| 无 pause/resume | Talker | MVP 可接受；pause/resume 是 non-goal。 | none unless requested |
| context too long | Thinker/Slow LLM/Composer | approved context policy 截断/总结；否则 fail/degrade。 | degraded or failed event |
| audio exceeds max seconds | ASR/Thinker/Duplex | segment / reject / degrade；保留 span refs。 | degraded or failed event |

## 7. Capability Missing Behavior Options

Allowed behavior labels:

- `mock_fallback`
- `disable_scenario`
- `degrade_to_text_only`
- `require_confirmation`
- `block_feature`
- `record_degradation_event`

规则：

- safety-critical required capability 缺失时，应 `block_feature` 或 `disable_scenario`。
- quality-only capability 缺失时，可 `degrade_to_text_only` 或 `mock_fallback`。
- fallback/degradation 必须 replay-visible。
- mock fallback 不算 real capability validation。

## 8. Capability Profiles by MVP Slice

### MVP-0

Required:

- ASR mock capability matrix。
- Thinker mock capability matrix。
- Slow Agent mock capability matrix if present。
- TTS mock capability matrix with playback progress and truncate behavior。
- Tool mock capability matrix if stubbed。
- session startup 记录 `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`。

Not required:

- real ASR / Thinker / Slow LLM / TTS。
- real semantic_close / assistant-directedness。
- real pause/resume。

### MVP-1

Required:

- SlowTask mock / Slow Agent mock structured outputs for lifecycle、UserPatch interpretation、plan_version、stale policy、SemanticCommitment mock。
- mock vs degraded output labels。

### MVP-2

Required:

- Tool adapter/executor capability for progressive demo protocol。
- Composer role capability or template fallback。
- Coverage/truthfulness check support。

### MVP-3

Required:

- 至少一个 real/remote endpoint for ASR、Thinker、Slow LLM、TTS。
- HTTP/WebSocket healthcheck。
- timeout/retry/error events。
- Slow LLM structured JSON validation。
- TTS basic audio synthesis。
- 不新增架构能力。

Executable readiness gate:

- `validate_mvp3_adapter_profile_set` 必须在 runtime assembly 前验证 profile set。
- `assemble_runtime_adapters(stage="mvp3", ...)` 必须拒绝 mock-only profile set。
- fallback / degraded / mock profile 可以存在，但不得计入 MVP-3 required real profile。
- MVP-3 required real profile 不得使用 `provider=mock`、`deployment_mode=mock`、`mock://` endpoint、`mocked=true` 或 `mock_profile_ref`。
- MVP-3 required real profile 必须声明 `target_architecture_validation=true`。
- MVP-3 assembly gate 只构建 capability snapshot，不得 probe provider endpoint。
- Adapter callback 进入 Event Journal 前必须通过单一 append boundary 分配 `adapter_callback_seq`，不得由 callback caller 自行填写。

## 9. Validation Requirements

- MVP-0 mock capability case 验证所有 mock adapter 如实声明 matrices。
- 系统必须区分 real / mock / fallback / degraded output。
- unsupported capability 不得静默使用。
- adapter failure paths 覆盖 healthcheck failed、retrying、failed、validation failed、degraded。
- adapter events 不得写入 secrets。
- MVP-3 runtime assembly 必须验证 ASR、Thinker、Slow LLM、TTS 各自至少有一个 required real profile。
- MVP-3 runtime assembly 必须记录 `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`，且 snapshot 包含 adapter ids/types、deployment modes、output modes、capability version。
- MVP-3 adapter health/error/degradation events 必须在 canonical event registry 中可验证。

## 10. ADR-018 Post-ADR-017 / MVP6.x Slice 3B Profiles

The accepted Route Evidence Adapter uses `adapter_type=route_evidence` and
declares exactly these route/candidate-safety capability terms:

```text
supports_route_schema
supports_task_focus
supports_foreground_act_hint
supports_ack_kind
supports_candidate_safety_schema
supports_prohibited_claim_detection
supports_strict_json_validation
supports_risk_tags
supports_confidence
```

ASR profiles that perform the non-blocking native-audio shadow declare:

```text
supports_candidate_output_audio_shadow_verification
```

Qwen role/session profiles declare independently:

```text
supports_smart_turn
supports_streaming_asr
supports_provider_response_cancellation
supports_provider_item_create
supports_provider_item_delete_ack
supports_manual_response_while_idle
supports_text_only_response_override
supports_candidate_quarantine
supports_provider_native_audio_release
supports_provider_context_readiness
supports_context_rebuild
```

These profiles keep `documentation_support`,
`provider_free_test_support`, `real_live_support`, and
`status=real|mock|fallback|degraded` as separate fields. No field implies
another.

The Slice 3B.1 `ScriptedFakeQwenWire` profile is explicitly provider-free:

```text
status=mock
output_mode=mock
provider_free_test_support=true
real_live_support=false
supports_smart_turn=true
supports_streaming_asr=true
supports_candidate_quarantine=true
supports_provider_native_audio_release=false
```

The three `supports_* = true` values describe only the Fake's deterministic
protocol behavior. They do not qualify a provider, model, endpoint, account,
region, prompt/profile, latency, cancellation behavior, or native PCM. The
Slice 3B.1 runtime additionally enforces `native_pcm_enabled=false`; that is a
runtime promotion gate, not a capability-profile field.
