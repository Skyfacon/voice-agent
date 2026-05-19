# Duplex / VAD Run: WebRTC VAD Harness

## Status

executed_spike_local_harness_metadata_only

## Date

2026-05-11

## Contract Snapshot

- `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- This report is research evidence only. It is not runtime integration, does not create a business adapter, and does not change ADR, event registry, adapter capability, replay, source, or test contracts.

## Question

Can the new spike-local WebRTC VAD harness under `tools/model_spikes/duplex_vad/` reproduce the Phase 5b / 5c synthetic probe as metadata-only output, while keeping raw artifacts out of the repository and preserving the Duplex / Interaction Controller / Talker ownership boundary?

## Harness Under Test

Harness files:

- `tools/model_spikes/duplex_vad/README.md`
- `tools/model_spikes/duplex_vad/requirements.txt`
- `tools/model_spikes/duplex_vad/generate_synthetic_audio.py`
- `tools/model_spikes/duplex_vad/run_webrtcvad_probe.py`
- `tools/model_spikes/duplex_vad/self_check.py`
- `tools/model_spikes/duplex_vad/schemas/duplex_vad_observation.schema.json`
- `tools/model_spikes/duplex_vad/runs/README.md`

The harness does not import `src/voice_agent`, does not emit canonical runtime events, and does not write generated audio by default. Optional WAV export is restricted to `/private/tmp`.

## Local Dependency Handling

- Temporary venv: `/private/tmp/voice-agent-model-spike-vad-venv-NmOI4R`
- Temporary run dir: `/private/tmp/voice-agent-model-spike-vad-run-gVBDrs`
- Installed packages in the temporary venv:
  - `setuptools==80.10.2`
  - `webrtcvad==2.0.10`
- The first install attempt inside the sandbox could not reach the package index; a human-approved escalated install succeeded.
- `silero_vad` and `torch` were not installed.
- After extracting the report summaries, the temporary venv and run dir were removed.

## Commands Run

Self-check:

```bash
/private/tmp/voice-agent-model-spike-vad-venv-NmOI4R/bin/python -B \
  tools/model_spikes/duplex_vad/self_check.py
```

Full harness run:

```bash
/private/tmp/voice-agent-model-spike-vad-venv-NmOI4R/bin/python -B \
  tools/model_spikes/duplex_vad/run_webrtcvad_probe.py \
  --contract-snapshot main@61e6afc \
  --candidate webrtcvad \
  --sample-rate-hz 16000 \
  --frame-ms 10,20,30 \
  --mode 0,2,3 \
  --cases all \
  --metadata-out /private/tmp/voice-agent-model-spike-vad-run-gVBDrs/observations.jsonl \
  --summary-out /private/tmp/voice-agent-model-spike-vad-run-gVBDrs/summary.json
