# Slow LLM Retry / Cancellation Eval Harness

This is a spike-local Slow LLM retry/cancellation metadata harness for model
research. It is not a runtime adapter and must not be imported by
`src/voice_agent`.

## Scope

The harness emits deterministic synthetic JSONL observations for the Slow LLM
retry, timeout, cancellation, late-result, stale-result, and validation eval
plan.

It is designed to support research reports for:

- structured JSON validation metadata;
- bounded retry metadata;
- client timeout, client abort, and provider-confirmed cancellation boundaries;
- late same-plan, stale old-plan, terminal-late, and explicit adopt/rebase
  metadata;
- tool proposal-only and confirmation boundary metadata;
- untrusted web evidence boundary checks.

It does not produce runtime events. It does not advance SlowTask state, accept
confirmation, execute tools, patch UI, emit SemanticCommitment, or decide
terminal task outcomes.

## Run

Dry-run writes metadata only and never calls a provider:

```bash
python3 -B -m tools.model_spikes.slow_llm_retry_eval dry-run \
  --case-set smoke \
  --out /private/tmp/voice-agent-slow-llm-retry-eval/smoke/observations.jsonl
```

Validate a JSONL file:

```bash
python3 -B -m tools.model_spikes.slow_llm_retry_eval validate \
  --schema tools/model_spikes/slow_llm_retry_eval/schemas/slow_llm_retry_observation.schema.json \
  --observations /private/tmp/voice-agent-slow-llm-retry-eval/smoke/observations.jsonl
```

Write a commit-safe summary:

```bash
python3 -B -m tools.model_spikes.slow_llm_retry_eval summarize \
  --observations /private/tmp/voice-agent-slow-llm-retry-eval/smoke/observations.jsonl \
  --out docs/research/spikes/slow-llm-retry-eval-dry-run-YYYY-MM-DD.md
```

The `live-run` command fails closed. A live provider probe requires a separate
human approval path and is not implemented here.

## Safety Rules

- Do not connect this harness to the main runtime.
- Do not use real user input.
- Do not commit provider request or response bodies.
- Do not commit local traces or replay caches.
- Do not execute tools or mutate UI.
- Deterministic replay should consume recorded metadata or synthetic fixtures;
  it should not rerun providers by default.
