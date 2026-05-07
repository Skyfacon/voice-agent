# ADR-011 Model Adapter Capability Contract

## Status

accepted

## Context

开发模式会经历多个阶段：

- MVP-0: ASR mock、Thinker mock、Slow Agent mock、TTS mock、Tool mock
- API Integration Phase: ASR / Thinker / Slow LLM / TTS 通过 HTTP/WebSocket API 访问
- A100 self-hosted Phase: 部分模型服务切换到自部署 endpoint
- GLM5.1 等模型仍可能通过远程接口调用

如果没有统一 adapter 和 capability contract，系统很容易在 mock 阶段假设了真实模型不支持的能力，例如流式音频理解、结构化 JSON、取消、音频时间戳、情绪识别、audio caption、TTS pause/resume。这样会导致 MVP 能跑，但接真实模型后架构边界崩掉。

## Decision

所有模型服务必须通过 adapter 访问。业务模块不得直接调用外部模型 endpoint。

每个 adapter 在启动 / healthcheck 时必须声明 capability matrix。系统根据 capability matrix 决定启用、降级或 mock 某些能力。

适用 adapter 类型：

- ASR Adapter
- Thinker / LALM Adapter
- Thinker-as-Composer Adapter
- Slow LLM Adapter
- TTS / Talker Adapter
- Duplex model Adapter if applicable
- Embedding / RAG Adapter if applicable
- Mock Adapter

每个 adapter 至少声明：

- `adapter_id`
- `adapter_type`
- `provider`
- `model_name`
- `deployment_mode`
- `endpoint`
- `health_status`
- `capability_version`
- `latency_class`
- `error_model`
- `timeout_policy`
- `retry_policy`

Capability matrix 至少包含：

- `supports_streaming_input`
- `supports_streaming_output`
- `supports_audio_input`
- `supports_audio_output`
- `supports_audio_timestamps`
- `supports_structured_json`
- `supports_tool_calling`
- `supports_cancellation`
- `supports_emotion`
- `supports_audio_caption`
- `supports_tts`
- `supports_tts_truncate`
- `supports_tts_pause_resume`
- `supports_semantic_close`
- `supports_assistant_directedness`
- `max_audio_seconds`
- `max_context_tokens`
- `max_output_tokens`
- `expected_first_token_latency_ms`
- `expected_first_audio_latency_ms`

MVP-0 capability expectations：

- ASR mock
- Thinker mock
- Slow Agent mock
- TTS mock
- Tool mock
- All mocks must still declare capabilities honestly.
- Mock 不得伪装成目标架构真实能力，除非字段标记为 `mocked=true`。

API Integration Phase must-have：

- ASR final transcript or equivalent text projection
- Slow LLM structured JSON output
- TTS basic audio synthesis
- HTTP/WebSocket adapter healthcheck
- timeout / retry / error reporting
- Thinker basic SemanticFrame output or mock-compatible equivalent
- Thinker-as-Composer SpokenPlan output or fallback template composer

API Integration Phase nice-to-have / can mock：

- streaming audio understanding
- token-level or frame-level partial semantic output
- emotion detection
- audio_caption
- semantic_close
- assistant-directedness
- model-side cancellation
- pause/resume TTS
- exact timestamps from model

Adapter behavior rules：

1. Modules depend on adapter interfaces, not provider-specific APIs.
2. Adapter must normalize provider output into system schema.
3. Adapter must expose unsupported capabilities explicitly.
4. If a required capability is unavailable, system must either degrade or fail fast with clear event.
5. Adapter errors must be converted into ADR-002 canonical structured events.
6. Model output that fails schema validation must not silently pass downstream.
7. Timeouts and retries must be visible in event journal.
8. Adapter must not log secrets in trace.
9. Adapter must identify whether an output is real, mock, fallback, or degraded.

Adapter event contract:

