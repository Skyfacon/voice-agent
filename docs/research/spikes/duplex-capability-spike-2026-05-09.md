# Duplex Capability Spike

## Status

evidence_report

## Date

2026-05-09

## Scope

This report covers Duplex / VAD / realtime audio gate candidates for MVP research. It evaluates local VAD, wake-word, echo likelihood, and lightweight semantic hints. It does not propose changes to the main runtime, accepted ADRs, or canonical event names.

## Architecture Role

Duplex is the low-latency live audio gate in front of ASR and Thinker evidence. It may emit pre-ASR signals such as speech start, speech end, wake/attention hints, and echo likelihood, but Interaction Controller remains responsible for turn ingress policy and truncate decisions. Large audio-language models can provide later evidence, not hot-path authority.

## ADR Constraints

- ADR-001: Duplex is outside the Interaction Controller authority boundary; the Interaction Controller owns turn ingress and policy decisions.
- ADR-003: barge-in must drive `TTS_TRUNCATE_REQUESTED` and then playback-confirmed `TTS_TRUNCATED`; truncate is a Talker/playback control contract.
- ADR-008: ASR/Thinker evidence fusion is SlowTask-led for conflicts; Duplex hints are evidence, not final semantic truth.
- ADR-011: any external model path must be an adapter with a declared capability matrix and output mode.
- ADR-012: MVP SLOs require low-latency barge-in behavior, so the hot path must be deterministic and local enough to replay.
- ADR-014: web evidence is untrusted evidence only.

## Candidate Shortlist

- Silero VAD: local lightweight VAD; official README advertises 30 ms and larger chunks, CPU-friendly inference, ONNX/PyTorch support, and 8 kHz / 16 kHz sampling.
- WebRTC VAD + WebRTC Audio Processing / AEC3: proven realtime voice stack for VAD, noise suppression, AGC, and acoustic echo cancellation reference handling.
- openWakeWord: local wake-word detector with ONNX/TFLite models and optional Silero VAD gating.
- SpeexDSP / RNNoise-style preprocessing: candidate noise suppression or echo-adjacent preprocessing, not sufficient as the main echo policy alone.
- Deferred semantic hint model: Qwen-Omni, MiniCPM-o, Moshi, or Ultravox can later provide semantic-close or assistant-directedness evidence, but not on the truncate hot path.

## Official Sources Checked

- Silero VAD GitHub: https://github.com/snakers4/silero-vad
- openWakeWord GitHub: https://github.com/dscripka/openWakeWord
- WebRTC Audio Processing source tree: https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/
- SpeexDSP project: https://www.speex.org/
- Moshi GitHub, for non-hot-path spoken-dialogue comparison: https://github.com/kyutai-labs/moshi

## Capability Matrix Assessment

| field | Silero VAD | WebRTC VAD / AEC3 | openWakeWord | deferred audio LLM hint |
| --- | --- | --- | --- | --- |
| adapter_type | duplex | duplex | duplex | thinker_or_duplex_evidence |
| provider | snakers4 | WebRTC project | dscripka | Qwen / MiniCPM / Moshi class |
| model_name | silero-vad | webrtc-vad-aec3 | openwakeword | unknown |
| deployment_mode | self_hosted_local | self_hosted_local | self_hosted_local | api_or_self_hosted |
| supports_streaming_input | real | real | real | degraded |
| supports_streaming_output | real | real | real | degraded |
| supports_audio_input | real | real | real | real |
| supports_audio_output | unsupported | unsupported | unsupported | degraded |
| supports_audio_timestamps | degraded | degraded | unsupported | unknown |
| supports_structured_json | unsupported | unsupported | unsupported | degraded |
| supports_tool_calling | unsupported | unsupported | unsupported | unsupported |
| supports_cancellation | real | real | real | degraded |
| supports_emotion | unsupported | unsupported | unsupported | unknown |
| supports_audio_caption | unsupported | unsupported | unsupported | degraded |
| supports_tts | unsupported | unsupported | unsupported | unsupported |
| supports_tts_truncate | unsupported | unsupported | unsupported | unsupported |
| supports_tts_pause_resume | unsupported | unsupported | unsupported | unsupported |
| supports_semantic_close | unsupported | unsupported | unsupported | degraded |
| supports_assistant_directedness | unsupported | degraded | degraded | degraded |
| max_audio_seconds | streaming_window | streaming_window | streaming_window | unknown |
| max_context_tokens | not_applicable | not_applicable | not_applicable | unknown |
| max_output_tokens | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_token_latency_ms | not_applicable | not_applicable | not_applicable | unknown |
| expected_first_audio_latency_ms | not_applicable | not_applicable | not_applicable | not_applicable |
| output_mode | real | real | fallback | degraded |
| degradation_notes | VAD only; no echo or semantics | strongest echo-reference candidate, but integration detail must be measured | wake/attention only; English pretrained coverage noted by upstream | advisory evidence only; keep out of barge-in hot path |

