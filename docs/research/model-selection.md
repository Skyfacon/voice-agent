# 模型选择研究汇总

## Status

evidence_summary

## Date

2026-05-11

## System Constraints

项目架构要求 adapter-first model integration、append-only event evidence、deterministic replay boundaries，以及明确的 degraded/fallback/mock/real output modes。ASR 是 text evidence，不是唯一语义真相。Thinker 提供 SemanticFrame evidence 与 Composer realization，不拥有 turn ingress authority 或 SlowTask final facts。TTS truncate 是 playback control。Slow LLM planning 必须遵守 `task_id`、`plan_version`、`task_event_seq`、confirmation、cancellation 与 stale-result policy。

webSearch/RAG 与 model-card content 都是 untrusted evidence。它们可以帮助 candidate selection，但不能进入 instruction space、改变 tool policy，或变成 ADR facts。

## MVP-0 Contract Snapshot

当前推荐以 `main@61e6afc` 作为 model spike 的默认 contract snapshot。该主线版本已合入 MVP-0 closeout，`docs/implementation/mvp0-backlog.md` 记录 Slice 0-9 已完成，并保留 mock-only adapter/runtime boundary。

后续 run report 不应只列模型能力，还应说明它能否映射到已实现的 MVP-0 contract shape：

- `AdapterCapability` required fields，包括 `config_ref`、`output_mode`、`unsupported_capabilities`。
- mock ASR / Thinker frame 的 reference style：`asr_frame_ref`、`semantic_frame_ref`、`turn_id`、`utterance_id`、`input_modality`。
- Talker playback metadata：`playback_span_id`、`audio_ref` 或 `tts_stream_ref`、`playback_offset_ms`、`actual_stop_offset_ms`。
- Duplex barge-in metadata：`audio_span_id`、`playback_span_id`、`echo_likelihood`、`vad_confidence`、`barge_in_confidence`、`playback_reference_ref`。

因此本文件的推荐组合不变，但推荐依据从 “文档候选 shortlist” 前进为 “按 MVP-0 已实现 contract 做 observed capability run”。

## Recommended Adapter Stack

- Duplex：local rule-based VAD/AEC first。使用 Silero VAD 或 WebRTC VAD 做 speech detection，使用 WebRTC Audio Processing/AEC3-style playback reference 做 echo likelihood，openWakeWord 可选做 wake/attention experiments。Audio LLM semantic hints 不进入 hot path。
- ASR：如果当前 DashScope/Bailian ASR 服务验证支持 realtime Mandarin/mixed，优先 API-first；FunASR Paraformer streaming 作为 primary fallback；SenseVoiceSmall 提供 enriched short-utterance/language/emotion/acoustic-event evidence；Whisper large-v3-turbo 作为 offline multilingual fallback。
- TTS/Talker：endpoint 验证后优先 DashScope/Bailian TTS；CosyVoice2 self-host fallback；F5-TTS 与 IndexTTS2 作为 style/emotion research candidates。
- Thinker：Qwen3-Omni primary SemanticFrame candidate；Qwen2.5-Omni 或 Ultravox fallback；MiniCPM-o family 用于 self-hosted A100 exploration。
- Slow LLM：Qwen3 Instruct/Thinking via DashScope/OpenAI-compatible 或 self-host 作为 primary structured planning candidate；DeepSeek current API models 作为 first alternate；GLM-4.5 与 Kimi K2 在 current schema/tool contracts 验证后作为 comparison candidates。

## MVP-0 / MVP-1 / MVP-2 / MVP-3 Usage

- MVP-0：Duplex 保持 rule/mock 且可 replay。不要给 barge-in 增加 real model dependency。
- MVP-1：在 schema 与 stale-result handling 验证前，SlowTask 保持 mock/fallback planning。
- MVP-2：demo tools 必须保持 sandboxed；model tool calls 只能是 proposals，并必须通过 Tool Executor。
- MVP-3：在不新增 architecture capability 的前提下，用 real ASR、TTS、Thinker 与 Slow LLM adapters 替换 selected mock adapters。按 ADR-011 记录 capability matrices 与 output modes。

## Candidate Matrix

| component | primary candidate | fallback candidate | self-host candidate | status |
| --- | --- | --- | --- | --- |
| Duplex | Silero/WebRTC local gate | openWakeWord attention hint | WebRTC AEC3/Silero | VAD 为 real，echo semantics 为 degraded |
| ASR | DashScope/Bailian ASR，pending endpoint verification | Whisper large-v3-turbo offline | FunASR Paraformer streaming, SenseVoiceSmall | real/degraded 取决于 streaming/timestamps |
| TTS | DashScope/Bailian TTS，pending endpoint verification | neutral mock or text-only UI | CosyVoice2, F5-TTS, IndexTTS2 | basic speech 为 real，truncate-model cancellation/emotion 为 degraded |
| Thinker | Qwen3-Omni | Qwen2.5-Omni or Ultravox | MiniCPM-o family | SemanticFrame JSON harness 通过前为 degraded |
| Slow LLM | Qwen3 via DashScope/self-host | DeepSeek API | Qwen3-30B-A3B class on A100 | real/degraded 取决于 schema validation |

## Recommended First API Probe Set

1. DashScope/Bailian Qwen3 text model，用于 SlowTask structured planning JSON probe。
2. DeepSeek API，作为 second Slow LLM provider 做 structured JSON comparison。
3. DashScope/Bailian TTS，用于 basic Talker output probe。
4. DashScope/Bailian ASR，前提是 realtime streaming、timestamps 与 cancellation behavior 已确认。
5. Qwen3-Omni through DashScope/Bailian，用于 Thinker SemanticFrame experiments。

