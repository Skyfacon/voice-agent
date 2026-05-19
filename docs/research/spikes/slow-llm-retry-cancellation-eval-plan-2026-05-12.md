# Slow LLM Retry / Cancellation Eval Plan

## Status

planned_metadata_only_eval

This document is research planning only. It does not authorize runtime integration, real business adapter work, provider calls, spike-local code, ADR changes, event registry changes, replay spec changes, or MVP scope expansion.

## Date

2026-05-12

## Contract Snapshot

- Default contract snapshot: `main@61e6afc`
- MVP-0 closeout reference: `22ddbf4 fix: harden mvp0 trace and replay safety`
- SlowTask ownership and confirmation contract: ADR-016
- Adapter capability contract: ADR-011 and `docs/specs/model-adapter-capabilities.md`
- Event and replay boundary: `docs/specs/event-registry.md` and `docs/specs/replay-spec.md`

## Scope

This plan defines the retry, timeout, cancellation, late-result, stale-result, and validation evidence still needed before DashScope / Bailian Qwen can move from strong structured JSON research evidence toward Slow LLM adapter profile hardening.

In scope:

- Slow LLM structured JSON retry and failure proof requirements.
- Adapter-shaped timeout and provider failure metadata.
- Provider-confirmed cancellation versus client-side abort/timeout.
- Late result handling bound to original `task_id`, `plan_version`, and `task_event_seq`.
- Old-plan result handling, stale evidence recording, and explicit adopt/rebase requirements.
- Streaming partial JSON and schema validation boundaries.
- Tool proposal, confirmation, and demo side-effect boundaries.
- Replay-safe metadata-only JSONL shape for future eval output.

Out of scope:

- No changes to `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`.
- No provider call in this thread.
- No main runtime wiring.
- No real business adapter.
- No spike-local harness implementation in this thread.
- No raw provider body, raw trace, local replay cache, real user input, or secret-bearing request metadata committed.
- No tool execution, UI mutation, external action, confirmation acceptance, or SlowTask state transition from raw model output.

## Source Evidence

Primary evidence:

- `docs/research/spikes/slow-llm-dashscope-qwen-json-run-2026-05-11.md`
- `docs/research/profiles/slow-llm-qwen-capability-profile-draft-2026-05-11.md`

Comparison context:

- `docs/research/spikes/slow-llm-deepseek-json-run-2026-05-11.md`

Coordination evidence:

- `docs/research/model-spike-phase-summary-2026-05-11.md`
- `docs/research/model-spike-execution-plan.md`
- `docs/research/model-spike-integration-ledger.md`
- `docs/research/model-spike-plan.md`
- `docs/research/model-selection.md`

Contract evidence:

- `AGENTS.md`
- `docs/adr/ADR-016 SlowTask Lifecycle and Confirmation State Contract.md`
- `docs/adr/ADR-011 Model Adapter Capability Contract.md`
- `docs/specs/model-adapter-capabilities.md`
- `docs/specs/event-registry.md`
- `docs/specs/replay-spec.md`

Current evidence labels:

| Evidence item | Current label | Notes |
| --- | --- | --- |
| Qwen structured JSON output | `observed_real` | Main synthetic cases parsed and passed strict local schema validation. |
| Missing required slot behavior | `observed_real` | Existing run emitted `INSUFFICIENT_EVIDENCE_FOR_ACTION` instead of guessing. |
| Conflicting evidence preservation | `observed_real` | Existing run did not invent a resolved location. |
| Synthetic web evidence boundary | `observed_real` | Existing run treated synthetic untrusted web evidence as evidence, not instruction. |
| Tool proposal shape | `observed_real` for schema-level proposal | Existing run did not enable provider-native tool execution. |
| Weak-schema validation failure detection | `observed_real` | Local validator caught missing required fields. |
| Bounded schema repair | `observed_real` | Existing run converged after two repair attempts. |
| Client-side timeout | `observed_degraded` | Timeout category observed; provider cancellation was not confirmed. |
| Provider-confirmed cancellation | `unknown` | Must not be inferred from timeout or client abort. |
| Streaming structured JSON | `docs_only_unobserved` | API surface exists, but usable streaming JSON was not tested. |
| Provider-side error/rate behavior | `unknown` | Not directly exercised in the Qwen run. |
| DeepSeek live comparison | `unknown_runtime` | Not executed because local access was unavailable. |

## Candidate Identity