## Candidate Comparison

Silero VAD is the strongest first VAD candidate because it is small, local, and supports 30 ms chunks. WebRTC VAD/AEC3 is the strongest echo-reference and realtime audio-processing candidate because it can model playback reference, residual echo, and voice activity inside a mature audio pipeline. openWakeWord is useful for explicit wake/attention experiments, but it should not replace barge-in VAD.

Audio-language models are intentionally weaker for this role. They may help label whether a segment was assistant-directed or semantically complete after audio is buffered, but their inference latency and non-determinism make them a poor fit for immediate truncate.

## Recommended MVP Usage

Use a rule-based local hot path:

- Primary speech gate: Silero VAD or WebRTC VAD.
- Echo likelihood: WebRTC AEC/AEC3 playback reference plus residual echo/energy/correlation telemetry.
- Wake/attention: optional openWakeWord experiment, not required for MVP-0.
- Semantic close and assistant-directedness: mock or degraded evidence until Thinker experiments prove stable hints.

`speech_start <=150ms` is realistic if frames are 10-30 ms, local inference is used, and buffering/hangover policy is conservative. It still needs device/browser measurement.

`barge-in -> truncate command <=250ms` is realistic only if the path stays local: mic frame -> VAD/echo gate -> Interaction Controller -> playback stop request. It should not wait for ASR, Thinker, or an omni model.

## API / Deployment Notes

Silero VAD and openWakeWord can run locally through ONNX/PyTorch/TFLite wrappers behind a Duplex adapter. WebRTC Audio Processing is likely a native or sidecar integration; if introduced later it must enter through the Duplex event interface or adapter boundary and must not alter canonical event semantics.

## Latency and Resource Notes

Silero advertises sub-millisecond processing for a 30 ms audio chunk on one CPU thread in its README. openWakeWord processes 80 ms frames and targets modest CPUs. WebRTC AEC is designed for realtime use but requires careful audio device timing, playback reference availability, and thread isolation so it does not block the Interaction Controller or replay runner.

## Schema / Structured Output Notes

Duplex output should be small typed evidence, for example speech start/end, confidence, echo likelihood, and playback reference id. It should not emit SemanticCommitment. Semantic close and assistant-directedness should be optional hint fields with `degraded` or `mock` output modes until validated.

## Cancellation / Timeout / Retry Notes

Local VAD/AEC processing can be cancelled by dropping frames and closing the session stream. If an audio LLM is used for delayed hints, late results must be tied to the original turn/task metadata and treated as stale evidence when the current plan has moved on.

## Trace and Privacy Notes

Do not store raw audio in repository fixtures. Persist only synthetic/redacted metadata such as frame time, VAD confidence bucket, echo likelihood bucket, playback span id, and adapter output mode. Playback reference hashes or ids should not expose user content.

## Degradation Proposal

- If AEC is unavailable, mark echo likelihood `unknown` and use stricter VAD thresholds during TTS playback.
- If VAD is noisy, require consecutive voiced frames before barge-in.
- If wake-word is unavailable, omit wake hints rather than blocking speech detection.
- If semantic-close hints are unavailable, leave them `unknown`; SlowTask/Thinker can still resolve conflicts later.

## Risks

- AEC quality depends heavily on playback reference routing and device timing.
- Aggressive VAD can truncate assistant speech on echo.
- Conservative VAD can miss fast barge-in.
- Native audio components can threaten deterministic replay if they emit unstructured side effects.
- Treating semantic hints as policy would conflict with ADR-001 and ADR-008.

## Suggested Follow-up Experiments

- Measure speech-start latency on synthetic Mandarin, English, mixed speech, noise, and TTS echo.
- Measure barge-in-to-playback-stop latency with a local playback reference id.
- Compare Silero VAD vs WebRTC VAD false positives during assistant playback.
- Prototype echo likelihood buckets without storing raw audio.
- Evaluate Thinker-produced assistant-directedness only as post-hoc evidence.

## Recommendation

Use local rule-based Duplex first: Silero or WebRTC VAD plus WebRTC-style playback reference and echo likelihood. Keep semantic close and assistant-directedness as mock/degraded evidence until a Thinker adapter proves reliable. Do not place a large omni model on the truncate hot path.