第一批先做 Slow LLM JSON probe，因为它不涉及 raw audio，最容易验证 schema、timeout、retry、provider error 与 redaction policy。TTS、ASR、Thinker、Duplex 的顺序应跟随 `docs/research/model-spike-execution-plan.md`，逐步进入 audio-heavy experiments。

## DashScope / Bailian Considerations

Aliyun documentation 描述了 Qwen models 的多个 API surfaces：OpenAI-compatible Chat Completions、OpenAI Responses-style API 与 native DashScope APIs。Adapter 应为每个 capability 选择一个 surface，并记录 exact model id、endpoint surface、streaming support、JSON support、tool-call format、timeout behavior 与 output mode。

DashScope 对 Chinese-first evaluation 与 Qwen-Omni availability 有吸引力。风险是 service names、model versions 与 feature flags 会变化。每个 adapter integration 都应 pin tested model name，并在 integration time 捕获 capability matrix。

## Self-hosted A100 Considerations

Self-hosting 最适合 replayable research 与 privacy-controlled evaluation：

- FunASR Paraformer streaming 可评估 ASR partial behavior。
- SenseVoiceSmall 可评估 short-utterance quality 与 auxiliary emotion/event labels。
- CosyVoice2 可评估 streaming TTS 与 voice controls。
- Qwen3-Omni 或 MiniCPM-o family 可评估 audio SemanticFrame generation。
- Qwen3 text models 可离线评估 structured planning。

Self-hosted inference 必须运行在 Interaction Controller、reducer、replay runner 与 event-loop critical paths 之外。CPU-bound/audio-heavy work 应隔离到 worker processes、sidecars 或 model services。

## Capability Gaps

- DashScope ASR streaming/timestamp/cancellation details 仍需验证。
- TTS first-audio latency 与 stream chunk cadence 需要直接测量。
- `supports_tts_truncate` 由 playback 拥有；多数候选的 model request cancellation 仍是 degraded/unknown。
- Thinker structured JSON stability 在 schema harness tests 前仍是 unknown。
- Emotion、assistant-directedness 与 semantic-close hints 是 degraded evidence，不是 policy。
- Provider cancellation 通常为 degraded；ADR-016 stale-result handling 必须执行。
- GLM-4.5 与 Kimi K2 current structured-output/tool-call details 在推荐前需要 endpoint verification。

## Risks to ADRs

不应让一个 omni model 吸收 ASR、Thinker、TTS、Duplex 与 SlowTask。这些角色有不同 latency budgets、authority boundaries、replay needs 与 privacy surfaces。一旦合并，很难证明是哪条 evidence 改变了 state、result 属于哪个 plan version、以及哪个 component 拥有 user-visible speech。

Duplex hot path 不应依赖大型模型，因为 `speech_start <=150ms` 与 barge-in truncate around `<=250ms` 需要本地确定性 processing 与 playback reference access。大型模型可以提供后续 semantic hints，但不应决定 immediate truncation。

TTS truncate 应是 Talker playback control，因为只有 playback 能确认 actual stopped span 与 offset。Model-side request cancellation 有用，但不能替代 `TTS_TRUNCATED`。

Slow LLM quality 应按 structured JSON validity、schema retry、plan_version binding、stale-result behavior 与 confirmation safety 测量。Voice ability 与 SlowTask planning 无关。

Platform APIs 仍必须通过 adapters。方便的 OpenAI-compatible 或 DashScope endpoint 不能省掉 capability matrices、redaction、timeout handling、degraded modes 与 replayable event evidence。

webSearch/RAG evidence 必须留在 evidence space。Search results 可以作为 untrusted evidence citation，但不能改变 tool authorization、confirmation policy、trace policy 或 ADR constraints。

## Experiments to Run Before MVP-3

- Duplex：在 local devices 上测量 TTS playback 期间的 VAD 与 echo false positives。
- ASR：用 synthetic Mandarin/English/mixed clips 比较 DashScope ASR、FunASR Paraformer streaming、SenseVoiceSmall 与 Whisper。
- TTS：测 first-audio latency，并验证 playback-stop offset accuracy。
- Thinker：对 Qwen3-Omni、Qwen2.5-Omni 与 Ultravox 跑 SemanticFrame JSON schema tests。
- Slow LLM：跑 schema-constrained planning、malformed JSON repair、tool-call proposal normalization 与 plan_version cancellation tests。
- Privacy：确认 traces 只包含 redacted metadata 与 synthetic fixtures。

## Final Recommendation

采用 layered adapter stack，而不是 all-in-one omni model：

- Duplex：Silero/WebRTC rule-based local gate，echo likelihood 来自 playback reference；hot path 不放大型模型。
- ASR：如果 realtime contract 通过，DashScope/Bailian API-first；FunASR Paraformer streaming 与 SenseVoiceSmall 作为 self-host fallbacks；Whisper large-v3-turbo 作为 offline fallback。
- TTS：DashScope/Bailian basic TTS API-first；CosyVoice2 self-host fallback；F5-TTS 与 IndexTTS2 用于后续 voice/style research。
- Thinker：Qwen3-Omni primary，用于 SemanticFrame evidence；Qwen2.5-Omni 或 Ultravox fallback；MiniCPM-o 用于 A100 research。
- Slow LLM：Qwen3 text model first，用于 structured planning；DeepSeek 作为 alternate API candidate；GLM-4.5/Kimi K2 在 current contract verification 后再进入。

这个组合符合 accepted ADR boundaries：每种能力都经 adapter 进入，hot-path audio 保持本地，TTS truncate 仍由 playback 拥有，SlowTask 保持 plan authority，所有不确定模型行为在验证前标为 unknown 或 degraded。