| Field | Planned value | Evidence label | Notes |
| --- | --- | --- | --- |
| `adapter_type` | `slow_llm` | `observed_real` | Role matches the executed structured JSON probe. |
| `provider` | DashScope / Bailian | `observed_real` | Provider used in the 2026-05-11 run. |
| `model_name` | `qwen3.6-plus` | `observed_real` | Must be re-pinned on any future run day. |
| `deployment_mode` | `remote_api` | `observed_real` | OpenAI-compatible Chat Completions surface observed. |
| `endpoint_ref` | `dashscope-compatible-chat-completions` | `observed_real` | Ref only; no secret-bearing values. |
| `output_mode` | `real` after validation, `degraded` for timeout/failure | case-specific | Raw provider output is not runtime fact. |

DashScope / Bailian Qwen is a Slow LLM planning evidence provider candidate. It is not SlowTask Runtime, not Router, not Tool Executor, not Interaction Controller, not Composer, and not a confirmation or task-outcome owner.

## Eval Goals

1. Prove retry behavior can be represented as adapter metadata without advancing SlowTask state.
2. Prove schema validation failures are recorded before any SlowTask consumption.
3. Prove retry budgets are bounded and visible.
4. Prove client timeout, client abort, provider failure, and provider-confirmed cancellation are separate observation classes.
5. Prove late output remains bound to original `task_id`, `plan_version`, and `task_event_seq`.
6. Prove old-plan output becomes stale evidence unless SlowTask explicitly adopts/rebases it.
7. Prove provider-native or schema-level tool-like output remains proposal evidence only.
8. Prove deterministic replay consumes recorded metadata or synthetic fixtures and does not rerun providers.

## Non-Goals

- No live provider execution in this thread.
- No retry/cancellation code implementation.
- No runtime adapter.
- No real demo tool execution.
- No UI patch mutation.
- No direct Tool Executor authorization from model text.
- No confirmation acceptance from model text.
- No direct `SLOWTASK_STATE_CHANGED`, `SEMANTIC_COMMITMENT_EMITTED`, or terminal task outcome from raw model output.
- No claim that client timeout proves provider cancellation.
- No claim that DeepSeek is observed until a live comparison run exists.

## Synthetic Case Matrix

| case_id | Purpose | Input shape | Expected current label | Required future observations |
| --- | --- | --- | --- | --- |
| `validated_json_current_plan` | Baseline validated SlowTask planning evidence. | Synthetic current-plan task with complete fields. | `observed_real` for Qwen JSON if validation passes. | parse pass, schema pass, task binding, no state transition from raw output. |
| `missing_required_slot_retry_blocked` | Ensure missing fields do not become guesses. | Missing date/contact/location field. | `observed_real` for Qwen missing-evidence behavior. | `INSUFFICIENT_EVIDENCE_FOR_ACTION`-compatible metadata, no tool proposal unless safe. |
| `conflicting_evidence_retry_blocked` | Preserve conflict after retry. | ASR/Thinker/UserPatch conflict. | `observed_real` for Qwen conflict preservation. | ambiguity metadata, no invented resolution. |
| `weak_schema_validation_failure` | Record local validation failure. | Prompt/schema allows missing required fields. | `observed_real` for failure detection. | validation failure reasons, invalid output ref redacted/local-only. |
| `bounded_schema_repair_success` | Validate bounded repair metadata. | Initial schema failure plus validation errors. | `observed_real` from prior run. | retry count, retry reason, final schema pass. |
| `bounded_schema_repair_exhausted` | Prove final failure path. | Repeated malformed/invalid output fixture. | `unknown` | final degraded/failure label, no SlowTask state update. |
| `client_timeout_probe` | Distinguish timeout from cancellation. | Very short timeout or synthetic timeout record. | `observed_degraded` for Qwen client timeout. | timeout_ms, retryable flag, provider cancellation not confirmed. |
| `client_abort_unconfirmed_cancel_probe` | Distinguish abort from provider cancellation. | Client closes request before response. | `unknown` | abort reason, no cancellation success claim, late output policy. |
| `provider_confirmed_cancel_probe` | Check explicit provider cancellation semantics if available. | Future approved provider-supported cancel path. | `unknown` | explicit provider confirmation field, late output behavior. |
| `retryable_provider_failure_probe` | Prove transient provider failure shape. | Synthetic 5xx/rate/failure fixture or approved run. | `unknown` | `ADAPTER_REQUEST_RETRYING`-compatible metadata, backoff bucket, bounded attempts. |
| `non_retryable_provider_failure_probe` | Prove final fail-fast shape. | Synthetic auth/config/model-not-found class without secret values. | `unknown` | final failure category, retryable=false, no state advance. |
| `late_result_same_plan_probe` | Ensure late but current-plan result is reviewable. | Slow response arrives before plan advances. | `unknown` | result binding, validation pass, SlowTask review gate. |
| `late_result_old_plan_stale_probe` | Ensure old-plan result is stale. | UserPatch advances plan before result returns. | `unknown` | original binding retained, stale marker required, no current-plan advance. |
| `terminal_task_late_result_probe` | Ensure late result after terminal task is debug/stale only. | Task cancelled/failed/completed before result. | `unknown` | terminal state unchanged, stale/debug metadata only. |
| `explicit_stale_adoption_probe` | Prove adopt/rebase metadata shape. | Old result is explicitly useful. | `unknown` | `STALE_EVIDENCE_ADOPTED`-compatible metadata with adopted scope and reason. |
| `streaming_partial_json_probe` | Evaluate streaming partial JSON safely. | Streamed structured JSON chunks. | `docs_only_unobserved` | partial validity, final validation, no partial state mutation. |
| `malformed_json_probe` | Ensure parse failure is validation failure. | Invalid JSON fixture. | `unknown` | parse failure category, local/redacted invalid ref, no downstream consumption. |
| `tool_proposal_confirmation_required_probe` | Preserve proposal-only tool boundary. | Demo destructive action proposal. | `observed_real` for proposal shape only. | proposal metadata, confirmation required, no execution. |
| `web_evidence_injection_retry_probe` | Preserve untrusted evidence boundary through retries. | Synthetic web evidence with instruction-like text. | `observed_real` in prior run. | evidence remains non-instruction across retry prompts. |
| `context_limit_degradation_probe` | Record prompt/context too large behavior. | Oversized synthetic evidence pack or fixture. | `unknown` | context degradation, summarization/fail-fast decision, no silent truncation. |
| `deepseek_comparison_deferred_probe` | Mirror Qwen cases when local access exists. | Same synthetic cases on DeepSeek. | `unknown_runtime` | same validation, retry, timeout, and cancellation metadata for comparison. |

