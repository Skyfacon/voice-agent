# TTS Playback / Truncate Eval Harness

This is a spike-local TTS playback/truncate metadata harness for model
research. It is not a runtime adapter and must not be imported by
`src/voice_agent`.

## Scope

The harness emits deterministic synthetic JSONL observations for the
CosyVoice playback/truncate proof plan.

It is designed to support research reports for:

- basic TTS synthesis metadata;
- streaming audio metadata without storing audio;
- Talker-owned playback span/progress/commit metadata;
- Interaction-owned truncate request metadata;
- Talker-owned truncate completion with actual stop offset metadata;
- timeout, retry, client close, provider cancellation, late audio, partial
  audio, and format mismatch boundaries.

It does not produce runtime events. It does not decide user acknowledgement,
SemanticCommitment, confirmation, tool authorization, task completion,
resolved arguments, semantic close, assistant-directedness, interrupt, or
barge-in.

## Run

Dry-run writes metadata only and never calls a provider:

```bash
python3 -B -m tools.model_spikes.tts_playback_eval dry-run \
  --case-set smoke \
  --out /private/tmp/voice-agent-tts-playback-eval/smoke/observations.jsonl
```

Validate a JSONL file:

```bash
python3 -B -m tools.model_spikes.tts_playback_eval validate \
  --schema tools/model_spikes/tts_playback_eval/schemas/tts_playback_observation.schema.json \
  --observations /private/tmp/voice-agent-tts-playback-eval/smoke/observations.jsonl
```

Write a commit-safe summary:

```bash
python3 -B -m tools.model_spikes.tts_playback_eval summarize \
  --observations /private/tmp/voice-agent-tts-playback-eval/smoke/observations.jsonl \
  --out docs/research/spikes/tts-cosyvoice-playback-eval-dry-run-YYYY-MM-DD.md
```

The `live-run` command fails closed. A live provider probe requires a separate
human approval path and is not implemented here.

## Safety Rules

- Do not connect this harness to the main runtime.
- Do not use real user text or recordings.
- Do not commit generated audio.
- Do not commit provider request or response bodies.
- Do not commit local traces or replay caches.
- Deterministic replay should consume recorded metadata or synthetic fixtures;
  it should not rerun TTS by default.
