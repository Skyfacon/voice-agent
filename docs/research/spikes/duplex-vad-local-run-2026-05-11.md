# Duplex / VAD Run: Local Energy Gate Baseline

## Status

executed_degraded_baseline

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration and does not change adapter, event, replay, or ADR contracts.

## Question

Can a local-only deterministic audio gate produce replay-safe Duplex / VAD / barge-in metadata shaped like MVP-0 events without using a large model, external provider call, real user recording, raw audio in the repo, or model-side cancellation as truncate evidence?

## Provider / Local Candidate

- Candidate executed: `python_stdlib_energy_gate_with_idealized_playback_reference_subtraction`
- Generation / processing tools available:
  - `ffmpeg`: present, version `8.1`
  - `afconvert`: present, version summary `Audio File Convert 2.0`
  - `say`: present, but produced zero audio packets in this sandboxed run; not used as a speech fixture
- VAD packages checked:
  - `webrtcvad`: missing
  - `silero_vad`: missing
  - `torch`: missing
  - `numpy`: missing
  - `scipy`: missing
- Additional local commands checked: `sox`, `vad`, `webrtcvad`, `silero-vad`, `silero_vad` were missing.
- Deployment mode: `local`
- Output mode: `degraded` because the executed gate is energy-based and synthetic, not a true natural-speech WebRTC/Silero VAD run.

## Official Sources Checked

