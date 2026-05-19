# Duplex / VAD WebRTC VAD Harness Plan

## Status

phase_5c_harness_design_with_repeatable_probe_executed

This is research evidence only. It does not connect to the main runtime, does not create a business adapter, and does not change ADR, event registry, adapter capability, replay, source, or test contracts.

## Date

2026-05-11

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- Referenced contracts:
  - `AGENTS.md`
  - `docs/research/model-spike-execution-plan.md`
  - `docs/research/model-spike-integration-ledger.md`
  - `docs/research/model-spike-plan.md`
  - `docs/research/model-selection.md`
  - `docs/specs/model-adapter-capabilities.md`
  - `docs/specs/event-registry.md`
  - `docs/specs/replay-spec.md`
  - `docs/adr/ADR-001 Duplex Boundary and Interaction Controller.md`
  - `docs/adr/ADR-003 Barge-in and TTS Truncate Contract.md`
  - `docs/adr/ADR-011 Model Adapter Capability Contract.md`

## Question

Can the one-off Phase 5b WebRTC VAD probe become a reproducible, spike-local harness that repeatedly emits metadata-only Duplex/VAD observations for MVP-0 event-shape analysis, without connecting to runtime, storing raw audio, using real user recordings, or treating VAD as semantic or truncate authority?

## Current Evidence Summary

The earlier local energy-gate report showed a useful degraded event-shape baseline, but it could not validate a real speech-activity dependency. The Phase 5b WebRTC VAD report improved that baseline by installing `webrtcvad` in a temporary local environment and running deterministic synthetic PCM through WebRTC VAD.

This Phase 5c rerun confirms the same direction:

- WebRTC VAD is a good first local candidate for low-latency speech activity evidence on synthetic PCM.
- 20 ms frames with mode 2 and a two-frame start debounce emitted clean speech start after 40 ms in the rerun.
- 10 ms frames reduce the synthetic speech-start emission to 20 ms, while 20 ms frames are a practical default and 30 ms frames increase hangover and alignment coarseness.
- WebRTC VAD alone misclassifies synthetic playback, tone, and broadband noise as speech-like activity in multiple settings.
- Playback reference remains mandatory. The synthetic playback-only mic path had raw VAD confidence 1.000, while idealized reference residual was 0.000.
- The result is stronger than the energy baseline for local VAD, but echo handling, real microphone latency, real room playback, directedness, and semantic close remain degraded or unknown.

## Local Dependency Handling

Branch and protected-area preflight:

- Current branch: `research/model-spikes`.
- Initial protected path status for `src/voice_agent`, `tests`, `docs/adr`, and `docs/specs`: clean.
- Existing untracked research reports were present under `docs/research/spikes/`; this plan only adds a new research report.

Local tools and dependencies observed:

| item | status | note |
| --- | --- | --- |
| `ffmpeg` | present | `/opt/homebrew/bin/ffmpeg`, version `8.1` |
| `afconvert` | present | `/usr/bin/afconvert`, help reports `Audio File Convert Version: 2.0` |
| `say` | present | `/usr/bin/say`; not used for this rerun |
| global `webrtcvad` | missing | installed only into a temporary `/private/tmp` venv |
| temporary `webrtcvad` | present | `webrtcvad==2.0.10` in `/private/tmp/voice-agent-model-spike-vad-venv-*` |
| temporary `setuptools` | present | `setuptools==80.10.2`, needed because `webrtcvad` imports `pkg_resources` |
| `silero_vad` | missing | not installed |
| `torch` | missing | not installed |

The dependency rule for the future harness should be:

- Default to a temporary or explicitly human-created local environment outside repo artifacts.
- Pin `webrtcvad==2.0.10` and `setuptools<81` for Python 3.12 compatibility unless the package removes the `pkg_resources` dependency.
- Do not install `silero_vad` or `torch` as part of this WebRTC VAD harness.
- Do not write venvs, generated audio, local trace, or replay cache into the repository.

