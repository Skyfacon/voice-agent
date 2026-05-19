# Duplex / VAD Run: Local WebRTC VAD

## Status

executed_webrtcvad_temp_venv_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can a locally installed WebRTC VAD dependency improve the Duplex / VAD probe from degraded energy gating to a more realistic local speech-activity baseline while keeping barge-in, echo, playback reference, truncate, and replay boundaries aligned with MVP-0?

## Provider / Local Candidate

- Candidate executed: `webrtcvad` in a temporary local venv.
- Venv location class: `/private/tmp/voice-agent-model-spike-vad-venv-*`.
- Package installed: `webrtcvad`.
- Compatibility note: `webrtcvad` imported only after pinning a compatible `setuptools` version because the package imports `pkg_resources`.
- Generation / processing tools available:
  - `ffmpeg`: present, version `8.1`
  - `afconvert`: present, version summary `Audio File Convert 2.0`
  - `say`: present, but still produced zero audio packets in this sandboxed run; not used as a speech fixture.
- Still missing: `silero_vad`, `torch`, `numpy`, `scipy`, `sox`.
- Deployment mode: `local`.
- Output mode: `real` for local WebRTC VAD frame decisions on synthetic PCM; `degraded` for natural speech quality, echo cancellation, and live device latency.

## Official Sources Checked

