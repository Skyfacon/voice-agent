# Slow LLM Retry Eval Dry-Run Summary

## Status

dry_run_metadata_only

## Observation Count

- observations: 5
- unique cases: 5

## Capability Labels

- `prior_observed_degraded_client_timeout`: 1
- `prior_observed_real_bounded_repair`: 1
- `prior_observed_real_tool_proposal_shape`: 1
- `prior_observed_real_validated_json`: 1
- `synthetic_old_plan_stale`: 1

## Case Results

| case | kind | expected evidence label | parse | schema | retry count | stale | may advance current task | tool proposal | failure |
| --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| validated_json_current_plan | adapter_validation_observation | prior_observed_real_validated_json | pass | pass | 0 | False | False | False | None |
| bounded_schema_repair_success | adapter_retry_observation | prior_observed_real_bounded_repair | pass | pass | 2 | False | False | False | None |
| client_timeout_probe | adapter_timeout_observation | prior_observed_degraded_client_timeout | not_applicable | not_applicable | 0 | False | False | False | client_timeout |
| late_result_old_plan_stale_probe | late_result_observation | synthetic_old_plan_stale | pass | pass | 0 | True | False | False | None |
| tool_proposal_confirmation_required_probe | tool_proposal_boundary_observation | prior_observed_real_tool_proposal_shape | pass | pass | 0 | False | False | True | None |

## Boundary Notes

- Slow LLM output is planning evidence, not SlowTask state.
- Local validation must pass before SlowTask consumption.
- Client timeout or abort is not provider-confirmed cancellation.
- Old-plan and terminal late results are stale/debug metadata by default.
- Stale output requires explicit SlowTask adopt/rebase before reuse.
- Tool-like output remains proposal evidence only.
- Model output cannot accept confirmation, authorize tools, mutate UI, or complete tasks.
- Deterministic replay consumes metadata or synthetic fixtures and does not rerun providers.

## Privacy Notes

- No provider request or response bodies are stored.
- No local traces or replay caches are stored.
- No real user input is used.
- No tools are executed.
