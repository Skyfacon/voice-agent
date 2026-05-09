# TTS Capability Spike

## Status

evidence_report

## Date

2026-05-09

## Scope

This report evaluates TTS / Talker candidates for MVP-3 basic speech output, streaming audio, first-audio latency, voice and emotion controls, and truncate behavior. It does not introduce a runtime adapter.

## Architecture Role

TTS produces audio for the Talker/playback layer. The model may stream generated audio, but playback control remains a Talker responsibility. Per ADR-003, `TTS_TRUNCATED` is only valid when the playback layer confirms actual truncation and records the stopped span/offset.

## ADR Constraints

- ADR-003: `TTS_TRUNCATE_REQUESTED` comes from Interaction Controller policy; `TTS_TRUNCATED` is emitted by the Talker/playback path after stop is effective.
- ADR-009: Thinker-as-Composer may shape spoken realization, but cannot rewrite immutable facts or required fields.
- ADR-011: TTS provider use must go through a model adapter capability contract.
- ADR-012: MVP-3 can replace mock TTS with real TTS without adding pause/resume or broader architecture scope.
- AGENTS.md: no raw audio, secrets, or local debug traces may be committed.

## Candidate Shortlist

- DashScope / Bailian Sambert or current TTS services: API-first basic TTS candidate; exact current model, streaming, and voice controls should be verified before integration.
- CosyVoice2 / CosyVoice: self-host fallback and advanced streaming candidate; official project notes streaming, multilingual, voice cloning, instruct controls, and newer bi-streaming work.
- F5-TTS: quality-oriented self-host fallback for voice cloning and offline generation; less obvious as a low-latency MVP streaming Talker.
- IndexTTS2: strong R&D candidate for emotion and duration control; licensing and operational fit require review.
- Chatterbox TTS: mentioned for follow-up only because official source verification was inconclusive in this pass.

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
| degradation_notes | verify current endpoint, streaming, and voice controls | promising self-host path; truncate still playback-owned | good quality baseline; streaming/live controls weaker | emotion/duration R&D, not basic MVP first pick | source not verified enough for recommendation |

## Candidate Comparison

DashScope/Bailian is the best API-first direction if current TTS services provide stable streaming and predictable operational controls. CosyVoice2 is the strongest self-host candidate because the official project emphasizes multilingual speech generation, streaming deployment, and voice/style controls. F5-TTS is useful for quality and voice-cloning experiments, but it is less clearly aligned with low-latency MVP playback. IndexTTS2 is attractive for emotional expression and duration control, but it should remain a research/degraded candidate until licensing, runtime, and API semantics are settled.

## Recommended MVP Usage

Use a basic TTS adapter for MVP-3:

- API-first: DashScope/Bailian TTS once exact endpoint and streaming behavior are verified.
- Self-host fallback: CosyVoice2.
- R&D: F5-TTS and IndexTTS2 for style, emotion, voice cloning, and duration experiments.

Do not define `supports_tts_truncate` as a model-native capability. For this architecture, it means the adapter/Talker integration can stop the currently playing audio span on `TTS_TRUNCATE_REQUESTED` and emit `TTS_TRUNCATED` with the actual stop offset. If the model generation request can also be closed, that is an optimization, not the source of truth.

Pause/resume should remain unsupported for MVP because ADR-003 marks truncate as the required MVP behavior.

## API / Deployment Notes

API TTS adapters should separate generation request state from playback state. Self-host TTS should run outside the event loop and stream PCM/encoded chunks into a playback queue with span ids. Voice cloning inputs are sensitive and should not be persisted unless synthetic and explicitly approved.

## Latency and Resource Notes

CosyVoice official materials mention streaming and newer low-latency bi-streaming paths, but target hardware must be measured. F5-TTS official benchmarks show good real-time factor on GPU-like hardware, but first-audio behavior depends on serving path. DashScope first-audio latency, chunk size, and voice availability must be measured through the actual endpoint.

## Schema / Structured Output Notes

TTS inputs should be explicit: text, voice id, speaking style, output format, sample rate, and commitment coverage metadata from Composer checks. TTS output should report audio span id, output mode, provider/model, and playback offsets. TTS should not accept instruction-like web evidence or modify SemanticCommitment facts.

## Cancellation / Timeout / Retry Notes

If provider cancellation is unavailable, local playback stop still satisfies truncate once `TTS_TRUNCATED` is emitted. Generation can be allowed to finish in a discarded background stream if necessary, but its output must not re-enter playback. Timeouts should degrade to silence or a short local fallback prompt, not block the Interaction Controller.

## Trace and Privacy Notes

Trace should store text, voice id, provider metadata, span ids, and playback offsets only when safe. Do not store generated raw audio in repository fixtures. Do not log voice-clone reference audio, tokens, authorization headers, or unredacted user content.

## Degradation Proposal

- If streaming TTS is unavailable, use chunked sentence-level generation and mark first-audio latency degraded.
- If emotion/voice controls are unstable, use a neutral voice and mark emotion unsupported/degraded.
- If model request cancellation is unavailable, stop local playback and discard late chunks.
- If provider fails, fall back to mock TTS or text-only UI state for replay.

## Risks

- Confusing provider cancellation with playback truncation would violate ADR-003.
- Voice cloning and reference audio create privacy risk.
- Emotion controls can alter factual emphasis if Composer coverage checks are weak.
- API voice availability and model names can shift over time.
- Long synthesis requests can block if not isolated from the control plane.

## Suggested Follow-up Experiments

- Measure first-audio latency and chunk cadence for DashScope TTS and CosyVoice2.
- Verify `TTS_TRUNCATED` offset accuracy during playback stop.
- Compare neutral Mandarin, English, and mixed text quality across candidates.
- Test emotional controls against fixed `must_say_fields` to ensure facts are not changed.
- Measure behavior when generation is cancelled or network stream closes mid-synthesis.

## Recommendation

Use DashScope/Bailian TTS as the first API candidate after endpoint verification and CosyVoice2 as the self-host fallback. Treat truncate as Talker playback control, keep pause/resume unsupported for MVP, and mark emotion/style controls degraded until coverage checks prove safe.
