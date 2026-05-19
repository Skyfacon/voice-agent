# Thinker / Composer Eval Harness

Spike-local dry-run harness for Thinker SemanticFrame and Thinker-as-Composer boundary observations.

This package is intentionally metadata-only:

- It does not import `src/voice_agent`.
- It does not call a provider by default.
- It does not execute tools.
- It does not store provider request or response bodies.
- It does not store raw audio, local traces, replay cache, or real user input.
- It only emits synthetic JSONL observations for research planning.

The live provider path is fail-closed until a human explicitly approves a separate spike.

## Commands

```bash
python3 -B -m tools.model_spikes.thinker_composer_eval dry-run --case-set smoke --out /private/tmp/voice-agent-thinker-composer-eval/smoke/observations.jsonl
python3 -B -m tools.model_spikes.thinker_composer_eval validate --schema tools/model_spikes/thinker_composer_eval/schemas/thinker_composer_observation.schema.json --observations /private/tmp/voice-agent-thinker-composer-eval/smoke/observations.jsonl
python3 -B -m tools.model_spikes.thinker_composer_eval summarize --observations /private/tmp/voice-agent-thinker-composer-eval/smoke/observations.jsonl --out docs/research/spikes/thinker-composer-boundary-eval-dry-run-2026-05-12.md
```

Use `full_synthetic` for the complete dry-run matrix.
