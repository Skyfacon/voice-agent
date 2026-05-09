# ASR Capability Spike

## Status

evidence_report

## Date

2026-05-09

## Scope

This report evaluates ASR candidates for Chinese, English, mixed short utterances, noise, timestamps, and streaming behavior. It treats ASR as text projection evidence, not the sole semantic truth.

## Architecture Role

ASR converts audio into textual evidence for the Interaction Controller, Thinker, and SlowTask evidence flow. Per ADR-008, ASR output is one projection of the user utterance; Thinker audio evidence and SlowTask conflict resolution can override or qualify it. ASR must not commit turn ingress or final task facts.

## ADR Constraints

- ADR-008: ASR text is evidence and must be fused with Thinker evidence under SlowTask-led conflict resolution.
- ADR-011: real ASR must be behind an adapter with a capability matrix and clear `real`, `fallback`, `degraded`, or `mock` output mode.
- ADR-012: MVP-3 may replace mock ASR with a real adapter but must not add new architecture capability.
- ADR-016: late ASR evidence attached to old task/plan metadata cannot advance the current task unless explicitly adopted or rebased.
- AGENTS.md: no raw audio, secrets, or local trace artifacts may be committed.

## Candidate Shortlist

- DashScope / Bailian ASR service candidate: API-first option for Chinese production-style evaluation; exact current ASR model and streaming contract need final integration verification in the platform console/docs.
- FunASR Paraformer streaming: self-host candidate for Mandarin and mixed command ASR with streaming pipeline support.
- SenseVoiceSmall / FunAudioLLM: strong self-host candidate for multilingual speech recognition plus language, emotion, and acoustic event labels; timestamp support is available through the official alignment path, while true streaming should be treated as degraded until tested.
- Whisper large-v3-turbo: robust multilingual fallback with timestamp support, but not a low-latency streaming-first adapter by default.

## Official Sources Checked

- FunASR GitHub: https://github.com/alibaba-damo-academy/FunASR
- SenseVoice GitHub: https://github.com/FunAudioLLM/SenseVoice
- Whisper large-v3-turbo model card: https://huggingface.co/openai/whisper-large-v3-turbo
- OpenAI Whisper GitHub: https://github.com/openai/whisper
- Aliyun Model Studio / DashScope model documentation entry point: https://help.aliyun.com/zh/model-studio/

## Capability Matrix Assessment

| field | DashScope ASR candidate | FunASR Paraformer streaming | SenseVoiceSmall | Whisper large-v3-turbo |
| --- | --- | --- | --- | --- |
| adapter_type | asr | asr | asr | asr |
| provider | Alibaba Cloud / DashScope | FunASR | FunAudioLLM | OpenAI |
| model_name | unknown_current_asr_service | paraformer-zh-streaming | SenseVoiceSmall | whisper-large-v3-turbo |
| deployment_mode | api | self_hosted | self_hosted | self_hosted_or_api_wrapped |
| supports_streaming_input | unknown | real | degraded | unsupported |
| supports_streaming_output | unknown | real | degraded | unsupported |
| supports_audio_input | real | real | real | real |
| supports_audio_output | unsupported | unsupported | unsupported | unsupported |
| supports_audio_timestamps | unknown | degraded | real | real |
| supports_structured_json | degraded | degraded | degraded | degraded |
| supports_tool_calling | unsupported | unsupported | unsupported | unsupported |
| supports_cancellation | unknown | degraded | degraded | degraded |
| supports_emotion | unknown | unsupported | real | unsupported |
| supports_audio_caption | unsupported | unsupported | degraded | unsupported |
| supports_tts | unsupported | unsupported | unsupported | unsupported |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | unsupported | unsupported | unsupported | unsupported |
| supports_assistant_directedness | unsupported | unsupported | unsupported | unsupported |
| max_audio_seconds | unknown | streaming_window | 30s_direct_or_vad_wrapped | unknown |
| max_context_tokens | not_applicable | not_applicable | not_applicable | not_applicable |
| max_output_tokens | not_applicable | not_applicable | not_applicable | not_applicable |
| expected_first_token_latency_ms | unknown | degraded_600ms_display_granularity_example | unknown | unknown |
| expected_first_audio_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable |
| output_mode | real_or_unknown | real | fallback | fallback |
| degradation_notes | verify exact model, timestamps, cancellation, and streaming before MVP-3 | streaming is promising; timestamp detail may need non-streaming or post alignment | rich labels, but true streaming adapter likely chunked/degraded | good fallback; not ideal for live partials |