## Input Fixture Policy

- Use only synthetic task evidence, invented ids, and redacted summaries.
- Bind every request/result fixture to `task_id`, `plan_version`, `task_event_seq`, `adapter_request_id`, and causal source refs.
- Keep web/RAG-like content explicitly marked as untrusted evidence.
- Do not store raw provider bodies, raw traces, local replay cache, real user input, or secret-bearing request metadata.
- Store validation errors, latency buckets, retry counts, and failure categories only.
- Tool-like output fixtures must be proposal-only and must not imply execution.
- Shareable fixtures must be synthetic / redacted / minimal.

## Expected Observation Schema

A future approved eval should emit metadata-only JSONL. Each line should be safe to commit after review and should not be a runtime event.

```json
{
  "schema_version": "slow_llm_retry_cancellation_observation.v1",
  "contract_snapshot": "main@61e6afc",
  "case_id": "late_result_old_plan_stale_probe",
  "observation_id": "obs_slow_llm_retry_2026_05_12_001",
  "candidate": {
    "adapter_type": "slow_llm",
    "provider": "dashscope",
    "model_name": "qwen3.6-plus",
    "deployment_mode": "remote_api",
    "endpoint_ref": "dashscope-compatible-chat-completions",
    "output_mode": "real_or_degraded"
  },
  "task_binding": {
    "task_id": "task_synthetic_001",
    "plan_version": 1,
    "task_event_seq": 7,
    "adapter_request_id": "adapter_req_synthetic_001",
    "causal_source_refs": ["event_ref://synthetic/task_replanned_001"]
  },
  "adapter_result": {
    "result_arrival_order": "late_after_plan_advance",
    "parse_status": "pass",
    "schema_status": "pass",
    "retry_count": 0,
    "timeout_ms": null,
    "provider_cancel_confirmed": false,
    "raw_provider_body_stored": false
  },
  "slowtask_effect": {
    "current_plan_version_at_arrival": 2,
    "should_mark_stale": true,
    "may_advance_current_task": false,
    "requires_explicit_adopt_or_rebase": true
  },
  "privacy": {
    "raw_trace_stored": false,
    "real_user_input_stored": false,
    "secret_material_stored": false,
    "deterministic_replay_reruns_provider": false
  }
}
```

Event-shaped observations can be represented separately:

```json
{
  "schema_version": "slow_llm_event_shape_observation.v1",
  "case_id": "weak_schema_validation_failure",
  "event_name": "ADAPTER_OUTPUT_VALIDATION_FAILED",
  "event_owner": "Adapter / Schema Validator",
  "required_fields_present": true,
  "payload": {
    "adapter_id": "adapter_synthetic_slow_llm_qwen",
    "adapter_type": "slow_llm",
    "adapter_request_id": "adapter_req_synthetic_002",
    "schema_name": "slow_llm_plan.synthetic.v1",
    "failure_reasons": ["missing_required_field:resolved_arguments"],
    "output_mode": "degraded"
  },
  "raw_provider_body_required_for_replay": false
}
```