## Synthetic Fixture Plan

The harness should generate deterministic synthetic PCM with a fixed seed and produce metadata summaries. Raw fixture audio should be local-only and disabled by default; the normal output should be computed metadata.

Required cases:

| synthetic case | fixture shape | expected observation |
| --- | --- | --- |
| `speech_start_clean` | 500 ms silence, 900 ms deterministic speech-like waveform, 500 ms silence | clean speech start latency |
| `speech_end_clean` | same signal as clean start | end offset and hangover behavior |
| `short_backchannel` | 300 ms silence, 180 ms short speech-like waveform, 300 ms silence | short utterance sensitivity |
| `silence_only` | 2000 ms silence | no speech candidate |
| `noise_or_tone` | 500 ms silence, 1000 ms pure tone, 500 ms silence | non-speech false-positive risk |
| `white_noise` | 500 ms silence, 1000 ms seeded broadband noise, 500 ms silence | noise false-positive risk |
| `clipped_start` | 300 ms silence, clipped speech-like waveform, 500 ms silence | truncated onset sensitivity |
| `tts_playback_only` | synthetic playback signal as mic input and matching playback reference | echo-only false-positive risk and residual blocking |
| `user_barge_in_over_tts` | playback plus residual user speech at 1000 ms | barge-in candidate evidence after reference residual |
| `near_end_barge_in` | playback plus short user speech at 2200 ms | weak near-end residual candidate behavior |
| `client_stop_playback_simulation` | metadata-only playback request/stop offsets | truncate ownership boundary, no VAD decision |

Future fixture parameters should include sample rate, frame size, mode, seed, amplitude, signal type, expected speech window, playback span id, audio span id, and whether the case is speech, non-speech, playback-only, or overlap.

## Proposed Harness Shape

Do not create these files in Phase 5c. If approved, create a spike-local harness under:

```text
tools/model_spikes/duplex_vad/
  README.md
  requirements.txt
  generate_synthetic_audio.py
  run_webrtcvad_probe.py
  schemas/
    duplex_vad_observation.schema.json
  runs/
    README.md
```

Responsibilities:

- `README.md`: scope, safety boundary, local environment setup, and examples.
- `requirements.txt`: `webrtcvad==2.0.10` and `setuptools<81`.
- `generate_synthetic_audio.py`: deterministic fixture generator with metadata-first defaults and optional local-only WAV output under `/private/tmp`.
- `run_webrtcvad_probe.py`: runs frame/mode matrix, playback-reference residual simulation, and metadata validation.
- `schemas/duplex_vad_observation.schema.json`: validates metadata-only observation records.
- `runs/README.md`: explains that raw audio and local traces are excluded, and that committed run summaries must be metadata-only.

The harness must remain outside `src/voice_agent`, must not import runtime modules, and must not emit canonical events directly. It should emit adapter-shaped research observations that can later be converted into synthetic replay or eval fixtures by a separate reviewed step.

## Proposed CLI / Output Shape

Proposed local commands:

```bash
python -m venv /private/tmp/voice-agent-model-spike-vad-venv-<id>
/private/tmp/voice-agent-model-spike-vad-venv-<id>/bin/python -m pip install -r tools/model_spikes/duplex_vad/requirements.txt
/private/tmp/voice-agent-model-spike-vad-venv-<id>/bin/python tools/model_spikes/duplex_vad/run_webrtcvad_probe.py \
  --contract-snapshot main@61e6afc \
  --candidate webrtcvad \
  --sample-rate-hz 16000 \
  --frame-ms 10,20,30 \
  --mode 0,2,3 \
  --cases all \
  --metadata-out /private/tmp/voice-agent-model-spike-vad-run-<id>/observations.jsonl
```

Output policy:

