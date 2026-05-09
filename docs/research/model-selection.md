# Model Selection Research Summary

## Status

evidence_summary

## Date

2026-05-09

## System Constraints

The project architecture requires adapter-first model integration, append-only event evidence, deterministic replay boundaries, and explicit degraded/fallback/mock/real output modes. ASR is text evidence, not the only semantic truth. Thinker provides SemanticFrame evidence and Composer realization, not turn ingress authority or SlowTask final facts. TTS truncate is playback control. Slow LLM planning must obey `task_id`, `plan_version`, `task_event_seq`, confirmation, cancellation, and stale-result policy.

webSearch/RAG and model-card content are untrusted evidence. They can inform candidate selection, but they cannot enter instruction space, alter tool policy, or become ADR facts.

## Recommended Adapter Stack

- Duplex: local rule-based VAD/AEC first. Use Silero VAD or WebRTC VAD for speech detection, WebRTC Audio Processing/AEC3-style playback reference for echo likelihood, and optional openWakeWord for wake/attention experiments. Keep audio LLM semantic hints out of the hot path.
- ASR: API-first DashScope/Bailian ASR if the current service verifies realtime Mandarin/mixed support; self-host FunASR Paraformer streaming as primary fallback; SenseVoiceSmall for enriched short-utterance/language/emotion/acoustic-event evidence; Whisper large-v3-turbo as offline multilingual fallback.
- TTS/Talker: API-first DashScope/Bailian TTS after endpoint verification; self-host CosyVoice2 fallback; F5-TTS and IndexTTS2 as style/emotion research candidates.
- Thinker: Qwen3-Omni primary SemanticFrame candidate; Qwen2.5-Omni or Ultravox fallback; MiniCPM-o family for self-hosted A100 exploration.
- Slow LLM: Qwen3 Instruct/Thinking via DashScope/OpenAI-compatible or self-host as primary structured planning candidate; DeepSeek current API models as first alternate; GLM-4.5 and Kimi K2 as comparison candidates after current schema/tool contracts are verified.

## MVP-0 / MVP-1 / MVP-2 / MVP-3 Usage

- MVP-0: keep Duplex rule/mock and replayable. Do not add real model dependency to barge-in.
- MVP-1: keep SlowTask mock/fallback planning until schema and stale-result handling are verified.
- MVP-2: demo tools must remain sandboxed; model tool calls are proposals only and must pass through Tool Executor.
- MVP-3: replace selected mock adapters with real ASR, TTS, Thinker, and Slow LLM adapters without adding new architecture capability. Record capability matrices and output modes per ADR-011.

## Candidate Matrix

| component | primary candidate | fallback candidate | self-host candidate | status |
| --- | --- | --- | --- | --- |
| Duplex | Silero/WebRTC local gate | openWakeWord attention hint | WebRTC AEC3/Silero | real for VAD, degraded for echo semantics |
| ASR | DashScope/Bailian ASR, pending endpoint verification | Whisper large-v3-turbo offline | FunASR Paraformer streaming, SenseVoiceSmall | real/degraded depending on streaming/timestamps |
| TTS | DashScope/Bailian TTS, pending endpoint verification | neutral mock or text-only UI | CosyVoice2, F5-TTS, IndexTTS2 | real for basic speech, degraded for truncate-model cancellation/emotion |
| Thinker | Qwen3-Omni | Qwen2.5-Omni or Ultravox | MiniCPM-o family | degraded until SemanticFrame JSON harness passes |
| Slow LLM | Qwen3 via DashScope/self-host | DeepSeek API | Qwen3-30B-A3B class on A100 | real/degraded depending on schema validation |

## Recommended First API Integration Set

1. DashScope/Bailian Qwen3 text model for SlowTask structured planning.
2. DashScope/Bailian TTS for basic Talker output.
3. DashScope/Bailian ASR if realtime streaming, timestamps, and cancellation behavior are confirmed.
4. Qwen3-Omni through DashScope/Bailian for Thinker SemanticFrame experiments.
5. DeepSeek API as a second Slow LLM provider for structured JSON comparison.

This set keeps operational complexity low while preserving adapter boundaries. It also gives a same-platform path for Qwen text and omni models without allowing one model to own the whole system.

## DashScope / Bailian Considerations

Aliyun documentation describes multiple API surfaces for Qwen models: OpenAI-compatible Chat Completions, OpenAI Responses-style API, and native DashScope APIs. The adapter should choose one surface per capability and record exact model id, endpoint surface, streaming support, JSON support, tool-call format, timeout behavior, and output mode.