## Structured JSON Validation Checks

The future eval should verify:

- Parse failure and schema failure are separate categories.
- Local schema validation happens before SlowTask consumption.
- Invalid output is never used to create `ARGUMENTS_RESOLVED`, `SEMANTIC_COMMITMENT_EMITTED`, or tool execution events.
- Validation failure records `adapter_id`, `adapter_type`, `adapter_request_id`, `schema_name`, failure reasons, and output mode.
- Repair prompts use validation errors as metadata and do not include raw sensitive provider bodies.
- A final valid output is still only evidence until SlowTask Runtime reviews and accepts it.

## Retry Checks

Retry proof should cover:

- Retryable schema failure.
- Retryable provider failure.
- Retryable timeout.
- Non-retryable failure.
- Retry budget exhausted.
- Duplicate or conflicting retry result.

Required metadata:

- `adapter_request_id` or attempt id.
- `retry_count`.
- `retry_reason`.
- optional timeout bound.
- final result category.
- causal link from the failed attempt to the retry.
- explicit `may_advance_current_task=false` until validation and SlowTask acceptance.

Retry must be bounded. Retry must not create duplicate SlowTask state transitions or duplicate tool proposals. A retry result must retain task binding and be compared against the current plan at arrival time.

## Cancellation / Timeout / Late Result Checks

The eval must distinguish:

| Observation class | Label guidance | Required metadata | Forbidden interpretation |
| --- | --- | --- | --- |
| Client timeout | `observed_degraded` if reproduced | timeout bound, adapter request id, retryable flag | Do not treat as provider cancellation. |
| Client abort | `observed_degraded` or `unknown` | abort reason, partial result flag | Do not report cancellation success. |
| Provider-confirmed cancellation | `observed_real` only with explicit confirmation | cancellation request ref, provider confirmation flag | Do not infer from connection close. |
| Late same-plan output | `observed_real` only if validated | original task binding, current plan unchanged | Still requires SlowTask review before state update. |
| Late old-plan output | stale by default | original plan version, current plan version, stale reason | Must not advance current task. |
| Late output after terminal task | stale/debug only | terminal state at arrival, result ref | Must not reopen terminal task. |
| Partial streaming output | degraded/unknown until validated | chunk count, final validation status | Must not partially update task facts. |

Any adapter that cannot prove cancellation must wait for or ignore late output according to stale policy. It must not invent cancellation success.

## Plan Version / Stale Result Checks

Every Slow LLM request and result intended for task planning must carry:

- `task_id`
- `plan_version`
- `task_event_seq`
- `adapter_request_id`
- causal source refs

Required stale result patterns:

- If `result.plan_version == current.plan_version`, validated output can be reviewed by SlowTask Runtime.
- If `result.plan_version < current.plan_version`, output must be marked stale.
- If the task is terminal, output is stale/debug metadata only.
- If stale output is reused, SlowTask must explicitly record adopt/rebase metadata.

Adoption proof should include:

- stale evidence ref,
- source result event/ref,
- adopted-from plan version,
- current plan version,
- adoption mode,
- adopted scope,
- adoption reason,
- adopting event id.

Without explicit adoption, old output cannot update resolved arguments, tool proposals, confirmation state, SemanticCommitment, or task status.

## Tool Proposal / Confirmation Boundary Checks

Slow LLM output may propose tool-like actions only as evidence.

The eval should verify:

- Tool-like output is normalized to a `tool_call_proposal`-style object.
- Tool Executor remains the owner of manifest checks, arguments, idempotency, retry, failure, cancellation, UI state patching, and execution.
- `DEMO_DESTRUCTIVE_ACTION` proposals require current-plan confirmation before execution.
- Missing/ambiguous arguments block execution.
- Model text cannot create `TOOL_EXECUTION_STARTED`, `TOOL_UI_STATE_PATCHED`, `CONFIRMATION_ACCEPTED`, or terminal task state.
- Provider-native tool features, if tested later, must be normalized and never directly executed.

## Web Evidence Boundary Checks

Synthetic web/RAG evidence must remain evidence, not instruction.

The eval should verify:

- Evidence refs are marked untrusted where appropriate.
- Instruction-like text inside evidence does not alter schema, retry, tool, confirmation, trace, or repository rules.
- Retry prompts do not accidentally move untrusted evidence into instruction space.
- The model must preserve uncertainty rather than using external evidence as authority.
- Replay-safe reports store only refs, summaries, and validation results.