- Default output is JSONL metadata, not audio.
- Optional generated WAV fixtures must stay under `/private/tmp` and be deleted after the probe.
- Reports under `docs/research/spikes/` should summarize the JSONL results and include only offsets, confidence summaries, output modes, degradation labels, and safety flags.
- The CLI should exit non-zero if metadata validation fails or if a raw artifact path points inside the repository.

## Replay-Safe Metadata Shape

Example observation record:

```json
{
  "contract_snapshot": "main@61e6afc",
  "candidate": "webrtcvad",
  "deployment_mode": "local",
  "output_mode": "real_or_degraded",
  "sample_rate_hz": 16000,
  "frame_ms": 20,
  "mode": 2,
  "synthetic_case": "speech_start_clean",
  "synthetic_seed": 20260511,
  "speech_start_ms": 500,
  "speech_start_emit_latency_ms": 40,
  "speech_end_ms": 1500,
  "speech_end_hangover_ms": 200,
  "vad_confidence_summary": 0.526,
  "echo_likelihood_mode": "degraded_playback_reference_required",
  "playback_reference_residual": "not_applicable",
  "raw_audio_committed": false,
  "contains_real_user_input": false,
  "contains_raw_trace": false,
  "deterministic_replay_reruns_vad": false
}
```

Replay-safe interpretation:

- Deterministic replay consumes the recorded metadata or a synthetic fixture.
- Deterministic replay does not rerun WebRTC VAD.
- Raw audio is never required for shareable replay.
- Any future re-eval mode must be explicit and must label regenerated output as re-eval evidence, not original runtime fact.

## WebRTC VAD Probe Result Summary

Rerun setup:

- Candidate: `webrtcvad==2.0.10` in a temporary `/private/tmp` venv.
- Sample rate: 16000 Hz.
- Sample format: 16-bit mono PCM.
- Primary setting: 20 ms frames, mode 2, two-frame start debounce, ten-frame end hangover.
- Probe style: in-memory deterministic synthetic PCM; no audio files were written.

Primary 20 ms / mode 2 results:

| case | basis | start | start emit latency | end | end offset error | hangover budget | confidence | raw confidence |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `speech_start_clean` | mic | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 | - |
| `speech_end_clean` | mic | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 | - |
| `short_backchannel` | mic | 300 ms | 40 ms | 580 ms | +100 ms | 200 ms | 0.359 | - |
| `silence_only` | mic | none | none | none | none | none | 0.000 | - |
| `noise_or_tone` | non-speech mic | 500 ms | not applicable | 1620 ms | not applicable | 200 ms | 0.560 | - |
| `white_noise` | non-speech mic | 500 ms | not applicable | 1600 ms | not applicable | 200 ms | 0.550 | - |
| `clipped_start` | mic | 300 ms | 40 ms | 1060 ms | +110 ms | 200 ms | 0.521 | - |
| `tts_playback_only` | residual after reference subtraction | none | none | none | none | none | 0.000 | 1.000 |
| `user_barge_in_over_tts` | residual after reference subtraction | 1000 ms | 40 ms | 1700 ms | +100 ms | 200 ms | 0.269 | 1.000 |
| `near_end_barge_in` | residual after reference subtraction | 2200 ms | 40 ms | 2480 ms | +100 ms | 200 ms | 0.108 | 1.000 |
| `client_stop_playback_simulation` | metadata only | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Clean speech frame/mode comparison:

| frame | mode | start | start emit latency | end | end offset error | hangover budget | confidence |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 ms | 0 | 500 ms | 20 ms | 1550 ms | +150 ms | 100 ms | 0.553 |
| 10 ms | 2 | 500 ms | 20 ms | 1490 ms | +90 ms | 100 ms | 0.521 |
| 10 ms | 3 | 500 ms | 20 ms | 1490 ms | +90 ms | 100 ms | 0.521 |
| 20 ms | 0 | 500 ms | 40 ms | 1560 ms | +160 ms | 200 ms | 0.558 |
| 20 ms | 2 | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 |
| 20 ms | 3 | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 |
| 30 ms | 0 | 480 ms | 40 ms | 1560 ms | +160 ms | 300 ms | 0.562 |
| 30 ms | 2 | 480 ms | 40 ms | 1500 ms | +100 ms | 300 ms | 0.531 |
| 30 ms | 3 | 480 ms | 40 ms | 1500 ms | +100 ms | 300 ms | 0.531 |

