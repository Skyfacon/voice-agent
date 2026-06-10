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
| `latency_class` | enum/ref | yes | development latency bucket 或 measured bucket。 |
| `max_audio_seconds` | integer/null | yes | 最大音频输入长度。 |
| `max_context_tokens` | integer/null | yes | 最大上下文长度。 |
| `max_output_tokens` | integer/null | yes | 最大输出长度。 |
| `expected_first_token_latency_ms` | integer/null | yes | 预期 first-token latency。 |
| `expected_first_audio_latency_ms` | integer/null | yes | 预期 first-audio latency。 |

Mock-specific fields:

- 被 mock 行为模拟的能力必须标 `mocked=true`。
- 使用 `mock_profile_ref` 指向 deterministic fixture behavior。
- 当 mock 缺少目标架构真实接口证据时，例如 barge-in 没有 playback reference，必须 `target_architecture_validation=false`。

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
