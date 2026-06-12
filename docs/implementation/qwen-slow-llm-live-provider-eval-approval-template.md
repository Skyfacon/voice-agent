# Qwen Slow LLM Live Provider Eval Approval Template

This template is required before any Qwen/DashScope live-provider eval command
is added or run. Filling this template does not by itself authorize broad live
provider use; it authorizes only the explicitly bounded synthetic eval described
here.

## Approval Status

- approval_status: pending
- approver:
- approval_date:
- approved_eval_scope: synthetic_only_qwen_slow_llm

## Provider And Model

- model_alias:
- model_alias_repin_date:
- provider_transport_allowance:

Allowed `provider_transport_allowance` examples:

- `direct_http_only`
- `provider_sdk_allowed`
- `direct_http_or_sdk_allowed`

The selected transport must remain adapter-internal.

## Credential Handling

- credential_source:
- credential_loading_command:
- credential_runtime_scope:

Rules:

- Do not paste API keys, tokens, cookies, credentials, bearer values, or
  authorization headers into this file.
- Credential loading must be runtime-only and adapter-internal.
- Credential values must not be printed, logged, serialized, written to Event
  Journal payloads, written to replay fixtures, or included in failure reasons.

## Bounds

- max_request_count:
- max_cost_quota:
- per_request_timeout_ms:
- retry_budget:

The live eval runner must fail closed if any bound is absent.

## Synthetic Input Set

- synthetic_input_set_path:
- input_redaction_status:
- real_user_input_included: false

Synthetic inputs must not contain real user input, raw web content, secrets, or
provider output.

## Output And Redaction

- output_storage_path:
- redaction_policy:
- cleanup_policy:
- aggregate_metadata_commit_policy:

Allowed output storage paths must be local-only ignored locations, such as
`diagnostics/`, `traces/`, or `replays/local/`.

Committed artifacts may contain only synthetic/redacted/minimal metadata. Raw
provider request bodies, raw provider response bodies, headers, raw trace, raw
audio, generated audio, local replay cache, secrets, real user input, and large
raw web content must not be committed.

## Required Acknowledgement

- forbidden_commit_artifacts_acknowledged: false

Set this to `true` only after confirming the eval runner and output directory
cannot commit forbidden artifacts.

## Expected Verification

Before live eval:

```bash
./scripts/test tests/adapters/test_qwen_slow_llm_adapter_skeleton.py -q
./scripts/test -q
```

After live eval:

```bash
git status --short --branch
```

The final report must include request counts, aggregate status counts,
redacted failure categories, timeout/retry counts, output location, cleanup
status, and confirmation that no raw provider body or secret was committed.
