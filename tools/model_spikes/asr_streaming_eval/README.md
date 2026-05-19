# ASR Qwen-ASR Streaming Eval Harness

This is a spike-local ASR metadata harness for model research. It is not a
runtime adapter and must not be imported by `src/voice_agent`.

## Scope

The harness emits deterministic synthetic JSONL observations for the Qwen-ASR
streaming, timestamp, cancellation, retry, and late-output proof plan.

It is designed to support research reports for:

- final transcript evidence as ASR text projection;
- response streaming output as partial/final ASR evidence;
- timestamp and word-alignment metadata normalization;
- non-speech, playback echo, timeout, retry, cancellation, and late output
  boundary checks.

It does not produce runtime events. It does not decide turn ingress,
semantic close, assistant-directedness, confirmation, tool authorization,
task completion, resolved arguments, or risk warnings.

## Run

Dry-run writes metadata only and never calls a provider:

```bash
python -m tools.model_spikes.asr_streaming_eval dry-run \
  --case-set smoke \
  --out /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl
```

Validate a JSONL file:

```bash
python -m tools.model_spikes.asr_streaming_eval validate \
  --schema tools/model_spikes/asr_streaming_eval/schemas/asr_streaming_observation.schema.json \
  --observations /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl
```

Write a commit-safe summary:

```bash
python -m tools.model_spikes.asr_streaming_eval summarize \
  --observations /private/tmp/voice-agent-asr-streaming-eval/smoke/observations.jsonl \
  --out docs/research/spikes/asr-qwen-asr-streaming-eval-run-YYYY-MM-DD.md
```

The `live-run` command fails closed. A live provider probe requires a separate
human approval path and is not implemented here.

## Safety Rules

- Do not connect this harness to the main runtime.
- Do not use real user recordings.
- Do not commit audio recordings.
- Do not commit provider request or response bodies.
- Do not commit local traces or replay caches.
- Deterministic replay should consume recorded metadata or synthetic fixtures;
  it should not rerun ASR by default.