```

## Synthetic Inputs

The harness generated the required synthetic cases:

- `speech_start_clean`
- `speech_end_clean`
- `short_backchannel`
- `silence_only`
- `noise_or_tone`
- `white_noise`
- `clipped_start`
- `tts_playback_only`
- `user_barge_in_over_tts`
- `near_end_barge_in`
- `client_stop_playback_simulation`

No real user recording was used. No generated audio was written for the full harness run.

## Harness Output Summary

The full run emitted:

| metric | value |
| --- | ---: |
| case count | 11 |
| observation count | 91 |
| VAD cases | 10 cases x 3 frame sizes x 3 modes = 90 observations |
| metadata-only playback simulation | 1 observation |
| `raw_audio_committed` | false for all observations |
| `contains_real_user_input` | false for all observations |
| `contains_raw_trace` | false for all observations |
| `deterministic_replay_reruns_vad` | false for all observations |

Self-check result:

- 4 checks ran.
- 4 checks passed.
- No dependency-backed check was skipped in the temporary venv.

## Primary 20 ms / Mode 2 Results

| case | start | start emit latency | end | end offset error | hangover budget | confidence | raw confidence |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `speech_start_clean` | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 | n/a |
| `speech_end_clean` | 500 ms | 40 ms | 1500 ms | +100 ms | 200 ms | 0.526 | n/a |
| `short_backchannel` | 300 ms | 40 ms | 580 ms | +100 ms | 200 ms | 0.359 | n/a |
| `silence_only` | none | none | none | none | none | 0.000 | n/a |
| `noise_or_tone` | 500 ms | n/a | 1620 ms | n/a | 200 ms | 0.560 | n/a |
| `white_noise` | 500 ms | n/a | 1600 ms | n/a | 200 ms | 0.550 | n/a |
| `clipped_start` | 300 ms | 40 ms | 1060 ms | +110 ms | 200 ms | 0.521 | n/a |
| `tts_playback_only` | none | none | none | none | none | 0.000 | 1.000 |
| `user_barge_in_over_tts` | 1000 ms | 40 ms | 1700 ms | +100 ms | 200 ms | 0.269 | 1.000 |
| `near_end_barge_in` | 2200 ms | 40 ms | 2500 ms | +120 ms | 200 ms | 0.115 | 1.000 |
| `client_stop_playback_simulation` | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

The playback simulation kept ownership metadata separate:

- request offset: 1040 ms
- actual stop offset: 1100 ms
- truncate owner: `talker_playback_controller`

## Frame / Mode Comparison

Clean speech result:

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

Additional matrix notes:

- `short_backchannel` detected across all tested settings, but 30 ms / mode 3 shifted start to 390 ms and raised emit latency to 150 ms.
- `silence_only` stayed silent across all tested settings.
- `noise_or_tone` produced false positives across tested settings; 20 ms / mode 3 reduced confidence to 0.080 but did not remove the risk.
- `white_noise` produced false positives in this harness run; 10 ms / mode 2 and 10 ms / mode 3 were low at 0.040, while 20 ms / mode 2 stayed high at 0.550.
- `tts_playback_only` residual stayed silent across all tested settings, while raw mic confidence was 1.000.
- `user_barge_in_over_tts` residual was detected across all tested settings.
- `near_end_barge_in` residual was detected across all tested settings, but remained weak, around 0.08 to 0.138 confidence depending on frame/mode.

## Comparison to Prior One-Off Probe

The harness reproduced the main Phase 5b / 5c findings:

- Primary 20 ms / mode 2 clean speech start remained 500 ms with 40 ms emit latency.
- Primary 20 ms / mode 2 clean speech confidence remained 0.526.
- Playback-only raw mic confidence remained 1.000, while residual confidence remained 0.000.
- User barge-in over playback remained detectable at 1000 ms with 40 ms emit latency.
- Non-speech false-positive risk remained visible for tone and white noise.

The near-end synthetic case produced a small end-offset difference from the hand-run summary, but the qualitative result is unchanged: near-end barge-in remains detectable and low-confidence, so it needs conservative policy and future echo-quality evaluation.

## Replay-Safe Metadata Review

The harness output is suitable as research observation metadata:

- It records `contract_snapshot`, candidate, deployment mode, output mode, frame size, mode, synthetic case, seed, timing offsets, confidence summary, echo mode, and safety flags.
- It does not require raw audio in the repository.
- It does not contain real user input.
- It does not contain a raw trace.
- It explicitly marks that deterministic replay should not rerun VAD.

Future deterministic replay should consume recorded metadata or synthetic fixture data. A future re-eval path must be explicit and must label regenerated output as re-eval evidence, not original runtime fact.

## Ownership Boundary Review

The harness preserves the MVP-0 mapping:

- `SPEECH_START_DETECTED` remains Duplex evidence.
- `SPEECH_END_DETECTED` remains Duplex evidence.
- `BARGE_IN_CANDIDATE` remains Duplex candidate evidence.
- `INTERRUPT_CANDIDATE` belongs to Interaction Controller.
- `TTS_TRUNCATE_REQUESTED` belongs to Interaction Controller.
- `TTS_TRUNCATED` belongs to Talker/playback controller after actual stop offset is known.
- WebRTC VAD does not provide `semantic_close`.
- WebRTC VAD does not provide `assistant_directedness`.

## Capability Matrix Implications

| capability | harness result |
| --- | --- |
| WebRTC VAD frame decisions | observed real for synthetic PCM |
| 10/20/30 ms frame support | observed real |
| mode 0/2/3 comparison | observed real |
| speech-start latency | observed real for synthetic PCM; live device latency unknown |
| speech-end hangover | observed by frame size; UX policy not decided |
| playback-only residual blocking | observed with idealized subtraction; real AEC not validated |
| false-positive risk | observed degraded risk for tone and white noise |
| barge-in candidate metadata | degraded until playback reference and policy are stronger |
| semantic close | unsupported by WebRTC VAD |
| assistant-directedness | unsupported by WebRTC VAD |
| TTS truncate confirmation | unsupported at VAD layer; playback-owned |

## Trace and Privacy Review

- No runtime source, tests, ADR, or spec files were modified by this run.
- No real user recording was used.
- No raw audio was committed.
- No generated WAV was written for the full harness run.
- The JSONL and summary output stayed under `/private/tmp`.
- The temporary venv and run output were removed after report extraction.

## Recommendation

Treat the WebRTC VAD harness as successfully established for repeatable spike-local probing.

Next recommended action:

1. Keep this harness out of the main runtime.
2. Use it for future Duplex/VAD research reruns and metadata-only reports.
3. Move on to the first adapter profile draft, starting with the strongest candidate: DashScope / Bailian Qwen structured JSON for Slow LLM.

Do not start Duplex/VAD adapter profile hardening yet. Playback reference, real echo behavior, natural speech quality, and live device latency still need stronger evidence.
