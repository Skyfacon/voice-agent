# TTS 能力探针

## Status

evidence_report

## Date

2026-05-09

## Scope

本文评估 TTS / Talker 候选在 MVP-3 basic speech output、streaming audio、first-audio latency、voice/emotion controls 与 truncate behavior 上的适配性。本文不引入 runtime adapter。

## Architecture Role

TTS 为 Talker/playback layer 生成音频。模型可以 stream generated audio，但 playback control 仍是 Talker 责任。根据 ADR-003，只有 playback layer 确认实际 truncation 并记录 stopped span/offset 后，`TTS_TRUNCATED` 才有效。

## ADR Constraints

- ADR-003：`TTS_TRUNCATE_REQUESTED` 来自 Interaction Controller policy；`TTS_TRUNCATED` 由 Talker/playback path 在 stop 生效后发出。
- ADR-009：Thinker-as-Composer 可以塑造 spoken realization，但不能改写 immutable facts 或 required fields。
- ADR-011：TTS provider 使用必须经 model adapter capability contract。
- ADR-012：MVP-3 可以用 real TTS 替换 mock TTS，但不新增 pause/resume 或更大 architecture scope。
- AGENTS.md：raw audio、secret、local debug trace 不得进入提交。

## Candidate Shortlist

- DashScope / Bailian Sambert 或 current TTS services：API-first basic TTS candidate；exact current model、streaming 与 voice controls 需要 integration 前验证。
- CosyVoice2 / CosyVoice：self-host fallback 与 advanced streaming candidate；官方项目强调 streaming、multilingual、voice cloning、instruct controls 与更新的 bi-streaming work。
- F5-TTS：quality-oriented self-host fallback，用于 voice cloning 与 offline generation；作为低延迟 MVP streaming Talker 不如 CosyVoice 清晰。
- IndexTTS2：emotion 与 duration control 的强 R&D candidate；licensing 与 operational fit 需要 review。
- Chatterbox TTS：仅列为 follow-up，因为本轮 official source verification 不足。

## Official Sources Checked

- CosyVoice GitHub: https://github.com/FunAudioLLM/CosyVoice
- F5-TTS GitHub: https://github.com/SWivid/F5-TTS
- IndexTTS GitHub: https://github.com/index-tts/index-tts
- Aliyun Sambert speech synthesis documentation: https://help.aliyun.com/zh/model-studio/sambert-speech-synthesis/
- Aliyun Model Studio / DashScope entry point: https://help.aliyun.com/zh/model-studio/

## Capability Matrix Assessment

| field | DashScope TTS candidate | CosyVoice2 | F5-TTS | IndexTTS2 | Chatterbox TTS |
| --- | --- | --- | --- | --- | --- |
| adapter_type | tts | tts | tts | tts | tts |
| provider | Alibaba Cloud / DashScope | FunAudioLLM | SWivid | IndexTeam | ResembleAI_or_unknown |
| model_name | sambert_or_current_tts_unknown | CosyVoice2-0.5B | F5-TTS-v1 | IndexTTS2 | unknown |
| deployment_mode | api | self_hosted | self_hosted | self_hosted | unknown |
| supports_streaming_input | unknown | degraded | unsupported | unknown | unknown |
| supports_streaming_output | unknown | real | degraded | unknown | unknown |
| supports_audio_input | unsupported | real | real | real | unknown |
| supports_audio_output | real | real | real | real | unknown |
| supports_audio_timestamps | unknown | unknown | unknown | unknown | unknown |
| supports_structured_json | unsupported | unsupported | unsupported | unsupported | unknown |
| supports_tool_calling | unsupported | unsupported | unsupported | unsupported | unknown |
| supports_cancellation | unknown | degraded | degraded | degraded | unknown |
| supports_emotion | unknown | degraded | degraded | real | unknown |
| supports_audio_caption | unsupported | unsupported | unsupported | unsupported | unknown |
| supports_tts | real | real | real | real | unknown |
| supports_tts_truncate | degraded | degraded | degraded | degraded | unknown |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported | unknown |
| supports_semantic_close | unsupported | unsupported | unsupported | unsupported | unsupported |
| supports_assistant_directedness | unsupported | unsupported | unsupported | unsupported | unsupported |
| max_audio_seconds | unknown | unknown | unknown | unknown | unknown |
| max_context_tokens | not_applicable | not_applicable | not_applicable | not_applicable | unknown |
| max_output_tokens | not_applicable | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_token_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_audio_latency_ms | unknown | degraded_around_150ms_claim_for_newer_bistreaming_path | degraded_benchmark_dependent | unknown | unknown |
| output_mode | real_or_unknown | fallback | fallback | degraded | unknown |
| degradation_notes | verify current endpoint, streaming, and voice controls | promising self-host path；truncate 仍由 playback 拥有 | good quality baseline；streaming/live controls 较弱 | emotion/duration R&D，不作为 basic MVP first pick | source 未充分验证，不推荐 |