- py-webrtcvad official GitHub: [wiseman/py-webrtcvad](https://github.com/wiseman/py-webrtcvad)
- Silero VAD official GitHub: [snakers4/silero-vad](https://github.com/snakers4/silero-vad)
- WebRTC AEC3 source: [echo_canceller3.h](https://webrtc.googlesource.com/src/+/refs/heads/main/modules/audio_processing/aec3/echo_canceller3.h)
- FFmpeg filter documentation: [silencedetect](https://ffmpeg.org/ffmpeg-filters.html#silencedetect)

Run-day notes from official sources:

- py-webrtcvad expects 16-bit mono PCM audio at supported sample rates such as 8, 16, 32, or 48 kHz, with 10, 20, or 30 ms frames.
- Silero VAD exposes speech timestamp extraction, but its package and model runtime were not locally available in this workspace.
- WebRTC AEC3 is a render/capture echo-canceller design; target barge-in validation needs a playback/render reference, not microphone VAD alone.
- FFmpeg `silencedetect` can detect silence by threshold and duration. It is useful as a local audio-activity diagnostic, not a semantic speech detector.

## Environment and Artifact Handling

- No remote model/provider call was made.
- No dependency was installed.
- All synthetic audio was generated under `/private/tmp/voice-agent-model-spike-duplex-*`.
- The temp directory was removed by shell trap after the run.
- No raw audio, raw trace, raw provider payload, local replay cache, credential, or real user recording was committed.
- Terminal output was restricted to synthetic case names, offsets, confidence-like ratios, and degradation labels.

## Synthetic Inputs

Natural TTS fixture generation was attempted with local `say`, but the produced files had zero audio packets in this environment. To keep the probe local and avoid provider calls, the executed baseline used deterministic synthetic speech-like waveforms generated with Python stdlib math:

- `speech_start_clean`: 500 ms silence + 900 ms speech-like waveform + 500 ms silence.
- `speech_end_clean`: same fixture, used for end / hangover observation.
- `short_backchannel`: 300 ms silence + 180 ms short speech-like waveform + 300 ms silence.
- `silence_only`: 2 seconds silence.
- `noise_or_tone`: 500 ms silence + 1 second pure tone + 500 ms silence.
- `clipped_start`: 300 ms silence + speech-like waveform with the first 250 ms removed + 500 ms silence.
- `tts_playback_only`: synthetic playback reference only.
- `user_barge_in_over_tts`: synthetic playback reference plus delayed synthetic user speech at 1000 ms.
- `near_end_barge_in`: synthetic playback reference plus delayed short user utterance at 2200 ms.
- `client_stop_playback_simulation`: metadata-only playback stop simulation.

## Request / Processing Shape

Observed processing shape:

```json
{
  "candidate": "python_stdlib_energy_gate_with_idealized_playback_reference_subtraction",
  "sample_rate_hz": 16000,
  "sample_format": "16-bit mono PCM",
  "frame_ms": 20,
  "threshold_dbfs": -42.0,
  "start_consecutive_frames": 2,
  "end_hangover_frames": 10,
  "playback_reference": "synthetic render signal, subtracted from synthetic mic signal for overlap cases"
}
```

This was an offline one-off probe. A real Duplex implementation would process frames incrementally and must account for scheduler and device latency.

## Observed Outputs

No raw audio was stored in the repository. The observed metadata summaries were:

| case | speech start | speech end | offset error / latency | confidence-like ratio | key observation |
| --- | ---: | ---: | --- | ---: | --- |
| `speech_start_clean` | 500 ms | 1400 ms | start offset error 0 ms | 0.474 | detected synthetic activity cleanly |
| `speech_end_clean` | 500 ms | 1400 ms | end offset error 0 ms | 0.474 | end boundary recorded; runtime emission would wait hangover frames |
| `short_backchannel` | 300 ms | 480 ms | start offset error 0 ms | 0.231 | short utterance detected in synthetic baseline |
| `silence_only` | none | none | no false positive | 0.000 | silence stayed silent |
| `noise_or_tone` | 500 ms | 1500 ms | false positive risk | 0.500 | pure tone triggers energy gate, showing non-speech false-positive risk |
| `clipped_start` | 300 ms | 940 ms | start offset error 0 ms; end offset error -10 ms | 0.444 | clipped synthetic activity still detected |
| `tts_playback_only` | raw mic 0 ms | raw mic 2600 ms | blocked after reference subtraction | 1.000 raw | raw activity is echo-only; playback reference removes it |
| `user_barge_in_over_tts` | residual 1000 ms | not recorded | barge-in offset error 0 ms | 0.269 residual | candidate only after idealized playback-reference subtraction |
| `near_end_barge_in` | residual 2200 ms | not recorded | barge-in offset error 0 ms | 0.069 residual | near-end candidate remains detectable in synthetic residual |
| `client_stop_playback_simulation` | n/a | n/a | request offset 1040 ms, actual stop offset 1100 ms | n/a | Talker/playback metadata simulation only |

The zero offset errors above are offline fixture alignment results, not end-to-end live device latency results.

## Capability Matrix Observation

| field | observation |
| --- | --- |
| `adapter_type` | `duplex_model` / local realtime audio gate candidate |
| `provider` | `local_python_ffmpeg` |
| `model_name` | `stdlib_energy_gate_v0` |
| `deployment_mode` | `local` |
| `endpoint` | `local-process-no-endpoint` |
| `health_status` | `degraded_baseline_executed` |
| `capability_version` | `research_observation_v1` |
| `latency_class` | `algorithmic_20ms_frames; live scheduling not measured` |
| `error_model` | `false_positive_energy_activity_or_missing_vad_dependency_or_missing_playback_reference` |
| `timeout_policy` | not applicable for local offline gate; future streaming gate should use frame-budget watchdogs |
| `retry_policy` | not applicable; VAD frames should not retry state transitions |
| `supports_streaming_input` | degraded/real-by-design for frame processing; not exercised with live microphone |
| `supports_streaming_output` | degraded/real-by-design for candidate events; not wired to runtime |
| `supports_audio_input` | real for local PCM input |
| `supports_audio_output` | unsupported / not applicable |
| `supports_audio_timestamps` | real for frame offsets in synthetic metadata |
| `supports_structured_json` | degraded; one-off metadata summary only, no provider JSON contract |
| `supports_tool_calling` | unsupported / not applicable |
| `supports_cancellation` | unsupported / not applicable to VAD; playback truncate is owned elsewhere |
| `supports_emotion` | unsupported |
| `supports_audio_caption` | unsupported |
| `supports_tts` | unsupported |
| `supports_tts_truncate` | unsupported at VAD layer |
| `supports_tts_pause_resume` | unsupported / MVP non-goal |
| `supports_semantic_close` | unknown / not validated |
| `supports_assistant_directedness` | unknown / not validated |
| `max_audio_seconds` | not bounded by model; future adapter should bound ring buffer and span duration |
| `max_context_tokens` | null |
| `max_output_tokens` | null |
| `expected_first_token_latency_ms` | null |
| `expected_first_audio_latency_ms` | null |
| `vad_frame_ms` | 20 ms |
| `speech_start_latency_ms` | algorithmic emission about 40 ms after onset with two-frame start rule; offline offset error 0 ms on synthetic clean case |
| `speech_end_hangover_ms` | algorithmic hangover about 200 ms with ten-frame end rule; offline end offset error 0 ms on synthetic clean case |
| `barge_in_candidate_latency_ms` | algorithmic emission about 40 ms after residual user activity; offline offset error 0 ms on synthetic overlap cases |
| `echo_likelihood_mode` | degraded: idealized playback-reference subtraction only |
| `playback_reference_required` | true |
| `output_mode` | `degraded` |

## VAD Latency Observation

The clean and clipped synthetic speech-like fixtures aligned to the expected start offsets. With 20 ms frames and two consecutive active frames required, a streaming implementation would emit speech-start no earlier than about 40 ms after onset, before device/scheduler overhead.

This is within the MVP target of `<=150ms` as an algorithmic budget, but it is not a real microphone latency measurement and should not be treated as SLO proof.

## Speech End / Hangover Observation

The offline end offset matched the synthetic expected end for the clean case. The configured end hangover was ten frames, or about 200 ms. That means the event can record an end offset near the true boundary, but live emission would occur after hangover delay.

The clipped case ended 10 ms before the synthetic expectation, which is acceptable for this coarse 20 ms frame baseline but should be rechecked with real VAD dependencies.

## Barge-in / Echo Observation

The probe demonstrates why playback reference is mandatory:

- `tts_playback_only` produced raw mic activity from the synthetic playback signal.
- Idealized reference subtraction removed that activity and blocked a barge-in candidate.
- `user_barge_in_over_tts` and `near_end_barge_in` produced residual activity at the synthetic user-speech offsets.

This is only a degraded echo baseline. It does not prove real acoustic echo cancellation, device echo robustness, or natural-speech directedness.

## Playback Reference / Truncate Observation

Playback reference compatibility is required for target-architecture barge-in. Without a render/playback reference, the raw energy gate misclassifies playback as speech activity.

The `client_stop_playback_simulation` case records distinct offsets:

- Candidate / request-side offset example: `1040 ms`
- Talker-confirmed actual stop offset example: `1100 ms`

This supports the ADR-003 shape, but it does not validate real Talker stop behavior. `TTS_TRUNCATED` must be emitted only by Talker/playback controller after actual stop offset is known.

## Directedness / Semantic Close Observation

No large model, ASR transcript, or Qwen-Omni output was used in the Duplex hot path.

- `assistant_directedness`: unknown / degraded. Suggested MVP policy remains `ASSUMED_DIRECTED` only for accepted text path or conservative `UNKNOWN` for audio until a real Duplex directedness signal exists.
- `semantic_close`: unknown / degraded. Suggested MVP policy remains rule/mock/conservative handling, not model-derived policy.

## Timeout / Retry / Cancellation Observation

- No remote request timeout was relevant.
- No retry was relevant.
- VAD frame processing should not retry state transitions; it should emit fresh candidate evidence per frame/span.
- Cancellation is not a VAD capability in this run.
- Model-side or client-side request cancellation must not be recorded as `TTS_TRUNCATED`.

## Trace and Privacy Review

- No real user recording was used.
- Synthetic local audio was generated under `/private/tmp` and removed.
- No raw audio, raw trace, provider payload, local replay cache, credential, or unredacted real user input was committed.
- The report contains only metadata, offsets, capability labels, and degradation notes.

## Degradation Mapping

| capability or failure | mapping |
| --- | --- |
| WebRTC / Silero dependency missing | keep local gate as degraded baseline; request human-approved dependency setup before quality claims |
| `say` produced zero-packet files | natural-speech synthetic fixture unavailable locally; use deterministic waveform only |
| Energy gate detects pure tone | false-positive risk; cannot be considered semantic speech detector |
| Playback-only raw activity | require playback reference; otherwise block or degrade barge-in validation |
| Idealized reference subtraction works | evidence for interface shape only, not proof of AEC robustness |
| Directedness unavailable | record `UNKNOWN` or `ASSUMED_DIRECTED` by explicit Interaction policy, not model inference |
| Semantic close unavailable | record `UNKNOWN` or conservative rule result, not model inference |
| Truncate stop offset unavailable | block target validation until Talker reports actual stop offset |

## Fit to MVP-0 Contract

Fit is partial and useful for event-shape hardening:

- `SPEECH_START_DETECTED` can be represented as Duplex evidence with `audio_span_id`, `audio_sample_offset`, and `vad_confidence`.
- `SPEECH_END_DETECTED` can record end offset and hangover basis.
- `BARGE_IN_CANDIDATE` can carry `audio_span_id`, `playback_span_id`, `playback_offset_ms`, `echo_likelihood`, `vad_confidence`, `barge_in_confidence`, and `playback_reference_ref`.
- `INTERRUPT_CANDIDATE` belongs to Interaction Controller, not Duplex.
- `TTS_TRUNCATE_REQUESTED` belongs to Interaction Controller, not Duplex.
- `TTS_TRUNCATED` can only be confirmed by Talker/playback controller after it knows `actual_stop_offset_ms`.
- VAD / echo evidence must not bypass Interaction Controller.
- `semantic_close` and `assistant_directedness` are not real capabilities in this run.
- Deterministic replay should not rerun real VAD; it should consume recorded metadata or a synthetic fixture.

This report does not authorize runtime integration.

## Recommendation

Do not enter adapter profile hardening for Duplex/VAD yet. First obtain a real local VAD dependency, preferably WebRTC VAD for a light deterministic baseline or Silero VAD for stronger speech detection, plus a planned WebRTC Audio Processing / AEC3-style playback reference path. The current run is valuable as a degraded event-shape and offset-semantics probe, but not as natural-speech VAD quality evidence.
