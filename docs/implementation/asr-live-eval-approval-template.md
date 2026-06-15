# ASR Live Eval Approval Template

This template is required before any ASR live-eval command may move beyond
provider-free dry-run validation. Filling this template does not authorize a
runtime ASR adapter, provider transport, provider SDK, secret read, business
runtime connection, ADR change, or canonical event change.

## Approval Status

- approval_status: pending
- approver:
- approval_date:
- approved_eval_scope: synthetic_asr_live_eval_dry_run_only

## Provider And Model

- provider_name:
- model_alias:
- model_alias_repin_date:
- provider_transport_allowance: dry_run_validation_only

The Goal C command skeleton remains dry-run and validation-only even when this
packet is complete. Any real HTTP, WebSocket, SDK, or provider transport needs
a separate approved goal.

## Credential Handling

- credential_source:
- credential_runtime_scope:

Rules:

- Do not paste API keys, tokens, cookies, credentials, bearer values, or
  authorization headers into this file.
- Goal C does not read environment variables, secret files, credential stores,
  provider SDK credentials, or authorization headers.
- Credential values must not be printed, logged, serialized, written to Event
  Journal payloads, written to replay fixtures, written to diagnostics, or
  included in failure reasons.

## Bounds

- max_request_count:
- max_cost_quota:
- per_request_timeout_ms:
- retry_budget:

The dry-run validator must fail closed if any bound is absent.

## Synthetic Input Set

- synthetic_input_set_path:
- input_redaction_status:
- real_user_input_included: false

Synthetic ASR inputs must contain metadata refs only. They must not contain raw
audio, raw transcript, raw provider request body, raw provider response body,
headers, prompt dumps, secrets, real user input, local filesystem paths, or
large raw web content.

## Output And Redaction

- output_storage_path:
- redaction_policy:
- cleanup_policy:
- aggregate_metadata_commit_policy:

Allowed output storage paths must be local-only ignored locations, such as
`diagnostics/`, `traces/`, `replays/local/`, or `outputs/`.

Committed artifacts may contain only synthetic, redacted, minimal aggregate
metadata. Raw audio, raw transcript, raw provider request body, raw provider
response body, headers, raw trace, generated audio, local replay cache, secrets,
real user input, and large raw web content must not be committed.

## Required Acknowledgement

- forbidden_commit_artifacts_acknowledged: false

Set this to `true` only after confirming the dry-run runner and output location
cannot commit forbidden artifacts.

## Expected Verification

Before any future live eval implementation:

```bash
./scripts/test tests/adapters/test_asr_live_eval_approval.py -q
git diff --check
```

The final report for this Goal C dry-run gate must include request counts,
output location, cleanup policy, aggregate metadata policy, and confirmation
that no provider call, provider SDK, secret read, raw audio, raw transcript, raw
provider body, raw trace, local replay cache, real user input, ADR change, or
canonical event change was introduced.