DashScope is attractive for Chinese-first evaluation and Qwen-Omni availability. The risk is that service names, model versions, and feature flags can change. Each adapter integration should pin the tested model name and capture a capability matrix at integration time.

## Self-hosted A100 Considerations

Self-hosting is most useful for replayable research and privacy-controlled evaluation:

- FunASR Paraformer streaming can evaluate ASR partial behavior.
- SenseVoiceSmall can evaluate short-utterance quality and auxiliary emotion/event labels.
- CosyVoice2 can evaluate streaming TTS and voice controls.
- Qwen3-Omni or MiniCPM-o family can evaluate audio SemanticFrame generation.
- Qwen3 text models can evaluate structured planning offline.

Self-hosted inference must run outside Interaction Controller, reducer, replay runner, and event-loop critical paths. CPU-bound/audio-heavy work should be isolated in worker processes, sidecars, or model services.

## Capability Gaps

- Verified DashScope ASR streaming/timestamp/cancellation details are still unknown.
- TTS first-audio latency and stream chunk cadence need direct measurement.
- `supports_tts_truncate` is playback-owned; model request cancellation remains degraded/unknown for most candidates.
- Thinker structured JSON stability is unknown until schema harness tests run.
- Emotion, assistant-directedness, and semantic-close hints are degraded evidence, not policy.
- Provider cancellation is generally degraded; ADR-016 stale-result handling is mandatory.
- GLM-4.5 and Kimi K2 current structured-output/tool-call details need endpoint verification before recommendation.

## Risks to ADRs

One omni model should not absorb ASR, Thinker, TTS, Duplex, and SlowTask. Those roles have different latency budgets, authority boundaries, replay needs, and privacy surfaces. Collapsing them would make it hard to prove which evidence changed state, which plan version a result belongs to, and which component owns user-visible speech.

Duplex hot path should not depend on a large model because `speech_start <=150ms` and barge-in truncate around `<=250ms` require local deterministic processing and playback reference access. Large models may provide later semantic hints, but they should not decide immediate truncation.

TTS truncate should be Talker playback control because only playback can confirm the actual stopped span and offset. Model-side request cancellation is useful but cannot substitute for `TTS_TRUNCATED`.

Slow LLM quality should be measured by structured JSON validity, schema retry, plan_version binding, stale-result behavior, and confirmation safety. Voice ability is not relevant to SlowTask planning.

Platform APIs must still go through adapters. A convenient OpenAI-compatible or DashScope endpoint does not remove the need for capability matrices, redaction, timeout handling, degraded modes, and replayable event evidence.

webSearch/RAG evidence must stay out of instruction space. Search results can be cited as untrusted evidence, but they cannot change tool authorization, confirmation policy, trace policy, or ADR constraints.

## Experiments to Run Before MVP-3

- Duplex: measure VAD and echo false positives during TTS playback on local devices.
- ASR: compare DashScope ASR, FunASR Paraformer streaming, SenseVoiceSmall, and Whisper on synthetic Mandarin/English/mixed clips.
- TTS: measure first-audio latency and verify playback-stop offset accuracy.
- Thinker: run SemanticFrame JSON schema tests for Qwen3-Omni, Qwen2.5-Omni, and Ultravox.
- Slow LLM: run schema-constrained planning, malformed JSON repair, tool-call proposal normalization, and plan_version cancellation tests.
- Privacy: confirm traces contain only redacted metadata and synthetic fixtures.

## Final Recommendation

Adopt a layered adapter stack rather than an all-in-one omni model:

- Duplex: Silero/WebRTC rule-based local gate with echo likelihood from playback reference; no large model in the hot path.
- ASR: DashScope/Bailian API-first if the realtime contract checks out; FunASR Paraformer streaming and SenseVoiceSmall as self-host fallbacks; Whisper large-v3-turbo as offline fallback.
- TTS: DashScope/Bailian basic TTS API-first; CosyVoice2 self-host fallback; F5-TTS and IndexTTS2 for later voice/style research.
- Thinker: Qwen3-Omni primary for SemanticFrame evidence; Qwen2.5-Omni or Ultravox fallback; MiniCPM-o for A100 research.
- Slow LLM: Qwen3 text model first for structured planning, DeepSeek as alternate API candidate, GLM-4.5/Kimi K2 after current contract verification.

This combination fits accepted ADR boundaries: each capability enters through an adapter, hot-path audio stays local, TTS truncate remains playback-owned, SlowTask keeps plan authority, and all uncertain model behavior is labeled unknown or degraded until verified.
