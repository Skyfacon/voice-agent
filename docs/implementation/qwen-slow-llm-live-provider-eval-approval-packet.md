# Qwen Slow LLM Live Provider Eval Approval Packet

This packet is submission-safe metadata for a synthetic-only live eval. It
records the human-provided credential bootstrap command without credential
values, and it does not contain raw provider request or response bodies.

The model alias is re-pinned from the Qwen Slow LLM research handoff and the
official DashScope OpenAI-compatible model list checked on 2026-06-11. This
packet completes the runner approval gate, but executing the live eval still
requires the human-provided runtime credential bootstrap in the current shell.

## Approval Status

- approval_status: approved_for_synthetic_live_eval
- approval_date: 2026-06-11
- approved_eval_scope: synthetic_only_qwen_slow_llm

## Provider And Model

- model_alias: qwen3.6-plus
- model_alias_repin_date: 2026-06-11
- provider_transport_allowance: direct_http_only
- endpoint_assumption: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
- provider_endpoint_ref: provider-url://dashscope/qwen/openai-compatible-chat-completions
- model_alias_basis: research_handoff_selected_qwen3_6_plus_and_official_dashscope_compatible_model_list

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

## Request And Response Assumptions

- request_body_shape_assumption: openai_compatible_chat_completions_json_object_non_streaming
- request_messages_assumption: system_instruction_plus_synthetic_metadata_user_payload
- qwen3_6_latency_bound_assumption: non_streaming_eval_disables_thinking_and_sets_max_completion_tokens
- response_text_extraction_assumption: choices_0_message_content_with_output_text_fallback
- structured_output_assumption: single_json_object_matching_slow_llm_qwen_evidence_v1
- validation_assumption: parse_then_validate_before_any_event_emission
- provider_sdk_assumption: sdk_not_required_direct_http_only

Live eval must verify that Qwen3.6 Plus still accepts the OpenAI-compatible
non-streaming chat completions request shape with JSON object output and returns
structured evidence text at `choices[0].message.content` or the existing
`output.text` fallback. Any mismatch must fail closed through the existing
adapter validation or request failure events.

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

## Known Risks To Verify During Live Eval

- Provider-confirmed cancellation is still unknown and not required for this eval.
- Provider response shape drift must be handled as validation failure or request
  failure without saving raw response bodies.
- Cost and quota remain limited to the three synthetic requests approved above.
- Timeout behavior must remain bounded by the 30000 ms per-request timeout and
  retry budget of 1.