## Candidate Comparison

FunASR Paraformer is the clearest self-host streaming ASR candidate because official examples include streaming chunk behavior and Mandarin-oriented pipelines. SenseVoiceSmall is attractive for short Chinese and mixed speech because it adds language, emotion, and acoustic event evidence; however, its direct inference duration and streaming semantics require careful adapter design. Whisper large-v3-turbo remains a strong multilingual fallback and benchmark baseline, but its usual deployment shape is offline/chunked.

DashScope/Bailian should be evaluated first for API-first MVP-3 if the current service exposes stable realtime input, partial output, timestamps, and operational controls. The exact service contract should be confirmed at integration time and recorded in the adapter capability matrix.

## Recommended MVP Usage

For MVP-3, prefer an API-first ASR adapter if DashScope/Bailian provides a stable realtime ASR endpoint for Mandarin and mixed speech. Keep FunASR Paraformer streaming as the self-host fallback. Use SenseVoiceSmall as a second self-host path for rich labels and short-utterance quality. Use Whisper large-v3-turbo as an offline multilingual fallback and regression benchmark.

ASR should never be treated as the only semantic truth. Its transcript should be labeled as evidence and fused with audio SemanticFrame evidence.

## API / Deployment Notes

API candidates should expose adapter-level fields for provider, model, request id, streaming mode, timestamp mode, and output mode. Self-host FunASR/SenseVoice adapters should isolate model inference from the event loop and Interaction Controller. GPU and CPU deployments must report degraded output if chunking, timestamps, or cancellation are weaker than the nominal capability.

## Latency and Resource Notes

FunASR streaming examples describe chunked online recognition with display granularity and lookahead; this is plausible for partial transcript evidence but not a sub-150 ms barge-in signal. SenseVoice reports very fast short-audio inference in official materials, but that should be measured on the target hardware. Whisper large-v3-turbo is expected to be heavier and should be treated as fallback for live command loops unless a dedicated streaming wrapper proves otherwise.

## Schema / Structured Output Notes

ASR output should be normalized by the adapter, not trusted as model-native schema. Minimal fields should include transcript text, language, confidence when available, segment timestamps when available, partial/final flag, provider metadata, and output mode. Emotion and acoustic event labels from SenseVoice should be separate evidence fields, not merged into transcript text.

## Cancellation / Timeout / Retry Notes

When provider-side cancellation is unavailable or unverified, adapter cancellation means local stream close and stale-result handling. Late partial/final transcripts must remain bound to utterance id, task id where applicable, plan version where applicable, and event sequence context. Old results enter stale evidence unless SlowTask explicitly adopts or rebases them.

## Trace and Privacy Notes

Do not persist raw audio or unredacted user speech in repository fixtures. Research fixtures should be synthetic or redacted and may store transcript snippets only when safe. API request ids are acceptable if they do not contain secrets. Authorization headers, cookies, and provider tokens must never enter trace.

## Degradation Proposal

- Missing streaming: use final transcript only and mark partial transcript unsupported.
- Missing timestamps: set timestamp mode `unknown` and avoid timestamp-dependent replay assertions.
- Missing cancellation: close local stream and rely on stale evidence policy.
- Noisy or low-confidence transcript: pass it as evidence with confidence notes and allow Thinker/SlowTask conflict resolution.

## Risks

- Streaming partials may be unstable in mixed Chinese/English.
- Timestamp precision may differ across providers and self-host models.
- Rich labels from SenseVoice can be useful but may tempt semantic overreach.
- API terms, model availability, and current endpoint names can change.
- Raw speech privacy risk is high if debug traces capture audio or full transcripts.

## Suggested Follow-up Experiments

- Benchmark Mandarin, English, mixed, numerals, names, and short corrections.
- Compare partial-final churn between DashScope ASR and FunASR streaming.
- Measure timestamp drift on synthetic clips with known word boundaries.
- Evaluate cancellation by interrupting streams mid-utterance and verifying stale handling.
- Run SenseVoice labels against noisy command clips and compare with Thinker evidence.

## Recommendation

Make ASR an adapter-normalized evidence source. Use DashScope/Bailian ASR as the first API integration candidate once its exact realtime contract is verified, with FunASR Paraformer streaming as the primary self-host fallback, SenseVoiceSmall for enriched short-utterance evidence, and Whisper large-v3-turbo as a robust offline fallback.
