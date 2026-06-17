# MVP-5 Live Eval Approval Template

This template is for live provider smoke opt-in only. It is not used by default
tests, deterministic replay, committed fixtures, or CI.

## Approval Scope

- Goal: run an approved MVP-5 local wav smoke through adapter-owned ASR and
  Thinker live provider paths.
- Provider adapter: list the adapter ids for ASR and Thinker.
- Local wav opt-in: required for any local wav read.
- Live provider opt-in: required for any provider request.
- Metadata-only output: required for stdout and local summaries.
- Replay never reruns provider.

## Required Packet Fields

Use structured metadata equivalent to:

```json
{
  "approval_id": "mvp5-live-eval-human-approved",
  "live_provider_opt_in": true,
  "local_wav_opt_in": true,
  "metadata_only_output": true,
  "replay_reruns_provider": false,
  "provider_adapter_ids": ["mvp5_asr_adapter", "mvp5_thinker_adapter"],
  "credential_env_var_name": "MVP5_PROVIDER_KEY",
  "max_provider_calls": 2,
  "timeout_ms": 30000,
  "safe_output_ref": "summary://mvp5/live-redacted-placeholder"
}
```

## Required Human Checks

- request budget: set the maximum provider request count before running.
- timeout: set a bounded per-request timeout before running.
- provider adapter: confirm all provider execution goes through adapters.
- local wav opt-in: confirm the wav is local-only and not committed.
- metadata-only output: confirm summaries contain refs, ids, status, and safety
  booleans only.

## Prohibited Content

Do not paste or commit secrets, tokens, cookies, authorization headers, raw wav
bytes, local wav paths, file names, raw transcripts, provider payloads, provider
schemas, prompt dumps, diagnostics, traces, local replay caches, or unredacted
real user input.

The approval packet may name the credential environment variable. It must never
include the secret material stored in that environment variable.

## Replay Policy

Replay never reruns provider. Redacted or minimal replay fixtures may use only
recorded safe refs and metadata. If live smoke output is later converted into a
fixture, first reduce it to synthetic, redacted, or minimal metadata.