## Candidate Comparison

如果 current TTS services 提供稳定 streaming 与可预期 operational controls，DashScope/Bailian 是最佳 API-first 方向。CosyVoice2 是最强 self-host candidate，因为官方项目强调 multilingual speech generation、streaming deployment 与 voice/style controls。F5-TTS 适合 quality 与 voice-cloning experiments，但与 low-latency MVP playback 的对齐不如 CosyVoice 清晰。IndexTTS2 对 emotional expression 与 duration control 很有吸引力，但在 licensing、runtime 与 API semantics 明确前应保持 research/degraded candidate。

## Recommended MVP Usage

MVP-3 使用 basic TTS adapter：

- API-first：DashScope/Bailian TTS，前提是 exact endpoint 与 streaming behavior 已验证。
- Self-host fallback：CosyVoice2。
- R&D：F5-TTS 与 IndexTTS2，用于 style、emotion、voice cloning 与 duration experiments。

不要把 `supports_tts_truncate` 定义为 model-native capability。在本架构中，它表示 adapter/Talker integration 能在 `TTS_TRUNCATE_REQUESTED` 后停止当前播放的 audio span，并带 actual stop offset 发出 `TTS_TRUNCATED`。如果 model generation request 也能关闭，那只是优化，不是事实来源。

Pause/resume 在 MVP 中应保持 unsupported，因为 ADR-003 把 truncate 定义为 required MVP behavior。

## API / Deployment Notes

API TTS adapter 应区分 generation request state 与 playback state。Self-host TTS 应运行在 event loop 之外，并把 PCM/encoded chunks stream 到带 span id 的 playback queue。Voice cloning inputs 很敏感，除非 synthetic 且明确批准，不应持久化。

## Latency and Resource Notes

CosyVoice 官方材料提到 streaming 与较新的 low-latency bi-streaming path，但必须在目标硬件上测量。F5-TTS 官方 benchmark 显示在 GPU-like hardware 上 real-time factor 较好，但 first-audio behavior 取决于 serving path。DashScope first-audio latency、chunk size 与 voice availability 必须通过实际 endpoint 测量。

## Schema / Structured Output Notes

TTS input 应显式包含 text、voice id、speaking style、output format、sample rate 与来自 Composer checks 的 commitment coverage metadata。TTS output 应报告 audio span id、output mode、provider/model 与 playback offsets。TTS 不应接收 instruction-like web evidence，也不应修改 SemanticCommitment facts。

## Cancellation / Timeout / Retry Notes

如果 provider cancellation 不可用，只要 local playback stop 后发出 `TTS_TRUNCATED`，仍满足 truncate contract。必要时 generation 可以在 discarded background stream 中完成，但 output 不得重新进入 playback。Timeout 应降级为 silence 或 short local fallback prompt，而不是阻塞 Interaction Controller。

## Trace and Privacy Notes

Trace 只应在安全时保存 text、voice id、provider metadata、span ids 与 playback offsets。不要在 repo fixture 中保存 generated raw audio。不要记录 voice-clone reference audio、token、authorization header 或未脱敏用户内容。

## Degradation Proposal

- 如果 streaming TTS 不可用，使用 sentence-level chunked generation，并标记 first-audio latency degraded。
- 如果 emotion/voice controls 不稳定，使用 neutral voice，并标记 emotion unsupported/degraded。
- 如果 model request cancellation 不可用，停止 local playback 并丢弃 late chunks。
- 如果 provider failure，fallback 到 mock TTS 或 text-only UI state for replay。

## Risks

- 混淆 provider cancellation 与 playback truncation 会违反 ADR-003。
- Voice cloning 与 reference audio 带来 privacy risk。
- 如果 Composer coverage checks 弱，emotion controls 可能改变事实强调。
- API voice availability 与 model names 会变化。
- Long synthesis request 如果未隔离，可能阻塞 control plane。

## Suggested Follow-up Experiments

- 测量 DashScope TTS 与 CosyVoice2 的 first-audio latency 与 chunk cadence。
- 验证 `TTS_TRUNCATED` offset accuracy during playback stop。
- 对 neutral Mandarin、English 与 mixed text 做候选质量比较。
- 用固定 `must_say_fields` 测 emotional controls，确保 facts 不变。
- 测 generation 被取消或 network stream mid-synthesis 关闭时的 behavior。

## Recommendation

DashScope/Bailian TTS 是 endpoint 验证后的第一 API candidate；CosyVoice2 是 self-host fallback。truncate 必须作为 Talker playback control；pause/resume 在 MVP 保持 unsupported；emotion/style controls 在 coverage checks 证明安全前标记 degraded。