- py-webrtcvad official GitHub: [wiseman/py-webrtcvad](https://github.com/wiseman/py-webrtcvad)
- Silero VAD official GitHub: [snakers4/silero-vad](https://github.com/snakers4/silero-vad)
- WebRTC AEC3 source: [echo_canceller3.h](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/aec3/echo_canceller3.h)
- FFmpeg filter documentation: [silencedetect](https://ffmpeg.org/ffmpeg-filters.html#silencedetect)

Run-day notes from official sources:

- py-webrtcvad expects 16-bit mono PCM at supported sample rates such as 8, 16, 32, or 48 kHz.
- py-webrtcvad accepts 10 ms, 20 ms, or 30 ms frames.
- WebRTC VAD exposes aggressiveness modes from 0 to 3.
- Silero VAD can expose speech timestamps, but it was not installed for this run.
- WebRTC AEC3 is a render/capture echo-canceller design, reinforcing that barge-in needs playback reference.
- FFmpeg silence filters remain useful diagnostics only; they are not speech-directedness logic.

## Environment and Artifact Handling

- A temporary venv under `/private/tmp` was created for this probe.
- No package or generated dependency artifact was written into the repository.
- No remote model/provider call was made.
- No real user recording was used.
- All synthetic audio was generated under `/private/tmp/voice-agent-model-spike-webrtcvad-*` and removed by shell trap.
- No raw audio, raw trace, provider payload, local replay cache, credential, or unredacted real user input was committed.
- Terminal output was restricted to offsets, frame sizes, mode values, confidence-like ratios, and degradation labels.

## Synthetic Inputs

Because local `say` generated zero-packet audio files, this run reused deterministic Python-generated PCM fixtures:

- `speech_start_clean`: 500 ms silence + 900 ms speech-like waveform + 500 ms silence.
- `speech_end_clean`: same fixture for end / hangover observation.
- `short_backchannel`: 300 ms silence + 180 ms short speech-like waveform + 300 ms silence.
- `silence_only`: 2 seconds silence.
- `noise_or_tone`: 500 ms silence + 1 second pure tone + 500 ms silence.
- `white_noise`: 500 ms silence + 1 second low-amplitude white noise + 500 ms silence.
- `clipped_start`: 300 ms silence + clipped speech-like waveform + 500 ms silence.
- `tts_playback_only`: synthetic playback reference only.
- `user_barge_in_over_tts`: synthetic playback reference plus delayed synthetic user speech at 1000 ms.
- `near_end_barge_in`: synthetic playback reference plus delayed short utterance at 2200 ms.
- `client_stop_playback_simulation`: metadata-only playback stop simulation.

## Request / Processing Shape

Observed processing shape:

```json
{
  "candidate": "webrtcvad_local_temp_venv",
  "sample_rate_hz": 16000,
  "sample_format": "16-bit mono PCM",
  "primary_frame_ms": 20,
  "primary_mode": 2,
  "start_consecutive_frames": 2,
  "end_hangover_frames": 10,
  "playback_reference": "synthetic render signal, subtracted from synthetic mic signal for overlap cases"
}
```

The run also compared 10 ms, 20 ms, and 30 ms frames with VAD modes 0, 2, and 3 for the clean synthetic speech case.

## Observed Outputs

No raw audio was stored in the repository. Primary 20 ms / mode 2 summaries:

| case | start | end | emit latency / error | confidence-like ratio | key observation |
| --- | ---: | ---: | --- | ---: | --- |
| `speech_start_clean` | 500 ms | 1480 ms | start emit latency 40 ms; end offset +80 ms | 0.516 | start within target algorithmic budget |
| `speech_end_clean` | 500 ms | 1480 ms | end hangover budget 200 ms | 0.516 | end offset available, emission delayed by hangover |
| `short_backchannel` | 300 ms | 560 ms | start emit latency 40 ms; end offset +80 ms | 0.333 | short utterance detected |
| `silence_only` | none | none | no false positive | 0.000 | silence stayed silent |
| `noise_or_tone` | 500 ms | 1620 ms | false positive risk | 0.560 | pure tone is misclassified as speech activity |
| `white_noise` | 500 ms | 580 ms | false positive risk | 0.040 | low-amplitude noise can trigger a short false positive |
| `clipped_start` | 300 ms | 1040 ms | start emit latency 40 ms; end offset +90 ms | 0.514 | clipped synthetic activity detected |
| `tts_playback_only` | raw mic 0 ms | n/a | residual start none | raw 1.000 / residual 0.000 | playback reference blocks echo-only candidate |
| `user_barge_in_over_tts` | residual 1000 ms | n/a | candidate emit latency 40 ms | residual 0.300 | candidate only after reference subtraction |
| `near_end_barge_in` | residual 2200 ms | n/a | candidate emit latency 40 ms | residual 0.100 | near-end candidate detected, weak confidence |
| `client_stop_playback_simulation` | n/a | n/a | request offset 1040 ms, actual stop offset 1100 ms | n/a | playback controller metadata only |

Frame / mode comparison for clean speech:

| frame | mode | start | start emit latency | end | end offset error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 10 ms | 0 | 500 ms | 20 ms | 1520 ms | +120 ms |
| 10 ms | 2 | 500 ms | 20 ms | 1470 ms | +70 ms |
| 10 ms | 3 | 500 ms | 20 ms | 1470 ms | +70 ms |
| 20 ms | 0 | 500 ms | 40 ms | 1540 ms | +140 ms |
| 20 ms | 2 | 500 ms | 40 ms | 1480 ms | +80 ms |
| 20 ms | 3 | 500 ms | 40 ms | 1480 ms | +80 ms |
| 30 ms | 0 | 480 ms | 40 ms | 1560 ms | +160 ms |
| 30 ms | 2 | 480 ms | 40 ms | 1470 ms | +70 ms |
| 30 ms | 3 | 480 ms | 40 ms | 1470 ms | +70 ms |

The pure tone false-positive risk persisted across modes 0, 2, and 3 in this synthetic setup.

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `duplex_model` / local realtime audio gate candidate |
| `provider` | `local_webrtcvad` |
| `model_name` | `webrtcvad` |
| `deployment_mode` | `local` |
| `endpoint` | `local-process-no-endpoint` |
| `health_status` | `healthy_for_synthetic_pcm_probe` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `algorithmic_10_to_30ms_frames; live scheduling not measured` |
| `error_model` | `false_positive_non_speech_activity_or_missing_playback_reference_or_live_device_latency` |
| `timeout_policy` | not applicable for local VAD frame decisions; future runtime should use frame-budget watchdogs |
| `retry_policy` | not applicable; VAD frames should emit fresh candidate evidence, not retry state transitions |
| `supports_streaming_input` | real by frame API shape; live microphone not exercised |
| `supports_streaming_output` | real by frame decision shape; runtime event emission not wired |
| `supports_audio_input` | real for 16-bit mono PCM |
| `supports_audio_output` | unsupported / not applicable |
| `supports_audio_timestamps` | real for frame offsets |
| `supports_structured_json` | unsupported / not applicable; report has metadata only |
| `supports_tool_calling` | unsupported / not applicable |
| `supports_cancellation` | unsupported / not applicable to local VAD |
| `supports_emotion` | unsupported |
| `supports_audio_caption` | unsupported |
| `supports_tts` | unsupported |
| `supports_tts_truncate` | unsupported at VAD layer |
| `supports_tts_pause_resume` | unsupported / MVP non-goal |
| `supports_semantic_close` | unknown / not validated |
| `supports_assistant_directedness` | unknown / not validated |
| `max_audio_seconds` | not model-bounded; future adapter should bound audio span/ring buffer |
| `max_context_tokens` | null |
| `max_output_tokens` | null |
| `expected_first_token_latency_ms` | null |
| `expected_first_audio_latency_ms` | null |
| `vad_frame_ms` | 10, 20, or 30 ms supported; primary probe used 20 ms |
| `speech_start_latency_ms` | 40 ms primary emit latency with 20 ms frames and two-frame start debounce |
| `speech_end_hangover_ms` | 200 ms primary hangover with ten 20 ms frames |
| `barge_in_candidate_latency_ms` | 40 ms primary emit latency after residual user activity |
| `echo_likelihood_mode` | degraded: idealized playback-reference subtraction only |
| `playback_reference_required` | true |
| `output_mode` | `real` for WebRTC VAD frame decisions on synthetic PCM; `degraded` for natural speech / echo / live latency |

## VAD Latency Observation

WebRTC VAD can support the MVP speech-start algorithmic budget on synthetic PCM:

- 10 ms frames with two-frame debounce emitted after about 20 ms.
- 20 ms frames with two-frame debounce emitted after about 40 ms.
- 30 ms frames with two-frame debounce emitted after about 40 ms due frame alignment in this fixture.

This is still not a real microphone measurement. Device capture, scheduler delay, audio callback buffering, and playback-reference plumbing remain unmeasured.

## Speech End / Hangover Observation

With ten-frame hangover:

- 10 ms frame mode implies about 100 ms hangover.
- 20 ms frame mode implies about 200 ms hangover.
- 30 ms frame mode implies about 300 ms hangover.

The primary 20 ms / mode 2 clean case ended 80 ms after the synthetic expected end and would emit only after the 200 ms hangover budget. This is acceptable as evidence shape, but product policy should choose hangover based on UX interruption tolerance.

## Barge-in / Echo Observation

WebRTC VAD alone classifies synthetic playback-only mic activity as speech. This is the important result:

- Raw `tts_playback_only` VAD confidence was 1.000.
- After idealized playback-reference subtraction, residual VAD confidence was 0.000 and no candidate was emitted.
- `user_barge_in_over_tts` residual speech started at 1000 ms with 40 ms emit latency.
- `near_end_barge_in` residual speech started at 2200 ms with 40 ms emit latency, but confidence-like ratio was weak at 0.100.

Therefore WebRTC VAD is useful for local speech activity, but target barge-in still requires playback reference and echo handling. The echo result remains degraded because subtraction was idealized and not real AEC.

## Playback Reference / Truncate Observation

Playback reference remains mandatory:

- Without render/reference comparison, playback-only audio becomes a false barge-in risk.
- With reference residual, echo-only playback is blocked in this synthetic setup.

The metadata-only truncate simulation kept offsets distinct:

- Candidate/request offset example: `1040 ms`
- Talker-confirmed actual stop offset example: `1100 ms`

`TTS_TRUNCATED` must remain Talker/playback-owned and cannot be inferred from WebRTC VAD, WebRTC AEC, or model request cancellation.

## Directedness / Semantic Close Observation

No large model, ASR transcript, or Qwen-Omni output was used in the Duplex hot path.

- `assistant_directedness`: unknown / degraded. WebRTC VAD cannot decide whether speech is addressed to the assistant.
- `semantic_close`: unknown / degraded. WebRTC VAD cannot decide turn semantic completeness.

These should remain Interaction Controller policy assumptions or future Duplex capabilities, not VAD facts.

## Timeout / Retry / Cancellation Observation

- No remote timeout was relevant.
- No retry was relevant.
- VAD frame processing should not retry state transitions.
- Cancellation is not a VAD capability.
- Model-side request cancellation remains unrelated to `TTS_TRUNCATED`.

## Trace and Privacy Review

- No real user recording was used.
- Synthetic local audio was generated under `/private/tmp` and removed.
- The temporary VAD venv stayed outside the repository.
- No raw audio, raw trace, provider payload, local replay cache, credential, or unredacted real user input was committed.
- The report contains only metadata, offsets, capability labels, and degradation notes.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| WebRTC VAD installed in temp venv only | real local decision evidence for spike; not a committed dependency |
| `pkg_resources` compatibility warning | pin compatible `setuptools` if this dependency is used in a future controlled harness |
| `say` produced zero-packet files | natural-speech synthetic fixture remains unavailable locally |
| Pure tone / white noise false positives | require non-speech eval and conservative Interaction policy |
| Playback-only raw VAD activity | require playback reference; raw VAD alone cannot validate target barge-in |
| Idealized reference subtraction works | confirms interface shape only, not production AEC |
| Directedness unavailable | use `UNKNOWN` or explicit policy assumption; do not call it real |
| Semantic close unavailable | use conservative rule/mock until real Duplex semantic close exists |
| Truncate stop offset unavailable to VAD | Talker/playback must confirm actual stop offset |

## Fit to MVP-0 Contract

Fit is stronger than the prior energy-gate baseline for local VAD, but still not ready for full adapter profile hardening:

- `SPEECH_START_DETECTED` can be represented as Duplex evidence with frame-derived offsets.
- `SPEECH_END_DETECTED` can carry end offset and hangover basis.
- `BARGE_IN_CANDIDATE` can carry playback span, playback offset, VAD confidence, degraded echo likelihood, and playback reference ref.
- `INTERRUPT_CANDIDATE` belongs to Interaction Controller.
- `TTS_TRUNCATE_REQUESTED` belongs to Interaction Controller.
- `TTS_TRUNCATED` can only be confirmed by Talker/playback controller after actual stop offset is known.
- VAD / echo evidence must not bypass Interaction Controller.
- `semantic_close` and `assistant_directedness` are not real WebRTC VAD capabilities.
- Deterministic replay should not rerun real VAD; it should consume recorded metadata or synthetic fixtures.

This report does not authorize runtime integration.

## Recommendation

Use WebRTC VAD as the first local Duplex/VAD dependency candidate for a spike-local harness. Before adapter profile hardening, run one more focused probe with either real natural-speech synthetic fixtures or a controlled generated speech source that produces non-empty audio in this environment, and define the playback-reference/AEC interface separately. Silero VAD remains useful as a later quality comparison, but it is heavier because it brings a model runtime dependency.