- Adapter registry / session startup records `ADAPTER_CAPABILITY_SNAPSHOT_RECORDED`.
- Healthcheck failure records `ADAPTER_HEALTHCHECK_FAILED`.
- Retryable timeout or provider failure records `ADAPTER_REQUEST_RETRYING`.
- Final request failure records `ADAPTER_REQUEST_FAILED`.
- Invalid provider output records `ADAPTER_OUTPUT_VALIDATION_FAILED`.
- Fallback, mock substitution, or unsupported capability degradation records `ADAPTER_OUTPUT_DEGRADED`.
- Adapter output events and frame events must carry `output_mode=real|mock|fallback|degraded` or an equivalent referenced capability snapshot.

Degradation examples：

- No streaming ASR: use final transcript only.
- No audio timestamps: omit exact timing and mark timestamp source unavailable.
- No emotion: set emotion unavailable, not neutral unless model truly predicts neutral.
- No semantic_close: rely on Duplex mock/rule-based or Interaction policy.
- No TTS truncate: MVP barge-in validation cannot pass target architecture criteria.
- No structured JSON from Slow LLM: use parser/validator retry; if still invalid, fail task or fallback mock.

## Alternatives Considered

1. Directly call each model service where needed.
   Fast initially, but provider-specific behavior leaks everywhere.

2. Define one generic LLM adapter for all models.
   Too coarse; ASR、Thinker、Composer、Slow LLM、TTS 的能力和 latency contract 不同。

3. Mock 阶段先不管 capabilities，真实模型接入时再补。
   会让 mock 建立错误假设，后续改动大。

4. 把 unsupported capability 当作默认 false，不记录事件。
   容易静默降级，debug 困难。

## Consequences

正向结果：

- mock、API、自部署阶段使用同一架构边界。
- 能力缺失会显式暴露，不会静默破坏设计。
- 真实模型接入时可以逐项替换。
- trace/replay 能解释某次输出来自真实模型、mock 还是 degraded fallback。
- MVP 不会误以为自己已经验证了真实流式能力。

代价：

- adapter schema 和 healthcheck 初期工作量增加。
- 每个模块需要处理 degraded / unavailable 状态。
- 某些 demo 能力可能被明确标为 mock，不能算目标架构验证通过。
- structured output validation 需要额外机制。

## Impacted Modules

- ASR Adapter
- Thinker / LALM Adapter
- Thinker-as-Composer Adapter
- Slow LLM Adapter
- TTS / Talker Adapter
- Duplex
- Router
- SlowTask
- Composer Contract
- Tool Executor
- Event Journal
- Trace / Replay
- Config / Environment
- Evaluation Harness

## Validation Method

MVP-0 / API Integration Phase 必须验证：

1. 每个 mock adapter 启动时声明 capability matrix。
2. 系统能区分 real / mock / fallback / degraded output。
3. 不支持的 capability 不会被静默使用。
4. adapter healthcheck 失败会产生 `ADAPTER_HEALTHCHECK_FAILED`。
5. ASR adapter 至少能返回 final transcript 或 mock transcript。
6. Slow LLM adapter structured JSON 输出失败时会触发 `ADAPTER_OUTPUT_VALIDATION_FAILED`。
7. TTS adapter 不支持 truncate 时，barge-in target validation 失败或产生 `ADAPTER_OUTPUT_DEGRADED`。
8. timeout / retry / error 必须以 `ADAPTER_REQUEST_RETRYING` / `ADAPTER_REQUEST_FAILED` 进入 event journal。
9. adapter 不会把 secret 写入 trace。
10. API endpoint 可配置，支持本地 mock、远程 API、自部署 endpoint 切换。

## Open Questions

- capability matrix 是静态配置、启动探测，还是两者结合？
- adapter capability 是否需要暴露给前端 demo，用于显示当前能力模式？
- structured JSON validation failure 是否允许自动 retry 几次？
- Thinker-as-Fast-System 和 Thinker-as-Composer 是否共用 adapter，但使用不同 method/profile？
- latency_class 是否先用枚举，还是直接记录 measured latency histogram？
- self-hosted A100 阶段是否需要 adapter compatibility test suite？