Frame/mode observations across the required cases:

- `speech_start_clean`, `speech_end_clean`, and `clipped_start` were detected across all tested frame/mode combinations.
- `short_backchannel` was detected across all combinations, but 30 ms / mode 3 shifted start to 390 ms and raised emit latency to 150 ms, making 30 ms / mode 3 risky for short backchannels.
- `silence_only` stayed silent across all combinations.
- `noise_or_tone` and `white_noise` produced false positives in this synthetic setup. Mode 3 reduced tone confidence for 20 ms and 30 ms frames, but did not remove the non-speech risk.
- `tts_playback_only` residual stayed silent across all combinations after idealized reference subtraction, while raw mic confidence was 1.000 in the primary setting.
- `user_barge_in_over_tts` residual was detected across all combinations, with primary 20 ms / mode 2 start emit latency at 40 ms.
- `near_end_barge_in` residual was detected across all combinations, but confidence was weak, around 0.10 in the primary setting.

Latency and hangover summary:

- Speech-start emit latency was 20 ms for 10 ms frames with two-frame debounce.
- Speech-start emit latency was 40 ms for 20 ms frames with two-frame debounce in the primary clean case.
- 30 ms frames had coarser alignment and case-dependent emit latency of about 40-60 ms, with worse behavior for one short backchannel mode.
- Configured speech-end hangover is `frame_ms * 10`: 100 ms, 200 ms, or 300 ms for the three tested frame sizes.
- WebRTC VAD itself also extends some detected speech windows after synthetic ground truth; clean speech mode 2 ended about 90-100 ms late in this rerun.

## Playback Reference / Echo Plan

WebRTC VAD must not be used as a standalone barge-in oracle.

Observed playback behavior:

- Playback-only raw mic VAD confidence was 1.000 in the primary setting.
- Idealized playback-reference subtraction reduced playback-only residual confidence to 0.000.
- User speech over playback survived residual subtraction and emitted a candidate at the expected user onset.
- Near-end barge-in survived residual subtraction, but with weak confidence.

Proposed plan:

- Treat playback reference as required for target architecture validation.
- Track separate mic, playback reference, and residual observation metadata.
- Record `echo_likelihood_mode=degraded_playback_reference_required` until a real AEC or robust residual estimator is evaluated.
- Record playback-only false-positive risk as a blocking condition for any harness result that lacks a playback reference.
- Keep `playback_reference_ref` as metadata-only in shareable reports.

## Truncate Ownership Boundary

MVP-0 mapping:

- `SPEECH_START_DETECTED` is Duplex evidence.
- `SPEECH_END_DETECTED` is Duplex evidence.
- `BARGE_IN_CANDIDATE` is Duplex candidate evidence.
- `INTERRUPT_CANDIDATE` belongs to Interaction Controller.
- `TTS_TRUNCATE_REQUESTED` belongs to Interaction Controller.
- `TTS_TRUNCATED` can only be emitted by Talker/playback controller after actual stop offset is known.
- WebRTC VAD does not provide `semantic_close`.
- WebRTC VAD does not provide `assistant_directedness`.
- Deterministic replay does not rerun VAD; it consumes recorded metadata or synthetic fixture data.

The `client_stop_playback_simulation` rerun used:

- Request-side offset: 1040 ms.
- Talker-confirmed actual stop offset: 1100 ms.

This remains metadata-only evidence for offset separation. VAD, playback-reference residuals, client stream close, and model request cancellation cannot confirm `TTS_TRUNCATED`, because only the Talker/playback layer owns actual device stop state and final playback offset.

