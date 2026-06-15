# ASR Live Eval Approval Packet

This packet records the approved Goal D provider discovery result and the
bounded synthetic live-eval gate. It contains no credential values, raw audio,
raw transcript, provider request body, provider response body, headers, or
Authorization material.

## Approval Status

- approval_status: approved_for_asr_provider_discovery_and_synthetic_live_eval
- approver: a123
- approval_date: 2026-06-15
- approved_eval_scope: asr_provider_discovery_and_synthetic_live_eval

## Provider And Model

- provider_name: Alibaba Cloud Bailian / DashScope
- model_alias: qwen3-asr-flash
- model_alias_repin_date: 2026-06-15
- provider_transport_allowance: direct_http_only_preferred_sdk_allowed_only_if_official_docs_require_it
- provider_endpoint_ref: provider-url://dashscope/qwen-asr/openai-compatible-chat-completions
- provider_endpoint_shape: openai_compatible_chat_completions_multimodal_input_audio_data_url
- docs_source_urls: https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference, https://help.aliyun.com/zh/model-studio/model-pricing
- provider_sdk_assumption: sdk_not_required_direct_http_only
- model_alias_basis: official_qwen_asr_api_reference_checked_2026_06_15

The official Qwen-ASR API reference checked on 2026-06-15 documents
`qwen3-asr-flash` for the OpenAI-compatible
`https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` endpoint,
with audio supplied as an `input_audio` Base64 Data URL and text returned via
the chat completion response content. The pricing page checked on 2026-06-15
lists Qwen3-ASR-Flash and a China-mainland free quota. Any paid or quota
warning during execution must stop the run.

## Credential Handling

- credential_source: runtime_only_user_provided_environment_or_shell_session
- credential_runtime_scope: adapter_internal_call_time_only

Credential values must not be pasted into this packet, printed, logged,
serialized, written to Event Journal payloads, written to replay fixtures, or
included in failure reasons. The runner may read the runtime credential only
inside the adapter-internal call-time gate.

## Bounds

- max_request_count: 10
- max_cost_quota: free_quota_only_stop_on_any_paid_or_quota_warning
- per_request_timeout_ms: 30000
- retry_budget: 1

## Synthetic Input Set

- synthetic_input_set_path: tests/fixtures/synthetic/asr-live-eval-inputs.jsonl
- input_redaction_status: synthetic_metadata_refs_only
- real_user_input_included: false

Synthetic records contain metadata refs only. The runner may generate bounded
synthetic audio under ignored local-only output paths for call-time use and must
delete local outputs after summarizing.

## Output And Redaction

- output_storage_path: diagnostics/asr/live-eval
- redaction_policy: metadata_only_no_raw_audio_transcript_or_provider_body
- cleanup_policy: delete_local_outputs_after_summary
- aggregate_metadata_commit_policy: allowed_if_redacted_metadata_only

## Required Acknowledgement

- forbidden_commit_artifacts_acknowledged: true

Committed artifacts may contain only synthetic, redacted, minimal aggregate
metadata. Raw audio, raw transcript, raw provider request body, raw provider
response body, headers, raw trace, generated audio, local replay cache,
secrets, real user input, and large raw web content must not be committed.
