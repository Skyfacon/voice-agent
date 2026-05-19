# Duplex VAD Model Spike Harness

This is a spike-local WebRTC VAD harness for model research. It is not a
runtime adapter and must not be imported by `src/voice_agent`.

## Scope

The harness generates deterministic synthetic PCM fixtures, runs WebRTC VAD
over 10 ms / 20 ms / 30 ms frames and modes 0 / 2 / 3, and emits
metadata-only JSONL observations.

It is designed to support research reports for:

- `SPEECH_START_DETECTED` as Duplex evidence.
- `SPEECH_END_DETECTED` as Duplex evidence.
- `BARGE_IN_CANDIDATE` as Duplex candidate evidence.
- playback-reference residual behavior as degraded echo evidence.

It does not produce runtime events. It does not decide `INTERRUPT_CANDIDATE`,
`TTS_TRUNCATE_REQUESTED`, or `TTS_TRUNCATED`.

## Local Setup

Use a temporary environment outside the repository:

```bash
python3 -m venv /private/tmp/voice-agent-model-spike-vad-venv-$(date +%s)
/private/tmp/voice-agent-model-spike-vad-venv-<id>/bin/python -m pip install \
  -r tools/model_spikes/duplex_vad/requirements.txt
```

The `setuptools<81` pin is present because `webrtcvad==2.0.10` imports
`pkg_resources` on Python 3.12.

## Run

```bash
/private/tmp/voice-agent-model-spike-vad-venv-<id>/bin/python \
  tools/model_spikes/duplex_vad/run_webrtcvad_probe.py \
  --contract-snapshot main@61e6afc \
  --candidate webrtcvad \
  --sample-rate-hz 16000 \
  --frame-ms 10,20,30 \
  --mode 0,2,3 \
  --cases all \
  --metadata-out /private/tmp/voice-agent-model-spike-vad-run-<id>/observations.jsonl
```

For local debug only, WAV export is allowed under `/private/tmp`:

```bash
python3 tools/model_spikes/duplex_vad/generate_synthetic_audio.py \
  --write-local-wav-dir /private/tmp/voice-agent-model-spike-vad-audio-<id>
```

The generator refuses to write WAV files outside `/private/tmp`.

## Self Check

```bash
/private/tmp/voice-agent-model-spike-vad-venv-<id>/bin/python \
  tools/model_spikes/duplex_vad/self_check.py
```

If `webrtcvad` is not installed, the dependency-backed probe check is skipped,
but fixture and schema checks still run.

## Safety Rules

- Do not commit raw audio.
- Do not commit local trace or replay cache.
- Do not use real user recordings.
- Do not install `silero_vad` or `torch` for this harness.
- Do not connect this harness to the main runtime.
- Deterministic replay should consume recorded metadata or synthetic fixtures;
  it should not rerun WebRTC VAD by default.