## Capability Matrix Implications

| capability | label | implication |
| --- | --- | --- |
| WebRTC VAD frame decision on synthetic PCM | real | `webrtcvad` made local frame decisions for 10/20/30 ms frames and modes 0/2/3. |
| `supports_streaming_input` | real by API shape, degraded for live device | Frame API supports streaming-style processing; microphone capture was not exercised. |
| `supports_streaming_output` | real by candidate metadata shape, not runtime wired | Harness can emit per-span metadata; no runtime events are produced. |
| `supports_audio_input` | real | 16-bit mono PCM at 16 kHz was accepted. |
| `supports_audio_timestamps` | real for frame offsets | Offsets are frame-derived synthetic timings, not device timings. |
| speech-start latency | real/degraded | Algorithmic result is real for synthetic PCM; live capture latency is unknown. |
| speech-end hangover | real/degraded | Harness can measure configured hangover; UX policy is not decided. |
| false-positive handling | degraded | Tone and noise false positives require eval gating and policy. |
| playback reference / echo likelihood | degraded | Idealized subtraction validates shape, not real AEC robustness. |
| `BARGE_IN_CANDIDATE` support | degraded | Candidate metadata is plausible only with playback reference and conservative policy. |
| `supports_semantic_close` | unsupported for WebRTC VAD | Must remain unknown, rule/mock, or provided by a separate approved Duplex capability. |
| `supports_assistant_directedness` | unsupported for WebRTC VAD | Must remain unknown, rule/mock, or provided by a separate approved Duplex capability. |
| `supports_tts_truncate` | unsupported at VAD layer | Talker/playback owns truncate confirmation. |
| cancellation | unsupported / not applicable | Local VAD frame processing should stop with the stream; it does not confirm adapter or model cancellation. |
| emotion, audio caption, tool calling, TTS output | unsupported | Out of scope for WebRTC VAD. |
| natural speech quality | unknown | No real user recording or natural generated speech fixture was used in this rerun. |
| live CPU/device behavior | unknown | Offline in-memory probe only. |

## Risks / Gaps

- Synthetic waveforms are not natural speech. The harness can prove repeatability and event shape, not final quality.
- WebRTC VAD classified deterministic tone and seeded white noise as speech-like activity in the rerun.
- Playback-only raw mic activity is a severe false barge-in risk without playback reference.
- Idealized subtraction is not equivalent to real acoustic echo cancellation.
- 30 ms frames can be too coarse for short backchannels.
- The rerun did not validate real microphone capture, frontend playback, device scheduling, room echo, CPU load, or end-to-end latency.
- `say` was present but not used in this rerun; prior local reports observed unusable zero-packet output in this environment.
- `silero_vad` and `torch` remain uninstalled, so Silero quality comparison is intentionally outside this step.
- No committed schema exists yet for the proposed observation JSONL; the schema should be part of the next approved harness-code step.

## Recommendation

Approve a small spike-local harness implementation under `tools/model_spikes/duplex_vad/` before adapter profile hardening.

Recommended next step:

- Implement only the harness files listed above.
- Keep all raw/generated audio under `/private/tmp`.
- Emit metadata-only JSONL validated by a small schema.
- Pin `webrtcvad==2.0.10` and `setuptools<81`.
- Make 20 ms / mode 2 the default probe setting, while retaining the required 10/20/30 ms and mode 0/2/3 comparison.
- Preserve the MVP-0 ownership boundary: Duplex emits evidence and candidates; Interaction Controller owns interrupt and truncate requests; Talker/playback owns `TTS_TRUNCATED`.

Do not enter runtime integration, real business adapter work, or Duplex adapter profile hardening yet. The harness is worth building because it gives repeatable local evidence for WebRTC VAD latency, false positives, and playback-reference requirements without expanding MVP scope.