## Replay-Safe Metadata Shape

Deterministic replay must not rerun Qwen, DeepSeek, or any real Slow LLM provider. It should consume recorded metadata or synthetic fixtures.

Recommended proof summary shape:

```json
{
  "proof_report_id": "slow_llm_retry_cancellation_eval_2026_05_12",
  "contract_snapshot": "main@61e6afc",
  "candidate": {
    "provider": "dashscope",
    "model_name_observed": "qwen3.6-plus",
    "endpoint_ref": "dashscope-compatible-chat-completions"
  },
  "case_results": [
    {
      "case_id": "bounded_schema_repair_success",
      "capability_labels": {
        "structured_json": "observed_real",
        "local_validation": "observed_real",
        "bounded_repair": "observed_real",
        "provider_confirmed_cancellation": "unknown",
        "streaming_json": "docs_only_unobserved"
      },
      "task_binding_required": true,
      "raw_provider_body_stored": false,
      "may_advance_current_task_without_slowtask_review": false
    }
  ],
  "replay": {
    "deterministic_replay_reruns_provider": false,
    "uses_recorded_metadata_or_synthetic_fixture": true,
    "old_plan_result_requires_adoption": true
  }
}
```

Recommended JSONL line types:

- `adapter_request_observation`
- `adapter_retry_observation`
- `adapter_validation_observation`
- `adapter_timeout_observation`
- `adapter_cancellation_observation`
- `late_result_observation`
- `stale_result_event_shape`
- `tool_proposal_boundary_observation`
- `privacy_review`
- `case_verdict`

## Trace / Privacy Boundary

- Store only metadata, validation summaries, synthetic refs, latency buckets, retry counts, failure categories, and redacted error summaries.
- Do not store raw provider bodies, raw traces, local replay cache, real user input, or secret-bearing request metadata.
- Do not store provider request/response files in repo-visible locations.
- Use synthetic ids and invented task content.
- Shareable output must be synthetic / redacted / minimal.
- Deterministic replay does not rerun the provider.

## Fit to MVP-0 / MVP-1 / MVP-2 / MVP-3

| Slice | Fit | Notes |
| --- | --- | --- |
| MVP-0 | Supportive, not required | Eval output maps to adapter capability and replay-safe metadata, while MVP-0 remains mock/runtime-only. |
| MVP-1 | Strongly relevant | Retry, cancellation, plan version, and stale evidence proof are prerequisites for safe SlowTask hardening. |
| MVP-2 | Strongly relevant for demo tools | Tool proposal and confirmation boundaries protect Tool Executor and demo sandbox rules. |
| MVP-3 | Candidate after hardening | Qwen is promising, but needs cancellation, provider failure, streaming JSON, larger schema, and stale-result eval evidence before integration consideration. |

## Risks / Gaps

- Provider-confirmed cancellation is still unknown.
- Streaming structured JSON is not observed.
- Provider-side errors and retry behavior are under-tested.
- Larger schemas and longer evidence packs may break JSON stability.
- Context/output limits must be rechecked on the hardening day.
- Late result behavior is not directly proven.
- Stale adoption/rebase shape has not been exercised.
- Tool proposal output can be misread as execution if boundaries are not explicit.
- DeepSeek comparison remains unobserved in this environment.
- No replay/eval fixture has been created from these observations yet.

## Recommendation

Keep DashScope / Bailian Qwen on the Slow LLM shortlist as the strongest current structured JSON planning candidate, with conservative labels:

- Mark structured JSON, local validation, missing-evidence behavior, conflict preservation, schema-level tool proposal, and bounded schema repair as `observed_real`.
- Mark client timeout as `observed_degraded`.
- Mark provider-confirmed cancellation, provider failure retry behavior, streaming JSON usability, late-result handling, and stale adoption as `unknown` until directly proven.
- Keep DeepSeek as comparison-only until a live run exists.

Do not integrate into runtime in this step. Do not let raw model output own SlowTask state, confirmation, tool authorization, UI mutation, terminal outcome, or stale-result adoption.

## Next Implementation Step, gated on human approval

If a human approves a follow-up implementation thread, create only a spike-local eval path, for example:

```text
tools/model_spikes/slow_llm_retry_eval/
```

The approved follow-up should emit metadata-only JSONL, validate observation shape, use synthetic task inputs, keep provider bodies out of repo-visible artifacts, and write a run report under `docs/research/spikes/`. It must not modify `src/voice_agent/`, `tests/`, `docs/adr/`, or `docs/specs/`, and it must not call providers unless human explicitly approves that run.

Until that approval exists, this thread stops at the eval plan.
