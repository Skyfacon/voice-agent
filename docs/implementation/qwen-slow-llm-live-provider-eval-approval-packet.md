# Qwen Slow LLM Live Provider Eval Approval Packet Draft

This packet is a submission-safe draft for a future synthetic-only live eval.
It does not authorize running the eval in this Slice 8A work. The model alias
is a conservative placeholder and must be re-pinned by a human before Slice 8B.

## Approval Status

- approval_status: pending_human_live_eval_approval
- approval_date: 2026-06-11
- approved_eval_scope: synthetic_only_qwen_slow_llm

## Provider And Model

- model_alias: qwen-plus-human-repin-required
- model_alias_repin_date: 2026-06-11
- provider_transport_allowance: direct_http_only

## Credential Handling

- credential_source: human_provided_runtime_env_script
- credential_loading_command: source ~/.voice-agent-secrets/dashscope.env && test -n "$DASHSCOPE_API_KEY" && echo "DASHSCOPE_API_KEY present"
- credential_runtime_scope: adapter_internal_call_time_only

Credential values must not be pasted into this packet, printed, logged,
serialized, written to Event Journal payloads, written to replay fixtures, or
included in failure reasons.

## Bounds

- max_request_count: 3
- max_cost_quota: minimal_human_approved_quota
- per_request_timeout_ms: 30000
- retry_budget: 1

## Synthetic Input Set

- synthetic_input_set_path: tests/fixtures/synthetic/qwen-slow-llm-inputs.jsonl
- input_redaction_status: synthetic_minimal_metadata_refs_only
- real_user_input_included: false

## Output And Redaction

- output_storage_path: diagnostics/qwen-slow-llm/live-eval
- redaction_policy: metadata_only_no_raw_provider_body
- cleanup_policy: delete_local_outputs_after_summary
- aggregate_metadata_commit_policy: allowed_if_redacted_metadata_only

## Commit Safety Acknowledgement

- forbidden_commit_artifacts_acknowledged: true

Committed artifacts may contain only synthetic/redacted/minimal aggregate
metadata. Raw provider request bodies, raw provider response bodies, headers,
raw trace, raw audio, generated audio, local replay cache, secrets, real user
input, and large raw web content must not be committed.
